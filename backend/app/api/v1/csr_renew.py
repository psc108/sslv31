"""Renew endpoint — extract subject/SAN from existing cert and generate a new CSR automatically."""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key
from app.models.csr import CertificateSigningRequest
from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/csr", tags=["CSR"])
crypto = CryptoEngine()


@router.post("/renew", status_code=201)
async def renew_from_existing(
    request: Request,
    cert_file: UploadFile | None = File(None),
    key_file: UploadFile | None = File(None),
    p12_file: UploadFile | None = File(None),
    p12_password: str | None = Form(None),
    key_password: str | None = Form(None),
    store_key: bool = Form(True),
    digest: str = Form("sha256"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Generate a CSR by extracting subject and SAN from an existing certificate.

    Two modes:
      - Upload a .p12/.pfx (contains cert + key): extracts both automatically
      - Upload cert_file + key_file separately
    """
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key,
        load_der_private_key,
        pkcs12,
        Encoding,
    )
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519

    cert_obj = None
    private_key = None

    # --- Option A: PKCS#12 file (contains both cert + key) ---
    if p12_file:
        p12_bytes = await p12_file.read()
        if not p12_bytes:
            raise HTTPException(status_code=422, detail="Empty P12 file")

        pwd = p12_password.encode() if p12_password else None
        try:
            p12_key, p12_cert, p12_chain = pkcs12.load_key_and_certificates(p12_bytes, pwd)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Failed to load P12: {e}")

        if not p12_cert:
            raise HTTPException(status_code=422, detail="P12 file does not contain a certificate")
        if not p12_key:
            raise HTTPException(status_code=422, detail="P12 file does not contain a private key")

        cert_obj = p12_cert
        private_key = p12_key

    # --- Option B: Separate cert + key files ---
    elif cert_file and key_file:
        cert_bytes = await cert_file.read()
        key_bytes = await key_file.read()

        if not cert_bytes:
            raise HTTPException(status_code=422, detail="Empty certificate file")
        if not key_bytes:
            raise HTTPException(status_code=422, detail="Empty key file")

        # Parse certificate
        try:
            if b"-----BEGIN CERTIFICATE-----" in cert_bytes:
                cert_obj = cx509.load_pem_x509_certificate(cert_bytes)
            else:
                cert_obj = cx509.load_der_x509_certificate(cert_bytes)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid certificate: {e}")

        # Parse key
        pwd = key_password.encode() if key_password else None
        try:
            if b"-----BEGIN" in key_bytes:
                private_key = load_pem_private_key(key_bytes, password=pwd)
            else:
                private_key = load_der_private_key(key_bytes, password=pwd)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Failed to load key: {e}")

    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either p12_file (PKCS#12) or both cert_file and key_file",
        )

    # --- Extract subject from certificate ---
    subject_attrs = {}
    oid_map = {
        cx509.oid.NameOID.COMMON_NAME: "cn",
        cx509.oid.NameOID.ORGANIZATION_NAME: "o",
        cx509.oid.NameOID.ORGANIZATIONAL_UNIT_NAME: "ou",
        cx509.oid.NameOID.COUNTRY_NAME: "c",
        cx509.oid.NameOID.STATE_OR_PROVINCE_NAME: "st",
        cx509.oid.NameOID.LOCALITY_NAME: "l",
    }
    for attr in cert_obj.subject:
        field = oid_map.get(attr.oid)
        if field:
            subject_attrs[field] = attr.value

    if not subject_attrs.get("cn"):
        raise HTTPException(status_code=422, detail="Certificate has no Common Name")

    subject = SubjectInfo(
        cn=subject_attrs.get("cn", ""),
        o=subject_attrs.get("o", ""),
        ou=subject_attrs.get("ou", ""),
        c=subject_attrs.get("c", ""),
        st=subject_attrs.get("st", ""),
        l=subject_attrs.get("l", ""),
    )

    # --- Extract SANs from certificate ---
    san_list: list[SANEntry] = []
    try:
        san_ext = cert_obj.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(cx509.DNSName):
            san_list.append(SANEntry(type="dns", value=dns))
        for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
            san_list.append(SANEntry(type="ip", value=str(ip)))
        for email in san_ext.value.get_values_for_type(cx509.RFC822Name):
            san_list.append(SANEntry(type="email", value=email))
        for uri in san_ext.value.get_values_for_type(cx509.UniformResourceIdentifier):
            san_list.append(SANEntry(type="uri", value=uri))
    except cx509.ExtensionNotFound:
        pass  # No SAN extension — proceed without

    # --- Detect key algorithm and size ---
    pub_key = private_key.public_key()
    if isinstance(pub_key, rsa.RSAPublicKey):
        key_algo, key_size = "RSA", pub_key.key_size
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        key_algo, key_size = "ECDSA", pub_key.key_size
    elif isinstance(pub_key, ed25519.Ed25519PublicKey):
        key_algo, key_size = "Ed25519", 256
    else:
        raise HTTPException(status_code=422, detail="Unsupported key algorithm")

    # --- Generate CSR ---
    csr = crypto.generate_csr(subject, san_list, private_key, digest)

    # Verify
    verification = crypto.verify_csr(csr)
    if verification.get("signature") == "fail":
        raise HTTPException(status_code=500, detail="CSR signature verification failed")

    csr_pem = crypto.export_csr_pem(csr).decode()

    # Encrypt and store key
    key_blob = None
    if store_key:
        key_pem = crypto.export_key_pem(private_key)
        key_blob = crypto.encrypt_key_blob(key_pem, settings.CERT_MASTER_KEY)

    # Store CSR record
    record = CertificateSigningRequest(
        mode="renew",
        subject_json=json.dumps(subject_attrs),
        san_json=json.dumps([{"type": s.type, "value": s.value} for s in san_list]),
        key_algo=key_algo,
        key_size=key_size,
        digest=digest,
        csr_pem=csr_pem,
        key_blob=key_blob,
        status="pending",
    )
    db.add(record)

    await audit_event(
        db=db,
        event_type="CSR_GENERATED",
        severity="INFO",
        request=request,
        subject_type="csr",
        subject_id=record.id,
        detail={
            "mode": "renew",
            "cn": subject.cn,
            "key_algo": key_algo,
            "san_count": len(san_list),
            "source_serial": format(cert_obj.serial_number, "x"),
        },
        description=f"CSR generated (renewal): {subject.cn}",
    )

    await db.commit()
    await db.refresh(record)

    return {
        "id": record.id,
        "mode": "renew",
        "subject_json": record.subject_json,
        "san_json": record.san_json,
        "key_algo": key_algo,
        "key_size": key_size,
        "status": "pending",
        "csr_pem": csr_pem,
        "verification": verification,
        "extracted": {
            "cn": subject.cn,
            "subject": subject_attrs,
            "san": [{"type": s.type, "value": s.value} for s in san_list],
            "original_serial": format(cert_obj.serial_number, "x"),
            "original_issuer": cert_obj.issuer.rfc4514_string(),
            "original_expires": cert_obj.not_valid_after_utc.isoformat(),
        },
        "created_at": record.created_at.isoformat(),
    }
