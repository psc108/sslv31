"""Enhancement Plan Stage 4 — job retry-on-partial-failure.

Ansible's own .retry file mechanism names files after the playbook, not the
job, so concurrent/sequential runs of the same playbook would clobber each
other's retry file — this app tracks failed hosts per-job instead, parsed
from the job's own captured output (fatal:/UNREACHABLE! lines) as it streams
in, and stores them on BMJob.failed_hosts. These tests confirm the parsing
regex, the retry endpoint's --limit narrowing, and the full-rerun fallback
when no host-level failure was recorded (e.g. a playbook that doesn't exist
at all fails before any host is ever reached).
"""
import re
import uuid

import pytest


def test_fatal_host_regex_matches_standard_ansible_failure_lines():
    from app.services.build_manager.ansible_runner import _FATAL_HOST_RE

    assert _FATAL_HOST_RE.match('fatal: [target-mysql]: FAILED! => {"msg": "boom"}').group(1) == "target-mysql"
    assert _FATAL_HOST_RE.match('fatal: [10.0.0.5]: UNREACHABLE! => {"msg": "no route"}').group(1) == "10.0.0.5"
    assert _FATAL_HOST_RE.match("ok: [target-mysql]") is None
    assert _FATAL_HOST_RE.match("PLAY RECAP") is None


@pytest.mark.usefixtures("setup_db")
async def test_retry_falls_back_to_full_rerun_when_no_hosts_recorded(client):
    import asyncio
    from app.core.database import async_session
    from app.services.build_manager.ansible_runner import submit_job
    from app.models.build_manager import BMJob
    from sqlalchemy import select

    async with async_session() as db:
        job = await submit_job(
            db, name="retry-test-no-playbook", playbook="does-not-exist-retry-test.yml",
        )
        job_id = job.id

    for _ in range(50):
        async with async_session() as db:
            current = (await db.execute(select(BMJob).where(BMJob.id == job_id))).scalar_one()
            if current.status in ("success", "failed"):
                break
        await asyncio.sleep(0.2)

    assert current.status == "failed"
    assert current.failed_hosts is None  # no host-level result — failed before reaching inventory

    resp = await client.post(f"/api/v1/build/jobs/{job_id}/retry")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["failed_hosts"] == []
    assert body["inventory_filter"] == ""  # full re-run, matching the original's empty filter
    assert body["name"] == "Retry: retry-test-no-playbook"

    await client.post(f"/api/v1/build/jobs/{body['id']}/cancel")


@pytest.mark.usefixtures("setup_db")
async def test_retry_limits_to_recorded_failed_hosts(client):
    """Directly exercises the retry endpoint's --limit narrowing without
    needing a real multi-host Ansible run — sets BMJob.failed_hosts as if
    the parsing loop had already recorded it, since that parsing logic
    itself is covered by the regex test above."""
    import json
    from app.core.database import async_session
    from app.models.build_manager import BMJob
    from sqlalchemy import select

    async with async_session() as db:
        job = BMJob(
            id=str(uuid.uuid4()), name="retry-test-partial", job_type="ansible",
            status="failed", playbook="site.yml", inventory_filter="",
            extra_vars="{}", exit_code=2,
            failed_hosts=json.dumps(["target-mysql", "target-rabbitmq"]),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    resp = await client.post(f"/api/v1/build/jobs/{job_id}/retry")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["inventory_filter"] == "target-mysql,target-rabbitmq"
    assert body["failed_hosts"] == []  # the *new* job's own field — it hasn't run yet

    async with async_session() as db:
        new_job = (await db.execute(select(BMJob).where(BMJob.id == body["id"]))).scalar_one()
        assert new_job.playbook == "site.yml"

    await client.post(f"/api/v1/build/jobs/{body['id']}/cancel")


@pytest.mark.usefixtures("setup_db")
async def test_retry_rejects_non_failed_job(client):
    import json
    from app.core.database import async_session
    from app.models.build_manager import BMJob

    async with async_session() as db:
        job = BMJob(
            id=str(uuid.uuid4()), name="retry-test-success", job_type="ansible",
            status="success", playbook="site.yml", inventory_filter="",
            extra_vars="{}", exit_code=0,
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    resp = await client.post(f"/api/v1/build/jobs/{job_id}/retry")
    assert resp.status_code == 409
