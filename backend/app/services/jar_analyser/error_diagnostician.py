"""Context-aware error diagnostician for JAR Analyser.

Takes an error text + report data and produces enriched diagnosis:
  - KB entry match
  - context_findings: specific services/endpoints/config keys from the report
  - suggested_actions: actionable next steps referencing report data
"""
from __future__ import annotations
import re
from typing import Any


# ── Context rule helpers ─────────────────────────────────────────────────────

def _ssl_context(error_text: str, sub_dicts: list[dict]) -> list[dict]:
    """Find SSL-related config keys across all services, including host/port."""
    findings: list[dict] = []
    ssl_keys = ("keystore", "truststore", "ssl.key", "ssl.cert", "ssl.trust",
                "javax.net.ssl", "server.ssl")
    host_keys = ("server.address", "spring.application.name", "hostname", "host")
    for sub in sub_dicts:
        svc = sub.get("service_name") or sub.get("filename", "")
        port = sub.get("declared_port")
        # Collect hostname hint from config
        hostname_hint: str | None = None
        for cfg in sub.get("config_files", []):
            for k in cfg.get("keys", []):
                key_lower = (k.get("key") or "").lower()
                if any(h in key_lower for h in host_keys) and k.get("value"):
                    val = k["value"]
                    if not val.startswith("${"):
                        hostname_hint = val
                        break
            if hostname_hint:
                break
        for cfg in sub.get("config_files", []):
            for k in cfg.get("keys", []):
                key = (k.get("key") or "").lower()
                val = k.get("value") or ""
                if any(s in key for s in ssl_keys):
                    findings.append({
                        "service": svc,
                        "sub_report_id": sub.get("sub_report_id", ""),
                        "config_file": cfg.get("filename", ""),
                        "config_key": k.get("key", ""),
                        "value": val,
                        "is_placeholder": k.get("is_placeholder", False),
                        "declared_port": port,
                        "hostname_hint": hostname_hint or svc,
                    })
    return findings


def _auth_context(error_text: str, sub_dicts: list[dict]) -> list[dict]:
    """Find endpoints with auth requirements — most relevant for 401/403/JWT errors."""
    findings: list[dict] = []
    # Try to extract a path hint from the error text
    path_hint = None
    m = re.search(r'(/[a-zA-Z0-9/_\-\.]+)', error_text)
    if m:
        path_hint = m.group(1).lower()

    for sub in sub_dicts:
        svc = sub.get("service_name") or sub.get("filename", "")
        for ep in sub.get("endpoints", []):
            sec = ep.get("security")
            if not sec:
                continue
            pa = sec.get("parsed_auth") or {}
            path = (ep.get("full_path") or "").lower()
            # Include if path matches hint, or include all secured endpoints (capped)
            if path_hint and path_hint not in path and path not in path_hint:
                continue
            roles = pa.get("roles", [])
            authorities = pa.get("authorities", [])
            public = pa.get("public", False)
            findings.append({
                "service": svc,
                "method": ep.get("http_method", ""),
                "path": ep.get("full_path", ""),
                "endpoint_id": ep.get("id", ""),
                "sub_report_id": sub.get("sub_report_id", ""),
                "roles_required": roles,
                "authorities_required": authorities,
                "is_public": public,
                "expression": sec.get("expression", ""),
            })
    # If no path hint matched, return top 10 secured endpoints
    if not findings and not path_hint:
        for sub in sub_dicts:
            svc = sub.get("service_name") or sub.get("filename", "")
            for ep in sub.get("endpoints", [])[:20]:
                sec = ep.get("security")
                if sec and not (sec.get("parsed_auth") or {}).get("public"):
                    pa = sec.get("parsed_auth") or {}
                    findings.append({
                        "service": svc,
                        "method": ep.get("http_method", ""),
                        "path": ep.get("full_path", ""),
                        "endpoint_id": ep.get("id", ""),
                        "sub_report_id": sub.get("sub_report_id", ""),
                        "roles_required": pa.get("roles", []),
                        "authorities_required": pa.get("authorities", []),
                        "is_public": False,
                        "expression": sec.get("expression", ""),
                    })
            if len(findings) >= 10:
                break
    return findings[:10]


