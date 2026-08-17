"""Per-template configurable Ansible job timeout.

Live-testing the 8-host Full Stack template (with the frontend-lb/backend-lb
tier added) hit the old single global settings.BM_ANSIBLE_TIMEOUT (1800s)
twice in a row, at almost identical durations — a real capacity issue for
bigger templates, not a bug. This makes the timeout configurable per
template (spec["ansible_timeout_minutes"], one of 30/40/50/60) instead of a
single constant everyone shares, resolved once at submit_job() time and
persisted onto BMJob.timeout_seconds so the running job loop never needs a
second DB round-trip, and an auto-retry's follow-up job carries the same
value forward.
"""
import asyncio
import uuid

import pytest


def test_validate_spec_accepts_allowed_timeout_values():
    from app.services.build_manager.template_service import validate_spec

    for minutes in (30, 40, 50, 60):
        spec = {"hosts": [{"role": "web"}], "ansible_timeout_minutes": minutes}
        assert validate_spec(spec) == []


def test_validate_spec_rejects_disallowed_timeout_values():
    from app.services.build_manager.template_service import validate_spec

    for bad_value in (45, 0, -30, "60", None):
        spec = {"hosts": [{"role": "web"}], "ansible_timeout_minutes": bad_value}
        errors = validate_spec(spec)
        assert errors, f"expected an error for ansible_timeout_minutes={bad_value!r}"
        assert "ansible_timeout_minutes" in errors[0]


def test_resolve_ansible_timeout_seconds_defaults_and_converts():
    from app.services.build_manager.template_service import resolve_ansible_timeout_seconds

    # No key at all — every existing template before this change — must
    # keep behaving exactly like the old hardcoded 30-minute constant.
    assert resolve_ansible_timeout_seconds({"hosts": []}) == 1800
    assert resolve_ansible_timeout_seconds({"hosts": [], "ansible_timeout_minutes": 60}) == 3600
    assert resolve_ansible_timeout_seconds({"hosts": [], "ansible_timeout_minutes": 40}) == 2400

    # An environment-level override (from BMEnvironment.variables, set via
    # PATCH /environments/{id}/variables) takes priority over the template's
    # own value — lets one environment need more headroom than every other
    # environment sharing the same template.
    spec = {"hosts": [], "ansible_timeout_minutes": 60}
    assert resolve_ansible_timeout_seconds(spec, {"ansible_timeout_minutes": 120}) == 7200
    assert resolve_ansible_timeout_seconds(spec, {}) == 3600
    assert resolve_ansible_timeout_seconds(spec, None) == 3600


@pytest.mark.usefixtures("setup_db")
async def test_submit_job_persists_explicit_timeout_seconds():
    from app.core.database import async_session
    from app.services.build_manager.ansible_runner import submit_job

    async with async_session() as db:
        job = await submit_job(
            db, name="timeout-explicit-test", playbook="does-not-exist-timeout-test.yml",
            timeout_seconds=3600,
        )
    assert job.timeout_seconds == 3600


@pytest.mark.usefixtures("setup_db")
async def test_submit_job_defaults_timeout_to_global_setting_when_omitted():
    from app.core.config import settings
    from app.core.database import async_session
    from app.services.build_manager.ansible_runner import submit_job

    async with async_session() as db:
        job = await submit_job(
            db, name="timeout-default-test", playbook="does-not-exist-timeout-test.yml",
        )
    assert job.timeout_seconds == settings.BM_ANSIBLE_TIMEOUT


async def _wait_for_terminal(job_id: str, timeout: float = 30.0):
    from app.core.database import async_session
    from app.models.build_manager import BMJob
    from sqlalchemy import select

    elapsed = 0.0
    while elapsed < timeout:
        async with async_session() as db:
            current = (await db.execute(select(BMJob).where(BMJob.id == job_id))).scalar_one()
            if current.status in ("success", "failed"):
                return current
        await asyncio.sleep(0.2)
        elapsed += 0.2
    raise AssertionError(f"Job {job_id} never reached a terminal state within {timeout}s")


def _write_fail_fast_playbook(tmp_path_str: str) -> str:
    """Same fail-fast pattern as test_build_manager_auto_retry.py — a real
    host-level fatal line (no network/SSH involved) so the auto-retry chain
    actually fires, letting us confirm the retry's own job carries the same
    timeout_seconds as the original."""
    import pathlib
    path = pathlib.Path(tmp_path_str)
    path.write_text(
        "---\n"
        "- hosts: localhost\n"
        "  connection: local\n"
        "  gather_facts: false\n"
        "  tasks:\n"
        "    - name: Always fail\n"
        "      ansible.builtin.fail:\n"
        "        msg: intentional test failure\n"
    )
    return str(path)


