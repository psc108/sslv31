"""Email service — SMTP dispatch with Jinja2 HTML templates."""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# HTML email templates (inline for simplicity)
TEMPLATES: dict[str, dict[str, str]] = {
    "expiry_warning": {
        "subject": "⚠️ Certificate Expiring: {cn} ({days_remaining} days)",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#d97706">Certificate Expiry Warning</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Common Name</td><td style="padding:8px">{cn}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Serial</td><td style="padding:8px"><code>{serial}</code></td></tr>
<tr><td style="padding:8px;font-weight:bold">Expires</td><td style="padding:8px">{expires_at}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Days Remaining</td><td style="padding:8px;color:#dc2626;font-weight:bold">{days_remaining}</td></tr>
</table>
<p style="margin-top:16px">Renew this certificate before it expires to avoid service disruption.</p>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "cert_issued": {
        "subject": "✅ Certificate Issued: {cn}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#059669">Certificate Issued</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Common Name</td><td style="padding:8px">{cn}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Serial</td><td style="padding:8px"><code>{serial}</code></td></tr>
<tr><td style="padding:8px;font-weight:bold">Profile</td><td style="padding:8px">{profile}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Expires</td><td style="padding:8px">{expires_at}</td></tr>
</table>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "approval_required": {
        "subject": "🔔 Approval Required: {cn}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#2563eb">Approval Required</h2>
<p>A certificate request requires your approval:</p>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Common Name</td><td style="padding:8px">{cn}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Requester</td><td style="padding:8px">{requester}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Profile</td><td style="padding:8px">{profile}</td></tr>
</table>
<p style="margin-top:16px">Log in to the PKI portal to approve or deny this request.</p>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "approval_decision": {
        "subject": "📋 Request {decision}: {cn}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:{color}">Request {decision}</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Common Name</td><td style="padding:8px">{cn}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Decision</td><td style="padding:8px">{decision}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Decided By</td><td style="padding:8px">{decided_by}</td></tr>
</table>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "security_event": {
        "subject": "🚨 Security Alert: {event}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#dc2626">Security Alert</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Event</td><td style="padding:8px">{event}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Details</td><td style="padding:8px">{details}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Source IP</td><td style="padding:8px">{source_ip}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Time</td><td style="padding:8px">{timestamp}</td></tr>
</table>
<p style="margin-top:16px">Investigate immediately if this was unexpected.</p>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "auto_renewal": {
        "subject": "🔄 Certificate Auto-Renewed: {cn}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#059669">Certificate Auto-Renewed</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Common Name</td><td style="padding:8px">{cn}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Old Serial</td><td style="padding:8px"><code>{old_serial}</code></td></tr>
<tr><td style="padding:8px;font-weight:bold">New Serial</td><td style="padding:8px"><code>{new_serial}</code></td></tr>
<tr><td style="padding:8px;font-weight:bold">New Expiry</td><td style="padding:8px">{expires_at}</td></tr>
</table>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "digest": {
        "subject": "📬 Daily PKI Digest — {count} notifications",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#4b5563">Daily PKI Digest</h2>
<p>You have {count} notification(s) from the past 24 hours:</p>
{items}
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "bm_job_failed": {
        "subject": "❌ Build Manager Job Failed: {job_name}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#dc2626">Build Manager Job Failed</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Job</td><td style="padding:8px">{job_name}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Exit Code</td><td style="padding:8px"><code>{exit_code}</code></td></tr>
<tr><td style="padding:8px;font-weight:bold">Environment</td><td style="padding:8px">{environment_id}</td></tr>
</table>
<p style="margin-top:16px">Check the job output in Build Manager for details.</p>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "bm_environment_degraded": {
        "subject": "⚠️ Build Manager Environment Degraded: {environment_name}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#d97706">Build Manager Environment Degraded</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Environment</td><td style="padding:8px">{environment_name}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Environment ID</td><td style="padding:8px"><code>{environment_id}</code></td></tr>
</table>
<p style="margin-top:16px">One or more services in this environment failed their health check.</p>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "bm_cert_binding_expiring": {
        "subject": "⚠️ Build Manager Cert Expiring: {role} in {environment_name} ({days_remaining} days)",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#d97706">Build Manager Certificate Binding Expiring</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Environment</td><td style="padding:8px">{environment_name}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Role</td><td style="padding:8px">{role}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Expires</td><td style="padding:8px">{expires_at}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Days Remaining</td><td style="padding:8px;color:#dc2626;font-weight:bold">{days_remaining}</td></tr>
</table>
<p style="margin-top:16px">This binding has auto-renew disabled — renew it manually before it expires.</p>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "bm_secret_rotation_overdue": {
        "subject": "⚠️ Build Manager Secret Rotation Overdue: {secret_name}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#d97706">Build Manager Secret Rotation Overdue</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Secret</td><td style="padding:8px">{secret_name}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Rotation Policy</td><td style="padding:8px">every {rotate_every_days} days</td></tr>
<tr><td style="padding:8px;font-weight:bold">Was Due</td><td style="padding:8px;color:#dc2626;font-weight:bold">{due_at}</td></tr>
</table>
<p style="margin-top:16px">This secret is not auto-rotated — review it and rotate manually via the Secrets page.</p>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "bug_assigned": {
        "subject": "🐛 Bug Assigned: {bug_title}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#2563eb">Bug Assigned to You</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Title</td><td style="padding:8px">{bug_title}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Severity</td><td style="padding:8px">{severity}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Assigned By</td><td style="padding:8px">{assigned_by}</td></tr>
</table>
<p style="margin-top:16px">Open the Bug Tracker (Docs → 🐛 Bugs) to view details.</p>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "bug_status_changed": {
        "subject": "🐛 Bug Status Changed: {bug_title} → {to_status}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#2563eb">Bug Status Changed</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Title</td><td style="padding:8px">{bug_title}</td></tr>
<tr><td style="padding:8px;font-weight:bold">From</td><td style="padding:8px">{from_status}</td></tr>
<tr><td style="padding:8px;font-weight:bold">To</td><td style="padding:8px;font-weight:bold">{to_status}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Changed By</td><td style="padding:8px">{changed_by}</td></tr>
</table>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
    "bug_occurrence_linked": {
        "subject": "🐛 Bug Also Seen Elsewhere: {bug_title}",
        "body": """
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#d97706">Bug Linked to Another Report</h2>
<table style="border-collapse:collapse;width:100%">
<tr><td style="padding:8px;font-weight:bold">Title</td><td style="padding:8px">{bug_title}</td></tr>
<tr><td style="padding:8px;font-weight:bold">Report</td><td style="padding:8px"><code>{report_id}</code></td></tr>
<tr><td style="padding:8px;font-weight:bold">Linked By</td><td style="padding:8px">{linked_by}</td></tr>
</table>
<p style="margin-top:16px">This bug is now known to affect more than one report — a pattern worth investigating.</p>
<p style="color:#6b7280;font-size:12px;margin-top:24px">— SSL Certificate Manager</p>
</div>""",
    },
}


def _render_template(template_name: str, **kwargs: Any) -> tuple[str, str]:
    """Render an email template, returning (subject, body_html)."""
    tmpl = TEMPLATES[template_name]
    subject = tmpl["subject"].format(**kwargs)
    body = tmpl["body"].format(**kwargs)
    return subject, body


def _send_smtp(to_email: str, subject: str, body_html: str) -> None:
    """Send email via SMTP (blocking — run in executor)."""
    msg = MIMEMultipart("alternative")
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))

    try:
        if settings.SMTP_TLS == "ssl":
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
            if settings.SMTP_TLS == "starttls":
                server.starttls()

        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

        server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
        server.quit()
        logger.debug(f"Email sent to {to_email}: {subject}")
    except Exception as e:
        logger.error(f"SMTP send failed to {to_email}: {e}")
        raise


async def send_email(to_email: str, subject: str, body_html: str) -> bool:
    """Send email asynchronously (runs SMTP in thread pool)."""
    if not settings.SMTP_ENABLED or not settings.SMTP_HOST:
        logger.debug("SMTP not configured, skipping email")
        return False
    if not to_email:
        return False

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _send_smtp, to_email, subject, body_html)
        return True
    except Exception:
        return False


async def send_templated_email(to_email: str, template_name: str, **kwargs: Any) -> bool:
    """Render template and send."""
    subject, body = _render_template(template_name, **kwargs)
    return await send_email(to_email, subject, body)


async def test_smtp_connection() -> dict:
    """Test SMTP connectivity."""
    if not settings.SMTP_HOST:
        return {"status": "error", "message": "SMTP_HOST not configured"}

    loop = asyncio.get_event_loop()
    try:
        def _test():
            if settings.SMTP_TLS == "ssl":
                server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
            else:
                server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
                if settings.SMTP_TLS == "starttls":
                    server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.quit()

        await loop.run_in_executor(None, _test)
        return {"status": "ok", "message": f"Connected to {settings.SMTP_HOST}:{settings.SMTP_PORT}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
