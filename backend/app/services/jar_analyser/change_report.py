"""Change Report renderer — produces a formal structured change report from a diff.

Outputs:
  - Markdown (plain text, suitable for wikis / git)
  - PDF (via weasyprint HTML→PDF pipeline)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Semver helpers
# ---------------------------------------------------------------------------

def _parse_semver(v: str | None) -> tuple[int, int, int] | None:
    if not v:
        return None
    m = re.match(r"(\d+)\.(\d+)\.?(\d*)", v.strip().lstrip("v"))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def _version_bump(from_v: str | None, to_v: str | None) -> str:
    """Return 'major', 'minor', 'patch', or 'unknown'."""
    a = _parse_semver(from_v)
    b = _parse_semver(to_v)
    if not a or not b:
        return "unknown"
    if b[0] != a[0]:
        return "major"
    if b[1] != a[1]:
        return "minor"
    return "patch"


# ---------------------------------------------------------------------------
# Impact helpers
# ---------------------------------------------------------------------------

_IMPACT_LABEL = {
    "breaking": "⛔ BREAKING",
    "potentially_breaking": "⚠ POTENTIALLY BREAKING",
    "none": "✓ Safe",
    "review": "👁 Review",
}


def _impact_label(impact: str) -> str:
    return _IMPACT_LABEL.get(impact, impact)


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def change_report_to_markdown(diff: dict) -> str:
    lines: list[str] = []
    la = diff.get("label_a") or "A"
    lb = diff.get("label_b") or "B"
    s = diff.get("summary", {})
    service_diffs: list[dict] = diff.get("service_diffs", [])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    breaking = s.get("breaking_changes", 0)
    security = s.get("security_changes", 0)

    # ---- Cover / header ----
    lines += [
        f"# Change Report: {la} → {lb}",
        "",
        f"| | |",
        f"|---|---|",
        f"| **Baseline** | {la} (`{diff.get('report_a_id', '')[:8]}`) |",
        f"| **New version** | {lb} (`{diff.get('report_b_id', '')[:8]}`) |",
        f"| **Generated** | {now} |",
        f"| **Diff ID** | `{diff.get('diff_id', '')}` |",
        "",
    ]

    # ---- Risk banner ----
    if breaking or security:
        lines.append("> ### ⚠ Attention Required")
        if breaking:
            lines.append(f">")
            lines.append(f"> **{breaking} breaking change{'s' if breaking != 1 else ''}** detected.")
            lines.append(f"> Plugins or integrations consuming this API may require updates before deploying this version.")
        if security:
            lines.append(f">")
            lines.append(f"> **{security} security expression change{'s' if security != 1 else ''}** detected — review access control carefully.")
        lines.append("")

    # ---- Executive summary ----
    lines += [
        "## Executive Summary",
        "",
        "| Category | Added | Removed | Changed |",
        "|----------|------:|--------:|--------:|",
        f"| Services | {s.get('services_added',0)} | {s.get('services_removed',0)} | {s.get('services_changed',0)} |",
        f"| Endpoints | {s.get('endpoints_added',0)} | {s.get('endpoints_removed',0)} | {s.get('endpoints_changed',0)} |",
        f"| Dependencies | {s.get('dependencies_added',0)} | {s.get('dependencies_removed',0)} | {s.get('dependencies_version_changed',0)} version changes |",
        f"| Config Keys | {s.get('config_keys_added',0)} | {s.get('config_keys_removed',0)} | {s.get('config_keys_changed',0)} |",
        f"| DB Migrations | {s.get('migration_scripts_added',0)} | {s.get('migration_scripts_removed',0)} | — |",
        f"| DB Tables | {s.get('db_tables_added',0)} | {s.get('db_tables_dropped',0)} | — |",
        f"| DB Columns | {s.get('db_columns_added',0)} | {s.get('db_columns_dropped',0)} | — |",
        f"| Schema Fields | {s.get('schema_fields_added',0)} | {s.get('schema_fields_removed',0)} | {s.get('schema_fields_type_changed',0)} type changes |",
        f"| Security Changes | — | — | {security} |",
        f"| Breaking Changes | — | — | **{breaking}** |",
        "",
    ]

    # ---- Breaking changes index ----
    details: list[str] = s.get("breaking_change_details", [])
    if details:
        lines += ["## Breaking Changes", ""]
        for d in details:
            lines.append(f"- `{d}`")
        lines.append("")

    # ---- Per-service sections ----
    lines += ["## Service Changes", ""]

    changed = [sd for sd in service_diffs if sd["change"] == "CHANGED"]
    added   = [sd for sd in service_diffs if sd["change"] == "ADDED"]
    removed = [sd for sd in service_diffs if sd["change"] == "REMOVED"]

    if added:
        lines += ["### New Services", ""]
        for sd in added:
            lines.append(f"- **{sd['service_name']}** — added in {lb}")
        lines.append("")

    if removed:
        lines += ["### Removed Services", ""]
        for sd in removed:
            lines.append(f"- **{sd['service_name']}** — removed from {lb}")
        lines.append("")

    for sd in changed:
        lines += _service_section(sd, la, lb)

    # ---- Dependency version changes (consolidated) ----
    all_dep_changes: list[dict] = []
    for sd in changed:
        for dep in sd.get("dependency_diffs", []):
            if dep["change"] == "CHANGED":
                all_dep_changes.append({**dep, "_service": sd["service_name"]})

    if all_dep_changes:
        lines += ["## Dependency Version Changes", ""]
        lines += [
            "| Service | Dependency | From | To | Bump |",
            "|---------|-----------|------|----|------|",
        ]
        for dep in sorted(all_dep_changes, key=lambda d: (_version_bump(d.get("version_from"), d.get("version_to")) == "major", d["_service"])):
            bump = _version_bump(dep.get("version_from"), dep.get("version_to"))
            bump_label = f"**{bump.upper()}**" if bump in ("major", "minor") else bump
            lines.append(
                f"| {dep['_service']} | `{dep.get('maven_coordinates','')}` "
                f"| `{dep.get('version_from','')}` | `{dep.get('version_to','')}` | {bump_label} |"
            )
        lines.append("")

    # ---- Warnings ----
    warnings = diff.get("warnings", [])
    if warnings:
        lines += ["## Warnings", ""]
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines += [
        "---",
        f"*Report generated by JAR Analyser — {now}*",
        "",
    ]

    return "\n".join(lines)


def _service_section(sd: dict, la: str, lb: str) -> list[str]:
    lines: list[str] = []
    svc = sd["service_name"]
    lines += [f"### {svc}", ""]

    vc = sd.get("version_change")
    pc = sd.get("port_change")
    sbc = sd.get("spring_boot_version_change")
    if vc:
        lines.append(f"- **Version:** `{vc['from']}` → `{vc['to']}`")
    if pc:
        lines.append(f"- **Port:** `{pc['from']}` → `{pc['to']}`")
    if sbc:
        lines.append(f"- **Spring Boot:** `{sbc['from']}` → `{sbc['to']}`")
    if vc or pc or sbc:
        lines.append("")

    # Endpoints
    ep_diffs: list[dict] = sd.get("endpoint_diffs", [])
    if ep_diffs:
        lines += ["#### API Endpoints", ""]
        added   = [e for e in ep_diffs if e["change"] == "ADDED"]
        removed = [e for e in ep_diffs if e["change"] == "REMOVED"]
        changed = [e for e in ep_diffs if e["change"] == "CHANGED"]

        if added:
            lines.append("**Added:**")
            for e in added:
                lines.append(f"- `{e['http_method']} {e['path']}`")
            lines.append("")
        if removed:
            lines.append("**Removed:**")
            for e in removed:
                lines.append(f"- `{e['http_method']} {e['path']}`")
            lines.append("")
        if changed:
            lines.append("**Modified:**")
            for e in changed:
                detail = e.get("detail") or {}
                flags: list[str] = []
                if detail.get("security_changed"):
                    flags.append("⚠ security")
                if detail.get("parameters_added"):
                    flags.append(f"+{len(detail['parameters_added'])} param(s)")
                if detail.get("parameters_removed"):
                    flags.append(f"-{len(detail['parameters_removed'])} param(s)")
                if detail.get("return_type_changed"):
                    rt = detail["return_type_changed"]
                    flags.append(f"return type: `{rt.get('from',{}).get('simple_type','?')}` → `{rt.get('to',{}).get('simple_type','?')}`")
                flag_str = " · ".join(flags)
                lines.append(f"- `{e['http_method']} {e['path']}`{' — ' + flag_str if flag_str else ''}")
                # Security detail
                if detail.get("security_changed"):
                    sc = detail["security_changed"]
                    lines.append(f"  - Security: `{sc.get('from') or 'none'}` → `{sc.get('to') or 'none'}`")
                # Param detail
                for p in detail.get("parameters_added", []):
                    lines.append(f"  - + param `{p.get('name')}` ({p.get('location','')}) added")
                for p in detail.get("parameters_removed", []):
                    lines.append(f"  - - param `{p.get('name')}` removed")
            lines.append("")

    # Schema field diffs
    schema_diffs: list[dict] = sd.get("schema_diffs", [])
    if schema_diffs:
        lines += ["#### Schema / DTO Changes", ""]
        for sc in schema_diffs:
            simple = sc["simple_name"]
            is_enum = sc.get("is_enum", False)
            field_diffs: list[dict] = sc.get("field_diffs", [])
            breaking_fields = [f for f in field_diffs if f["impact"] == "breaking"]
            lines.append(f"**`{simple}`**{'  *(enum)*' if is_enum else ''}:")
            lines.append("")
            lines += [
                "| Field | Change | Type | Impact |",
                "|-------|--------|------|--------|",
            ]
            for f in field_diffs:
                change = f["change"].replace("_", " ").title()
                if f["change"] == "TYPE_CHANGED":
                    type_str = f"`{f.get('type_from','?')}` → `{f.get('type_to','?')}`"
                else:
                    type_str = f"`{f.get('type','')}`" if f.get("type") else "—"
                req = " *(required)*" if f.get("required") and f["change"] == "ADDED" else ""
                lines.append(
                    f"| `{f['field']}`{req} | {change} | {type_str} | {_impact_label(f['impact'])} |"
                )
            lines.append("")

    # Dependencies (added/removed only — version changes go in consolidated table)
    dep_diffs: list[dict] = sd.get("dependency_diffs", [])
    dep_added   = [d for d in dep_diffs if d["change"] == "ADDED"]
    dep_removed = [d for d in dep_diffs if d["change"] == "REMOVED"]
    dep_changed = [d for d in dep_diffs if d["change"] == "CHANGED"]

    if dep_added or dep_removed or dep_changed:
        lines += ["#### Dependencies", ""]
        if dep_added:
            lines.append("**Added:**")
            for d in dep_added:
                lines.append(f"- `{d.get('maven_coordinates','')}` `{d.get('version','')}`")
            lines.append("")
        if dep_removed:
            lines.append("**Removed:**")
            for d in dep_removed:
                lines.append(f"- `{d.get('maven_coordinates','')}` `{d.get('version','')}`")
            lines.append("")
        if dep_changed:
            lines.append("**Version changes:**")
            lines += [
                "| Dependency | From | To | Bump |",
                "|-----------|------|----|------|",
            ]
            for d in dep_changed:
                bump = _version_bump(d.get("version_from"), d.get("version_to"))
                bump_label = f"**{bump.upper()}**" if bump in ("major", "minor") else bump
                lines.append(
                    f"| `{d.get('maven_coordinates','')}` | `{d.get('version_from','')}` | `{d.get('version_to','')}` | {bump_label} |"
                )
            lines.append("")

    # Config changes
    cfg_diffs: list[dict] = sd.get("config_diffs", [])
    if cfg_diffs:
        lines += ["#### Configuration Changes", ""]
        lines += [
            "| File | Key | Change | Value |",
            "|------|-----|--------|-------|",
        ]
        for c in cfg_diffs:
            if c["change"] == "CHANGED":
                val = f"`{c.get('value_from','')}` → `{c.get('value_to','')}`"
            elif c["change"] == "ADDED":
                val = f"`{c.get('value','')}`"
            else:
                val = "—"
            lines.append(f"| `{c.get('file','')}` | `{c.get('key','')}` | {c['change']} | {val} |")
        lines.append("")

    # Migrations
    mig_diffs: list[dict] = sd.get("migration_diffs", [])
    if mig_diffs:
        lines += ["#### Database Migrations", ""]
        for m in mig_diffs:
            prefix = "+" if m["change"] == "ADDED" else "-"
            warn = " ⚠ removed — verify migration order" if m.get("warning") else ""
            lines.append(f"- {prefix} `{m.get('filename','')}` — {m.get('description','')}{warn}")
        lines.append("")

    # DB Schema diffs
    db_schema_diffs: list[dict] = sd.get("db_schema_diffs", [])
    if db_schema_diffs:
        lines += ["#### Database Schema Changes", ""]
        _RISK_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        _CHANGE_LABEL = {
            "TABLE_ADDED": "Table added",
            "TABLE_DROPPED": "Table dropped",
            "COLUMN_ADDED": "Column added",
            "COLUMN_DROPPED": "Column dropped",
            "TYPE_CHANGED": "Type changed",
            "CONSTRAINT_CHANGED": "Constraint changed",
            "INDEX_CHANGED": "Index changed",
            "FK_CHANGED": "FK changed",
        }
        lines += [
            "| Risk | Change | Table | Column | Detail |",
            "|------|--------|-------|--------|--------|",
        ]
        for c in db_schema_diffs:
            risk_icon = _RISK_ICON.get(c.get("risk", "low"), "🟢")
            label = _CHANGE_LABEL.get(c["change"], c["change"])
            col = f"`{c['column']}`" if c.get("column") else "—"
            d = c.get("detail", {})
            if c["change"] == "TYPE_CHANGED":
                detail = f"`{d.get('from')}` → `{d.get('to')}`"
            elif c["change"] == "COLUMN_ADDED":
                null_note = "NOT NULL, no default ⚠" if not d.get("nullable") and d.get("default") is None else ""
                detail = f"`{d.get('type')}` {null_note}".strip()
            elif c["change"] == "CONSTRAINT_CHANGED":
                detail = f"nullable: `{d.get('nullable_from')}` → `{d.get('nullable_to')}`"
            elif c["change"] in ("INDEX_CHANGED", "FK_CHANGED"):
                kind = d.get("kind", "")
                name = d.get("name") or ""
                cols = ", ".join(d.get("columns") or [])
                detail = f"{kind} `{name}` ({cols})".strip()
            else:
                detail = ""
            lines.append(f"| {risk_icon} | {label} | `{c['table']}` | {col} | {detail} |")
        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# PDF renderer
# ---------------------------------------------------------------------------

_CSS = """
@page {
    size: A4;
    margin: 20mm 18mm 20mm 18mm;
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-size: 9pt;
        color: #888;
    }
}
body {
    font-family: "DejaVu Sans", Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.5;
    color: #1a1a1a;
}
h1 { font-size: 20pt; color: #1e3a5f; border-bottom: 2px solid #1e3a5f; padding-bottom: 4pt; margin-top: 0; }
h2 { font-size: 14pt; color: #1e3a5f; border-bottom: 1px solid #c0cfe0; padding-bottom: 2pt; margin-top: 18pt; }
h3 { font-size: 12pt; color: #2c5282; margin-top: 14pt; }
h4 { font-size: 10pt; color: #2d3748; margin-top: 10pt; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9pt; }
th { background: #1e3a5f; color: white; padding: 5pt 8pt; text-align: left; }
td { padding: 4pt 8pt; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
tr:nth-child(even) td { background: #f7fafc; }
code, pre { font-family: "DejaVu Sans Mono", monospace; font-size: 8.5pt; background: #f0f4f8; padding: 1pt 3pt; border-radius: 2pt; }
pre { padding: 6pt; display: block; white-space: pre-wrap; }
blockquote {
    border-left: 4px solid #e53e3e;
    background: #fff5f5;
    margin: 10pt 0;
    padding: 8pt 12pt;
    color: #742a2a;
}
blockquote h3 { color: #742a2a; margin-top: 0; }
ul { margin: 4pt 0; padding-left: 16pt; }
li { margin: 2pt 0; }
strong { color: #1a1a1a; }
.cover-meta td { border: none; background: none; padding: 3pt 8pt; }
hr { border: none; border-top: 1px solid #e2e8f0; margin: 12pt 0; }
"""


def change_report_to_pdf(diff: dict) -> bytes:
    """Render the change report as a PDF byte string."""
    import markdown as md_lib
    import weasyprint

    md_text = change_report_to_markdown(diff)
    html_body = md_lib.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>{_CSS}</style>
</head>
<body>
{html_body}
</body>
</html>"""

    return weasyprint.HTML(string=html).write_pdf()
