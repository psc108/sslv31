"""Audit log endpoint — paginated, filterable event retrieval."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_auth_context, AuthContext
from app.models.audit import AuditEvent
from app.api.v1.schemas import AuditEventResponse, PaginatedResponse

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


@router.get("")
async def list_audit_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    event_type: str | None = None,
    severity: str | None = None,
    subject_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> PaginatedResponse:
    query = select(AuditEvent)

    # Tenant scoping
    if not auth.is_global_admin:
        query = query.where(AuditEvent.tenant_id == auth.tenant_id)

    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    if severity:
        query = query.where(AuditEvent.severity == severity)
    if subject_id:
        query = query.where(AuditEvent.subject_id == subject_id)
    if from_date:
        query = query.where(AuditEvent.timestamp >= from_date)
    if to_date:
        query = query.where(AuditEvent.timestamp <= to_date)

    # Count total
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate (newest first)
    query = query.order_by(AuditEvent.timestamp.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    events = result.scalars().all()

    items = [
        AuditEventResponse(
            id=e.id,
            timestamp=e.timestamp,
            event_type=e.event_type,
            severity=e.severity,
            operator=e.operator,
            source_ip=e.source_ip,
            api_key_hint=e.api_key_hint,
            subject_type=e.subject_type,
            subject_id=e.subject_id,
            detail_json=e.detail_json,
            description=e.description,
        )
        for e in events
    ]

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)
