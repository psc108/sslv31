"""Enhancement Plan Stage 8 — Ansible check-mode / dry-run.

dry_run is persisted on BMJob (not just a request-time flag) so a dry-run
job is never mistaken for a real one in job history, and threads through
both ad-hoc job submission and environment builds. Known, documented (not
statically detected) limitation: command/shell tasks often report
inaccurately under Ansible's --check mode.
"""
import uuid

import pytest


@pytest.mark.usefixtures("setup_db")
async def test_create_job_dry_run_persisted_and_appends_check_diff(client, caplog):
    import asyncio
    from app.core.database import async_session
    from app.models.build_manager import BMJob
    from sqlalchemy import select

    resp = await client.post("/api/v1/build/jobs", json={
        "name": "dry-run-test-no-playbook",
        "playbook": "does-not-exist-dry-run-test.yml",
        "dry_run": True,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["dry_run"] is True
    job_id = body["id"]

    with caplog.at_level("INFO", logger="app.services.build_manager.ansible_runner"):
        for _ in range(50):
            async with async_session() as db:
                current = (await db.execute(select(BMJob).where(BMJob.id == job_id))).scalar_one()
                if current.status in ("success", "failed"):
                    break
            await asyncio.sleep(0.2)

    assert current.status == "failed"
    assert current.dry_run is True

    executing_lines = [r.message for r in caplog.records if "executing:" in r.message]
    assert executing_lines, "expected an 'executing:' log line from _execute_job"
    assert "--check --diff" in executing_lines[-1]


@pytest.mark.usefixtures("setup_db")
async def test_create_job_without_dry_run_defaults_false_and_omits_check_diff(client, caplog):
    import asyncio
    from app.core.database import async_session
    from app.models.build_manager import BMJob
    from sqlalchemy import select

    resp = await client.post("/api/v1/build/jobs", json={
        "name": "real-run-test-no-playbook",
        "playbook": "does-not-exist-real-run-test.yml",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["dry_run"] is False
    job_id = body["id"]

    with caplog.at_level("INFO", logger="app.services.build_manager.ansible_runner"):
        for _ in range(50):
            async with async_session() as db:
                current = (await db.execute(select(BMJob).where(BMJob.id == job_id))).scalar_one()
                if current.status in ("success", "failed"):
                    break
            await asyncio.sleep(0.2)

    assert current.dry_run is False
    executing_lines = [r.message for r in caplog.records if "executing:" in r.message]
    assert executing_lines
    assert "--check --diff" not in executing_lines[-1]


@pytest.mark.usefixtures("setup_db")
async def test_retry_preserves_original_dry_run_flag(client):
    import json
    from app.core.database import async_session
    from app.models.build_manager import BMJob

    async with async_session() as db:
        job = BMJob(
            id=str(uuid.uuid4()), name="dry-run-retry-test", job_type="ansible",
            status="failed", playbook="site.yml", inventory_filter="",
            extra_vars="{}", exit_code=2, dry_run=True,
            failed_hosts=json.dumps(["target-mysql"]),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    resp = await client.post(f"/api/v1/build/jobs/{job_id}/retry")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["dry_run"] is True

    await client.post(f"/api/v1/build/jobs/{body['id']}/cancel")


async def _create_template_and_env_with_ca(client, host_def: dict) -> str:
    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Dry Run Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    assert resp.status_code == 201, resp.text
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"dry-run-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [host_def]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"dry-run-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        # A real IP (not a bare role name) so ip_allocations resolves to
        # something ipaddress.ip_address() accepts — otherwise build_environment
        # treats the allocation as a Docker container name and tries to create
        # one via the Docker socket, which this test has no business touching.
        "ip_overrides": {host_def["role"]: "10.99.99.98"},
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.usefixtures("setup_db")
async def test_build_dry_run_does_not_change_environment_status(client):
    """A dry-run build shouldn't move the environment through
    provisioning/active — nothing was actually applied, so its lifecycle
    status must stay exactly where it was."""
    env_id = await _create_template_and_env_with_ca(client, {"role": "generic1"})

    resp = await client.get(f"/api/v1/build/environments/{env_id}")
    assert resp.json()["status"] == "pending"

    resp = await client.post(f"/api/v1/build/environments/{env_id}/build?dry_run=true")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    resp = await client.get(f"/api/v1/build/environments/{env_id}")
    assert resp.json()["status"] == "pending"  # unchanged, unlike a real build's "provisioning"

    resp = await client.get(f"/api/v1/build/jobs/{job_id}")
    assert resp.json()["dry_run"] is True

    await client.post(f"/api/v1/build/jobs/{job_id}/cancel")
