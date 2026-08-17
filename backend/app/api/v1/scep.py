"""SCEP Protocol endpoints — Simple Certificate Enrollment Protocol.

Provides certificate enrollment for legacy network devices (Cisco IOS,
VPN concentrators, embedded systems) that only support SCEP.

Endpoints:
  GET  /scep?operation=GetCACaps
  GET  /scep?operation=GetCACert
  GET  /scep?operation=PKIOperation&message=<base64>
  POST /scep  (PKIOperation via POST body)

Also available at /cgi-bin/pkiclient.exe for maximum device compatibility.
"""

import base64
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key
from app.models.ca import CertificateAuthority
from app.models.certificate import Certificate
from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry
from cryptography.hazmat.primitives import serialization
from app.services.chain_builder import build_chain, assemble_chain_pem
from app.services.serial_allocator import allocate_serial_safe
from app.services.audit import audit_event
from app.services.scep_service import (
    get_capabilities,
    parse_scep_request,
    extract_challenge_password,
    generate_transaction_id,
    build_cert_rep_success,
    build_cert_rep_failure,
    SCEPFailInfo,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["SCEP"])
crypto = CryptoEngine()


async def _resolve_scep_ca(db: AsyncSession) -> CertificateAuthority:
    """Find the CA configured for SCEP enrollment."""
    ca_id = settings.SCEP_CA_ID
    if ca_id:
        ca = await db.get(CertificateAuthority, ca_id)
        if ca and ca.key_blob:
            return ca

    # Fallback: first CA with a key
    result = await db.execute(
        select(CertificateAuthority)
        .where(CertificateAuthority.key_blob.isnot(None))
        .order_by(CertificateAuthority.is_root.asc())
        .limit(1)
    )
    ca = result.scalar_one_or_none()
    if not ca:
        raise HTTPException(status_code=503, detail="No CA available for SCEP")
    return ca


def _validate_challenge(password: str | None) -> bool:
    """Validate the SCEP challenge password."""
    if not settings.SCEP_CHALLENGE_PASSWORD:
        return True  # No challenge configured = open enrollment
    if not password:
        return False
    return password == settings.SCEP_CHALLENGE_PASSWORD


