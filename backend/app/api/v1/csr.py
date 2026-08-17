"""CSR endpoints — generate, list, sign, export, and delete CSRs."""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key, get_auth_context, AuthContext
from app.models.csr import CertificateSigningRequest
from app.models.ca import CertificateAuthority
from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry
from app.services.chain_builder import build_chain, assemble_chain_pem
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/csr", tags=["CSR"])
crypto = CryptoEngine()


# --- Schemas (inline for CSR-specific) ---

from pydantic import BaseModel, Field
from app.api.v1.schemas import SubjectSchema, SANEntrySchema


class CSRCreateRequest(BaseModel):
    mode: str = Field(..., pattern="^(new_key|existing_key)$")
    subject: SubjectSchema
    san: list[SANEntrySchema] = []
    key_algo: str = Field("RSA", pattern="^(RSA|ECDSA|Ed25519)$")
    key_size: int = Field(2048)
    key_password: str | None = None
    store_key: bool = True
    digest: str = Field("sha256", pattern="^(sha256|sha384|sha512)$")


class CSRSignRequest(BaseModel):
    signing_ca_id: str
    validity_days: int = Field(365, gt=0)
    profile: str = Field("server", pattern="^(server|client|code_sign|email|custom)$")
    template: str | None = None  # Template name for policy enforcement


