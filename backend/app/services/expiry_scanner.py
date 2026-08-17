"""Certificate expiry scanner — background job that flags expiring certificates."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.certificate import Certificate
from app.models.ca import CertificateAuthority
from app.models.audit import AuditEvent
from app.core.config import settings
from app.services.chain_builder import build_chain, assemble_chain_pem

logger = logging.getLogger(__name__)


async def scan_expiring_certificates(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Scan all valid certificates and flag those approaching expiry. Auto-renew if enabled."""
    thresholds = [int(d) for d in settings.EXPIRY_WARN_DAYS.split(",")]
    thresholds.sort(reverse=True)  # e.g. [60, 30, 7]
    now = datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)  # SQLite stores naive datetimes

    async with session_factory() as db:
        # Get all valid certificates
        result = await db.execute(
            select(Certificate).where(Certificate.status.in_(["valid", "held"]))
        )
        certs = result.scalars().all()

        scanned = 0
        expiring_count = 0
        newly_expired = 0
        auto_renewed = 0

        for cert in certs:
            scanned += 1
            days_remaining = (cert.expires_at - now_naive).days

            # Expired
            if days_remaining <= 0:
                if cert.status != "expired":
                    cert.status = "expired"
                    cert.expiry_warning = True
                    newly_expired += 1
                    db.add(AuditEvent(
                        timestamp=now,
                        event_type="CERT_EXPIRED",
                        severity="WARNING",
                        subject_type="cert",
                        subject_id=cert.serial,
                        description=f"Certificate expired: {cert.serial}",
                    ))
                    # Notify
                    cn = _get_cn(cert)
                    await _notify_expiry(db, cert, cn, 0)
                continue

            # Auto-renew check (30 days before expiry)
            if cert.auto_renew and days_remaining <= 30 and not cert.renewed_to and cert.signing_ca_id and cert.key_blob:
                try:
                    await _auto_renew_cert(db, cert, now)
                    auto_renewed += 1
                except Exception as e:
                    logger.error(f"Auto-renewal failed for {cert.serial}: {e}")
                continue

            # Check thresholds
            for threshold in thresholds:
                if days_remaining <= threshold:
                    if not cert.expiry_warning:
                        cert.expiry_warning = True
                        expiring_count += 1
                        severity = "WARNING" if threshold <= 30 else "INFO"
                        db.add(AuditEvent(
                            timestamp=now,
                            event_type="CERT_EXPIRY_WARNING",
                            severity=severity,
                            subject_type="cert",
                            subject_id=cert.serial,
                            description=f"Certificate expiring in {days_remaining} days: {cert.serial}",
                            detail_json=f'{{"days_remaining": {days_remaining}, "threshold": {threshold}}}',
                        ))
                        # Notify
                        cn = _get_cn(cert)
                        await _notify_expiry(db, cert, cn, days_remaining)
                    break

        await db.commit()
        logger.info(
            f"Expiry scan complete: {scanned} scanned, {expiring_count} newly flagged, "
            f"{newly_expired} expired, {auto_renewed} auto-renewed"
        )


