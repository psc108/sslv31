"""Builtin NFS Server reference template + persistent named-volume export.

The nfs_server/nfs_client catalogue products and Ansible roles already
existed (playbooks/roles/nfs_server, nfs_client) — the real gap was that a
Docker-hosted target container's export directory lived in the container's
own ephemeral writable layer, since container_manager.py had no way to bind
a persistent volume in. A named Docker volume is used rather than a raw
host-path bind — live-testing this found that a bind-mounted host directory
is only exportable via NFS if its underlying filesystem supports it, which a
plain host path often doesn't (e.g. Docker Desktop for Windows shares host
drives via 9p, which the kernel NFS server refuses to export outright,
confirmed via `exportfs`, no export option works around it). A named volume
lives on Docker's own managed disk (real ext4/xfs), which exports correctly.

These tests cover: create_container()'s new extra_binds param actually
reaching the Docker Engine API call, build_environment() deriving the right
per-role bind from a new variables.nfs_volumes convention (and not touching
hosts that don't have one), and the new seed template itself.
"""
import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services.build_manager import container_manager


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient — only the two calls create_container
    actually needs (create + start) are meaningfully handled; everything
    else returns an empty 200 so helper lookups don't blow up."""

    def __init__(self, captured_calls):
        self.captured_calls = captured_calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.captured_calls.append((url, kwargs))
        if url == "/containers/create":
            return _FakeResponse(201, {"Id": "abc123"})
        if url.endswith("/start"):
            return _FakeResponse(204)
        return _FakeResponse(200)

    async def get(self, url, **kwargs):
        return _FakeResponse(200, {})


async def test_create_container_includes_extra_binds_in_docker_config():
    captured: list = []
    with patch.object(container_manager, "container_exists", new=AsyncMock(return_value=False)), \
         patch.object(container_manager, "_get_target_image", new=AsyncMock(return_value="test-image")), \
         patch.object(container_manager, "_get_network_name", new=AsyncMock(return_value="test-net")), \
         patch.object(container_manager, "_get_volume_name", new=AsyncMock(return_value="test-vol")), \
         patch.object(container_manager.httpx, "AsyncClient", new=lambda *a, **k: _FakeAsyncClient(captured)):
        result = await container_manager.create_container(
            "nfs-test", extra_binds=["nfs-data-vol:/srv/nfs-export"],
        )

    assert result["status"] == "created"
    create_call = next(c for c in captured if c[0] == "/containers/create")
    binds = create_call[1]["json"]["HostConfig"]["Binds"]
    assert "nfs-data-vol:/srv/nfs-export" in binds
    # The existing default binds must still be present — this is additive.
    assert any("certmanager-data" in b for b in binds)


async def test_create_container_omits_extra_binds_when_not_given():
    captured: list = []
    with patch.object(container_manager, "container_exists", new=AsyncMock(return_value=False)), \
         patch.object(container_manager, "_get_target_image", new=AsyncMock(return_value="test-image")), \
         patch.object(container_manager, "_get_network_name", new=AsyncMock(return_value="test-net")), \
         patch.object(container_manager, "_get_volume_name", new=AsyncMock(return_value="test-vol")), \
         patch.object(container_manager.httpx, "AsyncClient", new=lambda *a, **k: _FakeAsyncClient(captured)):
        await container_manager.create_container("plain-test")

    create_call = next(c for c in captured if c[0] == "/containers/create")
    binds = create_call[1]["json"]["HostConfig"]["Binds"]
    assert len(binds) == 2  # only the two hardcoded defaults, nothing extra


async def test_wait_for_ssh_port_ready_returns_true_once_port_opens():
    mock_writer = Mock()
    mock_writer.wait_closed = AsyncMock()
    with patch("asyncio.open_connection", new=AsyncMock(return_value=(Mock(), mock_writer))):
        result = await container_manager._wait_for_ssh_port_ready("some-host", timeout=5, interval=0.1)
    assert result is True


async def test_wait_for_ssh_port_ready_gives_up_after_timeout():
    """Kept short (0.3s) deliberately — this exercises the real give-up path
    without the test itself hanging for the production default of 60s."""
    with patch("asyncio.open_connection", new=AsyncMock(side_effect=OSError("no route to host"))):
        result = await container_manager._wait_for_ssh_port_ready("no-such-host", timeout=0.3, interval=0.1)
    assert result is False


