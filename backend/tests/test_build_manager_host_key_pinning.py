"""Enhancement Plan Stage 9 — host-key verification (TOFU pinning).

Every SSH connection previously used StrictHostKeyChecking=no everywhere,
including the actual Ansible job run — protecting authentication (per-host
credentials) but not against a MITM substituting the target entirely. This
pins each registered SSH-type BMHost's real host key on first successful
connection and rejects a later, different key unless explicitly re-accepted.
Full enforcement (per user decision) covers both the connection-test/
preflight path and the real ansible-playbook invocation via a per-job
known_hosts file + --ssh-common-args.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.build_manager.host_key_service import _key_material


KEY_A = "10.99.1.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKeyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
KEY_A_DIFFERENT_HOST_COLUMN = "some-other-hostname ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKeyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
KEY_B = "10.99.1.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICompletelyDifferentKeyMaterialHereXX"


def test_key_material_ignores_leading_host_column():
    assert _key_material(KEY_A) == _key_material(KEY_A_DIFFERENT_HOST_COLUMN)
    assert _key_material(KEY_A) != _key_material(KEY_B)


def test_key_material_handles_malformed_input():
    assert _key_material("") is None
    assert _key_material("justonefield") is None


async def test_fetch_host_key_never_uses_a_shell_and_rejects_option_like_host():
    from app.services.build_manager.host_key_service import fetch_host_key

    with patch("app.services.build_manager.host_key_service.asyncio.create_subprocess_shell") as shell_mock, \
         patch("app.services.build_manager.host_key_service.asyncio.create_subprocess_exec", new_callable=AsyncMock) as exec_mock:
        exec_mock.return_value = AsyncMock(returncode=0, communicate=AsyncMock(return_value=(KEY_A.encode(), b"")))
        result = await fetch_host_key("10.99.1.1", 22)

    shell_mock.assert_not_called()
    assert result == KEY_A

    with patch("app.services.build_manager.host_key_service.asyncio.create_subprocess_exec", new_callable=AsyncMock) as exec_mock:
        result = await fetch_host_key("-oProxyCommand=evil", 22)
    exec_mock.assert_not_called()
    assert result is None


async def _make_ssh_host(client, ip="10.99.1.1") -> str:
    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": f"pinning-test-{uuid.uuid4().hex[:8]}",
        "ip": ip, "connection_type": "ssh",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.usefixtures("setup_db")
async def test_verify_or_pin_pins_on_first_connection(client):
    from app.core.database import async_session
    from app.models.build_manager import BMHost
    from app.services.build_manager.host_key_service import verify_or_pin_host_key
    from sqlalchemy import select

    host_id = await _make_ssh_host(client)

    async with async_session() as db:
        host = (await db.execute(select(BMHost).where(BMHost.id == host_id))).scalar_one()
        assert host.pinned_host_key is None

        with patch("app.services.build_manager.host_key_service.fetch_host_key", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = KEY_A
            ok, message = await verify_or_pin_host_key(db, host)

        assert ok is True
        assert "pinned" in message.lower()
        assert host.pinned_host_key == KEY_A
        assert host.host_key_pinned_at is not None


@pytest.mark.usefixtures("setup_db")
async def test_verify_or_pin_accepts_matching_key_even_under_different_host_column(client):
    from app.core.database import async_session
    from app.models.build_manager import BMHost
    from app.services.build_manager.host_key_service import verify_or_pin_host_key
    from sqlalchemy import select

    host_id = await _make_ssh_host(client)

    async with async_session() as db:
        host = (await db.execute(select(BMHost).where(BMHost.id == host_id))).scalar_one()
        host.pinned_host_key = KEY_A
        await db.commit()

        with patch("app.services.build_manager.host_key_service.fetch_host_key", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = KEY_A_DIFFERENT_HOST_COLUMN
            ok, message = await verify_or_pin_host_key(db, host)

    assert ok is True
    assert "verified" in message.lower()


@pytest.mark.usefixtures("setup_db")
async def test_verify_or_pin_rejects_changed_key(client):
    from app.core.database import async_session
    from app.models.build_manager import BMHost
    from app.services.build_manager.host_key_service import verify_or_pin_host_key
    from sqlalchemy import select

    host_id = await _make_ssh_host(client)

    async with async_session() as db:
        host = (await db.execute(select(BMHost).where(BMHost.id == host_id))).scalar_one()
        host.pinned_host_key = KEY_A
        await db.commit()

        with patch("app.services.build_manager.host_key_service.fetch_host_key", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = KEY_B
            ok, message = await verify_or_pin_host_key(db, host)

    assert ok is False
    assert "CHANGED" in message
    # Rejecting must not silently clobber the pinned value.
    async with async_session() as db:
        host = (await db.execute(select(BMHost).where(BMHost.id == host_id))).scalar_one()
        assert host.pinned_host_key == KEY_A


@pytest.mark.usefixtures("setup_db")
async def test_accept_new_host_key_endpoint_repins_and_audits(client):
    from app.core.database import async_session
    from app.models.build_manager import BMHost
    from sqlalchemy import select

    host_id = await _make_ssh_host(client)

    async with async_session() as db:
        host = (await db.execute(select(BMHost).where(BMHost.id == host_id))).scalar_one()
        host.pinned_host_key = KEY_A
        await db.commit()

    with patch("app.services.build_manager.host_key_service.fetch_host_key", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = KEY_B
        resp = await client.post(f"/api/v1/build/hosts/{host_id}/accept-host-key")

    assert resp.status_code == 200, resp.text
    assert resp.json()["pinned_host_key"] == KEY_B

    async with async_session() as db:
        host = (await db.execute(select(BMHost).where(BMHost.id == host_id))).scalar_one()
        assert host.pinned_host_key == KEY_B

    from app.models.audit import AuditEvent
    async with async_session() as db:
        events = (await db.execute(
            select(AuditEvent).where(AuditEvent.event_type == "BM_HOST_KEY_ACCEPTED", AuditEvent.subject_id == host_id)
        )).scalars().all()
    assert len(events) == 1
    assert events[0].severity == "WARNING"


@pytest.mark.usefixtures("setup_db")
async def test_accept_host_key_rejects_docker_hosts(client):
    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": f"pinning-docker-{uuid.uuid4().hex[:8]}",
        "ip": "127.0.0.1", "connection_type": "docker", "container_name": "some-container",
    })
    host_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/build/hosts/{host_id}/accept-host-key")
    assert resp.status_code == 422


@pytest.mark.usefixtures("setup_db")
async def test_test_endpoint_blocks_and_reports_status_when_key_changed(client):
    from app.core.database import async_session
    from app.models.build_manager import BMHost
    from app.services.build_manager import SSHTestResult
    from sqlalchemy import select

    host_id = await _make_ssh_host(client)
    async with async_session() as db:
        host = (await db.execute(select(BMHost).where(BMHost.id == host_id))).scalar_one()
        host.pinned_host_key = KEY_A
        await db.commit()

    with patch("app.services.build_manager.test_ssh_connectivity", new_callable=AsyncMock) as mock_conn, \
         patch("app.services.build_manager.host_key_service.fetch_host_key", new_callable=AsyncMock) as mock_fetch:
        mock_conn.return_value = SSHTestResult(success=True, message="Connection successful", latency_ms=12.0)
        mock_fetch.return_value = KEY_B
        resp = await client.post(f"/api/v1/build/hosts/{host_id}/test")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is False
    assert "CHANGED" in body["host_key_status"]
    assert body["host_key_status"] in body["message"] or body["message"] == body["host_key_status"]

    resp = await client.get(f"/api/v1/build/hosts/{host_id}")
    assert resp.json()["status"] == "offline"


async def _create_environment_with_ssh_host(client, host_id: str) -> str:
    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Pinning Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"pinning-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "mysql1", "inventory_host_id": host_id}]},
    })
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"pinning-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.usefixtures("setup_db")
async def test_job_fails_immediately_on_host_key_mismatch_without_running_ansible(client):
    import asyncio
    from app.core.database import async_session
    from app.models.build_manager import BMHost, BMJob
    from sqlalchemy import select

    host_id = await _make_ssh_host(client, ip="10.99.1.2")
    async with async_session() as db:
        host = (await db.execute(select(BMHost).where(BMHost.id == host_id))).scalar_one()
        host.pinned_host_key = KEY_A.replace("10.99.1.1", "10.99.1.2")
        await db.commit()

    env_id = await _create_environment_with_ssh_host(client, host_id)

    with patch("app.services.build_manager.host_key_service.fetch_host_key", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = KEY_B.replace("10.99.1.1", "10.99.1.2")
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build?force=true")
        assert resp.status_code == 200, resp.text
        job_id = resp.json()["job_id"]

        for _ in range(50):
            async with async_session() as db:
                current = (await db.execute(select(BMJob).where(BMJob.id == job_id))).scalar_one()
                if current.status in ("success", "failed"):
                    break
            await asyncio.sleep(0.2)

    assert current.status == "failed"
    resp = await client.get(f"/api/v1/build/jobs/{job_id}/output")
    lines = [l["line"] for l in resp.json()["lines"]]
    assert any("Host key verification failed" in l for l in lines)
    assert any("CHANGED" in l for l in lines)


@pytest.mark.usefixtures("setup_db")
async def test_job_enforces_pinned_keys_via_ssh_common_args(client, caplog):
    """The 'executing:' log line is emitted right after cmd_parts is built,
    before the ansible-playbook subprocess even starts — no need to wait for
    the (unreachable) target's real SSH timeout to see it, so this cancels
    the job immediately after rather than polling it to a terminal state."""
    import asyncio

    host_id = await _make_ssh_host(client, ip="10.99.1.3")
    env_id = await _create_environment_with_ssh_host(client, host_id)

    with patch("app.services.build_manager.host_key_service.fetch_host_key", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = KEY_A.replace("10.99.1.1", "10.99.1.3")
        with caplog.at_level("INFO", logger="app.services.build_manager.ansible_runner"):
            resp = await client.post(f"/api/v1/build/environments/{env_id}/build?force=true")
            assert resp.status_code == 200, resp.text
            job_id = resp.json()["job_id"]

            executing_lines = []
            for _ in range(25):
                executing_lines = [r.message for r in caplog.records if "executing:" in r.message]
                if executing_lines:
                    break
                await asyncio.sleep(0.2)

    await client.post(f"/api/v1/build/jobs/{job_id}/cancel")

    assert executing_lines
    assert "--ssh-common-args" in executing_lines[-1]
    assert "UserKnownHostsFile" in executing_lines[-1]
    assert "StrictHostKeyChecking=yes" in executing_lines[-1]