async def _enroll_from_csr(
    csr, ca: CertificateAuthority, request: Request, db: AsyncSession, transaction_id: str,
) -> tuple[str, str]:
    """Sign a CSR via SCEP and return (cert_pem, chain_pem)."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.x509.oid import NameOID
    from cryptography.x509 import (
        CertificateBuilder, BasicConstraints, KeyUsage,
        SubjectKeyIdentifier, AuthorityKeyIdentifier,
        ExtendedKeyUsage, SubjectAlternativeName,
    )
    from cryptography.x509.oid import ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes
    from datetime import timedelta

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Extract subject
    cn_attrs = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    cn = cn_attrs[0].value if cn_attrs else "SCEP-enrolled"

    # Extract SANs
    san_list: list[SANEntry] = []
    try:
        san_ext = csr.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(cx509.DNSName):
            san_list.append(SANEntry(type="dns", value=dns))
        for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
            san_list.append(SANEntry(type="ip", value=str(ip)))
    except cx509.ExtensionNotFound:
        pass

    # Build certificate
    validity_days = min(settings.MAX_CERT_DAYS, settings.SCEP_MAX_VALIDITY_DAYS)
    serial_int = await allocate_serial_safe(ca.id, db)
    now = datetime.now(timezone.utc)

    subject = SubjectInfo(cn=cn)
    name = crypto._build_name(subject)

    builder = (
        CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(serial_int)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
        .add_extension(BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            KeyUsage(
                key_cert_sign=False, crl_sign=False,
                digital_signature=True, key_encipherment=True,
                content_commitment=False, data_encipherment=False,
                key_agreement=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(SubjectKeyIdentifier.from_public_key(csr.public_key()), critical=False)
        .add_extension(AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False)
        .add_extension(
            ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
    )

    if san_list:
        san_names = crypto._build_san_extension(san_list)
        builder = builder.add_extension(SubjectAlternativeName(san_names), critical=False)

    # CDP/AIA
    if settings.PKI_BASE_URL:
        from cryptography.x509 import CRLDistributionPoints, DistributionPoint
        from cryptography.x509 import AuthorityInformationAccess, AccessDescription, AuthorityInformationAccessOID
        cdp_url = f"{settings.PKI_BASE_URL}/api/v1/pki/crl/{ca.id}"
        dp = DistributionPoint(
            full_name=[cx509.UniformResourceIdentifier(cdp_url)],
            relative_name=None, crl_issuer=None, reasons=None,
        )
        builder = builder.add_extension(CRLDistributionPoints([dp]), critical=False)

        aia = AuthorityInformationAccess([
            AccessDescription(
                AuthorityInformationAccessOID.OCSP,
                cx509.UniformResourceIdentifier(f"{settings.PKI_BASE_URL}/api/v1/pki/ocsp"),
            ),
            AccessDescription(
                AuthorityInformationAccessOID.CA_ISSUERS,
                cx509.UniformResourceIdentifier(f"{settings.PKI_BASE_URL}/api/v1/pki/ca/{ca.id}/cert"),
            ),
        ])
        builder = builder.add_extension(aia, critical=False)

    # Sign
    digest = crypto._get_digest("sha256", ca_key)
    cert_obj = builder.sign(ca_key, digest)

    cert_pem_bytes = crypto.export_cert_pem(cert_obj)
    serial_hex = format(cert_obj.serial_number, "x")

    # Build chain
    ca_chain = await build_chain(ca.id, db)
    chain_pem = assemble_chain_pem(cert_pem_bytes.decode(), ca_chain, mode="full")

    # Store certificate (no private key — client has it)
    placeholder_key = crypto.encrypt_key_blob(b"SCEP_ENROLLED_NO_KEY", settings.CERT_MASTER_KEY)

    certificate = Certificate(
        serial=serial_hex,
        profile=settings.SCEP_PROFILE,
        subject_json=json.dumps({"cn": cn}),
        san_json=json.dumps([{"type": s.type, "value": s.value} for s in san_list]),
        key_algo=_detect_key_algo(csr.public_key()),
        key_size=_detect_key_size(csr.public_key()),
        cert_pem=cert_pem_bytes.decode(),
        key_blob=placeholder_key,
        chain_pem=chain_pem,
        signing_ca_id=ca.id,
        status="valid",
        expires_at=cert_obj.not_valid_after_utc,
        tags=json.dumps(["scep-enrolled"]),
    )
    db.add(certificate)

    await audit_event(
        db=db, event_type="SCEP_ENROLL", severity="INFO", request=request,
        subject_type="cert", subject_id=serial_hex,
        detail={"cn": cn, "transaction_id": transaction_id},
        description=f"SCEP enrollment: {cn}",
    )
    await db.commit()

    return cert_pem_bytes.decode(), chain_pem


def _detect_key_algo(pub_key) -> str:
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519
    if isinstance(pub_key, rsa.RSAPublicKey):
        return "RSA"
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        return "ECDSA"
    return "Unknown"


def _detect_key_size(pub_key) -> int:
    from cryptography.hazmat.primitives.asymmetric import rsa, ec
    if isinstance(pub_key, rsa.RSAPublicKey):
        return pub_key.key_size
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        return pub_key.curve.key_size
    return 256


# --- SCEP Endpoints ---

async def _scep_get_handler(
    request: Request,
    operation: str,
    message: str | None,
    db: AsyncSession,
) -> Response:
    """SCEP GET handler — GetCACaps, GetCACert, PKIOperation."""
    if not settings.SCEP_ENABLED:
        raise HTTPException(status_code=404, detail="SCEP is not enabled")

    if operation == "GetCACaps":
        return PlainTextResponse(
            content=get_capabilities(),
            media_type="text/plain",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    if operation == "GetCACert":
        ca = await _resolve_scep_ca(db)
        from cryptography import x509 as cx509
        ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())
        ca_der = ca_cert.public_bytes(serialization.Encoding.DER)
        return Response(
            content=ca_der,
            media_type="application/x-x509-ca-cert",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    if operation == "PKIOperation":
        if not message:
            raise HTTPException(status_code=400, detail="Missing message parameter")
        try:
            data = base64.b64decode(message)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 message")
        return await _handle_pki_operation(data, request, db)

    raise HTTPException(status_code=400, detail=f"Unknown operation: {operation}")


async def _scep_post_handler(request: Request, db: AsyncSession) -> Response:
    """SCEP POST handler — PKIOperation via request body."""
    if not settings.SCEP_ENABLED:
        raise HTTPException(status_code=404, detail="SCEP is not enabled")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")

    return await _handle_pki_operation(body, request, db)


@router.get("/scep")
async def scep_get(
    request: Request,
    operation: str = Query(..., description="SCEP operation"),
    message: str | None = Query(None, description="Base64-encoded SCEP message"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _scep_get_handler(request, operation, message, db)


@router.get("/cgi-bin/pkiclient.exe")
async def scep_get_legacy(
    request: Request,
    operation: str = Query(..., description="SCEP operation"),
    message: str | None = Query(None, description="Base64-encoded SCEP message"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _scep_get_handler(request, operation, message, db)


@router.post("/scep")
async def scep_post(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _scep_post_handler(request, db)


@router.post("/cgi-bin/pkiclient.exe")
async def scep_post_legacy(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _scep_post_handler(request, db)


async def _handle_pki_operation(data: bytes, request: Request, db: AsyncSession) -> Response:
    """Process a SCEP PKIOperation message (enrollment)."""
    scep_req = parse_scep_request(data)

    if not scep_req.csr:
        # Try direct DER/PEM CSR as fallback (some clients skip PKCS#7 wrapping)
        raise HTTPException(status_code=400, detail="Unable to extract CSR from SCEP message")

    # Validate CSR signature
    if not scep_req.csr.is_signature_valid:
        return Response(
            content=build_cert_rep_failure(SCEPFailInfo.BAD_MESSAGE_CHECK, scep_req.transaction_id),
            media_type="application/x-pki-message",
            status_code=403,
        )

    # Validate challenge password
    if not _validate_challenge(scep_req.challenge_password):
        await audit_event(
            db=db, event_type="SCEP_CHALLENGE_FAILED", severity="WARNING", request=request,
            subject_type="scep", subject_id=scep_req.transaction_id,
            description=f"SCEP challenge password validation failed",
        )
        await db.commit()
        return Response(
            content=build_cert_rep_failure(SCEPFailInfo.BAD_REQUEST, scep_req.transaction_id),
            media_type="application/x-pki-message",
            status_code=403,
        )

    # Enroll
    ca = await _resolve_scep_ca(db)
    try:
        cert_pem, chain_pem = await _enroll_from_csr(
            scep_req.csr, ca, request, db, scep_req.transaction_id,
        )
    except Exception as e:
        logger.error(f"SCEP enrollment failed: {e}")
        return Response(
            content=build_cert_rep_failure(SCEPFailInfo.BAD_REQUEST, scep_req.transaction_id),
            media_type="application/x-pki-message",
            status_code=500,
        )

    # Build success response
    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    response_data = build_cert_rep_success(
        cert_pem=cert_pem,
        ca_cert_pem=ca.cert_pem,
        ca_key_pem=ca_key_pem,
        transaction_id=scep_req.transaction_id,
        sender_nonce=scep_req.sender_nonce,
    )

    return Response(
        content=response_data,
        media_type="application/x-pki-message",
    )


# --- SCEP Management API (authenticated) ---

@router.get("/api/v1/scep/config")
async def get_scep_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_api_key),
) -> dict:
    """Get SCEP configuration and status."""
    ca_name = ""
    if settings.SCEP_CA_ID:
        ca = await db.get(CertificateAuthority, settings.SCEP_CA_ID)
        if ca:
            ca_name = ca.cn

    return {
        "enabled": settings.SCEP_ENABLED,
        "ca_id": settings.SCEP_CA_ID,
        "ca_name": ca_name,
        "profile": settings.SCEP_PROFILE,
        "max_validity_days": settings.SCEP_MAX_VALIDITY_DAYS,
        "challenge_configured": bool(settings.SCEP_CHALLENGE_PASSWORD),
        "endpoints": {
            "get_ca_caps": "/scep?operation=GetCACaps",
            "get_ca_cert": "/scep?operation=GetCACert",
            "pki_operation": "/scep?operation=PKIOperation",
            "legacy_path": "/cgi-bin/pkiclient.exe",
        },
    }


@router.get("/api/v1/scep/guide")
async def get_scep_guide(
    _=Depends(require_api_key),
) -> dict:
    """Return device enrollment guide with examples."""
    base_url = settings.BASE_URL or "https://pki.internal"
    challenge = "<challenge-password>" if settings.SCEP_CHALLENGE_PASSWORD else "(none required)"

    return {
        "cisco_ios": {
            "title": "Cisco IOS / IOS-XE",
            "commands": f"""! Configure SCEP enrollment
