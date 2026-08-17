"""LDAP / Active Directory authentication backend.

Provides hybrid auth: local DB first, then LDAP if enabled.
Designed as a pluggable interface for future SAML/OIDC providers.
"""

import logging
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExternalAuthResult:
    """Result from an external auth provider (LDAP, SAML, OIDC)."""
    success: bool
    username: str = ""
    email: str = ""
    display_name: str = ""
    role: str = "readonly"
    groups: list[str] | None = None
    error: str = ""
    provider: str = ""  # "ldap", "saml", "oidc"


def is_ldap_enabled() -> bool:
    return settings.LDAP_ENABLED and bool(settings.LDAP_URL)


def get_ldap_config() -> dict:
    """Return current LDAP configuration (passwords masked)."""
    return {
        "enabled": settings.LDAP_ENABLED,
        "url": settings.LDAP_URL,
        "starttls": settings.LDAP_STARTTLS,
        "bind_dn": settings.LDAP_BIND_DN,
        "bind_password_set": bool(settings.LDAP_BIND_PASSWORD),
        "search_base": settings.LDAP_SEARCH_BASE,
        "search_filter": settings.LDAP_SEARCH_FILTER,
        "user_dn_template": settings.LDAP_USER_DN_TEMPLATE,
        "tls_ca_cert": settings.LDAP_TLS_CA_CERT,
        "timeout": settings.LDAP_TIMEOUT,
        "role_admin": settings.LDAP_ROLE_ADMIN,
        "role_operator": settings.LDAP_ROLE_OPERATOR,
        "role_auditor": settings.LDAP_ROLE_AUDITOR,
        "role_default": settings.LDAP_ROLE_DEFAULT,
        "group_attribute": settings.LDAP_GROUP_ATTRIBUTE,
    }


def _resolve_role_from_groups(groups: list[str]) -> str:
    """Map LDAP group memberships to application role (highest privilege wins)."""
    groups_lower = [g.lower() for g in groups]

    if settings.LDAP_ROLE_ADMIN and settings.LDAP_ROLE_ADMIN.lower() in groups_lower:
        return "admin"
    if settings.LDAP_ROLE_OPERATOR and settings.LDAP_ROLE_OPERATOR.lower() in groups_lower:
        return "operator"
    if settings.LDAP_ROLE_AUDITOR and settings.LDAP_ROLE_AUDITOR.lower() in groups_lower:
        return "auditor"
    return settings.LDAP_ROLE_DEFAULT


