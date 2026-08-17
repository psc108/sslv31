"""JAR Analyser — auto-generated platform reference document.

A fuller, narrative-oriented sibling to export.py's report_to_markdown().
Renders data this tool already extracts but the concise tabular export
doesn't surface: the per-service "Perceived Purpose" narrative
(purpose_narrative.py), installer/bundle metadata (part.yml, bundled Nginx/
monitoring/frontend config), and report-level infrastructure requirements
(IAM/database/messaging) and actuator-exposure/consistency findings.

No new extraction happens here — every section is a rendering of an
existing field on the report/sub-report dicts (see
backend/app/api/v1/jar_analyser.py's get_report()/_sub_full()). Matches this
tool's existing discipline of never inventing facts: the "Deployment Facts"
section only lists directly observed values (declared ports, part.yml
firewallPorts/templates, cloud-SDK dependency hints) — no resource-sizing or
instance-type guidance, since that isn't derivable from the jar itself.
"""
from __future__ import annotations

import textwrap

from app.services.jar_analyser.export import sub_report_to_markdown

# Long single-line paragraphs/bullets (purpose-narrative sentences, evidence
# lists, consistency-finding notes) are hard to read as one unbroken line in
# a plain text editor — wrapped to this width. Table rows and code fences are
# deliberately never wrapped here: breaking a "| a | b | c |" row mid-cell or
# a fenced code block would corrupt the Markdown/content itself.
_WRAP_WIDTH = 100


def _wrap(text: str, initial_indent: str = "", subsequent_indent: str = "") -> str:
    return textwrap.fill(
        text, width=_WRAP_WIDTH,
        initial_indent=initial_indent, subsequent_indent=subsequent_indent,
        break_long_words=False, break_on_hyphens=False,
    )


def _bullet(text: str) -> str:
    return _wrap(text, initial_indent="- ", subsequent_indent="  ")


def _sub_bullet(text: str) -> str:
    return _wrap(text, initial_indent="  - ", subsequent_indent="    ")


def _quote(text: str) -> str:
    # Every physical line of a Markdown blockquote needs its own "> " prefix.
    return _wrap(text, initial_indent="> ", subsequent_indent="> ")


def _v(d: dict, key: str, default: str = "N/A") -> str:
    """dict.get() with a real fallback for both missing keys AND keys
    explicitly stored as None — plain .get(key, default) only covers the
    former, so a present-but-null field (e.g. a nginx_installer's
    declared_port) renders as the literal string "None" instead."""
    val = d.get(key)
    return val if val not in (None, "") else default


_CLOUD_VENDOR_HINTS = [
    (("aws", "amazonaws"), "AWS"),
    (("azure",), "Azure"),
    (("google", "gcp"), "Google Cloud"),
]


def _cloud_dependency_hints(sr: dict) -> list[dict]:
    """Same recognition as purpose_narrative.py's _dependency_fingerprint,
    reimplemented against a plain dict — that module runs at analysis time
    against SubReportData objects; this renders already-persisted API dicts."""
    hints: list[dict] = []
    for d in sr.get("dependencies", []):
        if d.get("category") != "cloud_sdk":
            continue
        haystack = f"{d.get('group_id') or ''} {d.get('artifact_id') or ''}".lower()
        vendor = next((v for tokens, v in _CLOUD_VENDOR_HINTS if any(t in haystack for t in tokens)), None)
        if vendor:
            hints.append({"vendor": vendor, "artifact": d.get("artifact_id") or d.get("filename")})
    return hints


_JAR_TYPE_GROUP_LABELS = {
    "library": "Backend Services",
    "spring_boot_fat": "Backend Services",
    "nginx_installer": "Load Balancers",
    "monitoring_installer": "Infrastructure & Monitoring Services",
    "frontend_installer": "Frontend / UI Services",
}
_GROUP_ORDER = [
    "Backend Services", "Frontend / UI Services", "Load Balancers",
    "Infrastructure & Monitoring Services", "Other Services",
]


