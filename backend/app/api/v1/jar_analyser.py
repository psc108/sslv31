"""JAR Analyser REST API."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import AuthContext, require_role
from app.services.audit import audit_event
from app.models.jar_analyser import (
    JarUpload, AnalysisReport, SubReport,
    JarEndpoint, JarDependency, JarConfigFile,
    JarMigrationScript, JarEventFile, JarDiffReport, JarDtoSchema, JarWorkflow, JarErrorResponse,
    JarScheduledJob, JarDecompileRun, JarDecompiledClass, JarConfigExample, JarStringConstant,
    JarOutboundIntegration, JarOutboundCallSite,
)
from app.models.bug_tracker import Bug

router = APIRouter(prefix="/api/v1/jar-analyser", tags=["jar-analyser"])

_JAR_UPLOAD_DIR = settings.DATA_DIR / "jar_uploads"
_JAR_WORK_DIR = settings.DATA_DIR / "jar_work"
_MAX_JAR_MB = 5120  # 5 GB


# ---------------------------------------------------------------------------
# Upload & Analysis
# ---------------------------------------------------------------------------

@router.post("/upload", status_code=202)
async def upload_jar(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    label: str | None = Query(default=None),
    skip_if_duplicate: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith((".jar", ".war", ".zip")):
        raise HTTPException(status_code=422, detail="Only .jar, .war, and .zip bundle files are accepted")

    # Stream to disk in chunks — avoids loading multi-GB files into memory
    import hashlib as _hashlib
    _JAR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = _JAR_UPLOAD_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"_{uuid.uuid4().hex}_{file.filename}"

    sha256_h = _hashlib.sha256()
    md5_h = _hashlib.md5()
    size_bytes = 0
    max_bytes = _MAX_JAR_MB * 1024 * 1024
    try:
        with tmp_path.open("wb") as fout:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    tmp_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"File exceeds {_MAX_JAR_MB // 1024} GB limit")
                sha256_h.update(chunk)
                md5_h.update(chunk)
                fout.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Upload write failed: {e}")

    sha256 = sha256_h.hexdigest()
    md5 = md5_h.hexdigest()

    # Deduplication check — scoped to the caller's own tenant. Without this,
    # a matching sha256 uploaded by a different tenant would surface that
    # tenant's upload/report IDs here (and, with skip_if_duplicate, let the
    # caller silently "skip" onto data that isn't theirs).
    dedup_query = select(JarUpload).where(JarUpload.sha256 == sha256).limit(1)
    if not auth.is_global_admin:
        dedup_query = dedup_query.where(JarUpload.tenant_id == auth.tenant_id)
    existing = await db.execute(dedup_query)
    dup_upload = existing.scalar_one_or_none()
    if dup_upload and skip_if_duplicate:
        tmp_path.unlink(missing_ok=True)
        existing_report = await db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.upload_id == dup_upload.id, AnalysisReport.status == "completed")
            .order_by(AnalysisReport.analysis_completed_at.desc())
            .limit(1)
        )
        rep = existing_report.scalar_one_or_none()
        return {
            "upload_id": dup_upload.id,
            "report_id": rep.id if rep else None,
            "status": "duplicate_skipped",
            "duplicate": True,
            "existing_report_id": rep.id if rep else None,
            "filename": file.filename,
            "size_bytes": size_bytes,
            "sha256": sha256,
        }

    # Move temp file to final content-addressed location
    date_dir = _JAR_UPLOAD_DIR / datetime.now(timezone.utc).strftime("%Y/%m/%d") / sha256[:12]
    date_dir.mkdir(parents=True, exist_ok=True)
    stored_path = date_dir / file.filename
    tmp_path.rename(stored_path)

    upload = JarUpload(
        id=str(uuid.uuid4()),
        filename=stored_path.name,
        original_name=file.filename,
        sha256=sha256,
        md5=md5,
        size_bytes=size_bytes,
        stored_path=str(stored_path),
        uploaded_by=auth.username,
        label=label,
        status="pending",
        tenant_id=auth.tenant_id,
    )
    db.add(upload)
    await audit_event(
        db=db, event_type="JAR_UPLOADED", severity="INFO", request=request,
        subject_type="jar_upload", subject_id=upload.id,
        detail={"filename": file.filename, "size_bytes": size_bytes, "sha256": sha256},
        description=f"JAR uploaded: {file.filename}",
    )
    await db.commit()

    # Kick off background analysis
    background_tasks.add_task(_run_analysis, upload.id, str(stored_path))

    return {
        "upload_id": upload.id,
        "report_id": None,
        "status": "analysing",
        "duplicate": dup_upload is not None,
        "existing_report_id": None,
        "filename": file.filename,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "status_url": f"/api/v1/jar-analyser/uploads/{upload.id}/status",
    }


async def _run_analysis(upload_id: str, jar_path_str: str) -> None:
    """Background task — runs the analysis job."""
    from app.core.database import async_session
    from app.services.jar_analyser.job import AnalysisJob

    jar_path = Path(jar_path_str)
    work_dir = _JAR_WORK_DIR / upload_id
    work_dir.mkdir(parents=True, exist_ok=True)

    async with async_session() as db:
        result = await db.execute(select(JarUpload).where(JarUpload.id == upload_id))
        upload = result.scalar_one_or_none()
        if not upload:
            return
        job = AnalysisJob(upload, jar_path, work_dir)
        try:
            await job.run(db)
        except Exception:
            pass  # errors already persisted by job.run


@router.get("/uploads/{upload_id}/status")
async def get_upload_status(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    upload = await _get_upload_or_404(db, upload_id, auth)
    report = await db.execute(
        select(AnalysisReport)
        .where(AnalysisReport.upload_id == upload_id)
        .order_by(AnalysisReport.analysis_started_at.desc())
        .limit(1)
    )
    rep = report.scalar_one_or_none()
    return {
        "upload_id": upload_id,
        "status": upload.status,
        "report_id": rep.id if rep else None,
        "started_at": rep.analysis_started_at.isoformat() if rep and rep.analysis_started_at else None,
        "completed_at": rep.analysis_completed_at.isoformat() if rep and rep.analysis_completed_at else None,
        "duration_ms": rep.analysis_duration_ms if rep else None,
    }


# ---------------------------------------------------------------------------
# Report Retrieval
# ---------------------------------------------------------------------------

@router.get("/reports")
async def list_reports(
    q: str | None = Query(default=None),
    jar_type: str | None = Query(default=None),
    version: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    query = (
        select(AnalysisReport, JarUpload)
        .join(JarUpload, AnalysisReport.upload_id == JarUpload.id)
        .where(AnalysisReport.status == "completed")
        .order_by(AnalysisReport.analysis_completed_at.desc())
    )
    if not auth.is_global_admin:
        query = query.where(AnalysisReport.tenant_id == auth.tenant_id)
    if jar_type:
        query = query.where(AnalysisReport.jar_type == jar_type)
    if version:
        query = query.where(AnalysisReport.implementation_version == version)
    if q:
        like = f"%{q}%"
        query = query.where(
            AnalysisReport.implementation_title.ilike(like) |
            AnalysisReport.implementation_version.ilike(like) |
            JarUpload.original_name.ilike(like)
        )

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).all()

    items = []
    for rep, upload in rows:
        summary = json.loads(rep.summary_json) if rep.summary_json else {}
        items.append({
            "report_id": rep.id,
            "upload_id": upload.id,
            "filename": upload.original_name,
            "label": upload.label,
            "jar_type": rep.jar_type,
            "implementation_title": rep.implementation_title,
            "implementation_version": rep.implementation_version,
            "implementation_vendor": rep.implementation_vendor,
            "spring_boot_version": rep.spring_boot_version,
            "service_count": summary.get("nested_jar_count", 0),
            "endpoint_count": summary.get("total_endpoint_count", 0),
            "uploaded_at": upload.uploaded_at.isoformat() if upload.uploaded_at else None,
            "analysis_completed_at": rep.analysis_completed_at.isoformat() if rep.analysis_completed_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size)}


# Registered as its own top-level path (not nested under /reports/{report_id})
# since this deliberately searches across every analysed jar at once — "which
# service logs this message" is a question about the whole install, not one
# already-open report. See JarStringConstant's model docstring for what's
# actually indexed here (literal string constants from bytecode, extracted
# automatically at analysis time, not on-demand like decompilation).
@router.get("/strings/search")
async def search_string_constants(
    q: str = Query(..., min_length=1),
    report_id: str | None = Query(default=None, description="Scope to one already-analysed upload (a jar-of-jars' own nested services) instead of every analysed jar"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    if report_id:
        # Tenant-checks report_id before scoping to it — same reasoning as
        # the plain /search endpoint's own report_id handling.
        await _get_report_or_404(db, report_id, auth)

    query = (
        select(JarStringConstant, SubReport, AnalysisReport, JarUpload)
        .join(SubReport, JarStringConstant.sub_report_id == SubReport.id)
        .join(AnalysisReport, SubReport.parent_report_id == AnalysisReport.id)
        .join(JarUpload, AnalysisReport.upload_id == JarUpload.id)
        .where(AnalysisReport.status == "completed")
    )
    if report_id:
        query = query.where(AnalysisReport.id == report_id)
    elif not auth.is_global_admin:
        query = query.where(AnalysisReport.tenant_id == auth.tenant_id)

    # FTS5 when available (same "1000-row candidate cap, rank in Python"
    # shape as docs.py's search_docs) — falling back to ILIKE on the real
    # column on Postgres/MySQL, where jar_strings_fts doesn't exist.
    ranked_ids: list[str] | None = None
    snippet_by_id: dict[str, str] = {}
    if settings.is_sqlite:
        fts_rows = (await db.execute(
            text(
                "SELECT id, snippet(jar_strings_fts, 1, '**', '**', '…', 20) AS snip FROM jar_strings_fts "
                "WHERE jar_strings_fts MATCH :match ORDER BY bm25(jar_strings_fts) LIMIT 1000"
            ),
            {"match": _strings_fts_match_query(q)},
        )).all()
        ranked_ids = [r.id for r in fts_rows]
        snippet_by_id = {r.id: r.snip for r in fts_rows}
        if not ranked_ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 1}
        query = query.where(JarStringConstant.id.in_(ranked_ids))
    else:
        like = f"%{q}%"
        query = query.where(JarStringConstant.value.ilike(like))

    all_rows = (await db.execute(query)).all()
    if ranked_ids is not None:
        rank_index = {rid: i for i, rid in enumerate(ranked_ids)}
        all_rows = sorted(all_rows, key=lambda r: rank_index.get(r[0].id, len(ranked_ids)))
    total = len(all_rows)
    start = (page - 1) * page_size
    page_rows = all_rows[start:start + page_size]

    items = [
        {
            "id": sc.id,
            "report_id": rep.id,
            "sub_report_id": sub.id,
            "class_name": sc.class_name,
            "value": sc.value,
            "snippet": snippet_by_id.get(sc.id),
            "service_name": sub.service_name or sub.filename,
            "filename": sub.filename,
            "upload_filename": upload.original_name,
            "jar_type": rep.jar_type,
        }
        for sc, sub, rep, upload in page_rows
    ]
    return {
        "items": items,
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def _strings_fts_match_query(q: str) -> str:
    """Same safe-tokenisation shape as docs.py's own _fts_match_query —
    duplicated locally rather than imported cross-module, matching how
    bug_similarity.py built its own variant rather than reaching into
    docs.py's private helper."""
    import re
    terms = re.findall(r"\w+", q)
    if not terms:
        return '""'
    return " ".join(f'"{t}"*' for t in terms)


async def _related_bugs_summary(db: AsyncSession, rep: AnalysisReport, auth: AuthContext) -> list[dict[str, Any]] | None:
    """Resolves Improvements Plan Stage 12's related_bug_ids_json to real
    bug summaries, best-first (rank preserved — the ids were already ranked
    when the scan stored them, a second query has no ranking of its own to
    apply). None means "not yet scanned" (see the model column's own
    docstring); [] means "scanned, nothing found" — both are valid, only
    the frontend needs to tell them apart, this just passes the
    distinction through. Tenant-filtered defensively even though the ids
    stored were already scoped to the report's own tenant at scan time —
    matches this codebase's established belt-and-braces pattern for every
    other cross-entity lookup."""
    if rep.related_bug_ids_json is None:
        return None
    ids = json.loads(rep.related_bug_ids_json)
    if not ids:
        return []
    query = select(Bug).where(Bug.id.in_(ids), Bug.deleted_at.is_(None))
    if not auth.is_global_admin:
        query = query.where(Bug.tenant_id == auth.tenant_id)
    bugs = (await db.execute(query)).scalars().all()
    rank_index = {bid: i for i, bid in enumerate(ids)}
    ranked = sorted(bugs, key=lambda b: rank_index.get(b.id, len(ids)))
    return [{"id": b.id, "title": b.title, "status": b.status, "severity": b.severity} for b in ranked]


@router.get("/reports/{report_id}")
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    rep, upload = await _get_report_and_upload_or_404(db, report_id, auth)
    sub_result = await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
        .order_by(SubReport.service_name)
    )
    subs = sub_result.scalars().all()

    return {
        "report_id": rep.id,
        "upload_id": upload.id,
        "created_at": rep.analysis_completed_at.isoformat() if rep.analysis_completed_at else None,
        "jar_file": {
            "original_filename": upload.original_name,
            "sha256": upload.sha256,
            "size_bytes": upload.size_bytes,
            "stored_path": upload.stored_path,
        },
        "jar_type": rep.jar_type,
        "detection_confidence": rep.detection_confidence,
        "manifest": json.loads(rep.manifest_json) if rep.manifest_json else {},
        "summary": json.loads(rep.summary_json) if rep.summary_json else {},
        "nested_jars": [_sub_summary(s) for s in subs],
        "analyser_version": rep.analyser_version,
        "analysis_duration_ms": rep.analysis_duration_ms,
        "status": rep.status,
        "warnings": json.loads(rep.warnings_json) if rep.warnings_json else [],
        "errors": json.loads(rep.errors_json) if rep.errors_json else [],
        "consistency_findings": json.loads(rep.consistency_findings_json) if rep.consistency_findings_json else [],
        "infra_requirements": json.loads(rep.infra_requirements_json) if rep.infra_requirements_json else None,
        "actuator_exposure": json.loads(rep.actuator_exposure_json) if rep.actuator_exposure_json else None,
        "related_bugs": await _related_bugs_summary(db, rep, auth),
    }


@router.get("/reports/{report_id}/sub-reports")
async def list_sub_reports(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    await _get_report_or_404(db, report_id, auth)
    result = await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
        .order_by(SubReport.service_name)
    )
    return [_sub_summary(s) for s in result.scalars().all()]


