"""Secrets service — encrypted storage for deployment secrets (passwords, tokens)."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.build_manager import BMSecret

logger = logging.getLogger(__name__)

# Reuse the existing CERT_MASTER_KEY (Fernet) for secrets encryption
_fernet = Fernet(settings.CERT_MASTER_KEY.encode())


def _encrypt(plaintext: str) -> bytes:
    return _fernet.encrypt(plaintext.encode())


def _decrypt(blob: bytes) -> str:
    return _fernet.decrypt(blob).decode()


def encrypt_value(plaintext: str) -> str:
    """Encrypt a value for storage in a *text* column (e.g. BMHostVar.value) —
    same Fernet key as secrets, but returns a string rather than bytes since
    the target column isn't LargeBinary. Shared here so other Build Manager
    modules don't each stand up their own Fernet instance."""
    return _encrypt(plaintext).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a value previously encrypted with encrypt_value()."""
    return _decrypt(ciphertext.encode())


async def list_secrets(db: AsyncSession) -> list[dict]:
    """List all secrets (names only, no values)."""
    result = await db.execute(select(BMSecret).order_by(BMSecret.name))
    return [_secret_to_dict(s, include_value=False) for s in result.scalars().all()]


async def get_secret(db: AsyncSession, secret_id: str) -> dict:
    """Retrieve a secret including its decrypted value."""
    result = await db.execute(select(BMSecret).where(BMSecret.id == secret_id))
    secret = result.scalar_one_or_none()
    if not secret:
        raise ValueError("Secret not found")
    return _secret_to_dict(secret, include_value=True)


async def create_secret(
    db: AsyncSession, name: str, value: str, category: str = "custom",
    linked_service: str = "", description: str = "",
    created_by: str = "system", tenant_id: str = "00000000-0000-0000-0000-000000000001",
    rotate_every_days: int | None = None,
) -> dict:
    """Store a new encrypted secret."""
    # Check uniqueness
    existing = await db.execute(select(BMSecret).where(BMSecret.name == name))
    if existing.scalar_one_or_none():
        raise ValueError(f"Secret '{name}' already exists")

    secret = BMSecret(
        name=name,
        value_encrypted=_encrypt(value),
        category=category,
        linked_service=linked_service,
        description=description,
        created_by=created_by,
        tenant_id=tenant_id,
        rotate_every_days=rotate_every_days,
    )
    db.add(secret)
    await db.commit()
    await db.refresh(secret)
    return _secret_to_dict(secret, include_value=False)


async def update_secret(
    db: AsyncSession, secret_id: str, value: str | None = None,
    category: str | None = None, linked_service: str | None = None,
    description: str | None = None, rotate_every_days: int | None = None,
    rotate_every_days_set: bool = False,
) -> dict:
    """Update a secret's value or metadata.

    rotate_every_days_set distinguishes "the caller didn't mention this
    field" (rotate_every_days stays None as a sentinel and is left alone)
    from "the caller explicitly wants it cleared" (rotate_every_days=None,
    rotate_every_days_set=True) — a bare None default can't tell those apart.
    """
    result = await db.execute(select(BMSecret).where(BMSecret.id == secret_id))
    secret = result.scalar_one_or_none()
    if not secret:
        raise ValueError("Secret not found")

    if value is not None:
        secret.value_encrypted = _encrypt(value)
        secret.rotated_at = datetime.now(timezone.utc)
        secret.rotation_notified = False
    if category is not None:
        secret.category = category
    if linked_service is not None:
        secret.linked_service = linked_service
    if description is not None:
        secret.description = description
    if rotate_every_days_set:
        secret.rotate_every_days = rotate_every_days
        secret.rotation_notified = False

    await db.commit()
    return _secret_to_dict(secret, include_value=False)


async def rotate_secret(db: AsyncSession, secret_id: str, new_value: str) -> dict:
    """Rotate a secret's value (explicit rotation with new value)."""
    result = await db.execute(select(BMSecret).where(BMSecret.id == secret_id))
    secret = result.scalar_one_or_none()
    if not secret:
        raise ValueError("Secret not found")

    secret.value_encrypted = _encrypt(new_value)
    secret.rotated_at = datetime.now(timezone.utc)
    secret.rotation_notified = False
    await db.commit()
    return _secret_to_dict(secret, include_value=False)


