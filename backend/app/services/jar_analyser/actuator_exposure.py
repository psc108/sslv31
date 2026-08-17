"""Actuator / management endpoint exposure — a real, common production
vulnerability class (unsecured `/actuator/env` or `/actuator/heapdump`
leaking secrets or enabling abuse), checked purely from static evidence.

This deliberately does not attempt to parse custom Spring Security
HttpSecurity/SecurityFilterChain rules — that's an existing, documented
limitation of this tool (see the Security Posture section). Instead it
checks the framework-level `management.endpoints.web.exposure.*` config
keys (already categorised "actuator" by config_files.py), cross-referenced
with whether the management port is the same as the main app port and
whether that port is reachable via the Nginx proxy — the best static
signals available without live verification.
"""
from __future__ import annotations

from app.services.jar_analyser.proxy_checker import build_proxied_services, is_service_proxied

# Endpoints that leak information or enable abuse the moment they're
# web-exposed — no secondary "enabled" flag required in modern Spring Boot.
_SENSITIVE_ENDPOINTS = {
    "env", "heapdump", "threaddump", "beans", "configprops",
    "mappings", "loggers", "httptrace", "httpexchanges", "auditevents",
}

# shutdown is uniquely severe (remote process termination) but, unlike the
# endpoints above, doing nothing unless *also* explicitly enabled via
# management.endpoint.shutdown.enabled=true — exposure.include alone is not
# sufficient, so it's tracked separately rather than lumped into the set above.
_SHUTDOWN = "shutdown"


def _find_key(keys: list[dict], name: str) -> dict | None:
    for k in keys:
        if k.get("key") == name:
            return k
    return None


def _is_literal(k: dict | None) -> bool:
    if not k:
        return False
    val = k.get("value") or ""
    return bool(val) and not val.startswith("${") and not k.get("is_placeholder") and not k.get("is_encrypted")


def _parse_endpoint_list(raw: str) -> tuple[set[str], bool]:
    """Return (endpoint_ids, is_wildcard).

    Real-data finding: some bundles store this as a proper comma-separated
    string ("health,info"), others as a YAML list that ends up flattened to
    a Python-list-repr string ("['health', 'info']") — strip brackets/quotes
    before splitting so both forms parse identically.
    """
    raw = raw.strip()
    if raw == "*":
        return set(), True
    cleaned = raw.strip("[]")
    return {e.strip().strip("'\"") for e in cleaned.split(",") if e.strip().strip("'\"")}, False


def _has_actuator_dependency(sr: dict) -> bool:
    for d in sr.get("dependencies", []):
        haystack = f"{d.get('artifact_id') or ''} {d.get('filename') or ''}".lower()
        if "actuator" in haystack:
            return True
    return False


def compute_actuator_exposure(sub_reports: list[dict]) -> dict:
    proxied_services = build_proxied_services(sub_reports)
    services: list[dict] = []

    for sr in sub_reports:
        svc = sr.get("service_name") or sr.get("filename")
        keys = [k for cfg in sr.get("config_files", []) for k in cfg.get("keys", [])]
        actuator_keys = [k for k in keys if k.get("category") == "actuator"]

        if not actuator_keys and not _has_actuator_dependency(sr):
            continue  # actuator not evidenced at all for this service

        include_key = _find_key(keys, "management.endpoints.web.exposure.include")
        port_key = _find_key(keys, "management.server.port")
        address_key = _find_key(keys, "management.server.address")
        shutdown_enabled_key = _find_key(keys, "management.endpoint.shutdown.enabled")
        legacy_security_key = _find_key(keys, "management.security.enabled")

        if not include_key:
            continue  # no evidence of broadened exposure — framework default (health only) applies

        if not _is_literal(include_key):
            # exposure list is itself externally parameterised — can't resolve
            # what's actually exposed, so this is a known gap, not a finding.
            services.append({
                "service": svc,
                "evidence": [include_key["key"]],
                "risk": "unknown",
                "note": f"'{include_key['key']}' is externally parameterised — exposed endpoint list "
                        f"cannot be resolved from this bundle.",
            })
            continue

        exposed, is_wildcard = _parse_endpoint_list(include_key["value"])
        sensitive_exposed = sorted(_SENSITIVE_ENDPOINTS) if is_wildcard else sorted(exposed & _SENSITIVE_ENDPOINTS)

        shutdown_exposed = is_wildcard or _SHUTDOWN in exposed
        shutdown_enabled = _is_literal(shutdown_enabled_key) and shutdown_enabled_key["value"].lower() == "true"
        if shutdown_exposed and shutdown_enabled:
            sensitive_exposed = sorted(set(sensitive_exposed) | {_SHUTDOWN})

        if not sensitive_exposed:
            continue  # only non-sensitive endpoints (or just health/info) exposed — nothing to flag

        management_port = int(port_key["value"]) if _is_literal(port_key) and port_key["value"].isdigit() else None
        declared_port = sr.get("declared_port")
        same_port_as_app = management_port is None or management_port == declared_port

        is_proxied = is_service_proxied(svc, proxied_services) if proxied_services else None

        if same_port_as_app and is_proxied is True:
            risk = "high"
        elif same_port_as_app:
            risk = "medium"
        else:
            risk = "low"

        evidence = [include_key["key"]]
        if port_key:
            evidence.append(port_key["key"])
        if shutdown_enabled_key:
            evidence.append(shutdown_enabled_key["key"])

        services.append({
            "service": svc,
            "sensitive_endpoints_exposed": sensitive_exposed,
            "exposure_is_wildcard": is_wildcard,
            "management_port": management_port,
            "management_address": address_key["value"] if _is_literal(address_key) else None,
            "same_port_as_app": same_port_as_app,
            "externally_proxied": is_proxied,
            "legacy_security_disabled": _is_literal(legacy_security_key) and legacy_security_key["value"].lower() == "false",
            "risk": risk,
            "evidence": evidence,
        })

    known_gaps = [
        "Whether the management port is actually reachable from outside the host is a network/firewall "
        "configuration this tool cannot verify — same-port-as-app and Nginx-proxy status are the best "
        "static signals available.",
        "Custom Spring Security configuration (HttpSecurity/SecurityFilterChain rules) that separately "
        "restricts /actuator/** is not parsed — only the framework-level exposure.include/exclude "
        "configuration is checked (see the existing Security Posture limitation).",
        "Per-endpoint enablement (management.endpoint.<name>.enabled=false) can further restrict "
        "availability beyond what exposure.include lists — not cross-referenced here except for the "
        "shutdown endpoint's required explicit enable flag.",
    ]

    return {"services": services, "known_gaps": known_gaps}
