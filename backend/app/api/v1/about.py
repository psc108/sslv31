"""About page — a single, admin-editable page crediting every open-source
product LabTool is built on. Readable by anyone signed in; only admins can
edit it, since it's meant to be updated deliberately (e.g. after adding a
new dependency), not something every operator should be able to change.

Two forms of history, both populated automatically whenever the page
changes:

  - `about_page_versions` — a full-content backup, archived immediately
    before every overwrite (manual edit, regenerate, or restore), so a bad
    edit or a regenerate that got something wrong is never destructive.
    Restorable via POST /history/{id}/restore.
  - `about_version_changes` — a structured "package X: 1.2.3 -> 1.3.0"
    changelog, populated only by regenerate_about() (the only path with
    real per-package detected versions to diff), same from/to shape as
    JAR Analyser's own JarDiffReport dependency diffs."""

import difflib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import AuthContext, require_role
from app.models.about import AboutPage, AboutPageVersion, AboutVersionChange
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/about", tags=["About"])

_ROLES = ("admin", "operator", "auditor", "readonly")


async def _get_or_create(db: AsyncSession) -> AboutPage:
    """Fetch the single global About row, creating an empty one if
    somehow missing (e.g. a downgrade/upgrade cycle) — mirrors
    BMSettings/CategoryRule's own get_or_create shape, even though the
    normal path is migration 089's seeded row, not this fallback."""
    row = (await db.execute(select(AboutPage).where(AboutPage.id == "global"))).scalar_one_or_none()
    if row is None:
        row = AboutPage(id="global", content="")
        db.add(row)
        await db.flush()
    return row


async def _archive_current(db: AsyncSession, row: AboutPage, source: str) -> None:
    """Snapshots the row's *current* content into about_page_versions
    before the caller overwrites it. A no-op for an empty/never-edited
    page (nothing worth backing up yet) — otherwise every fresh install's
    first regenerate would archive a blank placeholder row."""
    if not row.content:
        return
    db.add(AboutPageVersion(
        content=row.content, updated_by=row.updated_by,
        updated_at=row.updated_at, source=source,
    ))


