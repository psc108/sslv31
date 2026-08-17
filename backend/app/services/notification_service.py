"""Notification dispatch service — routes events to subscribed users."""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.notification import NotificationPreference, NotificationQueue
from app.models.user import User
from app.services.email_service import send_email, _render_template

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


async def notify_event(
    db: AsyncSession,
    event_type: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    ca_id: str | None = None,
    tag: str | None = None,
    **template_kwargs,
) -> int:
    """Dispatch notification for an event to all subscribed users.

    Returns number of notifications sent/queued.
    """
    if not settings.SMTP_ENABLED:
        return 0

    # Find all preferences matching this event
    conditions = [
        NotificationPreference.event_type == event_type,
        NotificationPreference.enabled == True,
        NotificationPreference.tenant_id == tenant_id,
    ]

    result = await db.execute(
        select(NotificationPreference).where(and_(*conditions))
    )
    prefs = result.scalars().all()

    sent = 0
    for pref in prefs:
        # Apply CA filter
        if pref.filter_ca_id and ca_id and pref.filter_ca_id != ca_id:
            continue
        # Apply tag filter
        if pref.filter_tag and tag and pref.filter_tag != tag:
            continue

        # Get user email (prefer notification_email over account email)
        user = await db.get(User, pref.user_id)
        if not user or not user.active:
            continue
        to_email = user.notification_email or user.email
        if not to_email:
            continue

        subject, body_html = _render_template(event_type, **template_kwargs)

        if pref.digest_mode:
            # Queue for daily digest
            db.add(NotificationQueue(
                user_id=pref.user_id,
                event_type=event_type,
                subject=subject,
                body_html=body_html,
                tenant_id=tenant_id,
            ))
            sent += 1
        else:
            # Send immediately (fire-and-forget, don't block caller)
            asyncio.create_task(_send_safe(to_email, subject, body_html))
            sent += 1

    return sent


async def notify_admins(
    db: AsyncSession,
    event_type: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    **template_kwargs,
) -> int:
    """Send notification to all admin users (for security events, ceremonies)."""
    if not settings.SMTP_ENABLED:
        return 0

    result = await db.execute(
        select(User).where(and_(User.role == "admin", User.active == True))
    )
    admins = result.scalars().all()

    subject, body_html = _render_template(event_type, **template_kwargs)
    sent = 0
    for admin in admins:
        if admin.email:
            asyncio.create_task(_send_safe(admin.email, subject, body_html))
            sent += 1
    return sent


async def send_digest(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Send daily digest emails for queued notifications."""
    async with session_factory() as db:
        # Get unsent queue items grouped by user
        result = await db.execute(
            select(NotificationQueue).where(NotificationQueue.sent == False)
        )
        items = result.scalars().all()

        if not items:
            return

        # Group by user
        by_user: dict[str, list[NotificationQueue]] = {}
        for item in items:
            by_user.setdefault(item.user_id, []).append(item)

        for user_id, user_items in by_user.items():
            user = await db.get(User, user_id)
            if not user:
                continue
            to_email = user.notification_email or user.email
            if not to_email:
                continue

            # Build digest HTML
            items_html = ""
            for item in user_items:
                items_html += f'<div style="border-left:3px solid #3b82f6;padding:8px 12px;margin:8px 0"><strong>{item.subject}</strong></div>\n'

            subject, body = _render_template(
                "digest", count=len(user_items), items=items_html
            )
            await _send_safe(to_email, subject, body)

            # Mark as sent
            for item in user_items:
                item.sent = True

        await db.commit()
        logger.info(f"Digest sent to {len(by_user)} users ({len(items)} notifications)")


async def _send_safe(to_email: str, subject: str, body_html: str) -> None:
    """Send email, swallowing exceptions."""
    try:
        await send_email(to_email, subject, body_html)
    except Exception as e:
        logger.warning(f"Notification send failed to {to_email}: {e}")


async def run_digest_scheduler(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Background task: send digest at configured hour (UTC)."""
    while True:
        now = datetime.now(timezone.utc)
        target_hour = settings.NOTIFICATION_DIGEST_HOUR
        # Calculate seconds until next target hour
        if now.hour < target_hour:
            next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        else:
            from datetime import timedelta
            next_run = (now + timedelta(days=1)).replace(hour=target_hour, minute=0, second=0, microsecond=0)

        wait_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        try:
            await send_digest(session_factory)
        except Exception as e:
            logger.error(f"Digest scheduler error: {e}")
