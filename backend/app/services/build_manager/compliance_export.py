"""Compliance export — Enhancement Plan Stage 12, one-click compliance export.

Formats Stage 11's PKI posture aggregation (cert inventory, key strength,
signing-chain topology, secret rotation staleness) as a downloadable report
for security/compliance reviewers. Mostly a formatting exercise once Stage
11's aggregation exists, per the plan's own framing — no new data
collection here, only rendering what get_pki_posture() already returns.
"""
import csv
import io
from datetime import datetime, timezone

# Reused rather than duplicated — same PDF design language as the JAR
# Analyser's change-report export.
from app.services.jar_analyser.change_report import _CSS as REPORT_CSS


def posture_to_csv(posture: dict) -> str:
    """One flat, single-sheet CSV — a compliance reviewer importing this
    into a spreadsheet expects one file, not a multi-table export, so a
    'record_type' column distinguishes cert rows from secret rows sharing
    the same column layout."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "record_type", "environment_name", "role_or_secret_name", "cert_type_or_category",
        "cert_serial", "key_algo", "key_size", "weak_key", "signing_ca_chain",
        "expires_at_or_rotation_due", "risk_or_overdue", "auto_renew_or_rotate_every_days",
    ])
    for env in posture["environments"]:
        for c in env["certs"]:
            writer.writerow([
                "cert", env["environment_name"], c["role"], c["cert_type"],
                c["cert_serial"], c["key_algo"], c["key_size"], c["weak_key"],
                " -> ".join(c["signing_ca_chain"]),
                c["expires_at"], c["risk"], c["auto_renew"],
            ])
    for s in posture["secrets"]:
        writer.writerow([
            "secret", "", s["name"], s["category"],
            "", "", "", "", "",
            s["rotation_due_at"], s["rotation_overdue"], s["rotate_every_days"],
        ])
    return output.getvalue()


def posture_to_markdown(posture: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary = posture["summary"]
    lines = [
        "# PKI Compliance Report",
        "",
        f"Generated: {now}",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---|",
        f"| Total Certificates | {summary['total_certs']} |",
        f"| Expired | {summary['expired_count']} |",
        f"| Critical (≤7 days) | {summary['critical_count']} |",
        f"| Warning (≤30 days) | {summary['warning_count']} |",
        f"| Weak Keys | {summary['weak_key_count']} |",
        f"| Secrets Overdue for Rotation | {summary['secrets_overdue_count']} |",
        "",
    ]

    for env in posture["environments"]:
        lines.append(f"## Environment: {env['environment_name']} ({env['environment_status']})")
        lines.append("")
        if not env["certs"]:
            lines.append("_No certificate bindings._")
            lines.append("")
            continue
        lines.append("| Role | Type | Key | Weak? | Signing Chain | Expires | Risk | Auto-Renew |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for c in env["certs"]:
            key = f"{c['key_algo'] or '?'} {c['key_size'] or '?'}"
            chain = " → ".join(c["signing_ca_chain"]) or "—"
            lines.append(
                f"| {c['role']} | {c['cert_type']} | {key} | {'⚠ yes' if c['weak_key'] else 'no'} | "
                f"{chain} | {c['expires_at'] or '—'} | {c['risk']} | {'yes' if c['auto_renew'] else 'no'} |"
            )
        lines.append("")

    lines.append("## Secret Rotation Status")
    lines.append("")
    policy_secrets = [s for s in posture["secrets"] if s["rotate_every_days"]]
    if not policy_secrets:
        lines.append("_No secrets have a rotation policy configured._")
    else:
        lines.append("| Secret | Category | Rotate Every (days) | Due | Overdue? |")
        lines.append("|---|---|---|---|---|")
        for s in policy_secrets:
            overdue = "⚠ yes" if s["rotation_overdue"] else "no"
            lines.append(f"| {s['name']} | {s['category']} | {s['rotate_every_days']} | {s['rotation_due_at'] or '—'} | {overdue} |")
    lines.append("")

    return "\n".join(lines)


def posture_to_pdf(posture: dict) -> bytes:
    """Render the compliance report as a PDF byte string, reusing the same
    Markdown-through-weasyprint pipeline the JAR Analyser's change-report
    export already established."""
    import markdown as md_lib
    import weasyprint

    md_text = posture_to_markdown(posture)
    html_body = md_lib.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>{REPORT_CSS}</style>
</head>
<body>
{html_body}
</body>
</html>"""

    return weasyprint.HTML(string=html).write_pdf()