def _service_group_label(sr: dict) -> str:
    """part.yml's own group field when present (checked live: often empty
    on older stored analyses) — falls back to a jar_type-derived label,
    which is reliably populated and gives a reasonable proxy grouping."""
    return sr.get("group_name") or _JAR_TYPE_GROUP_LABELS.get(sr.get("jar_type"), "Other Services")


def _service_db_label(sr: dict, report: dict) -> str | None:
    svc = sr.get("service_name") or sr.get("filename")
    db_info = ((report.get("infra_requirements") or {}).get("database") or {}).get("per_service", {}).get(svc)
    if not db_info:
        return None
    name = db_info.get("database_name")
    tables = len(db_info.get("tables") or [])
    if name:
        return f"`{name}` ({tables} table(s))" if tables else f"`{name}`"
    if tables:
        return f"dedicated schema ({tables} table(s), name externally parameterised)"
    return None


def _condensed_purpose(sr: dict) -> str | None:
    """A short (2-4 sentence) prose paragraph synthesised from the same
    evidence purpose_narrative.py already computed for _purpose_section —
    reused here as structured data (each statement's `evidence` field) not
    its pre-rendered verbose `text`, so it reads as connected prose instead
    of a bullet dump. Genuinely inferred content still hedges ("appears
    to"/"is"); is_inference=False facts (authored docs) are stated plainly.
    Returns None when there's no narrative at all (e.g. an nginx/monitoring/
    frontend installer with no Java bytecode to analyse) — the caller falls
    back to facts-only for those, same as the hand-written doc's shorter
    treatment of grafana/prometheus."""
    statements = sr.get("purpose_narrative") or []
    if not statements:
        return None
    by_category = {s.get("category"): s for s in statements}
    sentences: list[str] = []

    authored = by_category.get("authored_intent")
    if authored and isinstance(authored.get("evidence"), list) and authored["evidence"]:
        sentences.append(f"{authored['evidence'][0].rstrip('.')}.")

    vocab = by_category.get("domain_vocabulary")
    if vocab:
        terms = [t.get("term") for t in (vocab.get("evidence") or [])[:3] if t.get("term")]
        if terms:
            sentences.append(f"Appears to manage data related to {', '.join(terms)}.")

    topology = by_category.get("event_topology")
    if topology:
        role = (topology.get("evidence") or {}).get("role")
        if role:
            sentences.append(f"It is {role}.")

    ownership = by_category.get("db_ownership")
    if ownership:
        count = (ownership.get("evidence") or {}).get("migration_count")
        if count:
            sentences.append(f"Owns {count} database table(s) via its own Flyway migrations.")

    posture = by_category.get("auth_posture")
    if posture:
        ev = posture.get("evidence") or {}
        total, admin_gated, public = ev.get("total", 0), ev.get("admin_gated", 0), ev.get("public", 0)
        if admin_gated and not public:
            sentences.append(
                f"Most of its {total} endpoints are role/authority-gated, suggesting an "
                "internal/administrative audience."
            )
        elif public and not admin_gated:
            sentences.append(f"Most of its {total} endpoints are public, suggesting general end-user consumption.")

    return " ".join(sentences) if sentences else None


