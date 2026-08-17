"""Certificate lifecycle endpoints — hold, unhold, renew, auto-renew."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_permission, AuthContext
from app.models.certificate import Certificate
from app.models.ca import CertificateAuthority
from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry
from app.services.chain_builder import build_chain, assemble_chain_pem
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/cert", tags=["Certificate Lifecycle"])
crypto = CryptoEngine()


class RenewRequest(BaseModel):
    validity_days: int = Field(365, gt=0)
    new_key: bool = False  # True = generate fresh key; False = reuse existing key


class AutoRenewUpdate(BaseModel):
    auto_renew: bool


# --- Hold (temporary revocation) ---

@router.post("/{serial}/hold", status_code=200)
async def hold_certificate(
    serial: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:revoke")),
) -> dict:
    """Place a certificate on hold (temporary revocation). Can be reversed with unhold."""
    result = await db.execute(select(Certificate).where(Certificate.serial == serial))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if cert.status == "revoked":
        raise HTTPException(status_code=409, detail="Certificate is permanently revoked — cannot hold")
    if cert.status == "held":
        raise HTTPException(status_code=409, detail="Certificate is already on hold")
    if cert.status == "expired":
        raise HTTPException(status_code=409, detail="Certificate is expired — cannot hold")

    cert.status = "held"
    cert.held_at = datetime.now(timezone.utc)
    cert.revocation_reason = "certificate_hold"

    await audit_event(
        db=db,
        event_type="CERT_HELD",
        severity="WARNING",
        request=request,
        subject_type="cert",
        subject_id=serial,
        description=f"Certificate placed on hold: {serial}",
    )
    await db.commit()

    return {"status": "held", "serial": serial, "held_at": cert.held_at.isoformat()}


@router.post("/{serial}/unhold", status_code=200)
async def unhold_certificate(
    serial: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:revoke")),
) -> dict:
    """Remove a certificate from hold, restoring it to valid status."""
    result = await db.execute(select(Certificate).where(Certificate.serial == serial))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if cert.status != "held":
        raise HTTPException(status_code=409, detail=f"Certificate is not on hold (status: {cert.status})")

    cert.status = "valid"
    cert.held_at = None
    cert.revocation_reason = None

    await audit_event(
        db=db,
        event_type="CERT_UNHELD",
        severity="INFO",
        request=request,
        subject_type="cert",
        subject_id=serial,
        description=f"Certificate removed from hold: {serial}",
    )
    await db.commit()

    return {"status": "valid", "serial": serial}


# --- Renew ---

@router.post("/{serial}/renew", status_code=201)
async def renew_certificate(
    serial: str,
    body: RenewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:issue")),
) -> dict:
    """Renew a certificate — preserves subject, SANs, and profile. Optionally generates a new key."""
    result = await db.execute(select(Certificate).where(Certificate.serial == serial))
    old_cert = result.scalar_one_or_none()
    if not old_cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if not old_cert.signing_ca_id:
        raise HTTPException(status_code=422, detail="Cannot renew externally-signed certificates")
    if not old_cert.key_blob:
        raise HTTPException(status_code=422, detail="No stored key — cannot renew")

    # Validate against MAX_CERT_DAYS
    if body.validity_days > settings.MAX_CERT_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Validity cannot exceed {settings.MAX_CERT_DAYS} days",
        )

    # Load signing CA
    ca = await db.get(CertificateAuthority, old_cert.signing_ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="Signing CA no longer exists")

    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography import x509 as cx509

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Key: reuse or generate new
    if body.new_key:
        key = crypto.generate_keypair(old_cert.key_algo, old_cert.key_size)
    else:
        old_key_pem = crypto.decrypt_key_blob(old_cert.key_blob, settings.CERT_MASTER_KEY)
        key = load_pem_private_key(old_key_pem, password=None)

    # Rebuild subject and SAN from old cert
    subject_data = json.loads(old_cert.subject_json)
    san_data = json.loads(old_cert.san_json)

    subject = SubjectInfo(
        cn=subject_data.get("cn", ""),
        o=subject_data.get("o", ""),
        ou=subject_data.get("ou", ""),
        c=subject_data.get("c", ""),
        st=subject_data.get("st", ""),
        l=subject_data.get("l", ""),
    )
    san_list = [SANEntry(type=s["type"], value=s["value"]) for s in san_data]

    # Issue new certificate
    new_cert_obj = crypto.issue_certificate(
        profile=old_cert.profile,
        subject=subject,
        san_list=san_list,
        key=key,
        signing_ca_key=ca_key,
        signing_ca_cert=ca_cert,
        validity_days=body.validity_days,
        signing_ca_id=old_cert.signing_ca_id,
        pki_base_url=settings.PKI_BASE_URL,
    )

    # Store new certificate
    cert_pem = crypto.export_cert_pem(new_cert_obj).decode()
    ca_chain = await build_chain(old_cert.signing_ca_id, db)
    chain_pem = assemble_chain_pem(cert_pem, ca_chain, mode="full")
    new_serial = format(new_cert_obj.serial_number, "x")
    key_pem = crypto.export_key_pem(key)
    key_blob = crypto.encrypt_key_blob(key_pem, settings.CERT_MASTER_KEY)

    new_certificate = Certificate(
        serial=new_serial,
        profile=old_cert.profile,
        subject_json=old_cert.subject_json,
        san_json=old_cert.san_json,
        key_algo=old_cert.key_algo,
        key_size=old_cert.key_size,
        cert_pem=cert_pem,
        key_blob=key_blob,
        chain_pem=chain_pem,
        signing_ca_id=old_cert.signing_ca_id,
        status="valid",
        expires_at=new_cert_obj.not_valid_after_utc,
        tags=old_cert.tags,
        auto_renew=old_cert.auto_renew,
        renewed_from=serial,
    )
    db.add(new_certificate)

    # Link old → new
    old_cert.renewed_to = new_serial

    await audit_event(
        db=db,
        event_type="CERT_RENEWED",
        severity="INFO",
        request=request,
        subject_type="cert",
        subject_id=new_serial,
        detail={
            "old_serial": serial,
            "new_serial": new_serial,
            "new_key": body.new_key,
            "validity_days": body.validity_days,
        },
        description=f"Certificate renewed: {subject.cn} ({serial} → {new_serial})",
    )
    await db.commit()

    return {
        "status": "renewed",
        "old_serial": serial,
        "new_serial": new_serial,
        "new_key": body.new_key,
        "expires_at": new_cert_obj.not_valid_after_utc.isoformat(),
    }


# --- Auto-renew toggle ---

@router.patch("/{serial}/auto-renew", status_code=200)
async def set_auto_renew(
    serial: str,
    body: AutoRenewUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:issue")),
) -> dict:
    """Enable or disable auto-renewal for a certificate."""
    result = await db.execute(select(Certificate).where(Certificate.serial == serial))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if not cert.signing_ca_id:
        raise HTTPException(status_code=422, detail="Cannot auto-renew externally-signed certificates")

    cert.auto_renew = body.auto_renew

    await db.commit()
    return {"serial": serial, "auto_renew": cert.auto_renew}
