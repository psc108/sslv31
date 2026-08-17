"""EST Protocol endpoints — RFC 7030 Enrollment over Secure Transport.

All endpoints under /.well-known/est/ as per RFC 7030 §3.2.2.
Provides automated certificate enrollment for devices and services.
"""

import base64
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import AuthContext, get_auth_context
from app.models.ca import CertificateAuthority
from app.models.certificate import Certificate
from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry
from app.services.chain_builder import build_chain, assemble_chain_pem
from app.services.serial_allocator import allocate_serial_safe
from app.services.audit import audit_event
from app.services.est_service import (
    parse_pkcs10_request,
    cert_to_est_response,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/.well-known/est", tags=["EST (RFC 7030)"])
crypto = CryptoEngine()

# Content types per RFC 7030
CT_PKCS7 = "application/pkcs7-mime; smime-type=certs-only"
CT_PKCS10 = "application/pkcs10"
CT_CSRATTRS = "application/csrattrs"


def _get_est_ca_id() -> str:
    """Resolve the CA used for EST enrollment.

    Uses EST_CA_ID env var if set, otherwise falls back to first available CA.
    """
    return getattr(settings, "EST_CA_ID", "") or ""


async def _resolve_est_ca(db: AsyncSession) -> CertificateAuthority:
    """Find the CA to use for EST enrollment."""
    ca_id = _get_est_ca_id()
    if ca_id:
        ca = await db.get(CertificateAuthority, ca_id)
        if ca:
            return ca

    # Fallback: first non-root CA with a key, or first root CA with a key
    result = await db.execute(
        select(CertificateAuthority)
        .where(CertificateAuthority.key_blob.isnot(None))
        .order_by(CertificateAuthority.is_root.asc())
        .limit(1)
    )
    ca = result.scalar_one_or_none()
    if not ca:
        raise HTTPException(status_code=503, detail="No CA available for EST enrollment")
    return ca


async def _issue_from_csr(
    csr: "x509.CertificateSigningRequest",
    ca: CertificateAuthority,
    profile: str,
    validity_days: int,
    request: Request,
    db: AsyncSession,
    auth_desc: str,
) -> tuple[Certificate, str, str]:
    """Common enrollment logic — sign a CSR and store the certificate."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.x509.oid import NameOID

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Extract subject from CSR
    cn_attrs = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    cn = cn_attrs[0].value if cn_attrs else "EST-enrolled"
    o_attrs = csr.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
    ou_attrs = csr.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)
    c_attrs = csr.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)

    subject = SubjectInfo(
        cn=cn,
        o=o_attrs[0].value if o_attrs else "",
        ou=ou_attrs[0].value if ou_attrs else "",
        c=c_attrs[0].value if c_attrs else "",
    )

    # Extract SANs from CSR extensions
    san_list: list[SANEntry] = []
    try:
        san_ext = csr.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(cx509.DNSName):
            san_list.append(SANEntry(type="dns", value=dns))
        for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
            san_list.append(SANEntry(type="ip", value=str(ip)))
        for email in san_ext.value.get_values_for_type(cx509.RFC822Name):
            san_list.append(SANEntry(type="email", value=email))
        for uri in san_ext.value.get_values_for_type(cx509.UniformResourceIdentifier):
            san_list.append(SANEntry(type="uri", value=uri))
    except cx509.ExtensionNotFound:
        pass

    # Use the CSR's public key (not generating a new one)
    serial_int = await allocate_serial_safe(ca.id, db)

    # Build certificate using CSR's public key
    from cryptography.x509 import CertificateBuilder, BasicConstraints, KeyUsage
    from cryptography.x509 import SubjectKeyIdentifier, AuthorityKeyIdentifier
    from cryptography.x509 import ExtendedKeyUsage, SubjectAlternativeName
    from cryptography.x509.oid import ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes
    from datetime import timedelta

    now = datetime.now(timezone.utc)
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
    )

    # EKU based on profile
    if profile == "server":
        builder = builder.add_extension(
            ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
    elif profile == "client":
        builder = builder.add_extension(
            ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
        )
    else:
        builder = builder.add_extension(
            ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )

    # SANs
    if san_list:
        san_names = crypto._build_san_extension(san_list)
        builder = builder.add_extension(SubjectAlternativeName(san_names), critical=False)

    # CDP/AIA
    if settings.PKI_BASE_URL:
        from cryptography.x509 import CRLDistributionPoints, DistributionPoint
        cdp_url = f"{settings.PKI_BASE_URL}/api/v1/pki/crl/{ca.id}"
        dp = DistributionPoint(
            full_name=[cx509.UniformResourceIdentifier(cdp_url)],
            relative_name=None, crl_issuer=None, reasons=None,
        )
        builder = builder.add_extension(CRLDistributionPoints([dp]), critical=False)

        from cryptography.x509 import AuthorityInformationAccess, AccessDescription, AuthorityInformationAccessOID
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

    # Store — key_blob is empty since we don't have the private key (client has it)
    # Use a placeholder encrypted blob
    placeholder_key = crypto.encrypt_key_blob(b"EST_ENROLLED_NO_KEY", settings.CERT_MASTER_KEY)

    certificate = Certificate(
        serial=serial_hex,
        profile=profile,
        subject_json=json.dumps({"cn": subject.cn, "o": subject.o, "ou": subject.ou, "c": subject.c}),
        san_json=json.dumps([{"type": s.type, "value": s.value} for s in san_list]),
        key_algo=_detect_key_algo(csr.public_key()),
        key_size=_detect_key_size(csr.public_key()),
        cert_pem=cert_pem_bytes.decode(),
        key_blob=placeholder_key,
        chain_pem=chain_pem,
        signing_ca_id=ca.id,
        status="valid",
        expires_at=cert_obj.not_valid_after_utc,
        tags=json.dumps(["est-enrolled"]),
    )
    db.add(certificate)

    await audit_event(
        db=db, event_type="EST_ENROLL", severity="INFO", request=request,
        subject_type="cert", subject_id=serial_hex,
        description=f"EST enrollment: {cn} ({auth_desc})",
    )
    await db.commit()

    return certificate, cert_pem_bytes.decode(), chain_pem


def _detect_key_algo(pub_key) -> str:
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519
    if isinstance(pub_key, rsa.RSAPublicKey):
        return "RSA"
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        return "ECDSA"
    elif isinstance(pub_key, ed25519.Ed25519PublicKey):
        return "Ed25519"
    return "Unknown"


def _detect_key_size(pub_key) -> int:
    from cryptography.hazmat.primitives.asymmetric import rsa, ec
    if isinstance(pub_key, rsa.RSAPublicKey):
        return pub_key.key_size
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        return pub_key.curve.key_size
    return 256


# --- EST Endpoints ---


@router.get("/cacerts")
async def est_cacerts(
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Distribution of CA certificates (RFC 7030 §4.1).

    Public endpoint — no authentication required.
    Returns the CA certificate chain for trust establishment.
    """
    ca = await _resolve_est_ca(db)

    # Build full chain (CA + any parent CAs up to root)
    ca_chain = await build_chain(ca.id, db)
    # Include the CA's own cert
    all_pems = [ca.cert_pem] + ca_chain

    # Return as base64-encoded concatenated certs
    combined = "\n".join(all_pems)
    b64_body = base64.b64encode(combined.encode())

    return Response(
        content=b64_body,
        media_type=CT_PKCS7,
        headers={
            "Content-Transfer-Encoding": "base64",
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.post("/simpleenroll")
async def est_simple_enroll(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
    content_type: str | None = Header(None, alias="content-type"),
) -> Response:
    """Initial enrollment — client submits CSR, receives certificate (RFC 7030 §4.2).

    Requires authentication (HTTP Basic over TLS, Bearer token, or API key).
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body — expected PKCS#10 CSR")

    try:
        csr = parse_pkcs10_request(body, content_type or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Verify CSR signature
    if not csr.is_signature_valid:
        raise HTTPException(status_code=400, detail="CSR signature verification failed")

    ca = await _resolve_est_ca(db)
    validity_days = min(settings.MAX_CERT_DAYS, 365)

    cert_record, cert_pem, chain_pem = await _issue_from_csr(
        csr=csr, ca=ca, profile="server", validity_days=validity_days,
        request=request, db=db, auth_desc=f"user:{auth.username}",
    )

    # Response: base64-encoded DER cert
    response_body = cert_to_est_response(cert_pem, chain_pem)

    return Response(
        content=response_body,
        media_type=CT_PKCS7,
        headers={
            "Content-Transfer-Encoding": "base64",
        },
    )


@router.post("/simplereenroll")
async def est_simple_reenroll(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
    content_type: str | None = Header(None, alias="content-type"),
) -> Response:
    """Re-enrollment — renew an existing certificate (RFC 7030 §4.2.2).

    Same as simpleenroll but semantically for renewal. The CSR subject
    should match the existing certificate being renewed.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body — expected PKCS#10 CSR")

    try:
        csr = parse_pkcs10_request(body, content_type or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not csr.is_signature_valid:
        raise HTTPException(status_code=400, detail="CSR signature verification failed")

    ca = await _resolve_est_ca(db)
    validity_days = min(settings.MAX_CERT_DAYS, 365)

    cert_record, cert_pem, chain_pem = await _issue_from_csr(
        csr=csr, ca=ca, profile="server", validity_days=validity_days,
        request=request, db=db, auth_desc=f"reenroll:{auth.username}",
    )

    await audit_event(
        db=db, event_type="EST_REENROLL", severity="INFO", request=request,
        subject_type="cert", subject_id=cert_record.serial,
        description=f"EST re-enrollment: {json.loads(cert_record.subject_json).get('cn', '')}",
    )
    await db.commit()

    response_body = cert_to_est_response(cert_pem, chain_pem)

    return Response(
        content=response_body,
        media_type=CT_PKCS7,
        headers={"Content-Transfer-Encoding": "base64"},
    )


@router.get("/csrattrs")
async def est_csr_attrs(
    db: AsyncSession = Depends(get_db),
) -> Response:
    """CSR Attributes — advertise what the server expects in CSRs (RFC 7030 §4.5).

    Public endpoint — helps clients construct valid CSRs.
    """
    # Return recommended attributes as base64-encoded ASN.1
    try:
        from app.services.est_service import build_csr_attrs_response
        attrs_b64 = build_csr_attrs_response()
    except ImportError:
        # Fallback if pyasn1 not available — return empty (valid per RFC)
        attrs_b64 = b""

    return Response(
        content=attrs_b64,
        media_type=CT_CSRATTRS,
        headers={
            "Content-Transfer-Encoding": "base64",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.post("/serverkeygen")
async def est_server_keygen(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
    content_type: str | None = Header(None, alias="content-type"),
) -> Response:
    """Server-side key generation (RFC 7030 §4.4).

    Client submits a CSR (for subject/SAN info), server generates the key pair,
    issues the certificate, and returns both the cert and the private key.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body — expected PKCS#10 CSR for subject info")

    try:
        csr = parse_pkcs10_request(body, content_type or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ca = await _resolve_est_ca(db)
    validity_days = min(settings.MAX_CERT_DAYS, 365)

    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.x509.oid import NameOID

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Extract subject from CSR
    cn_attrs = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    cn = cn_attrs[0].value if cn_attrs else "EST-keygen"

    subject = SubjectInfo(cn=cn)
    san_list: list[SANEntry] = []
    try:
        san_ext = csr.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(cx509.DNSName):
            san_list.append(SANEntry(type="dns", value=dns))
        for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
            san_list.append(SANEntry(type="ip", value=str(ip)))
    except cx509.ExtensionNotFound:
        pass

    # Generate server-side key
    key = crypto.generate_keypair("RSA", 2048)
    serial_int = await allocate_serial_safe(ca.id, db)

    cert_obj = crypto.issue_certificate(
        profile="server", subject=subject, san_list=san_list,
        key=key, signing_ca_key=ca_key, signing_ca_cert=ca_cert,
        validity_days=validity_days, signing_ca_id=ca.id,
        pki_base_url=settings.PKI_BASE_URL,
        serial_number=serial_int,
    )

    cert_pem_bytes = crypto.export_cert_pem(cert_obj)
    key_pem_bytes = crypto.export_key_pem(key)
    serial_hex = format(cert_obj.serial_number, "x")

    # Store
    ca_chain = await build_chain(ca.id, db)
    chain_pem = assemble_chain_pem(cert_pem_bytes.decode(), ca_chain, mode="full")
    key_blob = crypto.encrypt_key_blob(key_pem_bytes, settings.CERT_MASTER_KEY)

    certificate = Certificate(
        serial=serial_hex,
        profile="server",
        subject_json=json.dumps({"cn": cn}),
        san_json=json.dumps([{"type": s.type, "value": s.value} for s in san_list]),
        key_algo="RSA",
        key_size=2048,
        cert_pem=cert_pem_bytes.decode(),
        key_blob=key_blob,
        chain_pem=chain_pem,
        signing_ca_id=ca.id,
        status="valid",
        expires_at=cert_obj.not_valid_after_utc,
        tags=json.dumps(["est-keygen"]),
    )
    db.add(certificate)

    await audit_event(
        db=db, event_type="EST_KEYGEN", severity="WARNING", request=request,
        subject_type="cert", subject_id=serial_hex,
        description=f"EST server-keygen: {cn} (user:{auth.username})",
    )
    await db.commit()

    # Response: multipart — cert + key (RFC 7030 §4.4.2)
    # Use application/pkcs8 for key, application/pkcs7-mime for cert
    # Many clients expect a simple JSON or multipart response
    cert_b64 = base64.b64encode(cert_pem_bytes).decode()
    key_b64 = base64.b64encode(key_pem_bytes).decode()

    # Return as multipart/mixed per RFC 7030 §4.4.2
    boundary = "estServerKeyGenBoundary"
    body_parts = (
        f"--{boundary}\r\n"
        f"Content-Type: application/pkcs8\r\n"
        f"Content-Transfer-Encoding: base64\r\n\r\n"
        f"{key_b64}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {CT_PKCS7}\r\n"
        f"Content-Transfer-Encoding: base64\r\n\r\n"
        f"{cert_b64}\r\n"
        f"--{boundary}--\r\n"
    )

    return Response(
        content=body_parts.encode(),
        media_type=f"multipart/mixed; boundary={boundary}",
    )
