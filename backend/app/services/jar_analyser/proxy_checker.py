"""Proxy checker — determines which services are reachable via the Nginx proxy.

A service is considered proxied if its normalised name appears in the
`service_dependencies` list of any nginx_installer sub-report in the bundle.

`service_dependencies` is already extracted by the nginx config parser and
lists every upstream service name the load-balancer routes traffic to.
"""
from __future__ import annotations

import re


def _normalise(name: str) -> str:
    """Strip common suffixes so 'catalog-svc' and 'catalog' resolve to the same token."""
    return re.sub(r"-svc$|-upstream$|-service$|-installer$", "", name.lower().strip())


def build_proxied_services(sub_reports: list[dict]) -> set[str]:
    """
    sub_reports: list of dicts with keys: service_name, jar_type, installer_metadata

    Returns a set of normalised service names that are reachable via Nginx.
    """
    proxied: set[str] = set()
    for sr in sub_reports:
        if sr.get("jar_type") != "nginx_installer":
            continue
        meta = sr.get("installer_metadata") or {}
        nginx = meta.get("nginx") or {}
        for svc in nginx.get("service_dependencies", []):
            proxied.add(_normalise(svc))
        # Also cover upstream names as a fallback
        for upstream in nginx.get("upstreams", []):
            name = upstream.get("name", "")
            proxied.add(_normalise(name))
    return proxied


def is_service_proxied(service_name: str | None, proxied_services: set[str]) -> bool:
    """Return True if the given service name is in the proxied set."""
    if not service_name or not proxied_services:
        return False
    return _normalise(service_name) in proxied_services
