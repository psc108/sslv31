"""Authentication and authorization dependencies.

Supports three auth methods (checked in order):
1. Bearer JWT token (from login)
2. Scoped API key (from api_keys table)
3. Legacy master API key (from settings.API_KEY — always admin role)

Tenant resolution:
- X-Tenant header (slug)
- JWT claim (tenant_id)
- Scoped API key's tenant_id
- Fallback: default tenant
"""

import hmac
from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class AuthContext:
    """Holds the authenticated identity, role, and active tenant."""
    def __init__(self, user_id: str, username: str, role: str, auth_method: str,
                 tenant_id: str = DEFAULT_TENANT_ID, is_global_admin: bool = False):
        self.user_id = user_id
        self.username = username
        self.role = role
        self.auth_method = auth_method
        self.tenant_id = tenant_id
        self.is_global_admin = is_global_admin  # Can operate across tenants


async def _resolve_tenant(request: Request, user_id: str, default_tenant: str) -> str:
    """Resolve active tenant from X-Tenant header or use default."""
    tenant_slug = request.headers.get("X-Tenant")
    if not tenant_slug:
        return default_tenant

    from app.core.database import async_session
    from app.models.tenant import Tenant
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.slug == tenant_slug)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail=f"Tenant '{tenant_slug}' not found")
        return tenant.id


async def get_auth_context(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    api_key: str | None = Security(api_key_header),
) -> AuthContext:
    """Resolve authentication from JWT bearer token, scoped API key, or legacy master key."""

    # 1. Try JWT bearer token
    if bearer:
        from app.services.auth import decode_token
        payload = decode_token(bearer.credentials)
        if payload:
            user_id = payload["sub"]
            role = payload["role"]
            is_global = role == "admin"
            default_tid = payload.get("tenant_id", DEFAULT_TENANT_ID)
            tenant_id = await _resolve_tenant(request, user_id, default_tid)

            # Non-global-admin must be member of requested tenant
            if not is_global and tenant_id != default_tid:
                from app.core.database import async_session
                from app.models.tenant import UserTenantMembership
                from sqlalchemy import select
                async with async_session() as db:
                    mem = await db.execute(
                        select(UserTenantMembership).where(
                            UserTenantMembership.user_id == user_id,
                            UserTenantMembership.tenant_id == tenant_id,
                        )
                    )
                    if not mem.scalar_one_or_none():
                        raise HTTPException(status_code=403, detail="Not a member of this tenant")

            ctx = AuthContext(
                user_id=user_id,
                username=payload["username"],
                role=role,
                auth_method="jwt",
                tenant_id=tenant_id,
                is_global_admin=is_global,
            )
            request.state.api_key_hint = f"jwt:{payload['username']}"
            request.state.tenant_id = tenant_id
            return ctx

    # 2. Try API key
    if api_key:
        # 2a. Check legacy master key first
        if hmac.compare_digest(api_key, settings.API_KEY):
            tenant_id = await _resolve_tenant(request, "system", DEFAULT_TENANT_ID)
            ctx = AuthContext(
                user_id="system",
                username="system",
                role="admin",
                auth_method="legacy_key",
                tenant_id=tenant_id,
                is_global_admin=True,
            )
            request.state.api_key_hint = api_key[-8:]
            request.state.tenant_id = tenant_id
            return ctx

        # 2b. Check scoped API keys in database
        from app.services.auth import hash_api_key
        from app.core.database import async_session
        from app.models.api_key import ScopedAPIKey
        from sqlalchemy import select

        key_hash = hash_api_key(api_key)
        async with async_session() as db:
            result = await db.execute(
                select(ScopedAPIKey).where(
                    ScopedAPIKey.key_hash == key_hash,
                    ScopedAPIKey.active == True,
                )
            )
            scoped_key = result.scalar_one_or_none()

            if scoped_key:
                # Check expiry (handle naive datetimes from SQLite)
                if scoped_key.expires_at:
                    exp = scoped_key.expires_at
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if exp < datetime.now(timezone.utc):
                        raise HTTPException(status_code=401, detail="API key expired")

                # Update last_used
                scoped_key.last_used = datetime.now(timezone.utc)
                await db.commit()

                # Resolve tenant — key's own tenant or X-Tenant header
                key_tenant = scoped_key.tenant_id or DEFAULT_TENANT_ID
                tenant_id = await _resolve_tenant(request, scoped_key.id, key_tenant)

                ctx = AuthContext(
                    user_id=scoped_key.id,
                    username=f"key:{scoped_key.name}",
                    role=scoped_key.role,
                    auth_method="api_key",
                    tenant_id=tenant_id,
                    is_global_admin=False,
                )
                request.state.api_key_hint = scoped_key.key_prefix
                request.state.tenant_id = tenant_id
                return ctx

    raise HTTPException(status_code=401, detail="Missing or invalid authentication")


async def require_api_key(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> str:
    """Backward-compatible dependency — returns key hint string."""
    return auth.username


def require_role(*allowed_roles: str) -> Callable:
    """Dependency factory that checks the user has one of the allowed roles."""
    async def _check(
        request: Request,
        auth: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        if auth.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required role: {' or '.join(allowed_roles)}",
            )
        return auth
    return _check


def require_permission(permission: str) -> Callable:
    """Dependency factory that checks the user has a specific permission."""
    async def _check(
        request: Request,
        auth: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        from app.services.auth import role_has_permission
        if not role_has_permission(auth.role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {permission}",
            )
        return auth
    return _check


def require_global_admin() -> Callable:
    """Dependency factory that requires global admin (cross-tenant operations)."""
    async def _check(
        request: Request,
        auth: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        if not auth.is_global_admin:
            raise HTTPException(
                status_code=403,
                detail="This operation requires global admin privileges",
            )
        return auth
    return _check
