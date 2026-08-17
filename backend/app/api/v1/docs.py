"""Docs feature REST API — Stage 1 of the DocApp-in-LabTool plan.

Library/Shelf/Doc/DocAnnotation CRUD, real SQL search (ILIKE across
name+content, paginated) rather than DocApp's own in-browser naive
substring scoring — the whole point of recreating this feature on LabTool's
own stack is to use its real storage/search instead.
"""
from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import AuthContext, require_role
from app.services.audit import audit_event
from app.services.docs_map import compute_map
from app.models.docs import DocLibrary, DocShelf, Doc, DocAnnotation, KbMatchCount, DecodeEvent
from app.models.jar_analyser import AnalysisReport, SubReport, JarStringConstant, JarDecompiledClass

router = APIRouter(prefix="/api/v1/docs", tags=["docs"])

_ROLES = ("admin", "operator", "auditor", "readonly")
_WRITE_ROLES = ("admin", "operator")  # create/update — viewers (auditor/readonly) don't get this
_DELETE_ROLES = ("admin",)  # operator has create+read+update but not delete


# ---------------------------------------------------------------------------
# Tenant-scoped lookups (mirrors jar_analyser.py's _get_report_or_404 shape)
# ---------------------------------------------------------------------------

async def _get_library_or_404(db: AsyncSession, library_id: str, auth: AuthContext) -> DocLibrary:
    query = select(DocLibrary).where(DocLibrary.id == library_id)
    if not auth.is_global_admin:
        query = query.where(DocLibrary.tenant_id == auth.tenant_id)
    obj = (await db.execute(query)).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Library not found")
    return obj


async def _get_shelf_or_404(db: AsyncSession, shelf_id: str, auth: AuthContext) -> DocShelf:
    query = select(DocShelf).where(DocShelf.id == shelf_id)
    if not auth.is_global_admin:
        query = query.where(DocShelf.tenant_id == auth.tenant_id)
    obj = (await db.execute(query)).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Shelf not found")
    return obj


async def _get_current_doc_or_404(db: AsyncSession, doc_id: str, auth: AuthContext) -> Doc:
    """A `doc_id` may refer to any version — the caller gets that exact
    version. Use _get_latest_doc_version() when "the current version of
    this document name" is what's actually wanted (e.g. before saving a
    new version).

    Excludes soft-deleted docs (Stage 7) — a doc in Trash is 404 to every
    normal read/write path; only the dedicated trash/restore endpoints
    below can see or act on it."""
    query = select(Doc).where(Doc.id == doc_id, Doc.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Doc.tenant_id == auth.tenant_id)
    obj = (await db.execute(query)).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Document not found")
    return obj


async def _get_annotation_or_404(db: AsyncSession, annotation_id: str, auth: AuthContext) -> DocAnnotation:
    """Joins through Doc for the tenant check — DocAnnotation has no
    tenant_id column of its own (matches the codebase's own convention for
    child entities, e.g. SubReport scoping through AnalysisReport), so this
    makes the lookup independently tenant-safe regardless of call order,
    rather than trusting a caller already validated the parent doc."""
    query = select(DocAnnotation).join(Doc, DocAnnotation.doc_id == Doc.id).where(DocAnnotation.id == annotation_id)
    if not auth.is_global_admin:
        query = query.where(Doc.tenant_id == auth.tenant_id)
    obj = (await db.execute(query)).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return obj


async def _get_latest_doc_version(db: AsyncSession, shelf_id: str, name: str) -> Doc | None:
    """Excludes soft-deleted docs (Stage 7) — a deleted name is available
    for reuse, and this is also what create_doc's duplicate-name check
    relies on to allow that."""
    query = (
        select(Doc)
        .where(Doc.shelf_id == shelf_id, Doc.name == name, Doc.deleted_at.is_(None))
        .order_by(Doc.version.desc())
        .limit(1)
    )
    return (await db.execute(query)).scalar_one_or_none()


async def _validate_first_seen_link(
    db: AsyncSession, auth: AuthContext, report_id: str | None, sub_report_id: str | None
) -> None:
    """Same shape as bug_tracker.py's _validate_report_link — deliberately
    duplicated rather than shared, matching this codebase's existing
    per-module convention (e.g. DEFAULT_TENANT_ID is redefined in every
    feature module rather than imported from one place)."""
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


# ---------------------------------------------------------------------------
# FTS5 index maintenance — Improvements Plan Stage 11. SQLite-only (see
# migration 078's docstring for why); every call is a silent no-op on
# Postgres/MySQL, where search_docs() falls back to ILIKE instead. Only the
# *current, live* version of a document is ever indexed — matching exactly
# what ILIKE search always matched against — so callers pass the specific
# version row that's becoming (or ceasing to be) "current."
# ---------------------------------------------------------------------------

async def _fts_index_doc(db: AsyncSession, doc: Doc) -> None:
    if not settings.is_sqlite:
        return
    await db.execute(text("DELETE FROM docs_fts WHERE id = :id"), {"id": doc.id})
    await db.execute(
        text("INSERT INTO docs_fts (id, name, content) VALUES (:id, :name, :content)"),
        {"id": doc.id, "name": doc.name, "content": doc.content},
    )


async def _fts_unindex_doc(db: AsyncSession, doc_id: str) -> None:
    if not settings.is_sqlite:
        return
    await db.execute(text("DELETE FROM docs_fts WHERE id = :id"), {"id": doc_id})


def _fts_match_query(q: str) -> str:
    """Builds a safe FTS5 MATCH expression from arbitrary user input —
    extracts word tokens only (discarding anything FTS5's query syntax
    would otherwise interpret, like quotes/colons/hyphens/asterisks) and
    quotes+prefix-matches each one, ANDed together by FTS5's implicit
    default. Trades ILIKE's "matches any substring anywhere" for real
    tokenised prefix search — a expected difference, not a bug."""
    terms = re.findall(r"\w+", q)
    if not terms:
        return '""'
    return " ".join(f'"{t}"*' for t in terms)


def _library_dict(lib: DocLibrary) -> dict[str, Any]:
    return {"id": lib.id, "name": lib.name, "created_by": lib.created_by, "created_at": lib.created_at.isoformat()}


def _shelf_dict(shelf: DocShelf) -> dict[str, Any]:
    return {
        "id": shelf.id, "library_id": shelf.library_id, "name": shelf.name,
        "created_by": shelf.created_by, "created_at": shelf.created_at.isoformat(),
    }


def _doc_dict(doc: Doc, include_content: bool = True) -> dict[str, Any]:
    d = {
        "id": doc.id, "shelf_id": doc.shelf_id, "name": doc.name, "version": doc.version,
        "created_by": doc.created_by, "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(), "size": len(doc.content),
        "first_seen_report_id": doc.first_seen_report_id,
        "first_seen_sub_report_id": doc.first_seen_sub_report_id,
    }
    if include_content:
        d["content"] = doc.content
    return d


def _annotation_dict(a: DocAnnotation) -> dict[str, Any]:
    return {
        "id": a.id, "doc_id": a.doc_id, "text": a.text, "color": a.color, "note": a.note,
        "prefix": a.prefix, "suffix": a.suffix,
        "created_by": a.created_by, "created_at": a.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Libraries
# ---------------------------------------------------------------------------

class LibraryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)


