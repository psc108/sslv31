"""Shared package-cache Docker volume — replaces an earlier NFS-based design.

Running the actual NFS kernel server (nfsd) inside a container turned out to
be unstable on this Docker host: live-testing found the nfs-server
container's whole process tree repeatedly crashing and silently
auto-restarting (RestartCount climbing into double digits within minutes)
while every other container in the same build stayed at 0 restarts — pointing
squarely at nfsd itself, not the network, not SSH, not this app. Since every
"host" in a Docker-fallback template is already a container on the same
Docker engine, a single named Docker volume mounted directly into multiple
containers gives them all the same directory with zero network filesystem
involved at all. These tests cover _ensure_docker_hosts_ready deriving the
right extra_binds for both the seed host (pkg_cache_seed product) and every
consumer host (local_repo product), sharing one volume name.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.build_manager import container_manager


async def _create_pkg_cache_template_and_env(client, nfs_volumes_override: dict | None = None) -> tuple[str, str]:
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"pkg-cache-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [
            {"role": "seed", "products": [
                {"product": "pkg_cache_seed", "version": "1", "vars": {"pkg_cache_seed_packages": ["nginx"]}},
            ], "certs": []},
            {"role": "consumer", "products": [
                {"product": "local_repo", "version": "1", "vars": {"local_repo_cache_dir": "/mnt/pkg-cache"}},
                {"product": "nginx", "version": "1.26", "vars": {}},
            ], "certs": ["server_tls"]},
        ]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Pkg Cache Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    variables = {"signing_ca_id": ca_id}
    if nfs_volumes_override:
        variables.update(nfs_volumes_override)

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"pkg-cache-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": variables,
    })
    assert resp.status_code == 201, resp.text
    return template_id, resp.json()["id"]


@pytest.mark.usefixtures("setup_db")
async def test_seed_and_consumer_hosts_share_one_auto_generated_volume(client):
    _, env_id = await _create_pkg_cache_template_and_env(client)

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")

    assert resp.status_code == 200, resp.text
    called_hosts = mock_ensure.call_args.args[0]
    seed_host = next(h for h in called_hosts if h["role"] == "seed")
    consumer_host = next(h for h in called_hosts if h["role"] == "consumer")

    assert seed_host["extra_binds"] == [f"pkg-cache-{env_id[:8]}:/mnt/pkg-cache"]
    # Same volume name on both sides — that's the whole point.
    assert consumer_host["extra_binds"] == seed_host["extra_binds"]


@pytest.mark.usefixtures("setup_db")
async def test_explicit_pkg_cache_volume_name_overrides_auto_generated(client):
    _, env_id = await _create_pkg_cache_template_and_env(
        client, nfs_volumes_override={"pkg_cache_volume": "my-shared-cache"},
    )

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")

    assert resp.status_code == 200, resp.text
    called_hosts = mock_ensure.call_args.args[0]
    for host in called_hosts:
        assert host["extra_binds"] == ["my-shared-cache:/mnt/pkg-cache"]


@pytest.mark.usefixtures("setup_db")
async def test_path_shaped_pkg_cache_volume_name_rejected(client):
    _, env_id = await _create_pkg_cache_template_and_env(
        client, nfs_volumes_override={"pkg_cache_volume": r"C:\Users\test\shared"},
    )

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")

    assert resp.status_code == 422, resp.text
    assert "not a valid Docker volume name" in resp.json()["detail"]
    assert not mock_ensure.called


@pytest.mark.usefixtures("setup_db")
async def test_host_with_neither_product_gets_no_pkg_cache_bind(client):
    """A host with no pkg_cache_seed/local_repo product at all shouldn't get
    the shared volume bound — only hosts that actually need it."""
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"pkg-cache-mixed-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [
            {"role": "seed", "products": [
                {"product": "pkg_cache_seed", "version": "1", "vars": {"pkg_cache_seed_packages": ["nginx"]}},
            ], "certs": []},
            {"role": "unrelated", "products": [], "certs": []},
        ]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Pkg Cache Mixed Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"pkg-cache-mixed-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")

    assert resp.status_code == 200, resp.text
    called_hosts = mock_ensure.call_args.args[0]
    seed_host = next(h for h in called_hosts if h["role"] == "seed")
    unrelated_host = next(h for h in called_hosts if h["role"] == "unrelated")
    assert "extra_binds" in seed_host
    assert "extra_binds" not in unrelated_host


@pytest.mark.usefixtures("setup_db")
async def test_hosts_using_real_nfs_skip_the_docker_volume_bind(client):
    """A host that pairs pkg_cache_seed/local_repo with nfs_server/nfs_client
    is opting into real NFS instead of the Docker-volume shortcut (this is
    what the Full Stack golden-path template does) — it should get the
    nfs_server_roles bind at /srv/nfs-export (if applicable) but NOT also
    get an unused Docker volume bound at /mnt/pkg-cache, which would just be
    empty clutter sitting underneath the real NFS mount Ansible sets up
    there."""
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"pkg-cache-nfs-mix-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [
            {"role": "seed", "products": [
                {"product": "nfs_server", "version": "4", "vars": {
                    "nfs_exports": [{"path": "/srv/nfs-export", "clients": "*", "options": "rw,sync,no_subtree_check,no_root_squash"}],
                }},
                {"product": "pkg_cache_seed", "version": "1", "vars": {
                    "pkg_cache_seed_dir": "/srv/nfs-export/apt", "pkg_cache_seed_packages": ["nginx"],
                }},
            ], "certs": []},
            {"role": "consumer", "products": [
                {"product": "nfs_client", "version": "4", "vars": {"nfs_mounts": [
                    {"src": "seed:/srv/nfs-export", "path": "/mnt/pkg-cache", "opts": "nolock,vers=3"},
                ]}},
                {"product": "local_repo", "version": "1", "vars": {"local_repo_cache_dir": "/mnt/pkg-cache"}},
                {"product": "nginx", "version": "1.26", "vars": {}},
            ], "certs": ["server_tls"]},
        ]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Pkg Cache NFS Mix Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"pkg-cache-nfs-mix-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    with patch.object(container_manager, "ensure_containers_for_environment", new=AsyncMock(return_value=[])) as mock_ensure:
        resp = await client.post(f"/api/v1/build/environments/{env_id}/build")

    assert resp.status_code == 200, resp.text
    called_hosts = mock_ensure.call_args.args[0]
    seed_host = next(h for h in called_hosts if h["role"] == "seed")
    consumer_host = next(h for h in called_hosts if h["role"] == "consumer")
    # seed_host gets exactly one bind — the real nfs_server export volume —
    # not a second /mnt/pkg-cache Docker volume on top of it.
    assert seed_host["extra_binds"] == [b for b in seed_host["extra_binds"] if b.endswith(":/srv/nfs-export")]
    assert not any(b.endswith(":/mnt/pkg-cache") for b in seed_host["extra_binds"])
    # consumer_host has no nfs_server product, so no nfs_server_roles bind
    # either — and no pkg-cache Docker volume bind, since it's using
    # nfs_client (a real Ansible-managed mount) instead.
    assert "extra_binds" not in consumer_host
