"""CA management endpoints — create and list Certificate Authorities."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key, require_permission, AuthContext, get_auth_context
from app.models.ca import CertificateAuthority
from app.models.certificate import Certificate
from app.api.v1.schemas import CACreateRequest, CAResponse, CAListResponse
from app.services.crypto_engine import CryptoEngine, SubjectInfo
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/ca", tags=["Certificate Authorities"])
crypto = CryptoEngine()


@router.post("", response_model=CAResponse, status_code=201)
async def create_ca(
    body: CACreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),
) -> CAResponse:
    subject = SubjectInfo(
        cn=body.subject.cn,
        o=body.subject.o,
        ou=body.subject.ou,
        c=body.subject.c,
        st=body.subject.st,
        l=body.subject.l,
    )

    # Validate RSA minimum
    if body.key_algo == "RSA" and body.key_size < 2048:
        raise HTTPException(status_code=422, detail="RSA key size must be at least 2048 bits")

    # Generate keypair
    key = crypto.generate_keypair(body.key_algo, body.key_size)

    if body.parent_ca_id:
        # Intermediate CA
        parent = await db.get(CertificateAuthority, body.parent_ca_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent CA not found")

        parent_key_pem = crypto.decrypt_key_blob(parent.key_blob, settings.CERT_MASTER_KEY)
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography import x509 as cx509

        parent_key = load_pem_private_key(parent_key_pem, password=None)
        parent_cert = cx509.load_pem_x509_certificate(parent.cert_pem.encode())

        cert = crypto.create_intermediate_ca(
            subject=subject,
            key=key,
            parent_ca_key=parent_key,
            parent_ca_cert=parent_cert,
            validity_days=body.validity_days,
            path_length=body.path_length,
            name_constraints=body.name_constraints,
        )
        is_root = False
    else:
        # Root CA
        cert = crypto.create_root_ca(
            subject=subject,
            key=key,
            validity_days=body.validity_days,
            path_length=body.path_length,
        )
        is_root = True

    # Encrypt private key for storage
    key_pem = crypto.export_key_pem(key)
    key_blob = crypto.encrypt_key_blob(key_pem, settings.CERT_MASTER_KEY)
    cert_pem = crypto.export_cert_pem(cert).decode()

    ca = CertificateAuthority(
        cn=body.subject.cn,
        subject_json=json.dumps(body.subject.model_dump()),
        key_algo=body.key_algo,
        key_size=body.key_size,
        cert_pem=cert_pem,
        key_blob=key_blob,
        path_length=body.path_length,
        is_root=is_root,
        parent_ca_id=body.parent_ca_id,
        expires_at=cert.not_valid_after_utc,
        name_constraints_json=json.dumps(body.name_constraints) if body.name_constraints else None,
        policy_oid=body.policy_oid,
        cps_url=body.cps_url,
        tenant_id=auth.tenant_id,
    )
    db.add(ca)

    await audit_event(
        db=db,
        event_type="CA_CREATED",
        severity="INFO",
        request=request,
        subject_type="ca",
        subject_id=ca.id,
        detail={"cn": body.subject.cn, "is_root": is_root, "key_algo": body.key_algo},
        description=f"{'Root' if is_root else 'Intermediate'} CA created: {body.subject.cn}",
    )

    await db.commit()
    await db.refresh(ca)

    return CAResponse(
        id=ca.id,
        cn=ca.cn,
        subject_json=ca.subject_json,
        key_algo=ca.key_algo,
        key_size=ca.key_size,
        is_root=ca.is_root,
        path_length=ca.path_length,
        parent_ca_id=ca.parent_ca_id,
        source=ca.source,
        expires_at=ca.expires_at,
        created_at=ca.created_at,
        cert_pem=ca.cert_pem,
        has_key=ca.key_blob is not None,
    )


@router.get("", response_model=list[CAListResponse])
async def list_cas(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> list[CAListResponse]:
    query = select(CertificateAuthority)
    if not auth.is_global_admin:
        query = query.where(CertificateAuthority.tenant_id == auth.tenant_id)
    result = await db.execute(query)
    cas = result.scalars().all()

    responses = []
    for ca in cas:
        # Count children
        child_q = await db.execute(
            select(func.count()).where(CertificateAuthority.parent_ca_id == ca.id)
        )
        child_count = child_q.scalar() or 0

        # Count issued certificates
        cert_q = await db.execute(
            select(func.count()).where(Certificate.signing_ca_id == ca.id)
        )
        cert_count = cert_q.scalar() or 0

        responses.append(CAListResponse(
            id=ca.id,
            cn=ca.cn,
            key_algo=ca.key_algo,
            key_size=ca.key_size,
            is_root=ca.is_root,
            parent_ca_id=ca.parent_ca_id,
            expires_at=ca.expires_at,
            created_at=ca.created_at,
            child_count=child_count,
            cert_count=cert_count,
            has_key=ca.key_blob is not None,
            source=ca.source,
            name_constraints=json.loads(ca.name_constraints_json) if ca.name_constraints_json else None,
        ))

    return responses


@router.get("/{ca_id}/check-constraints")
async def check_name_constraints(
    ca_id: str,
    cn: str = "",
    sans: str = "",
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Pre-flight check: validate CN + SANs against CA name constraints.
    
    Query params:
        cn: Common Name
        sans: Comma-separated list of type:value pairs (e.g. dns:foo.com,ip:127.0.0.1)
    """
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")

    if not ca.name_constraints_json:
        return {"permitted": True, "violations": [], "constraints": None}

    constraints = json.loads(ca.name_constraints_json)
    permitted = constraints.get("permitted", [])
    excluded = constraints.get("excluded", [])

    # Parse SANs from query string
    dns_names = []
    if sans:
        for entry in sans.split(","):
            entry = entry.strip()
            if ":" in entry:
                t, v = entry.split(":", 1)
                if t == "dns":
                    dns_names.append(v)
            else:
                dns_names.append(entry)
    if cn and cn not in dns_names:
        dns_names.append(cn)

    violations = []
    for name in dns_names:
        for exc in excluded:
            if name == exc or name.endswith(exc if exc.startswith(".") else f".{exc}"):
                violations.append(f"'{name}' is excluded by constraint: {exc}")
                break
        if permitted:
            matched = any(
                name == p or name.endswith(p if p.startswith(".") else f".{p}")
                for p in permitted
            )
            if not matched:
                violations.append(f"'{name}' not within permitted names: {permitted}")

    return {
        "permitted": len(violations) == 0,
        "violations": violations,
        "constraints": constraints,
    }