@router.get("/reports/{report_id}/sub-reports/{sub_id}")
async def get_sub_report(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    sub = await _get_sub_or_404(db, report_id, sub_id, auth)
    return _sub_full(sub)


@router.get("/reports/{report_id}/sub-reports/{sub_id}/endpoints")
async def list_endpoints(
    report_id: str,
    sub_id: str,
    http_method: str | None = Query(default=None),
    path_contains: str | None = Query(default=None),
    confidence: str | None = Query(default=None),
    auth_filter: str | None = Query(default=None),
    paginated_only: bool = Query(default=False),
    deprecated_only: bool = Query(default=False),
    hide_deprecated: bool = Query(default=False),
    internal_only: bool = Query(default=False),
    hide_internal: bool = Query(default=False),
    opaque_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    query = select(JarEndpoint).where(JarEndpoint.sub_report_id == sub_id)
    if http_method:
        query = query.where(JarEndpoint.http_method == http_method.upper())
    if path_contains:
        query = query.where(JarEndpoint.full_path.ilike(f"%{path_contains}%"))
    if confidence:
        query = query.where(JarEndpoint.confidence == confidence.upper())
    if paginated_only:
        query = query.where(JarEndpoint.is_paginated == True)  # noqa: E712
    if deprecated_only:
        query = query.where(JarEndpoint.is_deprecated == True)  # noqa: E712
    if hide_deprecated:
        query = query.where(JarEndpoint.is_deprecated == False)  # noqa: E712
    if internal_only:
        query = query.where(JarEndpoint.is_proxied == False)  # noqa: E712
    if hide_internal:
        query = query.where(
            (JarEndpoint.is_proxied == True) | (JarEndpoint.is_proxied == None)  # noqa: E711,E712
        )
    if opaque_only:
        query = query.where(JarEndpoint.payload_shape_known == False)  # noqa: E712
    if auth_filter:
        if auth_filter == "public":
            query = query.where(
                (JarEndpoint.security_json == None) |  # noqa: E711
                JarEndpoint.parsed_auth_json.ilike('%"public": true%')
            )
        elif auth_filter == "authenticated":
            query = query.where(JarEndpoint.security_json != None)  # noqa: E711
        elif auth_filter.startswith("role:"):
            role = auth_filter[5:].upper()
            query = query.where(JarEndpoint.parsed_auth_json.ilike(f'%"{role}"%'))
        elif auth_filter.startswith("authority:"):
            authority = auth_filter[10:]
            query = query.where(JarEndpoint.parsed_auth_json.ilike(f'%"{authority}"%'))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {
        "items": [_endpoint_dict(e) for e in rows],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/reports/{report_id}/sub-reports/{sub_id}/dependencies")
async def list_dependencies(
    report_id: str,
    sub_id: str,
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    query = select(JarDependency).where(JarDependency.sub_report_id == sub_id)
    if category:
        query = query.where(JarDependency.category == category)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {
        "items": [_dep_dict(d) for d in rows],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/reports/{report_id}/sub-reports/{sub_id}/strings")
async def list_string_constants(
    report_id: str,
    sub_id: str,
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """This sub-report's own string constants, browsable/filterable —
    scoped to one jar (unlike GET /strings/search, which searches every
    analysed jar at once). Plain ILIKE, not FTS5: one sub-report's own rows
    are a small enough set that ranked full-text search adds no value over
    a simple substring filter here."""
    await _get_sub_or_404(db, report_id, sub_id, auth)
    query = select(JarStringConstant).where(JarStringConstant.sub_report_id == sub_id)
    if q:
        query = query.where(JarStringConstant.value.ilike(f"%{q}%"))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(
        query.order_by(JarStringConstant.class_name).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {
        "items": [{"id": s.id, "class_name": s.class_name, "value": s.value} for s in rows],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def _outbound_dict(oi: JarOutboundIntegration) -> dict[str, Any]:
    return {
        "id": oi.id, "kind": oi.kind, "class_name": oi.class_name, "target": oi.target,
        "config_key": oi.config_key, "raw_value": oi.raw_value, "resolved_value": oi.resolved_value,
    }


@router.get("/reports/{report_id}/sub-reports/{sub_id}/outbound-integrations")
async def list_outbound_integrations(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    """This sub-report's own statically-discovered outbound integrations —
    see JarOutboundIntegration's model docstring for what "statically
    discovered" does and doesn't prove."""
    await _get_sub_or_404(db, report_id, sub_id, auth)
    rows = (await db.execute(
        select(JarOutboundIntegration).where(JarOutboundIntegration.sub_report_id == sub_id)
        .order_by(JarOutboundIntegration.class_name)
    )).scalars().all()
    return [_outbound_dict(r) for r in rows]


@router.get("/reports/{report_id}/outbound-integrations")
async def list_report_outbound_integrations(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    """Every outbound integration signal across every service in this one
    upload — the "which of our services talk to which external systems"
    view for a jar-of-jars bundle, without needing to open each service's
    own tab one at a time."""
    await _get_report_or_404(db, report_id, auth)
    rows = (await db.execute(
        select(JarOutboundIntegration, SubReport)
        .join(SubReport, JarOutboundIntegration.sub_report_id == SubReport.id)
        .where(SubReport.parent_report_id == report_id)
        .order_by(SubReport.service_name, JarOutboundIntegration.class_name)
    )).all()
    return [
        {**_outbound_dict(oi), "sub_report_id": sub.id, "service_name": sub.service_name or sub.filename}
        for oi, sub in rows
    ]


def _call_site_dict(cs: JarOutboundCallSite) -> dict[str, Any]:
    return {
        "id": cs.id, "engine": cs.engine, "class_name": cs.class_name, "method_name": cs.method_name,
        "call_type": cs.call_type, "call_snippet": cs.call_snippet, "response_type": cs.response_type,
        "caught_exceptions": json.loads(cs.caught_exceptions_json) if cs.caught_exceptions_json else [],
        "thrown_exceptions": json.loads(cs.thrown_exceptions_json) if cs.thrown_exceptions_json else [],
        "status_checks": json.loads(cs.status_checks_json) if cs.status_checks_json else [],
    }


@router.get("/reports/{report_id}/sub-reports/{sub_id}/outbound-call-sites")
async def list_outbound_call_sites(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    """Response-shape / error-handling signals found by text-scanning this
    sub-report's own already-decompiled classes — see
    outbound_call_analysis.py's module docstring. Empty until at least one
    class in this jar has been decompiled (Section 36) — this never runs
    automatically, unlike outbound-integrations above."""
    await _get_sub_or_404(db, report_id, sub_id, auth)
    rows = (await db.execute(
        select(JarOutboundCallSite).where(JarOutboundCallSite.sub_report_id == sub_id)
        .order_by(JarOutboundCallSite.class_name)
    )).scalars().all()
    return [_call_site_dict(r) for r in rows]


@router.get("/reports/{report_id}/outbound-call-sites")
async def list_report_outbound_call_sites(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    """Every outbound call site signal across every service in this upload
    that's actually been decompiled — services never decompiled simply
    don't appear, since this data only exists once source text does."""
    await _get_report_or_404(db, report_id, auth)
    rows = (await db.execute(
        select(JarOutboundCallSite, SubReport)
        .join(SubReport, JarOutboundCallSite.sub_report_id == SubReport.id)
        .where(SubReport.parent_report_id == report_id)
        .order_by(SubReport.service_name, JarOutboundCallSite.class_name)
    )).all()
    return [
        {**_call_site_dict(cs), "sub_report_id": sub.id, "service_name": sub.service_name or sub.filename}
        for cs, sub in rows
    ]


@router.get("/reports/{report_id}/sub-reports/{sub_id}/config")
async def list_config_files(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    result = await db.execute(select(JarConfigFile).where(JarConfigFile.sub_report_id == sub_id))
    return [_config_dict(c) for c in result.scalars().all()]


@router.get("/reports/{report_id}/sub-reports/{sub_id}/migrations")
async def list_migrations(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    result = await db.execute(
        select(JarMigrationScript).where(JarMigrationScript.sub_report_id == sub_id)
        .order_by(JarMigrationScript.version)
    )
    scripts = result.scalars().all()

    from app.services.jar_analyser.schema_reconstructor import reconstruct_schema, score_migration_risk
    # Replay migrations in order to score each one against the schema state before it runs
    schema_state: dict = {}
    enriched: list[dict] = []
    for m in scripts:
        m_dict = _migration_dict(m)
        risk_result = score_migration_risk(m_dict, schema_state)
        m_dict["risk"] = risk_result["risk"]
        m_dict["risk_reasons"] = risk_result["reasons"]
        enriched.append(m_dict)
        # Advance schema state by applying this script
        from app.services.jar_analyser.schema_reconstructor import _apply_script
        _apply_script(m.content or "", schema_state)
    return enriched


@router.get("/reports/{report_id}/sub-reports/{sub_id}/events")
async def list_events(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    result = await db.execute(select(JarEventFile).where(JarEventFile.sub_report_id == sub_id))
    return [_event_dict(e) for e in result.scalars().all()]


@router.get("/reports/{report_id}/sub-reports/{sub_id}/workflows")
async def list_workflows(
    report_id: str,
    sub_id: str,
    source: str | None = Query(default=None),  # auto_detected | manual
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    query = select(JarWorkflow).where(JarWorkflow.sub_report_id == sub_id)
    if source:
        query = query.where(JarWorkflow.source == source)
    result = await db.execute(query.order_by(JarWorkflow.name))
    return [_workflow_dict(w) for w in result.scalars().all()]


@router.get("/reports/{report_id}/sub-reports/{sub_id}/scheduled-jobs")
async def list_scheduled_jobs(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    result = await db.execute(
        select(JarScheduledJob).where(JarScheduledJob.sub_report_id == sub_id)
        .order_by(JarScheduledJob.declaring_class_simple, JarScheduledJob.method_name)
    )
    return [_scheduled_job_dict(j) for j in result.scalars().all()]


class WorkflowUpload(BaseModel):
    yaml_content: str


@router.post("/reports/{report_id}/sub-reports/{sub_id}/workflows", status_code=201)
async def upload_workflows(
    report_id: str,
    sub_id: str,
    body: WorkflowUpload,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> list[dict[str, Any]]:
    """Parse a workflows.yml and persist as manual workflows for this sub-report."""
    await _get_sub_or_404(db, report_id, sub_id, auth)

    # Load existing endpoints for reference matching
    ep_rows = (await db.execute(
        select(JarEndpoint).where(JarEndpoint.sub_report_id == sub_id)
    )).scalars().all()
    endpoints = [_endpoint_dict(e) for e in ep_rows]

    from app.services.jar_analyser.workflows import WorkflowDetector
    try:
        workflows = WorkflowDetector.from_yaml(body.yaml_content, endpoints)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    created = []
    for wf in workflows:
        row = JarWorkflow(
            sub_report_id=sub_id,
            name=wf.name,
            description=wf.description,
            category=wf.category,
            source="manual",
            steps_json=json.dumps([
                {
                    "name": s.name, "method": s.method, "path": s.path,
                    "description": s.description, "input_from": s.input_from,
                    "output": s.output, "query_params": s.query_params,
                    "body_fields": s.body_fields, "poll_until": s.poll_until,
                    "endpoint_ref": s.endpoint_ref,
                }
                for s in wf.steps
            ]),
        )
        db.add(row)
        await db.flush()
        created.append(_workflow_dict(row))

    await db.commit()
    return created


@router.get("/reports/{report_id}/sub-reports/{sub_id}/schema-reconstruction")
async def get_schema_reconstruction(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Reconstruct the current DB schema by replaying Flyway migrations in version order."""
    await _get_sub_or_404(db, report_id, sub_id, auth)
    migrations = (await db.execute(
        select(JarMigrationScript)
        .where(JarMigrationScript.sub_report_id == sub_id)
        .order_by(JarMigrationScript.version)
    )).scalars().all()

    from app.services.jar_analyser.schema_reconstructor import reconstruct_schema, schema_to_dict
    tables = reconstruct_schema([_migration_dict(m) for m in migrations])
    return {
        "sub_report_id": sub_id,
        "migration_count": len(migrations),
        "table_count": len(tables),
        "tables": schema_to_dict(tables),
    }


@router.get("/reports/{report_id}/sub-reports/{sub_id}/errors")
async def list_error_responses(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    result = await db.execute(
        select(JarErrorResponse)
        .where(JarErrorResponse.sub_report_id == sub_id)
        .order_by(JarErrorResponse.http_status)
    )
    return [_error_response_dict(e) for e in result.scalars().all()]


@router.get("/reports/{report_id}/sub-reports/{sub_id}/endpoints/{ep_id}/examples")
async def get_endpoint_examples(
    report_id: str,
    sub_id: str,
    ep_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Generate request/response JSON examples for a single endpoint."""
    await _get_sub_or_404(db, report_id, sub_id, auth)
    ep_row = (await db.execute(
        select(JarEndpoint).where(JarEndpoint.id == ep_id, JarEndpoint.sub_report_id == sub_id)
    )).scalar_one_or_none()
    if not ep_row:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    dto_rows = (await db.execute(
        select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub_id)
    )).scalars().all()
    all_schemas = {
        s.simple_name: {
            "is_enum": s.is_enum,
            "enum_values": json.loads(s.enum_values_json) if s.enum_values_json else [],
            "fields": json.loads(s.fields_json) if s.fields_json else [],
        }
        for s in dto_rows
    }

    from app.services.jar_analyser.example_generator import generate_examples
    ep_dict = _endpoint_dict(ep_row)
    return generate_examples(ep_dict, all_schemas)


@router.get("/reports/{report_id}/sub-reports/{sub_id}/schemas")
async def list_schemas(
    report_id: str,
    sub_id: str,
    enums_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    query = select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub_id)
    if enums_only:
        query = query.where(JarDtoSchema.is_enum == True)  # noqa: E712
    result = await db.execute(query.order_by(JarDtoSchema.simple_name))
    return [_schema_dict(s) for s in result.scalars().all()]


@router.get("/reports/{report_id}/sub-reports/{sub_id}/schemas/{class_name:path}")
async def get_schema(
    report_id: str,
    sub_id: str,
    class_name: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    result = await db.execute(
        select(JarDtoSchema).where(
            JarDtoSchema.sub_report_id == sub_id,
            JarDtoSchema.class_name == class_name,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Schema not found")
    return _schema_dict(obj)


@router.get("/reports/{report_id}/sub-reports/{sub_id}/config-examples")
async def list_config_examples(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    """Config/design documents discovered for this service — e.g. a
    CompositeDesign. Most services have none; an empty list here is the
    normal case, not an error, and the frontend hides the tab accordingly."""
    await _get_sub_or_404(db, report_id, sub_id, auth)
    result = await db.execute(
        select(JarConfigExample)
        .where(JarConfigExample.sub_report_id == sub_id)
        .order_by(JarConfigExample.root_class_name)
    )
    return [
        {"root_class_name": e.root_class_name, "format": e.format, "source": e.source}
        for e in result.scalars().all()
    ]


@router.get("/reports/{report_id}/sub-reports/{sub_id}/config-examples/{root_class:path}")
async def get_config_example(
    report_id: str,
    sub_id: str,
    root_class: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    result = await db.execute(
        select(JarConfigExample).where(
            JarConfigExample.sub_report_id == sub_id,
            JarConfigExample.root_class_name == root_class,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Config example not found")
    return {
        "root_class_name": obj.root_class_name, "format": obj.format,
        "source": obj.source, "content": obj.content,
    }


@router.get("/search")
async def search(
    q: str = Query(min_length=2),
    report_id: str | None = Query(default=None),
    category: str | None = Query(default=None),  # endpoints|dependencies|config|schemas|events|migrations
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=40, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Full-text search across all JAR analyser data."""
    like = f"%{q}%"
    hits: list[dict] = []

    # Resolve which sub_report_ids to search
    if report_id:
        # Tenant-checks report_id (404s if it isn't the caller's) before
        # searching within it — this endpoint previously took report_id as
        # plain unchecked input, letting any authenticated user search
        # inside any tenant's report just by knowing its ID.
        await _get_report_or_404(db, report_id, auth)
        sub_rows = (await db.execute(
            select(SubReport).where(SubReport.parent_report_id == report_id)
        )).scalars().all()
    else:
        # All completed reports — tenant-scoped the same way list_reports is.
        completed_query = select(AnalysisReport).where(AnalysisReport.status == "completed")
        if not auth.is_global_admin:
            completed_query = completed_query.where(AnalysisReport.tenant_id == auth.tenant_id)
        completed = (await db.execute(completed_query)).scalars().all()
        rep_ids = [r.id for r in completed]
        if not rep_ids:
            return {"q": q, "total": 0, "hits": [], "page": page, "pages": 1}
        sub_rows = (await db.execute(
            select(SubReport).where(SubReport.parent_report_id.in_(rep_ids))
        )).scalars().all()

    sub_ids = [s.id for s in sub_rows]
    sub_map = {s.id: s for s in sub_rows}

    # Build report_id lookup for each sub
    sub_to_report: dict[str, str] = {s.id: s.parent_report_id for s in sub_rows}

    if not sub_ids:
        return {"q": q, "total": 0, "hits": [], "page": page, "pages": 1}

    def _ctx(sub_id: str) -> dict:
        s = sub_map[sub_id]
        return {
            "report_id": sub_to_report[sub_id],
            "sub_report_id": sub_id,
            "service_name": s.service_name or s.filename,
        }

    if not category or category == "endpoints":
        rows = (await db.execute(
            select(JarEndpoint).where(
                JarEndpoint.sub_report_id.in_(sub_ids),
                JarEndpoint.full_path.ilike(like)
                | JarEndpoint.controller_class.ilike(like)
                | JarEndpoint.method_name.ilike(like)
                | JarEndpoint.parameters_json.ilike(like)
                | JarEndpoint.return_type_json.ilike(like)
                | JarEndpoint.security_json.ilike(like)
                | JarEndpoint.request_body_json.ilike(like),
            )
        )).scalars().all()
        for e in rows:
            hits.append({
                "category": "endpoint",
                "title": f"{e.http_method} {e.full_path}",
                "detail": e.controller_simple,
                "extra": json.loads(e.security_json).get("expression", "") if e.security_json else "",
                **_ctx(e.sub_report_id),
            })

    if not category or category == "dependencies":
        rows = (await db.execute(
            select(JarDependency).where(
                JarDependency.sub_report_id.in_(sub_ids),
                JarDependency.maven_coordinates.ilike(like)
                | JarDependency.group_id.ilike(like)
                | JarDependency.artifact_id.ilike(like)
                | JarDependency.manifest_title.ilike(like),
            )
        )).scalars().all()
        for d in rows:
            hits.append({
                "category": "dependency",
                "title": d.maven_coordinates or f"{d.group_id}:{d.artifact_id}",
                "detail": d.version or "",
                "extra": d.category or "",
                **_ctx(d.sub_report_id),
            })

    if not category or category == "config":
        rows = (await db.execute(
            select(JarConfigFile).where(
                JarConfigFile.sub_report_id.in_(sub_ids),
                JarConfigFile.keys_json.ilike(like)
                | JarConfigFile.content.ilike(like)
                | JarConfigFile.filename.ilike(like),
            )
        )).scalars().all()
        for c in rows:
            # Find the specific matching keys
            keys = json.loads(c.keys_json) if c.keys_json else []
            matching_keys = [
                k for k in keys
                if q.lower() in (k.get("key") or "").lower()
                or q.lower() in (k.get("value") or "").lower()
            ]
            if matching_keys:
                for k in matching_keys[:5]:  # cap per file
                    hits.append({
                        "category": "config",
                        "title": f"{c.filename}: {k.get('key', '')}",
                        "detail": str(k.get("value", ""))[:120],
                        "extra": c.profile or "",
                        **_ctx(c.sub_report_id),
                    })
            else:
                hits.append({
                    "category": "config",
                    "title": c.filename,
                    "detail": "",
                    "extra": c.profile or "",
                    **_ctx(c.sub_report_id),
                })

    if not category or category == "schemas":
        rows = (await db.execute(
            select(JarDtoSchema).where(
                JarDtoSchema.sub_report_id.in_(sub_ids),
                JarDtoSchema.class_name.ilike(like)
                | JarDtoSchema.simple_name.ilike(like)
                | JarDtoSchema.fields_json.ilike(like)
                | JarDtoSchema.enum_values_json.ilike(like),
            )
        )).scalars().all()
        for s in rows:
            # Find matching fields
            fields = json.loads(s.fields_json) if s.fields_json else []
            matching = [f for f in fields if q.lower() in (f.get("json_name") or "").lower()
                        or q.lower() in (f.get("java_type") or "").lower()]
            detail = ", ".join(f["json_name"] for f in matching[:4]) if matching else ""
            hits.append({
                "category": "schema",
                "title": s.simple_name,
                "detail": detail,
                "extra": "enum" if s.is_enum else "dto",
                **_ctx(s.sub_report_id),
            })

    if not category or category == "events":
        rows = (await db.execute(
            select(JarEventFile).where(
                JarEventFile.sub_report_id.in_(sub_ids),
                JarEventFile.published_json.ilike(like)
                | JarEventFile.consumed_json.ilike(like)
                | JarEventFile.content.ilike(like),
            )
        )).scalars().all()
        for e in rows:
            hits.append({
                "category": "event",
                "title": e.filename,
                "detail": "",
                "extra": "",
                **_ctx(e.sub_report_id),
            })

    if not category or category == "migrations":
        rows = (await db.execute(
            select(JarMigrationScript).where(
                JarMigrationScript.sub_report_id.in_(sub_ids),
                JarMigrationScript.content.ilike(like)
                | JarMigrationScript.description.ilike(like)
                | JarMigrationScript.filename.ilike(like)
                | JarMigrationScript.tables_json.ilike(like),
            )
        )).scalars().all()
        for m in rows:
            hits.append({
                "category": "migration",
                "title": m.filename,
                "detail": m.description or "",
                "extra": m.version or "",
                **_ctx(m.sub_report_id),
            })

    total = len(hits)
    start = (page - 1) * page_size
    pages = max(1, (total + page_size - 1) // page_size)
    return {
        "q": q,
        "total": total,
        "page": page,
        "pages": pages,
        "hits": hits[start:start + page_size],
    }



@router.get("/reports/{report_id}/export/json")
async def export_report_json(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    report_dict = await get_report(report_id, db, auth)
    sub_list = await list_sub_reports(report_id, db, auth)
    from app.services.jar_analyser.export import report_to_json
    content = report_to_json(report_dict, sub_list)
    return Response(content=content, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="report-{report_id}.json"'})


@router.get("/reports/{report_id}/export/markdown")
async def export_report_markdown(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> PlainTextResponse:
    report_dict = await get_report(report_id, db, auth)
    sub_list = await list_sub_reports(report_id, db, auth)
    # Enrich sub_list with full data for export
    full_subs = []
    for s in sub_list:
        full = await get_sub_report(report_id, s["sub_report_id"], db, auth)
        full_subs.append(full)
    from app.services.jar_analyser.export import report_to_markdown
    content = report_to_markdown(report_dict, full_subs)
    return PlainTextResponse(content=content, media_type="text/markdown",
                              headers={"Content-Disposition": f'attachment; filename="report-{report_id}.md"'})


@router.get("/reports/{report_id}/sub-reports/{sub_id}/export/openapi")
async def export_sub_openapi(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    sub = await _get_sub_or_404(db, report_id, sub_id, auth)
    endpoints = (await db.execute(
        select(JarEndpoint).where(JarEndpoint.sub_report_id == sub_id)
    )).scalars().all()
    dto_schemas = (await db.execute(
        select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub_id)
    )).scalars().all()

    service = sub.service_name or sub.filename
    port = sub.declared_port or 8080
    version = sub.implementation_version or "1.0.0"

    # Build components/schemas from extracted DTOs
    components_schemas: dict = {}
    for dto in dto_schemas:
        if dto.is_enum:
            values = json.loads(dto.enum_values_json) if dto.enum_values_json else []
            serialised = [v.get("serialised_as", v.get("name", "")) for v in values]
            components_schemas[dto.simple_name] = {
                "type": "string",
                "enum": serialised,
                "x-java-class": dto.class_name,
            }
        else:
            fields = json.loads(dto.fields_json) if dto.fields_json else []
            required_fields = [f["json_name"] for f in fields
                               if f.get("required") and not f.get("json_ignored")]
            properties: dict = {}
            for f in fields:
                if f.get("json_ignored"):
                    continue
                prop: dict = {"type": f.get("openapi_type", "string")}
                if f.get("openapi_format"):
                    prop["format"] = f["openapi_format"]
                if f.get("nullable"):
                    prop["nullable"] = True
                if f.get("is_collection"):
                    elem = f.get("collection_element_type")
                    prop["type"] = "array"
                    prop["items"] = {"$ref": f"#/components/schemas/{elem}"} if elem else {"type": "object"}
                if f.get("constraints"):
                    prop["x-constraints"] = f["constraints"]
                properties[f["json_name"]] = prop
            schema_obj: dict = {"type": "object", "properties": properties}
            if required_fields:
                schema_obj["required"] = required_fields
            if dto.source_note:
                schema_obj["x-source-note"] = dto.source_note
            if getattr(dto, "description", None):
                schema_obj["description"] = dto.description
            components_schemas[dto.simple_name] = schema_obj

    paths: dict = {}
    for ep in endpoints:
        params_raw = json.loads(ep.parameters_json) if ep.parameters_json else []
        body_raw = json.loads(ep.request_body_json) if ep.request_body_json else None
        ret_raw = json.loads(ep.return_type_json) if ep.return_type_json else None
        sec_raw = json.loads(ep.security_json) if ep.security_json else None

        parameters = []
        for p in params_raw:
            if p.get("location") == "body":
                continue
            parameters.append({
                "name": p["name"],
                "in": p["location"],
                "required": p.get("required", True),
                "schema": {"type": _java_to_openapi_type(p.get("simple_type") or p.get("java_type") or "string")},
                **(({"default": p["default_value"]}) if p.get("default_value") else {}),
            })

        operation: dict = {
            "operationId": ep.method_name,
            "tags": [ep.controller_simple],
            **({"summary": ep.doc_summary} if getattr(ep, "doc_summary", None) else {}),
            **({"description": ep.doc_description} if getattr(ep, "doc_description", None) else {}),
            "parameters": parameters,
            "responses": {
                "200": {
                    "description": "Success",
                    **({
                        "content": {"application/json": {"schema": _response_schema_ref(
                            ret_raw, components_schemas
                        )}}
                    } if ret_raw and ret_raw.get("java_type") != "void" else {}),
                },
                "401": {"description": "Unauthorised"},
                "403": {"description": "Forbidden"},
            },
        }

        if body_raw:
            simple = body_raw.get("simple_type") or body_raw.get("java_type") or "object"
            if simple in components_schemas:
                body_schema: dict = {"$ref": f"#/components/schemas/{simple}"}
            else:
                body_schema = {"type": "object", "description": simple}
            operation["requestBody"] = {
                "required": body_raw.get("required", True),
                "content": {"application/json": {"schema": body_schema}},
            }

        if sec_raw:
            operation["security"] = [{"bearerAuth": []}]
            operation["x-security-expression"] = sec_raw.get("expression", "")

        path_key = ep.full_path
        method_key = ep.http_method.lower()
        paths.setdefault(path_key, {})[method_key] = operation

    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": service,
            "version": version,
            "description": f"Auto-generated from JAR bytecode analysis of {sub.filename}",
        },
        "servers": [{"url": f"http://localhost:{port}", "description": "Local"}],
        "paths": paths,
        "components": {
            "schemas": components_schemas,
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            },
        },
    }

    filename = f"{service}-openapi.json".replace(" ", "-")
    return Response(
        content=json.dumps(spec, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _java_to_openapi_type(java_type: str) -> str:
    t = java_type.lower()
    if any(x in t for x in ("int", "long", "short", "byte")):
        return "integer"
    if any(x in t for x in ("float", "double")):
        return "number"
    if "bool" in t:
        return "boolean"
    if any(x in t for x in ("list", "set", "collection", "[]")):
        return "array"
    if t in ("void",):
        return "null"
    return "object" if any(x in t for x in ("map", "object", "dto", "request", "response")) else "string"


def _response_schema_ref(ret_raw: dict, components_schemas: dict) -> dict:
    """Build a response schema — $ref if we have the DTO, else a basic type."""
    simple = ret_raw.get("simple_type") or ret_raw.get("java_type") or "object"
    if simple in components_schemas:
        return {"$ref": f"#/components/schemas/{simple}"}
    return {"type": _java_to_openapi_type(simple)}


def _schema_dict(s: "JarDtoSchema") -> dict[str, Any]:
    return {
        "id": s.id,
        "class_name": s.class_name,
        "simple_name": s.simple_name,
        "is_enum": s.is_enum,
        "is_lombok": s.is_lombok,
        "source_note": s.source_note,
        "enum_values": json.loads(s.enum_values_json) if s.enum_values_json else [],
        "fields": json.loads(s.fields_json) if s.fields_json else [],
        # Developer-authored, from @Schema(description=...) on the class — distinct from
        # this tool's own inference (see doc_summary/doc_description on endpoints).
        "description": getattr(s, "description", None),
    }


@router.get("/reports/{report_id}/sub-reports/{sub_id}/export/postman")
async def export_sub_postman(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    sub = await _get_sub_or_404(db, report_id, sub_id, auth)
    endpoints = (await db.execute(
        select(JarEndpoint).where(JarEndpoint.sub_report_id == sub_id)
    )).scalars().all()
    dto_schemas = (await db.execute(
        select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub_id)
    )).scalars().all()

    from app.services.jar_analyser.postman_generator import PostmanGenerator
    collection = PostmanGenerator.generate(
        service_name=sub.service_name or sub.filename,
        port=sub.declared_port or 8080,
        version=sub.implementation_version or "1.0.0",
        endpoints=[_endpoint_dict(e) for e in endpoints],
        schemas=[_schema_dict(s) for s in dto_schemas],
    )
    service = sub.service_name or sub.filename
    filename = f"{service}-postman.json".replace(" ", "-")
    return Response(
        content=json.dumps(collection, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/{report_id}/sub-reports/{sub_id}/export/sdk")
async def export_sub_sdk(
    report_id: str,
    sub_id: str,
    lang: str = Query(default="js", pattern="^(js|ts)$"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    sub = await _get_sub_or_404(db, report_id, sub_id, auth)
    endpoints = (await db.execute(
        select(JarEndpoint).where(JarEndpoint.sub_report_id == sub_id)
    )).scalars().all()
    dto_schemas = (await db.execute(
        select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub_id)
    )).scalars().all()
    wf_rows = (await db.execute(
        select(JarWorkflow).where(JarWorkflow.sub_report_id == sub_id)
    )).scalars().all()

    from app.services.jar_analyser.sdk_generator import JsSdkGenerator
    typescript = lang == "ts"
    content = JsSdkGenerator.generate(
        service_name=sub.service_name or sub.filename,
        port=sub.declared_port or 8080,
        version=sub.implementation_version or "1.0.0",
        filename=sub.filename,
        endpoints=[_endpoint_dict(e) for e in endpoints],
        schemas=[_schema_dict(s) for s in dto_schemas],
        workflows=[_workflow_dict(w) for w in wf_rows],
        typescript=typescript,
    )
    service = sub.service_name or sub.filename
    ext = "ts" if typescript else "js"
    filename = f"{service}-sdk.{ext}".replace(" ", "-")
    media = "text/plain"
    return Response(
        content=content, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/{report_id}/export/openapi")
async def export_report_openapi(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    """Combined OpenAPI 3.0.3 spec for all services in a JAR-of-JARs report."""
    rep = await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    version = rep.implementation_version or "1.0.0"
    title = rep.implementation_title or "Platform API"

    combined_paths: dict = {}
    combined_schemas: dict = {}
    tags: list[dict] = []

    for sub in subs:
        if sub.jar_type in ("frontend_installer", "nginx_installer", "monitoring_installer"):
            continue
        service = sub.service_name or sub.filename
        port = sub.declared_port or 8080

        tags.append({"name": service, "description": f"Port {port}"})

        endpoints = (await db.execute(
            select(JarEndpoint).where(JarEndpoint.sub_report_id == sub.id)
        )).scalars().all()
        dto_schemas = (await db.execute(
            select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub.id)
        )).scalars().all()

        # Build schemas — prefix with service name to avoid collisions
        for dto in dto_schemas:
            key = f"{service}__{dto.simple_name}"
            if dto.is_enum:
                values = json.loads(dto.enum_values_json) if dto.enum_values_json else []
                serialised = [v.get("serialised_as", v.get("name", "")) for v in values]
                combined_schemas[key] = {
                    "type": "string", "enum": serialised,
                    "x-java-class": dto.class_name, "x-service": service,
                }
            else:
                fields = json.loads(dto.fields_json) if dto.fields_json else []
                required_fields = [f["json_name"] for f in fields if f.get("required") and not f.get("json_ignored")]
                properties: dict = {}
                for f in fields:
                    if f.get("json_ignored"):
                        continue
                    prop: dict = {"type": f.get("openapi_type", "string")}
                    if f.get("openapi_format"):
                        prop["format"] = f["openapi_format"]
                    if f.get("nullable"):
                        prop["nullable"] = True
                    if f.get("is_collection"):
                        elem = f.get("collection_element_type")
                        prop["type"] = "array"
                        prop["items"] = {"$ref": f"#/components/schemas/{service}__{elem}"} if elem else {"type": "object"}
                    properties[f["json_name"]] = prop
                schema_obj: dict = {"type": "object", "properties": properties, "x-service": service}
                if required_fields:
                    schema_obj["required"] = required_fields
                combined_schemas[key] = schema_obj

        local_schema_names = {dto.simple_name for dto in dto_schemas}

        for ep in endpoints:
            params_raw = json.loads(ep.parameters_json) if ep.parameters_json else []
            body_raw = json.loads(ep.request_body_json) if ep.request_body_json else None
            ret_raw = json.loads(ep.return_type_json) if ep.return_type_json else None
            sec_raw = json.loads(ep.security_json) if ep.security_json else None

            parameters = []
            for p in params_raw:
                if p.get("location") == "body":
                    continue
                parameters.append({
                    "name": p["name"],
                    "in": p["location"],
                    "required": p.get("required", True),
                    "schema": {"type": _java_to_openapi_type(p.get("simple_type") or p.get("java_type") or "string")},
                    **(({"default": p["default_value"]}) if p.get("default_value") else {}),
                })

            operation: dict = {
                "operationId": f"{service}__{ep.method_name}",
                "tags": [service],
                "parameters": parameters,
                "responses": {
                    "200": {"description": "Success"},
                    "401": {"description": "Unauthorised"},
                    "403": {"description": "Forbidden"},
                },
            }

            if ret_raw and ret_raw.get("java_type") != "void":
                simple = ret_raw.get("simple_type") or ret_raw.get("java_type") or "object"
                ref_key = f"{service}__{simple}"
                resp_schema = {"$ref": f"#/components/schemas/{ref_key}"} if simple in local_schema_names else {"type": _java_to_openapi_type(simple)}
                operation["responses"]["200"]["content"] = {"application/json": {"schema": resp_schema}}

            if body_raw:
                simple = body_raw.get("simple_type") or body_raw.get("java_type") or "object"
                ref_key = f"{service}__{simple}"
                body_schema: dict = {"$ref": f"#/components/schemas/{ref_key}"} if simple in local_schema_names else {"type": "object", "description": simple}
                operation["requestBody"] = {
                    "required": body_raw.get("required", True),
                    "content": {"application/json": {"schema": body_schema}},
                }

            if sec_raw:
                operation["security"] = [{"bearerAuth": []}]
                operation["x-security-expression"] = sec_raw.get("expression", "")

            path_key = ep.full_path
            method_key = ep.http_method.lower()
            combined_paths.setdefault(path_key, {})[method_key] = operation

    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "version": version,
            "description": f"Combined OpenAPI spec for all services — auto-generated from JAR bytecode analysis.",
        },
        "tags": tags,
        "paths": combined_paths,
        "components": {
            "schemas": combined_schemas,
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            },
        },
    }

    filename = f"{title}-openapi-{version}.json".replace(" ", "-")
    return Response(
        content=json.dumps(spec, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/{report_id}/export/sdk")
async def export_report_sdk(
    report_id: str,
    lang: str = Query(default="js", pattern="^(js|ts)$"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    """Combined SDK for all services in a JAR-of-JARs report."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    services = []
    for sub in subs:
        if sub.jar_type in ("frontend_installer", "nginx_installer", "monitoring_installer"):
            continue
        endpoints = (await db.execute(
            select(JarEndpoint).where(JarEndpoint.sub_report_id == sub.id)
        )).scalars().all()
        dto_schemas = (await db.execute(
            select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub.id)
        )).scalars().all()
        wf_rows = (await db.execute(
            select(JarWorkflow).where(JarWorkflow.sub_report_id == sub.id)
        )).scalars().all()
        services.append({
            "name": sub.service_name or sub.filename,
            "port": sub.declared_port or 8080,
            "version": sub.implementation_version or "1.0.0",
            "filename": sub.filename,
            "endpoints": [_endpoint_dict(e) for e in endpoints],
            "schemas": [_schema_dict(s) for s in dto_schemas],
            "workflows": [_workflow_dict(w) for w in wf_rows],
        })

    from app.services.jar_analyser.sdk_generator import JsSdkGenerator
    typescript = lang == "ts"
    if len(services) == 1:
        svc = services[0]
        content = JsSdkGenerator.generate(
            service_name=svc["name"], port=svc["port"], version=svc["version"],
            filename=svc["filename"], endpoints=svc["endpoints"],
            schemas=svc["schemas"], workflows=svc["workflows"], typescript=typescript,
        )
    else:
        content = JsSdkGenerator.generate_combined(services, typescript=typescript)

    ext = "ts" if typescript else "js"
    filename = f"platform-sdk.{ext}"
    media = "text/plain"
    return Response(
        content=content, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/{report_id}/export/storefront-guide")
async def export_storefront_guide(
    report_id: str,
    lang: str = Query(default="ts", pattern="^(js|ts)$"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    """Storefront Developer Guide — annotated JS/TS client for shop-front developers."""
    rep = await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    services = []
    for sub in subs:
        if sub.jar_type in ("frontend_installer", "nginx_installer", "monitoring_installer"):
            continue
        endpoints = (await db.execute(
            select(JarEndpoint).where(JarEndpoint.sub_report_id == sub.id)
        )).scalars().all()
        dto_schemas = (await db.execute(
            select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub.id)
        )).scalars().all()
        event_files = (await db.execute(
            select(JarEventFile).where(JarEventFile.sub_report_id == sub.id)
        )).scalars().all()
        config_files = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()
        migration_scripts = (await db.execute(
            select(JarMigrationScript).where(JarMigrationScript.sub_report_id == sub.id)
            .order_by(JarMigrationScript.version)
        )).scalars().all()
        services.append({
            "name": sub.service_name or sub.filename,
            "service_name": sub.service_name,
            "filename": sub.filename,
            "port": sub.declared_port or 8080,
            "declared_port": sub.declared_port,
            "endpoints": [_endpoint_dict(e) for e in endpoints],
            "schemas": [_schema_dict(s) for s in dto_schemas],
            "event_files": [_event_dict(e) for e in event_files],
            "config_files": [_config_dict(c) for c in config_files],
            "migration_scripts": [_migration_dict(m) for m in migration_scripts],
            "installer_metadata": json.loads(sub.installer_metadata_json) if sub.installer_metadata_json else {},
        })

    from app.services.jar_analyser.storefront_guide_generator import StorefrontGuideGenerator
    typescript = lang == "ts"
    version = rep.implementation_version or "1.0.0"
    content = StorefrontGuideGenerator.generate(
        version=version,
        services=services,
        typescript=typescript,
    )
    ext = "ts" if typescript else "js"
    filename = f"storefront-guide-v{version}.{ext}".replace(" ", "-")
    return Response(
        content=content, media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/{report_id}/export/reference-doc")
async def export_report_reference_doc(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> PlainTextResponse:
    report_dict = await get_report(report_id, db, auth)
    sub_list = await list_sub_reports(report_id, db, auth)
    full_subs = []
    for s in sub_list:
        sub_id = s["sub_report_id"]
        full = await get_sub_report(report_id, sub_id, db, auth)
        # get_sub_report()/_sub_full() only returns SubReport's own scalar/JSON
        # columns — endpoints/dependencies/config/migrations/events live in
        # separate child tables and are never attached there (confirmed: the
        # sibling export_report_markdown/export_sub_markdown endpoints have
        # the same gap — their Endpoints/Dependencies/etc. sections render
        # empty today). Enriched properly here rather than inheriting that.
        endpoints = (await db.execute(select(JarEndpoint).where(JarEndpoint.sub_report_id == sub_id))).scalars().all()
        deps = (await db.execute(select(JarDependency).where(JarDependency.sub_report_id == sub_id))).scalars().all()
        configs = (await db.execute(select(JarConfigFile).where(JarConfigFile.sub_report_id == sub_id))).scalars().all()
        migrations = (await db.execute(select(JarMigrationScript).where(JarMigrationScript.sub_report_id == sub_id))).scalars().all()
        events = (await db.execute(select(JarEventFile).where(JarEventFile.sub_report_id == sub_id))).scalars().all()
        examples = (await db.execute(select(JarConfigExample).where(JarConfigExample.sub_report_id == sub_id))).scalars().all()
        full["endpoints"] = [_endpoint_dict(e) for e in endpoints]
        full["dependencies"] = [_dep_dict(d) for d in deps]
        full["config_files"] = [_config_dict(c) for c in configs]
        full["migration_scripts"] = [_migration_dict(m) for m in migrations]
        full["event_files"] = [_event_dict(e) for e in events]
        full["config_examples"] = [
            {"root_class_name": e.root_class_name, "format": e.format, "source": e.source, "content": e.content}
            for e in examples
        ]
        full_subs.append(full)
    from app.services.jar_analyser.reference_doc import report_to_reference_doc
    content = report_to_reference_doc(report_dict, full_subs)
    filename = f"reference-doc-{report_dict.get('manifest', {}).get('implementation_version') or report_id}.md"
    return PlainTextResponse(content=content, media_type="text/markdown",
                              headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/{report_id}/sub-reports/{sub_id}/export/markdown")
async def export_sub_markdown(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> PlainTextResponse:
    full = await get_sub_report(report_id, sub_id, db, auth)
    examples = (await db.execute(
        select(JarConfigExample).where(JarConfigExample.sub_report_id == sub_id)
    )).scalars().all()
    full["config_examples"] = [
        {"root_class_name": e.root_class_name, "format": e.format, "source": e.source, "content": e.content}
        for e in examples
    ]
    from app.services.jar_analyser.export import sub_report_to_markdown
    content = sub_report_to_markdown(full)
    return PlainTextResponse(content=content, media_type="text/markdown")


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

class DiffRequest(BaseModel):
    report_a_id: str
    report_b_id: str
    label_a: str | None = None
    label_b: str | None = None


@router.post("/diff", status_code=201)
async def create_diff(
    body: DiffRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    rep_a = await _get_report_or_404(db, body.report_a_id, auth)
    rep_b = await _get_report_or_404(db, body.report_b_id, auth)

    from app.services.jar_analyser.diff import DiffEngine
    engine = DiffEngine(rep_a, rep_b, body.label_a, body.label_b)
    diff_report = await engine.compute(db)
    return _diff_dict(diff_report)


@router.get("/diff")
async def list_diffs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    total = (await db.execute(select(func.count()).select_from(select(JarDiffReport).subquery()))).scalar() or 0
    rows = (await db.execute(
        select(JarDiffReport)
        .order_by(JarDiffReport.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {
        "items": [_diff_dict(d) for d in rows],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/diff/{diff_id}")
async def get_diff(
    diff_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    diff = await _get_diff_or_404(db, diff_id, auth)
    return _diff_dict(diff, full=True)


@router.get("/diff/{diff_id}/export/markdown")
async def export_diff_markdown(
    diff_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> PlainTextResponse:
    diff = await _get_diff_or_404(db, diff_id, auth)
    from app.services.jar_analyser.export import diff_to_markdown
    content = diff_to_markdown(_diff_dict(diff, full=True))
    return PlainTextResponse(content=content, media_type="text/markdown",
                              headers={"Content-Disposition": f'attachment; filename="diff-{diff_id}.md"'})


@router.get("/diff/{diff_id}/export/change-report/markdown")
async def export_change_report_markdown(
    diff_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> PlainTextResponse:
    diff = await _get_diff_or_404(db, diff_id, auth)
    from app.services.jar_analyser.change_report import change_report_to_markdown
    content = change_report_to_markdown(_diff_dict(diff, full=True))
    filename = f"change-report-{diff_id[:8]}.md"
    return PlainTextResponse(
        content=content, media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/diff/{diff_id}/export/change-report/pdf")
async def export_change_report_pdf(
    diff_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    diff = await _get_diff_or_404(db, diff_id, auth)
    from app.services.jar_analyser.change_report import change_report_to_pdf
    content = change_report_to_pdf(_diff_dict(diff, full=True))
    filename = f"change-report-{diff_id[:8]}.pdf"
    return Response(
        content=content, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Integration feeds
# ---------------------------------------------------------------------------

@router.get("/reports/{report_id}/sub-reports/{sub_id}/security-posture")
async def get_security_posture(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Security posture summary for a single service sub-report."""
    await _get_sub_or_404(db, report_id, sub_id, auth)
    eps = (await db.execute(
        select(JarEndpoint).where(JarEndpoint.sub_report_id == sub_id)
    )).scalars().all()

    total = len(eps)
    public: list[dict] = []
    authenticated_only: list[dict] = []
    role_gated: dict[str, list[dict]] = {}
    authority_gated: dict[str, list[dict]] = {}
    deny_all: list[dict] = []
    unannotated: list[dict] = []

    for ep in eps:
        entry = {"method": ep.http_method, "path": ep.full_path, "endpoint_id": ep.id}
        if not ep.security_json:
            unannotated.append(entry)
            continue
        pa = json.loads(ep.parsed_auth_json) if ep.parsed_auth_json else None
        if not pa:
            unannotated.append(entry)
            continue
        if pa.get("deny_all"):
            deny_all.append(entry)
        elif pa.get("public"):
            public.append(entry)
        elif pa.get("authenticated_only"):
            authenticated_only.append(entry)
        else:
            for role in pa.get("roles", []):
                role_gated.setdefault(role, []).append(entry)
            for authority in pa.get("authorities", []):
                authority_gated.setdefault(authority, []).append(entry)

    role_gated_count = sum(len(v) for v in role_gated.values())
    authority_gated_count = sum(len(v) for v in authority_gated.values())

    return {
        "sub_report_id": sub_id,
        "total_endpoints": total,
        "summary": {
            "public_count": len(public),
            "authenticated_only_count": len(authenticated_only),
            "role_gated_count": role_gated_count,
            "authority_gated_count": authority_gated_count,
            "deny_all_count": len(deny_all),
            "unannotated_count": len(unannotated),
            "unique_roles": sorted(role_gated.keys()),
            "unique_authorities": sorted(authority_gated.keys()),
        },
        "public_endpoints": public,
        "authenticated_only_endpoints": authenticated_only,
        "by_role": {r: eps for r, eps in sorted(role_gated.items())},
        "by_authority": {a: eps for a, eps in sorted(authority_gated.items())},
        "deny_all_endpoints": deny_all,
        "unannotated_endpoints": unannotated,
    }


@router.get("/reports/{report_id}/auth-requirements")
async def get_auth_requirements(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Aggregated auth requirements across all services — roles, authorities, public endpoints."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    # role/authority -> list of {service, method, path}
    role_map: dict[str, list[dict]] = {}
    authority_map: dict[str, list[dict]] = {}
    public_endpoints: list[dict] = []
    authenticated_only: list[dict] = []
    unsecured: list[dict] = []

    for sub in subs:
        svc = sub.service_name or sub.filename
        eps = (await db.execute(
            select(JarEndpoint).where(JarEndpoint.sub_report_id == sub.id)
        )).scalars().all()
        for ep in eps:
            entry = {"service": svc, "method": ep.http_method, "path": ep.full_path}
            if not ep.security_json:
                unsecured.append(entry)
                continue
            pa = json.loads(ep.parsed_auth_json) if ep.parsed_auth_json else None
            if not pa:
                unsecured.append(entry)
                continue
            if pa.get("public"):
                public_endpoints.append(entry)
            elif pa.get("deny_all"):
                pass  # skip deny_all from all lists
            elif pa.get("authenticated_only"):
                authenticated_only.append(entry)
            else:
                for role in pa.get("roles", []):
                    role_map.setdefault(role, []).append(entry)
                for authority in pa.get("authorities", []):
                    authority_map.setdefault(authority, []).append(entry)

    return {
        "report_id": report_id,
        "summary": {
            "unique_roles": sorted(role_map.keys()),
            "unique_authorities": sorted(authority_map.keys()),
            "public_endpoint_count": len(public_endpoints),
            "authenticated_only_count": len(authenticated_only),
            "unsecured_count": len(unsecured),
        },
        "by_role": {role: eps for role, eps in sorted(role_map.items())},
        "by_authority": {auth_val: eps for auth_val, eps in sorted(authority_map.items())},
        "public_endpoints": public_endpoints,
        "authenticated_only": authenticated_only,
        "unsecured": unsecured,
    }


@router.get("/reports/{report_id}/ssl-requirements")
async def get_ssl_requirements(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """SSL Cert Manager integration — SAN suggestions and SSL config extracted from JAR."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    keystore_path: str | None = None
    truststore_path: str | None = None
    keystore_type: str | None = None
    enabled_protocols: list[str] = []
    services: list[dict] = []
    san_set: set[str] = set()

    for sub in subs:
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()

        requires_client_auth = False
        for cfg in configs:
            keys = json.loads(cfg.keys_json) if cfg.keys_json else []
            for k in keys:
                key, val = k.get("key", ""), k.get("value", "") or ""
                if "keystore" in key and "path" in key and not keystore_path:
                    keystore_path = val
                if "truststore" in key and "path" in key and not truststore_path:
                    truststore_path = val
                if "keystore" in key and "type" in key and not keystore_type:
                    keystore_type = val
                if "ssl.enabled-protocols" in key or "ssl.protocol" in key:
                    for proto in val.replace(",", " ").split():
                        if proto and proto not in enabled_protocols:
                            enabled_protocols.append(proto)
                if "client-auth" in key and val.lower() in ("need", "want", "true"):
                    requires_client_auth = True
                if "server.port" in key and val.isdigit():
                    pass  # already on sub.declared_port

        if sub.service_name:
            san_set.add(sub.service_name)
            san_set.add(f"{sub.service_name}-svc")

        if sub.declared_port is not None:
            services.append({
                "name": sub.service_name or sub.filename,
                "port": sub.declared_port,
                "requires_client_auth": requires_client_auth,
                "install_path": sub.install_path,
            })

    # Always include generic SANs
    san_set.update(["localhost"])

    suggested_sans = (
        [{"type": "DNS", "value": s} for s in sorted(san_set)]
        + [{"type": "IP", "value": "127.0.0.1"}]
    )

    return {
        "report_id": report_id,
        "keystore_path": keystore_path,
        "truststore_path": truststore_path,
        "keystore_type": keystore_type or "JKS",
        "enabled_protocols": enabled_protocols or ["TLSv1.2"],
        "suggested_sans": suggested_sans,
        "services": services,
    }


@router.get("/reports/{report_id}/build-manager-feed")
async def get_build_manager_feed(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Build Manager integration — service inventory for environment provisioning."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    services: list[dict] = []
    infra = {
        "requires_mysql": False,
        "requires_rabbitmq": False,
        "requires_config_server": False,
        "rabbitmq_protocol": None,
        "rabbitmq_port": None,
        "mysql_port": None,
    }

    for sub in subs:
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()

        requires_db = False
        requires_mq = False
        requires_config = False
        config_server_port: int | None = None
        database_name: str | None = None
        systemd_unit: str | None = None
        firewall_ports: list[int] = []
        depends_on: list[str] = []

        meta = json.loads(sub.installer_metadata_json) if sub.installer_metadata_json else {}
        if meta.get("firewall_ports"):
            firewall_ports = [int(p) for p in meta["firewall_ports"] if str(p).isdigit()]

        for cfg in configs:
            keys = json.loads(cfg.keys_json) if cfg.keys_json else []
            for k in keys:
                key, val = k.get("key", ""), k.get("value", "") or ""
                if any(x in key for x in ("datasource", "jdbc", "db.")):
                    requires_db = True
                    infra["requires_mysql"] = True
                    if "url" in key and "mysql" in val.lower():
                        infra["mysql_port"] = infra["mysql_port"] or 3306
                    if "database" in key and val and not val.startswith("$"):
                        database_name = val
                if any(x in key for x in ("rabbitmq", "amqp")):
                    requires_mq = True
                    infra["requires_rabbitmq"] = True
                    if "port" in key and val.isdigit():
                        infra["rabbitmq_port"] = int(val)
                    if "ssl" in key and val.lower() in ("true", "amqps"):
                        infra["rabbitmq_protocol"] = "AMQPS"
                if "spring.cloud.config" in key or "config.uri" in key:
                    requires_config = True
                    infra["requires_config_server"] = True
                    if "port" in key and val.isdigit():
                        config_server_port = int(val)
                    elif "uri" in key and ":" in val:
                        try:
                            config_server_port = int(val.rsplit(":", 1)[-1].split("/")[0])
                        except ValueError:
                            pass

            if cfg.filename.endswith(".service"):
                systemd_unit = cfg.filename

        if requires_config and config_server_port:
            depends_on.append("config")

        if sub.declared_port and sub.declared_port not in firewall_ports:
            firewall_ports.append(sub.declared_port)

        services.append({
            "name": sub.service_name or sub.filename,
            "port": sub.declared_port,
            "group": sub.group_name,
            "install_path": sub.install_path,
            "requires_database": requires_db,
            "database_name": database_name,
            "requires_rabbitmq": requires_mq,
            "requires_config_server": requires_config,
            "config_server_port": config_server_port,
            "firewall_ports": firewall_ports,
            "systemd_unit": systemd_unit,
            "depends_on": depends_on,
        })

    if not infra["rabbitmq_protocol"]:
        infra["rabbitmq_protocol"] = "AMQP" if infra["requires_rabbitmq"] else None

    return {"report_id": report_id, "services": services, "infrastructure": infra}


@router.get("/reports/{report_id}/topology")
async def get_topology(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Inter-service dependency graph — nodes and edges from events, nginx, and API URLs."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    sub_dicts = []
    for sub in subs:
        events = (await db.execute(
            select(JarEventFile).where(JarEventFile.sub_report_id == sub.id)
        )).scalars().all()
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()
        sub_dicts.append({
            "service_name": sub.service_name,
            "filename": sub.filename,
            "declared_port": sub.declared_port,
            "installer_metadata": json.loads(sub.installer_metadata_json) if sub.installer_metadata_json else {},
            "event_files": [_event_dict(e) for e in events],
            "config_files": [_config_dict(c) for c in configs],
        })

    from app.services.jar_analyser.dependency_graph import build_dependency_graph
    graph = build_dependency_graph(sub_dicts)
    return {"report_id": report_id, **graph}


@router.get("/reports/{report_id}/env-vars")
async def get_env_vars(
    report_id: str,
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    service: str | None = Query(default=None),
    mandatory_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Unified environment variable / placeholder catalogue across all services."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    sub_dicts = []
    for sub in subs:
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()
        sub_dicts.append({
            "service_name": sub.service_name,
            "filename": sub.filename,
            "config_files": [_config_dict(c) for c in configs],
        })

    from app.services.jar_analyser.placeholder_catalogue import build_placeholder_catalogue
    catalogue = build_placeholder_catalogue(sub_dicts)

    # Apply filters
    if q:
        ql = q.lower()
        catalogue = [e for e in catalogue if ql in e['var_name'].lower()
                     or any(ql in u['config_key'].lower() for u in e['usages'])]
    if category:
        catalogue = [e for e in catalogue if e['category'] == category]
    if service:
        catalogue = [e for e in catalogue if service in e['services']]
    if mandatory_only:
        catalogue = [e for e in catalogue if e['mandatory']]

    categories = sorted({e['category'] for e in catalogue})
    services = sorted({s for e in catalogue for s in e['services']})
    mandatory_count = sum(1 for e in catalogue if e['mandatory'])

    return {
        "report_id": report_id,
        "total": len(catalogue),
        "mandatory_count": mandatory_count,
        "categories": categories,
        "services": services,
        "items": catalogue,
    }


@router.get("/reports/{report_id}/nginx-configs")
async def get_nginx_configs(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Generated nginx configs for on-prem (standard + HA), AWS, and Docker deployments."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    sub_dicts = []
    for sub in subs:
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()
        sub_dicts.append({
            "service_name": sub.service_name,
            "declared_port": sub.declared_port,
            "installer_metadata": json.loads(sub.installer_metadata_json) if sub.installer_metadata_json else {},
            "config_files": [_config_dict(c) for c in configs],
        })

    from app.services.jar_analyser.nginx_config_generator import build_nginx_configs
    return {"report_id": report_id, **build_nginx_configs(sub_dicts)}


@router.get("/reports/{report_id}/message-bus")
async def get_message_bus(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Cross-service RabbitMQ message topology — Publisher → Exchange → RoutingKey → Consumer per event."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    # Build: service_name -> list of published events (from their own event files)
    # Build: service_name -> list of consumed events (from bytecode consumer scan)
    publisher_map: dict[str, list[dict]] = {}   # service -> [{entity, action, exchange, routing_key, consumers, consumer_types, payload_class}]
    consumer_map: dict[str, list[dict]] = {}    # service -> [{source_service, entity, action, handler, payload_class}]

    # Also collect all DTO schemas per sub for payload_class linking
    schema_index: dict[str, str] = {}  # simple_name -> sub_report_id (first match)

    for sub in subs:
        svc = sub.service_name or sub.filename
        events = (await db.execute(
            select(JarEventFile).where(JarEventFile.sub_report_id == sub.id)
        )).scalars().all()

        schemas = (await db.execute(
            select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub.id)
        )).scalars().all()
        for s in schemas:
            if s.simple_name not in schema_index:
                schema_index[s.simple_name] = sub.id

        for ev in events:
            published = json.loads(ev.published_json) if ev.published_json else []
            consumed = json.loads(ev.consumed_json) if ev.consumed_json else []

            for p in published:
                publisher_map.setdefault(svc, []).append({
                    "entity": p.get("entity", ""),
                    "actions": p.get("actions") or [],
                    "exchange": p.get("exchange"),
                    "routing_key": p.get("routing_key_pattern"),
                    "consumers": p.get("consumers") or [],
                    "consumer_types": p.get("consumer_types") or [],
                    "payload_class": p.get("payload_class"),
                    "operation": p.get("operation"),
                })

            for c in consumed:
                consumer_map.setdefault(svc, []).append({
                    "source_service": c.get("source_service"),
                    "entity": c.get("entity"),
                    "action": c.get("action"),
                    "handler": c.get("handler"),
                    "payload_class": c.get("payload_class"),
                    "queue": c.get("queue"),
                    "exchange": c.get("exchange"),
                    "routing_key": c.get("routing_key"),
                })

    # Build the cross-service topology rows:
    # For each published event, find which services consume it (from consumer_map)
    # Key: (publisher, entity, action)
    rows: list[dict] = []
    seen: set[tuple] = set()

    for publisher, pub_events in sorted(publisher_map.items()):
        for pub in pub_events:
            entity = pub["entity"]
            for action in (pub["actions"] or [""]):
                event_key = f"{entity}/{action}" if action else entity

                # Find consumers: either from the published event's consumers list,
                # or by scanning consumer_map for matching source_service + entity + action
                declared_consumers = pub["consumers"]  # applicationId list from event YML

                # Also find services that have a ConsumedEvent matching this publisher+entity+action
                bytecode_consumers: list[dict] = []
                for svc, consumed_list in consumer_map.items():
                    for c in consumed_list:
                        src = (c.get("source_service") or "").replace("-svc", "")
                        pub_norm = publisher.replace("-svc", "").replace("-installer", "")
                        entity_match = (c.get("entity") or "").lower() == entity.lower()
                        action_match = not action or (c.get("action") or "").lower() in (action.lower(), "")
                        src_match = src and pub_norm and (src in pub_norm or pub_norm in src)
                        if entity_match and action_match and src_match:
                            bytecode_consumers.append({"service": svc, "handler": c.get("handler"), "payload_class": c.get("payload_class")})

                # Merge: declared consumers + bytecode consumers
                all_consumers: list[dict] = []
                seen_svcs: set[str] = set()
                for bc in bytecode_consumers:
                    if bc["service"] not in seen_svcs:
                        all_consumers.append(bc)
                        seen_svcs.add(bc["service"])
                for dc in declared_consumers:
                    if dc and dc not in seen_svcs:
                        all_consumers.append({"service": dc, "handler": None, "payload_class": None})
                        seen_svcs.add(dc)

                payload_simple = (pub["payload_class"] or "").rsplit(".", 1)[-1] if pub["payload_class"] else None
                payload_sub_id = schema_index.get(payload_simple) if payload_simple else None

                row_key = (publisher, entity, action)
                if row_key in seen:
                    continue
                seen.add(row_key)

                rows.append({
                    "publisher": publisher,
                    "entity": entity,
                    "action": action,
                    "event_key": event_key,
                    "exchange": pub["exchange"],
                    "routing_key": pub["routing_key"],
                    "operation": pub["operation"],
                    "payload_class": pub["payload_class"],
                    "payload_simple": payload_simple,
                    "payload_sub_report_id": payload_sub_id,
                    "consumers": all_consumers,
                })

    # Summary counts
    all_publishers = sorted({r["publisher"] for r in rows})
    all_consumer_svcs = sorted({c["service"] for r in rows for c in r["consumers"]})

    return {
        "report_id": report_id,
        "total_events": len(rows),
        "publishers": all_publishers,
        "consumers": all_consumer_svcs,
        "rows": rows,
    }


@router.get("/reports/{report_id}/dto-conflicts")
async def get_dto_conflicts(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Cross-service DTO consistency check — schemas with the same simple name but different fields or enum values."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    sub_dicts = []
    for sub in subs:
        schemas = (await db.execute(
            select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub.id)
        )).scalars().all()
        sub_dicts.append({
            "service_name": sub.service_name,
            "filename": sub.filename,
            "schemas": [_schema_dict(s) for s in schemas],
        })

    from app.services.jar_analyser.dto_consistency import check_dto_consistency
    conflicts = check_dto_consistency(sub_dicts)
    return {
        "report_id": report_id,
        "total_conflicts": len(conflicts),
        "enum_conflicts": sum(1 for c in conflicts if c["is_enum"]),
        "dto_conflicts": sum(1 for c in conflicts if not c["is_enum"]),
        "conflicts": conflicts,
    }


@router.get("/reports/{report_id}/port-inventory")
async def get_port_inventory(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Port inventory — all declared ports across all services."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    port_to_service: dict[str, str] = {}
    for sub in subs:
        if sub.declared_port:
            port_to_service[str(sub.declared_port)] = sub.service_name or sub.filename

    all_ports = sorted(int(p) for p in port_to_service)
    return {
        "report_id": report_id,
        "all_ports": all_ports,
        "port_to_service": port_to_service,
    }


# ---------------------------------------------------------------------------
# Context-aware diagnosis
# ---------------------------------------------------------------------------

class DiagnoseRequest(BaseModel):
    error_text: str


async def _build_frame_class_index(db: AsyncSession, report_id: str, class_names: set[str]) -> dict[str, str]:
    """dotted class_name -> sub_report_id, restricted to *this* report's own
    services only — the same JarStringConstant lookup Decode's global
    cross-reference uses (docs.py's _lookup_known_classes), scoped down to
    one report since Diagnose is deliberately report-scoped, not a
    cross-upload search. Lets diagnose() below correlate a pasted trace's
    own frames back to exactly which of this report's services they came
    from, instead of every context-finding function searching every service
    in the report indiscriminately regardless of what's actually in the trace."""
    if not class_names:
        return {}
    rows = (await db.execute(
        select(JarStringConstant.class_name, JarStringConstant.sub_report_id)
        .join(SubReport, JarStringConstant.sub_report_id == SubReport.id)
        .where(SubReport.parent_report_id == report_id, JarStringConstant.class_name.in_(class_names))
        .distinct()
    )).all()
    return {class_name: sub_report_id for class_name, sub_report_id in rows}


@router.post("/reports/{report_id}/diagnose")
async def diagnose_error(
    report_id: str,
    body: DiagnoseRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Context-aware error diagnosis — KB lookup enriched with report-specific
    findings, scoped to the one report the caller picked (unlike Docs'
    Decode tab, which searches every analysed upload — this stays
    report-scoped on purpose, since the whole point of Diagnose is "what
    does this mean for the specific report I'm looking at")."""
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    sub_dicts: list[dict] = []
    for sub in subs:
        endpoints = (await db.execute(
            select(JarEndpoint).where(JarEndpoint.sub_report_id == sub.id)
        )).scalars().all()
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()
        migrations = (await db.execute(
            select(JarMigrationScript)
            .where(JarMigrationScript.sub_report_id == sub.id)
            .order_by(JarMigrationScript.version)
        )).scalars().all()
        sub_dicts.append({
            "sub_report_id": sub.id,
            "service_name": sub.service_name,
            "filename": sub.filename,
            "declared_port": sub.declared_port,
            "endpoints": [_endpoint_dict(e) for e in endpoints],
            "config_files": [_config_dict(c) for c in configs],
            "migration_scripts": [_migration_dict(m) for m in migrations],
        })

    # Same stack_trace_parser.py used by Docs' Decode tab — parsed here too
    # (not just inside diagnose()) because turning frame class names into a
    # sub_report_id index needs a DB round trip, which diagnose() itself
    # (a plain sync function, reused as-is for its existing unit-testability)
    # can't do.
    from app.services.stack_trace_parser import extract_stack_traces
    blocks = extract_stack_traces(body.error_text)
    frame_class_names = {f.class_name for b in blocks for f in b.frames}
    frame_class_index = await _build_frame_class_index(db, report_id, frame_class_names)

    from app.services.jar_analyser.error_diagnostician import diagnose
    kb_entries = await _fetch_kb_entries(db, auth.tenant_id, auth.is_global_admin)
    results = diagnose(body.error_text, sub_dicts, kb_entries, frame_class_index=frame_class_index)

    # Usage tracking (Improvements Plan Stage 16) — this is a real "Diagnose
    # run" against real pasted error text, same class of event as the Docs
    # Search tab's pattern mode.
    from app.services.docs_error_kb import record_kb_matches
    await record_kb_matches(db, [r["kb_entry"]["id"] for r in results])
    await db.commit()

    # ML diagnostic layer — anomaly scoring + cross-signal correlation on
    # top of the KB results. No log file in this flow (no bundle uploaded),
    # so only stack trace parsing and correlation run; anomaly scoring is
    # skipped unless ML_LOG_PATH is configured.
    ml_analysis: dict | None = None
    try:
        from phase5.log_intelligence.pipeline import diagnose_with_ml
        ml_result = diagnose_with_ml(
            stack_trace_text=body.error_text,
            log_path=str(settings.ML_LOG_PATH) if settings.ML_LOG_PATH else None,
            report_id=report_id,
            scorer_path=str(settings.ML_SCORER_PATH) if settings.ML_SCORER_PATH else None,
        )
        ml_analysis = ml_result.to_dict()
    except Exception:
        pass

    return {
        "report_id": report_id,
        "error_text": body.error_text,
        "total": len(results),
        "results": results,
        "ml_analysis": ml_analysis,
    }


# ---------------------------------------------------------------------------
# Error KB
# ---------------------------------------------------------------------------

async def _fetch_kb_entries(db: AsyncSession, tenant_id: str, is_global_admin: bool) -> list[dict[str, Any]]:
    """KB entries as dicts, for passing into search_kb()/diagnose(). The KB
    lives as ordinary Docs (one per-category library) rather than a
    dedicated table — see app.services.docs_error_kb. Takes plain
    tenant_id/is_global_admin (not a full AuthContext) since one caller
    (_run_diagnostics) runs as a background task with no request auth.
    Plain browsing/search/editing of the KB itself now happens in the Docs
    section (GET /docs/error-kb/search + the normal Docs CRUD) — this
    function only serves report-context-aware diagnosis, which stays here
    since it's fundamentally report-specific, not a generic docs concern."""
    from app.services.docs_error_kb import build_kb_entries, fetch_all_current_docs_with_paths
    docs = await fetch_all_current_docs_with_paths(db, tenant_id, is_global_admin)
    return build_kb_entries(docs)


# ---------------------------------------------------------------------------
# Diagnostics — script generation + bundle upload + analysis
# ---------------------------------------------------------------------------

from app.models.jar_analyser import JarDiagnosticRun as _JarDiagnosticRun


@router.get("/reports/{report_id}/diagnostic-script")
async def get_diagnostic_script(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> Response:
    """Generate and return a report-specific diagnostic collection bash script."""
    rep, upload = await _get_report_and_upload_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    sub_dicts: list[dict] = []
    for sub in subs:
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()
        sub_dicts.append({
            "service_name": sub.service_name,
            "filename": sub.filename,
            "jar_type": sub.jar_type,
            "declared_port": sub.declared_port,
            "install_path": sub.install_path,
            "config_files": [_config_dict(c) for c in configs],
        })

    report_dict = {
        "report_id": rep.id,
        "manifest": json.loads(rep.manifest_json) if rep.manifest_json else {},
        "summary": json.loads(rep.summary_json) if rep.summary_json else {},
    }

    from app.services.jar_analyser.diagnostic_script_generator import generate_diagnostic_script
    script = generate_diagnostic_script(report_dict, sub_dicts)

    version = rep.implementation_version or "unknown"
    filename = f"diag-collect-{version}.sh".replace(" ", "-")
    return Response(
        content=script,
        media_type="text/x-shellscript",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/reports/{report_id}/diagnostics", status_code=201)
async def upload_diagnostic_bundle(
    report_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Upload a diagnostic bundle tar.gz and trigger analysis."""
    await _get_report_or_404(db, report_id, auth)

    if not file.filename or not file.filename.endswith(".tar.gz"):
        raise HTTPException(status_code=422, detail="Only .tar.gz bundles are accepted")

    diag_dir = settings.DATA_DIR / "diagnostics" / report_id
    diag_dir.mkdir(parents=True, exist_ok=True)
    dest = diag_dir / file.filename

    size = 0
    with dest.open("wb") as fout:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > 500 * 1024 * 1024:  # 500 MB cap
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Bundle exceeds 500 MB limit")
            fout.write(chunk)

    run = _JarDiagnosticRun(
        report_id=report_id,
        uploaded_by=auth.username,
        bundle_filename=file.filename,
        bundle_size_bytes=size,
        status="pending",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    background_tasks.add_task(_run_diagnostics, run.id, report_id, str(dest), auth.tenant_id, auth.is_global_admin)

    return {
        "run_id": run.id,
        "report_id": report_id,
        "status": "pending",
        "status_url": f"/api/v1/jar-analyser/reports/{report_id}/diagnostics/{run.id}",
    }


async def _run_diagnostics(run_id: str, report_id: str, bundle_path_str: str, tenant_id: str, is_global_admin: bool) -> None:
    from app.core.database import async_session
    from app.services.jar_analyser.diagnostics_analyser import analyse_diagnostic_bundle

    bundle_path = Path(bundle_path_str)
    async with async_session() as db:
        run = (await db.execute(
            select(_JarDiagnosticRun).where(_JarDiagnosticRun.id == run_id)
        )).scalar_one_or_none()
        if not run:
            return

        run.status = "analysing"
        await db.commit()

        try:
            # Load sub-dicts for context
            subs = (await db.execute(
                select(SubReport).where(SubReport.parent_report_id == report_id)
            )).scalars().all()
            sub_dicts: list[dict] = []
            for sub in subs:
                configs = (await db.execute(
                    select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
                )).scalars().all()
                sub_dicts.append({
                    "service_name": sub.service_name,
                    "filename": sub.filename,
                    "declared_port": sub.declared_port,
                    "config_files": [_config_dict(c) for c in configs],
                })

            kb_entries = await _fetch_kb_entries(db, tenant_id, is_global_admin)
            result = analyse_diagnostic_bundle(bundle_path, sub_dicts, kb_entries)

            manifest = result.get("manifest", {})
            run.hostname = manifest.get("hostname")
            run.os_id = manifest.get("os_id")
            run.platform_version = manifest.get("platform_version")
            run.summary_json = json.dumps(result["summary"])
            run.findings_json = json.dumps(result["findings"])
            run.cert_results_json = json.dumps(result["cert_results"])
            run.port_results_json = json.dumps(result["port_results"])
            run.rmq_summary_json = json.dumps(result["rmq_summary"])
            run.config_issues_json = json.dumps(result["config_issues"])
            # ML diagnostic layer — augments the rule-based log_findings
            # with anomaly scoring and cross-signal correlation. Runs after
            # the bundle analyser so it can use the same stack trace text
            # the bundle already extracted. Gracefully skipped if Neural is
            # not on the path or no scorer model has been trained yet.
            ml_log_findings = result["log_findings"]
            try:
                from phase5.log_intelligence.pipeline import diagnose_with_ml
                stack_text = " ".join(
                    f.get("message", "") for f in result.get("findings", [])
                    if "Exception" in f.get("message", "") or "Error" in f.get("message", "")
                )
                _log_paths = [p.strip() for p in settings.ML_LOG_PATHS.split(":") if p.strip()] if settings.ML_LOG_PATHS else None
                ml_result = diagnose_with_ml(
                    stack_trace_text=stack_text,
                    log_path=str(settings.ML_LOG_PATH) if settings.ML_LOG_PATH else None,
                    log_paths=_log_paths,
                    report_id=report_id,
                    scorer_path=str(settings.ML_SCORER_PATH) if settings.ML_SCORER_PATH else None,
                    tail_lines=settings.ML_TAIL_LINES,
                )
                ml_log_findings = {"rule_based": result["log_findings"], "ml": ml_result.to_dict()}
            except Exception:
                pass
            run.log_findings_json = json.dumps(ml_log_findings)
            run.os_info = result.get("os_info", "")
            run.status = "completed"
        except Exception as e:
            run.status = "failed"
            run.error = str(e)

        await db.commit()


@router.get("/reports/{report_id}/diagnostics")
async def list_diagnostic_runs(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    await _get_report_or_404(db, report_id, auth)
    rows = (await db.execute(
        select(_JarDiagnosticRun)
        .where(_JarDiagnosticRun.report_id == report_id)
        .order_by(_JarDiagnosticRun.uploaded_at.desc())
    )).scalars().all()
    return [_diag_run_summary(r) for r in rows]


@router.get("/reports/{report_id}/diagnostics/{run_id}")
async def get_diagnostic_run(
    report_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    run = await _get_diag_run_or_404(db, report_id, run_id, auth)
    return _diag_run_full(run)


@router.delete("/reports/{report_id}/diagnostics/{run_id}", status_code=204)
async def delete_diagnostic_run(
    report_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    run = await _get_diag_run_or_404(db, report_id, run_id, auth)
    await db.delete(run)
    await db.commit()


async def _get_diag_run_or_404(db: AsyncSession, report_id: str, run_id: str, auth: AuthContext) -> "_JarDiagnosticRun":
    query = select(_JarDiagnosticRun).where(
        _JarDiagnosticRun.id == run_id,
        _JarDiagnosticRun.report_id == report_id,
    )
    if not auth.is_global_admin:
        query = query.join(AnalysisReport, _JarDiagnosticRun.report_id == AnalysisReport.id).where(
            AnalysisReport.tenant_id == auth.tenant_id
        )
    r = await db.execute(query)
    obj = r.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Diagnostic run not found")
    return obj


def _diag_run_summary(r: "_JarDiagnosticRun") -> dict[str, Any]:
    return {
        "run_id": r.id,
        "report_id": r.report_id,
        "status": r.status,
        "uploaded_by": r.uploaded_by,
        "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
        "bundle_filename": r.bundle_filename,
        "bundle_size_bytes": r.bundle_size_bytes,
        "hostname": r.hostname,
        "os_id": r.os_id,
        "platform_version": r.platform_version,
        "summary": json.loads(r.summary_json) if r.summary_json else None,
        "error": r.error,
    }


def _diag_run_full(r: "_JarDiagnosticRun") -> dict[str, Any]:
    d = _diag_run_summary(r)
    d.update({
        "findings": json.loads(r.findings_json) if r.findings_json else [],
        "cert_results": json.loads(r.cert_results_json) if r.cert_results_json else [],
        "port_results": json.loads(r.port_results_json) if r.port_results_json else [],
        "rmq_summary": json.loads(r.rmq_summary_json) if r.rmq_summary_json else {},
        "config_issues": json.loads(r.config_issues_json) if r.config_issues_json else [],
        "log_findings": json.loads(r.log_findings_json) if r.log_findings_json else [],
        "os_info": r.os_info or "",
    })
    return d


# ---------------------------------------------------------------------------
# Decompilation (on-demand) — reconstructs real Java source from bytecode via
# CFR, for one specific nested jar or every jar in the bundle. See
# app/services/jar_analyser/decompiler.py and the "Golden-Path"-style
# limitations writeup in Documentation/jar_analyser_operations_guide.md.
# ---------------------------------------------------------------------------

class DecompileRequest(BaseModel):
    timeout_seconds: int = Field(default=120, ge=1, le=900)


async def cleanup_stale_decompile_workdirs() -> None:
    """Startup sweep — remove decompile_{run_id}_{random} work directories
    left behind by a crash or container restart mid-run. _run_decompile's own
    `finally: shutil.rmtree(...)` only fires if the background task actually
    gets to run it; a hard restart skips it entirely, and these can hold a
    full extracted jar's contents (hundreds of MB) each. Directories for a
    run that's still genuinely pending/running are left alone — call this
    once, at app startup, before any new decompile could have started."""
    if not _JAR_WORK_DIR.exists():
        return
    import shutil
    from app.core.database import async_session

    async with async_session() as db:
        active_ids = set((await db.execute(
            select(JarDecompileRun.id).where(JarDecompileRun.status.in_(["pending", "running"]))
        )).scalars().all())

    for entry in _JAR_WORK_DIR.iterdir():
        if not entry.is_dir() or not entry.name.startswith("decompile_"):
            continue
        # Format is decompile_{36-char run_id}_{random suffix} — see the
        # tempfile.mkdtemp(prefix=f"decompile_{run_id}_") call below.
        run_id = entry.name[len("decompile_"):][:36]
        if run_id in active_ids:
            continue
        shutil.rmtree(entry, ignore_errors=True)


@router.post("/reports/{report_id}/sub-reports/{sub_id}/decompile", status_code=201)
async def trigger_decompile_jar(
    request: Request,
    report_id: str,
    sub_id: str,
    background_tasks: BackgroundTasks,
    body: DecompileRequest = DecompileRequest(),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Decompile every class in one nested jar. Scoped runs like this replace
    that jar's previously decompiled classes, if any."""
    await _get_sub_or_404(db, report_id, sub_id, auth)
    run = JarDecompileRun(
        report_id=report_id, sub_report_id=sub_id,
        status="pending", timeout_seconds=body.timeout_seconds, jars_total=1,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await audit_event(
        db=db, event_type="JAR_DECOMPILE_TRIGGERED", severity="INFO", request=request,
        subject_type="jar_decompile_run", subject_id=run.id,
        detail={"report_id": report_id, "sub_report_id": sub_id, "timeout_seconds": body.timeout_seconds},
        description=f"Decompile triggered for sub-report {sub_id}",
    )
    await db.commit()

    background_tasks.add_task(_run_decompile, run.id, report_id, sub_id)

    return {
        "run_id": run.id, "report_id": report_id, "status": "pending",
        "status_url": f"/api/v1/jar-analyser/reports/{report_id}/decompile-runs/{run.id}",
    }


@router.post("/reports/{report_id}/decompile-all", status_code=201)
async def trigger_decompile_all(
    request: Request,
    report_id: str,
    background_tasks: BackgroundTasks,
    body: DecompileRequest = DecompileRequest(),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Decompile every class in every jar under this report, one jar (one
    JVM invocation) at a time — timeout_seconds applies per jar, not to the
    batch as a whole."""
    await _get_report_or_404(db, report_id, auth)
    total = (await db.execute(
        select(func.count()).select_from(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalar() or 0

    run = JarDecompileRun(
        report_id=report_id, sub_report_id=None,
        status="pending", timeout_seconds=body.timeout_seconds, jars_total=total,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await audit_event(
        db=db, event_type="JAR_DECOMPILE_TRIGGERED", severity="INFO", request=request,
        subject_type="jar_decompile_run", subject_id=run.id,
        detail={"report_id": report_id, "sub_report_id": None, "jars_total": total, "timeout_seconds": body.timeout_seconds},
        description=f"Decompile-all triggered for report {report_id} ({total} jars)",
    )
    await db.commit()

    background_tasks.add_task(_run_decompile, run.id, report_id, None)

    return {
        "run_id": run.id, "report_id": report_id, "status": "pending",
        "status_url": f"/api/v1/jar-analyser/reports/{report_id}/decompile-runs/{run.id}",
    }


async def _run_decompile(run_id: str, report_id: str, sub_id: str | None) -> None:
    """Background task: resolve each targeted sub-report's jar bytes (they
    aren't kept around after the original analysis — see decompiler.py's
    module docstring), run both decompiler engines, persist decompiled
    classes, and commit progress after every jar so a run's status is never
    invisible even if the whole batch runs long."""
    import asyncio
    import shutil
    import tempfile
    from app.core.database import async_session
    from app.services.jar_analyser.decompiler import (
        ENGINES, run_decompiler, collect_decompiled_sources, resolve_jar_path_for_sub_report,
    )

    async with async_session() as db:
        run = (await db.execute(select(JarDecompileRun).where(JarDecompileRun.id == run_id))).scalar_one_or_none()
        if not run:
            return

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        await db.commit()

        report_row = (await db.execute(
            select(AnalysisReport, JarUpload)
            .join(JarUpload, AnalysisReport.upload_id == JarUpload.id)
            .where(AnalysisReport.id == report_id)
        )).one_or_none()
        if not report_row:
            run.status = "failed"
            run.error = "Report or upload not found"
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return
        _, upload = report_row
        upload_path = Path(upload.stored_path)

        if sub_id:
            subs = [s for s in [
                (await db.execute(select(SubReport).where(SubReport.id == sub_id))).scalar_one_or_none()
            ] if s]
        else:
            subs = (await db.execute(
                select(SubReport).where(SubReport.parent_report_id == report_id)
            )).scalars().all()

        _JAR_WORK_DIR.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(dir=_JAR_WORK_DIR, prefix=f"decompile_{run_id}_"))
        results: list[dict[str, Any]] = []
        try:
            for sub in subs:
                # A cancel request updates the DB row from a different task's
                # session — re-fetch to see it. Checked between jars (not
                # mid-jar): the currently in-flight jar's subprocess, if any,
                # is terminated directly by the cancel endpoint itself, so
                # this just stops the batch from starting another one.
                await db.refresh(run)
                if run.status == "cancelled":
                    break

                entry: dict[str, Any] = {
                    "sub_report_id": sub.id, "filename": sub.filename,
                    "status": "failed", "classes_decompiled": 0, "error": None,
                    "engines": {},
                }
                try:
                    jar_path = resolve_jar_path_for_sub_report(upload_path, sub, work_dir)
                    if not jar_path or not jar_path.exists():
                        entry["error"] = "Could not locate this jar's bytes (original upload may be missing)"
                        run.jars_failed += 1
                    else:
                        # Both engines run concurrently, not sequentially — wall-clock
                        # time is bounded by whichever is slower, not their sum.
                        output_dirs = {engine: work_dir / f"out_{sub.id}_{engine}" for engine in ENGINES}
                        decompile_results = dict(zip(ENGINES, await asyncio.gather(*(
                            run_decompiler(engine, jar_path, output_dirs[engine], run.timeout_seconds, f"{run.id}:{sub.id}:{engine}")
                            for engine in ENGINES
                        ))))

                        await db.execute(delete(JarDecompiledClass).where(JarDecompiledClass.sub_report_id == sub.id))
                        await db.execute(delete(JarOutboundCallSite).where(JarOutboundCallSite.sub_report_id == sub.id))
                        total_classes = 0
                        any_engine_ran_cleanly = False
                        # Outbound call site analysis (Section 39) runs once
                        # per class, not once per engine — cfr is tried
                        # first (ENGINES order), vineflower only fills in
                        # classes cfr had no source for, to avoid two
                        # near-identical rows per class for what's the same
                        # underlying method either way.
                        call_site_analysed: set[str] = set()
                        for engine, decompile_result in decompile_results.items():
                            if not decompile_result.success:
                                entry["engines"][engine] = {
                                    "status": "timed_out" if decompile_result.timed_out else "failed",
                                    "classes_decompiled": 0, "error": decompile_result.error,
                                }
                                continue
                            any_engine_ran_cleanly = True
                            classes = collect_decompiled_sources(output_dirs[engine])
                            for class_name, package_name, simple_name, source in classes:
                                db.add(JarDecompiledClass(
                                    sub_report_id=sub.id, run_id=run.id, engine=engine,
                                    class_name=class_name, package_name=package_name,
                                    simple_name=simple_name, source=source,
                                ))
                                if class_name not in call_site_analysed:
                                    call_site_analysed.add(class_name)
                                    from app.services.jar_analyser.outbound_call_analysis import extract_outbound_call_sites
                                    for site in extract_outbound_call_sites(source):
                                        db.add(JarOutboundCallSite(
                                            sub_report_id=sub.id, run_id=run.id, engine=engine,
                                            class_name=class_name, method_name=site.method_name,
                                            call_type=site.call_type, call_snippet=site.call_snippet,
                                            response_type=site.response_type,
                                            caught_exceptions_json=json.dumps(site.caught_exceptions) if site.caught_exceptions else None,
                                            thrown_exceptions_json=json.dumps(site.thrown_exceptions) if site.thrown_exceptions else None,
                                            status_checks_json=json.dumps(site.status_checks) if site.status_checks else None,
                                        ))
                            total_classes += len(classes)
                            entry["engines"][engine] = {
                                "status": "completed" if classes else "no_classes",
                                "classes_decompiled": len(classes), "error": None,
                            }

                        # Summary across both engines — "completed" if *either* produced
                        # real output, so a class only one engine struggles with doesn't
                        # sink the jar's overall result. "no_classes" is a clean run on
                        # both, genuinely expected for non-Java bundles (nginx/monitoring/
                        # frontend installers) — kept distinct from "completed" so the UI
                        # doesn't offer a download for an empty result. Only "failed" when
                        # *both* engines failed outright.
                        entry["classes_decompiled"] = total_classes
                        if total_classes > 0:
                            entry["status"] = "completed"
                            run.jars_completed += 1
                        elif any_engine_ran_cleanly:
                            entry["status"] = "no_classes"
                            run.jars_completed += 1
                        else:
                            entry["status"] = "failed"
                            entry["error"] = "; ".join(
                                f"{e}: {d['error']}" for e, d in entry["engines"].items() if d.get("error")
                            ) or "Both decompiler engines failed"
                            run.jars_failed += 1
                except Exception as e:
                    entry["error"] = str(e)
                    run.jars_failed += 1

                results.append(entry)
                run.results_json = json.dumps(results)
                await db.commit()  # incremental — visible progress even mid-batch

            if run.status == "cancelled":
                pass  # set by the cancel endpoint — don't overwrite it below
            elif sub_id is not None:
                # Single-jar scope: the run's own outcome mirrors that one jar's.
                # "no_classes" is a clean run, not a failure — it just found nothing.
                run.status = "completed" if results and results[0]["status"] in ("completed", "no_classes") else "failed"
                if run.status == "failed" and results:
                    run.error = results[0]["error"]
            else:
                # Batch scope: the run "completed" once every jar's been attempted —
                # per-jar outcomes live in results_json, not the run's own status.
                run.status = "completed"
        except Exception as e:
            if run.status != "cancelled":
                run.status = "failed"
                run.error = str(e)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()


@router.get("/reports/{report_id}/decompile-runs/{run_id}")
async def get_decompile_run(
    report_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    run = await _get_decompile_run_or_404(db, report_id, run_id, auth)
    return _decompile_run_dict(run)


@router.post("/reports/{report_id}/decompile-runs/{run_id}/cancel")
async def cancel_decompile_run(
    request: Request,
    report_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Stop a stuck/runaway decompile run early rather than waiting out its
    timeout. Terminates whatever CFR/Vineflower subprocess is currently in
    flight for it (decompiler.cancel_run) and marks the run cancelled —
    _run_decompile checks for this between jars and won't overwrite it."""
    from app.services.jar_analyser.decompiler import cancel_run

    run = await _get_decompile_run_or_404(db, report_id, run_id, auth)
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"Run is already {run.status} — nothing to cancel")

    terminated = await cancel_run(run.id)
    run.status = "cancelled"
    run.finished_at = datetime.now(timezone.utc)
    await audit_event(
        db=db, event_type="JAR_DECOMPILE_CANCELLED", severity="INFO", request=request,
        subject_type="jar_decompile_run", subject_id=run.id,
        detail={"report_id": report_id, "processes_terminated": terminated},
        description=f"Decompile run cancelled: {run.id}",
    )
    await db.commit()
    return _decompile_run_dict(run)


@router.get("/reports/{report_id}/sub-reports/{sub_id}/decompile-runs")
async def list_decompile_runs_for_sub(
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> list[dict[str, Any]]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    rows = (await db.execute(
        select(JarDecompileRun)
        .where(JarDecompileRun.sub_report_id == sub_id)
        .order_by(JarDecompileRun.started_at.desc())
    )).scalars().all()
    return [_decompile_run_dict(r) for r in rows]


@router.get("/reports/{report_id}/sub-reports/{sub_id}/decompiled-classes")
async def list_decompiled_classes(
    report_id: str,
    sub_id: str,
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    # distinct() on just these three columns collapses the cfr/vineflower
    # rows for the same class into a single tree entry — a class decompiled
    # by both engines is still one thing to browse, not two.
    query = (
        select(JarDecompiledClass.class_name, JarDecompiledClass.package_name, JarDecompiledClass.simple_name)
        .where(JarDecompiledClass.sub_report_id == sub_id)
        .distinct()
    )
    if search:
        query = query.where(JarDecompiledClass.class_name.ilike(f"%{search}%"))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(
        query.order_by(JarDecompiledClass.class_name).offset((page - 1) * page_size).limit(page_size)
    )).all()
    return {
        "items": [
            {"class_name": r.class_name, "package_name": r.package_name, "simple_name": r.simple_name}
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/reports/{report_id}/sub-reports/{sub_id}/decompiled-classes/{class_name:path}/facts")
async def get_decompiled_class_facts(
    report_id: str,
    sub_id: str,
    class_name: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Cross-references a decompiled class against facts this tool already
    extracted elsewhere via static bytecode analysis (endpoints, scheduled
    jobs, DTO schemas, custom error handlers) — not a new analysis pass,
    just surfacing existing data inline with the source. No AI involved:
    every field here is a direct DB lookup against tables populated by
    annotations.py/endpoints.py/scheduled_jobs.py/dto_scanner.py/error_catalogue.py.

    Every one of those tables stores its class column dot-separated
    (com.foo.Bar), while JarDecompiledClass.class_name (and the class_name
    path param here, fed straight from it) is slash-separated (com/foo/Bar)
    — converted once below.

    Registered *before* get_decompiled_class_source below — both routes use
    a greedy `{class_name:path}` param, and Starlette tries routes in
    registration order, so the more specific "/facts"-suffixed pattern has
    to come first or the plain source route swallows the "/facts" suffix
    into class_name itself and this one is never reached (confirmed live:
    that's exactly what happened before this was reordered).
    """
    await _get_sub_or_404(db, report_id, sub_id, auth)
    dotted = class_name.replace("/", ".")

    endpoints = (await db.execute(
        select(JarEndpoint).where(JarEndpoint.sub_report_id == sub_id, JarEndpoint.controller_class == dotted)
    )).scalars().all()
    scheduled_jobs = (await db.execute(
        select(JarScheduledJob).where(JarScheduledJob.sub_report_id == sub_id, JarScheduledJob.declaring_class == dotted)
    )).scalars().all()
    dto_schema = (await db.execute(
        select(JarDtoSchema).where(JarDtoSchema.sub_report_id == sub_id, JarDtoSchema.class_name == dotted)
    )).scalar_one_or_none()
    # controller_class only — exception_class/response_schema_class are
    # simple-name-only on this table, so matching against them risks a
    # false positive against an unrelated class of the same simple name
    # in a different package.
    error_handlers = (await db.execute(
        select(JarErrorResponse).where(JarErrorResponse.sub_report_id == sub_id, JarErrorResponse.controller_class == dotted)
    )).scalars().all()

    return {
        "endpoints": [_endpoint_dict(e) for e in endpoints],
        "scheduled_jobs": [_scheduled_job_dict(j) for j in scheduled_jobs],
        "dto_schema": _schema_dict(dto_schema) if dto_schema else None,
        "error_handlers": [_error_response_dict(e) for e in error_handlers],
    }


@router.get("/reports/{report_id}/sub-reports/{sub_id}/decompiled-classes/{class_name:path}")
async def get_decompiled_class_source(
    request: Request,
    report_id: str,
    sub_id: str,
    class_name: str,
    engine: str = Query(default="cfr"),
    db: AsyncSession = Depends(get_db),
    # Decompiled source is the most sensitive artifact this tool produces —
    # restricted to admin/operator, unlike the class list/facts endpoints
    # (names and structural cross-references only) which stay open to all 4.
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    await _get_sub_or_404(db, report_id, sub_id, auth)
    all_rows = (await db.execute(
        select(JarDecompiledClass).where(
            JarDecompiledClass.sub_report_id == sub_id,
            JarDecompiledClass.class_name == class_name,
        )
    )).scalars().all()
    if not all_rows:
        raise HTTPException(status_code=404, detail="Decompiled class not found — decompile this jar first")

    available_engines = sorted({r.engine for r in all_rows})
    row = next((r for r in all_rows if r.engine == engine), None)
    if not row:
        # Requested engine produced no output for this specific class — fall
        # back to whichever engine did, so the caller always gets real
        # source rather than an empty response. available_engines tells the
        # UI which engine it actually got so it can reflect that honestly.
        row = all_rows[0]
    await audit_event(
        db=db, event_type="JAR_SOURCE_VIEWED", severity="INFO", request=request,
        subject_type="sub_report", subject_id=sub_id,
        detail={"class_name": class_name, "engine": row.engine},
        description=f"Decompiled source viewed: {class_name}",
    )
    await db.commit()
    return {
        "class_name": row.class_name, "package_name": row.package_name,
        "simple_name": row.simple_name, "source": row.source,
        "engine": row.engine, "available_engines": available_engines,
    }


@router.get("/reports/{report_id}/sub-reports/{sub_id}/decompile/export")
async def export_decompiled_source_zip(
    request: Request,
    report_id: str,
    sub_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> Response:
    sub = await _get_sub_or_404(db, report_id, sub_id, auth)
    rows = (await db.execute(
        select(JarDecompiledClass).where(JarDecompiledClass.sub_report_id == sub_id)
    )).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="No decompiled classes for this jar yet — decompile it first")

    buf = _zip_decompiled_classes({sub.filename: rows})
    fname = f"{Path(sub.filename).stem}-decompiled.zip"
    await audit_event(
        db=db, event_type="JAR_SOURCE_EXPORTED", severity="INFO", request=request,
        subject_type="sub_report", subject_id=sub_id,
        detail={"filename": sub.filename, "class_count": len(rows)},
        description=f"Decompiled source exported (zip): {sub.filename}",
    )
    await db.commit()
    return Response(
        content=buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/reports/{report_id}/decompile/export")
async def export_all_decompiled_source_zip(
    request: Request,
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> Response:
    await _get_report_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    by_sub: dict[str, list[JarDecompiledClass]] = {}
    for sub in subs:
        rows = (await db.execute(
            select(JarDecompiledClass).where(JarDecompiledClass.sub_report_id == sub.id)
        )).scalars().all()
        if rows:
            by_sub[sub.filename] = rows
    if not by_sub:
        raise HTTPException(status_code=404, detail="No decompiled classes for this report yet — decompile at least one jar first")

    buf = _zip_decompiled_classes(by_sub)
    await audit_event(
        db=db, event_type="JAR_SOURCE_EXPORTED", severity="INFO", request=request,
        subject_type="report", subject_id=report_id,
        detail={"service_count": len(by_sub)},
        description=f"Decompiled source exported (zip, all services): report {report_id}",
    )
    await db.commit()
    return Response(
        content=buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="report-{report_id}-decompiled.zip"'},
    )


def _zip_decompiled_classes(by_sub_filename: dict[str, list["JarDecompiledClass"]]) -> bytes:
    """One top-level folder per jar, then one subfolder per engine
    (cfr/vineflower), package tree underneath each — matches the layout each
    engine itself writes to disk, just re-zipped from the DB-stored rows.
    Splitting by engine (rather than merging) is the point: this export is
    the redundancy the dual-engine feature exists for, so both full outputs
    are kept side by side rather than one silently overwriting the other."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, classes in by_sub_filename.items():
            folder = Path(filename).stem
            for c in classes:
                zf.writestr(f"{folder}/{c.engine}/{c.class_name}.java", c.source or "")
    return buf.getvalue()


async def _get_decompile_run_or_404(db: AsyncSession, report_id: str, run_id: str, auth: AuthContext) -> JarDecompileRun:
    query = select(JarDecompileRun).where(
        JarDecompileRun.id == run_id,
        JarDecompileRun.report_id == report_id,
    )
    if not auth.is_global_admin:
        query = query.join(AnalysisReport, JarDecompileRun.report_id == AnalysisReport.id).where(
            AnalysisReport.tenant_id == auth.tenant_id
        )
    r = await db.execute(query)
    obj = r.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Decompile run not found")
    return obj


def _decompile_run_dict(r: JarDecompileRun) -> dict[str, Any]:
    return {
        "run_id": r.id,
        "report_id": r.report_id,
        "sub_report_id": r.sub_report_id,
        "status": r.status,
        "timeout_seconds": r.timeout_seconds,
        "jars_total": r.jars_total,
        "jars_completed": r.jars_completed,
        "jars_failed": r.jars_failed,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "results": json.loads(r.results_json) if r.results_json else [],
        "error": r.error,
    }


# ---------------------------------------------------------------------------
# Diagnostic Questionnaire — manual collection (air-gapped / restricted)
# ---------------------------------------------------------------------------

@router.get("/reports/{report_id}/diagnostic-questionnaire")
async def get_diagnostic_questionnaire(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Return a structured questionnaire of targeted information requests for this report."""
    rep, upload = await _get_report_and_upload_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    sub_dicts: list[dict] = []
    for sub in subs:
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()
        sub_dicts.append({
            "service_name": sub.service_name,
            "filename": sub.filename,
            "jar_type": sub.jar_type,
            "declared_port": sub.declared_port,
            "install_path": sub.install_path,
            "config_files": [_config_dict(c) for c in configs],
        })

    report_dict = {
        "report_id": rep.id,
        "manifest": json.loads(rep.manifest_json) if rep.manifest_json else {},
        "summary": json.loads(rep.summary_json) if rep.summary_json else {},
    }

    from app.services.jar_analyser.questionnaire_generator import generate_questionnaire
    sections = generate_questionnaire(report_dict, sub_dicts)
    return {
        "report_id": report_id,
        "platform_title": rep.implementation_title,
        "platform_version": rep.implementation_version,
        "total_sections": len(sections),
        "total_items": sum(len(s["items"]) for s in sections),
        "required_items": sum(1 for s in sections for i in s["items"] if i.get("required")),
        "sections": sections,
    }


@router.get("/reports/{report_id}/diagnostic-questionnaire/markdown")
async def get_diagnostic_questionnaire_markdown(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> PlainTextResponse:
    """Return the questionnaire as a Markdown checklist for offline use."""
    rep, upload = await _get_report_and_upload_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    sub_dicts: list[dict] = []
    for sub in subs:
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()
        sub_dicts.append({
            "service_name": sub.service_name,
            "filename": sub.filename,
            "jar_type": sub.jar_type,
            "declared_port": sub.declared_port,
            "install_path": sub.install_path,
            "config_files": [_config_dict(c) for c in configs],
        })

    report_dict = {
        "report_id": rep.id,
        "manifest": json.loads(rep.manifest_json) if rep.manifest_json else {},
        "summary": json.loads(rep.summary_json) if rep.summary_json else {},
    }

    from app.services.jar_analyser.questionnaire_generator import (
        generate_questionnaire, questionnaire_to_markdown,
    )
    sections = generate_questionnaire(report_dict, sub_dicts)
    content = questionnaire_to_markdown(
        sections, rep.id,
        rep.implementation_title or "platform",
        rep.implementation_version or "unknown",
    )
    filename = f"diag-questionnaire-{rep.implementation_version or 'unknown'}.md".replace(" ", "-")
    return PlainTextResponse(
        content=content, media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class QuestionnaireResponsesBody(BaseModel):
    responses: dict[str, str]  # {item_id: pasted_text}


@router.post("/reports/{report_id}/diagnostic-questionnaire/analyse", status_code=201)
async def analyse_questionnaire_responses(
    report_id: str,
    body: QuestionnaireResponsesBody,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Analyse manually-collected questionnaire responses and persist as a diagnostic run."""
    rep, upload = await _get_report_and_upload_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()

    sub_dicts: list[dict] = []
    for sub in subs:
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()
        sub_dicts.append({
            "service_name": sub.service_name,
            "filename": sub.filename,
            "declared_port": sub.declared_port,
            "config_files": [_config_dict(c) for c in configs],
        })

    report_dict = {
        "report_id": rep.id,
        "manifest": json.loads(rep.manifest_json) if rep.manifest_json else {},
        "summary": json.loads(rep.summary_json) if rep.summary_json else {},
    }

    from app.services.jar_analyser.questionnaire_generator import generate_questionnaire
    from app.services.jar_analyser.questionnaire_analyser import analyse_questionnaire_responses as _analyse

    sections = generate_questionnaire(report_dict, sub_dicts)
    kb_entries = await _fetch_kb_entries(db, auth.tenant_id, auth.is_global_admin)
    result = _analyse(body.responses, sections, sub_dicts, kb_entries)

    # Persist as a diagnostic run (bundle_filename marks it as questionnaire-sourced)
    run = _JarDiagnosticRun(
        report_id=report_id,
        uploaded_by=auth.username,
        bundle_filename="[manual-questionnaire]",
        bundle_size_bytes=sum(len(v) for v in body.responses.values()),
        status="completed",
        summary_json=json.dumps(result["summary"]),
        findings_json=json.dumps(result["findings"]),
        cert_results_json=json.dumps(result["cert_results"]),
        port_results_json=json.dumps(result["port_results"]),
        rmq_summary_json=json.dumps({}),
        config_issues_json=json.dumps(result["config_issues"]),
        log_findings_json=json.dumps(result["log_findings"]),
        os_info=result.get("os_info", ""),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return {
        "run_id": run.id,
        "report_id": report_id,
        "status": "completed",
        "source": "questionnaire",
        "missing_required": result["missing_required"],
        **_diag_run_full(run),
    }


@router.get("/reports/{report_id}/diagnostics/{run_id}/questionnaire-responses")
async def get_questionnaire_responses(
    report_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    """Return the questionnaire structure alongside a completed run (for review)."""
    run = await _get_diag_run_or_404(db, report_id, run_id, auth)
    if run.bundle_filename != "[manual-questionnaire]":
        raise HTTPException(status_code=409, detail="This run was not created from a questionnaire")

    rep, upload = await _get_report_and_upload_or_404(db, report_id, auth)
    subs = (await db.execute(
        select(SubReport).where(SubReport.parent_report_id == report_id)
    )).scalars().all()
    sub_dicts: list[dict] = []
    for sub in subs:
        configs = (await db.execute(
            select(JarConfigFile).where(JarConfigFile.sub_report_id == sub.id)
        )).scalars().all()
        sub_dicts.append({
            "service_name": sub.service_name,
            "filename": sub.filename,
            "jar_type": sub.jar_type,
            "declared_port": sub.declared_port,
            "install_path": sub.install_path,
            "config_files": [_config_dict(c) for c in configs],
        })
    report_dict = {
        "report_id": rep.id,
        "manifest": json.loads(rep.manifest_json) if rep.manifest_json else {},
        "summary": json.loads(rep.summary_json) if rep.summary_json else {},
    }
    from app.services.jar_analyser.questionnaire_generator import generate_questionnaire
    sections = generate_questionnaire(report_dict, sub_dicts)
    return {"run": _diag_run_full(run), "sections": sections}


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

def _find_jar_guide() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "Documentation" / "jar_analyser_operations_guide.md",
        Path("/opt/certmanager/Documentation/jar_analyser_operations_guide.md"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _parse_jar_guide_sections(content: str) -> list[dict]:
    import re
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
async def get_jar_help_sections(
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    guide = _find_jar_guide()
    if not guide:
        return {"available": False, "sections": [], "error": "JAR Analyser guide not found"}
    sections = _parse_jar_guide_sections(guide.read_text(encoding="utf-8"))
    return {
        "available": True,
        "total_sections": len(sections),
        "sections": [{"id": s["id"], "title": s["title"]} for s in sections],
    }


@router.get("/help/sections/{section_id}")
async def get_jar_help_section(
    section_id: str,
    auth: AuthContext = Depends(require_role("admin", "operator", "auditor", "readonly")),
) -> dict[str, Any]:
    guide = _find_jar_guide()
    if not guide:
        return {"available": False, "content": "", "error": "JAR Analyser guide not found"}
    for s in _parse_jar_guide_sections(guide.read_text(encoding="utf-8")):
        if s["id"] == section_id:
            return {"available": True, "id": s["id"], "title": s["title"], "content": s["content"].strip()}
    return {"available": False, "content": "", "error": f"Section {section_id} not found"}


# ---------------------------------------------------------------------------
# Delete / Re-run
# ---------------------------------------------------------------------------

@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    rep = await _get_report_or_404(db, report_id, auth)
    # jar_strings_fts is a SQLite FTS5 virtual table — it has no foreign key
    # to jar_string_constants, so the ondelete="CASCADE" that cleans up the
    # real rows on cascade delete below can't reach it. Must run before the
    # ORM delete, while the sub_reports this report owns can still be found.
    if settings.is_sqlite:
        await db.execute(text("""
            DELETE FROM jar_strings_fts WHERE id IN (
                SELECT jsc.id FROM jar_string_constants jsc
                JOIN sub_reports sr ON sr.id = jsc.sub_report_id
                WHERE sr.parent_report_id = :report_id
            )
        """), {"report_id": report_id})
    await db.delete(rep)
    await db.commit()


@router.post("/uploads/{upload_id}/reanalyse", status_code=202)
async def reanalyse_upload(
    upload_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Re-run analysis on an already-uploaded file."""
    upload = await _get_upload_or_404(db, upload_id, auth)
    stored = Path(upload.stored_path)
    if not stored.exists():
        raise HTTPException(status_code=409, detail="Stored file no longer exists on disk")
    upload.status = "pending"
    await db.commit()
    background_tasks.add_task(_run_analysis, upload.id, str(stored))
    return {
        "upload_id": upload.id,
        "status": "analysing",
        "status_url": f"/api/v1/jar-analyser/uploads/{upload.id}/status",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_upload_or_404(db: AsyncSession, upload_id: str, auth: AuthContext) -> JarUpload:
    query = select(JarUpload).where(JarUpload.id == upload_id)
    if not auth.is_global_admin:
        query = query.where(JarUpload.tenant_id == auth.tenant_id)
    r = await db.execute(query)
    obj = r.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Upload not found")
    return obj


async def _get_report_or_404(db: AsyncSession, report_id: str, auth: AuthContext) -> AnalysisReport:
    query = select(AnalysisReport).where(AnalysisReport.id == report_id)
    if not auth.is_global_admin:
        query = query.where(AnalysisReport.tenant_id == auth.tenant_id)
    r = await db.execute(query)
    obj = r.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Report not found")
    return obj


async def _get_report_and_upload_or_404(db: AsyncSession, report_id: str, auth: AuthContext):
    query = (
        select(AnalysisReport, JarUpload)
        .join(JarUpload, AnalysisReport.upload_id == JarUpload.id)
        .where(AnalysisReport.id == report_id)
    )
    if not auth.is_global_admin:
        query = query.where(AnalysisReport.tenant_id == auth.tenant_id)
    r = await db.execute(query)
    row = r.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return row


async def _get_diff_or_404(db: AsyncSession, diff_id: str, auth: AuthContext) -> JarDiffReport:
    r = await db.execute(select(JarDiffReport).where(JarDiffReport.id == diff_id))
    obj = r.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Diff report not found")
    if not auth.is_global_admin:
        # A diff spans two reports — both must belong to the caller's tenant,
        # not just one of them.
        tr = await db.execute(
            select(AnalysisReport.tenant_id).where(AnalysisReport.id.in_([obj.report_a_id, obj.report_b_id]))
        )
        tenant_ids = {row[0] for row in tr.all()}
        if tenant_ids - {auth.tenant_id}:
            raise HTTPException(status_code=404, detail="Diff report not found")
    return obj


async def _get_sub_or_404(db: AsyncSession, report_id: str, sub_id: str, auth: AuthContext) -> SubReport:
    query = select(SubReport).where(SubReport.id == sub_id, SubReport.parent_report_id == report_id)
    if not auth.is_global_admin:
        # Join back to the parent report's tenant rather than trusting that
        # the caller already validated report_id via _get_report_or_404 —
        # makes this lookup independently tenant-safe regardless of call order.
        query = query.join(AnalysisReport, SubReport.parent_report_id == AnalysisReport.id).where(
            AnalysisReport.tenant_id == auth.tenant_id
        )
    r = await db.execute(query)
    obj = r.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Sub-report not found")
    return obj


def _sub_summary(s: SubReport) -> dict[str, Any]:
    return {
        "sub_report_id": s.id,
        "filename": s.filename,
        "service_name": s.service_name,
        "jar_type": s.jar_type,
        "declared_port": s.declared_port,
        "spring_boot_version": s.spring_boot_version,
        "size_bytes": s.size_bytes,
        "depth": s.depth,
        "group_name": s.group_name,
        "install_path": s.install_path,
        "analysis_duration_ms": s.analysis_duration_ms,
    }


def _sub_full(s: SubReport) -> dict[str, Any]:
    d = _sub_summary(s)
    d.update({
        "start_class": s.start_class,
        "application_name": s.application_name,
        "implementation_version": s.implementation_version,
        "manifest": json.loads(s.manifest_json) if s.manifest_json else {},
        "installer_metadata": json.loads(s.installer_metadata_json) if s.installer_metadata_json else {},
        "package_structure": json.loads(s.package_structure_json) if s.package_structure_json else {},
        "class_file_versions": json.loads(s.class_file_versions_json) if s.class_file_versions_json else {},
        "purpose_narrative": json.loads(s.purpose_narrative_json) if s.purpose_narrative_json else [],
    })
    return d


def _endpoint_dict(e: JarEndpoint) -> dict[str, Any]:
    sec = json.loads(e.security_json) if e.security_json else None
    if sec and e.parsed_auth_json:
        sec["parsed_auth"] = json.loads(e.parsed_auth_json)
    return {
        "id": e.id,
        "controller_class": e.controller_class,
        "controller_simple": e.controller_simple,
        "http_method": e.http_method,
        "path": e.path,
        "full_path": e.full_path,
        "base_path": e.base_path,
        "method_name": e.method_name,
        "parameters": json.loads(e.parameters_json) if e.parameters_json else [],
        "request_body": json.loads(e.request_body_json) if e.request_body_json else None,
        "return_type": json.loads(e.return_type_json) if e.return_type_json else None,
        "security": sec,
        "confidence": e.confidence,
        "source_annotation": e.source_annotation,
        "signature_key": e.signature_key,
        "is_paginated": getattr(e, "is_paginated", False) or False,
        "page_param": getattr(e, "page_param", None),
        "size_param": getattr(e, "size_param", None),
        "sort_param": getattr(e, "sort_param", None),
        "default_page_size": getattr(e, "default_page_size", None),
        "is_deprecated": getattr(e, "is_deprecated", False) or False,
        "linked_tables": json.loads(e.linked_tables_json) if getattr(e, "linked_tables_json", None) else [],
        "is_proxied": getattr(e, "is_proxied", None),
        # Developer-authored text extracted from @Operation element values — never
        # confuse with anything inferred by this tool (see doc_authored on the schema side).
        "doc_summary": getattr(e, "doc_summary", None),
        "doc_description": getattr(e, "doc_description", None),
        "payload_shape_known": getattr(e, "payload_shape_known", None),
    }


def _dep_dict(d: JarDependency) -> dict[str, Any]:
    return {
        "id": d.id,
        "filename": d.filename,
        "group_id": d.group_id,
        "artifact_id": d.artifact_id,
        "version": d.version,
        "category": d.category,
        "size_bytes": d.size_bytes,
        "maven_coordinates": d.maven_coordinates,
        "source_path": d.source_path,
        "manifest_title": d.manifest_title,
        "manifest_vendor": d.manifest_vendor,
        "coordinates_source": d.coordinates_source,
    }


def _config_dict(c: JarConfigFile) -> dict[str, Any]:
    return {
        "id": c.id,
        "filename": c.filename,
        "path_in_jar": c.path_in_jar,
        "file_type": c.file_type,
        "profile": c.profile,
        "content": c.content,
        "key_count": c.key_count,
        "encrypted_count": c.encrypted_count,
        "placeholder_count": c.placeholder_count,
        "ssl_key_count": c.ssl_key_count,
        "db_key_count": c.db_key_count,
        "mq_key_count": c.mq_key_count,
        "keys": json.loads(c.keys_json) if c.keys_json else [],
    }


def _migration_dict(m: JarMigrationScript) -> dict[str, Any]:
    return {
        "id": m.id,
        "filename": m.filename,
        "version": m.version,
        "description": m.description,
        "script_type": m.script_type,
        "size_bytes": m.size_bytes,
        "statement_count": m.statement_count,
        "ddl_operations": json.loads(m.ddl_operations_json) if m.ddl_operations_json else [],
        "tables_affected": json.loads(m.tables_json) if m.tables_json else [],
        "content": m.content,
    }


def _event_dict(e: JarEventFile) -> dict[str, Any]:
    return {
        "id": e.id,
        "filename": e.filename,
        "path_in_jar": e.path_in_jar,
        "content": e.content,
        "published": json.loads(e.published_json) if e.published_json else [],
        "consumed": json.loads(e.consumed_json) if e.consumed_json else [],
    }


def _error_response_dict(e: "JarErrorResponse") -> dict[str, Any]:
    return {
        "id": e.id,
        "http_status": e.http_status,
        "exception_class": e.exception_class,
        "response_schema_class": e.response_schema_class,
        "scope": e.scope,
        "controller_class": e.controller_class,
        "fields": json.loads(e.fields_json) if e.fields_json else [],
    }


def _workflow_dict(w: "JarWorkflow") -> dict[str, Any]:
    return {
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "category": w.category,
        "source": w.source,
        "steps": json.loads(w.steps_json) if w.steps_json else [],
    }


def _scheduled_job_dict(j: "JarScheduledJob") -> dict[str, Any]:
    return {
        "id": j.id,
        "declaring_class": j.declaring_class,
        "declaring_class_simple": j.declaring_class_simple,
        "method_name": j.method_name,
        "cron": j.cron,
        "fixed_rate_ms": j.fixed_rate_ms,
        "fixed_delay_ms": j.fixed_delay_ms,
        "initial_delay_ms": j.initial_delay_ms,
        "zone": j.zone,
        "is_config_driven": j.is_config_driven,
        "display": j.display,
    }


def _diff_dict(d: JarDiffReport, full: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "diff_id": d.id,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "report_a_id": d.report_a_id,
        "report_b_id": d.report_b_id,
        "label_a": d.label_a,
        "label_b": d.label_b,
        "summary": json.loads(d.summary_json) if d.summary_json else {},
        "warnings": json.loads(d.warnings_json) if d.warnings_json else [],
    }
    if full:
        diff_doc = json.loads(d.diff_json) if d.diff_json else {}
        result["report_a"] = diff_doc.get("report_a", {})
        result["report_b"] = diff_doc.get("report_b", {})
        result["service_diffs"] = diff_doc.get("service_diffs", [])
    return result