def _placeholder_context(error_text: str, sub_dicts: list[dict]) -> list[dict]:
    """Find the specific placeholder variable mentioned in the error."""
    findings: list[dict] = []
    # Extract ${VAR_NAME} or 'VAR_NAME' from error text
    var_names: list[str] = []
    for m in re.finditer(r"\$\{([A-Z0-9_]+)[^}]*\}", error_text):
        var_names.append(m.group(1))
    for m in re.finditer(r"'([A-Z][A-Z0-9_]{2,})'", error_text):
        var_names.append(m.group(1))

    if not var_names:
        return []

    for sub in sub_dicts:
        svc = sub.get("service_name") or sub.get("filename", "")
        for cfg in sub.get("config_files", []):
            for k in cfg.get("keys", []):
                val = k.get("value") or ""
                for var in var_names:
                    if var in val:
                        findings.append({
                            "service": svc,
                            "sub_report_id": sub.get("sub_report_id", ""),
                            "config_file": cfg.get("filename", ""),
                            "config_key": k.get("key", ""),
                            "var_name": var,
                            "raw_value": val,
                            "has_default": ":" in val.split(var, 1)[-1].split("}")[0] if var in val else False,
                        })
    return findings


def _flyway_context(error_text: str, sub_dicts: list[dict]) -> list[dict]:
    """List migration scripts — flag any that appear in multiple reports (checksum risk)."""
    findings: list[dict] = []
    for sub in sub_dicts:
        svc = sub.get("service_name") or sub.get("filename", "")
        for m in sub.get("migration_scripts", []):
            findings.append({
                "service": svc,
                "sub_report_id": sub.get("sub_report_id", ""),
                "filename": m.get("filename", ""),
                "version": m.get("version", ""),
                "description": m.get("description", ""),
                "ddl_operations": m.get("ddl_operations", []),
                "tables_affected": m.get("tables_affected", []),
            })
    return findings[:20]


def _db_context(error_text: str, sub_dicts: list[dict]) -> list[dict]:
    """Find DB connection config keys."""
    findings: list[dict] = []
    db_keys = ("datasource.url", "datasource.username", "datasource.password",
               "datasource.hikari", "jdbc", "spring.jpa")
    for sub in sub_dicts:
        svc = sub.get("service_name") or sub.get("filename", "")
        for cfg in sub.get("config_files", []):
            for k in cfg.get("keys", []):
                key = (k.get("key") or "").lower()
                if any(s in key for s in db_keys):
                    findings.append({
                        "service": svc,
                        "sub_report_id": sub.get("sub_report_id", ""),
                        "config_file": cfg.get("filename", ""),
                        "config_key": k.get("key", ""),
                        "value": k.get("value") or "",
                        "is_placeholder": k.get("is_placeholder", False),
                    })
    return findings[:15]


def _rabbitmq_context(error_text: str, sub_dicts: list[dict]) -> list[dict]:
    """Find RabbitMQ connection config keys."""
    findings: list[dict] = []
    rmq_keys = ("rabbitmq.host", "rabbitmq.port", "rabbitmq.username",
                "rabbitmq.password", "rabbitmq.virtual-host", "amqp")
    for sub in sub_dicts:
        svc = sub.get("service_name") or sub.get("filename", "")
        for cfg in sub.get("config_files", []):
            for k in cfg.get("keys", []):
                key = (k.get("key") or "").lower()
                if any(s in key for s in rmq_keys):
                    findings.append({
                        "service": svc,
                        "sub_report_id": sub.get("sub_report_id", ""),
                        "config_file": cfg.get("filename", ""),
                        "config_key": k.get("key", ""),
                        "value": k.get("value") or "",
                        "is_placeholder": k.get("is_placeholder", False),
                    })
    return findings[:15]