def _service_facts_bullets(sr: dict, report: dict) -> list[str]:
    """Compact facts block matching the hand-written reference doc's own
    per-service format (Install path / Group / Port / Database / Events
    published) — replaces scattered detail across multiple sections with
    one short list a new reader can skim."""
    lines: list[str] = []
    meta = sr.get("installer_metadata") or {}
    install_path = meta.get("install_path") or sr.get("install_path")
    if install_path:
        lines.append(_bullet(f"**Install path:** `{install_path}`"))
    lines.append(_bullet(f"**Group:** {_service_group_label(sr)}"))

    declared_port = sr.get("declared_port")
    if declared_port:
        lines.append(_bullet(f"**Port:** {declared_port}"))
    fw_ports = meta.get("firewall_ports") or []
    if fw_ports and {str(p) for p in fw_ports} != ({str(declared_port)} if declared_port else set()):
        lines.append(_bullet(f"**Firewall ports (part.yml):** {', '.join(str(p) for p in fw_ports)}"))

    db_label = _service_db_label(sr, report)
    if db_label:
        lines.append(_bullet(f"**Database:** {db_label}"))

    statements = sr.get("purpose_narrative") or []
    topology = next((s for s in statements if s.get("category") == "event_topology"), None)
    if topology:
        published = (topology.get("evidence") or {}).get("published_count", 0)
        if published:
            lines.append(_bullet(
                f"**Events published:** {published} event type(s) — see Technical Reference for detail"
            ))
    return lines


def _service_catalogue_section(report: dict, sub_reports: list[dict]) -> list[str]:
    """The onboarding-facing counterpart to the "Per-Service Detail"
    technical-reference section further down: short paragraph + compact
    facts per service, grouped under readable headers, ending in a
    skimmable summary table — matching the hand-written reference doc's
    Part 2 shape rather than the tabular/evidence-bullet style everywhere
    else in this document."""
    lines = ["## Service Catalogue", ""]
    groups: dict[str, list[dict]] = {}
    for sr in sub_reports:
        groups.setdefault(_service_group_label(sr), []).append(sr)
    ordered_labels = [g for g in _GROUP_ORDER if g in groups] + sorted(g for g in groups if g not in _GROUP_ORDER)

    summary_rows: list[tuple[str, str, str, str, str, str]] = []
    for label in ordered_labels:
        lines += [f"### {label}", ""]
        for sr in sorted(groups[label], key=lambda s: s.get("service_name") or s.get("filename") or ""):
            name = sr.get("service_name") or sr.get("filename", "unknown")
            port = sr.get("declared_port")
            lines.append(f"#### {name} (Port {port})" if port else f"#### {name}")
            lines.append("")

            paragraph = _condensed_purpose(sr)
            summary_text = "—"
            if paragraph:
                lines.append(_wrap(paragraph))
                lines.append("")
                summary_text = paragraph.split(". ")[0].rstrip(".") + "."

            lines += _service_facts_bullets(sr, report)
            lines.append("")

            meta = sr.get("installer_metadata") or {}
            install_path = meta.get("install_path") or sr.get("install_path") or "—"
            db_label = _service_db_label(sr, report) or "—"
            summary_short = summary_text if len(summary_text) <= 80 else summary_text[:79] + "…"
            summary_rows.append((name, str(port) if port else "—", label, install_path, db_label, summary_short))

    lines += ["### Service Summary Table", "", "| Service | Port | Group | Install Path | DB | Summary |",
              "|---|---|---|---|---|---|"]
    for name, port, label, install_path, db_label, summary_short in summary_rows:
        lines.append(f"| {name} | {port} | {label} | `{install_path}` | {db_label} | {summary_short} |")
    lines.append("")
    return lines


