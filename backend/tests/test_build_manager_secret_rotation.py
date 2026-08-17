"""Enhancement Plan Stage 10 — policy-driven secret rotation.

Deliberately flag-only, not auto-rotate: a wrong automatic rotation could
break a live service still using the old credential, so BMSecret.rotate_every_days
only drives a computed "overdue" flag (surfaced in the API/UI) and a one-shot
notification via the existing notification_service.py/email_service.py
infrastructure (Stage 2) — the periodic scanner never touches the secret's
value itself.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.email_service import TEMPLATES, _render_template
from app.api.v1.notifications import EVENT_TYPES


def test_bm_secret_rotation_overdue_registered_in_preferences_allowlist():
    assert "bm_secret_rotation_overdue" in EVENT_TYPES


def test_bm_secret_rotation_overdue_template_renders_without_error():
    assert "bm_secret_rotation_overdue" in TEMPLATES
    subject, body = _render_template(
        "bm_secret_rotation_overdue", secret_name="mysql_root_password",
        rotate_every_days=90, due_at="2026-01-01T00:00:00",
    )
    assert subject
    assert body


@pytest.mark.usefixtures("setup_db")
async def test_create_secret_with_rotation_policy_exposes_due_date(client):
    name = f"rotation-test-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/secrets", json={
        "name": name, "value": "s3cret", "rotate_every_days": 30,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rotate_every_days"] == 30
    assert body["rotation_due_at"] is not None
    assert body["rotation_overdue"] is False  # just created, nowhere near due

    await client.delete(f"/api/v1/build/secrets/{body['id']}")


@pytest.mark.usefixtures("setup_db")
async def test_secret_without_policy_is_never_overdue(client):
    resp = await client.post("/api/v1/build/secrets", json={
        "name": f"rotation-nopolicy-{uuid.uuid4().hex[:8]}", "value": "s3cret",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rotate_every_days"] is None
    assert body["rotation_due_at"] is None
    assert body["rotation_overdue"] is False

    await client.delete(f"/api/v1/build/secrets/{body['id']}")


async def _make_overdue_secret(client, days_overdue: int = 5, rotate_every_days: int = 30) -> str:
    """Create a secret with a rotation policy, then backdate created_at via
    the ORM (not raw SQL — this app's DateTime columns are stored/compared
    as SQLite strings in a specific format the ORM writes consistently but
    a hand-written SQL UPDATE could easily mismatch) so it's already overdue."""
    from app.core.database import async_session
    from app.models.build_manager import BMSecret
    from sqlalchemy import select

    resp = await client.post("/api/v1/build/secrets", json={
        "name": f"rotation-overdue-{uuid.uuid4().hex[:8]}", "value": "s3cret",
        "rotate_every_days": rotate_every_days,
    })
    assert resp.status_code == 200, resp.text
    secret_id = resp.json()["id"]

    async with async_session() as db:
        secret = (await db.execute(select(BMSecret).where(BMSecret.id == secret_id))).scalar_one()
        secret.created_at = datetime.now(timezone.utc) - timedelta(days=rotate_every_days + days_overdue)
        await db.commit()

    return secret_id


@pytest.mark.usefixtures("setup_db")
async def test_overdue_secret_reports_overdue_true(client):
    secret_id = await _make_overdue_secret(client)
    resp = await client.get("/api/v1/build/secrets")
    matching = [s for s in resp.json() if s["id"] == secret_id]
    assert matching and matching[0]["rotation_overdue"] is True

    await client.delete(f"/api/v1/build/secrets/{secret_id}")


@pytest.mark.usefixtures("setup_db")
async def test_scan_overdue_secrets_notifies_once_then_stays_quiet(client):
    from app.core.database import async_session
    from app.models.build_manager import BMSecret
    from app.services.build_manager.secrets_service import scan_overdue_secrets
    from sqlalchemy import select

    secret_id = await _make_overdue_secret(client)

    async with async_session() as db:
        notified = await scan_overdue_secrets(db)

    async with async_session() as db:
        secret = (await db.execute(select(BMSecret).where(BMSecret.id == secret_id))).scalar_one()
        assert secret.rotation_notified is True
        notified_name = secret.name
    assert notified_name in notified

    # Second scan: already notified, must not fire again.
    async with async_session() as db:
        notified_again = await scan_overdue_secrets(db)
    assert notified_name not in notified_again

    await client.delete(f"/api/v1/build/secrets/{secret_id}")


@pytest.mark.usefixtures("setup_db")
async def test_rotating_overdue_secret_clears_notified_flag_and_resets_due_date(client):
    from app.core.database import async_session
    from app.models.build_manager import BMSecret
    from app.services.build_manager.secrets_service import scan_overdue_secrets
    from sqlalchemy import select

    secret_id = await _make_overdue_secret(client)
    async with async_session() as db:
        await scan_overdue_secrets(db)
        secret = (await db.execute(select(BMSecret).where(BMSecret.id == secret_id))).scalar_one()
        assert secret.rotation_notified is True

    resp = await client.post(f"/api/v1/build/secrets/{secret_id}/rotate", json={"name": "_", "value": "new-value"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rotation_overdue"] is False  # rotated_at just reset the clock

    async with async_session() as db:
        secret = (await db.execute(select(BMSecret).where(BMSecret.id == secret_id))).scalar_one()
        assert secret.rotation_notified is False

    await client.delete(f"/api/v1/build/secrets/{secret_id}")


@pytest.mark.usefixtures("setup_db")
async def test_update_secret_can_clear_rotation_policy(client):
    resp = await client.post("/api/v1/build/secrets", json={
        "name": f"rotation-clear-{uuid.uuid4().hex[:8]}", "value": "s3cret", "rotate_every_days": 30,
    })
    secret_id = resp.json()["id"]

    resp = await client.put(f"/api/v1/build/secrets/{secret_id}", json={"clear_rotation_policy": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["rotate_every_days"] is None
    assert resp.json()["rotation_due_at"] is None

    await client.delete(f"/api/v1/build/secrets/{secret_id}")


@pytest.mark.usefixtures("setup_db")
async def test_update_secret_without_mentioning_policy_leaves_it_untouched(client):
    resp = await client.post("/api/v1/build/secrets", json={
        "name": f"rotation-untouched-{uuid.uuid4().hex[:8]}", "value": "s3cret", "rotate_every_days": 45,
    })
    secret_id = resp.json()["id"]

    resp = await client.put(f"/api/v1/build/secrets/{secret_id}", json={"description": "just a metadata change"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["rotate_every_days"] == 45

    await client.delete(f"/api/v1/build/secrets/{secret_id}")