def _http_context(error_text: str, sub_dicts: list[dict]) -> list[dict]:
    """Find service URLs and port config relevant to HTTP client errors."""
    findings: list[dict] = []
    url_keys = ("url", "host", "port", "base-url", "endpoint", "uri")
    for sub in sub_dicts:
        svc = sub.get("service_name") or sub.get("filename", "")
        port = sub.get("declared_port")
        if port:
            findings.append({
                "service": svc,
                "sub_report_id": sub.get("sub_report_id", ""),
                "declared_port": port,
                "config_key": "server.port",
                "value": str(port),
            })
        for cfg in sub.get("config_files", []):
            for k in cfg.get("keys", []):
                key = (k.get("key") or "").lower()
                val = k.get("value") or ""
                if any(s in key for s in url_keys) and ("http" in val.lower() or val.isdigit()):
                    findings.append({
                        "service": svc,
                        "sub_report_id": sub.get("sub_report_id", ""),
                        "config_file": cfg.get("filename", ""),
                        "config_key": k.get("key", ""),
                        "value": val,
                        "is_placeholder": k.get("is_placeholder", False),
                    })
    return findings[:15]


# ── Suggested actions ────────────────────────────────────────────────────────

def _ssl_actions(findings: list[dict], sub_dicts: list[dict],
                 kb_entry_id: str = "") -> list[dict]:
    """Generate SSL-specific actions with deep-link params keyed by KB entry ID."""
    actions: list[dict] = []

    # Collect per-service host/port from findings or sub_dicts
    services_with_port: list[tuple[str, str, int | None]] = []
    seen_svcs: set[str] = set()
    for f in findings:
        svc = f.get("service", "")
        if svc not in seen_svcs:
            seen_svcs.add(svc)
            services_with_port.append((svc, f.get("hostname_hint") or svc, f.get("declared_port")))
    if not services_with_port:
        for sub in sub_dicts:
            svc = sub.get("service_name") or sub.get("filename", "")
            if svc not in seen_svcs:
                seen_svcs.add(svc)
                services_with_port.append((svc, svc, sub.get("declared_port")))

    # ssl-001 / ssl-005: PKIX / trust store errors → TrustStore builder + remote check
    if kb_entry_id in ("ssl-001", "ssl-005", ""):
        for f in findings[:2]:
            if "truststore" in (f.get("config_key") or "").lower():
                actions.append({
                    "label": f"Build/verify trust store for {f['service']}",
                    "description": (
                        f"Config key `{f['config_key']}` = `{f['value'] or '(not set)'}`. "
                        "Use the TrustStore builder to create a merged cacerts + internal CA trust store."
                    ),
                    "cert_manager_tool": "keystore",
                    "cert_manager_params": {"service": f["service"]},
                })
        if services_with_port:
            svc, host, port = services_with_port[0]
            actions.append({
                "label": f"Inspect live TLS certificate on {host}:{port or '443'}",
                "description": "Use Remote Server Check to fetch and inspect the certificate chain presented by the service.",
                "cert_manager_tool": "remote",
                "cert_manager_params": {"host": host, "port": port or 443},
            })

    # ssl-002: Handshake failure → Java TLS debug command generator
    elif kb_entry_id == "ssl-002":
        for f in findings[:2]:
            if "truststore" in (f.get("config_key") or "").lower():
                actions.append({
                    "label": f"Build trust store for {f['service']}",
                    "description": f"Config key `{f['config_key']}` = `{f['value'] or '(not set)'}`.",
                    "cert_manager_tool": "keystore",
                    "cert_manager_params": {"service": f["service"]},
                })
        actions.append({
            "label": "Generate Java TLS debug command",
            "description": "Use the Java TLS Debug tool to generate the -Djavax.net.debug=ssl:handshake JVM flag command for your service.",
            "cert_manager_tool": "javadebug",
            "cert_manager_params": {},
        })
        if services_with_port:
            svc, host, port = services_with_port[0]
            actions.append({
                "label": f"Run TLS connection test on {host}:{port or '443'}",
                "description": "Use the Connection Test tool to simulate a full TLS handshake and identify protocol/cipher mismatches.",
                "cert_manager_tool": "conntest",
                "cert_manager_params": {"host": host, "port": port or 443},
            })

    # ssl-003: Certificate expired → remote check pre-filled with host:port
    elif kb_entry_id == "ssl-003":
        if services_with_port:
            svc, host, port = services_with_port[0]
            actions.append({
                "label": f"Check live certificate expiry on {host}:{port or '443'}",
                "description": "Use Remote Server Check to confirm the certificate is expired and see the exact expiry date.",
                "cert_manager_tool": "remote",
                "cert_manager_params": {"host": host, "port": port or 443},
            })
        actions.append({
            "label": "Renew the certificate via CSR renewal",
            "description": "Use the CSR tool's renewal flow to generate a new CSR from the existing certificate, preserving the CN and SANs.",
            "cert_manager_tool": "csr",
            "cert_manager_params": {},
        })

    # ssl-004: Hostname mismatch → decode cert + CSR generator pre-filled with service CN
    elif kb_entry_id == "ssl-004":
        actions.append({
            "label": "Decode certificate and inspect SANs",
            "description": "Use the Certificate Decoder to view the current SANs and confirm which hostnames are covered.",
            "cert_manager_tool": "decode",
            "cert_manager_params": {},
        })
        if services_with_port:
            svc, host, port = services_with_port[0]
            actions.append({
                "label": f"Generate new CSR for {host}",
                "description": f"Use the CSR generator to create a new certificate request with the correct SANs for {host}.",
                "cert_manager_tool": "csr",
                "cert_manager_params": {"cn": host},
            })

    # ssl-006: Keystore integrity / wrong password → PKCS#12 builder
    elif kb_entry_id == "ssl-006":
        for f in findings[:2]:
            if "keystore" in (f.get("config_key") or "").lower():
                actions.append({
                    "label": f"Rebuild keystore for {f['service']}",
                    "description": (
                        f"Config key `{f['config_key']}` = `{f['value'] or '(not set)'}`. "
                        "Re-export the keystore from the SSL Cert Manager if the file may be corrupted."
                    ),
                    "cert_manager_tool": "p12",
                    "cert_manager_params": {},
                })

    # Fallback: generic trust store + remote check
    else:
        for f in findings[:2]:
            key_lower = (f.get("config_key") or "").lower()
            if "truststore" in key_lower:
                actions.append({
                    "label": f"Build trust store for {f['service']}",
                    "description": f"Config key `{f['config_key']}` = `{f['value'] or '(not set)'}`.",
                    "cert_manager_tool": "keystore",
                    "cert_manager_params": {"service": f["service"]},
                })
            elif "keystore" in key_lower:
                actions.append({
                    "label": f"Rebuild keystore for {f['service']}",
                    "description": f"Config key `{f['config_key']}` = `{f['value'] or '(not set)'}`.",
                    "cert_manager_tool": "p12",
                    "cert_manager_params": {},
                })
        if services_with_port:
            svc, host, port = services_with_port[0]
            actions.append({
                "label": f"Run remote TLS check on {host}:{port or '443'}",
                "description": "Use Remote Server Check to inspect the live TLS certificate.",
                "cert_manager_tool": "remote",
                "cert_manager_params": {"host": host, "port": port or 443},
            })
    return actions


