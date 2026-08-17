"""Repeated download detection — flags certificates with excessive key downloads."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.certificate import Certificate

WARNING_EVENT_TYPES = ("KEY_DOWNLOAD", "P12_DOWNLOAD", "JKS_DOWNLOAD")
KEY_THRESHOLD = 3
BACKUP_THRESHOLD = 2
WINDOW_HOURS = 24


async def check_repeated_downloads(
    db: AsyncSession,
    subject_id: str,
    event_type: str,
) -> bool:
    """Check if download threshold exceeded. Returns True if flag was set."""
    if event_type not in WARNING_EVENT_TYPES:
        return False

    since = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)

    count_q = select(func.count()).where(
        AuditEvent.subject_id == subject_id,
        AuditEvent.event_type.in_(WARNING_EVENT_TYPES),
        AuditEvent.timestamp >= since,
    )
    result = await db.execute(count_q)
    count = result.scalar() or 0

    if count >= KEY_THRESHOLD:
        # Set flag on certificate
        cert_q = select(Certificate).where(Certificate.serial == subject_id)
        cert_result = await db.execute(cert_q)
        cert = cert_result.scalar_one_or_none()
        if cert and not cert.repeated_key_download:
            cert.repeated_key_download = True
            return True

    return False
