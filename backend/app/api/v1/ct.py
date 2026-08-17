"""Certificate Transparency log API — query, verify, monitor."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_auth_context, require_permission, AuthContext
from app.models.ct_log import CTLogEntry, CTTreeHead
from app.services.ct_service import (
    get_tree_head,
    verify_tree_consistency,
    detect_anomalies,
)

router = APIRouter(prefix="/api/v1/ct", tags=["Certificate Transparency"])


@router.get("/entries")
async def list_ct_entries(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    domain: str | None = None,
    ca_id: str | None = None,
    since: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """Query CT log entries with optional filters."""
    query = select(CTLogEntry)

    if not auth.is_global_admin:
        query = query.where(CTLogEntry.tenant_id == auth.tenant_id)

    if domain:
        query = query.where(
            CTLogEntry.subject_cn.contains(domain) |
            CTLogEntry.san_json.contains(domain)
        )
    if ca_id:
        query = query.where(CTLogEntry.issuer_ca_id == ca_id)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            if since_dt.tzinfo:
                since_dt = since_dt.replace(tzinfo=None)
            query = query.where(CTLogEntry.timestamp >= since_dt)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid 'since' date format (use ISO 8601)")

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    query = query.order_by(desc(CTLogEntry.log_index))
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    entries = result.scalars().all()

    items = [
        {
            "id": e.id,
            "log_index": e.log_index,
            "cert_serial": e.cert_serial,
            "cert_der_hash": e.cert_der_hash,
            "issuer_ca_id": e.issuer_ca_id,
            "subject_cn": e.subject_cn,
            "san": json.loads(e.san_json) if e.san_json else [],
            "leaf_hash": e.leaf_hash,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "sct": json.loads(e.sct_json) if e.sct_json else None,
        }
        for e in entries
    ]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/entries/{log_index}")
async def get_ct_entry(
    log_index: int,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """Get a single CT log entry by index."""
    result = await db.execute(
        select(CTLogEntry).where(CTLogEntry.log_index == log_index)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="CT log entry not found")

    return {
        "id": entry.id,
        "log_index": entry.log_index,
        "cert_serial": entry.cert_serial,
        "cert_der_hash": entry.cert_der_hash,
        "issuer_ca_id": entry.issuer_ca_id,
        "subject_cn": entry.subject_cn,
        "san": json.loads(entry.san_json) if entry.san_json else [],
        "leaf_hash": entry.leaf_hash,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "sct": json.loads(entry.sct_json) if entry.sct_json else None,
        "tenant_id": entry.tenant_id,
    }


@router.get("/sth")
async def get_signed_tree_head(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """Get the current Signed Tree Head (STH)."""
    return await get_tree_head(db)


@router.post("/verify")
async def verify_ct_log(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """Verify CT log Merkle tree consistency."""
    return await verify_tree_consistency(db)


@router.get("/anomalies")
async def get_anomalies(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> dict:
    """Detect anomalous certificates in the CT log."""
    tenant_id = None if auth.is_global_admin else auth.tenant_id
    alerts = await detect_anomalies(db, tenant_id)
    return {"alerts": alerts, "count": len(alerts)}


@router.get("/stats")
async def ct_stats(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """CT log statistics."""
    query = select(func.count()).select_from(CTLogEntry)
    if not auth.is_global_admin:
        query = query.where(CTLogEntry.tenant_id == auth.tenant_id)
    total = (await db.execute(query)).scalar() or 0

    # Last entry timestamp
    last_q = select(CTLogEntry.timestamp).order_by(desc(CTLogEntry.log_index)).limit(1)
    last_result = await db.execute(last_q)
    last_row = last_result.first()
    last_entry = last_row[0].isoformat() if last_row and last_row[0] else None

    # Tree heads count
    heads_count = (await db.execute(select(func.count()).select_from(CTTreeHead))).scalar() or 0

    return {
        "total_entries": total,
        "last_entry_at": last_entry,
        "tree_heads_stored": heads_count,
    }