async def _auto_renew_cert(db: AsyncSession, cert: Certificate, now: datetime) -> None:
    """Auto-renew a certificate using the same key, subject, SANs, and profile."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography import x509 as cx509
    from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry

    crypto = CryptoEngine()

    ca = await db.get(CertificateAuthority, cert.signing_ca_id)
    if not ca:
        raise ValueError(f"Signing CA {cert.signing_ca_id} not found")

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Reuse existing key
    key_pem = crypto.decrypt_key_blob(cert.key_blob, settings.CERT_MASTER_KEY)
    key = load_pem_private_key(key_pem, password=None)

    subject_data = json.loads(cert.subject_json)
    san_data = json.loads(cert.san_json)
    subject = SubjectInfo(
        cn=subject_data.get("cn", ""), o=subject_data.get("o", ""),
        ou=subject_data.get("ou", ""), c=subject_data.get("c", ""),
        st=subject_data.get("st", ""), l=subject_data.get("l", ""),
    )
    san_list = [SANEntry(type=s["type"], value=s["value"]) for s in san_data]

    # Use same validity as original cert (capped at MAX_CERT_DAYS)
    original_days = (cert.expires_at - cert.created_at).days  # both naive from SQLite
    validity_days = min(original_days, settings.MAX_CERT_DAYS)

    new_cert_obj = crypto.issue_certificate(
        profile=cert.profile, subject=subject, san_list=san_list,
        key=key, signing_ca_key=ca_key, signing_ca_cert=ca_cert,
        validity_days=validity_days, signing_ca_id=cert.signing_ca_id,
        pki_base_url=settings.PKI_BASE_URL,
    )

    cert_pem = crypto.export_cert_pem(new_cert_obj).decode()
    new_serial = format(new_cert_obj.serial_number, "x")
    key_blob = crypto.encrypt_key_blob(key_pem, settings.CERT_MASTER_KEY)

    # Build full chain
    ca_chain = await build_chain(cert.signing_ca_id, db)
    chain_pem = assemble_chain_pem(cert_pem, ca_chain, mode="full")

    new_certificate = Certificate(
        serial=new_serial,
        profile=cert.profile,
        subject_json=cert.subject_json,
        san_json=cert.san_json,
        key_algo=cert.key_algo,
        key_size=cert.key_size,
        cert_pem=cert_pem,
        key_blob=key_blob,
        chain_pem=chain_pem,
        signing_ca_id=cert.signing_ca_id,
        status="valid",
        expires_at=new_cert_obj.not_valid_after_utc,
        tags=cert.tags,
        auto_renew=True,
        renewed_from=cert.serial,
    )
    db.add(new_certificate)
    cert.renewed_to = new_serial

    db.add(AuditEvent(
        timestamp=now,
        event_type="CERT_AUTO_RENEWED",
        severity="INFO",
        subject_type="cert",
        subject_id=new_serial,
        description=f"Certificate auto-renewed: {subject.cn} ({cert.serial} → {new_serial})",
        detail_json=json.dumps({"old_serial": cert.serial, "new_serial": new_serial, "validity_days": validity_days}),
    ))
    logger.info(f"Auto-renewed certificate {cert.serial} → {new_serial}")


async def run_expiry_scanner(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Run the expiry scanner on a recurring interval."""
    interval = settings.EXPIRY_SCAN_INTERVAL_HOURS * 3600
    while True:
        try:
            await scan_expiring_certificates(session_factory)
        except Exception as e:
            logger.error(f"Expiry scanner error: {e}")
        await asyncio.sleep(interval)


async def send_webhook_notification(cert_serial: str, cn: str, days_remaining: int, expires_at: str) -> None:
    """Send webhook notification for certificate expiry (H-03)."""
    if not settings.NOTIFY_WEBHOOK_URL:
        return

    import httpx

    payload = {
        "event": "cert_expiry_warning",
        "severity": "WARNING" if days_remaining <= 30 else "INFO",
        "certificate": {
            "serial": cert_serial,
            "cn": cn,
            "expires_at": expires_at,
            "days_remaining": days_remaining,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(settings.NOTIFY_WEBHOOK_URL, json=payload)
            if response.status_code >= 400:
                logger.warning(f"Webhook notification failed: HTTP {response.status_code}")
    except Exception as e:
        logger.warning(f"Webhook notification failed: {e}")
        # One retry after 30s
        await asyncio.sleep(30)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(settings.NOTIFY_WEBHOOK_URL, json=payload)
        except Exception:
            logger.error(f"Webhook retry failed for cert {cert_serial}")


def _get_cn(cert: Certificate) -> str:
    """Extract CN from certificate subject_json."""
    try:
        data = json.loads(cert.subject_json)
        return data.get("cn", cert.serial)
    except Exception:
        return cert.serial


async def _notify_expiry(db: AsyncSession, cert: Certificate, cn: str, days_remaining: int) -> None:
    """Send email notification for certificate expiry."""
    try:
        from app.services.notification_service import notify_event
        await notify_event(
            db, "expiry_warning",
            tenant_id=cert.tenant_id,
            ca_id=cert.signing_ca_id,
            cn=cn, serial=cert.serial,
            expires_at=str(cert.expires_at),
            days_remaining=days_remaining,
        )
    except Exception as e:
        logger.debug(f"Expiry notification dispatch failed: {e}")

