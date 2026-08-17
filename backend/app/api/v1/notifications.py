"""Notification preferences and SMTP management endpoints."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_permission, AuthContext
from app.models.notification import NotificationPreference, NotificationQueue
from app.models.user import User
from app.services.audit import audit_event
from app.services.email_service import test_smtp_connection, send_templated_email
from app.core.config import settings

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])

EVENT_TYPES = [
    "expiry_warning", "cert_issued", "approval_required",
    "approval_decision", "security_event", "auto_renewal",
    "bm_job_failed", "bm_environment_degraded", "bm_cert_binding_expiring",
    "bm_secret_rotation_overdue",
    "bug_assigned", "bug_status_changed", "bug_occurrence_linked",
]


class PreferenceCreate(BaseModel):
    event_type: str
    enabled: bool = True
    filter_ca_id: str | None = None
    filter_tag: str | None = None
    digest_mode: bool = False


class PreferenceUpdate(BaseModel):
    enabled: bool | None = None
    digest_mode: bool | None = None


class SMTPSettingsUpdate(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    from_address: str = "PKI Alerts <pki@corp.internal>"
    tls: str = "starttls"


# --- User email ---

class EmailUpdate(BaseModel):
    email: str


@router.get("/my-email")
async def get_my_email(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:read")),
) -> dict:
    """Get current user's notification email address."""
    user = await db.get(User, auth.user_id)
    return {
        "notification_email": user.notification_email if user else None,
        "account_email": user.email if user else None,
        "effective_email": (user.notification_email or user.email) if user else None,
    }


@router.put("/my-email")
async def update_my_email(
    body: EmailUpdate,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:read")),
) -> dict:
    """Set notification email address for current user."""
    from fastapi import HTTPException
    user = await db.get(User, auth.user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.notification_email = body.email.strip() or None
    await db.commit()
    return {"status": "updated", "notification_email": user.notification_email}


# --- User preferences ---

@router.get("/preferences")
async def get_my_preferences(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:read")),
) -> dict:
    """Get current user's notification preferences."""
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == auth.user_id
        )
    )
    prefs = result.scalars().all()
    return {
        "preferences": [
            {
                "id": p.id,
                "event_type": p.event_type,
                "enabled": p.enabled,
                "filter_ca_id": p.filter_ca_id,
                "filter_tag": p.filter_tag,
                "digest_mode": p.digest_mode,
                "mandatory": p.mandatory,
            }
            for p in prefs
        ],
        "available_events": EVENT_TYPES,
    }


@router.post("/preferences")
async def create_preference(
    body: PreferenceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:read")),
) -> dict:
    """Subscribe to a notification event."""
    if body.event_type not in EVENT_TYPES:
        from fastapi import HTTPException
        raise HTTPException(400, f"Invalid event_type. Must be one of: {EVENT_TYPES}")

    tenant_id = getattr(request.state, "tenant_id", None) or "00000000-0000-0000-0000-000000000001"

    pref = NotificationPreference(
        user_id=auth.user_id,
        event_type=body.event_type,
        enabled=body.enabled,
        filter_ca_id=body.filter_ca_id,
        filter_tag=body.filter_tag,
        digest_mode=body.digest_mode,
        tenant_id=tenant_id,
    )
    db.add(pref)
    await db.commit()
    return {"id": pref.id, "status": "created"}


@router.put("/preferences/{pref_id}")
async def update_preference(
    pref_id: str,
    body: PreferenceUpdate,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:read")),
) -> dict:
    """Update a notification preference."""
    from fastapi import HTTPException
    pref = await db.get(NotificationPreference, pref_id)
    if not pref or pref.user_id != auth.user_id:
        raise HTTPException(404, "Preference not found")
    if pref.mandatory:
        raise HTTPException(403, "Cannot modify mandatory notification")

    if body.enabled is not None:
        pref.enabled = body.enabled
    if body.digest_mode is not None:
        pref.digest_mode = body.digest_mode
    await db.commit()
    return {"status": "updated"}


@router.delete("/preferences/{pref_id}")
async def delete_preference(
    pref_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:read")),
) -> dict:
    """Remove a notification subscription."""
    from fastapi import HTTPException
    pref = await db.get(NotificationPreference, pref_id)
    if not pref or pref.user_id != auth.user_id:
        raise HTTPException(404, "Preference not found")
    if pref.mandatory:
        raise HTTPException(403, "Cannot delete mandatory notification")

    await db.delete(pref)
    await db.commit()
    return {"status": "deleted"}


# --- Admin: SMTP settings ---

@router.get("/smtp")
async def get_smtp_settings(
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Get current SMTP configuration (password masked)."""
    return {
        "enabled": settings.SMTP_ENABLED,
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "user": settings.SMTP_USER,
        "password": "••••••••" if settings.SMTP_PASSWORD else "",
        "from_address": settings.SMTP_FROM,
        "tls": settings.SMTP_TLS,
        "digest_hour": settings.NOTIFICATION_DIGEST_HOUR,
    }


@router.put("/smtp")
async def update_smtp_settings(
    body: SMTPSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Update SMTP settings (in-memory, update .env for persistence)."""
    settings.SMTP_ENABLED = body.enabled
    settings.SMTP_HOST = body.host
    settings.SMTP_PORT = body.port
    settings.SMTP_USER = body.user
    if body.password:
        settings.SMTP_PASSWORD = body.password
    settings.SMTP_FROM = body.from_address
    settings.SMTP_TLS = body.tls

    await audit_event(
        db=db, event_type="SMTP_SETTINGS_UPDATED", severity="INFO",
        request=request, subject_type="settings", subject_id="smtp",
        description=f"SMTP settings updated. Enabled={body.enabled}, Host={body.host}",
    )
    await db.commit()
    return {"status": "updated", "enabled": body.enabled}


@router.post("/smtp/test")
async def test_smtp(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Test SMTP connectivity."""
    result = await test_smtp_connection()

    await audit_event(
        db=db, event_type="SMTP_CONNECTION_TEST", severity="INFO",
        request=request, subject_type="settings", subject_id="smtp",
        description=f"SMTP test: {result['status']}",
    )
    await db.commit()
    return result


@router.post("/smtp/test-email")
async def send_test_email(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Send a test email to the current user."""
    # Get user email
    if not auth.user_id:
        from fastapi import HTTPException
        raise HTTPException(400, "No user context (API key auth has no email)")

    user = await db.get(User, auth.user_id)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(400, "User not found")
    to_email = user.notification_email or user.email
    if not to_email:
        from fastapi import HTTPException
        raise HTTPException(400, "No email address configured. Set one in My Preferences.")

    success = await send_templated_email(
        to_email, "cert_issued",
        cn="test.example.com", serial="abc123def456",
        profile="server", expires_at="2025-12-31T00:00:00Z",
    )
    return {"status": "sent" if success else "failed", "to": to_email}


# --- Admin: mandatory notifications ---

class MandatoryCreate(BaseModel):
    user_id: str
    event_type: str


@router.post("/mandatory")
async def create_mandatory_notification(
    body: MandatoryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Create a mandatory notification for a user (cannot be disabled by user)."""
    from fastapi import HTTPException
    if body.event_type not in EVENT_TYPES:
        raise HTTPException(400, f"Invalid event_type")

    tenant_id = getattr(request.state, "tenant_id", None) or "00000000-0000-0000-0000-000000000001"

    pref = NotificationPreference(
        user_id=body.user_id,
        event_type=body.event_type,
        enabled=True,
        mandatory=True,
        tenant_id=tenant_id,
    )
    db.add(pref)
    await db.commit()
    return {"id": pref.id, "status": "created", "mandatory": True}
