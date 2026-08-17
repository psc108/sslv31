"""Diagnostics analyser — processes an uploaded diagnostic bundle (tar.gz).

Unpacks the bundle, then runs:
  1. SSL cert analysis on every cert/keystore file found
  2. Error KB scan on every log/journal file
  3. Config key validation against the report's expected keys
  4. Port reachability summary
  5. RabbitMQ connectivity summary
  6. OS/JVM environment summary
"""
from __future__ import annotations

import json
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Any


# ── SSL cert analysis ─────────────────────────────────────────────────────────

def _analyse_cert_file(path: Path) -> dict[str, Any]:
    """Parse a keytool -list or openssl x509 -text output file."""
    text = path.read_text(errors="replace")
    result: dict[str, Any] = {"file": path.name, "entries": [], "warnings": []}

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
        # Check expiry
        if not_after:
            try:
                from datetime import datetime, timezone
                exp_str = not_after.group(1).strip()
                # openssl format: "Jan  1 00:00:00 2025 GMT"
                exp = datetime.strptime(exp_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                days = (exp - now).days
                entry["days_remaining"] = days
                entry["expired"] = days < 0
                if days < 0:
                    result["warnings"].append(f"Certificate EXPIRED {abs(days)} days ago")
                elif days < 30:
                    result["warnings"].append(f"Certificate expires in {days} days")
            except Exception:
                pass
        result["entries"].append(entry)

    # keytool -list output
    elif "Keystore type:" in text or "Entry type:" in text or "trustedCertEntry" in text:
        result["type"] = "keystore"
        aliases = re.findall(r"^(\S+),\s+\w+ \d+, \d{4},", text, re.MULTILINE)
        result["aliases"] = aliases
        result["alias_count"] = len(aliases)
        exp_dates = re.findall(r"until:\s*(.+)", text)
        result["expiry_dates"] = [d.strip() for d in exp_dates]
        if not aliases:
            result["warnings"].append("Keystore appears empty — no aliases found")

    return result


# ── Log / journal analysis ────────────────────────────────────────────────────

def _scan_log_for_errors(path: Path, report_sub_dicts: list[dict], kb_entries: list[dict] | None = None) -> list[dict]:
    """Run error KB patterns against a log file, return matches with context."""
    from app.services.jar_analyser.error_kb import search_kb

    try:
        text = path.read_text(errors="replace")
    except Exception:
        return []

    # Split into chunks of ~500 lines to avoid huge KB searches
    lines = text.splitlines()
    findings: list[dict] = []
    seen_ids: set[str] = set()

    # Scan in 100-line windows, stepping 50 lines
    window = 100
    step = 50
    for i in range(0, max(1, len(lines) - window + 1), step):
        chunk = "\n".join(lines[i:i + window])
        matches = search_kb(chunk, db_entries=kb_entries, limit=3)
        for m in matches:
            if m["id"] not in seen_ids:
                seen_ids.add(m["id"])
                # Find the triggering line
                trigger_line = ""
                for line in lines[i:i + window]:
                    try:
                        if re.search(m["pattern"], line, re.IGNORECASE):
                            trigger_line = line.strip()[:200]
                            break
                    except re.error:
                        pass
                findings.append({
                    "source_file": path.name,
                    "kb_entry_id": m["id"],
                    "kb_title": m["title"],
                    "kb_category": m["category"],
                    "kb_severity": m["severity"],
                    "trigger_line": trigger_line,
                    "causes": m.get("causes", []),
                    "fix_steps": m.get("fix_steps", []),
                })

    return findings


# ── Config validation ─────────────────────────────────────────────────────────

def _validate_configs(collected_configs: dict[str, str],
                      report_sub_dicts: list[dict]) -> list[dict]:
    """Compare collected config files against expected keys from the report."""
    issues: list[dict] = []

    # Build expected mandatory placeholders from report
    mandatory_vars: list[dict] = []
    for sub in report_sub_dicts:
        svc = sub.get("service_name") or sub.get("filename", "")
        for cfg in sub.get("config_files", []):
            for k in cfg.get("keys", []):
                val = k.get("value") or ""
                if k.get("is_placeholder") and val.startswith("${"):
                    # Check if mandatory (no default)
                    inner = val[2:-1] if val.endswith("}") else val[2:]
                    has_default = ":" in inner
                    if not has_default:
                        var_name = inner.strip()
                        mandatory_vars.append({
                            "service": svc,
                            "config_key": k.get("key", ""),
                            "var_name": var_name,
                        })

    # Check collected configs for unresolved placeholders
    for fname, content in collected_configs.items():
        unresolved = re.findall(r"\$\{([A-Z0-9_]+)\}", content)
        for var in set(unresolved):
            issues.append({
                "type": "unresolved_placeholder",
                "severity": "high",
                "file": fname,
                "var_name": var,
                "message": f"Placeholder ${{{var}}} is not resolved in {fname}",
            })

    # Check mandatory vars are present in collected configs
    all_content = "\n".join(collected_configs.values())
    for mv in mandatory_vars:
        var = mv["var_name"]
        # If the var appears as a placeholder in collected config, it's unresolved
        if f"${{{var}}}" in all_content:
            issues.append({
                "type": "mandatory_var_unset",
                "severity": "critical",
                "service": mv["service"],
                "config_key": mv["config_key"],
                "var_name": var,
                "message": f"Mandatory variable {var} (used by {mv['service']} as {mv['config_key']}) has no default and appears unresolved",
            })

    return issues


# ── Port summary ──────────────────────────────────────────────────────────────

def _parse_port_results(port_dir: Path) -> list[dict]:
    results: list[dict] = []
    if not port_dir.exists():
        return results
    for f in sorted(port_dir.glob("port_*.txt")):
        status = f.read_text().strip() if f.exists() else "UNKNOWN"
        port_str = f.stem.replace("port_", "")
        results.append({
            "port": port_str,
            "status": status,
            "open": status == "OPEN",
        })
    return results


# ── Main analyser ─────────────────────────────────────────────────────────────

def analyse_diagnostic_bundle(
    bundle_path: Path,
    report_sub_dicts: list[dict],
    kb_entries: list[dict] | None = None,
) -> dict[str, Any]:
    """Unpack bundle and run all analysis passes. Returns structured findings."""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Unpack
        try:
            with tarfile.open(bundle_path, "r:gz") as tf:
                tf.extractall(tmp)
        except Exception as e:
            return {"error": f"Failed to unpack bundle: {e}", "findings": []}

        # Find the root extraction dir (first subdir)
        roots = [d for d in tmp.iterdir() if d.is_dir()]
        root = roots[0] if roots else tmp

        # Read manifest
        manifest: dict = {}
        manifest_path = root / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
            except Exception:
                pass

        # Read capabilities
        capabilities: dict = {}
        cap_path = root / "capabilities.json"
        if cap_path.exists():
            try:
                capabilities = json.loads(cap_path.read_text())
            except Exception:
                pass
        missing_tools = [
            tool for tool, present in capabilities.items()
            if not present and tool in ("openssl", "keytool", "java", "nc", "curl", "ss", "journalctl")
        ]
        limited_collection = bool(missing_tools)

        findings: list[dict] = []
        cert_results: list[dict] = []
        log_findings: list[dict] = []
        config_issues: list[dict] = []
        port_results: list[dict] = []
        os_info: str = ""

        # ── OS info ──────────────────────────────────────────────
        sys_dir = root / "system"
        os_info_path = sys_dir / "os_info.txt"
        if os_info_path.exists():
            os_info = os_info_path.read_text(errors="replace")[:4000]

        # ── JVM cacerts ──────────────────────────────────────────
        cacerts_path = sys_dir / "jvm_cacerts.txt"
        if cacerts_path.exists():
            cr = _analyse_cert_file(cacerts_path)
            cr["source"] = "jvm_cacerts"
            cert_results.append(cr)

        # ── Port results ─────────────────────────────────────────
        port_dir = root / "ports"
        port_results = _parse_port_results(port_dir)

        # ── RabbitMQ ─────────────────────────────────────────────
        rmq_dir = root / "rabbitmq"
        rmq_summary: dict[str, Any] = {}
        if rmq_dir.exists():
            rmq_port_path = rmq_dir / "port.txt"
            if rmq_port_path.exists():
                rmq_summary["port_status"] = rmq_port_path.read_text().strip()
            overview_path = rmq_dir / "overview.json"
            if overview_path.exists():
                try:
                    overview = json.loads(overview_path.read_text())
                    rmq_summary["rabbitmq_version"] = overview.get("rabbitmq_version")
                    rmq_summary["erlang_version"] = overview.get("erlang_version")
                    rmq_summary["node"] = overview.get("node")
                    rmq_summary["message_stats"] = overview.get("message_stats", {})
                except Exception:
                    pass

        # ── Per-service analysis ──────────────────────────────────
        services_dir = root / "services"
        collected_configs: dict[str, str] = {}

        if services_dir.exists():
            for svc_dir in sorted(services_dir.iterdir()):
                if not svc_dir.is_dir():
                    continue
                svc_name = svc_dir.name

                # Cert files
                certs_dir = svc_dir / "certs"
                if certs_dir.exists():
                    for cf in certs_dir.glob("*.txt"):
                        cr = _analyse_cert_file(cf)
                        cr["service"] = svc_name
                        cr["source"] = "service_cert"
                        cert_results.append(cr)

                # Config files
                cfg_dir = svc_dir / "config"
                if cfg_dir.exists():
                    for cf in cfg_dir.iterdir():
                        if cf.is_file():
                            try:
                                content = cf.read_text(errors="replace")
                                collected_configs[f"{svc_name}/{cf.name}"] = content
                            except Exception:
                                pass

                # Log files
                logs_dir = svc_dir / "logs"
                if logs_dir.exists():
                    for lf in logs_dir.glob("*.tail"):
                        lf_findings = _scan_log_for_errors(lf, report_sub_dicts, kb_entries)
                        for f in lf_findings:
                            f["service"] = svc_name
                        log_findings.extend(lf_findings)

                # Journal
                journal = svc_dir / "journal.log"
                if journal.exists() and journal.stat().st_size > 0:
                    jf_findings = _scan_log_for_errors(journal, report_sub_dicts, kb_entries)
                    for f in jf_findings:
                        f["service"] = svc_name
                        f["source_file"] = "journal"
                    log_findings.extend(jf_findings)

                # Per-service port checks
                for pf in svc_dir.glob("port_*.txt"):
                    port_str = pf.stem.replace("port_", "")
                    status = pf.read_text().strip()
                    port_results.append({
                        "service": svc_name,
                        "port": port_str,
                        "status": status,
                        "open": status == "OPEN",
                    })

        # Config validation
        config_issues = _validate_configs(collected_configs, report_sub_dicts)

        # ── Cert expiry warnings as findings ─────────────────────
        for cr in cert_results:
            for w in cr.get("warnings", []):
                findings.append({
                    "category": "SSL/TLS",
                    "severity": "critical" if "EXPIRED" in w else "high",
                    "source": cr.get("source", "cert"),
                    "service": cr.get("service", ""),
                    "message": w,
                    "file": cr.get("file", ""),
                })

        # ── Port closed warnings ──────────────────────────────────
        for pr in port_results:
            if not pr.get("open"):
                findings.append({
                    "category": "Connectivity",
                    "severity": "high",
                    "source": "port_check",
                    "service": pr.get("service", ""),
                    "message": f"Port {pr['port']} is CLOSED or unreachable",
                    "port": pr["port"],
                })

        # ── Config issues as findings ─────────────────────────────
        for ci in config_issues:
            findings.append({
                "category": "Configuration",
                "severity": ci.get("severity", "medium"),
                "source": "config_validation",
                "service": ci.get("service", ""),
                "message": ci["message"],
                "file": ci.get("file", ""),
                "var_name": ci.get("var_name", ""),
            })

        # ── Log findings as top-level findings ────────────────────
        for lf in log_findings:
            findings.append({
                "category": lf["kb_category"],
                "severity": lf["kb_severity"],
                "source": "log_scan",
                "service": lf.get("service", ""),
                "message": f"{lf['kb_title']}: {lf['trigger_line'][:120]}",
                "kb_entry_id": lf["kb_entry_id"],
                "kb_title": lf["kb_title"],
                "causes": lf["causes"],
                "fix_steps": lf["fix_steps"],
                "trigger_line": lf["trigger_line"],
                "source_file": lf["source_file"],
            })

        # Deduplicate findings by (category + message[:80])
        seen_msgs: set[str] = set()
        deduped: list[dict] = []
        for f in findings:
            key = f"{f['category']}:{f['message'][:80]}"
            if key not in seen_msgs:
                seen_msgs.add(key)
                deduped.append(f)

        # Sort by severity
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        deduped.sort(key=lambda x: sev_order.get(x.get("severity", "low"), 3))

        return {
            "manifest": manifest,
            "capabilities": capabilities,
            "limited_collection": limited_collection,
            "missing_tools": missing_tools,
            "os_info": os_info,
            "cert_results": cert_results,
            "port_results": port_results,
            "rmq_summary": rmq_summary,
            "config_issues": config_issues,
            "log_findings": log_findings,
            "findings": deduped,
            "summary": {
                "total_findings": len(deduped),
                "critical": sum(1 for f in deduped if f.get("severity") == "critical"),
                "high": sum(1 for f in deduped if f.get("severity") == "high"),
                "medium": sum(1 for f in deduped if f.get("severity") == "medium"),
                "low": sum(1 for f in deduped if f.get("severity") == "low"),
                "cert_files_analysed": len(cert_results),
                "log_files_scanned": len({lf["source_file"] for lf in log_findings}),
                "ports_checked": len(port_results),
                "config_files_collected": len(collected_configs),
                "limited_collection": limited_collection,
                "missing_tools": missing_tools,
            },
        }
