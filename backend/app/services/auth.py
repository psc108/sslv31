"""Authentication service — JWT tokens and password hashing."""

import secrets
from datetime import datetime, timezone, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

ph = PasswordHasher()

# JWT config
JWT_ALGORITHM = "HS256"

def _jwt_secret() -> str:
    return settings.JWT_SECRET or settings.CERT_MASTER_KEY

ROLES = ("admin", "operator", "auditor", "readonly")

# Permission matrix
PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "ca:create", "ca:delete", "ca:read",
        "cert:issue", "cert:revoke", "cert:read", "cert:export_key",
        "csr:create", "csr:sign",
        "audit:read",
        "users:manage",
        "templates:manage",
        "settings:manage",
        "backup:manage",
        "provisioning:generate",
    },
    "operator": {
        "ca:read",
        "cert:issue", "cert:revoke", "cert:read", "cert:export_key",
        "csr:create", "csr:sign",
        "audit:read",
        "templates:manage",
        "provisioning:generate",
    },
    "auditor": {
        "ca:read",
        "cert:read",
        "audit:read",
    },
    "readonly": {
        "ca:read",
        "cert:read",
    },
}


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: str, username: str, role: str, tenant_id: str | None = None) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def hash_api_key(key: str) -> str:
    """Hash an API key for storage using SHA-256."""
    import hashlib
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def role_has_permission(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, set())
