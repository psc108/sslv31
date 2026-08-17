"""Analyse questionnaire responses submitted via the manual collection flow.

Responses is a dict of {item_id: text_value}.  We run the same analysis
passes as diagnostics_analyser but against pasted text rather than files
extracted from a tar.gz bundle.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


# ── Cert analysis (mirrors diagnostics_analyser._analyse_cert_file) ──────────

def _analyse_cert_text(item_id: str, text: str) -> dict[str, Any] | None:
    if not text.strip():
        return None
    result: dict[str, Any] = {"item_id": item_id, "entries": [], "warnings": []}

    # openssl x509 -text output
    if "Certificate:" in text and "Validity" in text:
        not_after = re.search(r"Not After\s*:\s*(.+)", text)
        not_before = re.search(r"Not Before\s*:\s*(.+)", text)
        subject = re.search(r"Subject:\s*(.+)", text)
        issuer = re.search(r"Issuer:\s*(.+)", text)
        sans = re.findall(r"DNS:([^\s,]+)", text)
        entry: dict[str, Any] = {
            "type": "certificate",
            "subject": subject.group(1).strip() if subject else "",
            "issuer": issuer.group(1).strip() if issuer else "",
            "not_before": not_before.group(1).strip() if not_before else "",
            "not_after": not_after.group(1).strip() if not_after else "",
            "sans": sans,
        }
        if not_after:
            try:
                exp_str = not_after.group(1).strip()
                exp = datetime.strptime(exp_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                days = (exp - datetime.now(timezone.utc)).days
                entry["days_remaining"] = days
                entry["expired"] = days < 0
                if days < 0:
                    result["warnings"].append(f"Certificate EXPIRED {abs(days)} days ago")
                elif days < 30:
                    result["warnings"].append(f"Certificate expires in {days} days")
            except Exception:
                pass
        result["entries"].append(entry)

    # keytool -list output (grep-filtered or full)
    elif "trustedCertEntry" in text or "Keystore type:" in text or "Entry type:" in text:
        result["type"] = "keystore"
        aliases = re.findall(r"^(\S+),\s+\w+ \d+, \d{4},", text, re.MULTILINE)
        result["aliases"] = aliases
        result["alias_count"] = len(aliases)
        exp_dates = re.findall(r"until:\s*(.+)", text)
        result["expiry_dates"] = [d.strip() for d in exp_dates]
        if not aliases:
            result["warnings"].append("Keystore appears empty — no aliases found")

    # Minimal grep output (Subject/Issuer/Not After lines only)
    elif re.search(r"Not After\s*:", text):
        not_after = re.search(r"Not After\s*:\s*(.+)", text)
        not_before = re.search(r"Not Before\s*:\s*(.+)", text)
        subject = re.search(r"Subject\s*:\s*(.+)", text)
        issuer = re.search(r"Issuer\s*:\s*(.+)", text)
        sans = re.findall(r"DNS:([^\s,]+)", text)
        entry = {
            "type": "certificate",
            "subject": subject.group(1).strip() if subject else "",
            "issuer": issuer.group(1).strip() if issuer else "",
            "not_before": not_before.group(1).strip() if not_before else "",
            "not_after": not_after.group(1).strip() if not_after else "",
            "sans": sans,
        }
        if not_after:
            try:
                exp_str = not_after.group(1).strip()
                exp = datetime.strptime(exp_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                days = (exp - datetime.now(timezone.utc)).days
                entry["days_remaining"] = days
                entry["expired"] = days < 0
                if days < 0:
                    result["warnings"].append(f"Certificate EXPIRED {abs(days)} days ago")
                elif days < 30:
                    result["warnings"].append(f"Certificate expires in {days} days")
            except Exception:
                pass
        result["entries"].append(entry)
    else:
        return None

    return result


# ── Port status ───────────────────────────────────────────────────────────────

def _parse_port_response(item_id: str, text: str, port: str | int) -> dict[str, Any]:
    text_upper = text.strip().upper()
    open_ = "OPEN" in text_upper and "CLOSED" not in text_upper
    return {"item_id": item_id, "port": str(port), "status": "OPEN" if open_ else "CLOSED", "open": open_}


# ── Log scan ──────────────────────────────────────────────────────────────────

def _scan_log_text(item_id: str, text: str, report_sub_dicts: list[dict], kb_entries: list[dict] | None = None) -> list[dict]:
    from app.services.jar_analyser.error_kb import search_kb

    lines = text.splitlines()
    findings: list[dict] = []
    seen_ids: set[str] = set()

    window, step = 100, 50
    for i in range(0, max(1, len(lines) - window + 1), step):
        chunk = "\n".join(lines[i:i + window])
        for m in search_kb(chunk, db_entries=kb_entries, limit=3):
            if m["id"] not in seen_ids:
                seen_ids.add(m["id"])
                trigger = ""
                for line in lines[i:i + window]:
                    try:
                        if re.search(m["pattern"], line, re.IGNORECASE):
                            trigger = line.strip()[:200]
                            break
                    except re.error:
                        pass
                findings.append({
                    "source_item": item_id,
                    "kb_entry_id": m["id"],
                    "kb_title": m["title"],
                    "kb_category": m["category"],
                    "kb_severity": m["severity"],
                    "trigger_line": trigger,
                    "causes": m.get("causes", []),
                    "fix_steps": m.get("fix_steps", []),
                })
    return findings


# ── Config validation ─────────────────────────────────────────────────────────

def _validate_config_text(item_id: str, text: str, report_sub_dicts: list[dict]) -> list[dict]:
    issues: list[dict] = []
    unresolved = re.findall(r"\$\{([A-Z0-9_]+)\}", text)
    for var in set(unresolved):
        issues.append({
            "type": "unresolved_placeholder",
            "severity": "high",
            "item_id": item_id,
            "var_name": var,
            "message": f"Placeholder ${{{var}}} is not resolved",
        })

    # Check mandatory vars from report
    for sub in report_sub_dicts:
        svc = sub.get("service_name") or sub.get("filename", "")
        for cfg in sub.get("config_files", []):
            for k in cfg.get("keys", []):
                val = k.get("value") or ""
                if k.get("is_placeholder") and val.startswith("${"):
                    inner = val[2:-1] if val.endswith("}") else val[2:]
                    if ":" not in inner:
                        var_name = inner.strip()
                        if f"${{{var_name}}}" in text:
                            issues.append({
                                "type": "mandatory_var_unset",
                                "severity": "critical",
                                "item_id": item_id,
                                "service": svc,
                                "config_key": k.get("key", ""),
                                "var_name": var_name,
                                "message": f"Mandatory variable {var_name} ({svc}: {k.get('key', '')}) has no default and is unresolved",
                            })
    return issues


# ── Main analyser ─────────────────────────────────────────────────────────────

def analyse_questionnaire_responses(
    responses: dict[str, str],
    sections: list[dict],
    report_sub_dicts: list[dict],
    kb_entries: list[dict] | None = None,
) -> dict[str, Any]:
    """
    responses: {item_id: pasted_text}
    sections:  the questionnaire structure (from questionnaire_generator)
    """
    findings: list[dict] = []
    cert_results: list[dict] = []
    port_results: list[dict] = []
    log_findings: list[dict] = []
    config_issues: list[dict] = []
    os_info: str = ""

    # Build a flat item index for quick lookup
    item_index: dict[str, dict] = {}
    for sec in sections:
        for item in sec.get("items", []):
            item_index[item["id"]] = item

    for item_id, text in responses.items():
        if not text or not text.strip():
            continue

        item = item_index.get(item_id, {})

        # OS info — collect into a single block
        if item_id.startswith("system."):
            os_info += f"\n=== {item.get('label', item_id)} ===\n{text}\n"
            continue

        # Port checks
        if item_id.endswith(".port") or item_id.endswith("_port") or "rabbitmq.port" == item_id:
            # Extract port number from item command or label
            port_match = re.search(r"/(\d{4,5})\b", item.get("command", ""))
            port = port_match.group(1) if port_match else "unknown"
            pr = _parse_port_response(item_id, text, port)
            # Derive service name from item_id prefix
            pr["service"] = item_id.split(".")[0] if "." in item_id else item_id
            port_results.append(pr)
            if not pr["open"]:
                findings.append({
                    "category": "Connectivity",
                    "severity": "high",
                    "source": "questionnaire",
                    "service": pr["service"],
                    "message": f"Port {port} is CLOSED or unreachable",
                    "port": port,
                })
            continue

        # Cert / keystore items
        if ".cert." in item_id or "cacerts" in item_id or "keystore" in item_id.lower():
            cr = _analyse_cert_text(item_id, text)
            if cr:
                cr["service"] = item_id.split(".")[0]
                cert_results.append(cr)
                for w in cr.get("warnings", []):
                    findings.append({
                        "category": "SSL/TLS",
                        "severity": "critical" if "EXPIRED" in w else "high",
                        "source": "questionnaire",
                        "service": cr["service"],
                        "message": w,
                        "item_id": item_id,
                    })
            continue

        # Config files
        if item_id.endswith(".config"):
            issues = _validate_config_text(item_id, text, report_sub_dicts)
            config_issues.extend(issues)
            for ci in issues:
                findings.append({
                    "category": "Configuration",
                    "severity": ci["severity"],
                    "source": "questionnaire",
                    "service": item_id.split(".")[0],
                    "message": ci["message"],
                    "item_id": item_id,
                    "var_name": ci.get("var_name", ""),
                })
            # Also scan config text for log-like errors
            lf = _scan_log_text(item_id, text, report_sub_dicts, kb_entries)
            log_findings.extend(lf)
            continue

        # Journal / status / any other text — scan for known error patterns
        lf = _scan_log_text(item_id, text, report_sub_dicts, kb_entries)
        for f in lf:
            f["service"] = item_id.split(".")[0]
        log_findings.extend(lf)

        # Surface log findings as top-level findings
        for lf_item in lf:
            findings.append({
                "category": lf_item["kb_category"],
                "severity": lf_item["kb_severity"],
                "source": "questionnaire_log_scan",
                "service": lf_item.get("service", ""),
                "message": f"{lf_item['kb_title']}: {lf_item['trigger_line'][:120]}",
                "kb_entry_id": lf_item["kb_entry_id"],
                "kb_title": lf_item["kb_title"],
                "causes": lf_item["causes"],
                "fix_steps": lf_item["fix_steps"],
                "trigger_line": lf_item["trigger_line"],
                "source_item": lf_item["source_item"],
            })

    # Deduplicate findings
    seen: set[str] = set()
    deduped: list[dict] = []
    for f in findings:
        key = f"{f['category']}:{f['message'][:80]}"
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    deduped.sort(key=lambda x: sev_order.get(x.get("severity", "low"), 3))

    # Check for missing required responses
    missing_required: list[str] = []
    for sec in sections:
        for item in sec.get("items", []):
            if item.get("required") and not responses.get(item["id"], "").strip():
                missing_required.append(item["id"])

    return {
        "os_info": os_info.strip(),
        "cert_results": cert_results,
        "port_results": port_results,
        "config_issues": config_issues,
        "log_findings": log_findings,
        "findings": deduped,
        "missing_required": missing_required,
        "summary": {
            "total_findings": len(deduped),
            "critical": sum(1 for f in deduped if f.get("severity") == "critical"),
            "high": sum(1 for f in deduped if f.get("severity") == "high"),
            "medium": sum(1 for f in deduped if f.get("severity") == "medium"),
            "low": sum(1 for f in deduped if f.get("severity") == "low"),
            "cert_files_analysed": len(cert_results),
            "log_items_scanned": len({lf["source_item"] for lf in log_findings}),
            "ports_checked": len(port_results),
            "config_items_checked": sum(1 for k in responses if k.endswith(".config")),
            "missing_required_count": len(missing_required),
            "response_count": sum(1 for v in responses.values() if v.strip()),
        },
    }
