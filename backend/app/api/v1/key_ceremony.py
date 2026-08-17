"""CA Key Ceremony & Offline Root endpoints.

Supports:
- Importing external root CA (cert only, no key)
- Temporary signing sessions (key held in memory, never persisted)
- Signing intermediate CAs during an active session
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_permission, AuthContext
from app.models.ca import CertificateAuthority
from app.services.audit import audit_event
from app.services.crypto_engine import CryptoEngine, SubjectInfo
from app.services.signing_session import session_manager

router = APIRouter(prefix="/api/v1/ca", tags=["CA Key Ceremony"])
crypto = CryptoEngine()


# --- Schemas ---

class CAImportRequest(BaseModel):
    cert_pem: str = Field(..., description="PEM-encoded CA certificate (no key)")


class SigningSessionStartRequest(BaseModel):
    key_pem: str = Field(..., description="PEM-encoded private key (temporary upload)")
    key_password: str | None = Field(None, description="Password for encrypted key")
    timeout_minutes: int = Field(15, ge=1, le=60, description="Session timeout (1-60 min)")


class SessionSignIntermediateRequest(BaseModel):
    subject_cn: str = Field(..., min_length=1, max_length=255)
    subject_o: str = ""
    subject_ou: str = ""
    subject_c: str = Field("", max_length=2)
    subject_st: str = ""
    subject_l: str = ""
    key_algo: str = Field("RSA", pattern="^(RSA|ECDSA|Ed25519)$")
    key_size: int = Field(4096)
    validity_days: int = Field(3650, gt=0, le=7300)
    path_length: int = Field(0, ge=0, le=3)
    name_constraints: dict | None = None


# --- Import External Root CA ---

@router.post("/import", status_code=201)
async def import_ca(
    body: CAImportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),
) -> dict:
    """Import an external root CA certificate without its private key.

    The CA can be used as a trust anchor for chain building but cannot
    sign certificates directly. Use a signing session to temporarily
    upload the key for intermediate CA signing.
    """
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519

    try:
        cert = cx509.load_pem_x509_certificate(body.cert_pem.encode())
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid PEM certificate: {e}")

    # Must be a CA certificate
    try:
        bc = cert.extensions.get_extension_for_class(cx509.BasicConstraints)
        if not bc.value.ca:
            raise HTTPException(status_code=422, detail="Certificate is not a CA (BasicConstraints.ca=False)")
        path_length = bc.value.path_length if bc.value.path_length is not None else 0
    except cx509.ExtensionNotFound:
        raise HTTPException(status_code=422, detail="Certificate missing BasicConstraints extension")

    # Determine key algo and size
    pub_key = cert.public_key()
    if isinstance(pub_key, rsa.RSAPublicKey):
        key_algo = "RSA"
        key_size = pub_key.key_size
    elif isinstance(pub_key, ec.EllipticCurvePublicKey):
        key_algo = "ECDSA"
        key_size = pub_key.key_size
    elif isinstance(pub_key, ed25519.Ed25519PublicKey):
        key_algo = "Ed25519"
        key_size = 256
    else:
        key_algo = "Unknown"
        key_size = 0

    # Extract CN
    cn_attrs = cert.subject.get_attributes_for_oid(cx509.oid.NameOID.COMMON_NAME)
    cn = cn_attrs[0].value if cn_attrs else "Imported CA"

    # Check if self-signed (root)
    is_root = cert.issuer == cert.subject

    # Build subject JSON
    subject_dict = {"cn": cn}
    for oid, field in [
        (cx509.oid.NameOID.ORGANIZATION_NAME, "o"),
        (cx509.oid.NameOID.ORGANIZATIONAL_UNIT_NAME, "ou"),
        (cx509.oid.NameOID.COUNTRY_NAME, "c"),
        (cx509.oid.NameOID.STATE_OR_PROVINCE_NAME, "st"),
        (cx509.oid.NameOID.LOCALITY_NAME, "l"),
    ]:
        attrs = cert.subject.get_attributes_for_oid(oid)
        subject_dict[field] = attrs[0].value if attrs else ""

    ca = CertificateAuthority(
        cn=cn,
        subject_json=json.dumps(subject_dict),
        key_algo=key_algo,
        key_size=key_size,
        cert_pem=body.cert_pem.strip(),
        key_blob=None,  # No key — offline root
        path_length=path_length,
        is_root=is_root,
        parent_ca_id=None,
        expires_at=cert.not_valid_after_utc,
        source="imported",
    )
    db.add(ca)

    await audit_event(
        db=db,
        event_type="KEY_CEREMONY",
        severity="INFO",
        request=request,
        subject_type="ca",
        subject_id=ca.id,
        detail={"action": "import", "cn": cn, "has_key": False, "is_root": is_root},
        description=f"External CA imported (offline root): {cn}",
    )

    await db.commit()
    await db.refresh(ca)

    return {
        "id": ca.id,
        "cn": ca.cn,
        "is_root": is_root,
        "has_key": False,
        "key_algo": key_algo,
        "key_size": key_size,
        "path_length": path_length,
        "expires_at": ca.expires_at.isoformat(),
        "message": "CA imported without private key. Use signing session to sign intermediates.",
    }


# --- Signing Sessions ---

@router.post("/{ca_id}/signing-session")
async def start_signing_session(
    ca_id: str,
    body: SigningSessionStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),
) -> dict:
    """Start a temporary signing session by uploading the CA private key.

    The key is held in memory only and never written to disk or database.
    Session expires after timeout_minutes (default 15, max 60).
    """
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")

    # Validate key matches CA certificate
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    try:
        pwd = body.key_password.encode() if body.key_password else None
        key = load_pem_private_key(body.key_pem.encode(), password=pwd)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to load private key: {e}")

    # Verify key matches certificate public key
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    cert_pub = ca_cert.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    key_pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    if cert_pub != key_pub:
        raise HTTPException(status_code=422, detail="Private key does not match CA certificate public key")

    timeout = body.timeout_minutes or settings.SIGNING_SESSION_TIMEOUT_MINUTES
    session = session_manager.start_session(
        ca_id=ca_id,
        key_pem=body.key_pem.encode(),
        key_password=body.key_password,
        timeout_minutes=timeout,
        username=auth.username,
    )

    await audit_event(
        db=db,
        event_type="CA_SIGNING_SESSION_START",
        severity="WARN",
        request=request,
        subject_type="ca",
        subject_id=ca_id,
        detail={"timeout_minutes": timeout, "ca_cn": ca.cn},
        description=f"Signing session started for CA '{ca.cn}' by {auth.username} ({timeout}min timeout)",
    )
    await db.commit()

    return {
        "status": "active",
        "ca_id": ca_id,
        "ca_cn": ca.cn,
        "started_by": auth.username,
        "timeout_minutes": timeout,
        "expires_at": session.expires_at.isoformat(),
    }


@router.delete("/{ca_id}/signing-session")
async def end_signing_session(
    ca_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),
) -> dict:
    """End a signing session, removing the key from memory immediately."""
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")

    ended = session_manager.end_session(ca_id)
    if not ended:
        raise HTTPException(status_code=404, detail="No active signing session for this CA")

    await audit_event(
        db=db,
        event_type="CA_SIGNING_SESSION_END",
        severity="INFO",
        request=request,
        subject_type="ca",
        subject_id=ca_id,
        detail={"ca_cn": ca.cn, "ended_by": auth.username},
        description=f"Signing session ended for CA '{ca.cn}' by {auth.username}",
    )
    await db.commit()

    return {"status": "ended", "ca_id": ca_id, "ca_cn": ca.cn}


@router.get("/{ca_id}/signing-session")
async def get_signing_session_status(
    ca_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),
) -> dict:
    """Check if a signing session is active for a CA."""
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")

    session = session_manager.get_session(ca_id)
    if not session:
        return {"status": "inactive", "ca_id": ca_id}

    now = datetime.now(timezone.utc)
    return {
        "status": "active",
        "ca_id": ca_id,
        "ca_cn": ca.cn,
        "started_by": session.started_by,
        "started_at": session.started_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "remaining_seconds": int((session.expires_at - now).total_seconds()),
    }


@router.post("/{ca_id}/signing-session/sign-intermediate", status_code=201)
async def sign_intermediate_with_session(
    ca_id: str,
    body: SessionSignIntermediateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),
) -> dict:
    """Sign a new intermediate CA using the active signing session key.

    The parent CA's key must be loaded via a signing session. The new
    intermediate CA's key is generated server-side and stored encrypted.
    """
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")

    # Get active session
    session = session_manager.get_session(ca_id)
    if not session:
        raise HTTPException(
            status_code=409,
            detail="No active signing session. Start one with POST /ca/{id}/signing-session",
        )

    from cryptography import x509 as cx509

    parent_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())
    parent_key = session.key

    # Generate new intermediate key
    subject = SubjectInfo(
        cn=body.subject_cn,
        o=body.subject_o,
        ou=body.subject_ou,
        c=body.subject_c,
        st=body.subject_st,
        l=body.subject_l,
    )

    if body.key_algo == "RSA" and body.key_size < 2048:
        raise HTTPException(status_code=422, detail="RSA key size must be at least 2048 bits")

    int_key = crypto.generate_keypair(body.key_algo, body.key_size)
    int_cert = crypto.create_intermediate_ca(
        subject=subject,
        key=int_key,
        parent_ca_key=parent_key,
        parent_ca_cert=parent_cert,
        validity_days=body.validity_days,
        path_length=body.path_length,
        name_constraints=body.name_constraints,
    )

    # Store intermediate CA with its key encrypted
    key_pem = crypto.export_key_pem(int_key)
    key_blob = crypto.encrypt_key_blob(key_pem, settings.CERT_MASTER_KEY)
    cert_pem = crypto.export_cert_pem(int_cert).decode()

    subject_dict = {
        "cn": body.subject_cn, "o": body.subject_o, "ou": body.subject_ou,
        "c": body.subject_c, "st": body.subject_st, "l": body.subject_l,
    }

    int_ca = CertificateAuthority(
        cn=body.subject_cn,
        subject_json=json.dumps(subject_dict),
        key_algo=body.key_algo,
        key_size=body.key_size,
        cert_pem=cert_pem,
        key_blob=key_blob,
        path_length=body.path_length,
        is_root=False,
        parent_ca_id=ca_id,
        expires_at=int_cert.not_valid_after_utc,
        source="ceremony",
    )
    db.add(int_ca)

    await audit_event(
        db=db,
        event_type="KEY_CEREMONY",
        severity="WARN",
        request=request,
        subject_type="ca",
        subject_id=int_ca.id,
        detail={
            "action": "sign_intermediate",
            "parent_ca_id": ca_id,
            "parent_cn": ca.cn,
            "intermediate_cn": body.subject_cn,
            "key_algo": body.key_algo,
            "validity_days": body.validity_days,
            "signed_by": auth.username,
        },
        description=f"Key ceremony: intermediate CA '{body.subject_cn}' signed by offline root '{ca.cn}'",
    )

    await db.commit()
    await db.refresh(int_ca)

    return {
        "id": int_ca.id,
        "cn": int_ca.cn,
        "is_root": False,
        "has_key": True,
        "parent_ca_id": ca_id,
        "key_algo": body.key_algo,
        "key_size": body.key_size,
        "path_length": body.path_length,
        "expires_at": int_ca.expires_at.isoformat(),
        "cert_pem": cert_pem,
    }