async def authenticate_ldap(username: str, password: str) -> ExternalAuthResult:
    """Authenticate user against LDAP/AD server.

    Returns ExternalAuthResult with success=True if credentials valid.
    """
    if not is_ldap_enabled():
        return ExternalAuthResult(success=False, error="LDAP not enabled")

    try:
        import ldap3
        from ldap3 import Server, Connection, ALL, SUBTREE, Tls
        import ssl as ssl_module
    except ImportError:
        logger.error("ldap3 package not installed. Install with: pip install ldap3")
        return ExternalAuthResult(success=False, error="LDAP library not available")

    try:
        # Configure TLS
        tls_config = None
        if settings.LDAP_URL.startswith("ldaps://") or settings.LDAP_STARTTLS:
            tls_kwargs = {"validate": ssl_module.CERT_REQUIRED}
            if settings.LDAP_TLS_CA_CERT:
                tls_kwargs["ca_certs_file"] = settings.LDAP_TLS_CA_CERT
            else:
                tls_kwargs["validate"] = ssl_module.CERT_NONE
            tls_config = Tls(**tls_kwargs)

        server = Server(
            settings.LDAP_URL,
            use_ssl=settings.LDAP_URL.startswith("ldaps://"),
            tls=tls_config,
            get_info=ALL,
            connect_timeout=settings.LDAP_TIMEOUT,
        )

        # Determine user DN for bind
        user_dn = None
        if settings.LDAP_USER_DN_TEMPLATE:
            # Direct bind mode
            user_dn = settings.LDAP_USER_DN_TEMPLATE.replace("{username}", username)
        elif settings.LDAP_SEARCH_BASE:
            # Search mode: first bind as service account, find user DN
            search_filter = settings.LDAP_SEARCH_FILTER.replace("{username}", username)
            bind_dn = settings.LDAP_BIND_DN or None
            bind_pw = settings.LDAP_BIND_PASSWORD or None

            conn = Connection(server, user=bind_dn, password=bind_pw, auto_bind=True)
            if settings.LDAP_STARTTLS and not settings.LDAP_URL.startswith("ldaps://"):
                conn.start_tls()

            conn.search(
                search_base=settings.LDAP_SEARCH_BASE,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=["dn", "mail", "displayName", "cn", settings.LDAP_GROUP_ATTRIBUTE],
            )

            if not conn.entries:
                conn.unbind()
                return ExternalAuthResult(success=False, username=username, error="User not found in LDAP")

            entry = conn.entries[0]
            user_dn = str(entry.entry_dn)
            conn.unbind()
        else:
            return ExternalAuthResult(success=False, error="LDAP misconfigured: no DN template or search base")

        # Bind as the user to verify password
        user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
        if settings.LDAP_STARTTLS and not settings.LDAP_URL.startswith("ldaps://"):
            user_conn.start_tls()

        # Fetch user attributes and groups
        email = ""
        display_name = username
        groups: list[str] = []

        if settings.LDAP_SEARCH_BASE:
            search_filter = settings.LDAP_SEARCH_FILTER.replace("{username}", username)
            user_conn.search(
                search_base=settings.LDAP_SEARCH_BASE,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=["mail", "displayName", "cn", settings.LDAP_GROUP_ATTRIBUTE],
            )
            if user_conn.entries:
                entry = user_conn.entries[0]
                email = str(entry.mail) if hasattr(entry, "mail") and entry.mail else ""
                display_name = str(entry.displayName) if hasattr(entry, "displayName") and entry.displayName else username
                group_attr = getattr(entry, settings.LDAP_GROUP_ATTRIBUTE, None)
                if group_attr:
                    groups = list(group_attr.values) if hasattr(group_attr, "values") else []

        user_conn.unbind()

        role = _resolve_role_from_groups(groups)

        logger.info(f"LDAP auth success: {username} (role={role}, groups={len(groups)})")
        return ExternalAuthResult(
            success=True,
            username=username,
            email=email,
            display_name=display_name,
            role=role,
            groups=groups,
            provider="ldap",
        )

    except ImportError:
        return ExternalAuthResult(success=False, error="ldap3 package not installed")
    except Exception as e:
        logger.warning(f"LDAP auth failed for {username}: {e}")
        return ExternalAuthResult(success=False, username=username, error=str(e), provider="ldap")


async def test_ldap_connection() -> dict:
    """Test LDAP connectivity without authenticating a user."""
    if not settings.LDAP_URL:
        return {"status": "error", "message": "LDAP URL not configured"}

    try:
        import ldap3
        from ldap3 import Server, Connection, ALL, Tls
        import ssl as ssl_module
    except ImportError:
        return {"status": "error", "message": "ldap3 package not installed. Add 'ldap3>=2.9.0' to requirements.txt"}

    try:
        tls_config = None
        if settings.LDAP_URL.startswith("ldaps://") or settings.LDAP_STARTTLS:
            tls_kwargs = {"validate": ssl_module.CERT_REQUIRED}
            if settings.LDAP_TLS_CA_CERT:
                tls_kwargs["ca_certs_file"] = settings.LDAP_TLS_CA_CERT
            else:
                tls_kwargs["validate"] = ssl_module.CERT_NONE
            tls_config = Tls(**tls_kwargs)

        server = Server(
            settings.LDAP_URL,
            use_ssl=settings.LDAP_URL.startswith("ldaps://"),
            tls=tls_config,
            get_info=ALL,
            connect_timeout=settings.LDAP_TIMEOUT,
        )

        bind_dn = settings.LDAP_BIND_DN or None
        bind_pw = settings.LDAP_BIND_PASSWORD or None

        conn = Connection(server, user=bind_dn, password=bind_pw, auto_bind=True)
        if settings.LDAP_STARTTLS and not settings.LDAP_URL.startswith("ldaps://"):
            conn.start_tls()

        server_info = {
            "vendor": str(server.info.vendor_name) if server.info and server.info.vendor_name else "unknown",
            "naming_contexts": [str(nc) for nc in server.info.naming_contexts] if server.info and server.info.naming_contexts else [],
        }
        conn.unbind()

        return {"status": "ok", "message": "LDAP connection successful", "server_info": server_info}

    except Exception as e:
        return {"status": "error", "message": f"LDAP connection failed: {e}"}