@pytest.mark.usefixtures("setup_db")
async def test_auto_retry_job_carries_forward_the_same_timeout_seconds(monkeypatch):
    from app.core.config import settings
    from app.core.database import async_session
    from app.services.build_manager.ansible_runner import submit_job
    from app.models.build_manager import BMJob
    from sqlalchemy import select

    monkeypatch.setattr(settings, "BM_AUTO_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(settings, "BM_MAX_AUTO_RETRIES", 1)

    playbook_path = _write_fail_fast_playbook(f"/tmp/timeout-auto-retry-test-{uuid.uuid4().hex}.yml")

    async with async_session() as db:
        job = await submit_job(
            db, name="timeout-auto-retry-test-build", playbook=playbook_path,
            timeout_seconds=2400,
        )
        job_id = job.id

    original = await _wait_for_terminal(job_id)
    assert original.timeout_seconds == 2400

    retry_job = None
    for _ in range(50):
        async with async_session() as db:
            rows = (await db.execute(
                select(BMJob).where(BMJob.name == "Auto-retry 1: timeout-auto-retry-test-build")
            )).scalars().all()
        if rows:
            retry_job = rows[0]
            break
        await asyncio.sleep(0.2)
    assert retry_job is not None, "expected an automatic retry job to be created"
    assert retry_job.timeout_seconds == 2400, "retry must carry forward the same configured timeout, not the global default"


@pytest.mark.usefixtures("setup_db")
async def test_build_environment_resolves_timeout_from_template_spec(client):
    """A template with ansible_timeout_minutes: 60 must produce a BMJob with
    timeout_seconds == 3600; a template with the key absent keeps the
    current default (1800) — mirrors this session's established pattern of
    mocking ensure_containers_for_environment/cleanup so no real Docker
    socket is needed for this plumbing check."""
    from unittest.mock import AsyncMock, patch
    from app.services.build_manager import container_manager

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"timeout-60min-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "web", "products": [], "certs": []}], "ansible_timeout_minutes": 60},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Timeout 60min Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"timeout-60min-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])):
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    from app.core.database import async_session
    from app.models.build_manager import BMJob
    from sqlalchemy import select
    async with async_session() as db:
        job = (await db.execute(select(BMJob).where(BMJob.id == job_id))).scalar_one()
    assert job.timeout_seconds == 3600

    # Also confirm it's actually exposed over the API, not just persisted —
    # _job_to_dict() must list every BMJob field consumers might want.
    resp = await client.get(f"/api/v1/build/jobs/{job_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["timeout_seconds"] == 3600


@pytest.mark.usefixtures("setup_db")
async def test_save_new_version_carries_forward_timeout_when_omitted(client):
    """A previously-tuned ansible_timeout_minutes must survive a new version
    that doesn't explicitly repeat it — this is exactly how it went missing
    across the Full Stack golden path's real version history (a raw spec
    edit or the Template Builder wizard, neither of which is guaranteed to
    carry an already-set value forward on its own)."""
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"timeout-carry-forward-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "web", "products": [], "certs": []}], "ansible_timeout_minutes": 60},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    # New version's spec omits ansible_timeout_minutes entirely.
    resp = await client.put(f"/api/v1/build/templates/{template_id}", json={
        "spec": {"hosts": [{"role": "web", "products": [], "certs": []}, {"role": "web2", "products": [], "certs": []}]},
        "change_note": "add a second host, unrelated to timeout",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["current_spec"]["ansible_timeout_minutes"] == 60

    # An explicit value in the new spec still wins over the carried-forward one.
    resp = await client.put(f"/api/v1/build/templates/{template_id}", json={
        "spec": {"hosts": [{"role": "web", "products": [], "certs": []}], "ansible_timeout_minutes": 90},
        "change_note": "explicitly raise timeout",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["current_spec"]["ansible_timeout_minutes"] == 90


@pytest.mark.usefixtures("setup_db")
async def test_build_environment_defaults_timeout_when_spec_key_absent(client):
    from unittest.mock import AsyncMock, patch
    from app.services.build_manager import container_manager

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"timeout-default-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "web", "products": [], "certs": []}]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Timeout Default Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"timeout-default-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])):
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    from app.core.config import settings
    from app.core.database import async_session
    from app.models.build_manager import BMJob
    from sqlalchemy import select
    async with async_session() as db:
        job = (await db.execute(select(BMJob).where(BMJob.id == job_id))).scalar_one()
    assert job.timeout_seconds == settings.BM_ANSIBLE_TIMEOUT


@pytest.mark.usefixtures("setup_db")
async def test_environment_variables_override_timeout_beyond_template(client):
    """PATCH /environments/{id}/variables lets one environment ask for more
    time than its template's own ansible_timeout_minutes, without touching
    the template (which every other environment built from it also uses)."""
    from unittest.mock import AsyncMock, patch
    from app.services.build_manager import container_manager

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"timeout-env-override-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "web", "products": [], "certs": []}], "ansible_timeout_minutes": 60},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Timeout Env Override Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"timeout-env-override-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    # Rejects a value outside the allowed set.
    resp = await client.patch(f"/api/v1/build/environments/{env_id}/variables", json={
        "variables": {"signing_ca_id": ca_id, "ansible_timeout_minutes": 45},
    })
    assert resp.status_code == 422, resp.text

    # Accepts an allowed value and it takes priority over the template's own 60.
    resp = await client.patch(f"/api/v1/build/environments/{env_id}/variables", json={
        "variables": {"signing_ca_id": ca_id, "ansible_timeout_minutes": 120},
    })
    assert resp.status_code == 200, resp.text

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])):
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    from app.core.database import async_session
    from app.models.build_manager import BMJob
    from sqlalchemy import select
    async with async_session() as db:
        job = (await db.execute(select(BMJob).where(BMJob.id == job_id))).scalar_one()
    assert job.timeout_seconds == 7200