def _auth_actions(findings: list[dict], sub_dicts: list[dict]) -> list[dict]:
    if not findings:
        return [{
            "label": "Review endpoint auth requirements",
            "description": "Use the Endpoints tab in the sub-report and filter by Auth to see which roles are required.",
            "cert_manager_tool": None,
            "cert_manager_params": {},
        }]
    roles = sorted({r for f in findings for r in f.get("roles_required", [])})
    return [{
        "label": "Check required roles",
        "description": f"Endpoints in this report require roles: {', '.join(roles) if roles else '(see endpoints tab)'}. Ensure the token includes the correct role claim.",
        "cert_manager_tool": None,
        "cert_manager_params": {},
    }]


def _placeholder_actions(findings: list[dict], sub_dicts: list[dict]) -> list[dict]:
    if not findings:
        return []
    return [{
        "label": f"Set environment variable {f['var_name']}",
        "description": f"Used by {f['service']} as `{f['config_key']}`. {'Has a default value.' if f.get('has_default') else 'No default — this variable is REQUIRED.'}",
        "cert_manager_tool": None,
        "cert_manager_params": {},
    } for f in findings[:5]]


def _flyway_actions(findings: list[dict], sub_dicts: list[dict]) -> list[dict]:
    return [{
        "label": "Run flyway repair",
        "description": "If a migration script was edited after being applied, run `flyway repair` to reset the checksum. Never edit applied migration scripts — create a new version instead.",
        "cert_manager_tool": None,
        "cert_manager_params": {},
    }]


