"""Three-way service wiring cross-check — Nginx upstream targets, the
frontend's configured API base URLs, and the set of services actually present
in this jar-of-jars bundle are three independent sources describing the same
wiring. Currently displayed separately; this flags when a service referenced
by Nginx or the frontend doesn't correspond to any real sub-report in the
bundle, rather than silently trusting the reference. See
Documentation/jar_analyser_dissection_accuracy_plan.md, Stage 3.3.

Deliberately name-based, not port-based: Nginx upstream server values are
almost always unresolved placeholders (e.g. ``${parts.catalog.port}``), not
literal port numbers, so comparing declared_port against them would mostly
compare a number against a template string. Service-name existence is the
part of the wiring that's actually checkable without live data.
"""
from __future__ import annotations

import re

# Common naming-convention transforms seen between nginx upstream keys / frontend
# config keys and a sub-report's own service_name (e.g. "serviceInstances" vs
# "service-instances", "catalog-svc" vs "catalog").
_SUFFIXES = re.compile(r"(-upstream|-svc|Svc)$")
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _normalise(name: str) -> str:
    name = _SUFFIXES.sub("", name)
    name = _CAMEL_BOUNDARY.sub("-", name)
    return name.lower()


def check_service_wiring_consistency(sub_reports: list[dict]) -> list[dict]:
    """sub_reports: list of dicts with keys service_name, jar_type, installer_metadata."""
    real_services = {
        _normalise(sr["service_name"])
        for sr in sub_reports
        if sr.get("service_name")
    }
    if not real_services:
        return []

    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for sr in sub_reports:
        meta = sr.get("installer_metadata") or {}

        nginx = meta.get("nginx")
        if nginx:
            for dep in (nginx.get("service_dependencies") or []):
                norm = _normalise(dep)
                if norm and norm not in real_services and (sr.get("filename"), norm) not in seen:
                    seen.add((sr.get("filename"), norm))
                    findings.append({
                        "type": "nginx_references_unknown_service",
                        "source_file": sr.get("filename"),
                        "referenced_service": dep,
                        "note": (
                            f"Nginx config in {sr.get('filename')} routes to a service "
                            f"'{dep}' that has no matching service in this bundle — either a "
                            f"naming-convention mismatch worth normalising, or this JAR-of-jars "
                            f"upload genuinely doesn't include that service."
                        ),
                    })

        frontend = meta.get("frontend")
        if frontend:
            for entry in (frontend.get("api_urls") or []):
                key = entry.get("key", "")
                first_segment = key.split(".", 1)[0] if key else ""
                if not first_segment:
                    continue
                norm = _normalise(first_segment)
                if norm and norm not in real_services and (sr.get("filename"), norm) not in seen:
                    seen.add((sr.get("filename"), norm))
                    findings.append({
                        "type": "frontend_references_unknown_service",
                        "source_file": sr.get("filename"),
                        "referenced_service": first_segment,
                        "config_key": key,
                        "note": (
                            f"Frontend config key '{key}' in {sr.get('filename')} appears to "
                            f"reference a service '{first_segment}' that has no matching service "
                            f"in this bundle."
                        ),
                    })

    return findings
