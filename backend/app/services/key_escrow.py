"""Key Escrow Service — encrypt/decrypt keys with a separate recovery key."""

import json
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.key_escrow import KeyEscrow, KeyRecoveryRequest
from app.models.certificate import Certificate


def _recovery_key() -> str:
    """Get the recovery key. Falls back to a derived key from CERT_MASTER_KEY if not configured."""
    key = settings.KEY_ESCROW_RECOVERY_KEY
    if key:
        return key
    # Derive a separate key from master key (not ideal but functional)
    import hashlib
    import base64
    derived = hashlib.sha256(f"escrow:{settings.CERT_MASTER_KEY}".encode()).digest()
    return base64.urlsafe_b64encode(derived).decode()


def encrypt_for_escrow(key_pem: bytes) -> bytes:
    """Encrypt a private key PEM with the recovery key."""
    f = Fernet(_recovery_key().encode())
    return f.encrypt(key_pem)


def decrypt_from_escrow(blob: bytes) -> bytes:
    """Decrypt an escrowed key blob with the recovery key."""
    f = Fernet(_recovery_key().encode())
    return f.decrypt(blob)


async def escrow_key(
    db: AsyncSession,
    certificate_serial: str,
    certificate_cn: str,
    profile: str,
    key_pem: bytes,
    escrowed_by: str,
    tenant_id: str,
) -> KeyEscrow:
    """Store a key in escrow, encrypted with the recovery key."""
    encrypted = encrypt_for_escrow(key_pem)
    entry = KeyEscrow(
        certificate_serial=certificate_serial,
        certificate_cn=certificate_cn,
        profile=profile,
        key_blob=encrypted,
        escrowed_at=datetime.now(timezone.utc),
        escrowed_by=escrowed_by,
        tenant_id=tenant_id,
    )
    db.add(entry)
    return entry


async def request_recovery(
    db: AsyncSession,
    certificate_serial: str,
    justification: str,
    requested_by: str,
    tenant_id: str,
) -> KeyRecoveryRequest:
    """Create a key recovery request requiring M-of-N approval."""
    # Find escrow entry
    result = await db.execute(
        select(KeyEscrow).where(KeyEscrow.certificate_serial == certificate_serial)
    )
    escrow = result.scalar_one_or_none()
    if not escrow:
        raise ValueError(f"No escrowed key found for serial {certificate_serial}")

    req = KeyRecoveryRequest(
        escrow_id=escrow.id,
        certificate_serial=certificate_serial,
        justification=justification,
        requested_by=requested_by,
        requested_at=datetime.now(timezone.utc),
        approvals_required=settings.KEY_RECOVERY_APPROVALS_REQUIRED,
        status="pending",
        tenant_id=tenant_id,
    )
    db.add(req)
    return req


async def approve_recovery(
    db: AsyncSession,
    request_id: str,
    approver: str,
) -> KeyRecoveryRequest:
    """Add an approval to a recovery request. If threshold met, mark approved."""
    req = await db.get(KeyRecoveryRequest, request_id)
    if not req:
        raise ValueError("Recovery request not found")
    if req.status != "pending":
        raise ValueError(f"Request is already {req.status}")

    approvals = json.loads(req.approvals_json)

    # Prevent duplicate approval
    if any(a["user"] == approver for a in approvals):
        raise ValueError("Already approved by this user")

    # Requester cannot approve their own request
    if approver == req.requested_by:
        raise ValueError("Cannot approve your own recovery request")

    approvals.append({"user": approver, "at": datetime.now(timezone.utc).isoformat()})
    req.approvals_json = json.dumps(approvals)

    if len(approvals) >= req.approvals_required:
        req.status = "approved"
        req.download_token = secrets.token_urlsafe(32)
        req.download_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    return req


async def deny_recovery(
    db: AsyncSession,
    request_id: str,
) -> KeyRecoveryRequest:
    """Deny a recovery request."""
    req = await db.get(KeyRecoveryRequest, request_id)
    if not req:
        raise ValueError("Recovery request not found")
    if req.status != "pending":
        raise ValueError(f"Request is already {req.status}")
    req.status = "denied"
    return req


async def download_recovered_key(
    db: AsyncSession,
    request_id: str,
    token: str,
) -> bytes:
    """Download the recovered key if token is valid and not expired."""
    req = await db.get(KeyRecoveryRequest, request_id)
    if not req:
        raise ValueError("Recovery request not found")
    if req.status not in ("approved", "completed"):
        raise ValueError(f"Request is not approved (status: {req.status})")
    if req.download_token != token:
        raise ValueError("Invalid download token")

    now = datetime.now(timezone.utc)
    expires = req.download_expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires and now > expires:
        req.status = "expired"
        raise ValueError("Download link has expired")

    # Get the escrowed key
    escrow = await db.get(KeyEscrow, req.escrow_id)
    if not escrow:
        raise ValueError("Escrow entry not found")

    # Mark as completed
    req.status = "completed"

    return decrypt_from_escrow(escrow.key_blob)


def should_escrow(profile: str, template_escrow_flag: bool | None) -> bool:
    """Determine if a key should be escrowed based on profile and template setting."""
    # Never escrow signing-only keys
    signing_profiles = {"server", "code_sign"}
    if profile in signing_profiles:
        return False
    # Escrow if template says so, or if profile is email/encryption
    if template_escrow_flag:
        return True
    return profile == "email"