def _db_actions(findings: list[dict], sub_dicts: list[dict]) -> list[dict]:
    return [{
        "label": "Verify database connection config",
        "description": "Check datasource URL, username, and password in application config. Ensure the database server is running and reachable.",
        "cert_manager_tool": None,
        "cert_manager_params": {},
    }]


def _rmq_actions(findings: list[dict], sub_dicts: list[dict]) -> list[dict]:
    return [{
        "label": "Verify RabbitMQ connection config",
        "description": "Check spring.rabbitmq.host, port, username, and password. Ensure RabbitMQ is running and the vhost permissions are correct.",
        "cert_manager_tool": None,
        "cert_manager_params": {},
    }]


def _http_actions(findings: list[dict], sub_dicts: list[dict]) -> list[dict]:
    return [{
        "label": "Verify target service is running",
        "description": "Check the configured URL and ensure the target service is healthy. Use the service port inventory to confirm expected ports.",
        "cert_manager_tool": None,
        "cert_manager_params": {},
    }]


# ── Category → context rule mapping ─────────────────────────────────────────

_CONTEXT_RULES: dict[str, tuple] = {
    "SSL/TLS":               (_ssl_context,         _ssl_actions),
    "Spring Security/Auth":  (_auth_context,        _auth_actions),
    "Database/Flyway":       (_db_context,          _db_actions),
    "RabbitMQ":              (_rabbitmq_context,    _rmq_actions),
    "HTTP Client":           (_http_context,        _http_actions),
    "Spring Boot Startup":   (_db_context,          _db_actions),  # most boot failures are DB-related
}

# Special override: placeholder errors always use placeholder context
_PLACEHOLDER_PATTERN = re.compile(
    r"Could not resolve placeholder|Unresolvable circular reference|\$\{[A-Z0-9_]+\}",
    re.IGNORECASE,
)
_FLYWAY_PATTERN = re.compile(r"FlywayException|checksum mismatch|Validate failed", re.IGNORECASE)


# ── Public API ───────────────────────────────────────────────────────────────

