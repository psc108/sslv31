"""Certificate lifecycle service — expiry monitoring, renewal, rotation, revocation."""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.build_manager import BMCertBinding, BMEnvironment, BMEnvironmentCert
from app.models.certificate import Certificate

logger = logging.getLogger(__name__)


async def list_all_bindings(db: AsyncSession) -> list[dict]:
    """List all cert bindings across all active environments."""
    result = await db.execute(
        select(BMCertBinding)
        .options(selectinload(BMCertBinding.environment))
        .order_by(BMCertBinding.expires_at.asc())
    )
    bindings = result.scalars().all()
    return [_binding_to_dict(b) for b in bindings]


async def list_environment_bindings(db: AsyncSession, environment_id: str) -> list[dict]:
    """List cert bindings for a specific environment."""
    result = await db.execute(
        select(BMCertBinding)
        .where(BMCertBinding.environment_id == environment_id)
        .order_by(BMCertBinding.role, BMCertBinding.cert_type)
    )
    return [_binding_to_dict(b) for b in result.scalars().all()]


async def get_expiring_bindings(db: AsyncSession, days: int = 30) -> list[dict]:
    """Get bindings expiring within the given threshold (only active environments)."""
    threshold = datetime.now(timezone.utc) + timedelta(days=days)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(BMCertBinding)
        .join(BMEnvironment, BMCertBinding.environment_id == BMEnvironment.id)
        .where(
            BMEnvironment.status.in_(["active", "degraded"]),
            BMCertBinding.expires_at.isnot(None),
            BMCertBinding.expires_at <= threshold,
            BMCertBinding.expires_at > now,
        )
        .options(selectinload(BMCertBinding.environment))
        .order_by(BMCertBinding.expires_at.asc())
    )
    return [_binding_to_dict(b) for b in result.scalars().all()]


async def renew_binding(db: AsyncSession, binding_id: str) -> dict:
    """Renew a single cert binding — re-issue cert with same CN/SANs, update binding."""
    result = await db.execute(
        select(BMCertBinding).where(BMCertBinding.id == binding_id)
    )
    binding = result.scalar_one_or_none()
    if not binding:
        raise ValueError("Cert binding not found")

    # Get the current certificate to extract CN/SANs
    cert_result = await db.execute(
        select(Certificate).where(Certificate.serial == binding.cert_serial)
    )
    old_cert = cert_result.scalar_one_or_none()
    if not old_cert:
        raise ValueError(f"Certificate {binding.cert_serial} not found in cert store")

    subject = json.loads(old_cert.subject_json)
    sans = json.loads(old_cert.san_json)
    cn = subject.get("cn", f"{binding.role}.internal")

    # Get signing CA from environment variables
    env_result = await db.execute(
        select(BMEnvironment).where(BMEnvironment.id == binding.environment_id)
    )
    env = env_result.scalar_one_or_none()
    variables = json.loads(env.variables) if env and env.variables else {}
    signing_ca_id = variables.get("signing_ca_id")

    # Re-issue via base_provisioner's _issue_cert
    from app.services.build_manager.base_provisioner import _issue_cert
    profile = "client" if binding.cert_type == "client" else "server"
    new_cert_pem, new_key_pem, new_serial = await _issue_cert(
        db=db, cn=cn, sans=sans, profile=profile,
        validity_days=365, preferred_ca_id=signing_ca_id,
    )

    # Mark old cert as renewed
    if old_cert:
        old_cert.renewed_to = new_serial

    # Get new cert expiry
    new_cert_result = await db.execute(
        select(Certificate).where(Certificate.serial == new_serial)
    )
    new_cert_obj = new_cert_result.scalar_one_or_none()

    # Update binding
    now = datetime.now(timezone.utc)
    binding.cert_serial = new_serial
    binding.expires_at = new_cert_obj.expires_at if new_cert_obj else now + timedelta(days=365)
    binding.last_renewed_at = now
    binding.renewal_count += 1

    # Also update the BMEnvironmentCert record
    env_cert = BMEnvironmentCert(
        id=str(uuid.uuid4()),
        environment_id=binding.environment_id,
        cert_serial=new_serial,
        role=binding.role,
        cert_type=binding.cert_type,
        issued_at=now,
    )
    db.add(env_cert)

    await db.commit()
    return {
        "binding_id": binding.id,
        "old_serial": old_cert.serial,
        "new_serial": new_serial,
        "expires_at": binding.expires_at.isoformat() if binding.expires_at else None,
        "cert_pem": new_cert_pem,
        "key_pem": new_key_pem,
    }


async def rotate_binding(db: AsyncSession, binding_id: str) -> dict:
    """Rotate a binding — new key pair + new cert. Same as renew but explicitly generates fresh keys."""
    # Rotation is functionally identical to renewal (base_provisioner always generates new keys)
    return await renew_binding(db, binding_id)


