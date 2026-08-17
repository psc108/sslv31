"""Certificate endpoints — issue, list, detail, and revoke."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key, require_permission, AuthContext, get_auth_context
from app.models.ca import CertificateAuthority
from app.models.certificate import Certificate
from app.api.v1.schemas import CertCreateRequest, CertResponse, CertListResponse, PaginatedResponse
from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry
from app.services.chain_builder import build_chain, assemble_chain_pem
from app.services.serial_allocator import allocate_serial_safe
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/cert", tags=["Certificates"])
crypto = CryptoEngine()


class CertTagsUpdate(BaseModel):
    tags: list[str]


class RevokeRequest(BaseModel):
    reason: str = Field(
        "unspecified",
        pattern="^(unspecified|key_compromise|ca_compromise|affiliation_changed|superseded|cessation_of_operation|privilege_withdrawn)$",
    )


@router.post("", response_model=CertResponse, status_code=201)
async def issue_certificate(
    body: CertCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:issue")),
) -> CertResponse:
    # Validate against MAX_CERT_DAYS
    if body.validity_days > settings.MAX_CERT_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Validity cannot exceed {settings.MAX_CERT_DAYS} days for leaf certificates",
        )

    # Server profile requires SAN
    if body.profile == "server" and not body.san:
        raise HTTPException(
            status_code=422,
            detail="Server certificates require at least one SAN entry (RFC 2818)",
        )

    # RSA minimum
    if body.key_algo == "RSA" and body.key_size < 2048:
        raise HTTPException(status_code=422, detail="RSA key size must be at least 2048 bits")

    # Template enforcement
    if body.template:
        from app.api.v1.templates import enforce_template
        await enforce_template(
            template_name=body.template,
            key_algo=body.key_algo,
            key_size=body.key_size,
            validity_days=body.validity_days,
            san_list=[s.model_dump() for s in body.san],
            subject_cn=body.subject.cn,
            subject_o=body.subject.o,
            db=db,
        )
        # Check if template requires approval (non-admin users get queued)
        from app.models.template import CertificateTemplate
        tmpl_result = await db.execute(
            select(CertificateTemplate).where(CertificateTemplate.name == body.template)
        )
        tmpl = tmpl_result.scalar_one_or_none()
        if tmpl and tmpl.require_approval and auth.role != "admin":
            from app.models.pending_request import PendingRequest
            pending = PendingRequest(
                request_type="cert",
                request_json=json.dumps(body.model_dump()),
                requested_by=auth.username,
                template_name=body.template,
            )
            db.add(pending)
            await audit_event(
                db=db, event_type="CERT_REQUEST_PENDING", severity="INFO",
                request=request, subject_type="pending_request", subject_id=pending.id,
                description=f"Certificate request queued for approval: {body.subject.cn}",
            )
            await db.commit()
            raise HTTPException(
                status_code=202,
                detail={"status": "pending_approval", "request_id": pending.id,
                        "message": "This template requires admin approval before issuance."},
            )

    # Load signing CA
    ca = await db.get(CertificateAuthority, body.signing_ca_id)
    if not ca:
        raise HTTPException(status_code=404, detail="Signing CA not found")

    # Enforce name constraints from CA
    if ca.name_constraints_json:
        _enforce_name_constraints(json.loads(ca.name_constraints_json), body.san, body.subject.cn)

    # Decrypt CA key
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography import x509 as cx509

    ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

    # Generate leaf keypair
    key = crypto.generate_keypair(body.key_algo, body.key_size)

    # Build subject and SAN
    subject = SubjectInfo(
        cn=body.subject.cn,
        o=body.subject.o,
        ou=body.subject.ou,
        c=body.subject.c,
        st=body.subject.st,
        l=body.subject.l,
    )
    san_list = [SANEntry(type=s.type, value=s.value) for s in body.san]

    # Allocate serial number (database-backed, collision-safe)
    serial_int = await allocate_serial_safe(body.signing_ca_id, db)

    # Issue certificate
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
        policy_oid=ca.policy_oid,
        cps_url=ca.cps_url,
        serial_number=serial_int,
    )

    # Build full chain PEM (leaf + all CA certs up to root)
    cert_pem_bytes = crypto.export_cert_pem(cert)
    ca_chain = await build_chain(body.signing_ca_id, db)
    chain_pem = assemble_chain_pem(cert_pem_bytes.decode(), ca_chain, mode="full")

    # Encrypt private key for storage
    key_pem = crypto.export_key_pem(key, passphrase=body.key_password)
    key_blob = crypto.encrypt_key_blob(
        crypto.export_key_pem(key),  # store unencrypted internally; passphrase applied on export
        settings.CERT_MASTER_KEY,
    )

    # Serial from certificate
    serial_hex = format(cert.serial_number, "x")

    certificate = Certificate(
        serial=serial_hex,
        profile=body.profile,
        subject_json=json.dumps(body.subject.model_dump()),
        san_json=json.dumps([s.model_dump() for s in body.san]),
        key_algo=body.key_algo,
        key_size=body.key_size,
        cert_pem=cert_pem_bytes.decode(),
        key_blob=key_blob,
        chain_pem=chain_pem,
        signing_ca_id=body.signing_ca_id,
        status="valid",
        expires_at=cert.not_valid_after_utc,
        tags=json.dumps(body.tags),
        tenant_id=auth.tenant_id,
    )
    db.add(certificate)

    await audit_event(
        db=db,
        event_type="CERT_ISSUED",
        severity="INFO",
        request=request,
        subject_type="cert",
        subject_id=serial_hex,
        detail={
            "profile": body.profile,
            "cn": body.subject.cn,
            "san": [s.model_dump() for s in body.san],
            "key_algo": body.key_algo,
            "validity_days": body.validity_days,
        },
        description=f"Certificate issued: {body.subject.cn} ({body.profile})",
    )

    # Submit to Certificate Transparency log
    from app.services.ct_service import submit_to_ct_log
    try:
        await submit_to_ct_log(
            db=db,
            cert_pem=cert_pem_bytes.decode(),
            cert_serial=serial_hex,
            issuer_ca_id=body.signing_ca_id,
            tenant_id=auth.tenant_id,
        )
    except Exception:
        pass  # CT log failure should not block issuance

    # Key escrow (if template or profile requires it)
    try:
        from app.services.key_escrow import should_escrow, escrow_key as do_escrow
        template_escrow = None
        if body.template:
            from app.models.template import CertificateTemplate
            t_res = await db.execute(
                select(CertificateTemplate).where(CertificateTemplate.name == body.template)
            )
            t_obj = t_res.scalar_one_or_none()
            if t_obj:
                template_escrow = t_obj.escrow_key
        if should_escrow(body.profile, template_escrow):
            await do_escrow(
                db=db,
                certificate_serial=serial_hex,
                certificate_cn=body.subject.cn,
                profile=body.profile,
                key_pem=crypto.export_key_pem(key),
                escrowed_by=auth.username,
                tenant_id=auth.tenant_id,
            )
    except Exception:
        pass  # Escrow failure should not block issuance

    # Email notification
    try:
        from app.services.notification_service import notify_event
        await notify_event(
            db, "cert_issued", tenant_id=auth.tenant_id,
            ca_id=body.signing_ca_id,
            cn=body.subject.cn, serial=serial_hex,
            profile=body.profile, expires_at=str(cert.not_valid_after_utc),
        )
    except Exception:
        pass

    await db.commit()
    await db.refresh(certificate)

    return CertResponse(
        id=certificate.id,
        serial=certificate.serial,
        profile=certificate.profile,
        subject_json=certificate.subject_json,
        san_json=certificate.san_json,
        key_algo=certificate.key_algo,
        key_size=certificate.key_size,
        signing_ca_id=certificate.signing_ca_id,
        status=certificate.status,
        expires_at=certificate.expires_at,
        created_at=certificate.created_at,
        revoked_at=certificate.revoked_at,
        cert_pem=certificate.cert_pem,
        chain_pem=certificate.chain_pem,
    )


@router.get("")
async def list_certificates(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    profile: str | None = None,
    status: str | None = None,
    signing_ca_id: str | None = None,
    search: str | None = None,
    tag: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> PaginatedResponse:
    query = select(Certificate)

    # Tenant scoping
    if not auth.is_global_admin:
        query = query.where(Certificate.tenant_id == auth.tenant_id)

    if profile:
        query = query.where(Certificate.profile == profile)
    if status:
        query = query.where(Certificate.status == status)
    if signing_ca_id:
        query = query.where(Certificate.signing_ca_id == signing_ca_id)
    if search:
        query = query.where(
            Certificate.subject_json.contains(search) |
            Certificate.san_json.contains(search) |
            Certificate.serial.contains(search) |
            Certificate.tags.contains(search)
        )
    if tag:
        query = query.where(Certificate.tags.contains(tag))

    # Count total
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    query = query.order_by(Certificate.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    certs = result.scalars().all()

    items = [
        CertListResponse(
            id=c.id,
            serial=c.serial,
            profile=c.profile,
            subject_json=c.subject_json,
            san_json=c.san_json,
            key_algo=c.key_algo,
            key_size=c.key_size,
            signing_ca_id=c.signing_ca_id,
            status=c.status,
            expires_at=c.expires_at,
            created_at=c.created_at,
            revoked_at=c.revoked_at,
            expiry_warning=c.expiry_warning,
            tags=json.loads(c.tags) if c.tags else [],
            auto_renew=c.auto_renew or False,
            renewed_from=c.renewed_from,
            renewed_to=c.renewed_to,
        )
        for c in certs
    ]

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{serial}", response_model=CertResponse)
async def get_certificate(
    serial: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> CertResponse:
    result = await db.execute(select(Certificate).where(Certificate.serial == serial))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    return CertResponse(
        id=cert.id,
        serial=cert.serial,
        profile=cert.profile,
        subject_json=cert.subject_json,
        san_json=cert.san_json,
        key_algo=cert.key_algo,
        key_size=cert.key_size,
        signing_ca_id=cert.signing_ca_id or "",
        status=cert.status,
        expires_at=cert.expires_at,
        created_at=cert.created_at,
        revoked_at=cert.revoked_at,
        cert_pem=cert.cert_pem,
        chain_pem=cert.chain_pem,
    )


@router.get("/{serial}/inspect")
async def inspect_certificate(
    serial: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Return decoded certificate details: subject, SANs, extensions, fingerprints, issuer chain."""
    result = await db.execute(select(Certificate).where(Certificate.serial == serial))
    cert_record = result.scalar_one_or_none()
    if not cert_record:
        raise HTTPException(status_code=404, detail="Certificate not found")

    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes

    cert_obj = cx509.load_pem_x509_certificate(cert_record.cert_pem.encode())

    # Subject
    subject = {}
    for attr in cert_obj.subject:
        subject[attr.oid._name] = attr.value

    # Issuer
    issuer = {}
    for attr in cert_obj.issuer:
        issuer[attr.oid._name] = attr.value

    # SANs
    sans = []
    try:
        san_ext = cert_obj.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        for dns in san_ext.value.get_values_for_type(cx509.DNSName):
            sans.append({"type": "dns", "value": dns})
        for ip in san_ext.value.get_values_for_type(cx509.IPAddress):
            sans.append({"type": "ip", "value": str(ip)})
        for email in san_ext.value.get_values_for_type(cx509.RFC822Name):
            sans.append({"type": "email", "value": email})
        for uri in san_ext.value.get_values_for_type(cx509.UniformResourceIdentifier):
            sans.append({"type": "uri", "value": uri})
    except cx509.ExtensionNotFound:
        pass

    # Extensions
    extensions = []
    for ext in cert_obj.extensions:
        extensions.append({
            "oid": ext.oid.dotted_string,
            "name": ext.oid._name,
            "critical": ext.critical,
            "value": str(ext.value),
        })

    # Fingerprints
    sha256_fp = cert_obj.fingerprint(hashes.SHA256()).hex()
    sha1_fp = cert_obj.fingerprint(hashes.SHA1()).hex()

    # Validity
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    days_remaining = (cert_obj.not_valid_after_utc - now).days

    return {
        "serial": serial,
        "serial_decimal": str(cert_obj.serial_number),
        "subject": subject,
        "subject_rfc4514": cert_obj.subject.rfc4514_string(),
        "issuer": issuer,
        "issuer_rfc4514": cert_obj.issuer.rfc4514_string(),
        "san": sans,
        "not_valid_before": cert_obj.not_valid_before_utc.isoformat(),
        "not_valid_after": cert_obj.not_valid_after_utc.isoformat(),
        "days_remaining": days_remaining,
        "key_algo": cert_record.key_algo,
        "key_size": cert_record.key_size,
        "signature_algorithm": cert_obj.signature_algorithm_oid._name,
        "extensions": extensions,
        "fingerprints": {
            "sha256": sha256_fp,
            "sha1": sha1_fp,
        },
        "profile": cert_record.profile,
        "status": cert_record.status,
        "pem": cert_record.cert_pem,
        "tags": json.loads(cert_record.tags) if cert_record.tags else [],
    }


