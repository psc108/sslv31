"""Security expression parser.

Converts raw Spring Security SpEL expressions and JSR-250 annotation values
into a structured auth requirements dict:

    {
        "public":      bool,   # true if no auth required (permitAll / anonymous)
        "deny_all":    bool,   # true if always denied
        "roles":       list[str],  # e.g. ["ADMIN", "OPERATOR"]
        "authorities": list[str],  # e.g. ["catalog:read", "request:write"]
        "authenticated_only": bool,  # isAuthenticated() with no role/authority constraint
        "raw":         str,    # original expression for display
    }

Handles:
  - @PreAuthorize("hasRole('X')")
  - @PreAuthorize("hasAnyRole('X','Y')")
  - @PreAuthorize("hasAuthority('x:read')")
  - @PreAuthorize("hasAnyAuthority('x:read','y:write')")
  - @PreAuthorize("isAuthenticated()")
  - @PreAuthorize("permitAll()")
  - @PreAuthorize("denyAll()")
  - @PreAuthorize("hasRole('X') and hasAuthority('y:z')")
  - @Secured("ROLE_ADMIN") / @Secured({"ROLE_ADMIN","ROLE_OP"})
  - @RolesAllowed("ADMIN") / @RolesAllowed({"ADMIN","OP"})
"""
from __future__ import annotations

import re

_ROLE_PREFIX = re.compile(r"^ROLE_", re.IGNORECASE)

# Patterns for SpEL function calls
_HAS_ROLE        = re.compile(r"hasRole\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.IGNORECASE)
_HAS_ANY_ROLE    = re.compile(r"hasAnyRole\s*\(([^)]+)\)", re.IGNORECASE)
_HAS_AUTH        = re.compile(r"hasAuthority\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.IGNORECASE)
_HAS_ANY_AUTH    = re.compile(r"hasAnyAuthority\s*\(([^)]+)\)", re.IGNORECASE)
_IS_AUTH         = re.compile(r"isAuthenticated\s*\(\s*\)", re.IGNORECASE)
_PERMIT_ALL      = re.compile(r"permitAll\s*\(\s*\)", re.IGNORECASE)
_DENY_ALL        = re.compile(r"denyAll\s*\(\s*\)", re.IGNORECASE)
_QUOTED_VALUES   = re.compile(r"['\"]([^'\"]+)['\"]")


def _strip_role_prefix(role: str) -> str:
    return _ROLE_PREFIX.sub("", role).strip()


def _extract_quoted(s: str) -> list[str]:
    return [m.strip() for m in _QUOTED_VALUES.findall(s)]


def parse_expression(annotation: str, expression: str) -> dict:
    """Parse a security annotation expression into a structured dict."""
    raw = expression.strip()
    result: dict = {
        "public": False,
        "deny_all": False,
        "roles": [],
        "authorities": [],
        "authenticated_only": False,
        "raw": raw,
    }

    if not raw:
        return result

    ann_lower = annotation.lower()

    # --- @Secured / @RolesAllowed: expression is a comma-separated role list ---
    if "@secured" in ann_lower or "@rolesallowed" in ann_lower:
        roles = [_strip_role_prefix(r) for r in raw.replace("{", "").replace("}", "").split(",")]
        result["roles"] = [r for r in roles if r]
        return result

    # --- @PreAuthorize SpEL ---
    expr = raw

    if _PERMIT_ALL.search(expr):
        result["public"] = True
        return result

    if _DENY_ALL.search(expr):
        result["deny_all"] = True
        return result

    roles: list[str] = []
    authorities: list[str] = []

    for m in _HAS_ROLE.finditer(expr):
        roles.append(_strip_role_prefix(m.group(1)))

    for m in _HAS_ANY_ROLE.finditer(expr):
        roles.extend(_strip_role_prefix(v) for v in _extract_quoted(m.group(1)))

    for m in _HAS_AUTH.finditer(expr):
        authorities.append(m.group(1).strip())

    for m in _HAS_ANY_AUTH.finditer(expr):
        authorities.extend(v for v in _extract_quoted(m.group(1)))

    result["roles"] = sorted(set(roles))
    result["authorities"] = sorted(set(authorities))

    if not roles and not authorities and _IS_AUTH.search(expr):
        result["authenticated_only"] = True

    return result
