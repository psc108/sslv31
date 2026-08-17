"""Stage 1 of the infra-requirements plan — IAM / auth-service provisioning
requirements.

Aggregates the same role/authority-per-endpoint evidence that already powers
the live `/reports/{report_id}/auth-requirements` endpoint, reframed as "what
must exist in the IAM service (e.g. Keystone) for this bundle to function"
rather than a live security-posture summary — plus connection facts (auth
URL/project, when a literal value is present — see connection_facts.py) and
an explicit, non-negotiable statement of what this tool cannot determine
(domain/project placement is a deployment decision, not something encoded in
bytecode).
"""
from __future__ import annotations

from app.services.jar_analyser.connection_facts import extract_connection_facts


def compute_iam_requirements(sub_reports: list[dict]) -> dict:
    role_map: dict[str, list[dict]] = {}
    authority_map: dict[str, list[dict]] = {}
    public_count = 0
    unsecured_count = 0

    auth_url: str | None = None
    auth_host: str | None = None
    project_name: str | None = None
    services_with_iam_config: set[str] = set()
    externally_parameterized: dict[str, list[str]] = {}

    for sr in sub_reports:
        svc = sr.get("service_name") or sr.get("filename")

        for ep in sr.get("endpoints", []):
            sec = ep.get("security")
            pa = sec.get("parsed_auth") if sec else None
            if not pa:
                unsecured_count += 1
                continue
            if pa.get("public"):
                public_count += 1
                continue
            if pa.get("deny_all") or pa.get("authenticated_only"):
                continue
            entry = {"service": svc, "method": ep.get("http_method"), "path": ep.get("full_path")}
            for role in pa.get("roles", []):
                role_map.setdefault(role, []).append(entry)
            for authority in pa.get("authorities", []):
                authority_map.setdefault(authority, []).append(entry)

        keys = [k for cfg in sr.get("config_files", []) for k in cfg.get("keys", [])]
        if not keys:
            continue
        iam = extract_connection_facts(keys).iam
        if iam.auth_url or iam.project_name or iam.externally_parameterized_keys:
            services_with_iam_config.add(svc)
        if iam.auth_url and not auth_url:
            auth_url, auth_host = iam.auth_url, iam.auth_host
        if iam.project_name and not project_name:
            project_name = iam.project_name
        if iam.externally_parameterized_keys:
            externally_parameterized[svc] = iam.externally_parameterized_keys

    requirements = [
        {"kind": "role", "name": name, "reference_count": len(entries),
         "services": sorted({e["service"] for e in entries})}
        for name, entries in sorted(role_map.items())
    ] + [
        {"kind": "authority", "name": name, "reference_count": len(entries),
         "services": sorted({e["service"] for e in entries})}
        for name, entries in sorted(authority_map.items())
    ]

    known_gaps = [
        "Which IAM domain or project each role/authority below should belong to, and whether it is a "
        "system-level or project-scoped role, is a deployment decision — not encoded anywhere in the "
        "analysed bytecode.",
    ]
    if not auth_url and not externally_parameterized:
        known_gaps.append(
            "No IAM/auth-service connection configuration (auth URL, project name) was found in this "
            "bundle's config files — services likely authenticate against tokens issued by an external "
            "IAM service that isn't shipped as part of this bundle."
        )

    return {
        "requirements": requirements,
        "connection": {
            "auth_url": auth_url,
            "auth_host": auth_host,
            "project_name": project_name,
            "services_with_iam_config": sorted(services_with_iam_config),
            "externally_parameterized_keys_by_service": externally_parameterized,
        },
        "known_gaps": known_gaps,
        "summary": {
            "unique_role_count": len(role_map),
            "unique_authority_count": len(authority_map),
            "public_endpoint_count": public_count,
            "unsecured_endpoint_count": unsecured_count,
        },
    }
