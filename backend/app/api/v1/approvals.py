"""Approval workflow — pending certificate requests that require admin review."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_permission, require_api_key, AuthContext
from app.models.pending_request import PendingRequest
from app.models.ca import CertificateAuthority
from app.models.certificate import Certificate
from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/approvals", tags=["Approvals"])
crypto = CryptoEngine()


class ReviewAction(BaseModel):
    action: str  # approve, reject
    note: str = ""


@router.get("")
async def list_pending_requests(
    status_filter: str = "pending",
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("audit:read")),
) -> list[dict]:
    """List pending certificate requests."""
    query = select(PendingRequest).order_by(PendingRequest.created_at.desc())
    if status_filter != "all":
        query = query.where(PendingRequest.status == status_filter)
    result = await db.execute(query)
    requests = result.scalars().all()
    return [_serialize(r) for r in requests]


@router.post("/{request_id}/review")
async def review_request(
    request_id: str,
    body: ReviewAction,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("ca:create")),  # admin only
) -> dict:
    """Approve or reject a pending certificate request."""
    pending = await db.get(PendingRequest, request_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Request not found")
    if pending.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request already {pending.status}")

    if body.action == "reject":
        pending.status = "rejected"
        pending.reviewed_by = auth.username
        pending.review_note = body.note
        pending.reviewed_at = datetime.now(timezone.utc)
        await audit_event(
            db=db, event_type="CERT_REQUEST_REJECTED", severity="WARNING",
            request=request, subject_type="pending_request", subject_id=request_id,
            detail={"note": body.note},
            description=f"Certificate request rejected by {auth.username}",
        )
        await db.commit()
        return {"status": "rejected", "request_id": request_id}

    elif body.action == "approve":
        # Issue the certificate from the stored request
        req_data = json.loads(pending.request_json)

        ca = await db.get(CertificateAuthority, req_data["signing_ca_id"])
        if not ca:
            raise HTTPException(status_code=404, detail="Signing CA no longer exists")

        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography import x509 as cx509

        ca_key_pem = crypto.decrypt_key_blob(ca.key_blob, settings.CERT_MASTER_KEY)
        ca_key = load_pem_private_key(ca_key_pem, password=None)
        ca_cert = cx509.load_pem_x509_certificate(ca.cert_pem.encode())

        subj = req_data.get("subject", {})
        subject = SubjectInfo(
            cn=subj.get("cn", ""), o=subj.get("o", ""), ou=subj.get("ou", ""),
            c=subj.get("c", ""), st=subj.get("st", ""), l=subj.get("l", ""),
        )
        san_list = [SANEntry(type=s["type"], value=s["value"]) for s in req_data.get("san", [])]

        key = crypto.generate_keypair(req_data.get("key_algo", "RSA"), req_data.get("key_size", 2048))

        cert = crypto.issue_certificate(
            profile=req_data.get("profile", "server"),
            subject=subject,
            san_list=san_list,
            key=key,
            signing_ca_key=ca_key,
            signing_ca_cert=ca_cert,
            validity_days=req_data.get("validity_days", 365),
            signing_ca_id=req_data["signing_ca_id"],
            pki_base_url=settings.PKI_BASE_URL,
            policy_oid=ca.policy_oid,
            cps_url=ca.cps_url,
        )

        cert_pem_bytes = crypto.export_cert_pem(cert)
        chain_pem = cert_pem_bytes.decode() + ca.cert_pem
        key_blob = crypto.encrypt_key_blob(crypto.export_key_pem(key), settings.CERT_MASTER_KEY)
        serial_hex = format(cert.serial_number, "x")

        certificate = Certificate(
            serial=serial_hex,
            profile=req_data.get("profile", "server"),
            subject_json=json.dumps(subj),
            san_json=json.dumps(req_data.get("san", [])),
            key_algo=req_data.get("key_algo", "RSA"),
            key_size=req_data.get("key_size", 2048),
            cert_pem=cert_pem_bytes.decode(),
            key_blob=key_blob,
            chain_pem=chain_pem,
            signing_ca_id=req_data["signing_ca_id"],
            status="valid",
            expires_at=cert.not_valid_after_utc,
            tags=json.dumps(req_data.get("tags", [])),
        )
        db.add(certificate)

        pending.status = "approved"
        pending.reviewed_by = auth.username
        pending.review_note = body.note
        pending.reviewed_at = datetime.now(timezone.utc)

        await audit_event(
            db=db, event_type="CERT_REQUEST_APPROVED", severity="INFO",
            request=request, subject_type="cert", subject_id=serial_hex,
            detail={"request_id": request_id, "approved_by": auth.username},
            description=f"Certificate request approved by {auth.username}: {subj.get('cn', '')}",
        )
        await db.commit()
        return {"status": "approved", "request_id": request_id, "serial": serial_hex}

    else:
        raise HTTPException(status_code=422, detail="Action must be 'approve' or 'reject'")


def _serialize(r: PendingRequest) -> dict:
    req_data = json.loads(r.request_json) if r.request_json else {}
    subj = req_data.get("subject", {})
    return {
        "id": r.id,
        "request_type": r.request_type,
        "cn": subj.get("cn", ""),
        "profile": req_data.get("profile", ""),
        "key_algo": req_data.get("key_algo", ""),
        "validity_days": req_data.get("validity_days", 0),
        "requested_by": r.requested_by,
        "status": r.status,
        "reviewed_by": r.reviewed_by,
        "review_note": r.review_note,
        "template_name": r.template_name,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
    }
