"""Render a completed infrastructure diagnostic run as a Markdown document."""
from __future__ import annotations

from datetime import datetime


_SEVERITY_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}


def render(
    service: str,
    display_name: str,
    label: str | None,
    created_at: str | None,
    summary: dict,
    findings: list[dict],
    cert_results: list[dict],
    port_results: list[dict],
    log_findings: list[dict],
    responses: dict[str, str],
    sections: list[dict],
) -> str:
    lines: list[str] = []

    # Header
    title = f"Infrastructure Diagnostic Run — {display_name}"
    if label:
        title += f": {label}"
    lines += [f"# {title}", ""]
    if created_at:
        lines += [f"**Date:** {created_at}", ""]

    # Summary
    s = summary
    lines += [
        "## Summary",
        "",
        f"| Severity | Count |",
        f"|---|---|",
        f"| 🔴 Critical | {s.get('critical', 0)} |",
        f"| 🟠 High | {s.get('high', 0)} |",
        f"| 🟡 Medium | {s.get('medium', 0)} |",
        f"| 🔵 Low | {s.get('low', 0)} |",
        f"| **Total** | **{s.get('total_findings', 0)}** |",
        "",
    ]
    if s.get("missing_required_count"):
        lines += [f"> ⚠️ {s['missing_required_count']} required item(s) were not submitted.", ""]

    # Findings
    lines += ["## Findings", ""]
    if not findings:
        lines += ["No findings.", ""]
    else:
        for f in findings:
            sev = f.get("severity", "")
            emoji = _SEVERITY_EMOJI.get(sev, "⚪")
            lines += [
                f"### {emoji} [{sev.upper()}] {f.get('category', '')} — {f.get('message', '')}",
                "",
                f"**Item:** `{f.get('item_id', '')}`  ",
                f"**Source:** {f.get('source', '')}",
                "",
            ]
            if f.get("trigger_line"):
                lines += [f"**Trigger line:** `{f['trigger_line']}`", ""]
            if f.get("causes"):
                lines += ["**Causes:**", ""]
                for c in f["causes"]:
                    lines.append(f"- {c}")
                lines.append("")
            if f.get("fix_steps"):
                lines += ["**Fix steps:**", ""]
                for step in f["fix_steps"]:
                    lines.append(f"1. {step}")
                lines.append("")

    # Port results
    if port_results:
        lines += ["## Port Check Results", ""]
        lines += ["| Item | Port | Status |", "|---|---|---|"]
        for p in port_results:
            status = "✅ OPEN" if p.get("open") else "❌ CLOSED"
            lines.append(f"| `{p.get('item_id', '')}` | {p.get('port', '')} | {status} |")
        lines.append("")

    # Cert results
    if cert_results:
        lines += ["## Certificate Analysis", ""]
        for c in cert_results:
            lines += [f"### `{c.get('item_id', '')}`", ""]
            if c.get("subject"):
                lines.append(f"**Subject:** {c['subject']}")
            if c.get("expiry"):
                lines.append(f"**Expiry:** {c['expiry']}")
            days = c.get("days_remaining")
            if days is not None:
                flag = " ⚠️ EXPIRED" if days < 0 else (" ⚠️ EXPIRING SOON" if days < 30 else "")
                lines.append(f"**Days remaining:** {days}{flag}")
            lines.append("")

    # Submitted responses
    lines += ["## Submitted Responses", ""]
    # Build item label lookup from sections
    label_map: dict[str, str] = {}
    for sec in sections:
        for item in sec.get("items", []):
            label_map[item["id"]] = item["label"]

    for item_id, output in responses.items():
        item_label = label_map.get(item_id, item_id)
        lines += [f"### {item_label}", f"`{item_id}`", ""]
        if output and output.strip():
            lines += ["```", output.strip(), "```"]
        else:
            lines += ["_(no output submitted)_"]
        lines.append("")

    return "\n".join(lines)
