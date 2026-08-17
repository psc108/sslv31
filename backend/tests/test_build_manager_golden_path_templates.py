"""Enhancement Plan Stage 7 — golden-path reference templates.

Mirrors the JAR Analyser error-KB's origin column pattern exactly:
BMTemplate.origin ('builtin' | 'user'), an idempotent seed script, and full
CRUD parity between builtin and user templates once seeded (edit/delete
apply equally — only the badge differs). Deleting a builtin is genuine and
permanent, recoverable only by re-running the seed for that name.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.build_manager import container_manager


@pytest.mark.usefixtures("setup_db")
async def test_seed_creates_builtin_templates_with_valid_specs(client):
    resp = await client.post("/api/v1/build/templates/seed")
    assert resp.status_code == 200, resp.text
    assert resp.json()["templates_added"] == 3

    resp = await client.get("/api/v1/build/templates")
    assert resp.status_code == 200
    builtins = [t for t in resp.json() if t["origin"] == "builtin"]
    assert len(builtins) == 3

    full_stack = next(t for t in builtins if "Full Stack" in t["name"])
    assert full_stack["current_spec"]["hosts"]
    roles = {h["role"] for h in full_stack["current_spec"]["hosts"]}
    assert roles == {"pkg-cache", "frontend", "backend", "mysql", "rabbitmq", "keystone", "backend-lb", "frontend-lb"}
    # Every host in the golden-path spec has real, non-empty products, and
    # certs except pkg-cache — no TLS-facing service runs there (it's a
    # plain package cache).
    for host in full_stack["current_spec"]["hosts"]:
        if host["role"] != "pkg-cache":
            assert host["certs"]
        assert host["products"]

    # Idempotent — re-running adds nothing.
    resp = await client.post("/api/v1/build/templates/seed")
    assert resp.json()["templates_added"] == 0


@pytest.mark.usefixtures("setup_db")
async def test_full_stack_exposes_frontend_lb_and_rabbitmq_ports_by_default(client):
    """A real browser on the Docker host needs to reach frontend-lb (443)
    and RabbitMQ's TLS management UI (15671) without any manual per-
    environment step — baked into the golden-path spec itself.
    backend-lb deliberately carries no expose_ports (only ever addressed
    from inside the Docker network by frontend-lb); port 80 is never
    exposed anywhere in this template since it's always owned by the
    ssl-cert-manager container's own -p 80:80 binding."""
    resp = await client.post("/api/v1/build/templates/seed")
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/build/templates")
    full_stack = next(t for t in resp.json() if "Full Stack" in t["name"])
    hosts_by_role = {h["role"]: h for h in full_stack["current_spec"]["hosts"]}

    assert hosts_by_role["frontend-lb"].get("expose_ports") == [443]
    assert hosts_by_role["rabbitmq"].get("expose_ports") == [15671]
    assert "expose_ports" not in hosts_by_role["backend-lb"]
    for host in full_stack["current_spec"]["hosts"]:
        assert 80 not in host.get("expose_ports", [])


@pytest.mark.usefixtures("setup_db")
async def test_full_stack_ansible_timeout_is_60_minutes(client):
    """This 8-host build genuinely needs more than the 30-minute default —
    confirmed by two real, reproducible timeouts before this was raised;
    must stay baked into the seeded spec itself, not just a one-off live
    override, or a fresh seed silently regresses back to 30 minutes."""
    resp = await client.post("/api/v1/build/templates/seed")
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/build/templates")
    full_stack = next(t for t in resp.json() if "Full Stack" in t["name"])
    assert full_stack["current_spec"]["ansible_timeout_minutes"] == 60


