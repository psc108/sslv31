"""Bug Tracker REST API — Stage 1 of the bug tracker plan (see
Documentation/planning/bug_tracker_plan.md).

Bug/Comment CRUD, status-transition history, full-text search. RBAC matches
the Docs tier established earlier: admin = full CRUD (including delete),
operator = create/read/update (no delete), auditor/readonly = read-only.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import AuthContext, require_role
from app.services.audit import audit_event
from app.services.bug_similarity import find_similar_bugs, find_similar_bugs_fts, fts_index_bug, fts_unindex_bug
from app.models.bug_tracker import Bug, BugAttachment, BugComment, BugHistoryEntry, BugOccurrence, BugActivityCheckpoint
from app.models.build_manager import BMJob
from app.models.docs import Doc, DocLibrary, DocShelf
from app.models.jar_analyser import AnalysisReport, SubReport
from app.models.user import User

router = APIRouter(prefix="/api/v1/bugs", tags=["bugs"])

_ROLES = ("admin", "operator", "auditor", "readonly")
_WRITE_ROLES = ("admin", "operator")  # create/update — viewers don't get this
_DELETE_ROLES = ("admin",)  # operator has create+read+update but not delete

# Bug attachments (Improvements Plan Stage 18) — same "DB row + on-disk
# file" split as JAR Analyser's upload storage, but deliberately lighter:
# no content-addressing/dedup, since these are expected to be small,
# per-bug artefacts (screenshots, logs), not large shared binaries.
_ATTACHMENT_DIR = settings.DATA_DIR / "bug_attachments"
_MAX_ATTACHMENT_MB = 25

_STATUSES = ("open", "investigating", "resolved", "closed", "wont-fix")
_SEVERITIES = ("critical", "high", "medium", "low")
_FREQUENCIES = ("always", "intermittent", "one-off")

_STATUS_PATTERN = "^(" + "|".join(_STATUSES) + ")$"
_SEVERITY_PATTERN = "^(" + "|".join(_SEVERITIES) + ")$"
_FREQUENCY_PATTERN = "^(" + "|".join(_FREQUENCIES) + ")$"


# ---------------------------------------------------------------------------
# Tenant-scoped lookups
# ---------------------------------------------------------------------------

async def _get_bug_or_404(db: AsyncSession, bug_id: str, auth: AuthContext) -> Bug:
    """Excludes soft-deleted bugs (Improvements Plan Stage 7) — a bug in
    Trash is 404 to every normal read/write path; only the dedicated
    trash/restore endpoints below can see or act on it."""
    query = select(Bug).where(Bug.id == bug_id, Bug.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    obj = (await db.execute(query)).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Bug not found")
    return obj


async def _get_comment_or_404(db: AsyncSession, comment_id: str, auth: AuthContext) -> BugComment:
    """Joins through Bug for the tenant check — BugComment has no tenant_id
    column of its own, matching DocAnnotation's pattern for child entities."""
    query = select(BugComment).join(Bug, BugComment.bug_id == Bug.id).where(BugComment.id == comment_id)
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    obj = (await db.execute(query)).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Comment not found")
    return obj


async def _get_occurrence_or_404(db: AsyncSession, occurrence_id: str, auth: AuthContext) -> BugOccurrence:
    """Joins through Bug for the tenant check, same pattern as comments."""
    query = select(BugOccurrence).join(Bug, BugOccurrence.bug_id == Bug.id).where(BugOccurrence.id == occurrence_id)
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    obj = (await db.execute(query)).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    return obj


async def _get_attachment_or_404(db: AsyncSession, attachment_id: str, auth: AuthContext) -> BugAttachment:
    """Joins through Bug for the tenant check, same pattern as comments/occurrences."""
    query = select(BugAttachment).join(Bug, BugAttachment.bug_id == Bug.id).where(BugAttachment.id == attachment_id)
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    obj = (await db.execute(query)).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return obj


async def _validate_report_link(
    db: AsyncSession, auth: AuthContext, report_id: str | None, sub_report_id: str | None
) -> None:
    """A bug's report_id/sub_report_id must point at real, tenant-accessible
    rows — and if both are given, the sub-report must actually belong to
    that report — otherwise a bug could silently link to another tenant's
    report or to a mismatched pair."""
    if report_id is None and sub_report_id is None:
        return
    if report_id is not None:
        query = select(AnalysisReport).where(AnalysisReport.id == report_id)
        if not auth.is_global_admin:
            query = query.where(AnalysisReport.tenant_id == auth.tenant_id)
        report = (await db.execute(query)).scalar_one_or_none()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
    if sub_report_id is not None:
        sub = (await db.execute(
            select(SubReport).where(SubReport.id == sub_report_id)
        )).scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Sub-report not found")
        if report_id is not None and sub.parent_report_id != report_id:
            raise HTTPException(status_code=422, detail="Sub-report does not belong to the given report")