@router.delete("/{serial}", status_code=200)
async def revoke_certificate(
    serial: str,
    request: Request,
    body: RevokeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("cert:revoke")),
) -> dict[str, str]:
    result = await db.execute(select(Certificate).where(Certificate.serial == serial))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    if cert.status == "revoked":
        raise HTTPException(status_code=409, detail="Certificate already revoked")

    reason = body.reason if body else "unspecified"
    cert.status = "revoked"
    cert.revoked_at = datetime.now(timezone.utc)
    cert.revocation_reason = reason

    await audit_event(
        db=db,
        event_type="CERT_REVOKED",
        severity="WARNING",
        request=request,
        subject_type="cert",
        subject_id=serial,
        detail={"reason": reason},
        description=f"Certificate revoked: {serial} (reason: {reason})",
    )

    await db.commit()

    import logging
    logging.getLogger(__name__).info(
        f"CRL update: certificate {serial} revoked under CA {cert.signing_ca_id}"
    )

    return {"status": "revoked", "serial": serial, "reason": reason}


@router.patch("/{serial}/tags", status_code=200)
async def update_certificate_tags(
    serial: str,
    body: CertTagsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Update tags/labels on a certificate."""
    result = await db.execute(select(Certificate).where(Certificate.serial == serial))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    # Normalize: lowercase, strip whitespace, deduplicate
    clean_tags = list(set(t.strip().lower() for t in body.tags if t.strip()))
    cert.tags = json.dumps(clean_tags)

    await db.commit()
    return {"serial": serial, "tags": clean_tags}


def _enforce_name_constraints(constraints: dict, san_list: list, cn: str) -> None:
    """Reject certificate if SANs or CN violate the signing CA's name constraints."""
    permitted = constraints.get("permitted", [])
    excluded = constraints.get("excluded", [])

    # Collect all DNS names to check (CN + DNS SANs)
    dns_names = [s.value for s in san_list if s.type == "dns"]
    if cn and not any(cn == d for d in dns_names):
        dns_names.append(cn)

    errors = []
    for name in dns_names:
        # Check excluded first
        for exc in excluded:
            if name == exc or name.endswith(exc if exc.startswith(".") else f".{exc}"):
                errors.append(f"'{name}' is excluded by CA name constraint: {exc}")
                break
        # Check permitted (if specified, name must match at least one)
        if permitted:
            matched = False
            for perm in permitted:
                if name == perm or name.endswith(perm if perm.startswith(".") else f".{perm}"):
                    matched = True
                    break
            if not matched:
                errors.append(f"'{name}' not within CA permitted names: {permitted}")

    if errors:
        raise HTTPException(status_code=422, detail={"name_constraint_violations": errors})
