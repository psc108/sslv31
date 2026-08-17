"""PKI posture dashboard — Enhancement Plan Stage 11, the flagship
differentiator: a single view aggregating cert/CA chain topology, expiry
risk, key strength, auto-renew status, and secret rotation staleness across
every Build Manager environment. Pure aggregation over existing facts
(BMCertBinding, Certificate, CertificateAuthority, BMSecret) — no new data
model, since the underlying facts already exist; this is presentation.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.build_manager import BMCertBinding, BMEnvironment, BMSecret
from app.models.ca import CertificateAuthority
from app.models.certificate import Certificate
from app.services.build_manager.secrets_service import is_rotation_overdue, rotation_due_at

# Same BR minimums compliance_scanner.py already enforces at issuance time —
# reused here for consistency rather than re-deriving a second threshold.
WEAK_RSA_BITS = 2048
WEAK_ECDSA_BITS = 256


def _risk_level(expires_at: datetime | None, now: datetime) -> str:
    """Color-coded risk bucket, reusing the same 7/30-day windows the rest
    of the app's cert-expiry logic (cert_lifecycle.py, notifications) uses."""
    if expires_at is None:
        return "unknown"
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    if expires_at <= now:
        return "expired"
    if expires_at <= now + timedelta(days=7):
        return "critical"
    if expires_at <= now + timedelta(days=30):
        return "warning"
    return "ok"


def _is_weak_key(key_algo: str | None, key_size: int | None) -> bool:
    if not key_algo or not key_size:
        return False
    if key_algo == "RSA":
        return key_size < WEAK_RSA_BITS
    if key_algo == "ECDSA":
        return key_size < WEAK_ECDSA_BITS
    return False


def _ca_chain(ca_id: str | None, cas_by_id: dict[str, CertificateAuthority]) -> list[str]:
    """Walk parent_ca_id up to the root, returning CA names from the
    immediate signer to the root. Guards against a self-referential loop
    (shouldn't exist, but this is display code — never worth an infinite
    loop over a data-integrity bug elsewhere)."""
    chain = []
    seen = set()
    current = ca_id
    while current and current in cas_by_id and current not in seen:
        seen.add(current)
        ca = cas_by_id[current]
        chain.append(ca.cn)
        current = ca.parent_ca_id
    return chain


async def get_pki_posture(db: AsyncSession) -> dict:
    """Aggregate PKI posture across every non-destroyed Build Manager
    environment. Returns per-environment cert rows plus a top-level secrets
    section (BMSecret isn't environment-scoped in this schema) and an
    overall summary for at-a-glance risk counts."""
    now = datetime.now(timezone.utc)

    env_result = await db.execute(
        select(BMEnvironment).where(BMEnvironment.status != "destroyed").order_by(BMEnvironment.name)
    )
    environments = env_result.scalars().all()
    env_by_id = {e.id: e for e in environments}

    bindings: list[BMCertBinding] = []
    if env_by_id:
        binding_result = await db.execute(
            select(BMCertBinding).where(BMCertBinding.environment_id.in_(env_by_id.keys()))
        )
        bindings = binding_result.scalars().all()

    serials = {b.cert_serial for b in bindings if b.cert_serial}
    certs_by_serial: dict[str, Certificate] = {}
    if serials:
        cert_result = await db.execute(select(Certificate).where(Certificate.serial.in_(serials)))
        certs_by_serial = {c.serial: c for c in cert_result.scalars().all()}

    # Pull every CA up front (typically a small table) so chain-walking is
    # in-memory rather than N+1 queries per cert.
    ca_result = await db.execute(select(CertificateAuthority))
    cas_by_id = {c.id: c for c in ca_result.scalars().all()}

    envs_out = []
    total_certs = expired_count = critical_count = warning_count = weak_key_count = 0

    for env in environments:
        env_bindings = [b for b in bindings if b.environment_id == env.id]
        cert_rows = []
        for b in env_bindings:
            cert = certs_by_serial.get(b.cert_serial)
            risk = _risk_level(b.expires_at, now)
            weak = _is_weak_key(cert.key_algo if cert else None, cert.key_size if cert else None)

            total_certs += 1
            if risk == "expired":
                expired_count += 1
            elif risk == "critical":
                critical_count += 1
            elif risk == "warning":
                warning_count += 1
            if weak:
                weak_key_count += 1

            cert_rows.append({
                "binding_id": b.id,
                "role": b.role,
                "cert_type": b.cert_type,
                "cert_serial": b.cert_serial,
                "cert_status": cert.status if cert else None,
                "key_algo": cert.key_algo if cert else None,
                "key_size": cert.key_size if cert else None,
                "weak_key": weak,
                "signing_ca_chain": _ca_chain(cert.signing_ca_id if cert else None, cas_by_id),
                "expires_at": b.expires_at.isoformat() if b.expires_at else None,
                "risk": risk,
                "auto_renew": b.auto_renew,
                "renewal_count": b.renewal_count,
            })

        envs_out.append({
            "environment_id": env.id,
            "environment_name": env.name,
            "environment_status": env.status,
            "certs": cert_rows,
        })

    secret_result = await db.execute(select(BMSecret).order_by(BMSecret.name))
    secrets_out = []
    secrets_overdue_count = 0
    for s in secret_result.scalars().all():
        overdue = is_rotation_overdue(s, now)
        if overdue:
            secrets_overdue_count += 1
        secrets_out.append({
            "id": s.id,
            "name": s.name,
            "category": s.category,
            "linked_service": s.linked_service,
            "rotate_every_days": s.rotate_every_days,
            "rotation_due_at": (rotation_due_at(s).isoformat() if rotation_due_at(s) else None),
            "rotation_overdue": overdue,
        })

    return {
        "environments": envs_out,
        "secrets": secrets_out,
        "summary": {
            "total_certs": total_certs,
            "expired_count": expired_count,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "weak_key_count": weak_key_count,
            "secrets_overdue_count": secrets_overdue_count,
        },
    }
