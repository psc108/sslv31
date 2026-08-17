"""Public PKI endpoints — CRL distribution, CA cert download, OCSP responder, PKI info.

These endpoints are PUBLIC (no API key required) as per RFC 5280/6960.
Relying parties must be able to fetch CRLs, CA certs, and OCSP responses without authentication.
"""

import base64
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key
from app.models.ca import CertificateAuthority
from app.models.certificate import Certificate
from app.services.crypto_engine import CryptoEngine
from app.services.ocsp_responder import (
    build_error_response,
    build_successful_response,
    parse_ocsp_request,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pki", tags=["PKI (Public)"])
crypto = CryptoEngine()


@router.get("/crl/{ca_id}")
async def public_crl_download(
    ca_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Public CRL endpoint — no authentication required (RFC 5280 §4.2.1.13)."""
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")
    if not ca.key_blob:
        raise HTTPException(status_code=409, detail="CA key is offline — CRL unavailable")

    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography import x509 as cx509

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Get all revoked certs for this CA
    result = await db.execute(
        select(Certificate).where(
            Certificate.signing_ca_id == ca_id,
            Certificate.status.in_(["revoked", "held"]),
        )
    )
    revoked_certs = result.scalars().all()

    revoked_entries: list[tuple[int, datetime, str | None]] = []
    for cert in revoked_certs:
        serial_int = int(cert.serial, 16)
        revoked_at = cert.revoked_at or cert.held_at or cert.created_at
        revoked_entries.append((serial_int, revoked_at, cert.revocation_reason))

    crl_der = crypto.generate_crl(
        ca_cert=ca_cert,
        ca_key=ca_key,
        revoked_entries=revoked_entries,
        validity_days=settings.CRL_VALIDITY_DAYS,
    )

    return Response(
        content=crl_der,
        media_type="application/pkix-crl",
        headers={
            "Content-Disposition": f'inline; filename="{ca.cn}.crl"',
            "Cache-Control": f"public, max-age={settings.CRL_VALIDITY_DAYS * 86400 // 2}",
        },
    )


@router.get("/ca/{ca_id}/cert")
async def public_ca_cert_download(
    ca_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Public CA certificate endpoint — no authentication required (RFC 5280 AIA)."""
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")

    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import Encoding

    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())
    der_bytes = ca_cert.public_bytes(Encoding.DER)

    return Response(
        content=der_bytes,
        media_type="application/x-x509-ca-cert",
        headers={
            "Content-Disposition": f'inline; filename="{ca.cn}.cer"',
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get("/info")
async def pki_info() -> dict:
    """Public PKI information — base URL, OCSP endpoint, CRL pattern."""
    base = settings.PKI_BASE_URL
    if not base:
        return {"enabled": False, "message": "PKI_BASE_URL not configured. Set it in .env to enable CDP/AIA/OCSP."}

    return {
        "enabled": True,
        "base_url": base,
        "crl_pattern": f"{base}/api/v1/pki/crl/{{ca_id}}",
        "ca_cert_pattern": f"{base}/api/v1/pki/ca/{{ca_id}}/cert",
        "ocsp_endpoint": f"{base}/api/v1/pki/ocsp",
    }


@router.post("/ca/{ca_id}/ocsp-cert")
async def generate_ocsp_cert(
    ca_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Manually generate/renew the OCSP signing certificate for a CA (admin only)."""
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")
    if not ca.key_blob:
        raise HTTPException(status_code=409, detail="CA key is offline — cannot generate OCSP cert")

    from app.services.ocsp_delegation import ensure_ocsp_cert, generate_ocsp_signing_cert
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography import x509 as cx509

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    ocsp_cert, ocsp_key_pem, ocsp_cert_pem = generate_ocsp_signing_cert(ca_cert, ca_key)
    ocsp_key_blob = crypto.encrypt_key_blob(ocsp_key_pem, settings.CERT_MASTER_KEY)

    ca.ocsp_cert_pem = ocsp_cert_pem.decode()
    ca.ocsp_key_blob = ocsp_key_blob
    ca.ocsp_cert_expires = ocsp_cert.not_valid_after_utc

    await db.commit()

    return {
        "status": "generated",
        "ca_id": ca_id,
        "ocsp_cert_subject": ocsp_cert.subject.rfc4514_string(),
        "expires": ca.ocsp_cert_expires.isoformat(),
        "validity_days": 30,
    }


# --- OCSP Responder (RFC 6960) ---

async def _handle_ocsp_request(
    der_data: bytes,
    db: AsyncSession,
) -> Response:
    """Core OCSP logic shared by POST and GET handlers."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography import x509 as cx509
    from cryptography.x509 import ocsp as cocsp

    try:
        ocsp_req = parse_ocsp_request(der_data)
    except Exception:
        error_der = build_error_response(cocsp.OCSPResponseStatus.MALFORMED_REQUEST)
        return Response(content=error_der, media_type="application/ocsp-response")

    # Extract serial from request
    serial_int = ocsp_req.serial_number
    serial_hex = format(serial_int, "x")

    # Find the certificate in our database
    result = await db.execute(
        select(Certificate).where(Certificate.serial == serial_hex)
    )
    cert_record = result.scalar_one_or_none()

    if not cert_record or not cert_record.signing_ca_id:
        # Unknown certificate — we didn't issue it
        error_der = build_error_response(cocsp.OCSPResponseStatus.UNAUTHORIZED)
        return Response(content=error_der, media_type="application/ocsp-response")

    # Load the signing CA
    ca = await db.get(CertificateAuthority, cert_record.signing_ca_id)
    if not ca:
        error_der = build_error_response(cocsp.OCSPResponseStatus.INTERNAL_ERROR)
        return Response(content=error_der, media_type="application/ocsp-response")

    if not ca.key_blob:
        # Offline CA with no stored key — cannot sign OCSP responses
        error_der = build_error_response(cocsp.OCSPResponseStatus.UNAUTHORIZED)
        return Response(content=error_der, media_type="application/ocsp-response")

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Determine status
    is_revoked = cert_record.status in ("revoked", "held")
    rev_time = cert_record.revoked_at or cert_record.held_at if is_revoked else None
    rev_reason = cert_record.revocation_reason if is_revoked else None

    # Try delegated OCSP signing
    from app.services.ocsp_delegation import get_ocsp_signing_materials, ensure_ocsp_cert
    await ensure_ocsp_cert(ca, db)
    ocsp_materials = get_ocsp_signing_materials(ca)
    responder_cert = ocsp_materials[0] if ocsp_materials else None
    responder_key = ocsp_materials[1] if ocsp_materials else None

    try:
        response_der = build_successful_response(
            serial_number=serial_int,
            ca_cert=ca_cert,
            ca_key=ca_key,
            is_revoked=is_revoked,
            revocation_time=rev_time,
            revocation_reason=rev_reason,
            next_update_seconds=settings.CRL_VALIDITY_DAYS * 86400,
            responder_cert=responder_cert,
            responder_key=responder_key,
        )
    except Exception as e:
        logger.error(f"OCSP response build failed: {e}")
        error_der = build_error_response(cocsp.OCSPResponseStatus.INTERNAL_ERROR)
        return Response(content=error_der, media_type="application/ocsp-response")

    return Response(
        content=response_der,
        media_type="application/ocsp-response",
        headers={
            "Cache-Control": f"public, max-age={min(settings.CRL_VALIDITY_DAYS * 86400, 86400)}",
        },
    )


@router.post("/ocsp")
async def ocsp_post(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """OCSP responder — POST method (RFC 6960 §A.1). No authentication required."""
    body = await request.body()
    if not body:
        from cryptography.x509 import ocsp as cocsp
        error_der = build_error_response(cocsp.OCSPResponseStatus.MALFORMED_REQUEST)
        return Response(content=error_der, media_type="application/ocsp-response")
    return await _handle_ocsp_request(body, db)


@router.get("/ocsp/status/{serial}")
async def ocsp_status(
    serial: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Readable OCSP status for a certificate serial (public, for UI use)."""
    result = await db.execute(
        select(Certificate).where(Certificate.serial == serial)
    )
    cert_record = result.scalar_one_or_none()
    if not cert_record:
        return {"serial": serial, "status": "unknown", "message": "Certificate not found in this CA"}

    return {
        "serial": serial,
        "status": cert_record.status,
        "revoked_at": cert_record.revoked_at.isoformat() if cert_record.revoked_at else None,
        "revocation_reason": cert_record.revocation_reason,
        "expires_at": cert_record.expires_at.isoformat(),
        "signing_ca_id": cert_record.signing_ca_id,
    }


@router.get("/ocsp/staple/{serial}")
async def ocsp_staple(
    serial: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> Response:
    """Generate a pre-signed OCSP response for stapling (Nginx ssl_stapling_file).

    This endpoint requires authentication — it's for server operators, not relying parties.
    """
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography import x509 as cx509
    from cryptography.x509 import ocsp as cocsp

    result = await db.execute(
        select(Certificate).where(Certificate.serial == serial)
    )
    cert_record = result.scalar_one_or_none()
    if not cert_record:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if not cert_record.signing_ca_id:
        raise HTTPException(status_code=422, detail="Certificate has no signing CA")

    ca = await db.get(CertificateAuthority, cert_record.signing_ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="Signing CA not found")
    if not ca.key_blob:
        raise HTTPException(status_code=409, detail="CA key is offline — OCSP staple unavailable")

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    serial_int = int(serial, 16)
    is_revoked = cert_record.status in ("revoked", "held")
    rev_time = cert_record.revoked_at or cert_record.held_at if is_revoked else None
    rev_reason = cert_record.revocation_reason if is_revoked else None

    # Use delegated OCSP signing if available
    from app.services.ocsp_delegation import get_ocsp_signing_materials, ensure_ocsp_cert
    await ensure_ocsp_cert(ca, db)
    ocsp_materials = get_ocsp_signing_materials(ca)
    responder_cert = ocsp_materials[0] if ocsp_materials else None
    responder_key = ocsp_materials[1] if ocsp_materials else None

    response_der = build_successful_response(
        serial_number=serial_int,
        ca_cert=ca_cert,
        ca_key=ca_key,
        is_revoked=is_revoked,
        revocation_time=rev_time,
        revocation_reason=rev_reason,
        next_update_seconds=settings.CRL_VALIDITY_DAYS * 86400,
        responder_cert=responder_cert,
        responder_key=responder_key,
    )

    return Response(
        content=response_der,
        media_type="application/ocsp-response",
        headers={
            "Content-Disposition": f'attachment; filename="{serial}.ocsp"',
        },
    )


@router.get("/ocsp/{encoded_request}")
async def ocsp_get(
    encoded_request: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """OCSP responder — GET method (RFC 6960 §A.1). Base64-encoded DER in URL."""
    try:
        der_data = base64.b64decode(encoded_request)
    except Exception:
        from cryptography.x509 import ocsp as cocsp
        error_der = build_error_response(cocsp.OCSPResponseStatus.MALFORMED_REQUEST)
        return Response(content=error_der, media_type="application/ocsp-response")
    return await _handle_ocsp_request(der_data, db)
