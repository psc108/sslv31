"""Docs & Bug Tracker Improvements Plan — Stage 10: automated integration
coverage for the core CRUD/RBAC/tenant-isolation paths in docs.py.

Every stage before this one was verified by hand against a live container —
thorough, but nothing regression-proof. This file (and its bug_tracker.py
sibling) exercise the same shapes of behaviour those manual walkthroughs
already proved out, so future stages touching this code have something to
run besides another curl session.
"""
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def make_tenant_key(setup_db):
    """Factory: create a real Tenant row + a non-global-admin ScopedAPIKey
    bound to it, returning (tenant_id, headers). The legacy master API key
    (used by the `client` fixture by default) is always is_global_admin=True
    and bypasses every tenant_id filter in docs.py/bug_tracker.py outright —
    a scoped key is the only way to exercise the actual tenant-isolation
    code path (`if not auth.is_global_admin: query = query.where(...)`)."""
    from app.core.database import async_session
    from app.models.tenant import Tenant
    from app.models.api_key import ScopedAPIKey
    from app.services.auth import hash_api_key, generate_api_key

    async def _make(role: str = "admin") -> tuple[str, dict[str, str]]:
        tenant_id = str(uuid.uuid4())
        raw_key = generate_api_key()
        async with async_session() as db:
            db.add(Tenant(id=tenant_id, name=f"Test Tenant {tenant_id[:8]}", slug=f"test-{tenant_id[:8]}"))
            db.add(ScopedAPIKey(
                name=f"test-{role}-{tenant_id[:8]}", key_hash=hash_api_key(raw_key),
                key_prefix=raw_key[:8], role=role, created_by="test", tenant_id=tenant_id,
            ))
            await db.commit()
        return tenant_id, {"X-API-Key": raw_key}

    return _make


async def _make_library_shelf(client, headers=None) -> tuple[str, str]:
    lib = await client.post("/api/v1/docs/libraries", json={"name": f"Lib {uuid.uuid4().hex[:8]}"}, headers=headers)
    assert lib.status_code == 201, lib.text
    library_id = lib.json()["id"]
    shelf = await client.post(
        "/api/v1/docs/shelves", json={"library_id": library_id, "name": f"Shelf {uuid.uuid4().hex[:8]}"}, headers=headers,
    )
    assert shelf.status_code == 201, shelf.text
    return library_id, shelf.json()["id"]


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------

