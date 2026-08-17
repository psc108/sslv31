"""Shared analysis passes for infrastructure diagnostic analysers.

Wraps the existing questionnaire_analyser helpers so cert, port, and log
scan logic is not duplicated across the three service analysers.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.jar_analyser.questionnaire_analyser import (
    _analyse_cert_text,
    _parse_port_response,
    _scan_log_text,
)

# Item-id suffixes / substrings that trigger each pass
_CERT_TRIGGERS = (".cert", ".ssl", ".live_cert", "ca_cert", "server_cert")
_PORT_TRIGGERS = (".port", ".port_amqps", ".port_amqp", ".port_check")
_LOG_TRIGGERS  = (".error_log", ".service_status", ".broker_status")

# Map item-id → port number for port parsing
_PORT_MAP: dict[str, str] = {
    "mysql.port":          "3306",
    "rabbitmq.port_amqps": "5671",
    "rabbitmq.port_amqp":  "5672",
    "keystone.port_check": "5000",
}


def run_shared_passes(
    responses: dict[str, str],
    sections: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Run cert, port, and log passes over all responses.

    Returns (findings, cert_results, port_results, log_findings).
    """
    findings: list[dict] = []
    cert_results: list[dict] = []
    port_results: list[dict] = []
    log_findings: list[dict] = []

    service = _infer_service(sections)

    for item_id, text in responses.items():
        if not text or not text.strip():
            continue

        # --- cert pass ---
        if any(t in item_id for t in _CERT_TRIGGERS):
            cr = _analyse_cert_text(item_id, text)
            if cr:
                cr["service"] = service
                cert_results.append(cr)
                for w in cr.get("warnings", []):
                    findings.append(_finding(
                        category="SSL/TLS",
                        severity="critical" if "EXPIRED" in w else "high",
                        source="cert_analysis",
                        service=service,
                        message=w,
                        item_id=item_id,
                        ai_annotations=None,
                    ))

        # --- port pass ---
        if any(item_id.endswith(t) for t in _PORT_TRIGGERS):
            port = _PORT_MAP.get(item_id, "unknown")
            # keystone port_check returns an HTTP status code, not ss output
            if item_id == "keystone.port_check":
                # handled by keystone analyser — skip generic port parse
                pass
            else:
                pr = _parse_port_response(item_id, text, port)
                pr["service"] = service
                port_results.append(pr)
                if not pr["open"]:
                    findings.append(_finding(
                        category="Connectivity",
                        severity="high",
                        source="port_check",
                        service=service,
                        message=f"Port {port} is CLOSED or not listening",
                        item_id=item_id,
                        ai_annotations=None,
                    ))

        # --- log scan pass ---
        if any(item_id.endswith(t) for t in _LOG_TRIGGERS):
            lf = _scan_log_text(item_id, text, [])
            for f in lf:
                f["service"] = service
            log_findings.extend(lf)
            for lf_item in lf:
                findings.append(_finding(
                    category=lf_item["kb_category"],
                    severity=lf_item["kb_severity"],
                    source="log_scan",
                    service=service,
                    message=lf_item["kb_title"],
                    item_id=lf_item["source_item"],
                    causes=lf_item.get("causes", []),
                    fix_steps=lf_item.get("fix_steps", []),
                    trigger_line=lf_item.get("trigger_line", ""),
                    ai_annotations=None,
                ))

    return findings, cert_results, port_results, log_findings


def build_summary(
    findings: list[dict],
    cert_results: list[dict],
    port_results: list[dict],
    log_findings: list[dict],
    responses: dict[str, str],
    sections: list[dict],
) -> dict[str, Any]:
    missing = _missing_required(responses, sections)
    return {
        "total_findings": len(findings),
        "critical": sum(1 for f in findings if f.get("severity") == "critical"),
        "high":     sum(1 for f in findings if f.get("severity") == "high"),
        "medium":   sum(1 for f in findings if f.get("severity") == "medium"),
        "low":      sum(1 for f in findings if f.get("severity") == "low"),
        "cert_files_analysed":    len(cert_results),
        "log_items_scanned":      len({lf["source_item"] for lf in log_findings}),
        "ports_checked":          len(port_results),
        "missing_required_count": len(missing),
        "response_count":         sum(1 for v in responses.values() if v.strip()),
    }


def dedupe_sort(findings: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for f in findings:
        key = f"{f.get('category')}:{f.get('message', '')[:80]}"
        if key not in seen:
            seen.add(key)
            out.append(f)
    sev = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    out.sort(key=lambda x: sev.get(x.get("severity", "low"), 3))
    return out


def _finding(
    *,
    category: str,
    severity: str,
    source: str,
    service: str,
    message: str,
    item_id: str = "",
    causes: list[str] | None = None,
    fix_steps: list[str] | None = None,
    trigger_line: str = "",
    ai_annotations: None = None,
) -> dict[str, Any]:
    return {
        "category":      category,
        "severity":      severity,
        "source":        source,
        "service":       service,
        "message":       message,
        "item_id":       item_id,
        "causes":        causes or [],
        "fix_steps":     fix_steps or [],
        "trigger_line":  trigger_line,
        "ai_annotations": ai_annotations,
    }


def _missing_required(responses: dict[str, str], sections: list[dict]) -> list[str]:
    missing = []
    for sec in sections:
        for item in sec.get("items", []):
            if item.get("required") and not responses.get(item["id"], "").strip():
                missing.append(item["id"])
    return missing


def _infer_service(sections: list[dict]) -> str:
    for sec in sections:
        for item in sec.get("items", []):
            iid = item.get("id", "")
            if "." in iid:
                return iid.split(".")[0]
    return "unknown"
