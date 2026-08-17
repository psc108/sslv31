"""Scoped API key management — create, list, revoke."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import AuthContext, require_role
from app.models.api_key import ScopedAPIKey
from app.services.auth import generate_api_key, hash_api_key, ROLES
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/api-keys", tags=["API Keys"])


class APIKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    role: str = Field("operator", pattern="^(admin|operator|auditor|readonly)$")
    expires_in_days: int | None = Field(None, ge=1, le=365)


class APIKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    role: str
    active: bool
    created_by: str
    expires_at: str | None
    last_used: str | None
    created_at: str


class APIKeyCreateResponse(APIKeyResponse):
    key: str  # Only returned on creation


@router.get("")
async def list_api_keys(
    auth: AuthContext = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[APIKeyResponse]:
    result = await db.execute(select(ScopedAPIKey).order_by(ScopedAPIKey.created_at.desc()))
    keys = result.scalars().all()
    return [
        APIKeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            role=k.role,
            active=k.active,
            created_by=k.created_by,
            expires_at=k.expires_at.isoformat() if k.expires_at else None,
            last_used=k.last_used.isoformat() if k.last_used else None,
            created_at=k.created_at.isoformat(),
        )
        for k in keys
    ]


@router.post("", status_code=201)
async def create_api_key(
    body: APIKeyCreateRequest,
    request: Request,
    auth: AuthContext = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> APIKeyCreateResponse:
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)

    expires_at = None
    if body.expires_in_days:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)

    api_key = ScopedAPIKey(
        name=body.name,
        key_hash=key_hash,
        key_prefix=raw_key[:8],
        role=body.role,
        created_by=auth.username,
        active=True,
        expires_at=expires_at,
    )
    db.add(api_key)

    await audit_event(
        db=db,
        event_type="API_KEY_CREATED",
        severity="INFO",
        request=request,
        subject_type="api_key",
        subject_id=api_key.id,
        detail={"name": body.name, "role": body.role},
        description=f"API key created: {body.name} (role: {body.role})",
    )
    await db.commit()
    await db.refresh(api_key)

    return APIKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        role=api_key.role,
        active=api_key.active,
        created_by=api_key.created_by,
        expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
        last_used=None,
        created_at=api_key.created_at.isoformat(),
        key=raw_key,
    )


@router.delete("/{key_id}", status_code=200)
async def revoke_api_key(
    key_id: str,
    request: Request,
    auth: AuthContext = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    api_key = await db.get(ScopedAPIKey, key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.active = False

    await audit_event(
        db=db,
        event_type="API_KEY_REVOKED",
        severity="WARNING",
        request=request,
        subject_type="api_key",
        subject_id=key_id,
        description=f"API key revoked: {api_key.name}",
    )
    await db.commit()

    return {"status": "revoked", "name": api_key.name}
