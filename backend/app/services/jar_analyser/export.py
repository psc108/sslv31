"""JAR Analyser export renderers — Markdown and JSON."""
from __future__ import annotations

import json
import textwrap
from typing import Any

# Wraps long free-text bullet lines (event publish/consume descriptions) so
# the exported document isn't one unbroken line per bullet. Deliberately not
# applied to table rows or code-fenced raw content elsewhere in this module —
# wrapping those would corrupt the Markdown table syntax or the file content
# itself.
_WRAP_WIDTH = 100


def _bullet(text: str) -> str:
    return textwrap.fill(
        text, width=_WRAP_WIDTH, initial_indent="- ", subsequent_indent="  ",
        break_long_words=False, break_on_hyphens=False,
    )


def report_to_json(report: dict, sub_reports: list[dict]) -> str:
    return json.dumps({"report": report, "sub_reports": sub_reports}, indent=2, default=str)


def report_to_markdown(report: dict, sub_reports: list[dict]) -> str:
    lines: list[str] = []
    upload = report.get("jar_file", {})
    manifest = report.get("manifest", {})
    summary = report.get("summary", {})

    lines += [
        f"# JAR Analysis Report: {upload.get('original_filename', 'unknown')}",
        "",
        f"**Version:** {manifest.get('implementation_version', 'N/A')}  ",
        f"**Vendor:** {manifest.get('implementation_vendor', 'N/A')}  ",
        f"**JAR Type:** {report.get('jar_type', 'N/A')}  ",
        f"**Spring Boot:** {manifest.get('spring_boot_version', 'N/A')}  ",
        f"**SHA256:** `{upload.get('sha256', 'N/A')}`  ",
        f"**Analysis Duration:** {report.get('analysis_duration_ms', 0)} ms",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Services | {summary.get('nested_jar_count', 0)} |",
        f"| Endpoints | {summary.get('total_endpoint_count', 0)} |",
        f"| Dependencies | {summary.get('total_dependency_count', 0)} |",
        f"| Config Keys | {summary.get('total_config_key_count', 0)} |",
        f"| Migration Scripts | {summary.get('total_migration_script_count', 0)} |",
        f"| Ports | {', '.join(str(p) for p in summary.get('ports_detected', []))} |",
        "",
    ]

    for sr in sub_reports:
        lines += _sub_report_to_markdown(sr)

    return "\n".join(lines)


def sub_report_to_markdown(sr: dict) -> str:
    return "\n".join(_sub_report_to_markdown(sr))


def diff_to_markdown(diff: dict) -> str:
    lines: list[str] = []
    la = diff.get("label_a", "A")
    lb = diff.get("label_b", "B")
    lines += [
        f"# JAR Diff Report: {la} → {lb}",
        "",
        f"**Baseline:** {la} (`{diff.get('report_a_id', '')[:8]}`)  ",
        f"**Comparison:** {lb} (`{diff.get('report_b_id', '')[:8]}`)  ",
        f"**Generated:** {diff.get('created_at', 'N/A')}",
        "",
        "## Summary",
        "",
    ]
    s = diff.get("summary", {})
    lines += [
        "| Category | Added | Removed | Changed |",
        "|----------|-------|---------|---------|" ,
        f"| Services | {s.get('services_added',0)} | {s.get('services_removed',0)} | {s.get('services_changed',0)} |",
        f"| Endpoints | {s.get('endpoints_added',0)} | {s.get('endpoints_removed',0)} | {s.get('endpoints_changed',0)} |",
        f"| Dependencies | {s.get('dependencies_added',0)} | {s.get('dependencies_removed',0)} | {s.get('dependencies_version_changed',0)} version changes |",
        f"| Config Keys | {s.get('config_keys_added',0)} | {s.get('config_keys_removed',0)} | {s.get('config_keys_changed',0)} |",
        f"| Migrations | {s.get('migration_scripts_added',0)} | {s.get('migration_scripts_removed',0)} | — |",
        "",
    ]
    if s.get("security_changes", 0):
        lines.append(f"> ⚠️ **{s['security_changes']} security change(s) detected**")
        lines.append("")

    for sd in diff.get("service_diffs", []):
        change = sd["change"]
        svc = sd["service_name"]
        prefix = "+" if change == "ADDED" else ("-" if change == "REMOVED" else "~")
        lines.append(f"### {prefix} Service: {svc} [{change}]")
        lines.append("")

        for ep in sd.get("endpoint_diffs", []):
            ec = ep["change"]
            ep_prefix = "+" if ec == "ADDED" else ("-" if ec == "REMOVED" else "~")
            lines.append(f"  {ep_prefix} `{ep['http_method']} {ep['path']}` [{ec}]")
            detail = ep.get("detail") or {}
            for p in detail.get("parameters_added", []):
                lines.append(f"    + param `{p.get('name')}` ({p.get('location','')}) ADDED")
            for p in detail.get("parameters_removed", []):
                lines.append(f"    - param `{p.get('name')}` REMOVED")
            if detail.get("security_changed"):
                sc = detail["security_changed"]
                lines.append(f"    ⚠️ Security changed: `{sc.get('from')}` → `{sc.get('to')}`")

        for dep in sd.get("dependency_diffs", []):
            dc = dep["change"]
            dep_prefix = "+" if dc == "ADDED" else ("-" if dc == "REMOVED" else "~")
            coord = dep.get("maven_coordinates", "")
            if dc == "CHANGED":
                lines.append(f"  {dep_prefix} `{coord}` {dep.get('version_from')} → {dep.get('version_to')}")
            else:
                lines.append(f"  {dep_prefix} `{coord}` {dep.get('version', '')} [{dc}]")

        for cfg in sd.get("config_diffs", []):
            cc = cfg["change"]
            cfg_prefix = "+" if cc == "ADDED" else ("-" if cc == "REMOVED" else "~")
            lines.append(f"  {cfg_prefix} config `{cfg.get('file')}` key `{cfg.get('key')}` [{cc}]")

        for mig in sd.get("migration_diffs", []):
            mc = mig["change"]
            mig_prefix = "+" if mc == "ADDED" else "-"
            lines.append(f"  {mig_prefix} migration `{mig.get('filename')}` [{mc}]")
            if mig.get("warning"):
                lines.append(f"    ⚠️ Migration removed — verify migration order")

        lines.append("")

    warnings = diff.get("warnings", [])
    if warnings:
        lines += ["## Warnings", ""]
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)


