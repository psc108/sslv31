"""API v2 router — versioned endpoints with enhanced response format.

v2 provides:
- Consistent envelope response format: {data, meta, errors}
- Pagination via cursor (not offset)
- Expanded filtering
- Deprecation of legacy fields

v1 remains fully supported. v2 is additive — no v1 endpoints are removed.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import get_auth_context, AuthContext

router = APIRouter(prefix="/api/v2", tags=["API v2"])


class VersionInfo(BaseModel):
    api_version: str = "2.0"
    app_version: str
    status: str = "current"
    v1_status: str = "stable"
    v1_sunset: str | None = None
    supported_versions: list[str] = ["v1", "v2"]
    changelog_url: str = "/api/v2/changelog"


class ChangelogEntry(BaseModel):
    version: str
    date: str
    changes: list[str]


@router.get("/version")
async def get_version_info() -> VersionInfo:
    """API version information and deprecation schedule."""
    return VersionInfo(app_version=settings.APP_VERSION)


@router.get("/changelog")
async def get_changelog() -> list[ChangelogEntry]:
    """API changelog — breaking changes and new features by version."""
    return [
        ChangelogEntry(
            version="2.0",
            date="2025-01-01",
            changes=[
                "Envelope response format: {data, meta, errors}",
                "Cursor-based pagination",
                "SDK generation endpoint",
                "CLI tool support",
                "Deprecation headers on v1 (no sunset date yet)",
            ],
        ),
        ChangelogEntry(
            version="1.0",
            date="2024-01-01",
            changes=[
                "Initial API release",
                "Certificate management (issue, revoke, export)",
                "CA management",
                "CSR generation and signing",
                "Trust store builder",
                "RBAC with JWT + API keys",
                "Audit trail",
                "OCSP, CRL, EST, CT",
                "Multi-tenancy",
                "Key escrow",
                "Compliance scanning",
            ],
        ),
    ]


@router.get("/health")
async def health_v2() -> dict:
    """Enhanced health check with component status."""
    from app.core.database import engine
    from sqlalchemy import text

    components = {}

    # Database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_type = "postgresql" if settings.is_postgres else "mysql" if settings.is_mysql else "sqlite"
        components["database"] = {"status": "healthy", "type": db_type}
    except Exception as e:
        components["database"] = {"status": "unhealthy", "error": str(e)}

    # Keytool
    import shutil
    components["keytool"] = {"status": "healthy" if shutil.which("keytool") else "unavailable"}

    # OpenSSL
    components["openssl"] = {"status": "healthy" if shutil.which("openssl") else "unavailable"}

    overall = "healthy" if all(c.get("status") == "healthy" for c in components.values() if c.get("status") != "unavailable") else "degraded"

    return {
        "data": {
            "status": overall,
            "version": settings.APP_VERSION,
            "api_version": "2.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": components,
        },
        "meta": {"api_version": "2.0"},
        "errors": [],
    }


@router.get("/me")
async def get_current_user_v2(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """Current authenticated user info (v2 envelope format)."""
    return {
        "data": {
            "user_id": auth.user_id,
            "username": auth.username,
            "role": auth.role,
            "auth_method": auth.auth_method,
            "tenant_id": auth.tenant_id,
            "is_global_admin": auth.is_global_admin,
        },
        "meta": {"api_version": "2.0"},
        "errors": [],
    }
