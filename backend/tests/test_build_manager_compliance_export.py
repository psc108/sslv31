"""Enhancement Plan Stage 12 — one-click compliance export.

Mostly a formatting exercise over Stage 11's PKI posture aggregation, per
the plan's own framing — these tests confirm each export format (JSON,
CSV, Markdown, PDF) renders the same underlying data correctly and that
each endpoint returns a downloadable attachment, not an inline response.
"""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.build_manager.compliance_export import posture_to_csv, posture_to_markdown, posture_to_pdf


_SAMPLE_POSTURE = {
    "environments": [
        {
            "environment_id": "env-1", "environment_name": "prod-01", "environment_status": "active",
            "certs": [
                {
                    "binding_id": "b-1", "role": "mysql", "cert_type": "server",
                    "cert_serial": "abc123", "cert_status": "valid",
                    "key_algo": "RSA", "key_size": 2048, "weak_key": False,
                    "signing_ca_chain": ["Intermediate CA", "Root CA"],
                    "expires_at": "2026-08-15T00:00:00", "risk": "warning",
                    "auto_renew": True, "renewal_count": 2,
                },
            ],
        },
    ],
    "secrets": [
        {"id": "s-1", "name": "mysql_root_password", "category": "database", "linked_service": "mysql",
         "rotate_every_days": 90, "rotation_due_at": "2026-09-01T00:00:00", "rotation_overdue": False},
    ],
    "summary": {
        "total_certs": 1, "expired_count": 0, "critical_count": 0, "warning_count": 1,
        "weak_key_count": 0, "secrets_overdue_count": 0,
    },
}


def test_posture_to_csv_includes_cert_and_secret_rows():
    csv_text = posture_to_csv(_SAMPLE_POSTURE)
    rows = list(csv.reader(io.StringIO(csv_text)))
    header, cert_row, secret_row = rows[0], rows[1], rows[2]

    assert cert_row[0] == "cert"
    assert cert_row[header.index("role_or_secret_name")] == "mysql"
    assert cert_row[header.index("key_algo")] == "RSA"
    assert "Intermediate CA -> Root CA" in cert_row[header.index("signing_ca_chain")]

    assert secret_row[0] == "secret"
    assert secret_row[header.index("role_or_secret_name")] == "mysql_root_password"
    assert secret_row[header.index("auto_renew_or_rotate_every_days")] == "90"


def test_posture_to_markdown_includes_summary_and_environment_sections():
    md = posture_to_markdown(_SAMPLE_POSTURE)
    assert "# PKI Compliance Report" in md
    assert "prod-01" in md
    assert "mysql" in md
    assert "Intermediate CA → Root CA" in md
    assert "mysql_root_password" in md
    assert "90" in md


def test_posture_to_markdown_handles_empty_state():
    empty = {"environments": [], "secrets": [], "summary": {
        "total_certs": 0, "expired_count": 0, "critical_count": 0, "warning_count": 0,
        "weak_key_count": 0, "secrets_overdue_count": 0,
    }}
    md = posture_to_markdown(empty)
    assert "# PKI Compliance Report" in md
    assert "No secrets have a rotation policy configured" in md


def test_posture_to_pdf_produces_valid_pdf_bytes():
    pdf_bytes = posture_to_pdf(_SAMPLE_POSTURE)
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.usefixtures("setup_db")
async def test_export_json_endpoint_returns_attachment(client):
    resp = await client.get("/api/v1/build/pki-posture/export/json")
    assert resp.status_code == 200, resp.text
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["content-disposition"].endswith('.json"')
    body = resp.json()
    assert "environments" in body and "secrets" in body and "summary" in body


@pytest.mark.usefixtures("setup_db")
async def test_export_csv_endpoint_returns_attachment_with_real_secret(client):
    resp = await client.post("/api/v1/build/secrets", json={
        "name": f"export-test-{uuid.uuid4().hex[:8]}", "value": "s3cret", "rotate_every_days": 30,
    })
    secret_id = resp.json()["id"]
    secret_name = resp.json()["name"]

    resp = await client.get("/api/v1/build/pki-posture/export/csv")
    assert resp.status_code == 200, resp.text
    assert "attachment" in resp.headers["content-disposition"]
    assert secret_name in resp.text

    await client.delete(f"/api/v1/build/secrets/{secret_id}")


@pytest.mark.usefixtures("setup_db")
async def test_export_markdown_endpoint_returns_attachment(client):
    resp = await client.get("/api/v1/build/pki-posture/export/markdown")
    assert resp.status_code == 200, resp.text
    assert "attachment" in resp.headers["content-disposition"]
    assert "# PKI Compliance Report" in resp.text


@pytest.mark.usefixtures("setup_db")
async def test_export_pdf_endpoint_returns_attachment_pdf_bytes(client):
    resp = await client.get("/api/v1/build/pki-posture/export/pdf")
    assert resp.status_code == 200, resp.text
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")