async def test_ensure_containers_for_environment_threads_extra_binds_through():
    with patch.object(container_manager, "create_container", new=AsyncMock(return_value={"status": "created"})) as mock_create, \
         patch.object(container_manager, "_wait_for_ssh_port_ready", new=AsyncMock(return_value=True)):
        await container_manager.ensure_containers_for_environment([
            {"role": "nfs-server", "container_name": "env-nfs-server", "connection_type": "docker",
             "extra_binds": ["nfs-data-vol:/srv/nfs-export"]},
            {"role": "web", "container_name": "env-web", "connection_type": "docker"},
        ])

    calls = {c.args[0]: c.args for c in mock_create.call_args_list}
    assert calls["env-nfs-server"][2] == ["nfs-data-vol:/srv/nfs-export"]
    assert calls["env-web"][2] is None


def test_seeded_nfs_template_passes_spec_validation():
    from app.services.build_manager.template_service import validate_spec, SEED_TEMPLATES

    nfs_template = next(t for t in SEED_TEMPLATES if "NFS" in t["name"])
    errors = validate_spec(nfs_template["spec"])
    assert errors == []

    host = nfs_template["spec"]["hosts"][0]
    assert host["role"] == "nfs-server"
    export = host["products"][0]["vars"]["nfs_exports"][0]
    assert export["path"] == "/srv/nfs-export"
    assert "no_root_squash" in export["options"]
    assert "fsid=0" in export["options"]


def test_nfs_client_default_mount_opts_use_working_nfsv3_not_broken_default():
    """Regression: the NFS Client product's default/placeholder mount opts
    used to suggest nfsvers=4, which fails to mount against this server
    (confirmed by real cross-container testing — NFSv4 needs a properly
    configured pseudo-filesystem root this minimal appliance doesn't set
    up). nolock,vers=3 is what was actually confirmed to work."""
    from app.services.build_manager.catalogue_service import SEED_PRODUCTS

    nfs_client = next(p for p in SEED_PRODUCTS if p["name"] == "nfs_client")
    mounts_field = next(f for f in nfs_client["config_schema"] if f["key"] == "nfs_mounts")
    opts_field = next(f for f in mounts_field["item_schema"] if f["key"] == "opts")
    assert opts_field["default"] == "nolock,vers=3"
    assert "nfsvers=4" not in opts_field["placeholder"]


@pytest.mark.usefixtures("setup_db")
async def test_template_baked_in_product_vars_survive_provisioning_when_unoverridden(client):
    """Real build failure, reported by the user: the seeded NFS Server
    template bakes nfs_exports directly into the product's vars, but the
    Environments page's Product Configuration form used to always populate
    variables.product_config with the config_schema's own defaults — and
    nfs_exports's schema default is an empty list. Since product_config
    takes precedence over the template's vars in provision_environment()
    (base_provisioner.py's _get_product_config merge), that empty default
    silently overwrote the template's real value, so nfs_exports came
    through empty and the Ansible role's /etc/exports write task failed.
    The actual fix is in EnvironmentsPage.tsx (no frontend test harness
    exists in this repo) — this pins the server-side half of the contract:
    with no product_config override at all for this product, the
    template's own baked-in vars must reach Ansible's extra_vars intact."""
    from app.services.build_manager.base_provisioner import provision_environment

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"nfs-vars-survive-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "nfs-server", "products": [
            {"product": "nfs_server", "version": "4", "vars": {
                "nfs_exports": [{"path": "/srv/nfs-export", "clients": "*", "options": "rw,sync,no_subtree_check,no_root_squash"}],
            }},
        ], "certs": []}]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"NFS Vars Survive Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"nfs-vars-survive-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},  # deliberately no product_config at all
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    from app.core.database import async_session
    async with async_session() as db:
        provision_data = await provision_environment(db, env_id)

    nfs_exports = provision_data["host_products"]["nfs-server"][0]["vars"]["nfs_exports"]
    assert nfs_exports == [{"path": "/srv/nfs-export", "clients": "*", "options": "rw,sync,no_subtree_check,no_root_squash"}]


async def _create_docker_template_and_env(client, role: str, product: dict) -> tuple[str, str]:
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"nfs-bind-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": role, "products": [product], "certs": []}]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"NFS Bind Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"nfs-bind-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id, "nfs_volumes": {role: "nfs-data-vol"}},
    })
    assert resp.status_code == 201, resp.text
    return template_id, resp.json()["id"]


