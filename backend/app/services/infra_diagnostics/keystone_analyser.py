"""Keystone infrastructure diagnostic analyser."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.services.infra_diagnostics.infra_analyser_base import (
    _finding, _missing_required, build_summary, dedupe_sort, run_shared_passes,
)
from app.services.infra_diagnostics.keystone_questionnaire import get_questionnaire


def analyse(
    responses: dict[str, str],
    report_context: dict | None = None,
) -> dict[str, Any]:
    sections = get_questionnaire()
    findings, cert_results, port_results, log_findings = run_shared_passes(responses, sections)

    findings += _check_token_endpoint(responses)
    findings += _check_service_account(responses)
    findings += _check_role_assignments(responses)
    findings += _check_endpoint_catalogue(responses)
    findings += _check_fernet_keys(responses)

    if report_context:
        findings += _cross_reference(responses, report_context)

    findings = dedupe_sort(findings)
    missing = _missing_required(responses, sections)

    return {
        "service":          "keystone",
        "cert_results":     cert_results,
        "port_results":     port_results,
        "log_findings":     log_findings,
        "config_issues":    [],
        "findings":         findings,
        "missing_required": missing,
        "summary":          build_summary(findings, cert_results, port_results, log_findings, responses, sections),
        "ai_summary":       None,
    }


# ---------------------------------------------------------------------------

def _check_token_endpoint(responses: dict[str, str]) -> list[dict]:
    text = responses.get("keystone.port_check", "").strip()
    if not text:
        return []
    # curl -w "%{http_code}" returns just the status code
    code_m = re.search(r"\b(\d{3})\b", text)
    if not code_m:
        return []
    code = int(code_m.group(1))
    if code == 0 or code == 0:
        return [_finding(
            category="Service", severity="critical", source="service_check", service="keystone",
            message="Keystone token endpoint is unreachable (curl returned 000 — connection refused or DNS failure).",
            item_id="keystone.port_check",
            fix_steps=["Check Keystone / Apache is running: systemctl status apache2",
                       "Verify the hostname resolves: nslookup <keystone_host>"],
        )]
    if 200 <= code < 400:
        return []  # healthy
    sev_map = {503: "critical", 502: "critical", 500: "critical", 401: "high", 403: "high"}
    sev = sev_map.get(code, "critical")
    return [_finding(
        category="Service", severity=sev, source="service_check", service="keystone",
        message=f"Keystone token endpoint returned HTTP {code}.",
        item_id="keystone.port_check",
        fix_steps=["Check Keystone logs: tail -n 100 /var/log/keystone/keystone.log",
                   "Check Apache logs: journalctl -u apache2 -n 50 --no-pager"],
    )]


def _check_service_account(responses: dict[str, str]) -> list[dict]:
    text = responses.get("keystone.user_show", "")
    if not text.strip():
        return []
    findings = []
    user = responses.get("keystone.param.service_user", "<service_user>")
    if re.search(r"No user with a name or ID|Not Found|HTTP 404", text, re.IGNORECASE):
        findings.append(_finding(
            category="Auth", severity="critical", source="service_check", service="keystone",
            message=f"Service account '{user}' does not exist in Keystone.",
            item_id="keystone.user_show",
            fix_steps=[f"openstack user create --domain default --password <password> {user}",
                       f"openstack role add --user {user} --project <project> <role>"],
        ))
        return findings
    if re.search(r"enabled\s*\|\s*False|enabled.*False", text, re.IGNORECASE):
        findings.append(_finding(
            category="Auth", severity="critical", source="service_check", service="keystone",
            message=f"Service account '{user}' is disabled in Keystone.",
            item_id="keystone.user_show",
            fix_steps=[f"openstack user set --enable {user}"],
        ))
    return findings


def _check_role_assignments(responses: dict[str, str]) -> list[dict]:
    text = responses.get("keystone.role_assignments", "")
    if not text.strip():
        return []
    user = responses.get("keystone.param.service_user", "<service_user>")
    project = responses.get("keystone.param.project", "<project>")
    # Empty table — header row only or truly empty
    lines = [l for l in text.splitlines() if l.strip() and not re.match(r"^[+\-|]+$", l.strip())]
    data_lines = [l for l in lines if not re.search(r"Role\s*\|\s*User\s*\|\s*Group", l, re.IGNORECASE)]
    if not data_lines:
        return [_finding(
            category="Auth", severity="critical", source="service_check", service="keystone",
            message=f"Service account '{user}' has no role assignments on project '{project}'. Authentication will fail.",
            item_id="keystone.role_assignments",
            fix_steps=[f"openstack role add --user {user} --project {project} member"],
        )]
    return []


def _check_endpoint_catalogue(responses: dict[str, str]) -> list[dict]:
    text = responses.get("keystone.endpoint_list", "")
    if not text.strip():
        return []
    findings = []
    if not re.search(r"identity", text, re.IGNORECASE):
        findings.append(_finding(
            category="Configuration", severity="critical", source="service_check", service="keystone",
            message="No identity service endpoint found in the endpoint catalogue.",
            item_id="keystone.endpoint_list",
            fix_steps=["openstack endpoint create --region RegionOne identity public https://<host>:5000/v3",
                       "openstack endpoint create --region RegionOne identity internal https://<host>:5000/v3",
                       "openstack endpoint create --region RegionOne identity admin https://<host>:5000/v3"],
        ))
        return findings
    if re.search(r"localhost|127\.0\.0\.1", text, re.IGNORECASE):
        findings.append(_finding(
            category="Configuration", severity="high", source="service_check", service="keystone",
            message="Identity endpoint URL is localhost-bound. Remote clients cannot reach it.",
            item_id="keystone.endpoint_list",
            fix_steps=["Update the endpoint URL to use the server's real hostname or IP.",
                       "openstack endpoint set --url https://<real_host>:5000/v3 <endpoint_id>"],
        ))
    if re.search(r"False\s*\|.*identity|identity.*\|\s*False", text, re.IGNORECASE):
        findings.append(_finding(
            category="Configuration", severity="critical", source="service_check", service="keystone",
            message="Identity endpoint is disabled in the catalogue.",
            item_id="keystone.endpoint_list",
            fix_steps=["openstack endpoint set --enable <endpoint_id>"],
        ))
    return findings


def _check_fernet_keys(responses: dict[str, str]) -> list[dict]:
    text = responses.get("keystone.fernet_keys", "")
    if not text.strip():
        return []
    findings = []
    # Directory empty or does not exist
    if re.search(r"No such file|cannot access|total 0", text, re.IGNORECASE):
        findings.append(_finding(
            category="Configuration", severity="critical", source="service_check", service="keystone",
            message="Fernet key directory is empty or does not exist. Token issuance will fail.",
            item_id="keystone.fernet_keys",
            fix_steps=["keystone-manage fernet_setup --keystone-user keystone --keystone-group keystone",
                       "keystone-manage fernet_rotate --keystone-user keystone --keystone-group keystone"],
        ))
        return findings
    # Check newest key age — look for dates in ls -la output
    dates = re.findall(r"(\w{3}\s+\d+\s+\d{2}:\d{2}|\w{3}\s+\d+\s+\d{4})", text)
    if dates:
        try:
            now = datetime.now(timezone.utc)
            for d in dates:
                try:
                    # Try "Jan 15 14:32" (current year) or "Jan 15 2024"
                    if re.search(r"\d{4}$", d):
                        dt = datetime.strptime(d, "%b %d %Y").replace(tzinfo=timezone.utc)
                    else:
                        dt = datetime.strptime(f"{d} {now.year}", "%b %d %H:%M %Y").replace(tzinfo=timezone.utc)
                    age_hours = (now - dt).total_seconds() / 3600
                    if age_hours > 24:
                        findings.append(_finding(
                            category="Configuration", severity="medium", source="service_check", service="keystone",
                            message=f"Fernet keys may not have been rotated recently (newest key is ~{int(age_hours/24)} days old).",
                            item_id="keystone.fernet_keys",
                            fix_steps=["keystone-manage fernet_rotate --keystone-user keystone --keystone-group keystone"],
                        ))
                        break
                except ValueError:
                    continue
        except Exception:
            pass
    return findings


def _cross_reference(responses: dict[str, str], ctx: dict) -> list[dict]:
    findings = []
    param_host = responses.get("keystone.param.keystone_host", "").strip()
    config_host = ctx.get("keystone_auth_host", "")
    if param_host and config_host and param_host != config_host:
        findings.append(_finding(
            category="Configuration", severity="medium", source="cross_reference", service="keystone",
            message=f"Application Keystone auth URL host ({config_host}) differs from the host being diagnosed ({param_host}).",
            item_id="keystone.param.keystone_host",
        ))

    param_project = responses.get("keystone.param.project", "").strip()
    config_project = ctx.get("keystone_project", "")
    if param_project and config_project and param_project != config_project:
        findings.append(_finding(
            category="Configuration", severity="medium", source="cross_reference", service="keystone",
            message=f"Application Keystone project ('{config_project}') differs from the project being diagnosed ('{param_project}').",
            item_id="keystone.param.project",
        ))
    return findings