crypto pki trustpoint INTERNAL-CA
  enrollment url http://{base_url.replace('https://', '').replace('http://', '')}/cgi-bin/pkiclient.exe
  subject-name CN=router01.internal,O=Corp
  revocation-check crl
  rsakeypair INTERNAL-CA 2048
  password {challenge}
!
! Authenticate (download CA cert)
crypto pki authenticate INTERNAL-CA
!
! Enroll (request certificate)
crypto pki enroll INTERNAL-CA""",
        },
        "cisco_asa": {
            "title": "Cisco ASA",
            "commands": f"""! Configure trustpoint
crypto ca trustpoint INTERNAL-CA
  enrollment url http://{base_url.replace('https://', '').replace('http://', '')}/scep
  keypair-name INTERNAL-CA
  subject-name CN=asa01.internal,O=Corp
  password {challenge}
!
crypto ca authenticate INTERNAL-CA
crypto ca enroll INTERNAL-CA""",
        },
        "windows_ndes": {
            "title": "Windows (certreq)",
            "commands": f"""REM Generate CSR and enroll via SCEP
certreq -new request.inf request.req
certreq -submit -config "{base_url}/cgi-bin/pkiclient.exe" request.req cert.cer""",
        },
        "openssl_scep": {
            "title": "OpenSSL + sscep (Linux)",
            "commands": f"""# Install sscep
apt-get install sscep

# Get CA certificate
sscep getca -u {base_url}/cgi-bin/pkiclient.exe -c ca.pem

# Generate key and CSR
openssl req -new -newkey rsa:2048 -nodes -keyout device.key \\
  -out device.csr -subj "/CN=device01.internal"

# Enroll
sscep enroll -u {base_url}/cgi-bin/pkiclient.exe \\
  -c ca.pem -k device.key -r device.csr \\
  -l device.pem -p {challenge}""",
        },
        "mikrotik": {
            "title": "MikroTik RouterOS",
            "commands": f"""/certificate
add name=internal-ca common-name=internal-ca
set internal-ca scep-url="{base_url}/scep"
sign internal-ca scep-url="{base_url}/scep" challenge-password={challenge}""",
        },
    }