@pytest.mark.usefixtures("setup_db")
async def test_build_environment_derives_extra_binds_for_matching_role(client):
    """End-to-end through the real /build endpoint (docker-fallback, no
    inventory_host_id — same mode the seeded templates use), with
    ensure_containers_for_environment mocked so this never touches a real
    Docker socket, only asserting on exactly what it was called with."""
    _, env_id = await _create_docker_template_and_env(
        client, "nfs-server", {"product": "nfs_server", "version": "4", "vars": {}},
    )

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")

    assert resp.status_code == 200, resp.text
    called_hosts = mock_ensure.call_args.args[0]
    nfs_host = next(h for h in called_hosts if h["role"] == "nfs-server")
    assert nfs_host["extra_binds"] == ["nfs-data-vol:/srv/nfs-export"]


@pytest.mark.usefixtures("setup_db")
async def test_build_environment_auto_generates_volume_for_nfs_server_without_explicit_name(client):
    """Real failure, found via a live build: an nfs_server host with no
    variables.nfs_volumes entry at all got no extra_binds, so /srv/nfs-export
    was just the container's own overlay2 root filesystem — and exportfs
    fails on that too, not just on a 9p-backed host-path bind ("does not
    support NFS export" either way). Every nfs_server host now always gets a
    named-volume bind, auto-generating a name (scoped to this environment +
    role, so a rebuild reuses the same one) when the user didn't supply one."""
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"nfs-autovol-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "nfs-server", "products": [
            {"product": "nfs_server", "version": "4", "vars": {}},
        ], "certs": []}]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"NFS Autovol Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"nfs-autovol-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},  # no nfs_volumes at all
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")

    assert resp.status_code == 200, resp.text
    called_hosts = mock_ensure.call_args.args[0]
    nfs_host = next(h for h in called_hosts if h["role"] == "nfs-server")
    assert nfs_host["extra_binds"] == [f"nfs-auto-{env_id[:8]}-nfs-server:/srv/nfs-export"]


@pytest.mark.usefixtures("setup_db")
async def test_build_environment_omits_extra_binds_when_nfs_volumes_absent(client):
    """Regression: a template/environment with no nfs_volumes variable
    at all must build exactly as before this change — no extra_binds key,
    no error."""
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"no-bind-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1", "products": [], "certs": []}]},
    })
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"No Bind Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"no-bind-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    env_id = resp.json()["id"]

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")

    assert resp.status_code == 200, resp.text
    called_hosts = mock_ensure.call_args.args[0]
    assert "extra_binds" not in called_hosts[0]


@pytest.mark.usefixtures("setup_db")
async def test_rebuild_environment_also_ensures_docker_containers(client):
    """Real failure, reported by the user: rebuild_environment() never
    ensured Docker containers existed at all — it went straight to
    re-issuing certs and re-running Ansible, on the (wrong, for a
    Docker-hosted host) assumption the target infrastructure was already
    there. If the container isn't currently running for any reason (never
    successfully created, removed by destroy, manual cleanup, host
    restart...), Ansible fails with "Could not resolve hostname" since
    nothing ever recreates it. Fixed by extracting the same container-
    ensuring logic build_environment already had into a shared helper and
    calling it from rebuild_environment too."""
    _, env_id = await _create_docker_template_and_env(
        client, "nfs-server", {"product": "nfs_server", "version": "4", "vars": {}},
    )
    # A real build first, so rebuild has real certs/bindings to revoke.
    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])):
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 200, resp.text

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/rebuild")

    assert resp.status_code == 200, resp.text
    assert mock_ensure.called
    called_hosts = mock_ensure.call_args.args[0]
    nfs_host = next(h for h in called_hosts if h["role"] == "nfs-server")
    assert nfs_host["extra_binds"] == ["nfs-data-vol:/srv/nfs-export"]


@pytest.mark.usefixtures("setup_db")
async def test_build_environment_rejects_path_shaped_volume_name(client):
    """Real failure, reported by the user: they typed a real Windows path
    (a OneDrive folder) into the Storage Volume Name field. Docker Desktop
    auto-translates anything path-shaped into a host-path bind instead of
    creating a named volume, silently reproducing the exact 9p
    "does not support NFS export" failure the named-volume design exists to
    avoid — but only ~10 minutes into a build, as a cryptic exportfs error.
    Fixed by validating the value looks like a legal Docker volume name
    before ever creating the container, failing fast with a clear reason."""
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"nfs-badvol-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "nfs-server", "products": [
            {"product": "nfs_server", "version": "4", "vars": {}},
        ], "certs": []}]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"NFS Bad Volume Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"nfs-badvol-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {
            "signing_ca_id": ca_id,
            "nfs_volumes": {"nfs-server": r"C:\Users\pscott32\OneDrive - DXC Production\shared"},
        },
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")

    assert resp.status_code == 422, resp.text
    assert "not a valid Docker volume name" in resp.json()["detail"]
    assert not mock_ensure.called