@router.get("/libraries")
async def list_libraries(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> list[dict[str, Any]]:
    query = select(DocLibrary).order_by(DocLibrary.name)
    if not auth.is_global_admin:
        query = query.where(DocLibrary.tenant_id == auth.tenant_id)
    rows = (await db.execute(query)).scalars().all()
    return [_library_dict(r) for r in rows]


@router.post("/libraries", status_code=201)
async def create_library(
    body: LibraryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    lib = DocLibrary(name=body.name, tenant_id=auth.tenant_id, created_by=auth.username)
    db.add(lib)
    await db.flush()
    await audit_event(
        db=db, event_type="DOC_LIBRARY_CREATED", severity="INFO", request=request,
        subject_type="doc_library", subject_id=lib.id,
        detail={"name": lib.name}, description=f"Doc library created: {lib.name}",
    )
    await db.commit()
    return _library_dict(lib)


@router.delete("/libraries/{library_id}", status_code=204)
async def delete_library(
    library_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    lib = await _get_library_or_404(db, library_id, auth)
    await audit_event(
        db=db, event_type="DOC_LIBRARY_DELETED", severity="WARNING", request=request,
        subject_type="doc_library", subject_id=lib.id,
        detail={"name": lib.name}, description=f"Doc library deleted: {lib.name}",
    )
    await db.delete(lib)
    await db.commit()


# ---------------------------------------------------------------------------
# Shelves
# ---------------------------------------------------------------------------

class ShelfCreate(BaseModel):
    library_id: str
    name: str = Field(min_length=1, max_length=256)


@router.get("/libraries/{library_id}/shelves")
async def list_shelves(
    library_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> list[dict[str, Any]]:
    await _get_library_or_404(db, library_id, auth)
    query = select(DocShelf).where(DocShelf.library_id == library_id).order_by(DocShelf.name)
    rows = (await db.execute(query)).scalars().all()
    return [_shelf_dict(r) for r in rows]


async def _current_docs_for_map(db: AsyncSession, shelf_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Every document's *current* (latest, non-deleted) version, joined to
    its shelf's name — optionally scoped to a specific set of shelves.
    Shared by the per-library and all-libraries Map View endpoints so both
    resolve "current version" identically (mirrors get_doc's own latest-
    version-per-name logic, just batched across many docs at once)."""
    where_clauses = [Doc.deleted_at.is_(None)]
    if shelf_ids is not None:
        where_clauses.append(Doc.shelf_id.in_(shelf_ids))

    subq = (
        select(Doc.shelf_id, Doc.name, func.max(Doc.version).label("max_version"))
        .where(*where_clauses)
        .group_by(Doc.shelf_id, Doc.name)
        .subquery()
    )
    query = (
        select(Doc, DocShelf.name.label("shelf_name"))
        .join(DocShelf, Doc.shelf_id == DocShelf.id)
        .join(subq, (Doc.shelf_id == subq.c.shelf_id) & (Doc.name == subq.c.name) & (Doc.version == subq.c.max_version))
        .where(*where_clauses)
    )
    rows = (await db.execute(query)).all()
    return [
        {"id": d.id, "name": d.name, "shelf_id": d.shelf_id, "shelf_name": shelf_name, "content": d.content}
        for d, shelf_name in rows
    ]


@router.get("/libraries/{library_id}/map")
async def get_library_map(
    library_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    """Relationship graph across every current document in this library —
    wiki-link, shared-heading, and shared-keyword edges, computed by
    docs_map.compute_map() against content already in the DB, rather than
    shipping every doc's full text to the browser to compute client-side.
    Also returns any manually-saved node layout (Improvements Plan
    Stage 14) — {} if none has been saved yet, distinct from "not present"
    since the frontend always expects the key."""
    library = await _get_library_or_404(db, library_id, auth)
    shelves = (await db.execute(select(DocShelf.id).where(DocShelf.library_id == library_id))).scalars().all()
    layout = json.loads(library.map_layout_json) if library.map_layout_json else {}
    if not shelves:
        return {"nodes": [], "edges": [], "layout": layout}
    docs = await _current_docs_for_map(db, shelf_ids=list(shelves))
    result = compute_map(docs)
    result["layout"] = layout
    return result


@router.get("/map")
async def get_all_libraries_map(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    """Relationship graph across every current document in every library the
    caller can see (Improvements Plan Stage 14) — the same wiki-link/shared-
    heading/shared-keyword edges as the per-library map, just computed
    against the full corpus instead of one library's shelves, so a wiki-link
    from an Error KB doc into a Bug Resolutions doc (two different
    libraries) actually shows up. No persisted layout here — this is an
    exploration view across everything, not a single library's own map, so
    there's no one library row to save a layout onto."""
    query = select(DocShelf.id)
    if not auth.is_global_admin:
        query = query.where(DocShelf.tenant_id == auth.tenant_id)
    shelf_ids = (await db.execute(query)).scalars().all()
    if not shelf_ids:
        return {"nodes": [], "edges": []}
    docs = await _current_docs_for_map(db, shelf_ids=list(shelf_ids))
    return compute_map(docs)


class MapLayoutUpdate(BaseModel):
    positions: dict[str, dict[str, float]]


@router.put("/libraries/{library_id}/map/layout")
async def save_library_map_layout(
    library_id: str,
    body: MapLayoutUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    """Full-replace save of a library's manually-dragged Map View node
    positions (Improvements Plan Stage 14) — the frontend always sends its
    complete current pinned-node set, same "caller sends the full state"
    shape as the environment-variables PATCH endpoint elsewhere in this
    codebase. An empty {"positions": {}} is exactly how "Reset Layout"
    clears a saved layout back to pure auto-arrange."""
    library = await _get_library_or_404(db, library_id, auth)
    library.map_layout_json = json.dumps(body.positions)
    await audit_event(
        db=db, event_type="DOC_MAP_LAYOUT_SAVED", severity="INFO", request=request,
        subject_type="doc_library", subject_id=library.id,
        detail={"node_count": len(body.positions)}, description=f"Map layout saved for library: {library.name}",
    )
    await db.commit()
    return {"positions": body.positions}


@router.post("/shelves", status_code=201)
async def create_shelf(
    body: ShelfCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    await _get_library_or_404(db, body.library_id, auth)
    shelf = DocShelf(library_id=body.library_id, name=body.name, tenant_id=auth.tenant_id, created_by=auth.username)
    db.add(shelf)
    await db.flush()
    await audit_event(
        db=db, event_type="DOC_SHELF_CREATED", severity="INFO", request=request,
        subject_type="doc_shelf", subject_id=shelf.id,
        detail={"name": shelf.name, "library_id": shelf.library_id}, description=f"Doc shelf created: {shelf.name}",
    )
    await db.commit()
    return _shelf_dict(shelf)


@router.delete("/shelves/{shelf_id}", status_code=204)
async def delete_shelf(
    shelf_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    shelf = await _get_shelf_or_404(db, shelf_id, auth)
    await audit_event(
        db=db, event_type="DOC_SHELF_DELETED", severity="WARNING", request=request,
        subject_type="doc_shelf", subject_id=shelf.id,
        detail={"name": shelf.name}, description=f"Doc shelf deleted: {shelf.name}",
    )
    await db.delete(shelf)
    await db.commit()


class ShelfMove(BaseModel):
    library_id: str


@router.post("/shelves/{shelf_id}/move")
async def move_shelf(
    shelf_id: str,
    body: ShelfMove,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    """Repoints a shelf onto a different library, in place — the
    alternative today is delete-and-recreate, which loses every document,
    version, and annotation on it (Improvements Plan Stage 8). Shelf names
    aren't unique within a library (no DB constraint, no check on create),
    so there's no destination collision to guard against here."""
    shelf = await _get_shelf_or_404(db, shelf_id, auth)
    target_library = await _get_library_or_404(db, body.library_id, auth)
    if target_library.id == shelf.library_id:
        raise HTTPException(status_code=400, detail="Shelf is already in this library")
    old_library_id = shelf.library_id
    shelf.library_id = target_library.id
    await audit_event(
        db=db, event_type="DOC_SHELF_MOVED", severity="INFO", request=request,
        subject_type="doc_shelf", subject_id=shelf.id,
        detail={"name": shelf.name, "from_library_id": old_library_id, "to_library_id": target_library.id},
        description=f"Doc shelf moved: {shelf.name}",
    )
    await db.commit()
    await db.refresh(shelf)
    return _shelf_dict(shelf)


# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------

class DocCreate(BaseModel):
    shelf_id: str
    name: str = Field(min_length=1, max_length=512)
    content: str = ""
    # Optional at creation time — "the reason for creating the document at
    # all" (see doc_first_seen_plan.md).
    first_seen_report_id: str | None = None
    first_seen_sub_report_id: str | None = None


class DocSave(BaseModel):
    content: str


@router.get("/shelves/{shelf_id}/docs")
async def list_docs(
    shelf_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> list[dict[str, Any]]:
    """One row per document *name* (its latest version only), not one row
    per version — mirrors how DocApp's own library-store.js lists a
    shelf (max version per name), matching that behaviour rather than
    surprising a caller with every historical version in the list."""
    await _get_shelf_or_404(db, shelf_id, auth)
    subq = (
        select(Doc.name, func.max(Doc.version).label("max_version"))
        .where(Doc.shelf_id == shelf_id, Doc.deleted_at.is_(None))
        .group_by(Doc.name)
        .subquery()
    )
    query = (
        select(Doc)
        .join(subq, (Doc.name == subq.c.name) & (Doc.version == subq.c.max_version))
        .where(Doc.shelf_id == shelf_id, Doc.deleted_at.is_(None))
        .order_by(Doc.name)
    )
    rows = (await db.execute(query)).scalars().all()
    return [_doc_dict(r, include_content=False) for r in rows]


# Search — real SQL ILIKE across name+content, paginated. This is the whole
# point of rebuilding on LabTool's own stack instead of porting DocApp's
# load-everything-into-memory substring scoring (library-search.js).
# Registered before the greedy "/{doc_id}" route below — Starlette matches
# routes in registration order, so "/search" would otherwise be swallowed
# as doc_id="search" (confirmed live: that's exactly what happened before
# this was reordered — same class of bug documented on the decompiled-class
# routes in jar_analyser.py).
@router.get("/search")
async def search_docs(
    q: str = Query(default="", description="Optional when filtering by first_seen_report_id instead"),
    first_seen_report_id: str | None = Query(default=None),
    first_seen_sub_report_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    if not q and not first_seen_report_id and not first_seen_sub_report_id:
        raise HTTPException(status_code=422, detail="q or first_seen_report_id is required")
    # Search only the latest version of each document name — matching
    # search results are always current content, not stale history.
    subq = (
        select(Doc.shelf_id, Doc.name, func.max(Doc.version).label("max_version"))
        .where(Doc.deleted_at.is_(None))
        .group_by(Doc.shelf_id, Doc.name)
        .subquery()
    )
    query = (
        select(Doc)
        .join(subq, (Doc.shelf_id == subq.c.shelf_id) & (Doc.name == subq.c.name) & (Doc.version == subq.c.max_version))
        .where(Doc.deleted_at.is_(None))
    )

    # FTS5 (Stage 11) when available — ranked, snippeted, real tokenised
    # search — falling back to plain ILIKE substring matching on Postgres/
    # MySQL, where docs_fts doesn't exist. ranked_ids stays None on the
    # ILIKE path, which is what selects the original count()+offset/limit
    # SQL pagination below rather than the Python-side rank-preserving one.
    ranked_ids: list[str] | None = None
    snippet_by_id: dict[str, str] = {}
    if q and settings.is_sqlite:
        fts_rows = (await db.execute(
            text(
                "SELECT id, snippet(docs_fts, 2, '**', '**', '…', 16) AS snip FROM docs_fts "
                "WHERE docs_fts MATCH :match ORDER BY bm25(docs_fts) LIMIT 1000"
            ),
            {"match": _fts_match_query(q)},
        )).all()
        ranked_ids = [r.id for r in fts_rows]
        snippet_by_id = {r.id: r.snip for r in fts_rows}
        if not ranked_ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 1}
        query = query.where(Doc.id.in_(ranked_ids))
    elif q:
        like = f"%{q}%"
        query = query.where(Doc.name.ilike(like) | Doc.content.ilike(like))

    # Reverse lookup for the "N docs first seen here" report-side badge
    # (Stage 3) — same primary-link filter shape as the Bug Tracker's
    # report_id filter, just without an occurrence-style OR-subquery since
    # first-seen is a single link, not a multi-report pattern.
    if first_seen_report_id:
        query = query.where(Doc.first_seen_report_id == first_seen_report_id)
    if first_seen_sub_report_id:
        query = query.where(Doc.first_seen_sub_report_id == first_seen_sub_report_id)
    if not auth.is_global_admin:
        query = query.where(Doc.tenant_id == auth.tenant_id)

    if ranked_ids is not None:
        # Relevance order isn't expressible in the SQL above (it comes from
        # docs_fts, a separate table) — fetch the (small, capped) full
        # matching set and paginate/order in Python instead.
        all_rows = (await db.execute(query)).scalars().all()
        rank_index = {rid: i for i, rid in enumerate(ranked_ids)}
        all_rows = sorted(all_rows, key=lambda r: rank_index.get(r.id, len(ranked_ids)))
        total = len(all_rows)
        start = (page - 1) * page_size
        rows = all_rows[start:start + page_size]
        items = [
            {**_doc_dict(r, include_content=False), "snippet": snippet_by_id.get(r.id)}
            for r in rows
        ]
    else:
        total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
        rows = (await db.execute(
            query.order_by(Doc.name).offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()
        items = [_doc_dict(r, include_content=False) for r in rows]

    return {
        "items": items,
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


# Error KB search — the JAR Analyser's error lookup now lives as ordinary
# docs (one per-category library), each encoding a regex match pattern as a
# parseable metadata line. This is a different search direction to /search
# above (regex-from-doc tested against the pasted query, not query tested
# as a substring of doc content), so it needs its own endpoint rather than
# reusing ILIKE search. Registered before "/{doc_id}" for the same reason
# "/search" is — "error-kb" would otherwise be swallowed as a doc id.
@router.get("/error-kb/search")
async def search_error_kb(
    q: str = Query(default="", description="Pasted error text (pattern mode) or keyword (topic mode)"),
    mode: str = Query(default="pattern", pattern="^(pattern|topic)$"),
    category: list[str] = Query(default=[], description="Filter to one or more KB categories - Browse by Topic's category pick-list. In topic mode, selecting a category with no keyword browses every entry in it directly."),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    from app.services.docs_error_kb import build_kb_entries, fetch_all_current_docs_with_paths, record_kb_matches
    from app.services.jar_analyser.error_kb import search_kb

    docs = await fetch_all_current_docs_with_paths(db, auth.tenant_id, auth.is_global_admin)
    kb_entries = build_kb_entries(docs)
    if category:
        kb_entries = [e for e in kb_entries if e["category"] in category]

    if mode == "topic":
        if not q.strip() and category:
            # Pure category browse - a topic was picked from the list, no
            # keyword needed at all, unlike a real topic search.
            results = sorted(kb_entries, key=lambda e: e["title"].lower())
        else:
            results = await _search_kb_by_topic(db, q, kb_entries)
    else:
        results = search_kb(q, db_entries=kb_entries)
        # Usage tracking (Improvements Plan Stage 16) — pattern mode only,
        # not topic mode (a keyword browse, not a real pattern match against
        # pasted error text).
        await record_kb_matches(db, [r["id"] for r in results])
        await db.commit()
    return {"q": q, "mode": mode, "category": category, "total": len(results), "results": results}


@router.get("/error-kb/categories")
async def list_kb_categories(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> list[dict[str, Any]]:
    """Distinct KB categories (library names) with an entry count each —
    powers Browse by Topic's pick-list, so browsing starts from what's
    actually there instead of a guessed keyword. Registered as a literal
    path, same reason /error-kb/search and /error-kb/usage already are."""
    from app.services.docs_error_kb import build_kb_entries, fetch_all_current_docs_with_paths

    docs = await fetch_all_current_docs_with_paths(db, auth.tenant_id, auth.is_global_admin)
    entries = build_kb_entries(docs)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["category"]] = counts.get(e["category"], 0) + 1
    return sorted(({"name": name, "count": n} for name, n in counts.items()), key=lambda c: c["name"].lower())


@router.get("/error-kb/usage")
async def get_kb_usage(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    """Match-count usage stats for every KB entry (Improvements Plan
    Stage 16) — "most matched" surfaces entries pulling their weight,
    "least matched" (including never-matched entries, count 0) surfaces
    ones that might need rewriting, broadening their pattern, or removing.
    Registered as a literal path, before the greedy "/{doc_id}" route below,
    same reason "/error-kb/search" already is."""
    from app.services.docs_error_kb import build_kb_entries, fetch_all_current_docs_with_paths, fetch_kb_usage

    docs = await fetch_all_current_docs_with_paths(db, auth.tenant_id, auth.is_global_admin)
    kb_entries = build_kb_entries(docs)
    usage = await fetch_kb_usage(db, kb_entries)
    usage.sort(key=lambda e: e["match_count"], reverse=True)
    return {"total": len(usage), "entries": usage}


class DecodeStackTraceRequest(BaseModel):
    text: str = Field(min_length=1)


async def _lookup_known_classes(
    db: AsyncSession, class_names: set[str], tenant_id: str, is_global_admin: bool,
) -> dict[str, list[dict[str, Any]]]:
    """For each dotted class name a stack frame names, finds every analysed
    sub-report (tenant-scoped, across every uploaded jar, not just one
    report) whose own scanned classes include it — so a frame naming
    `com.dxc.ecs.fulfillment.service.ServiceDesignService` can be pointed
    back at "the fulfillment service, uploaded such-and-such a date" instead
    of staying a bare, unplaced name. Two independent sources, same reason
    outbound_call_analysis.py needs Decompilation (Section 36) on top of
    outbound_integrations.py's always-on pass:
      - JarStringConstant: populated for every class the scanner reaches
        during ordinary analysis (not opt-in), dot-separated class_name —
        cheap, broad coverage, but only proves the class exists, not that a
        specific line/source is available to jump to.
      - JarDecompiledClass: only populated for jars someone chose to
        decompile (Section 36), slash-separated class_name — proves a
        "jump to source" link is actually possible for this class.
    A class with no string constants at all (rare — see classfile.py's own
    string_constants docstring) and never decompiled simply won't be found
    by either query, same as a genuinely-unknown (third-party/JDK) class."""
    if not class_names:
        return {}

    names = list(class_names)
    string_const_query = (
        select(JarStringConstant.class_name, SubReport.id, SubReport.parent_report_id, SubReport.service_name, SubReport.filename)
        .join(SubReport, JarStringConstant.sub_report_id == SubReport.id)
        .join(AnalysisReport, SubReport.parent_report_id == AnalysisReport.id)
        .where(JarStringConstant.class_name.in_(names))
        .distinct()
    )
    if not is_global_admin:
        string_const_query = string_const_query.where(AnalysisReport.tenant_id == tenant_id)
    string_const_rows = (await db.execute(string_const_query)).all()

    slash_to_dotted = {n.replace(".", "/"): n for n in names}
    decompiled_query = (
        select(JarDecompiledClass.class_name, JarDecompiledClass.sub_report_id)
        .join(SubReport, JarDecompiledClass.sub_report_id == SubReport.id)
        .join(AnalysisReport, SubReport.parent_report_id == AnalysisReport.id)
        .where(JarDecompiledClass.class_name.in_(slash_to_dotted.keys()))
        .distinct()
    )
    if not is_global_admin:
        decompiled_query = decompiled_query.where(AnalysisReport.tenant_id == tenant_id)
    decompiled_sub_report_ids = {
        (slash_to_dotted[cn], sub_id) for cn, sub_id in (await db.execute(decompiled_query)).all()
    }

    result: dict[str, list[dict[str, Any]]] = {}
    for class_name, sub_id, report_id, service_name, filename in string_const_rows:
        result.setdefault(class_name, []).append({
            "sub_report_id": sub_id, "report_id": report_id,
            "service_name": service_name or filename, "filename": filename,
            "decompiled": (class_name, sub_id) in decompiled_sub_report_ids,
        })
    return result


@router.post("/error-kb/decode")
async def decode_stack_trace(
    body: DecodeStackTraceRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    """Parses a pasted Java stack trace / log blob (stack_trace_parser.py)
    into its exception chain, matches each exception's own class+message
    against the Error KB independently — a "Caused by:" root cause gets its
    own KB hits rather than being drowned out by the wrapper exception's
    matches, same reason outbound-call analysis correlates signals per call
    site rather than per whole source file — and cross-references every
    frame's class against classes already known from analysed jar uploads
    (_lookup_known_classes), so "which of our services does this frame
    actually belong to" doesn't require a second manual search."""
    from app.services.stack_trace_parser import extract_stack_traces
    from app.services.docs_error_kb import build_kb_entries, fetch_all_current_docs_with_paths, record_kb_matches
    from app.services.jar_analyser.error_kb import search_kb

    blocks = extract_stack_traces(body.text)
    docs = await fetch_all_current_docs_with_paths(db, auth.tenant_id, auth.is_global_admin)
    kb_entries = build_kb_entries(docs)

    all_class_names = {f.class_name for block in blocks for f in block.frames}
    known_classes = await _lookup_known_classes(db, all_class_names, auth.tenant_id, auth.is_global_admin)

    # Exception classes that are pure wrappers — their KB matches are almost
    # always duplicates of what the root cause block already shows, so cap
    # them to 3 results and suppress cross-chain duplicates aggressively.
    _WRAPPER_CLASSES = {
        "CompletionException", "ExecutionException", "InvocationTargetException",
        "DataAccessResourceFailureException", "CannotCreateTransactionException",
        "PersistenceException", "JDBCConnectionException",
    }

    matched_ids: list[str] = []
    exceptions: list[dict[str, Any]] = []
    # Track KB IDs already shown in earlier blocks so wrapper blocks don't
    # repeat the same entries the root cause block already surfaced.
    shown_kb_ids: set[str] = set()

    for block in blocks:
        exc_part = ": ".join(p for p in (block.exception_class, block.message) if p)
        frame_tokens = [
            f.class_name.split(".")[-1]
            for f in block.frames
            if f.class_name and not f.class_name.startswith(("java.lang", "sun.", "jdk."))
        ]
        frame_fqns = [
            f.class_name
            for f in block.frames
            if f.class_name and not f.class_name.startswith(("java.lang", "sun.", "jdk."))
        ]
        query_parts = [exc_part] + list(dict.fromkeys(frame_tokens + frame_fqns))
        query = " ".join(p for p in query_parts if p)

        short_class = (block.exception_class or "").split(".")[-1]
        is_wrapper = short_class in _WRAPPER_CLASSES
        # Wrappers get a tighter limit; always fetch full set first so we
        # can deduplicate before capping.
        raw_matches = search_kb(query, db_entries=kb_entries, limit=10) if query else []

        if is_wrapper:
            # Keep only matches not already shown in a prior block, then cap at 3.
            # Always keep the #1 match even if it was shown before — it's the
            # direct match for this exception class and the user needs to see it.
            deduped = [raw_matches[0]] if raw_matches else []
            for m in raw_matches[1:]:
                if m["id"] not in shown_kb_ids:
                    deduped.append(m)
            matches = deduped[:3]
        else:
            matches = raw_matches

        matched_ids += [m["id"] for m in matches]
        shown_kb_ids.update(m["id"] for m in matches)
        exceptions.append({
            "kind": block.kind,
            "exception_class": block.exception_class,
            "message": block.message,
            "is_likely_root_cause": block.is_likely_root_cause,
            "frames": [
                {
                    "class_name": f.class_name, "method_name": f.method_name,
                    "file_name": f.file_name, "line_number": f.line_number,
                    "is_native": f.is_native, "is_application_frame": f.is_application_frame,
                    "known_in": known_classes.get(f.class_name, []),
                }
                for f in block.frames
            ],
            "kb_matches": matches,
        })

    if matched_ids:
        # Same usage-tracking convention as /error-kb/search's pattern mode.
        await record_kb_matches(db, matched_ids)
        await db.commit()

    # ML diagnostic layer — same stack trace text, no log file in this flow.
    ml_analysis: dict | None = None
    try:
        from phase5.log_intelligence.pipeline import diagnose_with_ml
        from app.core.config import settings
        _log_paths = [p.strip() for p in settings.ML_LOG_PATHS.split(":") if p.strip()] if settings.ML_LOG_PATHS else None
        ml_result = diagnose_with_ml(
            stack_trace_text=body.text,
            log_path=str(settings.ML_LOG_PATH) if settings.ML_LOG_PATH else None,
            log_paths=_log_paths,
            report_id="decode",
            scorer_path=str(settings.ML_SCORER_PATH) if settings.ML_SCORER_PATH else None,
            tail_lines=settings.ML_TAIL_LINES,
        )
        ml_analysis = ml_result.to_dict()
    except Exception:
        pass

    # Persist decode event for ML training corpus — fire and commit
    # independently so a DB hiccup here never breaks the decode response.
    try:
        import hashlib
        fingerprint = hashlib.sha256(body.text.encode()).hexdigest()[:64]
        exc_classes = [b["exception_class"] for b in exceptions if b.get("exception_class")]
        db.add(DecodeEvent(
            tenant_id=auth.tenant_id,
            stack_fingerprint=fingerprint,
            exception_classes_json=json.dumps(exc_classes),
            matched_kb_ids_json=json.dumps(list(dict.fromkeys(matched_ids))),
            ml_analysis_json=json.dumps(ml_analysis) if ml_analysis else None,
        ))
        await db.commit()
    except Exception:
        pass

    return {"total_exceptions": len(exceptions), "exceptions": exceptions, "ml_analysis": ml_analysis}


async def _search_kb_by_topic(db: AsyncSession, q: str, kb_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keyword/topic search across KB entries — a complement to search_kb()'s
    regex-pattern matching above, for browsing by subject ("keystone
    certificate") rather than needing a real error message to paste.
    KB entries are ordinary Docs, so this reuses the same FTS5 ranking and
    snippets as search_docs() when available, scoped down to just the KB
    entries' own doc ids (Improvements Plan Stage 11 follow-up)."""
    if not q or not q.strip():
        return []
    by_id = {e["id"]: e for e in kb_entries}
    if not by_id:
        return []

    if settings.is_sqlite:
        stmt = text(
            "SELECT id, snippet(docs_fts, 2, '**', '**', '…', 16) AS snip FROM docs_fts "
            "WHERE docs_fts MATCH :match AND id IN :ids ORDER BY bm25(docs_fts) LIMIT 50"
        ).bindparams(bindparam("ids", expanding=True))
        rows = (await db.execute(stmt, {"match": _fts_match_query(q), "ids": list(by_id.keys())})).all()
        results = []
        for r in rows:
            entry = dict(by_id[r.id])
            entry["snippet"] = r.snip
            results.append(entry)
        return results

    # Non-SQLite fallback — the KB corpus is already fully loaded into
    # memory just above (kb_entries), so a plain case-insensitive substring
    # check is simplest here rather than duplicating ILIKE SQL for a list
    # this small.
    ql = q.lower()
    matches = []
    for entry in kb_entries:
        haystack = " ".join(filter(None, [
            entry.get("title", ""), entry.get("plain_english", ""),
            " ".join(entry.get("causes", [])), " ".join(entry.get("fix_steps", [])),
        ])).lower()
        if ql in haystack:
            matches.append(entry)
    return matches[:50]


# Trash listing — Improvements Plan Stage 7. Registered before the greedy
# "/{doc_id}" route for the same reason "/search" is above (Starlette
# matches by registration order for same-shaped single-segment paths, so
# "/trash" would otherwise be swallowed as doc_id="trash").
@router.get("/trash")
async def list_trash(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> list[dict[str, Any]]:
    subq = (
        select(Doc.shelf_id, Doc.name, func.max(Doc.version).label("max_version"))
        .where(Doc.deleted_at.is_not(None))
        .group_by(Doc.shelf_id, Doc.name)
        .subquery()
    )
    query = (
        select(Doc, DocShelf.name, DocLibrary.name)
        .join(subq, (Doc.shelf_id == subq.c.shelf_id) & (Doc.name == subq.c.name) & (Doc.version == subq.c.max_version))
        .join(DocShelf, Doc.shelf_id == DocShelf.id)
        .join(DocLibrary, DocShelf.library_id == DocLibrary.id)
        .where(Doc.deleted_at.is_not(None))
        .order_by(Doc.deleted_at.desc())
    )
    if not auth.is_global_admin:
        query = query.where(Doc.tenant_id == auth.tenant_id)
    rows = (await db.execute(query)).all()
    return [
        {
            "id": d.id, "shelf_id": d.shelf_id, "shelf_name": shelf_name, "library_name": library_name,
            "name": d.name, "version": d.version, "created_by": d.created_by,
            "deleted_at": d.deleted_at.isoformat(),
        }
        for d, shelf_name, library_name in rows
    ]


# ---------------------------------------------------------------------------
# Bulk actions — Improvements Plan Stage 9. Checkbox-selection from a
# shelf's document list; each id is processed independently (not
# all-or-nothing), returning which ones succeeded and which were skipped,
# so one conflicting/missing id doesn't sink the whole batch.
# ---------------------------------------------------------------------------

class BulkMove(BaseModel):
    doc_ids: list[str] = Field(min_length=1, max_length=200)
    shelf_id: str


@router.post("/bulk-move")
async def bulk_move_docs(
    body: BulkMove,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    """Moves multiple documents onto the same destination shelf in one
    action, reusing move_doc's per-document collision checks (Stage 7's
    live-or-trashed name lesson applies here too)."""
    target_shelf = await _get_shelf_or_404(db, body.shelf_id, auth)
    moved: list[str] = []
    failed: list[dict[str, str]] = []

    for doc_id in body.doc_ids:
        try:
            doc = await _get_current_doc_or_404(db, doc_id, auth)
        except HTTPException:
            failed.append({"doc_id": doc_id, "name": "", "error": "Document not found"})
            continue
        if target_shelf.id == doc.shelf_id:
            failed.append({"doc_id": doc_id, "name": doc.name, "error": "Already on this shelf"})
            continue
        live_collision = await _get_latest_doc_version(db, target_shelf.id, doc.name)
        if live_collision:
            failed.append({"doc_id": doc_id, "name": doc.name, "error": "A document with this name already exists on the destination shelf"})
            continue
        trashed_collision = (await db.execute(
            select(Doc).where(Doc.shelf_id == target_shelf.id, Doc.name == doc.name, Doc.deleted_at.is_not(None)).limit(1)
        )).scalar_one_or_none()
        if trashed_collision:
            failed.append({"doc_id": doc_id, "name": doc.name, "error": "A document with this name is in Rubbish on the destination shelf"})
            continue

        versions_query = select(Doc).where(Doc.shelf_id == doc.shelf_id, Doc.name == doc.name, Doc.deleted_at.is_(None))
        if not auth.is_global_admin:
            versions_query = versions_query.where(Doc.tenant_id == auth.tenant_id)
        versions = (await db.execute(versions_query)).scalars().all()
        for v in versions:
            v.shelf_id = target_shelf.id
        moved.append(doc_id)

    if moved:
        await audit_event(
            db=db, event_type="DOC_BULK_MOVED", severity="INFO", request=request,
            subject_type="doc_shelf", subject_id=target_shelf.id,
            detail={"moved_count": len(moved), "failed_count": len(failed), "to_shelf_id": target_shelf.id},
            description=f"Bulk-moved {len(moved)} document(s) to shelf {target_shelf.name}",
        )
    await db.commit()
    return {"moved": moved, "failed": failed}


class BulkDelete(BaseModel):
    doc_ids: list[str] = Field(min_length=1, max_length=200)


@router.post("/bulk-delete")
async def bulk_delete_docs(
    body: BulkDelete,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> dict[str, Any]:
    """Soft-deletes multiple documents (all versions of each) in one
    action — same Trash/restore path as a single delete."""
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    now = datetime.now(timezone.utc)

    for doc_id in body.doc_ids:
        try:
            doc = await _get_current_doc_or_404(db, doc_id, auth)
        except HTTPException:
            failed.append({"doc_id": doc_id, "name": "", "error": "Document not found"})
            continue
        versions_query = select(Doc).where(Doc.shelf_id == doc.shelf_id, Doc.name == doc.name, Doc.deleted_at.is_(None))
        if not auth.is_global_admin:
            versions_query = versions_query.where(Doc.tenant_id == auth.tenant_id)
        versions = (await db.execute(versions_query)).scalars().all()
        for v in versions:
            v.deleted_at = now
        await _fts_unindex_doc(db, doc.id)
        deleted.append(doc_id)

    if deleted:
        await audit_event(
            db=db, event_type="DOC_BULK_DELETED", severity="WARNING", request=request,
            subject_type="doc", subject_id="bulk",
            detail={"deleted_count": len(deleted), "failed_count": len(failed)},
            description=f"Bulk-deleted {len(deleted)} document(s) to Rubbish",
        )
    await db.commit()
    return {"deleted": deleted, "failed": failed}


@router.get("/{doc_id}")
async def get_doc(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    doc = await _get_current_doc_or_404(db, doc_id, auth)
    return _doc_dict(doc)


@router.get("/{doc_id}/export/markdown")
async def export_doc_markdown(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> PlainTextResponse:
    """Raw markdown export of a document's current version (Improvements
    Plan Stage 17 follow-up) — returned verbatim, exactly as stored, unlike
    the PDF export's preprocessing (wiki-links/callouts converted, HTML
    stripped): this is meant for portability/backup, so the point is
    getting back exactly what was authored, not a rendered view of it."""
    doc = await _get_current_doc_or_404(db, doc_id, auth)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", doc.name).strip("-") or "document"
    return PlainTextResponse(
        content=doc.content, media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.md"'},
    )


@router.get("/{doc_id}/export/pdf")
async def export_doc_pdf(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> Response:
    """PDF export of a document's current version (Improvements Plan
    Stage 17) — read-gated the same as viewing the doc itself, since this
    is just another way of consuming the same content. Mermaid diagrams
    render as raw source text (no browser/JS engine server-side)."""
    doc = await _get_current_doc_or_404(db, doc_id, auth)
    shelf = await _get_shelf_or_404(db, doc.shelf_id, auth)
    library = await _get_library_or_404(db, shelf.library_id, auth)
    from app.services.docs_export import doc_to_pdf
    pdf_bytes = doc_to_pdf(
        title=doc.name, content=doc.content,
        library_name=library.name, shelf_name=shelf.name,
        version=doc.version, updated_at=doc.updated_at.strftime("%Y-%m-%d %H:%M UTC"),
    )
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", doc.name).strip("-") or "document"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'},
    )


@router.get("/{doc_id}/versions")
async def list_doc_versions(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> list[dict[str, Any]]:
    doc = await _get_current_doc_or_404(db, doc_id, auth)
    query = (
        select(Doc)
        .where(Doc.shelf_id == doc.shelf_id, Doc.name == doc.name)
        .order_by(Doc.version.desc())
    )
    rows = (await db.execute(query)).scalars().all()
    return [_doc_dict(r, include_content=False) for r in rows]


def _doc_version_brief(doc: Doc) -> dict[str, Any]:
    return {"id": doc.id, "version": doc.version, "created_by": doc.created_by, "created_at": doc.created_at.isoformat()}


@router.get("/{doc_id}/diff")
async def diff_doc_versions(
    doc_id: str,
    against: str = Query(..., description="The other version's doc id to diff against"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    """Simple line-based diff between two versions of the same document
    (Improvements Plan Stage 6) — matches JAR Analyser's report-diff in
    spirit, but deliberately much lighter: stdlib difflib over the raw
    markdown text rather than a structured, persisted comparison, since
    that's all a document version actually needs."""
    doc_a = await _get_current_doc_or_404(db, doc_id, auth)
    doc_b = await _get_current_doc_or_404(db, against, auth)
    if doc_a.shelf_id != doc_b.shelf_id or doc_a.name != doc_b.name:
        raise HTTPException(status_code=400, detail="Both versions must belong to the same document")
    if doc_a.id == doc_b.id:
        raise HTTPException(status_code=400, detail="Cannot diff a version against itself")

    # Normalise so "a" is always the older version and "b" the newer one,
    # regardless of which id was passed as doc_id vs against — keeps
    # insert/delete direction meaningful no matter how the caller orders
    # its two selections.
    if doc_a.version > doc_b.version:
        doc_a, doc_b = doc_b, doc_a

    lines_a = doc_a.content.splitlines()
    lines_b = doc_b.content.splitlines()
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
        "doc_a": _doc_version_brief(doc_a),
        "doc_b": _doc_version_brief(doc_b),
        "added": sum(1 for r in rows if r["tag"] == "insert"),
        "removed": sum(1 for r in rows if r["tag"] == "delete"),
        "rows": rows,
    }


@router.post("", status_code=201)
async def create_doc(
    body: DocCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    await _get_shelf_or_404(db, body.shelf_id, auth)
    existing = await _get_latest_doc_version(db, body.shelf_id, body.name)
    if existing:
        raise HTTPException(status_code=409, detail="A document with this name already exists on this shelf")
    # A soft-deleted (Trashed) doc with this name is invisible to the check
    # above but its rows still physically occupy (shelf_id, name, version)
    # — the DB's unique constraint doesn't know about deleted_at, so a new
    # doc would always start at version=1 and collide with a deleted v1.
    # Block explicitly, with a clearer message, rather than crashing on insert.
    trashed = (await db.execute(
        select(Doc).where(Doc.shelf_id == body.shelf_id, Doc.name == body.name, Doc.deleted_at.is_not(None)).limit(1)
    )).scalar_one_or_none()
    if trashed:
        raise HTTPException(
            status_code=409,
            detail="A document with this name is in Rubbish — restore or permanently purge it before creating a new one with this name",
        )
    await _validate_first_seen_link(db, auth, body.first_seen_report_id, body.first_seen_sub_report_id)
    doc = Doc(
        shelf_id=body.shelf_id, name=body.name, content=body.content, version=1,
        first_seen_report_id=body.first_seen_report_id, first_seen_sub_report_id=body.first_seen_sub_report_id,
        tenant_id=auth.tenant_id, created_by=auth.username,
    )
    db.add(doc)
    await db.flush()
    await _fts_index_doc(db, doc)
    await audit_event(
        db=db, event_type="DOC_CREATED", severity="INFO", request=request,
        subject_type="doc", subject_id=doc.id,
        detail={"name": doc.name, "shelf_id": doc.shelf_id}, description=f"Document created: {doc.name}",
    )
    await db.commit()
    return _doc_dict(doc)


@router.post("/{doc_id}/save", status_code=201)
async def save_doc_version(
    doc_id: str,
    body: DocSave,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    """Creates a new version row (matches DocApp's own addDocument()
    behaviour — never overwrites in place)."""
    doc = await _get_current_doc_or_404(db, doc_id, auth)
    latest = await _get_latest_doc_version(db, doc.shelf_id, doc.name)
    # First-seen link carries forward from the latest version onto this new
    # one automatically — it's metadata about the doc's origin, not part of
    # what's being edited here. Change it afterward via the dedicated
    # PATCH .../first-seen endpoint if it needs to change.
    carry_from = latest or doc
    new_doc = Doc(
        shelf_id=doc.shelf_id, name=doc.name, content=body.content,
        version=(latest.version if latest else doc.version) + 1,
        first_seen_report_id=carry_from.first_seen_report_id,
        first_seen_sub_report_id=carry_from.first_seen_sub_report_id,
        tenant_id=auth.tenant_id, created_by=auth.username,
    )
    db.add(new_doc)
    await db.flush()

    # Annotations belong to one specific version row (a real FK, not
    # doc-name-level) — carry them forward the same way first_seen already
    # does, so a save doesn't silently start every highlight from zero
    # (Improvements Plan Stage 3a). Copied as fresh rows — the old version
    # row and its own annotations stay exactly as they were for anyone
    # still looking at that version — with the original created_at/
    # created_by preserved rather than reset to "now". If a copied
    # annotation's text no longer appears in the new content, Stage 3's
    # re-anchor-failure notice is what surfaces that to the user; this
    # endpoint doesn't need its own copy of that matching logic.
    old_annotations = (await db.execute(
        select(DocAnnotation).where(DocAnnotation.doc_id == carry_from.id)
    )).scalars().all()
    for old_ann in old_annotations:
        db.add(DocAnnotation(
            doc_id=new_doc.id, text=old_ann.text, color=old_ann.color, note=old_ann.note,
            prefix=old_ann.prefix, suffix=old_ann.suffix,
            created_by=old_ann.created_by, created_at=old_ann.created_at,
        ))

    # KB usage stats (Improvements Plan Stage 16) are keyed by a specific
    # Doc row's id, same as annotations — without this, editing a KB entry
    # (saving a new version) would silently reset its match history to
    # zero, exactly the class of bug Stage 3a already fixed for
    # annotations. Moved, not copied — a match count is one cumulative
    # value, not a per-version-independent list, so the old version simply
    # has no usage stats of its own once this runs (nothing else reads
    # them off a non-current version anyway).
    old_usage = (await db.execute(
        select(KbMatchCount).where(KbMatchCount.doc_id == carry_from.id)
    )).scalar_one_or_none()
    if old_usage:
        db.add(KbMatchCount(doc_id=new_doc.id, match_count=old_usage.match_count, last_matched_at=old_usage.last_matched_at))
        await db.delete(old_usage)

    # The old current version stops being "the document" the moment this
    # new one exists — its FTS row would otherwise linger as stale,
    # unreachable-via-listing search noise.
    await _fts_unindex_doc(db, carry_from.id)
    await _fts_index_doc(db, new_doc)

    await audit_event(
        db=db, event_type="DOC_SAVED", severity="INFO", request=request,
        subject_type="doc", subject_id=new_doc.id,
        detail={"name": new_doc.name, "version": new_doc.version, "annotations_carried_forward": len(old_annotations)},
        description=f"Document saved: {new_doc.name} v{new_doc.version}",
    )
    await db.commit()
    return _doc_dict(new_doc)


class FirstSeenUpdate(BaseModel):
    report_id: str | None = None
    sub_report_id: str | None = None


@router.patch("/{doc_id}/first-seen")
async def update_doc_first_seen(
    doc_id: str,
    body: FirstSeenUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    """Sets or clears the first-seen link on the *current* version row in
    place — no new version, since this is metadata about the doc's origin,
    not content. Works retroactively on any existing doc, not just at
    creation time. Sending {"report_id": null} clears it."""
    doc = await _get_current_doc_or_404(db, doc_id, auth)
    await _validate_first_seen_link(db, auth, body.report_id, body.sub_report_id)
    doc.first_seen_report_id = body.report_id
    doc.first_seen_sub_report_id = body.sub_report_id
    await audit_event(
        db=db, event_type="DOC_FIRST_SEEN_UPDATED", severity="INFO", request=request,
        subject_type="doc", subject_id=doc.id,
        detail={"report_id": body.report_id, "sub_report_id": body.sub_report_id},
        description=f"Document '{doc.name}' first-seen link updated",
    )
    await db.commit()
    await db.refresh(doc)
    return _doc_dict(doc)


@router.delete("/{doc_id}", status_code=204)
async def delete_doc(
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    """Soft-deletes every version of this document name on its shelf, not
    just the one row referenced by doc_id — deleting only the current
    version would leave older versions orphaned but still listed as "the"
    document under a stale name/shelf pairing.

    Stage 7 (Improvements Plan): marks deleted_at rather than removing the
    rows, so an accidental click is recoverable from Trash via
    POST .../restore, until the background retention sweep
    (app/services/trash_sweep.py) or an explicit DELETE /trash/{id}
    purges it for good."""
    doc = await _get_current_doc_or_404(db, doc_id, auth)
    query = select(Doc).where(Doc.shelf_id == doc.shelf_id, Doc.name == doc.name, Doc.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Doc.tenant_id == auth.tenant_id)
    versions = (await db.execute(query)).scalars().all()
    now = datetime.now(timezone.utc)
    for v in versions:
        v.deleted_at = now
    await _fts_unindex_doc(db, doc.id)
    await audit_event(
        db=db, event_type="DOC_DELETED", severity="WARNING", request=request,
        subject_type="doc", subject_id=doc.id,
        detail={"name": doc.name, "versions_deleted": len(versions)}, description=f"Document moved to rubbish: {doc.name}",
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Trash (continued) — restore/purge are two-segment routes so they don't
# have the "/trash" listing's ordering problem, same as "/{doc_id}/versions"
# etc. below the greedy "/{doc_id}" route.
# ---------------------------------------------------------------------------

@router.post("/{doc_id}/restore")
async def restore_doc(
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> dict[str, Any]:
    query = select(Doc).where(Doc.id == doc_id, Doc.deleted_at.is_not(None))
    if not auth.is_global_admin:
        query = query.where(Doc.tenant_id == auth.tenant_id)
    doc = (await db.execute(query)).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Deleted document not found in Rubbish")

    # A new, unrelated doc may have taken this name on this shelf while the
    # old one sat in Trash — restoring would otherwise silently create two
    # "current" versions of the same shelf+name pairing.
    collision = await _get_latest_doc_version(db, doc.shelf_id, doc.name)
    if collision:
        raise HTTPException(
            status_code=409,
            detail="A document with this name already exists on this shelf — rename or remove it before restoring",
        )

    versions_query = select(Doc).where(Doc.shelf_id == doc.shelf_id, Doc.name == doc.name, Doc.deleted_at.is_not(None))
    if not auth.is_global_admin:
        versions_query = versions_query.where(Doc.tenant_id == auth.tenant_id)
    versions = (await db.execute(versions_query)).scalars().all()
    for v in versions:
        v.deleted_at = None
    latest = max(versions, key=lambda v: v.version)
    await _fts_index_doc(db, latest)
    await audit_event(
        db=db, event_type="DOC_RESTORED", severity="INFO", request=request,
        subject_type="doc", subject_id=doc.id,
        detail={"name": doc.name, "versions_restored": len(versions)}, description=f"Document restored from Rubbish: {doc.name}",
    )
    await db.commit()
    return _doc_dict(latest, include_content=False)


@router.delete("/trash/{doc_id}", status_code=204)
async def purge_doc(
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    """Permanent, immediate purge of one Trash entry — the manual half of
    "purged after N days or via an admin empty-trash action"; the
    automatic half is the retention sweep in app/services/trash_sweep.py."""
    query = select(Doc).where(Doc.id == doc_id, Doc.deleted_at.is_not(None))
    if not auth.is_global_admin:
        query = query.where(Doc.tenant_id == auth.tenant_id)
    doc = (await db.execute(query)).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Deleted document not found in Rubbish")

    versions_query = select(Doc).where(Doc.shelf_id == doc.shelf_id, Doc.name == doc.name, Doc.deleted_at.is_not(None))
    if not auth.is_global_admin:
        versions_query = versions_query.where(Doc.tenant_id == auth.tenant_id)
    versions = (await db.execute(versions_query)).scalars().all()
    # Already removed at delete-time in the normal case (only the current
    # version is ever indexed) — this is just a defensive no-op safety net.
    await _fts_unindex_doc(db, doc.id)
    await audit_event(
        db=db, event_type="DOC_PURGED", severity="WARNING", request=request,
        subject_type="doc", subject_id=doc.id,
        detail={"name": doc.name, "versions_purged": len(versions)}, description=f"Document permanently purged from Rubbish: {doc.name}",
    )
    for v in versions:
        await db.delete(v)
    await db.commit()


class DocMove(BaseModel):
    shelf_id: str


@router.post("/{doc_id}/move")
async def move_doc(
    doc_id: str,
    body: DocMove,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    """Repoints every version of this document onto a different shelf, in
    place — the alternative today is delete-and-recreate, which loses
    every version and every annotation (Improvements Plan Stage 8)."""
    doc = await _get_current_doc_or_404(db, doc_id, auth)
    target_shelf = await _get_shelf_or_404(db, body.shelf_id, auth)
    if target_shelf.id == doc.shelf_id:
        raise HTTPException(status_code=400, detail="Document is already on this shelf")

    # Same two-part collision check as create_doc (Stage 7's lesson): the
    # destination shelf might already have a live doc with this name, or a
    # soft-deleted one still occupying (shelf_id, name, version) at the DB
    # level even though it's invisible to normal queries.
    live_collision = await _get_latest_doc_version(db, target_shelf.id, doc.name)
    if live_collision:
        raise HTTPException(status_code=409, detail="A document with this name already exists on the destination shelf")
    trashed_collision = (await db.execute(
        select(Doc).where(Doc.shelf_id == target_shelf.id, Doc.name == doc.name, Doc.deleted_at.is_not(None)).limit(1)
    )).scalar_one_or_none()
    if trashed_collision:
        raise HTTPException(
            status_code=409,
            detail="A document with this name is in Rubbish on the destination shelf — restore or purge it first",
        )

    versions_query = select(Doc).where(Doc.shelf_id == doc.shelf_id, Doc.name == doc.name, Doc.deleted_at.is_(None))
    if not auth.is_global_admin:
        versions_query = versions_query.where(Doc.tenant_id == auth.tenant_id)
    versions = (await db.execute(versions_query)).scalars().all()
    old_shelf_id = doc.shelf_id
    for v in versions:
        v.shelf_id = target_shelf.id
    await audit_event(
        db=db, event_type="DOC_MOVED", severity="INFO", request=request,
        subject_type="doc", subject_id=doc.id,
        detail={"name": doc.name, "from_shelf_id": old_shelf_id, "to_shelf_id": target_shelf.id, "versions_moved": len(versions)},
        description=f"Document moved: {doc.name}",
    )
    await db.commit()
    await db.refresh(doc)
    return _doc_dict(doc, include_content=False)


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

class AnnotationCreate(BaseModel):
    text: str
    color: str = "yellow"
    note: str | None = None
    prefix: str | None = None
    suffix: str | None = None


class AnnotationUpdate(BaseModel):
    color: str | None = None
    note: str | None = None


@router.get("/{doc_id}/annotations")
async def list_annotations(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> list[dict[str, Any]]:
    await _get_current_doc_or_404(db, doc_id, auth)
    query = select(DocAnnotation).where(DocAnnotation.doc_id == doc_id).order_by(DocAnnotation.created_at)
    rows = (await db.execute(query)).scalars().all()
    return [_annotation_dict(r) for r in rows]


@router.post("/{doc_id}/annotations", status_code=201)
async def create_annotation(
    doc_id: str,
    body: AnnotationCreate,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    await _get_current_doc_or_404(db, doc_id, auth)
    ann = DocAnnotation(
        doc_id=doc_id, text=body.text, color=body.color, note=body.note,
        prefix=body.prefix, suffix=body.suffix, created_by=auth.username,
    )
    db.add(ann)
    await db.commit()
    return _annotation_dict(ann)


@router.patch("/annotations/{annotation_id}")
async def update_annotation(
    annotation_id: str,
    body: AnnotationUpdate,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_WRITE_ROLES)),
) -> dict[str, Any]:
    ann = await _get_annotation_or_404(db, annotation_id, auth)
    if body.color is not None:
        ann.color = body.color
    if body.note is not None:
        ann.note = body.note
    await db.commit()
    return _annotation_dict(ann)


@router.delete("/annotations/{annotation_id}", status_code=204)
async def delete_annotation(
    annotation_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    ann = await _get_annotation_or_404(db, annotation_id, auth)
    await db.delete(ann)
    await db.commit()


# ---------------------------------------------------------------------------
# Help — serves docs_operations_guide.md parsed into sections, same pattern
# as jar_analyser.py's /help/sections and build_manager.py's guide-aware
# equivalent. "/help/sections" is two path segments, unlike "/search" above,
# so there's no risk of it being swallowed as doc_id="help" by the greedy
# "/{doc_id}" route regardless of registration order — no reordering needed.
# ---------------------------------------------------------------------------

def _find_docs_guide() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "Documentation" / "docs_operations_guide.md",
        Path("/opt/certmanager/Documentation/docs_operations_guide.md"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _parse_docs_guide_sections(content: str) -> list[dict]:
    sections: list[dict] = []
    current: dict | None = None
    fallback = 100
    for line in content.split("\n"):
        m = re.match(r"^## (\d+)\.\s+(.+)$", line)
        if m:
            if current:
                sections.append(current)
            current = {"id": m.group(1), "title": m.group(2).strip(), "content": ""}
            continue
        m2 = re.match(r"^## (.+)$", line)
        if m2:
            title = m2.group(1).strip()
            if title.lower() == "table of contents":
                continue
            if current:
                sections.append(current)
            fallback += 1
            current = {"id": str(fallback), "title": title, "content": ""}
            continue
        if current:
            current["content"] += line + "\n"
    if current:
        sections.append(current)
    return sections


@router.get("/help/sections")
async def get_docs_help_sections(
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    guide = _find_docs_guide()
    if not guide:
        return {"available": False, "sections": [], "error": "Docs guide not found"}
    sections = _parse_docs_guide_sections(guide.read_text(encoding="utf-8"))
    return {
        "available": True,
        "total_sections": len(sections),
        "sections": [{"id": s["id"], "title": s["title"]} for s in sections],
    }


@router.get("/help/sections/{section_id}")
async def get_docs_help_section(
    section_id: str,
    auth: AuthContext = Depends(require_role(*_ROLES)),
) -> dict[str, Any]:
    guide = _find_docs_guide()
    if not guide:
        return {"available": False, "content": "", "error": "Docs guide not found"}
    for s in _parse_docs_guide_sections(guide.read_text(encoding="utf-8")):
        if s["id"] == section_id:
            return {"available": True, "id": s["id"], "title": s["title"], "content": s["content"].strip()}
    return {"available": False, "content": "", "error": f"Section {section_id} not found"}