def _diagnose_one(
    query_text: str, pattern_text: str, sub_dicts: list[dict], kb_entries: list[dict] | None,
    seen_kb_ids: set[str], matched_exception: dict[str, Any] | None,
) -> list[dict]:
    """One root-cause unit's own KB search + context enrichment — factored
    out of diagnose() so it can run once per exception in a chain rather
    than once for the whole pasted blob. `query_text` is what the KB search
    itself runs against (narrow: this exception's own class+message, or the
    raw paste when there's nothing narrower); `pattern_text` is what the
    placeholder/flyway override checks run against (kept as the full raw
    paste even when query_text is narrower, since those checks are cheap and
    a false negative there is worse than the narrowing helps)."""
    from app.services.jar_analyser.error_kb import search_kb

    kb_results = search_kb(query_text, db_entries=kb_entries, limit=5)
    diagnoses: list[dict] = []
    for kb_entry in kb_results:
        if kb_entry.get("id") in seen_kb_ids:
            continue
        seen_kb_ids.add(kb_entry.get("id"))
        category = kb_entry.get("category", "")

        # Override context rule for specific error patterns
        if _PLACEHOLDER_PATTERN.search(pattern_text):
            ctx_fn, act_fn = _placeholder_context, _placeholder_actions
        elif _FLYWAY_PATTERN.search(pattern_text):
            ctx_fn, act_fn = _flyway_context, _flyway_actions
        else:
            ctx_fn, act_fn = _CONTEXT_RULES.get(category, (_http_context, _http_actions))

        findings = ctx_fn(query_text, sub_dicts)
        kb_id = kb_entry.get("id", "")
        actions = act_fn(findings, sub_dicts, kb_id) if ctx_fn is _ssl_context else act_fn(findings, sub_dicts)

        diagnoses.append({
            "kb_entry": kb_entry,
            "context_findings": findings,
            "suggested_actions": actions,
            "matched_exception": matched_exception,
        })
    return diagnoses


def diagnose(
    error_text: str, sub_dicts: list[dict], kb_entries: list[dict] | None = None,
    frame_class_index: dict[str, str] | None = None,
) -> list[dict]:
    """Run KB lookup + context enrichment.

    Parses error_text into its exception chain first (stack_trace_parser.py
    — the same parser Docs' Decode tab uses), same reasoning as there: a
    "Caused by:" root cause's own text shouldn't get diluted by matching KB
    patterns against the whole raw paste including the outer wrapper
    exception's own unrelated text. Each independent root cause (there can
    be more than one if several unrelated incidents were pasted together)
    is searched separately and deduped by KB entry id.

    frame_class_index (dotted class_name -> sub_report_id, scoped to this
    one report — see _build_frame_class_index in jar_analyser.py) lets each
    root cause's own frames correlate back to exactly which of this report's
    services it came from; context_findings are then scoped to just those
    correlated services rather than every service in the report, whenever
    that correlation actually finds something. A pasted snippet with no real
    "at ..." frames (most short/manually-typed error descriptions) can't
    correlate anything, so it falls back to searching the whole report
    exactly as before.

    Returns a list of diagnosis results, one per KB match, each with:
      - kb_entry: the matched KB entry
      - context_findings: list of report-specific findings
      - suggested_actions: list of actionable next steps
      - matched_exception: which parsed exception this came from (kind/
        exception_class/message), or None when error_text didn't parse into
        a real trace and the whole raw paste was used instead
    """
    from app.services.stack_trace_parser import extract_stack_traces

    blocks = extract_stack_traces(error_text)
    root_causes = [b for b in blocks if b.is_likely_root_cause]

    seen_kb_ids: set[str] = set()
    diagnoses: list[dict] = []

    if not root_causes:
        # Not a real copy-pasted trace (no "at ..." frames/header this parser
        # recognises) — same whole-blob behaviour this function always had.
        return _diagnose_one(error_text, error_text, sub_dicts, kb_entries, seen_kb_ids, None)

    for block in root_causes:
        query = ": ".join(p for p in (block.exception_class, block.message) if p) or error_text
        correlated_sub_ids = {
            frame_class_index[f.class_name] for f in block.frames if f.class_name in (frame_class_index or {})
        }
        scoped_sub_dicts = (
            [s for s in sub_dicts if s.get("sub_report_id") in correlated_sub_ids]
            if correlated_sub_ids else sub_dicts
        )
        matched_exception = {"kind": block.kind, "exception_class": block.exception_class, "message": block.message}
        diagnoses += _diagnose_one(query, error_text, scoped_sub_dicts, kb_entries, seen_kb_ids, matched_exception)

    return diagnoses