def _sub_report_to_markdown(sr: dict) -> list[str]:
    lines: list[str] = []
    name = sr.get("service_name") or sr.get("filename", "unknown")
    lines += [
        f"---",
        f"## Service: {name}",
        "",
        f"**File:** `{sr.get('filename')}`  ",
        f"**Type:** {sr.get('jar_type')}  ",
        f"**Port:** {sr.get('declared_port', 'N/A')}  ",
        f"**Spring Boot:** {sr.get('spring_boot_version', 'N/A')}  ",
        f"**Start Class:** `{sr.get('start_class', 'N/A')}`",
        "",
    ]

    # Endpoints
    endpoints = sr.get("endpoints", [])
    if endpoints:
        lines += ["### Endpoints", ""]
        lines += ["| Method | Path | Controller | Security |",
                  "|--------|------|------------|----------|"]
        for ep in endpoints:
            sec = ep.get("security", {})
            sec_str = sec.get("expression", "") if sec else ""
            lines.append(
                f"| {ep['http_method']} | `{ep['full_path']}` | {ep['controller_simple']} | {sec_str} |"
            )
        lines.append("")

    # Dependencies
    deps = sr.get("dependencies", [])
    if deps:
        lines += ["### Dependencies", ""]
        lines += ["| Group | Artifact | Version | Category |",
                  "|-------|----------|---------|----------|"]
        for d in deps[:50]:  # cap at 50 for readability
            lines.append(
                f"| {d.get('group_id', '')} | {d.get('artifact_id', '')} | {d.get('version', '')} | {d.get('category', '')} |"
            )
        if len(deps) > 50:
            lines.append(f"*... and {len(deps) - 50} more*")
        lines.append("")

    # Config files
    configs = sr.get("config_files", [])
    if configs:
        lines += ["### Configuration Files", ""]
        for cf in configs:
            lines += [
                f"#### `{cf['filename']}`",
                "",
                f"Keys: {cf.get('key_count', 0)} | Encrypted: {cf.get('encrypted_count', 0)} | SSL keys: {cf.get('ssl_key_count', 0)}",
                "",
                "```properties",
                (cf.get("content") or "")[:2000],
                "```",
                "",
            ]

    # Migrations
    migrations = sr.get("migration_scripts", [])
    if migrations:
        lines += ["### Flyway Migrations", ""]
        lines += ["| Version | Description | Statements | Tables |",
                  "|---------|-------------|------------|--------|"]
        for ms in migrations:
            tables = ", ".join(ms.get("tables_affected") or [])
            lines.append(
                f"| {ms.get('version', '')} | {ms.get('description', '')} | {ms.get('statement_count', 0)} | {tables} |"
            )
        lines.append("")

    # Events
    events = sr.get("event_files", [])
    if events:
        lines += ["### Event Definitions", ""]
        published_evs = [ev for ev in events if ev.get("published")]
        consumed_evs  = [ev for ev in events if ev.get("consumed")]
        if published_evs:
            lines.append("**Published:**")
            for ev in published_evs:
                for pub in ev.get("published", []):
                    consumers = ", ".join(pub.get("consumers") or [])
                    lines.append(_bullet(
                        f"`{pub['entity']}` / {', '.join(pub.get('actions', []))} "
                        f"({pub.get('operation', '')}) → consumers: {consumers or '—'}"
                    ))
        if consumed_evs:
            lines.append("")
            lines.append("**Consumed:**")
            for ev in consumed_evs:
                for con in ev.get("consumed", []):
                    src = con.get("source_service") or con.get("queue") or "?"
                    entity = con.get("entity") or ""
                    action = con.get("action") or ""
                    handler = con.get("handler") or ""
                    lines.append(_bullet(f"from `{src}`: `{entity}` / {action} → handler: {handler}"))
        lines.append("")

    # Config/design document examples — real bundled ones, or structurally
    # valid synthesized ones (never AI-generated; see config_examples.py).
    examples = sr.get("config_examples", [])
    if examples:
        lines += ["### Example Config Documents", ""]
        for ex in examples:
            badge = "real, bundled with the jar" if ex.get("source") == "bundled" else "synthesized — structurally valid, not from a real deployment"
            lines += [
                f"#### `{ex['root_class_name'].rsplit('.', 1)[-1]}` ({badge})",
                "",
                f"```{ex.get('format', 'yaml')}",
                ex.get("content") or "",
                "```",
                "",
            ]

    return lines