async def _validate_bm_job_link(db: AsyncSession, auth: AuthContext, bm_job_id: str | None) -> None:
    """A bug's bm_job_id must point at a real, tenant-accessible Build
    Manager job (Improvements Plan Stage 19) — same shape as
    _validate_report_link. BMJob.tenant_id is a plain column, not a
    relationship-checked FK, same as everywhere else in this codebase that
    scopes by tenant_id directly."""
    if bm_job_id is None:
        return
    query = select(BMJob).where(BMJob.id == bm_job_id)
    if not auth.is_global_admin:
        query = query.where(BMJob.tenant_id == auth.tenant_id)
    job = (await db.execute(query)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Build Manager job not found")


def _check_origin_exclusive(report_id: str | None, sub_report_id: str | None, bm_job_id: str | None) -> None:
    """A bug (or occurrence) is filed against a JAR Analyser report or a
    Build Manager job, never both at once — enforced here rather than a DB
    constraint (see migration 084's docstring)."""
    if bm_job_id is not None and (report_id is not None or sub_report_id is not None):
        raise HTTPException(status_code=422, detail="A bug/occurrence can be linked to a report or a Build Manager job, not both")


async def _validate_assignee(db: AsyncSession, assignee_id: str | None) -> None:
    """assignee_id must be a real account (Improvements Plan Stage 4) — no
    tenant check needed, User has no tenant_id of its own (see notification.py
    for the same convention)."""
    if assignee_id is None:
        return
    user = (await db.execute(select(User).where(User.id == assignee_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Assignee not found")


async def _assignee_usernames(db: AsyncSession, bugs: list[Bug]) -> dict[str, str]:
    """Batch-resolves assignee_id -> username for a page of bugs in one
    query, rather than N+1 lookups — same shape as resolving report display
    names elsewhere, just kept local since only this module needs it."""
    ids = {b.assignee_id for b in bugs if b.assignee_id}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
    return {uid: uname for uid, uname in rows}


async def _notify_assignee(db: AsyncSession, auth: AuthContext, bug: Bug, assignee_username: str) -> None:
    """Fires bug_assigned — pre-commit, try/except-wrapped, exact shape
    every other notify_event() call site in this codebase uses (see
    certificates.py's cert_issued call). Tagged with the assignee's own
    username; a user only receives this if they've subscribed to
    "Bug Assigned to You" with a matching filter_tag (the Notifications
    page auto-fills this to their own username for bug_* events — see
    NotificationsPage.tsx's subscribe()). Safe to call unconditionally:
    notify_event() itself no-ops entirely when SMTP isn't configured."""
    try:
        from app.services.notification_service import notify_event
        await notify_event(
            db, "bug_assigned", tenant_id=auth.tenant_id, tag=assignee_username,
            bug_title=bug.title, severity=bug.severity, assigned_by=auth.username,
        )
    except Exception:
        pass


async def _notify_relevant(db: AsyncSession, auth: AuthContext, bug: Bug, event_type: str, **template_kwargs: Any) -> None:
    """Fires event_type at whoever's relevant to this bug — its assignee
    and/or its reporter — excluding the acting user themselves (your own
    status change/occurrence link on your own bug isn't news to you).
    Same pre-commit, try/except-wrapped shape as _notify_assignee above;
    used for bug_status_changed and bug_occurrence_linked, which (unlike
    assignment) concern both roles, not just one."""
    usernames = await _assignee_usernames(db, [bug])
    assignee_username = usernames.get(bug.assignee_id or "")
    targets = {u for u in (assignee_username, bug.reporter) if u and u != auth.username}
    if not targets:
        return
    try:
        from app.services.notification_service import notify_event
        for username in targets:
            await notify_event(db, event_type, tenant_id=auth.tenant_id, tag=username, **template_kwargs)
    except Exception:
        pass


def _bug_dict(b: Bug, include_body: bool = True, assignee_username: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": b.id, "title": b.title, "status": b.status, "severity": b.severity,
        "frequency": b.frequency, "tags": json.loads(b.tags_json),
        "report_id": b.report_id, "sub_report_id": b.sub_report_id, "bm_job_id": b.bm_job_id,
        "reporter": b.reporter, "assignee_id": b.assignee_id, "assignee_username": assignee_username,
        "auto_created": b.auto_created,
        "duplicate_of_bug_id": b.duplicate_of_bug_id,
        "created_at": b.created_at.isoformat(), "updated_at": b.updated_at.isoformat(),
    }
    if include_body:
        d["description"] = b.description
        d["resolution"] = b.resolution
    return d


def _comment_dict(c: BugComment) -> dict[str, Any]:
    return {"id": c.id, "bug_id": c.bug_id, "author": c.author, "text": c.text, "created_at": c.created_at.isoformat()}


def _history_dict(h: BugHistoryEntry) -> dict[str, Any]:
    return {
        "id": h.id, "bug_id": h.bug_id, "action": h.action,
        "from_status": h.from_status, "to_status": h.to_status,
        "note": h.note, "actor": h.actor, "created_at": h.created_at.isoformat(),
    }


def _attachment_dict(a: BugAttachment) -> dict[str, Any]:
    return {
        "id": a.id, "bug_id": a.bug_id, "filename": a.filename,
        "size_bytes": a.size_bytes, "content_type": a.content_type,
        "uploaded_by": a.uploaded_by, "created_at": a.created_at.isoformat(),
    }


def _occurrence_dict(o: BugOccurrence) -> dict[str, Any]:
    return {
        "id": o.id, "bug_id": o.bug_id, "report_id": o.report_id, "sub_report_id": o.sub_report_id,
        "bm_job_id": o.bm_job_id,
        "note": o.note, "noted_by": o.noted_by, "created_at": o.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# FTS5 index maintenance — Improvements Plan Stage 11. SQLite-only (see
# migration 078's docstring); every call is a silent no-op on Postgres/
# MySQL, where search_bugs()/similar candidates fall back to ILIKE and the
# word-overlap scorer below instead. tags stored as the raw JSON array
# string — FTS5's default tokenizer splits on the brackets/quotes/commas
# anyway, so "["urgent","backend"]" tokenises into "urgent", "backend"
# with no extra parsing needed at every call site.
# ---------------------------------------------------------------------------

# Thin aliases — the actual implementation lives in bug_similarity.py so
# bug_pattern_scan.py (a services module) can keep its own bugs_fts index
# in sync without importing a private name out of an api/v1 file.
_fts_index_bug = fts_index_bug
_fts_unindex_bug = fts_unindex_bug


# ---------------------------------------------------------------------------
# Duplicate-suggestion assist — used while filing a new bug to surface "this
# looks like an existing one — link this report as an occurrence instead?"
# candidates. Scoring itself lives in app.services.bug_similarity (moved
# there for Improvements Plan Stage 12, so JAR Analyser's cross-report bug
# pattern scan can reuse the exact same ranking without importing this
# api/v1 module).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Bugs
# ---------------------------------------------------------------------------

class BugCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    description: str = ""
    severity: str = Field(default="medium", pattern=_SEVERITY_PATTERN)
    frequency: str | None = Field(default=None, pattern=_FREQUENCY_PATTERN)
    tags: list[str] = []
    report_id: str | None = None
    sub_report_id: str | None = None
    bm_job_id: str | None = None
    assignee_id: str | None = None


class BugUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = None
    severity: str | None = Field(default=None, pattern=_SEVERITY_PATTERN)
    frequency: str | None = Field(default=None, pattern=_FREQUENCY_PATTERN)
    tags: list[str] | None = None
    report_id: str | None = None
    sub_report_id: str | None = None
    bm_job_id: str | None = None
    assignee_id: str | None = None
    resolution: str | None = None


class BugStatusUpdate(BaseModel):
    status: str = Field(pattern=_STATUS_PATTERN)
    note: str | None = None


# Registered before the greedy "/{bug_id}" route below — Starlette matches
# routes in registration order, so "/search" would otherwise be swallowed as
# bug_id="search" (the same class of bug already hit twice this session on
# docs.py and jar_analyser.py's decompiled-class routes).
@router.get("/search")
async def search_bugs(
    q: str = Query(min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    query = select(Bug).where(Bug.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)

    if settings.is_sqlite:
        terms = re.findall(r"\w+", q)
        match_q = " ".join(f'"{t}"*' for t in terms) if terms else '""'
        fts_rows = (await db.execute(
            text(
                "SELECT id, snippet(bugs_fts, 2, '**', '**', '…', 16) AS snip FROM bugs_fts "
                "WHERE bugs_fts MATCH :match ORDER BY bm25(bugs_fts) LIMIT 1000"
            ),
            {"match": match_q},
        )).all()
        ranked_ids = [r.id for r in fts_rows]
        snippet_by_id = {r.id: r.snip for r in fts_rows}
        if not ranked_ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 1}
        query = query.where(Bug.id.in_(ranked_ids))
        all_rows = (await db.execute(query)).scalars().all()
        rank_index = {rid: i for i, rid in enumerate(ranked_ids)}
        all_rows = sorted(all_rows, key=lambda r: rank_index.get(r.id, len(ranked_ids)))
        total = len(all_rows)
        start = (page - 1) * page_size
        rows = all_rows[start:start + page_size]
        items = [
            {**_bug_dict(r, include_body=False), "snippet": snippet_by_id.get(r.id)}
            for r in rows
        ]
    else:
        like = f"%{q}%"
        query = query.where(Bug.title.ilike(like) | Bug.description.ilike(like) | Bug.tags_json.ilike(like))
        total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
        rows = (await db.execute(
            query.order_by(Bug.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()
        items = [_bug_dict(r, include_body=False) for r in rows]

    return {
        "items": items,
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


# Also registered before "/{bug_id}" for the same reason as "/search" above.
@router.get("/similar")
async def similar_bugs(
    title: str = Query(default=""),
    text: str = Query(default=""),
    limit: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    query = select(Bug).where(Bug.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)

    if settings.is_sqlite:
        candidate_ids = await find_similar_bugs_fts(db, title, text, limit)
        if not candidate_ids:
            return {"results": []}
        query = query.where(Bug.id.in_(candidate_ids))
        bugs = (await db.execute(query)).scalars().all()
        rank_index = {bid: i for i, bid in enumerate(candidate_ids)}
        matches = sorted(bugs, key=lambda b: rank_index.get(b.id, len(candidate_ids)))[:limit]
    else:
        bugs = (await db.execute(query)).scalars().all()
        matches = find_similar_bugs(title, text, list(bugs), limit)

    return {"results": [_bug_dict(b, include_body=False) for b in matches]}


# Also registered before "/{bug_id}" for the same reason as "/search" above.
@router.get("/dashboard")
async def bug_dashboard(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    bug_query = select(Bug).where(Bug.deleted_at.is_(None))
    if not auth.is_global_admin:
        bug_query = bug_query.where(Bug.tenant_id == auth.tenant_id)
    bugs = (await db.execute(bug_query)).scalars().all()

    by_status = {s: 0 for s in _STATUSES}
    open_by_severity = {s: 0 for s in _SEVERITIES}
    # Improvements Plan enhancement — "collect first, decide later" (Stage
    # 22's own framing) needs a real triage queue, not just a badge on
    # individual rows: still-open bugs nobody has acted on yet (a status
    # change to investigating/resolved/etc. counts as "acted on", even if
    # nobody's touched the auto_created flag itself, which never changes).
    auto_filed_open_count = 0
    for b in bugs:
        by_status[b.status] = by_status.get(b.status, 0) + 1
        if b.status in ("open", "investigating"):
            open_by_severity[b.severity] = open_by_severity.get(b.severity, 0) + 1
        if b.auto_created and b.status == "open":
            auto_filed_open_count += 1

    bug_ids = [b.id for b in bugs]
    created_at_by_id = {b.id: b.created_at for b in bugs}

    # Average resolution time: created_at -> the *first* status_change to
    # "resolved" for each bug (a bug can later flip out of resolved again;
    # only the initial resolution is what "time to resolve" means here).
    avg_resolution_hours: float | None = None
    if bug_ids:
        resolved_entries = (await db.execute(
            select(BugHistoryEntry.bug_id, BugHistoryEntry.created_at)
            .where(BugHistoryEntry.bug_id.in_(bug_ids), BugHistoryEntry.to_status == "resolved")
            .order_by(BugHistoryEntry.created_at)
        )).all()
        first_resolved: dict[str, datetime] = {}
        for bug_id, ts in resolved_entries:
            first_resolved.setdefault(bug_id, ts)
        if first_resolved:
            deltas = [
                (ts - created_at_by_id[bug_id]).total_seconds() / 3600.0
                for bug_id, ts in first_resolved.items()
                if bug_id in created_at_by_id
            ]
            if deltas:
                avg_resolution_hours = sum(deltas) / len(deltas)

    # Top affected reports: a report's count is the number of *distinct*
    # bugs that touch it via the primary link or a BugOccurrence — same
    # "primary + occurrences" definition Stage 4 already uses for the
    # per-report "N known bugs" badge.
    report_bugs: dict[str, set[str]] = {}
    for b in bugs:
        if b.report_id:
            report_bugs.setdefault(b.report_id, set()).add(b.id)
    if bug_ids:
        occ_rows = (await db.execute(
            select(BugOccurrence.report_id, BugOccurrence.bug_id).where(BugOccurrence.bug_id.in_(bug_ids))
        )).all()
        for report_id, bug_id in occ_rows:
            # A job-origin occurrence (Stage 19) has report_id = None — this
            # stat is report-specific, so it's excluded here rather than
            # poisoning the dict with a None key (which crashed the
            # frontend's TopReportRow, which assumes every report_id is a
            # real string it can .slice() for a fallback display).
            if report_id is None:
                continue
            report_bugs.setdefault(report_id, set()).add(bug_id)

    top_reports = sorted(
        ({"report_id": rid, "bug_count": len(ids)} for rid, ids in report_bugs.items()),
        key=lambda r: -r["bug_count"],
    )[:10]

    return {
        "total": len(bugs),
        "by_status": by_status,
        "open_by_severity": open_by_severity,
        "avg_resolution_hours": avg_resolution_hours,
        "top_reports": top_reports,
        "auto_filed_open_count": auto_filed_open_count,
    }


# Also registered before "/{bug_id}" for the same reason as "/search" above.
@router.get("/export")
async def export_bugs(
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    report_id: str | None = Query(default=None),
    sub_report_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> PlainTextResponse:
    # Same filters as list_bugs (including the primary-or-occurrence report
    # match), just unpaginated — this exports whatever set the user is
    # currently looking at in the list view.
    query = select(Bug).where(Bug.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    if status_filter:
        query = query.where(Bug.status == status_filter)
    if severity:
        query = query.where(Bug.severity == severity)
    if report_id:
        occ_reports = select(BugOccurrence.bug_id).where(BugOccurrence.report_id == report_id)
        query = query.where((Bug.report_id == report_id) | Bug.id.in_(occ_reports))
    if sub_report_id:
        occ_subs = select(BugOccurrence.bug_id).where(BugOccurrence.sub_report_id == sub_report_id)
        query = query.where((Bug.sub_report_id == sub_report_id) | Bug.id.in_(occ_subs))
    if tag:
        query = query.where(Bug.tags_json.ilike(f'%"{tag}"%'))

    bugs = (await db.execute(query.order_by(Bug.severity, Bug.created_at))).scalars().all()
    usernames = await _assignee_usernames(db, list(bugs))

    lines = ["# Bug Tracker Export", "", f"_{len(bugs)} bug(s), generated {datetime.now(timezone.utc).isoformat()}_", ""]
    for b in bugs:
        lines.append(f"## {b.title}")
        tags = json.loads(b.tags_json)
        meta = [f"**Status:** {b.status}", f"**Severity:** {b.severity}"]
        if b.frequency:
            meta.append(f"**Frequency:** {b.frequency}")
        if tags:
            meta.append(f"**Tags:** {', '.join(tags)}")
        if b.assignee_id and usernames.get(b.assignee_id):
            meta.append(f"**Assignee:** {usernames[b.assignee_id]}")
        meta.append(f"**Reporter:** {b.reporter or 'unknown'}")
        meta.append(f"**Created:** {b.created_at.isoformat()}")
        lines.append(" | ".join(meta))
        lines.append("")
        if b.report_id:
            ref = f"**Filed against report:** `{b.report_id}`"
            if b.sub_report_id:
                ref += f" (sub-report `{b.sub_report_id}`)"
            lines.append(ref)
            lines.append("")
        elif b.bm_job_id:
            lines.append(f"**Filed against Build Manager job:** `{b.bm_job_id}`")
            lines.append("")
        if b.description:
            lines.append("### Description")
            lines.append(b.description)
            lines.append("")
        if b.resolution:
            lines.append("### Resolution")
            lines.append(b.resolution)
            lines.append("")
        lines.append("---")
        lines.append("")

    content = "\n".join(lines)
    return PlainTextResponse(
        content=content, media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="bugs-export.md"'},
    )


# Also registered before "/{bug_id}" for the same reason as "/search" above.
# Write-role gated — only people who can actually assign a bug need the
# picker list; User has no tenant_id of its own so there's nothing to
# scope this by (Improvements Plan Stage 4).
@router.get("/assignable-users")
async def assignable_users(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(User.id, User.username).where(User.active.is_(True)).order_by(User.username)
    )).all()
    return [{"id": uid, "username": uname} for uid, uname in rows]


# ---------------------------------------------------------------------------
# In-app activity badge — Improvements Plan Stage 5. Distinct from the email
# notifications above: this is a purely in-app "N bugs need your attention"
# signal that works regardless of whether SMTP is configured, backed by a
# single per-user checkpoint timestamp rather than a real notification feed.
# Both registered before "/{bug_id}" for the same reason as "/search" above.
# ---------------------------------------------------------------------------

_ACTIVITY_ACTIONS = ("status_change", "occurrence_linked", "occurrence_unlinked", "comment")


@router.get("/my-activity-count")
async def my_activity_count(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, int]:
    checkpoint = await db.get(BugActivityCheckpoint, auth.user_id)
    if not checkpoint:
        # Never checked before — nothing is "new" yet rather than dumping
        # a potentially large, confusing backlog count on first visit.
        # Opening the Bug Tracker sets a checkpoint (see below), so this
        # is a one-time state, not a way to permanently hide activity.
        return {"count": 0}

    my_bug_ids = select(Bug.id).where(
        Bug.deleted_at.is_(None), (Bug.assignee_id == auth.user_id) | (Bug.reporter == auth.username)
    )
    if not auth.is_global_admin:
        my_bug_ids = my_bug_ids.where(Bug.tenant_id == auth.tenant_id)

    count = (await db.execute(
        select(func.count()).select_from(BugHistoryEntry).where(
            BugHistoryEntry.bug_id.in_(my_bug_ids),
            BugHistoryEntry.created_at > checkpoint.checked_at,
            BugHistoryEntry.action.in_(_ACTIVITY_ACTIONS),
            BugHistoryEntry.actor != auth.username,
        )
    )).scalar() or 0
    return {"count": count}


@router.post("/my-activity-checkpoint")
async def mark_activity_seen(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    checkpoint = await db.get(BugActivityCheckpoint, auth.user_id)
    if checkpoint:
        checkpoint.checked_at = now
    else:
        db.add(BugActivityCheckpoint(user_id=auth.user_id, checked_at=now))
    await db.commit()
    return {"checked_at": now.isoformat()}


# Trash listing — Improvements Plan Stage 7. Also registered before
# "/{bug_id}" for the same reason as "/search" above.
@router.get("/trash")
async def list_bug_trash(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> list[dict[str, Any]]:
    query = select(Bug).where(Bug.deleted_at.is_not(None)).order_by(Bug.deleted_at.desc())
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    rows = (await db.execute(query)).scalars().all()
    return [
        {
            "id": b.id, "title": b.title, "severity": b.severity, "status": b.status,
            "reporter": b.reporter, "deleted_at": b.deleted_at.isoformat(),
        }
        for b in rows
    ]


# ---------------------------------------------------------------------------
# Bulk actions — Improvements Plan Stage 9. Checkbox-selection from the list
# view; every action here processes each id independently (not
# all-or-nothing), returning which ones succeeded and which were skipped,
# since a single conflicting/missing id shouldn't sink the whole batch. Also
# registered before "/{bug_id}" for the same reason as "/search" above.
# ---------------------------------------------------------------------------

class BulkStatusUpdate(BaseModel):
    bug_ids: list[str] = Field(min_length=1, max_length=200)
    status: str = Field(pattern=_STATUS_PATTERN)
    note: str | None = None


@router.post("/bulk/status")
async def bulk_update_status(
    body: BulkStatusUpdate,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    query = select(Bug).where(Bug.id.in_(body.bug_ids), Bug.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    bugs = (await db.execute(query)).scalars().all()
    found_ids = {b.id for b in bugs}

    for bug in bugs:
        from_status = bug.status
        bug.status = body.status
        bug.updated_at = datetime.now(timezone.utc)
        db.add(BugHistoryEntry(
            bug_id=bug.id, action="status_change", from_status=from_status, to_status=body.status,
            note=body.note, actor=auth.username,
        ))
        await _notify_relevant(
            db, auth, bug, "bug_status_changed",
            bug_title=bug.title, from_status=from_status, to_status=body.status, changed_by=auth.username,
        )

    await db.commit()
    return {
        "updated": sorted(found_ids),
        "not_found": sorted(set(body.bug_ids) - found_ids),
    }


class BulkTagUpdate(BaseModel):
    bug_ids: list[str] = Field(min_length=1, max_length=200)
    tag: str = Field(min_length=1, max_length=64)
    action: str = Field(pattern="^(add|remove)$")


@router.post("/bulk/tag")
async def bulk_update_tag(
    body: BulkTagUpdate,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    query = select(Bug).where(Bug.id.in_(body.bug_ids), Bug.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    bugs = (await db.execute(query)).scalars().all()
    found_ids = {b.id for b in bugs}

    for bug in bugs:
        tags = set(json.loads(bug.tags_json))
        if body.action == "add":
            tags.add(body.tag)
        else:
            tags.discard(body.tag)
        bug.tags_json = json.dumps(sorted(tags))
        bug.updated_at = datetime.now(timezone.utc)
        await _fts_index_bug(db, bug)

    await db.commit()
    return {
        "updated": sorted(found_ids),
        "not_found": sorted(set(body.bug_ids) - found_ids),
    }


@router.get("")
async def list_bugs(
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    report_id: str | None = Query(default=None),
    sub_report_id: str | None = Query(default=None),
    bm_job_id: str | None = Query(default=None, description="Filter to bugs filed against (or occurring on) a specific Build Manager job — Stage 19"),
    tag: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None, description="Filter to bugs assigned to a specific user — powers the 'My Bugs' view"),
    auto_created: bool | None = Query(default=None, description="Filter to (or exclude) bugs auto-filed by the Ansible-failure scanner — Stage 22"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    query = select(Bug).where(Bug.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    if status_filter:
        query = query.where(Bug.status == status_filter)
    if severity:
        query = query.where(Bug.severity == severity)
    if report_id:
        # Matches the bug's primary report link OR any additional report
        # it's been explicitly linked to via BugOccurrence (Stage 4) — a
        # report's "N known bugs affect this report" figure should count
        # both, not just bugs originally filed against it.
        occ_reports = select(BugOccurrence.bug_id).where(BugOccurrence.report_id == report_id)
        query = query.where((Bug.report_id == report_id) | Bug.id.in_(occ_reports))
    if sub_report_id:
        occ_subs = select(BugOccurrence.bug_id).where(BugOccurrence.sub_report_id == sub_report_id)
        query = query.where((Bug.sub_report_id == sub_report_id) | Bug.id.in_(occ_subs))
    if bm_job_id:
        # Same primary-or-occurrence shape as report_id above.
        occ_jobs = select(BugOccurrence.bug_id).where(BugOccurrence.bm_job_id == bm_job_id)
        query = query.where((Bug.bm_job_id == bm_job_id) | Bug.id.in_(occ_jobs))
    if tag:
        query = query.where(Bug.tags_json.ilike(f'%"{tag}"%'))
    if assignee_id:
        query = query.where(Bug.assignee_id == assignee_id)
    if auto_created is not None:
        query = query.where(Bug.auto_created == auto_created)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(
        query.order_by(Bug.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    usernames = await _assignee_usernames(db, list(rows))
    return {
        "items": [_bug_dict(r, include_body=False, assignee_username=usernames.get(r.assignee_id or "")) for r in rows],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.post("", status_code=201)
async def create_bug(
    body: BugCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    _check_origin_exclusive(body.report_id, body.sub_report_id, body.bm_job_id)
    await _validate_report_link(db, auth, body.report_id, body.sub_report_id)
    await _validate_bm_job_link(db, auth, body.bm_job_id)
    await _validate_assignee(db, body.assignee_id)

    bug = Bug(
        title=body.title, description=body.description, severity=body.severity,
        frequency=body.frequency, tags_json=json.dumps(body.tags),
        report_id=body.report_id, sub_report_id=body.sub_report_id, bm_job_id=body.bm_job_id,
        assignee_id=body.assignee_id, reporter=auth.username, tenant_id=auth.tenant_id,
    )
    db.add(bug)
    await db.flush()
    await _fts_index_bug(db, bug)

    db.add(BugHistoryEntry(bug_id=bug.id, action="created", to_status=bug.status, actor=auth.username))
    await audit_event(
        db=db, event_type="BUG_CREATED", severity="INFO", request=request,
        subject_type="bug", subject_id=bug.id,
        detail={"title": bug.title, "severity": bug.severity}, description=f"Bug filed: {bug.title}",
    )

    usernames = await _assignee_usernames(db, [bug])
    assignee_username = usernames.get(bug.assignee_id or "")
    if assignee_username and assignee_username != auth.username:
        await _notify_assignee(db, auth, bug, assignee_username)

    await db.commit()
    await db.refresh(bug)
    return _bug_dict(bug, assignee_username=assignee_username)


@router.get("/{bug_id}")
async def get_bug(
    bug_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    bug = await _get_bug_or_404(db, bug_id, auth)
    usernames = await _assignee_usernames(db, [bug])
    d = _bug_dict(bug, assignee_username=usernames.get(bug.assignee_id or ""))

    comments = (await db.execute(
        select(BugComment).where(BugComment.bug_id == bug_id).order_by(BugComment.created_at)
    )).scalars().all()
    history = (await db.execute(
        select(BugHistoryEntry).where(BugHistoryEntry.bug_id == bug_id).order_by(BugHistoryEntry.created_at)
    )).scalars().all()
    occurrences = (await db.execute(
        select(BugOccurrence).where(BugOccurrence.bug_id == bug_id).order_by(BugOccurrence.created_at)
    )).scalars().all()
    attachments = (await db.execute(
        select(BugAttachment).where(BugAttachment.bug_id == bug_id).order_by(BugAttachment.created_at)
    )).scalars().all()

    d["comments"] = [_comment_dict(c) for c in comments]
    d["history"] = [_history_dict(h) for h in history]
    d["occurrences"] = [_occurrence_dict(o) for o in occurrences]
    d["attachments"] = [_attachment_dict(a) for a in attachments]

    if bug.duplicate_of_bug_id:
        target = (await db.execute(
            select(Bug).where(Bug.id == bug.duplicate_of_bug_id)
        )).scalar_one_or_none()
        d["duplicate_of_title"] = target.title if target else None

    return d


@router.patch("/{bug_id}")
async def update_bug(
    bug_id: str,
    body: BugUpdate,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    bug = await _get_bug_or_404(db, bug_id, auth)
    old_assignee_id = bug.assignee_id

    new_report_id = body.report_id if body.report_id is not None else bug.report_id
    new_sub_report_id = body.sub_report_id if body.sub_report_id is not None else bug.sub_report_id
    new_bm_job_id = body.bm_job_id if body.bm_job_id is not None else bug.bm_job_id
    if body.report_id is not None or body.sub_report_id is not None or body.bm_job_id is not None:
        _check_origin_exclusive(new_report_id, new_sub_report_id, new_bm_job_id)
        await _validate_report_link(db, auth, new_report_id, new_sub_report_id)
        await _validate_bm_job_link(db, auth, body.bm_job_id)
    if body.assignee_id is not None:
        await _validate_assignee(db, body.assignee_id)

    if body.title is not None:
        bug.title = body.title
    if body.description is not None:
        bug.description = body.description
    if body.severity is not None:
        bug.severity = body.severity
    if body.frequency is not None:
        bug.frequency = body.frequency
    if body.tags is not None:
        bug.tags_json = json.dumps(body.tags)
    if body.report_id is not None:
        bug.report_id = body.report_id
    if body.sub_report_id is not None:
        bug.sub_report_id = body.sub_report_id
    if body.bm_job_id is not None:
        bug.bm_job_id = body.bm_job_id
    if body.assignee_id is not None:
        bug.assignee_id = body.assignee_id
    if body.resolution is not None:
        bug.resolution = body.resolution

    bug.updated_at = datetime.now(timezone.utc)

    if body.title is not None or body.description is not None or body.tags is not None:
        await _fts_index_bug(db, bug)

    usernames = await _assignee_usernames(db, [bug])
    assignee_username = usernames.get(bug.assignee_id or "")
    # Only notify on an actual reassignment to someone new — not every PATCH
    # that happens to repeat the same assignee_id.
    if bug.assignee_id and bug.assignee_id != old_assignee_id and assignee_username and assignee_username != auth.username:
        await _notify_assignee(db, auth, bug, assignee_username)

    await db.commit()
    await db.refresh(bug)
    return _bug_dict(bug, assignee_username=assignee_username)


@router.patch("/{bug_id}/status")
async def update_bug_status(
    bug_id: str,
    body: BugStatusUpdate,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    bug = await _get_bug_or_404(db, bug_id, auth)
    from_status = bug.status
    bug.status = body.status
    bug.updated_at = datetime.now(timezone.utc)
    db.add(BugHistoryEntry(
        bug_id=bug.id, action="status_change", from_status=from_status, to_status=body.status,
        note=body.note, actor=auth.username,
    ))

    await _notify_relevant(
        db, auth, bug, "bug_status_changed",
        bug_title=bug.title, from_status=from_status, to_status=body.status, changed_by=auth.username,
    )

    await db.commit()
    await db.refresh(bug)
    usernames = await _assignee_usernames(db, [bug])
    return _bug_dict(bug, assignee_username=usernames.get(bug.assignee_id or ""))


@router.delete("/{bug_id}", status_code=204)
async def delete_bug(
    bug_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    """Soft-deletes the bug (Improvements Plan Stage 7) — marks deleted_at
    rather than removing the row, so an accidental click is recoverable
    from Trash via POST .../restore, until the background retention sweep
    (app/services/trash_sweep.py) or an explicit DELETE /trash/{id}
    purges it for good."""
    bug = await _get_bug_or_404(db, bug_id, auth)
    bug.deleted_at = datetime.now(timezone.utc)
    await _fts_unindex_bug(db, bug.id)
    await audit_event(
        db=db, event_type="BUG_DELETED", severity="WARNING", request=request,
        subject_type="bug", subject_id=bug.id,
        detail={"title": bug.title}, description=f"Bug moved to rubbish: {bug.title}",
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Trash — Improvements Plan Stage 7. Restore/purge are two-segment routes,
# no ordering issue; the trash listing itself is registered up near the
# other literal-path routes ("/search", "/dashboard", etc.) above, for the
# same reason those are.
# ---------------------------------------------------------------------------

@router.post("/{bug_id}/restore")
async def restore_bug(
    bug_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> dict[str, Any]:
    query = select(Bug).where(Bug.id == bug_id, Bug.deleted_at.is_not(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    bug = (await db.execute(query)).scalar_one_or_none()
    if not bug:
        raise HTTPException(status_code=404, detail="Deleted bug not found in Rubbish")
    bug.deleted_at = None
    await _fts_index_bug(db, bug)
    await audit_event(
        db=db, event_type="BUG_RESTORED", severity="INFO", request=request,
        subject_type="bug", subject_id=bug.id,
        detail={"title": bug.title}, description=f"Bug restored from Rubbish: {bug.title}",
    )
    await db.commit()
    await db.refresh(bug)
    usernames = await _assignee_usernames(db, [bug])
    return _bug_dict(bug, assignee_username=usernames.get(bug.assignee_id or ""))


@router.delete("/trash/{bug_id}", status_code=204)
async def purge_bug(
    bug_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    """Permanent, immediate purge of one Trash entry — the manual half of
    "purged after N days or via an admin empty-trash action"; the
    automatic half is the retention sweep in app/services/trash_sweep.py."""
    query = select(Bug).where(Bug.id == bug_id, Bug.deleted_at.is_not(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    bug = (await db.execute(query)).scalar_one_or_none()
    if not bug:
        raise HTTPException(status_code=404, detail="Deleted bug not found in Rubbish")
    # Already removed at delete-time in the normal case — defensive no-op.
    await _fts_unindex_bug(db, bug.id)
    # ondelete=CASCADE only cleans up the BugAttachment DB rows — the
    # on-disk files are never touched by that, so delete them explicitly
    # before the bug (and its attachment rows) actually go away.
    attachments = (await db.execute(
        select(BugAttachment).where(BugAttachment.bug_id == bug.id)
    )).scalars().all()
    for a in attachments:
        Path(a.stored_path).unlink(missing_ok=True)
    await audit_event(
        db=db, event_type="BUG_PURGED", severity="WARNING", request=request,
        subject_type="bug", subject_id=bug.id,
        detail={"title": bug.title}, description=f"Bug permanently purged from Rubbish: {bug.title}",
    )
    await db.delete(bug)
    await db.commit()


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

class CommentCreate(BaseModel):
    text: str = Field(min_length=1)


@router.post("/{bug_id}/comments", status_code=201)
async def create_comment(
    bug_id: str,
    body: CommentCreate,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    await _get_bug_or_404(db, bug_id, auth)
    comment = BugComment(bug_id=bug_id, author=auth.username, text=body.text)
    db.add(comment)
    db.add(BugHistoryEntry(bug_id=bug_id, action="comment", actor=auth.username))
    await db.commit()
    await db.refresh(comment)
    return _comment_dict(comment)


@router.delete("/{bug_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    bug_id: str,
    comment_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    comment = await _get_comment_or_404(db, comment_id, auth)
    if comment.bug_id != bug_id:
        raise HTTPException(status_code=404, detail="Comment not found")
    await db.delete(comment)
    await db.commit()


# ---------------------------------------------------------------------------
# Attachments — Improvements Plan Stage 18. A screenshot, log file, or other
# artefact attached directly to a bug rather than pasted/described as text.
# No standalone list endpoint, same as comments/occurrences above — the
# full list comes back inline from GET /{bug_id}.
# ---------------------------------------------------------------------------

@router.post("/{bug_id}/attachments", status_code=201)
async def upload_attachment(
    bug_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    await _get_bug_or_404(db, bug_id, auth)
    if not file.filename:
        raise HTTPException(status_code=422, detail="A filename is required")

    bug_dir = _ATTACHMENT_DIR / bug_id
    bug_dir.mkdir(parents=True, exist_ok=True)
    attachment_id = str(uuid.uuid4())
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", file.filename).strip("-") or "attachment"
    stored_path = bug_dir / f"{attachment_id}_{safe_name}"

    max_bytes = _MAX_ATTACHMENT_MB * 1024 * 1024
    size_bytes = 0
    try:
        with stored_path.open("wb") as fout:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    stored_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"File exceeds {_MAX_ATTACHMENT_MB} MB limit")
                fout.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Upload write failed: {e}")

    attachment = BugAttachment(
        id=attachment_id, bug_id=bug_id, filename=file.filename,
        stored_path=str(stored_path), size_bytes=size_bytes,
        content_type=file.content_type, uploaded_by=auth.username,
    )
    db.add(attachment)
    db.add(BugHistoryEntry(bug_id=bug_id, action="attachment_added", note=file.filename, actor=auth.username))
    await audit_event(
        db=db, event_type="BUG_ATTACHMENT_UPLOADED", severity="INFO", request=request,
        subject_type="bug", subject_id=bug_id,
        detail={"filename": file.filename, "size_bytes": size_bytes},
        description=f"Attachment uploaded to bug: {file.filename}",
    )
    await db.commit()
    await db.refresh(attachment)
    return _attachment_dict(attachment)


@router.get("/{bug_id}/attachments/{attachment_id}/download")
async def download_attachment(
    bug_id: str,
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> FileResponse:
    attachment = await _get_attachment_or_404(db, attachment_id, auth)
    if attachment.bug_id != bug_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if not Path(attachment.stored_path).is_file():
        raise HTTPException(status_code=404, detail="Attachment file is missing on disk")
    return FileResponse(
        attachment.stored_path, filename=attachment.filename,
        media_type=attachment.content_type or "application/octet-stream",
    )


@router.delete("/{bug_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    bug_id: str,
    attachment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    attachment = await _get_attachment_or_404(db, attachment_id, auth)
    if attachment.bug_id != bug_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    Path(attachment.stored_path).unlink(missing_ok=True)
    await audit_event(
        db=db, event_type="BUG_ATTACHMENT_DELETED", severity="WARNING", request=request,
        subject_type="bug", subject_id=bug_id,
        detail={"filename": attachment.filename}, description=f"Attachment deleted from bug: {attachment.filename}",
    )
    await db.delete(attachment)
    await db.commit()


# ---------------------------------------------------------------------------
# Occurrences — Stage 4's "find patterns across reports" mechanism. A
# confirmed, human-linked sighting of an existing bug on a report other than
# (or in addition to) its primary one.
# ---------------------------------------------------------------------------

class OccurrenceCreate(BaseModel):
    # Exactly one of report_id or bm_job_id must be set (Improvements Plan
    # Stage 19) — unlike Bug itself, an occurrence's whole purpose is
    # recording *where* it was seen, so "neither" isn't a valid occurrence.
    report_id: str | None = None
    sub_report_id: str | None = None
    bm_job_id: str | None = None
    note: str | None = None


@router.post("/{bug_id}/occurrences", status_code=201)
async def create_occurrence(
    bug_id: str,
    body: OccurrenceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    bug = await _get_bug_or_404(db, bug_id, auth)
    if body.report_id is None and body.bm_job_id is None:
        raise HTTPException(status_code=422, detail="An occurrence must link to either a report or a Build Manager job")
    _check_origin_exclusive(body.report_id, body.sub_report_id, body.bm_job_id)
    await _validate_report_link(db, auth, body.report_id, body.sub_report_id)
    await _validate_bm_job_link(db, auth, body.bm_job_id)

    origin_desc = f"report {body.report_id}" if body.report_id else f"Build Manager job {body.bm_job_id}"

    occurrence = BugOccurrence(
        bug_id=bug_id, report_id=body.report_id, sub_report_id=body.sub_report_id, bm_job_id=body.bm_job_id,
        note=body.note, noted_by=auth.username,
    )
    db.add(occurrence)
    db.add(BugHistoryEntry(
        bug_id=bug_id, action="occurrence_linked", actor=auth.username,
        note=body.note or f"Also seen on {origin_desc}",
    ))
    await audit_event(
        db=db, event_type="BUG_OCCURRENCE_LINKED", severity="INFO", request=request,
        subject_type="bug", subject_id=bug.id,
        detail={"report_id": body.report_id, "sub_report_id": body.sub_report_id, "bm_job_id": body.bm_job_id},
        description=f"Bug '{bug.title}' linked to another {origin_desc}",
    )

    await _notify_relevant(
        db, auth, bug, "bug_occurrence_linked",
        bug_title=bug.title, report_id=origin_desc, linked_by=auth.username,
    )

    await db.commit()
    await db.refresh(occurrence)
    return _occurrence_dict(occurrence)


@router.delete("/{bug_id}/occurrences/{occurrence_id}", status_code=204)
async def delete_occurrence(
    bug_id: str,
    occurrence_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    occurrence = await _get_occurrence_or_404(db, occurrence_id, auth)
    if occurrence.bug_id != bug_id:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    await audit_event(
        db=db, event_type="BUG_OCCURRENCE_UNLINKED", severity="INFO", request=request,
        subject_type="bug", subject_id=bug_id,
        detail={"report_id": occurrence.report_id, "sub_report_id": occurrence.sub_report_id},
        description=f"Bug occurrence unlinked from report {occurrence.report_id}",
    )
    db.add(BugHistoryEntry(bug_id=bug_id, action="occurrence_unlinked", actor=auth.username))
    await db.delete(occurrence)
    await db.commit()


# ---------------------------------------------------------------------------
# Duplicate linking — for the case an occurrence doesn't cover: two people
# each independently filed their own Bug for the same underlying issue.
# Occurrences link one bug to an *additional report/job* it was also seen
# on; this links two already-independent Bug rows to each other. The
# "duplicate" bug isn't deleted or merged field-by-field — its own
# comments/attachments/history stay exactly where they are, so nothing is
# lost — it's marked (duplicate_of_bug_id + auto-closed) and its
# occurrences (plus its own primary report/job origin, as a new occurrence)
# move onto the canonical bug, so that bug's "seen in N places" reflects
# the combined footprint.
# ---------------------------------------------------------------------------

class MarkDuplicateBody(BaseModel):
    target_bug_id: str = Field(min_length=1)


@router.post("/{bug_id}/mark-duplicate")
async def mark_duplicate(
    bug_id: str,
    body: MarkDuplicateBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    bug = await _get_bug_or_404(db, bug_id, auth)
    if body.target_bug_id == bug_id:
        raise HTTPException(status_code=422, detail="A bug can't be marked as a duplicate of itself")
    if bug.duplicate_of_bug_id:
        raise HTTPException(status_code=422, detail="This bug is already marked as a duplicate — unmark it first")
    target = await _get_bug_or_404(db, body.target_bug_id, auth)

    # Resolve chains: if the chosen target is itself a duplicate of
    # something else, link to that canonical bug instead — a reader
    # shouldn't have to follow more than one hop to find where things
    # actually landed.
    if target.duplicate_of_bug_id:
        canonical = await _get_bug_or_404(db, target.duplicate_of_bug_id, auth)
        target = canonical
        if target.id == bug_id:
            raise HTTPException(status_code=422, detail="That bug is already marked as a duplicate of this one")

    occ_result = await db.execute(select(BugOccurrence).where(BugOccurrence.bug_id == bug_id))
    for occ in occ_result.scalars().all():
        occ.bug_id = target.id

    if bug.report_id or bug.bm_job_id:
        db.add(BugOccurrence(
            bug_id=target.id, report_id=bug.report_id, sub_report_id=bug.sub_report_id,
            bm_job_id=bug.bm_job_id, note=f"From duplicate bug: {bug.title}", noted_by=auth.username,
        ))

    bug.duplicate_of_bug_id = target.id
    if bug.status not in ("resolved", "wont-fix"):
        old_status = bug.status
        bug.status = "closed"
        db.add(BugHistoryEntry(
            bug_id=bug.id, action="status_change", from_status=old_status, to_status="closed",
            note=f'Auto-closed: marked as a duplicate of "{target.title}"', actor=auth.username,
        ))
    db.add(BugHistoryEntry(
        bug_id=bug.id, action="marked_duplicate",
        note=f'Marked as a duplicate of "{target.title}"', actor=auth.username,
    ))
    db.add(BugHistoryEntry(
        bug_id=target.id, action="duplicate_linked",
        note=f'Bug "{bug.title}" was marked as a duplicate of this bug', actor=auth.username,
    ))
    bug.updated_at = datetime.now(timezone.utc)
    target.updated_at = datetime.now(timezone.utc)

    await audit_event(
        db=db, event_type="BUG_MARKED_DUPLICATE", severity="INFO", request=request,
        subject_type="bug", subject_id=bug.id,
        detail={"target_bug_id": target.id, "target_title": target.title},
        description=f'Bug "{bug.title}" marked as a duplicate of "{target.title}"',
    )

    await db.commit()
    await db.refresh(bug)
    usernames = await _assignee_usernames(db, [bug])
    return _bug_dict(bug, assignee_username=usernames.get(bug.assignee_id or ""))


@router.post("/{bug_id}/unmark-duplicate")
async def unmark_duplicate(
    bug_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    bug = await _get_bug_or_404(db, bug_id, auth)
    if not bug.duplicate_of_bug_id:
        raise HTTPException(status_code=422, detail="This bug isn't marked as a duplicate")
    old_target_id = bug.duplicate_of_bug_id
    bug.duplicate_of_bug_id = None
    bug.updated_at = datetime.now(timezone.utc)
    db.add(BugHistoryEntry(bug_id=bug.id, action="duplicate_unmarked", actor=auth.username))
    await audit_event(
        db=db, event_type="BUG_DUPLICATE_UNMARKED", severity="INFO", request=request,
        subject_type="bug", subject_id=bug.id,
        detail={"previous_target_bug_id": old_target_id},
        description=f'Bug "{bug.title}" un-marked as a duplicate',
    )
    await db.commit()
    await db.refresh(bug)
    usernames = await _assignee_usernames(db, [bug])
    return _bug_dict(bug, assignee_username=usernames.get(bug.assignee_id or ""))


# ---------------------------------------------------------------------------
# Save to Docs — Stage 6. Writes a resolved bug's write-up into Docs as an
# ordinary browsable/searchable Doc (one shared "Bug Resolutions" library +
# shelf, one Doc per bug — same "new version row per save" convention Docs
# already uses, so re-saving after an updated resolution just adds a
# version rather than duplicating the doc). One-directional: this is an
# export, not a live sync — the Doc doesn't get updated automatically if
# the bug changes again later, matching DocApp's own "save resolved bug as
# a library doc" action.
# ---------------------------------------------------------------------------

_RESOLUTIONS_LIBRARY_NAME = "Bug Resolutions"
_RESOLUTIONS_SHELF_NAME = "Bug Resolutions"


def _bug_resolution_doc_content(bug: Bug, history: list[BugHistoryEntry], assignee_username: str | None = None) -> str:
    tags = json.loads(bug.tags_json)
    meta = [f"**Status:** {bug.status}", f"**Severity:** {bug.severity}"]
    if bug.frequency:
        meta.append(f"**Frequency:** {bug.frequency}")
    if tags:
        meta.append(f"**Tags:** {', '.join(tags)}")
    meta.append(f"**Reporter:** {bug.reporter or 'unknown'}")
    if assignee_username:
        meta.append(f"**Assignee:** {assignee_username}")

    lines = list(meta)
    lines.append("")
    if bug.report_id:
        ref = f"_Originally filed against report `{bug.report_id}`"
        if bug.sub_report_id:
            ref += f" (sub-report `{bug.sub_report_id}`)"
        ref += "._"
        lines.append(ref)
        lines.append("")
    if bug.description:
        lines.append(bug.description.strip())
        lines.append("")
    lines.append("## Resolution")
    lines.append("")
    lines.append((bug.resolution or "").strip())
    lines.append("")
    if history:
        lines.append("## Timeline")
        lines.append("")
        for h in history:
            entry = f"- {h.created_at.isoformat()} — {h.action}"
            if h.to_status:
                entry += f" → {h.to_status}"
            if h.actor:
                entry += f" ({h.actor})"
            if h.note:
                entry += f" — {h.note}"
            lines.append(entry)
        lines.append("")
    return "\n".join(lines)


async def _get_latest_doc_version(db: AsyncSession, shelf_id: str, name: str) -> Doc | None:
    query = select(Doc).where(Doc.shelf_id == shelf_id, Doc.name == name).order_by(Doc.version.desc()).limit(1)
    return (await db.execute(query)).scalar_one_or_none()


@router.post("/{bug_id}/save-to-docs", status_code=201)
async def save_bug_to_docs(
    bug_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    bug = await _get_bug_or_404(db, bug_id, auth)
    if not bug.resolution or not bug.resolution.strip():
        raise HTTPException(status_code=422, detail="Bug has no resolution to save yet")

    history = (await db.execute(
        select(BugHistoryEntry).where(BugHistoryEntry.bug_id == bug_id).order_by(BugHistoryEntry.created_at)
    )).scalars().all()

    # Find-or-create the shared library/shelf — always scoped to the
    # acting user's own tenant, even for a global admin (matches every
    # other create path in this codebase: reads may bypass tenant filters,
    # writes never do).
    library = (await db.execute(
        select(DocLibrary).where(DocLibrary.tenant_id == auth.tenant_id, DocLibrary.name == _RESOLUTIONS_LIBRARY_NAME)
    )).scalar_one_or_none()
    if not library:
        library = DocLibrary(name=_RESOLUTIONS_LIBRARY_NAME, tenant_id=auth.tenant_id, created_by=auth.username)
        db.add(library)
        await db.flush()

    shelf = (await db.execute(
        select(DocShelf).where(DocShelf.library_id == library.id, DocShelf.name == _RESOLUTIONS_SHELF_NAME)
    )).scalar_one_or_none()
    if not shelf:
        shelf = DocShelf(library_id=library.id, name=_RESOLUTIONS_SHELF_NAME, tenant_id=auth.tenant_id, created_by=auth.username)
        db.add(shelf)
        await db.flush()

    # Short id suffix keeps the doc name unique even when two bugs share a
    # title, same disambiguation convention used elsewhere (report labels).
    doc_name = f"{bug.title[:490]} (#{bug.id[:8]})"
    usernames = await _assignee_usernames(db, [bug])
    content = _bug_resolution_doc_content(bug, list(history), assignee_username=usernames.get(bug.assignee_id or ""))

    existing = await _get_latest_doc_version(db, shelf.id, doc_name)
    doc = Doc(
        shelf_id=shelf.id, name=doc_name, content=content,
        version=(existing.version + 1) if existing else 1,
        # The bug's own report link *is* this doc's origin — carry it
        # straight over rather than leaving the new doc's first-seen link
        # empty every time (Improvements Plan Stage 1). If the doc already
        # existed and had a different first-seen link set by hand, honour
        # that instead of clobbering it on re-save.
        first_seen_report_id=(existing.first_seen_report_id if existing else None) or bug.report_id,
        first_seen_sub_report_id=(existing.first_seen_sub_report_id if existing else None) or bug.sub_report_id,
        tenant_id=auth.tenant_id, created_by=auth.username,
    )
    db.add(doc)
    await db.flush()

    # This writes a Doc directly rather than going through docs.py's
    # create_doc/save_doc_version, so it needs its own copy of their FTS5
    # index maintenance (Stage 11) — same "only the current version is
    # indexed" rule: drop the superseded version's row, index the new one.
    if settings.is_sqlite:
        if existing:
            await db.execute(text("DELETE FROM docs_fts WHERE id = :id"), {"id": existing.id})
        await db.execute(text("DELETE FROM docs_fts WHERE id = :id"), {"id": doc.id})
        await db.execute(
            text("INSERT INTO docs_fts (id, name, content) VALUES (:id, :name, :content)"),
            {"id": doc.id, "name": doc.name, "content": doc.content},
        )

    await audit_event(
        db=db, event_type="BUG_SAVED_TO_DOCS", severity="INFO", request=request,
        subject_type="bug", subject_id=bug.id,
        detail={"doc_id": doc.id, "shelf_id": shelf.id, "version": doc.version},
        description=f"Bug '{bug.title}' saved to Docs as '{doc_name}'",
    )
    db.add(BugHistoryEntry(
        bug_id=bug_id, action="saved_to_docs", actor=auth.username,
        note=f"Saved to Docs (v{doc.version})",
    ))
    await db.commit()

    return {
        "doc_id": doc.id, "doc_name": doc.name, "version": doc.version,
        "shelf_id": shelf.id, "shelf_name": shelf.name,
        "library_id": library.id, "library_name": library.name,
    }