@pytest.mark.usefixtures("setup_db")
async def test_full_stack_hosts_install_correct_base_software(client):
    """Cross-checked against Documentation/install-descriptions.md (the real
    on-prem SSP install guide): Frontend needs Python + Node.js + nginx,
    Backend needs Python + nginx (Java is already covered unconditionally by
    every host's base role, so no separate product entry is needed for it),
    MySQL was already correct. Keystone previously listed a non-existent
    "apache" product and RabbitMQ a non-existent "erlang" product (no such
    Ansible roles exist for either — both would crash the build with "role
    not found", caught by an actual live build, not just review) that were
    also redundant: the keystone role already installs Apache + mod_wsgi
    itself, and the rabbitmq role already installs erlang-nox itself.

    Every consumer host (mysql/rabbitmq/keystone/backend/frontend/backend-lb/
    frontend-lb) also carries nfs_client + local_repo ahead of their real
    products, so they mount and read from the pkg-cache host's pre-seeded
    package cache over real NFS — see test_full_stack_pkg_cache_wiring —
    instead of the network. Real NFS, not a Docker-only shared volume, since
    on-prem/AWS hosts won't share a Docker daemon the way these lab
    containers do. backend-lb/frontend-lb are modeled directly on the real
    application's own load-balancer nginx configs (traced via the JAR
    Analyser) — see test_build_manager_nginx_lb.py for the product itself."""
    resp = await client.post("/api/v1/build/templates/seed")
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/build/templates")
    full_stack = next(t for t in resp.json() if "Full Stack" in t["name"])
    products_by_role = {
        h["role"]: {p["product"] for p in h["products"]}
        for h in full_stack["current_spec"]["hosts"]
    }
    assert products_by_role["frontend"] == {"nginx", "python", "nodejs", "nfs_client", "local_repo"}
    assert products_by_role["backend"] == {"python", "uvicorn", "nginx", "nfs_client", "local_repo"}
    assert products_by_role["mysql"] == {"mysql", "nfs_client", "local_repo"}
    assert products_by_role["rabbitmq"] == {"rabbitmq", "nfs_client", "local_repo"}
    assert products_by_role["keystone"] == {"keystone", "nfs_client", "local_repo"}
    assert products_by_role["pkg-cache"] == {"pkg_cache_seed", "nfs_server"}
    assert products_by_role["backend-lb"] == {"nginx_lb", "nfs_client", "local_repo"}
    assert products_by_role["frontend-lb"] == {"nginx_lb", "nfs_client", "local_repo"}


@pytest.mark.usefixtures("setup_db")
async def test_full_stack_pkg_cache_wiring(client):
    """The pkg-cache host must build first (see
    test_full_stack_is_docker_hosted_not_ssh for host-order confirmation),
    run an NFS server, and seed a package cache into the export that the
    other 5 hosts mount with the NFS Client product and read from — real
    NFS, not a Docker volume, deliberately: this lab's hosts all happen to
    share one Docker engine, but real on-prem/AWS hosts won't. Confirm the
    plumbing: pkg_cache_seed writes into the nfs_server's own export path,
    every consumer host's nfs_client mounts that export at /mnt/pkg-cache,
    local_repo_cache_dir points at the same path, and nfs_client + local_repo
    both run before this role's real products (mount, then configure apt,
    then actually install)."""
    resp = await client.post("/api/v1/build/templates/seed")
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/build/templates")
    full_stack = next(t for t in resp.json() if "Full Stack" in t["name"])
    hosts_by_role = {h["role"]: h for h in full_stack["current_spec"]["hosts"]}

    pkg_cache_products = hosts_by_role["pkg-cache"]["products"]
    nfs_server = next(p for p in pkg_cache_products if p["product"] == "nfs_server")
    export_path = nfs_server["vars"]["nfs_exports"][0]["path"]
    assert export_path == "/srv/nfs-export"
    assert "no_root_squash" in nfs_server["vars"]["nfs_exports"][0]["options"]

    seed = next(p for p in pkg_cache_products if p["product"] == "pkg_cache_seed")
    assert seed["vars"]["pkg_cache_seed_packages"], "must actually list packages to cache"
    assert seed["vars"]["pkg_cache_seed_dir"] == f"{export_path}/apt", (
        "pkg_cache_seed must write inside the actual NFS export, not somewhere unexported"
    )
    # nfs_server must come first — it creates/exports the directory that
    # pkg_cache_seed then writes a subdirectory inside.
    assert pkg_cache_products.index(nfs_server) < pkg_cache_products.index(seed)

    for role in ("mysql", "rabbitmq", "keystone", "backend", "frontend", "backend-lb", "frontend-lb"):
        products = hosts_by_role[role]["products"]
        nfs_client = next(p for p in products if p["product"] == "nfs_client")
        local_repo = next(p for p in products if p["product"] == "local_repo")
        mounts = nfs_client["vars"]["nfs_mounts"]
        assert mounts == [{"src": "pkg-cache:/srv/nfs-export", "path": "/mnt/pkg-cache", "opts": "nolock,vers=3"}]
        assert local_repo["vars"]["local_repo_cache_dir"] == "/mnt/pkg-cache"
        # nfs_client must mount before local_repo checks for the cache, and
        # local_repo must come before this role's real products (configure
        # apt to look at the cache before anything tries to install).
        real_products = [p for p in products if p["product"] not in ("nfs_client", "local_repo")]
        assert real_products
        assert products.index(nfs_client) < products.index(local_repo)
        assert all(products.index(local_repo) < products.index(p) for p in real_products)


