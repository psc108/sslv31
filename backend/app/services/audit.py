"""Audit event helper — single-call function for recording audit events with hash chain."""

import hashlib
import json
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _compute_hash(event_type: str, subject_id: str, timestamp: str, prev_hash: str) -> str:
    """SHA-256 hash of event data + previous hash for tamper evidence."""
    payload = f"{prev_hash}|{timestamp}|{event_type}|{subject_id}"
    return hashlib.sha256(payload.encode()).hexdigest()


async def audit_event(
    db: AsyncSession,
    event_type: str,
    severity: str,
    request: Request,
    subject_type: str,
    subject_id: str,
    detail: dict | None = None,
    description: str | None = None,
    tenant_id: str | None = None,
) -> None:
    """Write an audit event atomically within the caller's transaction."""
    source_ip = getattr(request.state, "source_ip", None) or (
        request.client.host if request.client else "unknown"
    )
    api_key_hint = getattr(request.state, "api_key_hint", None)

    # Resolve tenant_id from request state (set by auth context) or fallback
    if tenant_id is None:
        tenant_id = getattr(request.state, "tenant_id", None) or DEFAULT_TENANT_ID

    now = datetime.now(timezone.utc)
    # Use naive timestamp string for hash (SQLite strips timezone)
    ts_for_hash = now.replace(tzinfo=None).isoformat()

    # Get previous hash for chain
    result = await db.execute(
        select(AuditEvent.prev_hash, AuditEvent.id)
        .order_by(desc(AuditEvent.id))
        .limit(1)
    )
    row = result.first()
    last_hash = row[0] if row and row[0] else "0" * 64

    # Use subject_id or "" consistently (matches verification)
    current_hash = _compute_hash(event_type, subject_id or "", ts_for_hash, last_hash)

    event = AuditEvent(
        timestamp=now,
        event_type=event_type,
        severity=severity,
        source_ip=source_ip,
        api_key_hint=api_key_hint,
        subject_type=subject_type,
        subject_id=subject_id,
        detail_json=json.dumps(detail) if detail else None,
        description=description,
        prev_hash=current_hash,
        tenant_id=tenant_id,
    )
    db.add(event)