async def delete_secret(db: AsyncSession, secret_id: str) -> None:
    """Delete a secret."""
    result = await db.execute(select(BMSecret).where(BMSecret.id == secret_id))
    secret = result.scalar_one_or_none()
    if not secret:
        raise ValueError("Secret not found")
    await db.delete(secret)
    await db.commit()


async def get_ansible_extra_vars(db: AsyncSession, linked_service: str | None = None) -> dict[str, str]:
    """Build a dict of decrypted secrets suitable for Ansible --extra-vars injection.

    Keys are prefixed with 'vault_' to match Ansible Vault convention.
    Values are NEVER written to disk — only passed in-memory to subprocess.
    """
    query = select(BMSecret)
    if linked_service:
        query = query.where(BMSecret.linked_service == linked_service)
    result = await db.execute(query)
    secrets = result.scalars().all()

    extra_vars = {}
    for s in secrets:
        key = f"vault_{s.name}"
        extra_vars[key] = _decrypt(s.value_encrypted)
    return extra_vars


def mask_value(value: str) -> str:
    """Mask a secret value for display (show first 2 and last 2 chars)."""
    if len(value) <= 6:
        return "••••••"
    return value[:2] + "•" * (len(value) - 4) + value[-2:]


def rotation_due_at(s: BMSecret) -> datetime | None:
    """When this secret's rotation policy next requires action, or None if
    it has no policy. Measured from rotated_at if it's ever been rotated,
    otherwise from created_at — a secret that's never been rotated is still
    subject to its policy from the moment it was created."""
    if s.rotate_every_days is None:
        return None
    baseline = s.rotated_at or s.created_at
    return baseline + timedelta(days=s.rotate_every_days)


def is_rotation_overdue(s: BMSecret, now: datetime | None = None) -> bool:
    due = rotation_due_at(s)
    if due is None:
        return False
    now = now or datetime.now(timezone.utc)
    if due.tzinfo is None:
        now = now.replace(tzinfo=None)
    return now >= due


async def scan_overdue_secrets(db: AsyncSession) -> list[str]:
    """Fire a one-shot notification for each secret that just became overdue
    (rotation_notified is still False) — not on every scan tick, matching
    the anti-spam discipline health_service.py's degraded-transition check
    already established. Returns the names notified this pass."""
    from app.services.notification_service import notify_event

    result = await db.execute(
        select(BMSecret).where(BMSecret.rotate_every_days.isnot(None), BMSecret.rotation_notified == False)  # noqa: E712
    )
    now = datetime.now(timezone.utc)
    notified = []
    for secret in result.scalars().all():
        if not is_rotation_overdue(secret, now):
            continue
        await notify_event(
            db, "bm_secret_rotation_overdue", tenant_id=secret.tenant_id,
            secret_name=secret.name, rotate_every_days=secret.rotate_every_days,
            due_at=rotation_due_at(secret).isoformat(),
        )
        secret.rotation_notified = True
        notified.append(secret.name)
    if notified:
        await db.commit()
    return notified


async def run_secret_rotation_scanner(session_factory) -> None:
    """Periodic background loop (mirrors environment_service.py's
    run_environment_ttl_scheduler) — checks for newly-overdue secret
    rotations and notifies once per overdue transition. Deliberately
    flag-only: never rotates a secret itself, since a wrong automatic
    rotation could break a live service still using the old value."""
    interval = settings.BM_SECRET_ROTATION_CHECK_INTERVAL_MINUTES * 60
    while True:
        try:
            async with session_factory() as db:
                await scan_overdue_secrets(db)
        except Exception as e:
            logger.error(f"Secret rotation scan failed: {e}")
        await asyncio.sleep(interval)


def _secret_to_dict(s: BMSecret, include_value: bool = False) -> dict:
    due = rotation_due_at(s)
    d = {
        "id": s.id,
        "name": s.name,
        "category": s.category,
        "linked_service": s.linked_service,
        "description": s.description,
        "created_by": s.created_by,
        "rotated_at": s.rotated_at.isoformat() if s.rotated_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "rotate_every_days": s.rotate_every_days,
        "rotation_due_at": due.isoformat() if due else None,
        "rotation_overdue": is_rotation_overdue(s),
    }
    if include_value:
        d["value"] = _decrypt(s.value_encrypted)
    else:
        d["masked_value"] = mask_value(_decrypt(s.value_encrypted))
    return d
