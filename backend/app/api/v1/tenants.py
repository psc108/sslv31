"""Tenant management endpoints — create, list, update, delete tenants."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import AuthContext, require_global_admin, get_auth_context, DEFAULT_TENANT_ID
from app.models.tenant import Tenant, UserTenantMembership
from app.models.user import User
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/tenants", tags=["Tenants"])


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = ""


class TenantUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    created_at: str
    member_count: int = 0


class TenantMemberAdd(BaseModel):
    user_id: str
    tenant_role: str | None = None  # Override role within tenant


class TenantMemberResponse(BaseModel):
    user_id: str
    username: str
    tenant_role: str | None
    global_role: str


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(
    body: TenantCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_global_admin()),
) -> TenantResponse:
    # Check slug uniqueness
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Tenant slug '{body.slug}' already exists")

    tenant = Tenant(name=body.name, slug=body.slug, description=body.description)
    db.add(tenant)

    await audit_event(
        db=db, event_type="TENANT_CREATED", severity="INFO",
        request=request, subject_type="tenant", subject_id=tenant.id,
        description=f"Tenant created: {body.name} ({body.slug})",
    )
    await db.commit()
    await db.refresh(tenant)

    return TenantResponse(
        id=tenant.id, name=tenant.name, slug=tenant.slug,
        description=tenant.description,
        created_at=tenant.created_at.isoformat(), member_count=0,
    )


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> list[TenantResponse]:
    if auth.is_global_admin:
        result = await db.execute(select(Tenant).order_by(Tenant.name))
    else:
        # Non-admin: only tenants they belong to
        result = await db.execute(
            select(Tenant).join(UserTenantMembership).where(
                UserTenantMembership.user_id == auth.user_id
            ).order_by(Tenant.name)
        )

    tenants = result.scalars().all()
    responses = []
    for t in tenants:
        count_q = await db.execute(
            select(func.count()).where(UserTenantMembership.tenant_id == t.id)
        )
        member_count = count_q.scalar() or 0
        responses.append(TenantResponse(
            id=t.id, name=t.name, slug=t.slug, description=t.description,
            created_at=t.created_at.isoformat(), member_count=member_count,
        ))
    return responses


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> TenantResponse:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    count_q = await db.execute(
        select(func.count()).where(UserTenantMembership.tenant_id == tenant_id)
    )
    member_count = count_q.scalar() or 0

    return TenantResponse(
        id=tenant.id, name=tenant.name, slug=tenant.slug,
        description=tenant.description,
        created_at=tenant.created_at.isoformat(), member_count=member_count,
    )


@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_global_admin()),
) -> TenantResponse:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if body.name is not None:
        tenant.name = body.name
    if body.description is not None:
        tenant.description = body.description

    await audit_event(
        db=db, event_type="TENANT_UPDATED", severity="INFO",
        request=request, subject_type="tenant", subject_id=tenant_id,
        description=f"Tenant updated: {tenant.name}",
    )
    await db.commit()
    await db.refresh(tenant)

    count_q = await db.execute(
        select(func.count()).where(UserTenantMembership.tenant_id == tenant_id)
    )
    member_count = count_q.scalar() or 0

    return TenantResponse(
        id=tenant.id, name=tenant.name, slug=tenant.slug,
        description=tenant.description,
        created_at=tenant.created_at.isoformat(), member_count=member_count,
    )


@router.delete("/{tenant_id}", status_code=200)
async def delete_tenant(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_global_admin()),
) -> dict:
    if tenant_id == DEFAULT_TENANT_ID:
        raise HTTPException(status_code=400, detail="Cannot delete the default tenant")

    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Check for resources still in this tenant
    from app.models.ca import CertificateAuthority
    ca_count = (await db.execute(
        select(func.count()).where(CertificateAuthority.tenant_id == tenant_id)
    )).scalar() or 0
    if ca_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Tenant has {ca_count} CA(s). Move or delete them first.",
        )

    await db.delete(tenant)
    await audit_event(
        db=db, event_type="TENANT_DELETED", severity="WARNING",
        request=request, subject_type="tenant", subject_id=tenant_id,
        description=f"Tenant deleted: {tenant.name} ({tenant.slug})",
    )
    await db.commit()
    return {"status": "deleted", "tenant_id": tenant_id}


# --- Membership management ---

@router.get("/{tenant_id}/members", response_model=list[TenantMemberResponse])
async def list_members(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_global_admin()),
) -> list[TenantMemberResponse]:
    result = await db.execute(
        select(UserTenantMembership, User).join(
            User, User.id == UserTenantMembership.user_id
        ).where(UserTenantMembership.tenant_id == tenant_id)
    )
    rows = result.all()
    return [
        TenantMemberResponse(
            user_id=mem.user_id, username=user.username,
            tenant_role=mem.tenant_role, global_role=user.role,
        )
        for mem, user in rows
    ]


@router.post("/{tenant_id}/members", status_code=201)
async def add_member(
    tenant_id: str,
    body: TenantMemberAdd,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_global_admin()),
) -> dict:
    # Verify tenant and user exist
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    user = await db.get(User, body.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check not already member
    existing = await db.execute(
        select(UserTenantMembership).where(
            UserTenantMembership.user_id == body.user_id,
            UserTenantMembership.tenant_id == tenant_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member of this tenant")

    membership = UserTenantMembership(
        user_id=body.user_id, tenant_id=tenant_id, tenant_role=body.tenant_role,
    )
    db.add(membership)

    await audit_event(
        db=db, event_type="TENANT_MEMBER_ADDED", severity="INFO",
        request=request, subject_type="tenant", subject_id=tenant_id,
        detail={"user_id": body.user_id, "username": user.username},
        description=f"User '{user.username}' added to tenant '{tenant.name}'",
    )
    await db.commit()
    return {"status": "added", "user_id": body.user_id, "tenant_id": tenant_id}


@router.delete("/{tenant_id}/members/{user_id}", status_code=200)
async def remove_member(
    tenant_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_global_admin()),
) -> dict:
    result = await db.execute(
        select(UserTenantMembership).where(
            UserTenantMembership.user_id == user_id,
            UserTenantMembership.tenant_id == tenant_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="Membership not found")

    await db.delete(membership)
    await audit_event(
        db=db, event_type="TENANT_MEMBER_REMOVED", severity="INFO",
        request=request, subject_type="tenant", subject_id=tenant_id,
        description=f"User removed from tenant",
    )
    await db.commit()
    return {"status": "removed", "user_id": user_id, "tenant_id": tenant_id}
