"""Automatic job retry on transient host failures.

The user reported repeated live-build failures on this Docker host where an
in-progress SSH session gets killed for reasons outside Ansible/this app's
control (traced to the host's own network stack — see
Documentation/build_manager_operations_guide.md), leaving no way to fix the
root cause from here. The existing manual POST /jobs/{id}/retry endpoint
(Enhancement Plan Stage 4) already knows how to re-run just the failed
hosts — this makes that happen automatically, up to
settings.BM_MAX_AUTO_RETRIES times, only for failures that actually named
specific fatal/unreachable hosts (never for a hard config/logic error, which
gets no host-level result at all and would just fail identically again).
"""
import asyncio
import uuid

import pytest


def test_should_auto_retry_only_for_host_level_failures_under_the_cap():
    from app.services.build_manager.ansible_runner import _should_auto_retry

    # Real host-level failure, under the cap — retry.
    assert _should_auto_retry("failed", {"nfs-server"}, auto_retry_count=0, max_retries=3) is True
    assert _should_auto_retry("failed", {"nfs-server"}, auto_retry_count=2, max_retries=3) is True
    # Cap reached — final failure, no more retries.
    assert _should_auto_retry("failed", {"nfs-server"}, auto_retry_count=3, max_retries=3) is False
    # Hard config/logic error (e.g. bad playbook) never gets a host-level
    # result — failed_hosts is empty, so this must not retry (it would just
    # fail identically again).
    assert _should_auto_retry("failed", set(), auto_retry_count=0, max_retries=3) is False
    # Success never retries, regardless of failed_hosts.
    assert _should_auto_retry("success", {"nfs-server"}, auto_retry_count=0, max_retries=3) is False


def test_strip_auto_retry_prefix_avoids_stacking():
    from app.services.build_manager.ansible_runner import _strip_auto_retry_prefix

    assert _strip_auto_retry_prefix("Build environment: foo") == "Build environment: foo"
    assert _strip_auto_retry_prefix("Auto-retry 1: Build environment: foo") == "Build environment: foo"
    assert _strip_auto_retry_prefix("Auto-retry 2: Build environment: foo") == "Build environment: foo"


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
    """A playbook that fails almost instantly with a real host-level fatal
    line (no network/SSH involved), so _FATAL_HOST_RE picks up "localhost"
    as a failed host just like it would a real unreachable target."""
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
async def test_failed_job_with_known_host_auto_retries(monkeypatch):
    from app.core.config import settings
    from app.core.database import async_session
    from app.services.build_manager.ansible_runner import submit_job
    from app.models.build_manager import BMJob
    from sqlalchemy import select

    monkeypatch.setattr(settings, "BM_AUTO_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(settings, "BM_MAX_AUTO_RETRIES", 3)

    playbook_path = _write_fail_fast_playbook(f"/tmp/auto-retry-test-{uuid.uuid4().hex}.yml")

    async with async_session() as db:
        job = await submit_job(db, name="auto-retry-test-build", playbook=playbook_path)
        job_id = job.id

    original = await _wait_for_terminal(job_id)
    assert original.status == "failed"
    assert original.failed_hosts and "localhost" in original.failed_hosts
    assert original.auto_retry_count == 0

    # The auto-retry job should appear shortly after, without anyone calling
    # the manual retry endpoint.
    async with async_session() as db:
        retry_job = None
        for _ in range(50):
            rows = (await db.execute(
                select(BMJob).where(BMJob.name == "Auto-retry 1: auto-retry-test-build")
            )).scalars().all()
            if rows:
                retry_job = rows[0]
                break
            await asyncio.sleep(0.2)
        assert retry_job is not None, "expected an automatic retry job to be created"
        assert retry_job.auto_retry_count == 1
        assert retry_job.inventory_filter == "localhost"

    await _wait_for_terminal(retry_job.id)

    # And it keeps retrying (same failure every time, since the playbook
    # always fails) until settings.BM_MAX_AUTO_RETRIES is reached, then
    # stops for good — no fifth job.
    rows = []
    for _ in range(50):
        async with async_session() as db:
            rows = (await db.execute(select(BMJob).where(BMJob.playbook == playbook_path))).scalars().all()
        if len(rows) >= 4:  # original + 3 retries
            break
        await asyncio.sleep(0.2)
    assert len(rows) == 4, f"expected exactly 4 jobs (original + {settings.BM_MAX_AUTO_RETRIES} retries), got {len(rows)}"
    assert sorted(j.auto_retry_count for j in rows) == [0, 1, 2, 3]
    final = max(rows, key=lambda j: j.auto_retry_count)
    final = await _wait_for_terminal(final.id)
    assert final.status == "failed"

    # And truly no fifth job — the cap was respected.
    await asyncio.sleep(1)
    async with async_session() as db:
        rows = (await db.execute(select(BMJob).where(BMJob.playbook == playbook_path))).scalars().all()
    assert len(rows) == 4


@pytest.mark.usefixtures("setup_db")
async def test_failed_job_without_host_level_result_does_not_auto_retry():
    """A hard config/logic error (here: a playbook that doesn't exist at
    all) never reaches a host, so failed_hosts stays empty — must not
    auto-retry, since a retry would just fail identically again."""
    from app.core.database import async_session
    from app.services.build_manager.ansible_runner import submit_job
    from app.models.build_manager import BMJob
    from sqlalchemy import select

    async with async_session() as db:
        job = await submit_job(db, name="auto-retry-test-no-hosts", playbook="does-not-exist-auto-retry-test.yml")
        job_id = job.id

    original = await _wait_for_terminal(job_id)
    assert original.status == "failed"
    assert not original.failed_hosts

    await asyncio.sleep(1)  # give any (incorrect) auto-retry a moment to appear
    async with async_session() as db:
        rows = (await db.execute(
            select(BMJob).where(BMJob.name.like("Auto-retry%auto-retry-test-no-hosts%"))
        )).scalars().all()
        assert rows == []
