"""Key Escrow & Recovery API — admin-only key recovery with M-of-N approval."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_auth_context, require_permission, AuthContext
from app.models.key_escrow import KeyEscrow, KeyRecoveryRequest
from app.services.audit import audit_event
from app.services import key_escrow as escrow_svc

router = APIRouter(prefix="/api/v1/key-escrow", tags=["Key Escrow"])


# --- Schemas ---

class RecoveryRequestCreate(BaseModel):
    certificate_serial: str = Field(..., min_length=1)
    justification: str = Field(..., min_length=10, max_length=1000)


class ApprovalAction(BaseModel):
    action: str = Field(..., pattern="^(approve|deny)$")


# --- Endpoints ---

@router.get("/escrowed")
async def list_escrowed_keys(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """List all escrowed keys (admin only)."""
    query = select(KeyEscrow)
    if not auth.is_global_admin:
        query = query.where(KeyEscrow.tenant_id == auth.tenant_id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(KeyEscrow.escrowed_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": [
            {
                "id": e.id,
                "certificate_serial": e.certificate_serial,
                "certificate_cn": e.certificate_cn,
                "profile": e.profile,
                "escrowed_at": e.escrowed_at.isoformat() if e.escrowed_at else None,
                "escrowed_by": e.escrowed_by,
            }
            for e in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/requests")
async def list_recovery_requests(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """List key recovery requests (admin only)."""
    query = select(KeyRecoveryRequest)
    if not auth.is_global_admin:
        query = query.where(KeyRecoveryRequest.tenant_id == auth.tenant_id)
    if status:
        query = query.where(KeyRecoveryRequest.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(KeyRecoveryRequest.requested_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": [_serialize_request(r) for r in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/requests", status_code=201)
async def create_recovery_request(
    body: RecoveryRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Request key recovery (requires justification, triggers M-of-N approval)."""
    try:
        req = await escrow_svc.request_recovery(
            db=db,
            certificate_serial=body.certificate_serial,
            justification=body.justification,
            requested_by=auth.username,
            tenant_id=auth.tenant_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await audit_event(
        db=db, event_type="KEY_RECOVERY_REQUESTED", severity="WARNING", request=request,
        subject_type="certificate", subject_id=body.certificate_serial,
        description=f"Key recovery requested by {auth.username}: {body.justification[:100]}",
    )
    await db.commit()
    await db.refresh(req)
    return _serialize_request(req)


@router.post("/requests/{request_id}/action")
async def action_recovery_request(
    request_id: str,
    body: ApprovalAction,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Approve or deny a key recovery request."""
    try:
        if body.action == "approve":
            req = await escrow_svc.approve_recovery(db, request_id, auth.username)
            event_type = "KEY_RECOVERY_APPROVED"
        else:
            req = await escrow_svc.deny_recovery(db, request_id)
            event_type = "KEY_RECOVERY_DENIED"
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await audit_event(
        db=db, event_type=event_type, severity="WARNING", request=request,
        subject_type="recovery_request", subject_id=request_id,
        description=f"Key recovery {body.action}d by {auth.username}",
    )
    await db.commit()
    await db.refresh(req)
    return _serialize_request(req)


@router.get("/requests/{request_id}/download")
async def download_recovered_key(
    request_id: str,
    token: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Download recovered key (time-limited, requires valid token)."""
    try:
        key_pem = await escrow_svc.download_recovered_key(db, request_id, token)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await audit_event(
        db=db, event_type="KEY_RECOVERY_COMPLETED", severity="CRITICAL", request=request,
        subject_type="recovery_request", subject_id=request_id,
        description=f"Recovered key downloaded by {auth.username}",
    )
    await db.commit()

    return {
        "key_pem": key_pem.decode(),
        "warning": "This key is sensitive. Store securely and rotate if possible.",
    }


@router.get("/policy")
async def get_escrow_policy(
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Get current key escrow policy configuration."""
    from app.core.config import settings
    return {
        "approvals_required": settings.KEY_RECOVERY_APPROVALS_REQUIRED,
        "download_window_hours": 1,
        "escrow_profiles": ["email"],
        "never_escrow_profiles": ["server", "code_sign"],
        "recovery_key_configured": bool(settings.KEY_ESCROW_RECOVERY_KEY),
    }


# --- Helpers ---

def _serialize_request(r: KeyRecoveryRequest) -> dict:
    return {
        "id": r.id,
        "escrow_id": r.escrow_id,
        "certificate_serial": r.certificate_serial,
        "justification": r.justification,
        "requested_by": r.requested_by,
        "requested_at": r.requested_at.isoformat() if r.requested_at else None,
        "approvals": json.loads(r.approvals_json),
        "approvals_required": r.approvals_required,
        "status": r.status,
        "download_expires_at": r.download_expires_at.isoformat() if r.download_expires_at else None,
        "download_token": r.download_token if r.status in ("approved", "completed") else None,
    }