@router.get("/{ca_id}", response_model=CAResponse)
async def get_ca(
    ca_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> CAResponse:
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")

    return CAResponse(
        id=ca.id,
        cn=ca.cn,
        subject_json=ca.subject_json,
        key_algo=ca.key_algo,
        key_size=ca.key_size,
        is_root=ca.is_root,
        path_length=ca.path_length,
        parent_ca_id=ca.parent_ca_id,
        source=ca.source,
        expires_at=ca.expires_at,
        created_at=ca.created_at,
        cert_pem=ca.cert_pem,
        has_key=ca.key_blob is not None,
    )


class SerialFormatRequest(BaseModel):
    format: str = Field(..., pattern="^(random|sequential|timestamp)$")
    prefix: str = Field("", max_length=16)


@router.put("/{ca_id}/serial-format")
async def set_serial_format(
    ca_id: str,
    body: SerialFormatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),
) -> dict:
    """Configure the serial number format for a CA (admin only)."""
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")

    from app.services.serial_allocator import configure_serial_format
    counter = await configure_serial_format(ca_id, body.format, body.prefix, db)

    ca.serial_format = body.format

    await audit_event(
        db=db,
        event_type="CA_UPDATED",
        severity="INFO",
        request=request,
        subject_type="ca",
        subject_id=ca_id,
        detail={"serial_format": body.format, "prefix": body.prefix},
        description=f"Serial format set to '{body.format}' for CA '{ca.cn}'",
    )
    await db.commit()

    return {
        "ca_id": ca_id,
        "serial_format": body.format,
        "prefix": body.prefix,
        "next_value": counter.next_value,
    }


@router.get("/{ca_id}/serial-format")
async def get_serial_format(
    ca_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Get the serial number format configuration for a CA."""
    ca = await db.get(CertificateAuthority, ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="CA not found")

    from app.models.serial_counter import SerialCounter
    result = await db.execute(
        select(SerialCounter).where(SerialCounter.ca_id == ca_id)
    )
    counter = result.scalar_one_or_none()

    if not counter:
        return {"ca_id": ca_id, "serial_format": "random", "prefix": "", "next_value": None}

    return {
        "ca_id": ca_id,
        "serial_format": counter.format,
        "prefix": counter.prefix,
        "next_value": counter.next_value,
    }
