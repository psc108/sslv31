"""Enhancement Plan Stage 6 — Operating System Catalogue.

Mirrors the existing Product Catalogue's two-level CRUD pattern
(family + specific version, admin-only mutation, any-authenticated read,
idempotent seed). Replaces three previously-hardcoded sources of truth
(BMTemplateBuilderPage's 4-tile grid, InventoryPage's OS_TYPES array,
HostCreate.os_type's backend regex) with a real, seedable catalogue that
admins can add their own entries to.
"""
import uuid

import pytest


@pytest.mark.usefixtures("setup_db")
async def test_seed_populates_builtin_families(client):
    resp = await client.post("/api/v1/build/os-catalogue/seed")
    assert resp.status_code == 200, resp.text
    assert resp.json()["families_added"] == 7

    resp = await client.get("/api/v1/build/os-catalogue")
    assert resp.status_code == 200
    names = {f["name"] for f in resp.json()}
    assert names == {"ubuntu", "debian", "rhel", "centos", "almalinux", "rocky", "alpine"}
    ubuntu = next(f for f in resp.json() if f["name"] == "ubuntu")
    assert ubuntu["origin"] == "builtin"
    assert {v["version"] for v in ubuntu["versions"]} == {"24.04", "22.04"}

    # Idempotent — re-running adds nothing.
    resp = await client.post("/api/v1/build/os-catalogue/seed")
    assert resp.json()["families_added"] == 0


@pytest.mark.usefixtures("setup_db")
async def test_create_update_delete_os_family(client):
    name = f"testos-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/os-catalogue", json={
        "name": name, "display_name": "Test OS", "icon": "🧪",
    })
    assert resp.status_code == 201, resp.text
    family_id = resp.json()["id"]
    assert resp.json()["origin"] == "user"
    assert resp.json()["versions"] == []

    resp = await client.post("/api/v1/build/os-catalogue", json={
        "name": name, "display_name": "Duplicate", "icon": "🧪",
    })
    assert resp.status_code == 409

    resp = await client.put(f"/api/v1/build/os-catalogue/{family_id}", json={"display_name": "Renamed OS"})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Renamed OS"

    resp = await client.delete(f"/api/v1/build/os-catalogue/{family_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/build/os-catalogue/{family_id}")
    assert resp.status_code == 404


@pytest.mark.usefixtures("setup_db")
async def test_add_update_delete_os_version(client):
    name = f"testos2-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/os-catalogue", json={"name": name, "display_name": "Test OS 2"})
    family_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/build/os-catalogue/{family_id}/versions", json={
        "version": "1.0", "display_name": "1.0", "is_latest": True,
    })
    assert resp.status_code == 201, resp.text
    v1_id = resp.json()["id"]
    assert resp.json()["is_latest"] is True

    resp = await client.post(f"/api/v1/build/os-catalogue/{family_id}/versions", json={
        "version": "2.0", "display_name": "2.0", "is_latest": True,
    })
    v2_id = resp.json()["id"]

    # Adding a new is_latest version unmarks the previous one.
    resp = await client.get(f"/api/v1/build/os-catalogue/{family_id}")
    versions = {v["id"]: v["is_latest"] for v in resp.json()["versions"]}
    assert versions[v1_id] is False
    assert versions[v2_id] is True

    resp = await client.put(f"/api/v1/build/os-catalogue/versions/{v1_id}", json={"eol_date": "2020-01-01"})
    assert resp.status_code == 200
    assert resp.json()["eol_date"] == "2020-01-01"

    resp = await client.delete(f"/api/v1/build/os-catalogue/versions/{v1_id}")
    assert resp.status_code == 204


@pytest.mark.usefixtures("setup_db")
async def test_cannot_delete_family_referenced_by_host(client):
    name = f"testos3-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/os-catalogue", json={"name": name, "display_name": "Test OS 3"})
    family_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": f"os-in-use-host-{uuid.uuid4().hex[:8]}", "ip": "10.0.0.1",
        "connection_type": "ssh", "os_type": name,
    })
    assert resp.status_code == 201, resp.text
    host_id = resp.json()["id"]

    resp = await client.delete(f"/api/v1/build/os-catalogue/{family_id}")
    assert resp.status_code == 409

    await client.delete(f"/api/v1/build/hosts/{host_id}")

    resp = await client.delete(f"/api/v1/build/os-catalogue/{family_id}")
    assert resp.status_code == 204  # no longer in use, deletion succeeds


@pytest.mark.usefixtures("setup_db")
async def test_cannot_delete_version_referenced_by_template(client):
    name = f"testos4-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/os-catalogue", json={"name": name, "display_name": "Test OS 4"})
    family_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/build/os-catalogue/{family_id}/versions", json={
        "version": "9.9", "display_name": "9.9",
    })
    version_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"os-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1"}], "base_os": name, "base_os_version": "9.9"},
    })
    assert resp.status_code == 201, resp.text

    resp = await client.delete(f"/api/v1/build/os-catalogue/versions/{version_id}")
    assert resp.status_code == 409

    # But the family-level delete is also blocked, since the version is referenced.
    resp = await client.delete(f"/api/v1/build/os-catalogue/{family_id}")
    assert resp.status_code == 409


@pytest.mark.usefixtures("setup_db")
async def test_create_host_accepts_arbitrary_os_type_not_in_hardcoded_list(client):
    """The whole point of Stage 6: HostCreate.os_type is no longer a fixed
    enum, so admins can use an OS family the backend didn't ship with."""
    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": f"custom-os-host-{uuid.uuid4().hex[:8]}", "ip": "10.0.0.2",
        "connection_type": "ssh", "os_type": "arch-linux",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["os_type"] == "arch-linux"
