"""Cross-Certification & Bridge CA endpoints."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cryptography import x509
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_permission, AuthContext
from app.models.ca import CertificateAuthority
from app.models.cross_cert import CrossCertificate
from app.services.crypto_engine import CryptoEngine
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/cross-certs", tags=["Cross-Certification"])
crypto = CryptoEngine()


class CrossSignRequest(BaseModel):
    external_ca_pem: str = Field(..., description="PEM-encoded certificate of the external CA")
    validity_days: int = Field(730, gt=0, le=3650, description="Validity of cross-certificate")
    path_length: int = Field(0, ge=0, le=2)
    name_constraints: dict | None = None
    direction: str = Field("outbound", pattern="^(outbound|inbound)$")


class CrossCertResponse(BaseModel):
    id: str
    issuing_ca_id: str
    issuing_ca_cn: str | None = None
    external_ca_cn: str
    serial: str
    status: str
    direction: str
    path_length: int
    name_constraints_json: str | None
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None = None
    cross_cert_pem: str | None = None


@router.post("/{ca_id}/cross-sign", status_code=201)
async def cross_sign_external_ca(
    ca_id: str,
    body: CrossSignRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),
) -> dict:
    """Cross-sign an external CA's certificate using a local CA.

    This creates a trust bridge: clients trusting the local CA will
    now be able to validate certificates issued by the external CA.
    """
    # Load local CA
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(404, "Local CA not found")
    if not ca.key_blob:
        raise HTTPException(400, "CA has no private key (offline root cannot cross-sign)")

    # Parse external CA certificate
    try:
        external_cert = x509.load_pem_x509_certificate(body.external_ca_pem.encode())
    except Exception:
        raise HTTPException(400, "Invalid PEM certificate for external CA")

    # Verify it's actually a CA certificate
    try:
        bc = external_cert.extensions.get_extension_for_class(x509.BasicConstraints)
        if not bc.value.ca:
            raise HTTPException(400, "External certificate is not a CA (BasicConstraints.ca=False)")
    except x509.ExtensionNotFound:
        raise HTTPException(400, "External certificate has no BasicConstraints extension")

    # Load local CA key
    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = x509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Issue cross-certificate
    cross_cert = crypto.create_cross_certificate(
        external_ca_cert=external_cert,
        signing_ca_key=ca_key,
        signing_ca_cert=ca_cert,
        validity_days=body.validity_days,
        path_length=body.path_length,
        name_constraints=body.name_constraints,
    )

    cross_cert_pem = crypto.export_cert_pem(cross_cert).decode()
    serial = format(cross_cert.serial_number, "x")

    # Extract external CA subject info
    ext_cn = ""
    cn_attrs = external_cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    if cn_attrs:
        ext_cn = cn_attrs[0].value

    ext_subject = {}
    for attr in external_cert.subject:
        ext_subject[attr.oid._name] = attr.value

    # Store
    record = CrossCertificate(
        issuing_ca_id=ca_id,
        external_ca_cn=ext_cn or "Unknown",
        external_ca_subject_json=json.dumps(ext_subject),
        external_ca_cert_pem=body.external_ca_pem,
        cross_cert_pem=cross_cert_pem,
        serial=serial,
        path_length=body.path_length,
        name_constraints_json=json.dumps(body.name_constraints) if body.name_constraints else None,
        status="active",
        direction=body.direction,
        expires_at=cross_cert.not_valid_after_utc,
        tenant_id=auth.tenant_id,
    )
    db.add(record)

    await audit_event(
        db=db,
        event_type="CROSS_CERT_ISSUED",
        severity="INFO",
        request=request,
        subject_type="cross_cert",
        subject_id=record.id,
        detail={"issuing_ca": ca.cn, "external_ca": ext_cn, "direction": body.direction},
        description=f"Cross-certificate issued: {ca.cn} → {ext_cn} ({body.direction})",
    )
    await db.commit()

    return {
        "id": record.id,
        "serial": serial,
        "issuing_ca_cn": ca.cn,
        "external_ca_cn": ext_cn,
        "direction": body.direction,
        "expires_at": record.expires_at.isoformat(),
        "cross_cert_pem": cross_cert_pem,
    }


@router.get("")
async def list_cross_certs(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:read")),
) -> list[CrossCertResponse]:
    """List all cross-certifications (trust bridges)."""
    query = select(CrossCertificate)
    if not auth.is_global_admin:
        query = query.where(CrossCertificate.tenant_id == auth.tenant_id)
    query = query.order_by(CrossCertificate.created_at.desc())

    result = await db.execute(query)
    records = result.scalars().all()

    responses = []
    for r in records:
        # Get issuing CA CN
        ca = await db.get(CertificateAuthority, r.issuing_ca_id)
        responses.append(CrossCertResponse(
            id=r.id,
            issuing_ca_id=r.issuing_ca_id,
            issuing_ca_cn=ca.cn if ca else None,
            external_ca_cn=r.external_ca_cn,
            serial=r.serial,
            status=r.status,
            direction=r.direction,
            path_length=r.path_length,
            name_constraints_json=r.name_constraints_json,
            expires_at=r.expires_at,
            created_at=r.created_at,
            revoked_at=r.revoked_at,
        ))

    return responses


@router.get("/{cross_cert_id}")
async def get_cross_cert(
    cross_cert_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:read")),
) -> CrossCertResponse:
    """Get details of a cross-certificate including PEM."""
    record = await db.get(CrossCertificate, cross_cert_id)
    if not record:
        raise HTTPException(404, "Cross-certificate not found")

    ca = await db.get(CertificateAuthority, record.issuing_ca_id)
    return CrossCertResponse(
        id=record.id,
        issuing_ca_id=record.issuing_ca_id,
        issuing_ca_cn=ca.cn if ca else None,
        external_ca_cn=record.external_ca_cn,
        serial=record.serial,
        status=record.status,
        direction=record.direction,
        path_length=record.path_length,
        name_constraints_json=record.name_constraints_json,
        expires_at=record.expires_at,
        created_at=record.created_at,
        revoked_at=record.revoked_at,
        cross_cert_pem=record.cross_cert_pem,
    )


@router.post("/{cross_cert_id}/revoke")
async def revoke_cross_cert(
    cross_cert_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),
) -> dict:
    """Revoke a cross-certificate (terminate trust bridge)."""
    record = await db.get(CrossCertificate, cross_cert_id)
    if not record:
        raise HTTPException(404, "Cross-certificate not found")
    if record.status == "revoked":
        raise HTTPException(400, "Already revoked")

    record.status = "revoked"
    record.revoked_at = datetime.now(timezone.utc)

    ca = await db.get(CertificateAuthority, record.issuing_ca_id)

    await audit_event(
        db=db,
        event_type="CROSS_CERT_REVOKED",
        severity="WARNING",
        request=request,
        subject_type="cross_cert",
        subject_id=cross_cert_id,
        detail={"issuing_ca": ca.cn if ca else record.issuing_ca_id, "external_ca": record.external_ca_cn},
        description=f"Cross-certificate revoked: trust bridge to {record.external_ca_cn} terminated",
    )
    await db.commit()

    return {"status": "revoked", "id": cross_cert_id, "external_ca_cn": record.external_ca_cn}


@router.get("/{cross_cert_id}/export")
async def export_cross_cert(
    cross_cert_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:read")),
) -> dict:
    """Export cross-certificate PEM and chain for distribution."""
    record = await db.get(CrossCertificate, cross_cert_id)
    if not record:
        raise HTTPException(404, "Cross-certificate not found")

    # Build chain: cross-cert + issuing CA cert
    ca = await db.get(CertificateAuthority, record.issuing_ca_id)
    chain_pem = record.cross_cert_pem
    if ca:
        chain_pem += "\n" + ca.cert_pem

    return {
        "cross_cert_pem": record.cross_cert_pem,
        "external_ca_pem": record.external_ca_cert_pem,
        "chain_pem": chain_pem,
        "issuing_ca_pem": ca.cert_pem if ca else None,
    }
