"""Enhancement Plan Stage 2 — job-failure / environment-drift notifications.

Reuses the app's existing notification_service.py/email_service.py rather than
building a new notification subsystem. These tests confirm: the three new
event types (bm_job_failed, bm_environment_degraded, bm_cert_binding_expiring)
render without error and are accepted by the preferences API; an environment
health-check transitioning into "degraded" fires exactly once per transition
(not on every subsequent check while still degraded); and check_and_auto_renew
notifies — but does not renew — bindings that have auto_renew disabled.
"""
import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.notification import NotificationPreference, NotificationQueue
from app.models.user import User
from app.services.email_service import TEMPLATES, _render_template
from app.api.v1.notifications import EVENT_TYPES


NEW_EVENT_TYPES = ["bm_job_failed", "bm_environment_degraded", "bm_cert_binding_expiring"]


@pytest.mark.parametrize("event_type", NEW_EVENT_TYPES)
def test_new_event_types_registered_in_preferences_allowlist(event_type):
    assert event_type in EVENT_TYPES


@pytest.mark.parametrize("event_type,kwargs", [
    ("bm_job_failed", {"job_name": "Build environment: test", "exit_code": 1, "environment_id": "env-123"}),
    ("bm_environment_degraded", {"environment_name": "test-env", "environment_id": "env-123"}),
    ("bm_cert_binding_expiring", {"environment_name": "test-env", "role": "mysql", "expires_at": "2026-01-01T00:00:00", "days_remaining": 5}),
])
def test_new_templates_render_without_error(event_type, kwargs):
    assert event_type in TEMPLATES
    subject, body = _render_template(event_type, **kwargs)
    assert subject
    assert body


async def _create_user_with_digest_preference(db, event_type: str) -> str:
    user = User(
        id=str(uuid.uuid4()), username=f"notify-test-{uuid.uuid4().hex[:8]}",
        email="notify-test@example.com", password_hash="not-a-real-hash", role="admin",
    )
    db.add(user)
    await db.flush()
    db.add(NotificationPreference(
        id=str(uuid.uuid4()), user_id=user.id, event_type=event_type,
        enabled=True, digest_mode=True,
    ))
    await db.commit()
    return user.id


@pytest.mark.usefixtures("setup_db")
async def test_environment_degraded_transition_fires_notification_once(client, monkeypatch):
    from app.core.database import async_session
    from app.services.build_manager.health_service import run_health_checks
    from app.models.build_manager import BMEnvironment

    monkeypatch.setattr(settings, "SMTP_ENABLED", True)

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"notify-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1"}]},
    })
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"notify-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "ip_overrides": {"generic1": "10.99.1.1"},
    })
    env_id = resp.json()["id"]

    async with async_session() as db:
        await _create_user_with_digest_preference(db, "bm_environment_degraded")
        # run_health_checks only proceeds on active/degraded/provisioning
        env = (await db.execute(select(BMEnvironment).where(BMEnvironment.id == env_id))).scalar_one()
        env.status = "active"
        await db.commit()

    async with async_session() as db:
        results = await run_health_checks(db, env_id)
        assert any(r["status"] != "healthy" for r in results)  # no real target reachable

        queued = (await db.execute(
            select(NotificationQueue).where(NotificationQueue.event_type == "bm_environment_degraded")
        )).scalars().all()
        assert len(queued) == 1

    # Second run while still degraded: must not fire again.
    async with async_session() as db:
        await run_health_checks(db, env_id)
        queued = (await db.execute(
            select(NotificationQueue).where(NotificationQueue.event_type == "bm_environment_degraded")
        )).scalars().all()
        assert len(queued) == 1


@pytest.mark.usefixtures("setup_db")
async def test_check_and_auto_renew_notifies_without_renewing_manual_bindings(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.core.database import async_session
    from app.models.build_manager import BMEnvironment, BMCertBinding
    from app.services.build_manager.cert_lifecycle import check_and_auto_renew

    monkeypatch.setattr(settings, "SMTP_ENABLED", True)

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"notify-cert-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "mysql1"}]},
    })
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"notify-cert-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
    })
    env_id = resp.json()["id"]

    async with async_session() as db:
        await _create_user_with_digest_preference(db, "bm_cert_binding_expiring")

        env = (await db.execute(select(BMEnvironment).where(BMEnvironment.id == env_id))).scalar_one()
        env.status = "active"

        binding = BMCertBinding(
            id=str(uuid.uuid4()), environment_id=env_id, cert_serial="deadbeef",
            role="mysql", cert_type="server", auto_renew=False,
            expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        )
        db.add(binding)
        await db.commit()
        binding_id = binding.id

    async with async_session() as db:
        renewed = await check_and_auto_renew(db, threshold_days=30)
        assert renewed == []  # the manual binding must not be auto-renewed

        binding = (await db.execute(select(BMCertBinding).where(BMCertBinding.id == binding_id))).scalar_one()
        assert binding.cert_serial == "deadbeef"  # untouched
        assert binding.renewal_count == 0

        queued = (await db.execute(
            select(NotificationQueue).where(NotificationQueue.event_type == "bm_cert_binding_expiring")
        )).scalars().all()
        assert len(queued) == 1
        assert "mysql" in queued[0].subject


@pytest.mark.usefixtures("setup_db")
async def test_job_failure_fires_notification(monkeypatch):
    import asyncio
    from app.core.database import async_session
    from app.services.build_manager.ansible_runner import submit_job
    from app.models.build_manager import BMJob

    monkeypatch.setattr(settings, "SMTP_ENABLED", True)

    async with async_session() as db:
        await _create_user_with_digest_preference(db, "bm_job_failed")
        # A playbook path that can't possibly exist — ansible-playbook fails
        # fast (parse-time error) without ever attempting a real connection.
        job = await submit_job(
            db, name="notify-test-job", playbook="does-not-exist-notify-test.yml",
        )
        job_id = job.id

    # _execute_job runs as a detached background task; poll for completion
    # rather than assuming a fixed sleep is long enough.
    for _ in range(50):
        async with async_session() as db:
            current = (await db.execute(select(BMJob).where(BMJob.id == job_id))).scalar_one()
            if current.status in ("success", "failed"):
                break
        await asyncio.sleep(0.2)

    assert current.status == "failed"

    async with async_session() as db:
        queued = (await db.execute(
            select(NotificationQueue).where(NotificationQueue.event_type == "bm_job_failed")
        )).scalars().all()
        assert len(queued) == 1
        assert "notify-test-job" in queued[0].subject