async def revoke_environment_bindings(db: AsyncSession, environment_id: str) -> int:
    """Revoke all cert bindings for an environment. Returns count revoked."""
    result = await db.execute(
        select(BMCertBinding).where(BMCertBinding.environment_id == environment_id)
    )
    bindings = result.scalars().all()
    now = datetime.now(timezone.utc)
    count = 0

    for binding in bindings:
        # Mark the actual certificate as revoked
        cert_result = await db.execute(
            select(Certificate).where(Certificate.serial == binding.cert_serial, Certificate.status == "valid")
        )
        cert = cert_result.scalar_one_or_none()
        if cert:
            cert.status = "revoked"
            cert.revoked_at = now
            cert.revocation_reason = "environment_destroyed"
            count += 1

    # Delete bindings (environment cascade will handle this too)
    for binding in bindings:
        await db.delete(binding)

    await db.commit()
    return count


async def create_binding_from_cert(
    db: AsyncSession, environment_id: str, cert_serial: str,
    role: str, cert_type: str = "server", host_id: str | None = None,
) -> BMCertBinding:
    """Create a cert binding record when a cert is issued during provisioning."""
    # Look up cert expiry
    cert_result = await db.execute(
        select(Certificate).where(Certificate.serial == cert_serial)
    )
    cert = cert_result.scalar_one_or_none()

    cert_path = "/etc/ssl/certs/server.pem" if cert_type == "server" else "/etc/ssl/certs/client.pem"
    key_path = "/etc/ssl/private/server-key.pem" if cert_type == "server" else "/etc/ssl/private/client-key.pem"

    binding = BMCertBinding(
        id=str(uuid.uuid4()),
        environment_id=environment_id,
        cert_serial=cert_serial,
        role=role,
        cert_type=cert_type,
        host_id=host_id,
        cert_path=cert_path,
        key_path=key_path,
        expires_at=cert.expires_at if cert else None,
        auto_renew=True,
    )
    db.add(binding)
    return binding


async def toggle_auto_renew(db: AsyncSession, binding_id: str, enabled: bool) -> dict:
    """Toggle auto-renew for a binding."""
    result = await db.execute(
        select(BMCertBinding).where(BMCertBinding.id == binding_id)
    )
    binding = result.scalar_one_or_none()
    if not binding:
        raise ValueError("Cert binding not found")
    binding.auto_renew = enabled
    await db.commit()
    return {"id": binding.id, "auto_renew": binding.auto_renew}


async def check_and_auto_renew(db: AsyncSession, threshold_days: int = 30) -> list[dict]:
    """Background task: find bindings approaching expiry with auto_renew=True and renew them.

    Bindings with auto_renew=False in the same window are deliberately left
    alone (an operator explicitly opted out of automatic renewal for that
    binding) but get a notification instead, since no one is otherwise
    watching for them."""
    threshold = datetime.now(timezone.utc) + timedelta(days=threshold_days)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(BMCertBinding)
        .join(BMEnvironment, BMCertBinding.environment_id == BMEnvironment.id)
        .where(
            BMEnvironment.status.in_(["active", "degraded"]),
            BMCertBinding.auto_renew == True,
            BMCertBinding.expires_at.isnot(None),
            BMCertBinding.expires_at <= threshold,
            BMCertBinding.expires_at > now,
        )
    )
    bindings = result.scalars().all()
    renewed = []

    for binding in bindings:
        try:
            info = await renew_binding(db, binding.id)
            renewed.append(info)
            logger.info(f"Auto-renewed cert binding {binding.id} (role={binding.role})")
        except Exception as e:
            logger.error(f"Failed to auto-renew binding {binding.id}: {e}")

    manual_result = await db.execute(
        select(BMCertBinding)
        .options(selectinload(BMCertBinding.environment))
        .join(BMEnvironment, BMCertBinding.environment_id == BMEnvironment.id)
        .where(
            BMEnvironment.status.in_(["active", "degraded"]),
            BMCertBinding.auto_renew == False,
            BMCertBinding.expires_at.isnot(None),
            BMCertBinding.expires_at <= threshold,
            BMCertBinding.expires_at > now,
        )
    )
    manual_bindings = manual_result.scalars().all()
    if manual_bindings:
        from app.services.notification_service import notify_event
        for binding in manual_bindings:
            env = binding.environment
            # BMCertBinding.expires_at is a plain DateTime column — SQLite
            # round-trips it as timezone-naive regardless of what was written,
            # so comparing directly against an aware `now` can raise.
            now_for_diff = now.replace(tzinfo=None) if binding.expires_at.tzinfo is None else now
            await notify_event(
                db, "bm_cert_binding_expiring",
                tenant_id=env.tenant_id if env else "00000000-0000-0000-0000-000000000001",
                environment_name=env.name if env else "unknown",
                role=binding.role,
                expires_at=binding.expires_at.isoformat(),
                days_remaining=(binding.expires_at - now_for_diff).days,
            )

    return renewed


def _binding_to_dict(b: BMCertBinding) -> dict:
    return {
        "id": b.id,
        "environment_id": b.environment_id,
        "environment_name": b.environment.name if b.environment else None,
        "cert_serial": b.cert_serial,
        "role": b.role,
        "cert_type": b.cert_type,
        "host_id": b.host_id,
        "cert_path": b.cert_path,
        "key_path": b.key_path,
        "ca_path": b.ca_path,
        "expires_at": b.expires_at.isoformat() if b.expires_at else None,
        "auto_renew": b.auto_renew,
        "last_renewed_at": b.last_renewed_at.isoformat() if b.last_renewed_at else None,
        "renewal_count": b.renewal_count,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }
