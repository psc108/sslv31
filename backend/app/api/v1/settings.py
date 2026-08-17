"""Settings endpoints — API key rotation."""

import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key, require_permission, AuthContext
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])


@router.post("/rotate-api-key")
async def rotate_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Generate a new API key. The old key is immediately invalidated.

    The new key is returned in the response — save it immediately.
    The application's in-memory settings are updated; the .env file
    must be updated manually (or via the install script).
    """
    new_key = secrets.token_urlsafe(32)

    # Update in-memory settings
    settings.API_KEY = new_key

    await audit_event(
        db=db,
        event_type="API_KEY_ROTATED",
        severity="WARNING",
        request=request,
        subject_type="settings",
        subject_id="api_key",
        description="API key rotated. Old key invalidated.",
    )
    await db.commit()

    return {
        "status": "rotated",
        "new_api_key": new_key,
        "message": "Save this key immediately. Update backend/.env or /etc/certmanager/certmanager.env with the new value.",
    }


@router.get("/pki")
async def get_pki_settings(
    _: str = Depends(require_api_key),
) -> dict:
    """Get current PKI infrastructure settings."""
    base = settings.PKI_BASE_URL
    return {
        "pki_base_url": base,
        "crl_validity_days": settings.CRL_VALIDITY_DAYS,
        "enabled": bool(base),
        "crl_endpoint": f"{base}/api/v1/pki/crl/{{ca_id}}" if base else None,
        "ca_cert_endpoint": f"{base}/api/v1/pki/ca/{{ca_id}}/cert" if base else None,
        "ocsp_endpoint": f"{base}/api/v1/pki/ocsp" if base else None,
    }


from pydantic import BaseModel


class PKISettingsUpdate(BaseModel):
    pki_base_url: str = ""
    crl_validity_days: int = 7


class LDAPSettingsUpdate(BaseModel):
    enabled: bool = False
    url: str = ""
    starttls: bool = False
    bind_dn: str = ""
    bind_password: str = ""
    search_base: str = ""
    search_filter: str = "(uid={username})"
    user_dn_template: str = ""
    tls_ca_cert: str = ""
    timeout: int = 10
    role_admin: str = ""
    role_operator: str = ""
    role_auditor: str = ""
    role_default: str = "readonly"
    group_attribute: str = "memberOf"


@router.put("/pki")
async def update_pki_settings(
    body: PKISettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Update PKI base URL. Takes effect immediately for new certificates."""
    # Strip trailing slash
    base = body.pki_base_url.rstrip("/")
    settings.PKI_BASE_URL = base
    settings.CRL_VALIDITY_DAYS = body.crl_validity_days

    await audit_event(
        db=db,
        event_type="PKI_SETTINGS_UPDATED",
        severity="INFO",
        request=request,
        subject_type="settings",
        subject_id="pki",
        detail={"pki_base_url": base, "crl_validity_days": body.crl_validity_days},
        description=f"PKI base URL set to: {base or '(disabled)'}",
    )
    await db.commit()

    return {
        "status": "updated",
        "pki_base_url": base,
        "crl_validity_days": body.crl_validity_days,
        "enabled": bool(base),
    }


@router.get("/ldap")
async def get_ldap_settings(
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Get current LDAP configuration (passwords masked)."""
    from app.services.ldap_auth import get_ldap_config
    return get_ldap_config()


@router.put("/ldap")
async def update_ldap_settings(
    body: LDAPSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Update LDAP settings. Takes effect immediately for new logins."""
    settings.LDAP_ENABLED = body.enabled
    settings.LDAP_URL = body.url
    settings.LDAP_STARTTLS = body.starttls
    settings.LDAP_BIND_DN = body.bind_dn
    if body.bind_password:  # Only update if provided (don't clear on empty)
        settings.LDAP_BIND_PASSWORD = body.bind_password
    settings.LDAP_SEARCH_BASE = body.search_base
    settings.LDAP_SEARCH_FILTER = body.search_filter
    settings.LDAP_USER_DN_TEMPLATE = body.user_dn_template
    settings.LDAP_TLS_CA_CERT = body.tls_ca_cert
    settings.LDAP_TIMEOUT = body.timeout
    settings.LDAP_ROLE_ADMIN = body.role_admin
    settings.LDAP_ROLE_OPERATOR = body.role_operator
    settings.LDAP_ROLE_AUDITOR = body.role_auditor
    settings.LDAP_ROLE_DEFAULT = body.role_default
    settings.LDAP_GROUP_ATTRIBUTE = body.group_attribute

    await audit_event(
        db=db,
        event_type="LDAP_SETTINGS_UPDATED",
        severity="WARNING",
        request=request,
        subject_type="settings",
        subject_id="ldap",
        description=f"LDAP settings updated. Enabled={body.enabled}, URL={body.url}",
    )
    await db.commit()

    return {"status": "updated", "enabled": body.enabled, "url": body.url}


@router.post("/ldap/test")
async def test_ldap_connection(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Test LDAP connectivity with current settings."""
    from app.services.ldap_auth import test_ldap_connection as _test
    result = await _test()

    await audit_event(
        db=db,
        event_type="LDAP_CONNECTION_TEST",
        severity="INFO",
        request=request,
        subject_type="settings",
        subject_id="ldap",
        description=f"LDAP connection test: {result['status']}",
    )
    await db.commit()

    return result


# --- Build Manager (Improvements Plan Stage 22) ---
# Unlike PKI/LDAP above, this toggle is DB-backed (BMSettings), not an
# in-memory Settings() attribute — it needs to survive a restart without
# relying on someone hand-editing .env, and it's read from a background
# job pipeline (ansible_runner.py), not just API request handlers.

@router.get("/build-manager")
async def get_build_manager_settings(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Get the current opt-in auto-bug-filing setting."""
    from app.services.build_manager.bug_pattern_scan import get_or_create_bm_settings
    row = await get_or_create_bm_settings(db)
    await db.commit()
    return {"auto_file_bugs_on_failure": row.auto_file_bugs_on_failure}


class BuildManagerSettingsUpdate(BaseModel):
    auto_file_bugs_on_failure: bool


@router.put("/build-manager")
async def update_build_manager_settings(
    body: BuildManagerSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("settings:manage")),
) -> dict:
    """Turn automatic bug filing on Ansible job failure on/off. See the Bug
    Tracker section of the Docs Help for how the matching/dedup works."""
    from app.services.build_manager.bug_pattern_scan import get_or_create_bm_settings
    row = await get_or_create_bm_settings(db)
    row.auto_file_bugs_on_failure = body.auto_file_bugs_on_failure
    row.updated_by = auth.username

    await audit_event(
        db=db,
        event_type="BM_SETTINGS_UPDATED",
        severity="INFO",
        request=request,
        subject_type="settings",
        subject_id="build-manager",
        detail={"auto_file_bugs_on_failure": body.auto_file_bugs_on_failure},
        description=f"Auto-file bugs on Ansible failure set to: {body.auto_file_bugs_on_failure}",
    )
    await db.commit()

    return {"status": "updated", "auto_file_bugs_on_failure": body.auto_file_bugs_on_failure}
