"""Auth endpoints — login, token refresh, current user, change password."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import AuthContext, get_auth_context
from app.models.user import User
from app.services.auth import verify_password, create_access_token, hash_password, ROLES
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    username: str
    role: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/auth-info")
async def auth_info() -> dict:
    """Public endpoint — returns auth configuration for the login page."""
    from app.services.ldap_auth import is_ldap_enabled
    return {"ldap_enabled": is_ldap_enabled()}


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    result = await db.execute(
        select(User).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()

    # Check lockout BEFORE password verification
    if user and user.locked_until:
        lock_time = user.locked_until
        if lock_time.tzinfo is None:
            lock_time = lock_time.replace(tzinfo=timezone.utc)
        if lock_time > datetime.now(timezone.utc):
            remaining = int((lock_time - datetime.now(timezone.utc)).total_seconds())
            raise HTTPException(
                status_code=423,
                detail=f"Account locked. Try again in {remaining} seconds.",
                headers={"Retry-After": str(remaining)},
            )

    # Try local auth first (for local users or if user not found yet)
    local_auth_ok = False
    if user and getattr(user, "auth_source", "local") == "local":
        local_auth_ok = verify_password(body.password, user.password_hash)

    # Try LDAP if local auth failed and LDAP is enabled
    ldap_auth_result = None
    if not local_auth_ok:
        from app.services.ldap_auth import is_ldap_enabled, authenticate_ldap
        if is_ldap_enabled():
            ldap_auth_result = await authenticate_ldap(body.username, body.password)
            if ldap_auth_result.success:
                # Create or update shadow user record
                if not user:
                    user = User(
                        username=body.username,
                        email=ldap_auth_result.email,
                        password_hash="ldap-external",
                        role=ldap_auth_result.role,
                        auth_source="ldap",
                        ldap_dn=ldap_auth_result.display_name,
                    )
                    db.add(user)
                    await db.flush()
                else:
                    # Update role from LDAP groups on each login
                    user.role = ldap_auth_result.role
                    user.auth_source = "ldap"
                    if ldap_auth_result.email:
                        user.email = ldap_auth_result.email

    # Determine final auth success
    auth_ok = local_auth_ok or (ldap_auth_result and ldap_auth_result.success)

    if not auth_ok:
        # Record failed attempt if user exists
        if user:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= settings.LOGIN_MAX_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
                await audit_event(
                    db=db, event_type="AUTH_LOCKOUT", severity="WARNING", request=request,
                    subject_type="user", subject_id=user.id,
                    description=f"Account locked after {user.failed_attempts} failed attempts: {user.username}",
                )
            await db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not user.active:
        raise HTTPException(status_code=403, detail="Account disabled")

    # Successful login — reset failed attempts
    user.failed_attempts = 0
    user.locked_until = None

    # Resolve user's default tenant (first membership)
    from app.models.tenant import UserTenantMembership
    mem_result = await db.execute(
        select(UserTenantMembership.tenant_id).where(
            UserTenantMembership.user_id == user.id
        ).limit(1)
    )
    default_tenant = mem_result.scalar_one_or_none() or "00000000-0000-0000-0000-000000000001"

    token = create_access_token(user.id, user.username, user.role, tenant_id=default_tenant)
    user.last_login = datetime.now(timezone.utc)

    auth_method = "ldap" if (ldap_auth_result and ldap_auth_result.success) else "local"
    await audit_event(
        db=db,
        event_type="USER_LOGIN",
        severity="INFO",
        request=request,
        subject_type="user",
        subject_id=user.id,
        description=f"User logged in: {user.username} (auth={auth_method})",
    )
    await db.commit()

    return LoginResponse(
        token=token,
        user_id=user.id,
        username=user.username,
        role=user.role,
    )


@router.get("/me")
async def get_current_user(
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    base = {
        "user_id": auth.user_id,
        "username": auth.username,
        "role": auth.role,
        "auth_method": auth.auth_method,
        "tenant_id": auth.tenant_id,
        "is_global_admin": auth.is_global_admin,
    }
    if auth.auth_method == "jwt":
        result = await db.execute(select(User).where(User.id == auth.user_id))
        user = result.scalar_one_or_none()
        if user:
            base.update({
                "email": user.email,
                "auth_source": getattr(user, "auth_source", "local"),
                "last_login": user.last_login.isoformat() if user.last_login else None,
            })
    return base


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if auth.auth_method != "jwt":
        raise HTTPException(status_code=400, detail="Password change only available for user accounts")

    result = await db.execute(select(User).where(User.id == auth.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    user.password_hash = hash_password(body.new_password)

    await audit_event(
        db=db,
        event_type="PASSWORD_CHANGED",
        severity="WARNING",
        request=request,
        subject_type="user",
        subject_id=user.id,
        description=f"Password changed for user: {user.username}",
    )
    await db.commit()

    return {"status": "password_changed"}