@pytest.mark.usefixtures("setup_db")
async def test_full_stack_is_docker_hosted_not_ssh(client):
    """The user needs this template to be buildable against Docker
    containers (like the NFS Shared Storage Server template already is),
    not real SSH-reachable machines at auto-allocated IPs that don't exist
    in this environment. allocate_ips() only falls back to using each role
    name directly as its Docker container name when the spec has no
    "network" pool — confirm that fallback actually applies to every host
    here now that the pool has been removed, not just some of them."""
    resp = await client.post("/api/v1/build/templates/seed")
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/build/templates")
    full_stack = next(t for t in resp.json() if "Full Stack" in t["name"])
    template_id = full_stack["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"fullstack-docker-check-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]
    ip_allocations = resp.json()["ip_allocations"]
    assert ip_allocations == {
        "pkg-cache": "pkg-cache",
        "frontend": "frontend", "backend": "backend", "mysql": "mysql",
        "rabbitmq": "rabbitmq", "keystone": "keystone",
        "backend-lb": "backend-lb", "frontend-lb": "frontend-lb",
    }
    # Host order controls serial:1 build order (see site.yml) — pkg-cache
    # must come first so its package cache is ready before anything reads it;
    # backend-lb/frontend-lb come last since they front backend/frontend,
    # which must already exist.
    resp2 = await client.get(f"/api/v1/build/templates/{template_id}")
    assert [h["role"] for h in resp2.json()["current_spec"]["hosts"]] == [
        "pkg-cache", "mysql", "rabbitmq", "keystone", "backend", "frontend",
        "backend-lb", "frontend-lb",
    ]

    # setup_db is session-scoped (shared across every test in this file) —
    # destroy the environment so it doesn't count as "active" against this
    # template for other tests (e.g. the builtin delete test) sharing the DB.
    # Mocked because this throwaway test process has no real Docker socket.
    with patch.object(container_manager, "cleanup_containers_for_environment", new=AsyncMock(return_value=[])):
        resp = await client.post(f"/api/v1/build/environments/{env_id}/destroy")
    assert resp.status_code == 200, resp.text


@pytest.mark.usefixtures("setup_db")
async def test_seeded_templates_pass_spec_validation(client):
    """validate_spec() is what /templates and /templates/{id} (PUT) actually
    enforce — confirm the seeded specs would pass it too, not just that the
    seed script bypasses validation by inserting directly."""
    from app.services.build_manager.template_service import validate_spec, SEED_TEMPLATES

    for tdata in SEED_TEMPLATES:
        errors = validate_spec(tdata["spec"])
        assert errors == [], f"{tdata['name']}: {errors}"


@pytest.mark.usefixtures("setup_db")
async def test_user_created_template_has_user_origin(client):
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"user-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1"}]},
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["origin"] == "user"


@pytest.mark.usefixtures("setup_db")
async def test_builtin_template_is_fully_editable_and_deletable(client):
    """The whole point of Stage 7: builtins are real, DB-managed templates —
    not read-only presets. Edit and delete apply exactly as they do to a
    user template."""
    await client.post("/api/v1/build/templates/seed")
    resp = await client.get("/api/v1/build/templates")
    builtin = next(t for t in resp.json() if t["origin"] == "builtin")
    template_id = builtin["id"]

    # Edit: save a new version, same as any user template.
    resp = await client.put(f"/api/v1/build/templates/{template_id}", json={
        "spec": {**builtin["current_spec"], "network": {"subnet": "10.99.0.0/24"}},
        "change_note": "Customised the network range",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["current_version"] == 2
    assert resp.json()["origin"] == "builtin"  # editing doesn't change origin

    # Delete: genuine, permanent — no automatic revert.
    resp = await client.delete(f"/api/v1/build/templates/{template_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/build/templates/{template_id}")
    assert resp.status_code == 404

    # Recovery is only via re-seeding — confirm the deleted one comes back.
    resp = await client.post("/api/v1/build/templates/seed")
    assert resp.json()["templates_added"] == 1  # only the deleted one is missing now

    resp = await client.get("/api/v1/build/templates")
    assert any(t["origin"] == "builtin" and t["id"] != template_id for t in resp.json())