@router.post("", status_code=201)
async def create_csr(
    body: CSRCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """Generate CSR — Path A (new key)."""
    if body.mode != "new_key":
        raise HTTPException(status_code=422, detail="Use multipart upload for existing_key mode")

    # Generate keypair
    key = crypto.generate_keypair(body.key_algo, body.key_size)

    subject = SubjectInfo(
        cn=body.subject.cn, o=body.subject.o, ou=body.subject.ou,
        c=body.subject.c, st=body.subject.st, l=body.subject.l,
    )
    san_list = [SANEntry(type=s.type, value=s.value) for s in body.san]

    # Generate CSR
    csr = crypto.generate_csr(subject, san_list, key, body.digest)

    # Verify
    verification = crypto.verify_csr(csr)
    if verification.get("signature") == "fail":
        raise HTTPException(status_code=500, detail="CSR signature verification failed")

    csr_pem = crypto.export_csr_pem(csr).decode()

    # Encrypt and store key if requested
    key_blob = None
    if body.store_key:
        key_pem = crypto.export_key_pem(key, passphrase=body.key_password)
        key_blob = crypto.encrypt_key_blob(
            crypto.export_key_pem(key), settings.CERT_MASTER_KEY
        )

    record = CertificateSigningRequest(
        mode="new_key",
        subject_json=json.dumps(body.subject.model_dump()),
        san_json=json.dumps([s.model_dump() for s in body.san]),
        key_algo=body.key_algo,
        key_size=body.key_size,
        digest=body.digest,
        csr_pem=csr_pem,
        key_blob=key_blob,
        status="pending",
        tenant_id=auth.tenant_id,
    )
    db.add(record)

    await audit_event(
        db=db,
        event_type="CSR_GENERATED",
        severity="INFO",
        request=request,
        subject_type="csr",
        subject_id=record.id,
        detail={"mode": "new_key", "cn": body.subject.cn, "key_algo": body.key_algo},
        description=f"CSR generated (new key): {body.subject.cn}",
    )

    await db.commit()
    await db.refresh(record)

    return {
        "id": record.id,
        "mode": record.mode,
        "subject_json": record.subject_json,
        "san_json": record.san_json,
        "key_algo": record.key_algo,
        "key_size": record.key_size,
        "status": record.status,
        "csr_pem": record.csr_pem,
        "verification": verification,
        "created_at": record.created_at.isoformat(),
    }


@router.post("/upload", status_code=201)
async def create_csr_from_existing_key(
    request: Request,
    key_file: UploadFile = File(...),
    subject_json: str = Form(...),
    san_json: str = Form("[]"),
    key_password: str | None = Form(None),
    store_key: bool = Form(False),
    digest: str = Form("sha256"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Generate CSR — Path B (existing key upload)."""
    # Read uploaded key
    key_bytes = await key_file.read()
    if not key_bytes:
        raise HTTPException(status_code=422, detail="Empty key file")

    # Parse subject and SAN
    try:
        subject_data = json.loads(subject_json)
        san_data = json.loads(san_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid JSON in subject or SAN")

    subject = SubjectInfo(
        cn=subject_data.get("cn", ""),
        o=subject_data.get("o", ""),
        ou=subject_data.get("ou", ""),
        c=subject_data.get("c", ""),
        st=subject_data.get("st", ""),
        l=subject_data.get("l", ""),
    )
    san_list = [SANEntry(type=s["type"], value=s["value"]) for s in san_data]

    # Generate CSR from existing key
    try:
        csr = crypto.csr_from_existing_key(key_bytes, key_password, subject, san_list, digest)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to load key: {e}")

    verification = crypto.verify_csr(csr)
    csr_pem = crypto.export_csr_pem(csr).decode()

    # Detect key algo and size from CSR
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519
    pub_key = csr.public_key()
    if isinstance(pub_key, rsa.RSAPublicKey):
        key_algo, key_size = "RSA", pub_key.key_size
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        key_algo, key_size = "ECDSA", pub_key.key_size
    else:
        key_algo, key_size = "Ed25519", 256

    # Optionally store key
    key_blob = None
    if store_key:
        key_blob = crypto.encrypt_key_blob(key_bytes, settings.CERT_MASTER_KEY)

    record = CertificateSigningRequest(
        mode="existing_key",
        subject_json=subject_json,
        san_json=san_json if san_json != "[]" else "[]",
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
        detail={"mode": "existing_key", "cn": subject.cn, "key_algo": key_algo, "store_key": store_key},
        description=f"CSR generated (existing key): {subject.cn}",
    )

    await db.commit()
    await db.refresh(record)

    return {
        "id": record.id,
        "mode": record.mode,
        "subject_json": record.subject_json,
        "san_json": record.san_json,
        "key_algo": record.key_algo,
        "key_size": record.key_size,
        "status": record.status,
        "csr_pem": record.csr_pem,
        "verification": verification,
        "created_at": record.created_at.isoformat(),
    }


@router.get("")
async def list_csrs(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> list[dict]:
    result = await db.execute(
        select(CertificateSigningRequest).order_by(CertificateSigningRequest.created_at.desc())
    )
    csrs = result.scalars().all()
    return [
        {
            "id": c.id,
            "mode": c.mode,
            "subject_json": c.subject_json,
            "san_json": c.san_json,
            "key_algo": c.key_algo,
            "key_size": c.key_size,
            "status": c.status,
            "signed_cert_id": c.signed_cert_id,
            "has_stored_key": c.key_blob is not None,
            "created_at": c.created_at.isoformat(),
        }
        for c in csrs
    ]


@router.get("/{csr_id}")
async def get_csr(
    csr_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    record = await db.get(CertificateSigningRequest, csr_id)
    if not record:
        raise HTTPException(status_code=404, detail="CSR not found")
    return {
        "id": record.id,
        "mode": record.mode,
        "subject_json": record.subject_json,
        "san_json": record.san_json,
        "key_algo": record.key_algo,
        "key_size": record.key_size,
        "digest": record.digest,
        "status": record.status,
        "csr_pem": record.csr_pem,
        "signed_cert_id": record.signed_cert_id,
        "has_stored_key": record.key_blob is not None,
        "created_at": record.created_at.isoformat(),
    }


@router.post("/{csr_id}/sign")
async def sign_csr(
    csr_id: str,
    body: CSRSignRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Sign a stored CSR with an internal CA."""
    record = await db.get(CertificateSigningRequest, csr_id)
    if not record:
        raise HTTPException(status_code=404, detail="CSR not found")
    if record.status != "pending":
        raise HTTPException(status_code=409, detail="CSR is not in pending state")
    if not record.key_blob:
        raise HTTPException(status_code=422, detail="No stored key — cannot sign without private key")

    # Load CA
    ca = await db.get(CertificateAuthority, body.signing_ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="Signing CA not found")

    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography import x509 as cx509

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Decrypt stored key
    key_pem = crypto.decrypt_key_blob(record.key_blob, settings.CERT_MASTER_KEY)
    key = load_pem_private_key(key_pem, password=None)

    # Build subject and SAN from CSR record
    subject_data = json.loads(record.subject_json)
    san_data = json.loads(record.san_json)

    subject = SubjectInfo(
        cn=subject_data.get("cn", ""),
        o=subject_data.get("o", ""),
        ou=subject_data.get("ou", ""),
        c=subject_data.get("c", ""),
        st=subject_data.get("st", ""),
        l=subject_data.get("l", ""),
    )
    san_list = [SANEntry(type=s["type"], value=s["value"]) for s in san_data]

    # Issue certificate
    # Template enforcement
    if body.template:
        from app.api.v1.templates import enforce_template
        await enforce_template(
            template_name=body.template,
            key_algo=record.key_algo,
            key_size=record.key_size,
            validity_days=body.validity_days,
            san_list=san_data,
            subject_cn=subject.cn,
            subject_o=subject.o,
            db=db,
        )

    try:
        cert = crypto.issue_certificate(
            profile=body.profile,
            subject=subject,
            san_list=san_list,
            key=key,
            signing_ca_key=ca_key,
            signing_ca_cert=ca_cert,
            validity_days=body.validity_days,
            signing_ca_id=body.signing_ca_id,
            pki_base_url=settings.PKI_BASE_URL,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Store certificate
    from app.models.certificate import Certificate
    cert_pem = crypto.export_cert_pem(cert).decode()
    ca_chain = await build_chain(body.signing_ca_id, db)
    chain_pem = assemble_chain_pem(cert_pem, ca_chain, mode="full")
    serial_hex = format(cert.serial_number, "x")
    key_blob_enc = crypto.encrypt_key_blob(key_pem, settings.CERT_MASTER_KEY)

    certificate = Certificate(
        serial=serial_hex,
        profile=body.profile,
        subject_json=record.subject_json,
        san_json=record.san_json,
        key_algo=record.key_algo,
        key_size=record.key_size,
        cert_pem=cert_pem,
        key_blob=key_blob_enc,
        chain_pem=chain_pem,
        signing_ca_id=body.signing_ca_id,
        status="valid",
        expires_at=cert.not_valid_after_utc,
    )
    db.add(certificate)

    # Update CSR record
    record.status = "signed"
    record.signed_cert_id = certificate.id

    await audit_event(
        db=db,
        event_type="CSR_SIGNED",
        severity="INFO",
        request=request,
        subject_type="csr",
        subject_id=csr_id,
        detail={"cert_serial": serial_hex, "ca_id": body.signing_ca_id},
        description=f"CSR signed: {subject.cn} → serial {serial_hex}",
    )

    await db.commit()

    return {"status": "signed", "certificate_serial": serial_hex, "certificate_id": certificate.id}


@router.get("/{csr_id}/export/{fmt}")
async def export_csr(
    csr_id: str,
    fmt: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> Response:
    if fmt not in ("pem", "der", "text", "zip"):
        raise HTTPException(status_code=422, detail="Format must be pem, der, text, or zip")

    record = await db.get(CertificateSigningRequest, csr_id)
    if not record:
        raise HTTPException(status_code=404, detail="CSR not found")

    subject = json.loads(record.subject_json)
    cn = subject.get("cn", "csr").replace(" ", "_")

    await audit_event(
        db=db,
        event_type="CSR_DOWNLOAD",
        severity="INFO",
        request=request,
        subject_type="csr",
        subject_id=csr_id,
        detail={"format": fmt},
    )
    await db.commit()

    if fmt == "pem":
        return Response(
            content=record.csr_pem.encode(),
            media_type="application/x-pem-file",
            headers={"Content-Disposition": f'attachment; filename="{cn}.csr"'},
        )

    elif fmt == "der":
        from cryptography import x509 as cx509
        csr_obj = cx509.load_pem_x509_csr(record.csr_pem.encode())
        der = crypto.export_csr_der(csr_obj)
        return Response(
            content=der,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{cn}.der"'},
        )

    elif fmt == "text":
        from cryptography import x509 as cx509
        csr_obj = cx509.load_pem_x509_csr(record.csr_pem.encode())
        # Build readable text
        text_lines = [f"Certificate Signing Request (PKCS#10)"]
        text_lines.append(f"  Subject: {csr_obj.subject.rfc4514_string()}")
        text_lines.append(f"  Public Key Algorithm: {record.key_algo} ({record.key_size} bit)")
        text_lines.append(f"  Signature Valid: {csr_obj.is_signature_valid}")
        for ext in csr_obj.extensions:
            text_lines.append(f"  Extension: {ext.oid._name} (critical={ext.critical})")
            text_lines.append(f"    {ext.value}")
        text_lines.append("")
        text_lines.append("PEM:")
        text_lines.append(record.csr_pem)
        text_output = "\n".join(text_lines)

        return Response(
            content=text_output.encode(),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{cn}-csr.txt"'},
        )

    elif fmt == "zip":
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{cn}.csr", record.csr_pem)
            # Text dump
            from cryptography import x509 as cx509
            csr_obj = cx509.load_pem_x509_csr(record.csr_pem.encode())
            text = f"Subject: {csr_obj.subject.rfc4514_string()}\nKey: {record.key_algo} {record.key_size}\n"
            zf.writestr(f"{cn}-csr.txt", text)
            zf.writestr("README.txt", _csr_readme(cn))

        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{cn}-csr-bundle.zip"'},
        )

    raise HTTPException(status_code=422, detail=f"Unsupported format: {fmt}")


@router.post("/{csr_id}/import-cert", status_code=201)
async def import_signed_certificate(
    csr_id: str,
    request: Request,
    cert_file: UploadFile = File(...),
    chain_file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Import a signed certificate received from an external CA, pairing it with the CSR's stored key."""
    record = await db.get(CertificateSigningRequest, csr_id)
    if not record:
        raise HTTPException(status_code=404, detail="CSR not found")
    if record.status != "pending":
        raise HTTPException(status_code=409, detail="CSR is not in pending state")

    # Read uploaded cert
    cert_bytes = await cert_file.read()
    if not cert_bytes:
        raise HTTPException(status_code=422, detail="Empty certificate file")

    # Parse certificate
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding

    try:
        # Try PEM first
        if b"-----BEGIN CERTIFICATE-----" in cert_bytes:
            cert_obj = cx509.load_pem_x509_certificate(cert_bytes)
        else:
            # Try DER
            cert_obj = cx509.load_der_x509_certificate(cert_bytes)
            cert_bytes = cert_obj.public_bytes(Encoding.PEM)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid certificate file: {e}")

    # Verify the cert's public key matches the CSR's public key
    csr_obj = cx509.load_pem_x509_csr(record.csr_pem.encode())
    cert_pub_bytes = cert_obj.public_key().public_bytes(
        Encoding.PEM,
        format=cert_obj.public_key().public_bytes.__func__.__code__.co_varnames[2]  # type: ignore
    ) if False else None  # skip complex comparison, use simpler method:

    from cryptography.hazmat.primitives.serialization import PublicFormat
    cert_pub = cert_obj.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    csr_pub = csr_obj.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    if cert_pub != csr_pub:
        raise HTTPException(
            status_code=422,
            detail="Certificate public key does not match CSR. This certificate was not issued for this CSR."
        )

    # Read optional chain
    chain_pem = cert_bytes.decode()
    if chain_file:
        chain_bytes = await chain_file.read()
        if chain_bytes:
            chain_pem = cert_bytes.decode() + chain_bytes.decode()

    # Store as a certificate record
    from app.models.certificate import Certificate

    serial_hex = format(cert_obj.serial_number, "x")

    # Get key blob (if stored)
    key_blob = record.key_blob
    if not key_blob:
        # No stored key — store cert without key
        key_blob = b""

    # Detect profile from CSR context
    subject_data = json.loads(record.subject_json)

    certificate = Certificate(
        serial=serial_hex,
        profile="external",
        subject_json=record.subject_json,
        san_json=record.san_json,
        key_algo=record.key_algo,
        key_size=record.key_size,
        cert_pem=cert_bytes.decode(),
        key_blob=key_blob,
        chain_pem=chain_pem,
        signing_ca_id=None,  # Externally signed — no internal CA
        status="valid",
        expires_at=cert_obj.not_valid_after_utc,
    )
    db.add(certificate)

    # Update CSR record
    record.status = "signed"
    record.signed_cert_id = certificate.id

    await audit_event(
        db=db,
        event_type="CERT_IMPORTED",
        severity="INFO",
        request=request,
        subject_type="cert",
        subject_id=serial_hex,
        detail={
            "csr_id": csr_id,
            "cn": subject_data.get("cn", ""),
            "issuer": cert_obj.issuer.rfc4514_string(),
            "source": "external_ca",
        },
        description=f"Signed certificate imported: {subject_data.get('cn', '')} (external CA)",
    )

    await db.commit()

    return {
        "status": "imported",
        "certificate_id": certificate.id,
        "certificate_serial": serial_hex,
        "issuer": cert_obj.issuer.rfc4514_string(),
        "expires_at": cert_obj.not_valid_after_utc.isoformat(),
    }


@router.delete("/{csr_id}", status_code=200)
async def delete_csr(
    csr_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    record = await db.get(CertificateSigningRequest, csr_id)
    if not record:
        raise HTTPException(status_code=404, detail="CSR not found")

    await audit_event(
        db=db,
        event_type="CSR_DELETED",
        severity="INFO",
        request=request,
        subject_type="csr",
        subject_id=csr_id,
    )

    await db.delete(record)
    await db.commit()
    return {"status": "deleted", "id": csr_id}


def _csr_readme(cn: str) -> str:
    return f"""CSR Bundle — {cn}
{'=' * 40}

Files:
- {cn}.csr         PKCS#10 CSR (PEM format)
- {cn}-csr.txt     Readable CSR details

Submission Instructions:
- Let's Encrypt / ACME:  certbot certonly --csr {cn}.csr
- DigiCert / Sectigo:    Paste PEM content into web portal
- Microsoft ADCS:        certreq -submit {cn}.csr
- Internal OpenSSL CA:   openssl ca -in {cn}.csr -out cert.pem

Verification:
  openssl req -in {cn}.csr -text -noout -verify
"""
