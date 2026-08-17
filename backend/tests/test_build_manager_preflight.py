"""Enhancement Plan Stage 3 — pre-flight validation before build.

Catches avoidable build failures (host unreachable, no sudo, low disk, no
package manager) before a job is submitted. Only registered SSH-type hosts
are actually probed — Docker-hosted and unregistered placeholder hosts get a
"checked": false, "ready": true pass-through, since there's nothing real to
probe until the build actually creates a container for them.
"""
import uuid

import pytest


async def _create_template_and_env(client, host_def: dict) -> tuple[str, str]:
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"preflight-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [host_def]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"preflight-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
    })
    assert resp.status_code == 201, resp.text
    return template_id, resp.json()["id"]


@pytest.mark.usefixtures("setup_db")
async def test_preflight_passes_through_unregistered_host(client):
    _, env_id = await _create_template_and_env(client, {"role": "generic1"})

    resp = await client.post(f"/api/v1/build/environments/{env_id}/preflight")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["ready"] is True
    assert report["hosts"] == [{"role": "generic1", "checked": False, "ready": True, "blockers": []}]


@pytest.mark.usefixtures("setup_db")
async def test_preflight_flags_unreachable_ssh_host(client):
    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": f"preflight-host-{uuid.uuid4().hex[:8]}",
        "ip": "10.255.255.1",  # unreachable, non-routable test address
        "connection_type": "ssh",
    })
    assert resp.status_code == 201, resp.text
    host_id = resp.json()["id"]

    _, env_id = await _create_template_and_env(client, {"role": "mysql1", "inventory_host_id": host_id})

    resp = await client.post(f"/api/v1/build/environments/{env_id}/preflight")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["ready"] is False
    host_report = report["hosts"][0]
    assert host_report["role"] == "mysql1"
    assert host_report["checked"] is True
    assert host_report["ready"] is False
    assert any("unreachable" in b.lower() for b in host_report["blockers"])


@pytest.mark.usefixtures("setup_db")
async def test_build_blocked_by_failed_preflight_returns_structured_report(client):
    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": f"preflight-build-host-{uuid.uuid4().hex[:8]}",
        "ip": "10.255.255.2", "connection_type": "ssh",
    })
    host_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Preflight Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"preflight-build-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "mysql1", "inventory_host_id": host_id}]},
    })
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"preflight-build-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    env_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "preflight" in detail
    assert detail["preflight"]["ready"] is False


@pytest.mark.usefixtures("setup_db")
async def test_build_force_true_bypasses_preflight(client):
    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": f"preflight-force-host-{uuid.uuid4().hex[:8]}",
        "ip": "10.255.255.3", "connection_type": "ssh",
    })
    host_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Preflight Force Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"preflight-force-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "mysql1", "inventory_host_id": host_id}]},
    })
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"preflight-force-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    env_id = resp.json()["id"]

    # Without force: blocked.
    resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 422

    # With force=true: proceeds despite the same unreachable host.
    resp = await client.post(f"/api/v1/build/environments/{env_id}/build?force=true")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "provisioning"

    job_id = resp.json()["job_id"]
    await client.post(f"/api/v1/build/jobs/{job_id}/cancel")