def _overview_section(report: dict) -> list[str]:
    upload = report.get("jar_file", {})
    manifest = report.get("manifest", {})
    summary = report.get("summary", {})
    ports = summary.get("ports_detected", []) or []

    return [
        f"# Platform Reference: {_v(upload, 'original_filename', 'unknown')}",
        "",
        f"**Version:** {_v(manifest, 'implementation_version')}  ",
        f"**Vendor:** {_v(manifest, 'implementation_vendor')}  ",
        f"**JAR Type:** {_v(report, 'jar_type')}  ",
        f"**Spring Boot:** {_v(manifest, 'spring_boot_version')}  ",
        f"**Java:** {_v(manifest, 'java_version_required')} "
        f"(built with {_v(manifest, 'build_jdk')})  ",
        f"**SHA256:** `{_v(upload, 'sha256')}`",
        "",
        "## Overview",
        "",
        _wrap(
            f"This package is a `{report.get('jar_type', 'unknown')}` bundling "
            f"{summary.get('nested_jar_count', 0)} service(s), exposing "
            f"{summary.get('total_endpoint_count', 0)} HTTP endpoint(s) across "
            f"{len(ports)} declared port(s)"
            + (f" ({', '.join(str(p) for p in ports)})" if ports else "")
            + f", with {summary.get('total_dependency_count', 0)} bundled dependencies, "
            f"{summary.get('total_config_key_count', 0)} configuration keys, and "
            f"{summary.get('total_migration_script_count', 0)} database migration script(s) "
            "across all services."
        ),
        "",
        _quote(
            "Generated automatically by the JAR Analyser from static analysis of the uploaded "
            "artifact. Every statement in this document is either a directly observed fact or an "
            "explicitly hedged inference — nothing is invented or AI-generated. New to this "
            "platform? Start with the Service Catalogue below — it's the readable walkthrough. "
            "The Technical Reference section further down has the exhaustive per-endpoint/"
            "dependency/migration detail for when you need to verify something specific."
        ),
        "",
    ]


def _topology_section(sub_reports: list[dict]) -> list[str]:
    lines = ["## Service Topology", "", "| Service | Group | Port | Type |", "|---|---|---|---|"]
    groups: dict[str, list[dict]] = {}
    for sr in sub_reports:
        groups.setdefault(_service_group_label(sr), []).append(sr)
    ordered_labels = [g for g in _GROUP_ORDER if g in groups] + sorted(g for g in groups if g not in _GROUP_ORDER)
    for label in ordered_labels:
        for sr in sorted(groups[label], key=lambda s: s.get("service_name") or s.get("filename") or ""):
            name = sr.get("service_name") or sr.get("filename", "unknown")
            lines.append(f"| {name} | {label} | {_v(sr, 'declared_port', '—')} | {_v(sr, 'jar_type', '—')} |")
    lines.append("")
    return lines