def _about_dict(row: AboutPage) -> dict[str, Any]:
    return {
        "content": row.content,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _version_dict(v: AboutPageVersion) -> dict[str, Any]:
    return {
        "id": v.id, "updated_by": v.updated_by,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
        "archived_at": v.archived_at.isoformat() if v.archived_at else None,
        "source": v.source, "content_length": len(v.content),
    }


def _change_dict(c: AboutVersionChange) -> dict[str, Any]:
    return {
        "id": c.id, "package_key": c.package_key, "display_name": c.display_name,
        "old_version": c.old_version, "new_version": c.new_version,
        "detected_at": c.detected_at.isoformat() if c.detected_at else None,
    }


@router.get("")
async def get_about(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    row = await _get_or_create(db)
    await db.commit()
    return _about_dict(row)


class AboutUpdate(BaseModel):
    content: str = Field(min_length=1)


@router.put("")
async def update_about(
    body: AboutUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    row = await _get_or_create(db)
    await _archive_current(db, row, "manual_edit")
    row.content = body.content
    row.updated_by = auth.username
    row.updated_at = datetime.now(timezone.utc)

    await audit_event(
        db=db, event_type="ABOUT_PAGE_UPDATED", severity="INFO", request=request,
        subject_type="about_page", subject_id="global",
        detail={"content_length": len(body.content)},
        description=f"About page updated by {auth.username}",
    )

    await db.commit()
    await db.refresh(row)
    return _about_dict(row)


@router.post("/regenerate")
async def regenerate_about(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Rebuilds the page from live-detected dependency versions (pip
    metadata, frontend/package-lock.json, java/nginx/tofu/ansible-galaxy
    --version output, the CFR/Vineflower manifest baked in at Docker build
    time — see about_generator.py for the detection detail) rather than an
    admin hand-transcribing them. Same effect as a manual PUT otherwise:
    overwrites content, stamps updated_by/updated_at, audit-logged — plus
    two things a manual edit doesn't do: archives the previous content
    (same as any overwrite) and diffs the freshly-detected versions
    against the last regenerate's, recording an AboutVersionChange row for
    anything that moved (or is newly detected) — the structured changelog
    surfaced via GET /about/changelog."""
    from app.services.about_generator import (
        detect_all_versions, display_name_for, flatten_versions, render_about_markdown,
    )
    row = await _get_or_create(db)
    await _archive_current(db, row, "regenerate")

    detected = detect_all_versions()
    new_versions = flatten_versions(detected)
    old_versions: dict[str, str] = json.loads(row.last_versions_json) if row.last_versions_json else {}

    changes = 0
    for key, new_value in new_versions.items():
        old_value = old_versions.get(key)
        if old_value != new_value:
            db.add(AboutVersionChange(
                package_key=key, display_name=display_name_for(key),
                old_version=old_value, new_version=new_value,
            ))
            changes += 1

    row.content = render_about_markdown(detected)
    row.last_versions_json = json.dumps(new_versions)
    row.updated_by = auth.username
    row.updated_at = datetime.now(timezone.utc)

    await audit_event(
        db=db, event_type="ABOUT_PAGE_REGENERATED", severity="INFO", request=request,
        subject_type="about_page", subject_id="global",
        detail={"content_length": len(row.content), "version_changes": changes},
        description=f"About page regenerated from detected versions by {auth.username} ({changes} version change(s))",
    )

    await db.commit()
    await db.refresh(row)
    return _about_dict(row)


@router.get("/history")
async def list_about_history(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> list[dict[str, Any]]:
    """Archived content snapshots, newest first — a summary list (no
    content body, same "brief list, fetch one for the body" shape as
    docs.py's GET /{doc_id}/versions) for the History picker."""
    rows = (await db.execute(
        select(AboutPageVersion).order_by(AboutPageVersion.archived_at.desc())
    )).scalars().all()
    return [_version_dict(v) for v in rows]


@router.get("/history/{version_id}")
async def get_about_history_entry(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    v = (await db.execute(select(AboutPageVersion).where(AboutPageVersion.id == version_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    d = _version_dict(v)
    d["content"] = v.content
    return d


@router.get("/history/{version_id}/diff")
async def diff_about_history_entry(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    """Line diff (stdlib difflib, same shape as docs.py's own /{doc_id}/diff)
    between a snapshot and whatever content superseded it. Deliberately no
    "against" parameter to pick like Docs has — for an inline expand next to
    a History row, the only diff worth showing without extra clicks is "what
    did the action on *this* row actually change", i.e. this snapshot's
    content versus the content that replaced it: the next-younger archived
    snapshot if one exists, or the page's current live content if this is
    the newest snapshot on file."""
    v = (await db.execute(select(AboutPageVersion).where(AboutPageVersion.id == version_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    next_v = (await db.execute(
        select(AboutPageVersion)
        .where(AboutPageVersion.archived_at > v.archived_at)
        .order_by(AboutPageVersion.archived_at.asc())
        .limit(1)
    )).scalar_one_or_none()
    if next_v:
        after_content = next_v.content
        after_meta = _version_dict(next_v)
    else:
        row = await _get_or_create(db)
        await db.commit()
        after_content = row.content
        after_meta = _about_dict(row)

    lines_a = v.content.splitlines()
    lines_b = after_content.splitlines()
    rows: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, lines_a, lines_b).get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                rows.append({"tag": "equal", "a_line": i1 + offset + 1, "b_line": j1 + offset + 1, "text": lines_a[i1 + offset]})
        else:
            for k in range(i1, i2):
                rows.append({"tag": "delete", "a_line": k + 1, "b_line": None, "text": lines_a[k]})
            for k in range(j1, j2):
                rows.append({"tag": "insert", "a_line": None, "b_line": k + 1, "text": lines_b[k]})

    return {
        "before": _version_dict(v),
        "after": after_meta,
        "added": sum(1 for r in rows if r["tag"] == "insert"),
        "removed": sum(1 for r in rows if r["tag"] == "delete"),
        "rows": rows,
    }


@router.post("/history/{version_id}/restore")
async def restore_about_history_entry(
    version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Makes an archived snapshot current again — the "undo" half of the
    backup-before-every-overwrite safety net. Archives whatever's current
    right now first (source="restore"), same as any other overwrite, so a
    restore is itself undoable rather than a one-way trip."""
    v = (await db.execute(select(AboutPageVersion).where(AboutPageVersion.id == version_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    row = await _get_or_create(db)
    await _archive_current(db, row, "restore")
    row.content = v.content
    row.updated_by = auth.username
    row.updated_at = datetime.now(timezone.utc)

    await audit_event(
        db=db, event_type="ABOUT_PAGE_RESTORED", severity="INFO", request=request,
        subject_type="about_page", subject_id="global",
        detail={"restored_version_id": version_id, "originally_from": v.source},
        description=f"About page restored to a snapshot from {v.archived_at.isoformat() if v.archived_at else '?'} by {auth.username}",
    )

    await db.commit()
    await db.refresh(row)
    return _about_dict(row)


@router.get("/changelog")
async def get_about_changelog(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> list[dict[str, Any]]:
    """The structured "package X: 1.2.3 -> 1.3.0" version-change history,
    newest first — populated only by Regenerate (see regenerate_about()'s
    own docstring for why a manual Edit doesn't touch this)."""
    rows = (await db.execute(
        select(AboutVersionChange).order_by(AboutVersionChange.detected_at.desc())
    )).scalars().all()
    return [_change_dict(c) for c in rows]


@router.get("/export/markdown")
async def export_about_markdown(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> PlainTextResponse:
    """Raw markdown export, exactly as stored — same "portability, not a
    rendered view" rationale as docs.py's own export_doc_markdown. Useful
    for feeding into a license-scanning tool or attaching to a review
    ticket without formatting loss."""
    row = await _get_or_create(db)
    await db.commit()
    return PlainTextResponse(
        content=row.content, media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="about.md"'},
    )


@router.get("/export/pdf")
async def export_about_pdf(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> Response:
    """PDF export — same read-gating as viewing the page itself, since
    this is just another way of consuming the same content."""
    row = await _get_or_create(db)
    await db.commit()
    from app.services.docs_export import about_to_pdf
    pdf_bytes = about_to_pdf(
        content=row.content, updated_by=row.updated_by,
        updated_at=row.updated_at.strftime("%Y-%m-%d %H:%M UTC") if row.updated_at else None,
    )
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="about.pdf"'},
    )
