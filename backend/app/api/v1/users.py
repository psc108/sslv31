"""User management endpoints — admin only."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import AuthContext, require_role
from app.models.user import User
from app.services.auth import hash_password, ROLES
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: str = ""
    password: str = Field(..., min_length=8)
    role: str = Field("readonly", pattern="^(admin|operator|auditor|readonly)$")


class UserUpdateRequest(BaseModel):
    email: str | None = None
    role: str | None = Field(None, pattern="^(admin|operator|auditor|readonly)$")
    active: bool | None = None
    password: str | None = Field(None, min_length=8)


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    active: bool
    created_at: str
    last_login: str | None


@router.get("")
async def list_users(
    auth: AuthContext = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[UserResponse]:
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [
        UserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            role=u.role,
            active=u.active,
            created_at=u.created_at.isoformat(),
            last_login=u.last_login.isoformat() if u.last_login else None,
        )
        for u in users
    ]


@router.post("", status_code=201)
async def create_user(
    body: UserCreateRequest,
    request: Request,
    auth: AuthContext = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    # Check uniqueness
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already exists")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        active=True,
    )
    db.add(user)

    await audit_event(
        db=db,
        event_type="USER_CREATED",
        severity="INFO",
        request=request,
        subject_type="user",
        subject_id=user.id,
        detail={"username": body.username, "role": body.role},
        description=f"User created: {body.username} (role: {body.role})",
    )
    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        active=user.active,
        created_at=user.created_at.isoformat(),
        last_login=None,
    )


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    request: Request,
    auth: AuthContext = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.email is not None:
        user.email = body.email
    if body.role is not None:
        user.role = body.role
    if body.active is not None:
        user.active = body.active
    if body.password is not None:
        user.password_hash = hash_password(body.password)

    await audit_event(
        db=db,
        event_type="USER_UPDATED",
        severity="INFO",
        request=request,
        subject_type="user",
        subject_id=user_id,
        description=f"User updated: {user.username}",
    )
    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        active=user.active,
        created_at=user.created_at.isoformat(),
        last_login=user.last_login.isoformat() if user.last_login else None,
    )


@router.delete("/{user_id}", status_code=200)
async def delete_user(
    user_id: str,
    request: Request,
    auth: AuthContext = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.username == "admin":
        raise HTTPException(status_code=403, detail="Cannot delete the default admin user")

    await db.delete(user)

    await audit_event(
        db=db,
        event_type="USER_DELETED",
        severity="WARNING",
        request=request,
        subject_type="user",
        subject_id=user_id,
        description=f"User deleted: {user.username}",
    )
    await db.commit()

    return {"status": "deleted", "username": user.username}
