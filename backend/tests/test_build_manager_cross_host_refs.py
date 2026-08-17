"""Cross-host reference resolution for Host-Mapped environments.

Every seeded template's nfs_mounts[].src ("<role>:<path>") and
lb_upstreams[].host bake in the literal role name as the hostname to
reach that other host on docker_bm-net — correct only when the
"no network pool" auto-detect convention is used (role name IS the
container name). A real live build broke this: mapping roles to the
pre-existing target-* fixture containers via ip_overrides (Host Mapping
in EnvironmentsPage.tsx) left mysql's nfs_mounts.src still reading the
literal "pkg-cache:/srv/nfs-export" — a hostname nothing on the Docker
network actually answers to (the real container was target-pkg-cache) —
so "Mount NFS shares" failed with "Failed to resolve server pkg-cache".
_resolve_cross_host_refs() rewrites these using ip_allocations (which
already knows every role's actual assigned container name for this one
environment), and is a no-op whenever ip_allocations is the identity
mapping (every environment that doesn't override the default naming).
"""
import uuid

import pytest


def test_resolve_cross_host_refs_rewrites_nfs_mount_src_when_overridden():
    from app.services.build_manager.base_provisioner import _resolve_cross_host_refs

    product_vars = {"nfs_mounts": [
        {"src": "pkg-cache:/srv/nfs-export", "path": "/mnt/pkg-cache", "opts": "nolock,vers=3"},
    ]}
    ip_allocations = {"pkg-cache": "target-pkg-cache", "mysql": "target-mysql"}

    result = _resolve_cross_host_refs(product_vars, ip_allocations)
    assert result["nfs_mounts"][0]["src"] == "target-pkg-cache:/srv/nfs-export"
    assert result["nfs_mounts"][0]["path"] == "/mnt/pkg-cache"


def test_resolve_cross_host_refs_rewrites_lb_upstream_host_when_overridden():
    from app.services.build_manager.base_provisioner import _resolve_cross_host_refs

    product_vars = {"lb_upstreams": [
        {"name": "backend", "path": "/", "host": "backend", "port": 8000},
    ]}
    ip_allocations = {"backend": "target-backend", "backend-lb": "target-backend-lb"}

    result = _resolve_cross_host_refs(product_vars, ip_allocations)
    assert result["lb_upstreams"][0]["host"] == "target-backend"
    assert result["lb_upstreams"][0]["port"] == 8000


def test_resolve_cross_host_refs_is_a_no_op_under_identity_mapping():
    """The default, every-test-this-session convention: ip_allocations maps
    each role to itself. Must produce byte-identical vars — zero behavior
    change for any environment that doesn't override the default naming."""
    from app.services.build_manager.base_provisioner import _resolve_cross_host_refs

    product_vars = {
        "nfs_mounts": [{"src": "pkg-cache:/srv/nfs-export", "path": "/mnt/pkg-cache", "opts": "nolock,vers=3"}],
        "lb_upstreams": [{"name": "backend", "path": "/", "host": "backend", "port": 8000}],
    }
    ip_allocations = {"pkg-cache": "pkg-cache", "backend": "backend"}

    result = _resolve_cross_host_refs(product_vars, ip_allocations)
    assert result == product_vars


def test_resolve_cross_host_refs_leaves_unrelated_vars_untouched():
    from app.services.build_manager.base_provisioner import _resolve_cross_host_refs

    product_vars = {"mysql_root_password": "changeit", "mysql_databases": [{"name": "appdb"}]}
    result = _resolve_cross_host_refs(product_vars, {"mysql": "target-mysql"})
    assert result == product_vars


@pytest.mark.usefixtures("setup_db")
async def test_provision_environment_resolves_nfs_and_lb_refs_for_host_mapped_env(client):
    """Integration proof, via the real API + provision_environment(): an
    environment whose roles are mapped (ip_overrides) to differently-named
    containers gets nfs_mounts.src and lb_upstreams.host rewritten to match,
    not left pointing at hostnames nothing on the network answers to."""
    from app.services.build_manager.base_provisioner import provision_environment

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"cross-host-refs-test-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [
            {"role": "pkg-cache", "products": [], "certs": []},
            {"role": "mysql", "products": [
                {"product": "nfs_client", "version": "4", "vars": {"nfs_mounts": [
                    {"src": "pkg-cache:/srv/nfs-export", "path": "/mnt/pkg-cache", "opts": "nolock,vers=3"},
                ]}},
            ], "certs": []},
            {"role": "backend", "products": [], "certs": []},
            {"role": "backend-lb", "products": [
                {"product": "nginx_lb", "version": "1", "vars": {"lb_upstreams": [
                    {"name": "backend", "path": "/", "host": "backend", "port": 8000},
                ]}},
            ], "certs": ["server_tls"]},
        ]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Cross Host Refs Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"cross-host-refs-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "ip_overrides": {
            "pkg-cache": "target-pkg-cache", "mysql": "target-mysql",
            "backend": "target-backend", "backend-lb": "target-backend-lb",
        },
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    from app.core.database import async_session
    async with async_session() as db:
        provision_data = await provision_environment(db, env_id)

    mysql_nfs_client = next(p for p in provision_data["host_products"]["mysql"] if p["ansible_role"] == "nfs_client")
    assert mysql_nfs_client["vars"]["nfs_mounts"][0]["src"] == "target-pkg-cache:/srv/nfs-export"

    backend_lb_nginx = next(p for p in provision_data["host_products"]["backend-lb"] if p["ansible_role"] == "nginx_lb")
    assert backend_lb_nginx["vars"]["lb_upstreams"][0]["host"] == "target-backend"
