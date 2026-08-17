"""Expose LB/RabbitMQ ports to the Docker host.

container_manager.create_container()/ensure_containers_for_environment()
already fully supported Docker PortBindings via an expose_ports dict — it
was just never populated with real data. This wires up two sources: (a) a
template-baked default (host["expose_ports"]: list[int], e.g. the
golden-path frontend-lb:443/rabbitmq:15671 — see
test_build_manager_golden_path_templates.py for those), and (b) a real
environment-level opt-in (variables.expose_ports: {role: bool}, from a
checkbox in EnvironmentsPage.tsx that existed but was never read back
server-side), expanded to that role's product default_ports. Port 80 is
always excluded — ssl-cert-manager itself permanently owns host port 80.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.build_manager import container_manager


def test_validate_spec_accepts_valid_expose_ports():
    from app.services.build_manager.template_service import validate_spec

    spec = {"hosts": [{"role": "web", "expose_ports": [443, 8443]}]}
    assert validate_spec(spec) == []


def test_validate_spec_rejects_non_list_or_non_int_expose_ports():
    from app.services.build_manager.template_service import validate_spec

    for bad_value in ("443", 443, {"443": "443"}, [443, "8443"], [443, 8443.0]):
        spec = {"hosts": [{"role": "web", "expose_ports": bad_value}]}
        errors = validate_spec(spec)
        assert errors, f"expected an error for expose_ports={bad_value!r}"
        assert "expose_ports" in errors[0]


def test_validate_spec_rejects_out_of_range_ports():
    from app.services.build_manager.template_service import validate_spec

    for bad_port in (0, -1, 70000):
        spec = {"hosts": [{"role": "web", "expose_ports": [bad_port]}]}
        errors = validate_spec(spec)
        assert errors, f"expected an error for port {bad_port}"
        assert "valid TCP port range" in errors[0]


def test_validate_spec_rejects_reserved_ports_80_and_8000():
    from app.services.build_manager.template_service import validate_spec

    for reserved_port in (80, 8000):
        spec = {"hosts": [{"role": "web", "expose_ports": [reserved_port]}]}
        errors = validate_spec(spec)
        assert errors, f"expected an error for reserved port {reserved_port}"
        assert "reserved" in errors[0]
        assert str(reserved_port) in errors[0]


async def _create_template_ca_env(client, spec: dict) -> tuple[str, str]:
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"expose-ports-test-{uuid.uuid4().hex[:8]}",
        "spec": spec,
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Expose Ports Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"expose-ports-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]
    return template_id, env_id


@pytest.mark.usefixtures("setup_db")
async def test_build_environment_publishes_template_default_expose_ports(client):
    """A host with expose_ports baked into the spec (the golden-path
    default) must be published without any environment-level opt-in."""
    spec = {
        "hosts": [
            {"role": "frontend-lb", "products": [], "certs": [], "expose_ports": [443]},
        ],
    }
    _, env_id = await _create_template_ca_env(client, spec)

    with patch.object(container_manager, "ensure_containers_for_environment",
                       new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 200, resp.text

    mock_ensure.assert_awaited_once()
    docker_hosts = mock_ensure.await_args.args[0]
    dh = next(h for h in docker_hosts if h["role"] == "frontend-lb")
    assert dh["expose_ports"] == {"443": "443"}


@pytest.mark.usefixtures("setup_db")
async def test_build_environment_expands_opt_in_checkbox_and_excludes_port_80(client):
    """variables.expose_ports (the environment-creation checkbox) must
    expand to that role's product default_ports, with port 80 excluded —
    ssl-cert-manager itself permanently owns host port 80, so publishing
    it for another host container would always fail at creation time."""
    resp = await client.post("/api/v1/build/catalogue/seed")
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/build/catalogue")
    assert resp.status_code == 200, resp.text
    nginx_lb = next(p for p in resp.json() if p["name"] == "nginx_lb")
    assert set(nginx_lb["default_ports"]) == {80, 443}

    spec = {
        "hosts": [
            {"role": "backend-lb", "products": [{"product": "nginx_lb", "version": "1", "vars": {}}], "certs": []},
        ],
    }
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"expose-ports-opt-in-{uuid.uuid4().hex[:8]}",
        "spec": spec,
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Expose Ports Opt-In Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"expose-ports-opt-in-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id, "expose_ports": {"backend-lb": True}},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    with patch.object(container_manager, "ensure_containers_for_environment",
                       new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 200, resp.text

    mock_ensure.assert_awaited_once()
    docker_hosts = mock_ensure.await_args.args[0]
    dh = next(h for h in docker_hosts if h["role"] == "backend-lb")
    assert dh["expose_ports"] == {"443": "443"}


@pytest.mark.usefixtures("setup_db")
async def test_build_environment_opt_in_checkbox_also_excludes_port_8000(client):
    """Found via a real live build: opting in a role whose product declares
    default_ports including 8000 (uvicorn) created a container requesting
    host port 8000 — permanently owned by ssl-cert-manager's own -p 8000:8000
    binding. The container's failed start left it running with zero network
    attachment at all (Docker's bridge endpoint setup didn't complete),
    a much worse outcome than a clean rejection. Must be excluded exactly
    like port 80."""
    resp = await client.post("/api/v1/build/catalogue/seed")
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/build/catalogue")
    uvicorn = next(p for p in resp.json() if p["name"] == "uvicorn")
    assert set(uvicorn["default_ports"]) == {8000}

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"expose-ports-8000-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [
            {"role": "backend", "products": [{"product": "uvicorn", "version": "0.32", "vars": {}}], "certs": []},
        ]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Expose Ports 8000 Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"expose-ports-8000-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id, "expose_ports": {"backend": True}},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    with patch.object(container_manager, "ensure_containers_for_environment",
                       new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 200, resp.text

    mock_ensure.assert_awaited_once()
    docker_hosts = mock_ensure.await_args.args[0]
    dh = next(h for h in docker_hosts if h["role"] == "backend")
    assert "expose_ports" not in dh, "port 8000 should have been excluded entirely, leaving nothing to publish"


@pytest.mark.usefixtures("setup_db")
async def test_build_environment_no_expose_ports_when_neither_source_present(client):
    spec = {
        "hosts": [
            {"role": "mysql", "products": [], "certs": []},
        ],
    }
    _, env_id = await _create_template_ca_env(client, spec)

    with patch.object(container_manager, "ensure_containers_for_environment",
                       new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 200, resp.text

    mock_ensure.assert_awaited_once()
    docker_hosts = mock_ensure.await_args.args[0]
    dh = next(h for h in docker_hosts if h["role"] == "mysql")
    assert "expose_ports" not in dh