async def test_create_library_shelf_doc_flow(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    library_id, shelf_id = await _make_library_shelf(client, headers)

    doc = await client.post(
        "/api/v1/docs", json={"shelf_id": shelf_id, "name": "Doc A", "content": "hello world"}, headers=headers,
    )
    assert doc.status_code == 201, doc.text
    body = doc.json()
    assert body["name"] == "Doc A"
    assert body["version"] == 1
    assert body["content"] == "hello world"

    listed = await client.get(f"/api/v1/docs/shelves/{shelf_id}/docs", headers=headers)
    assert listed.status_code == 200
    assert [d["name"] for d in listed.json()] == ["Doc A"]

    fetched = await client.get(f"/api/v1/docs/{body['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "hello world"


async def test_duplicate_doc_name_on_same_shelf_conflicts(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    _, shelf_id = await _make_library_shelf(client, headers)
    payload = {"shelf_id": shelf_id, "name": "Dup", "content": "v1"}
    first = await client.post("/api/v1/docs", json=payload, headers=headers)
    assert first.status_code == 201
    second = await client.post("/api/v1/docs", json=payload, headers=headers)
    assert second.status_code == 409


async def test_get_nonexistent_doc_404(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    resp = await client.get(f"/api/v1/docs/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


async def test_save_doc_version_increments_and_preserves_old(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    _, shelf_id = await _make_library_shelf(client, headers)
    v1 = (await client.post(
        "/api/v1/docs", json={"shelf_id": shelf_id, "name": "Versioned", "content": "one"}, headers=headers,
    )).json()

    v2_resp = await client.post(f"/api/v1/docs/{v1['id']}/save", json={"content": "two"}, headers=headers)
    assert v2_resp.status_code == 201
    v2 = v2_resp.json()
    assert v2["version"] == 2
    assert v2["content"] == "two"
    assert v2["id"] != v1["id"]

    # The old version row is untouched, still independently fetchable by id.
    old = await client.get(f"/api/v1/docs/{v1['id']}", headers=headers)
    assert old.status_code == 200
    assert old.json()["content"] == "one"
    assert old.json()["version"] == 1

    # But the shelf listing (latest-version-per-name) now shows v2's content only.
    listed = await client.get(f"/api/v1/docs/shelves/{shelf_id}/docs", headers=headers)
    assert len(listed.json()) == 1
    assert listed.json()[0]["version"] == 2


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

async def test_readonly_role_cannot_create_library(client, make_tenant_key):
    _, headers = await make_tenant_key("readonly")
    resp = await client.post("/api/v1/docs/libraries", json={"name": "Nope"}, headers=headers)
    assert resp.status_code == 403


async def test_readonly_role_can_read(client, make_tenant_key):
    _, admin_headers = await make_tenant_key("admin")
    library_id, _ = await _make_library_shelf(client, admin_headers)
    # readonly is a *different* scoped key/tenant here deliberately — this
    # test only cares that the role itself isn't blocked from GET, tenant
    # isolation is covered separately below.
    _, ro_headers = await make_tenant_key("readonly")
    resp = await client.get("/api/v1/docs/libraries", headers=ro_headers)
    assert resp.status_code == 200


async def test_operator_can_create_but_not_delete(client, make_tenant_key):
    _, headers = await make_tenant_key("operator")
    library_id, _ = await _make_library_shelf(client, headers)
    resp = await client.delete(f"/api/v1/docs/libraries/{library_id}", headers=headers)
    assert resp.status_code == 403


async def test_admin_can_delete_library(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    library_id, _ = await _make_library_shelf(client, headers)
    resp = await client.delete(f"/api/v1/docs/libraries/{library_id}", headers=headers)
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_doc_created_in_one_tenant_invisible_to_another(client, make_tenant_key):
    _, tenant_a = await make_tenant_key("admin")
    _, tenant_b = await make_tenant_key("admin")

    _, shelf_id = await _make_library_shelf(client, tenant_a)
    doc = (await client.post(
        "/api/v1/docs", json={"shelf_id": shelf_id, "name": "Secret", "content": "a-only"}, headers=tenant_a,
    )).json()

    # Tenant B can't fetch it directly...
    resp = await client.get(f"/api/v1/docs/{doc['id']}", headers=tenant_b)
    assert resp.status_code == 404

    # ...and can't even resolve the parent shelf to list under it.
    listed = await client.get(f"/api/v1/docs/shelves/{shelf_id}/docs", headers=tenant_b)
    assert listed.status_code == 404

    # Tenant A can still see its own data.
    own = await client.get(f"/api/v1/docs/{doc['id']}", headers=tenant_a)
    assert own.status_code == 200


async def test_library_list_scoped_per_tenant(client, make_tenant_key):
    _, tenant_a = await make_tenant_key("admin")
    _, tenant_b = await make_tenant_key("admin")

    await client.post("/api/v1/docs/libraries", json={"name": "A-only lib"}, headers=tenant_a)
    await client.post("/api/v1/docs/libraries", json={"name": "B-only lib"}, headers=tenant_b)

    a_names = {l["name"] for l in (await client.get("/api/v1/docs/libraries", headers=tenant_a)).json()}
    b_names = {l["name"] for l in (await client.get("/api/v1/docs/libraries", headers=tenant_b)).json()}

    assert "A-only lib" in a_names and "B-only lib" not in a_names
    assert "B-only lib" in b_names and "A-only lib" not in b_names


# ---------------------------------------------------------------------------
# Soft-delete / trash / restore (Stage 7 regression coverage)
# ---------------------------------------------------------------------------

async def test_delete_trash_restore_roundtrip(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    _, shelf_id = await _make_library_shelf(client, headers)
    doc = (await client.post(
        "/api/v1/docs", json={"shelf_id": shelf_id, "name": "Recoverable", "content": "x"}, headers=headers,
    )).json()

    delete_resp = await client.delete(f"/api/v1/docs/{doc['id']}", headers=headers)
    assert delete_resp.status_code == 204

    # Excluded from normal read/list.
    assert (await client.get(f"/api/v1/docs/{doc['id']}", headers=headers)).status_code == 404
    listed = await client.get(f"/api/v1/docs/shelves/{shelf_id}/docs", headers=headers)
    assert listed.json() == []

    # Present in Trash.
    trash = await client.get("/api/v1/docs/trash", headers=headers)
    assert any(t["id"] == doc["id"] for t in trash.json())

    # Restore brings it back.
    restore_resp = await client.post(f"/api/v1/docs/{doc['id']}/restore", headers=headers)
    assert restore_resp.status_code == 200
    assert (await client.get(f"/api/v1/docs/{doc['id']}", headers=headers)).status_code == 200


async def test_create_blocked_while_same_name_in_trash(client, make_tenant_key):
    """Regression test for the exact bug Stage 7 caught live: the DB's
    UNIQUE(shelf_id, name, version) constraint has no knowledge of
    deleted_at, so reusing a name while its old version is still sitting in
    Trash must be blocked with a clear 409 rather than crashing on insert."""
    _, headers = await make_tenant_key("admin")
    _, shelf_id = await _make_library_shelf(client, headers)
    payload = {"shelf_id": shelf_id, "name": "Reused", "content": "first"}
    first = (await client.post("/api/v1/docs", json=payload, headers=headers)).json()
    await client.delete(f"/api/v1/docs/{first['id']}", headers=headers)

    blocked = await client.post("/api/v1/docs", json=payload, headers=headers)
    assert blocked.status_code == 409
    assert "trash" in blocked.json()["detail"].lower()

    # Purging frees the name up again.
    purge = await client.delete(f"/api/v1/docs/trash/{first['id']}", headers=headers)
    assert purge.status_code == 204
    freed = await client.post("/api/v1/docs", json=payload, headers=headers)
    assert freed.status_code == 201