def _tech_stack_section(report: dict, sub_reports: list[dict]) -> list[str]:
    manifest = report.get("manifest", {})
    lines = [
        "## Technology Stack",
        "",
        f"- **Spring Boot:** {_v(manifest, 'spring_boot_version')}",
        f"- **Java:** {_v(manifest, 'java_version_required')}",
        f"- **Build JDK:** {_v(manifest, 'build_jdk')}",
        "",
    ]
    category_counts: dict[str, int] = {}
    for sr in sub_reports:
        for d in sr.get("dependencies", []):
            cat = d.get("category") or "other"
            category_counts[cat] = category_counts.get(cat, 0) + 1
    if category_counts:
        lines += ["### Dependency Categories (across all services)", "", "| Category | Count |", "|---|---|"]
        for cat, count in sorted(category_counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {cat} | {count} |")
        lines.append("")
    return lines


def _purpose_section(sr: dict) -> list[str]:
    statements = sr.get("purpose_narrative") or []
    if not statements:
        return []
    lines = ["### Perceived Purpose", ""]
    for s in statements:
        marker = " *(inferred)*" if s.get("is_inference") else ""
        lines.append(_bullet(f"{s.get('text', '')}{marker}"))
        evidence = s.get("evidence")
        if isinstance(evidence, list) and evidence and isinstance(evidence[0], str):
            lines.append(_sub_bullet(f"Evidence: {'; '.join(evidence)}"))
    lines.append("")
    return lines


def _installer_metadata_section(sr: dict) -> list[str]:
    meta = sr.get("installer_metadata") or {}
    if not meta:
        return []
    lines = ["### Installer / Bundle Metadata", ""]

    if meta.get("install_path") or meta.get("firewall_ports") or meta.get("templates") or meta.get("build_info"):
        lines.append(_bullet(f"**Install path:** `{_v(meta, 'install_path')}`"))
        ports = meta.get("firewall_ports") or []
        if ports:
            lines.append(_bullet(f"**Firewall ports (part.yml):** {', '.join(str(p) for p in ports)}"))
        templates = meta.get("templates") or []
        if templates:
            template_names = ", ".join(
                (t.get("ref") or str(t)) if isinstance(t, dict) else str(t) for t in templates
            )
            lines.append(_bullet(f"**Bundled templates:** {template_names}"))
        build_info = meta.get("build_info") or {}
        if build_info:
            build_str = ", ".join(f"{k}: {v}" for k, v in build_info.items())
            lines.append(_bullet(f"**Build info:** {build_str}"))
        lines.append("")

    nginx = meta.get("nginx")
    if nginx:
        lines += ["**Nginx configuration:**", ""]
        upstreams = nginx.get("upstreams") or []
        if upstreams:
            lines += ["| Upstream | Servers | Keepalive |", "|---|---|---|"]
            for u in upstreams:
                lines.append(f"| {u.get('name')} | {', '.join(u.get('servers') or [])} | {_v(u, 'keepalive', '—')} |")
            lines.append("")
        for block in nginx.get("server_blocks") or []:
            ssl_flag = "yes" if block.get("ssl") else "no"
            lines.append(_bullet(
                f"Server block: ports {block.get('listen_ports')}, "
                f"names {block.get('server_names')}, SSL: {ssl_flag}"
            ))
        lines.append("")

    monitoring = meta.get("monitoring")
    if monitoring:
        lines += ["**Monitoring configuration:**", ""]
        dashboards = monitoring.get("grafana_dashboards") or []
        if dashboards:
            lines.append(_bullet(
                f"Grafana dashboards: {', '.join(d.get('title') or d.get('filename') for d in dashboards)}"
            ))
        jobs = monitoring.get("prometheus_jobs") or []
        if jobs:
            lines.append(_bullet(
                "Prometheus jobs: "
                + ", ".join(f"{j.get('job_name')} (TLS: {'yes' if j.get('has_tls') else 'no'})" for j in jobs)
            ))
        lines.append("")

    frontend = meta.get("frontend")
    if frontend:
        lines += [
            "**Frontend configuration:**",
            "",
            _bullet(
                f"Framework: {_v(frontend, 'framework')} "
                f"(package `{_v(frontend, 'package_name')}` v{_v(frontend, 'package_version')})"
            ),
        ]
        api_urls = frontend.get("api_urls") or []
        if api_urls:
            lines.append(f"- API URLs referenced: {len(api_urls)}")
        lines.append("")

    return lines


def _deployment_facts_section(sr: dict) -> list[str]:
    """Directly-derivable deployment-relevant facts only — no invented
    resource-sizing or instance-type guidance (see module docstring)."""
    meta = sr.get("installer_metadata") or {}
    ports = meta.get("firewall_ports") or []
    declared_port = sr.get("declared_port")
    cloud_hints = _cloud_dependency_hints(sr)

    if not ports and not declared_port and not cloud_hints:
        return []

    lines = ["### Deployment Facts", ""]
    if declared_port:
        lines.append(_bullet(f"**Declared application port:** {declared_port}"))
    if ports:
        lines.append(_bullet(f"**Firewall ports (part.yml):** {', '.join(str(p) for p in ports)}"))
    for hint in cloud_hints:
        lines.append(_bullet(f"**Cloud SDK dependency:** `{hint['artifact']}` — suggests integration with {hint['vendor']}"))
    lines.append("")
    return lines


def _infra_requirements_section(report: dict) -> list[str]:
    infra = report.get("infra_requirements")
    if not infra:
        return []
    lines = ["## Platform Infrastructure Requirements", ""]

    iam = infra.get("iam") or {}
    if iam.get("requirements"):
        lines += ["### IAM Roles & Authorities", "", "| Kind | Name | References | Services |", "|---|---|---|---|"]
        for r in iam["requirements"]:
            lines.append(f"| {r.get('kind')} | {r.get('name')} | {r.get('reference_count')} | "
                         f"{', '.join(r.get('services') or [])} |")
        lines.append("")
    conn = iam.get("connection") or {}
    if conn.get("auth_url"):
        lines.append(f"- **IAM connection:** `{conn['auth_url']}`"
                     + (f" (project: `{conn['project_name']}`)" if conn.get("project_name") else ""))
        lines.append("")

    database = infra.get("database") or {}
    if database.get("requirements"):
        lines += ["### Databases", "", "| Database | Owning Service(s) | Tables |", "|---|---|---|"]
        for r in database["requirements"]:
            lines.append(f"| {r.get('database_name')} | {', '.join(r.get('services') or [])} | "
                         f"{len(r.get('tables') or [])} |")
        lines.append("")
    if database.get("collisions"):
        lines.append(_quote("⚠️ Multiple services declare the same database name — confirm intentional sharing:"))
        for c in database["collisions"]:
            lines.append(_wrap(
                f"`{c.get('database_name')}`: {', '.join(c.get('services') or [])}",
                initial_indent="> - ", subsequent_indent=">   ",
            ))
        lines.append("")

    messaging = infra.get("messaging") or {}
    if messaging.get("requirements"):
        lines += ["### Messaging (RabbitMQ)", "", "| Service | Virtual Host | SSL | Role |", "|---|---|---|---|"]
        for r in messaging["requirements"]:
            ssl = "yes" if r.get("ssl_enabled") else ("no" if r.get("ssl_enabled") is False else "—")
            lines.append(f"| {r.get('service')} | {_v(r, 'virtual_host', '—')} | {ssl} | {_v(r, 'role', '—')} |")
        lines.append("")

    for section, label in ((iam, "IAM"), (database, "Database"), (messaging, "Messaging")):
        for gap in section.get("known_gaps") or []:
            lines.append(_quote(f"**{label} — known limitation:** {gap}"))
            lines.append("")

    return lines


def _actuator_exposure_section(report: dict) -> list[str]:
    exposure = report.get("actuator_exposure")
    if not exposure or not exposure.get("services"):
        return []
    lines = ["## Actuator / Management Endpoint Exposure", "",
             "| Service | Sensitive Endpoints Exposed | Risk | Same Port as App |",
             "|---|---|---|---|"]
    for s in exposure["services"]:
        lines.append(f"| {s.get('service')} | {', '.join(s.get('sensitive_endpoints_exposed') or [])} | "
                     f"{_v(s, 'risk', '—')} | {'yes' if s.get('same_port_as_app') else 'no'} |")
    lines.append("")
    return lines


def _consistency_findings_section(report: dict) -> list[str]:
    findings = report.get("consistency_findings")
    if not findings:
        return []
    lines = ["## Static Consistency Findings", ""]
    for f in findings:
        lines.append(_bullet(f"**{f.get('type', 'finding')}:** {f.get('note', '')}"))
    lines.append("")
    return lines


def report_to_reference_doc(report: dict, sub_reports: list[dict]) -> str:
    lines: list[str] = []
    lines += _overview_section(report)
    lines += _topology_section(sub_reports)
    lines += _tech_stack_section(report, sub_reports)
    lines += _service_catalogue_section(report, sub_reports)
    lines += _infra_requirements_section(report)
    lines += _actuator_exposure_section(report)
    lines += _consistency_findings_section(report)

    lines += [
        "## Technical Reference — Per-Service Detail", "",
        _wrap(
            "Exhaustive per-service detail — every endpoint, dependency, configuration key, "
            "migration script, and event definition, plus the full evidence trail behind each "
            "Perceived Purpose statement above. Use this section to verify a specific fact; the "
            "Service Catalogue above is the better starting point for getting oriented."
        ),
        "",
    ]
    for sr in sub_reports:
        lines.append(sub_report_to_markdown(sr))
        lines += _purpose_section(sr)
        lines += _installer_metadata_section(sr)
        lines += _deployment_facts_section(sr)

    return "\n".join(lines)
