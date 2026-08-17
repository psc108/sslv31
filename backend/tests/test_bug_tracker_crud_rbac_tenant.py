"""Docs & Bug Tracker Improvements Plan — Stage 10: automated integration
coverage for the core CRUD/RBAC/tenant-isolation paths in bug_tracker.py.
See test_docs_crud_rbac_tenant.py's module docstring for the rationale.
"""
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def make_tenant_key(setup_db):
    """Factory: create a real Tenant row + a non-global-admin ScopedAPIKey
    bound to it, returning (tenant_id, headers). Duplicated from
    test_docs_crud_rbac_tenant.py rather than shared — each test file in
    this suite is self-contained, matching the existing convention."""
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


async def _make_bug(client, headers, **overrides) -> dict:
    payload = {"title": f"Bug {uuid.uuid4().hex[:8]}", "description": "desc"}
    payload.update(overrides)
    resp = await client.post("/api/v1/bugs", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------

async def test_create_and_fetch_bug(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    bug = await _make_bug(client, headers, title="Widget crashes on save", severity="high")
    assert bug["status"] == "open"
    assert bug["severity"] == "high"

    fetched = await client.get(f"/api/v1/bugs/{bug['id']}", headers=headers)
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["title"] == "Widget crashes on save"
    assert body["history"] and body["history"][0]["action"] == "created"


async def test_get_nonexistent_bug_404(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    resp = await client.get(f"/api/v1/bugs/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


async def test_list_bugs_returns_created_bug(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    bug = await _make_bug(client, headers)
    listed = await client.get("/api/v1/bugs", headers=headers)
    assert listed.status_code == 200
    ids = [b["id"] for b in listed.json()["items"]]
    assert bug["id"] in ids


async def test_create_bug_with_unknown_assignee_404s(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    resp = await client.post(
        "/api/v1/bugs", json={"title": "x", "assignee_id": str(uuid.uuid4())}, headers=headers,
    )
    assert resp.status_code == 404


async def test_status_update_records_history_entry(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    bug = await _make_bug(client, headers)

    resp = await client.patch(
        f"/api/v1/bugs/{bug['id']}/status", json={"status": "investigating", "note": "looking into it"}, headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "investigating"

    detail = (await client.get(f"/api/v1/bugs/{bug['id']}", headers=headers)).json()
    statuses = [h["to_status"] for h in detail["history"]]
    assert statuses == ["open", "investigating"]


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

async def test_readonly_role_cannot_create_bug(client, make_tenant_key):
    _, headers = await make_tenant_key("readonly")
    resp = await client.post("/api/v1/bugs", json={"title": "nope"}, headers=headers)
    assert resp.status_code == 403


async def test_readonly_role_can_list(client, make_tenant_key):
    _, headers = await make_tenant_key("readonly")
    resp = await client.get("/api/v1/bugs", headers=headers)
    assert resp.status_code == 200


async def test_operator_can_create_but_not_delete(client, make_tenant_key):
    _, headers = await make_tenant_key("operator")
    bug = await _make_bug(client, headers)
    resp = await client.delete(f"/api/v1/bugs/{bug['id']}", headers=headers)
    assert resp.status_code == 403


async def test_admin_can_delete_bug(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    bug = await _make_bug(client, headers)
    resp = await client.delete(f"/api/v1/bugs/{bug['id']}", headers=headers)
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_bug_created_in_one_tenant_invisible_to_another(client, make_tenant_key):
    _, tenant_a = await make_tenant_key("admin")
    _, tenant_b = await make_tenant_key("admin")

    bug = await _make_bug(client, tenant_a, title="Tenant A's private bug")

    assert (await client.get(f"/api/v1/bugs/{bug['id']}", headers=tenant_b)).status_code == 404

    b_ids = [b["id"] for b in (await client.get("/api/v1/bugs", headers=tenant_b)).json()["items"]]
    assert bug["id"] not in b_ids

    a_ids = [b["id"] for b in (await client.get("/api/v1/bugs", headers=tenant_a)).json()["items"]]
    assert bug["id"] in a_ids


# ---------------------------------------------------------------------------
# Soft-delete / trash / restore
# ---------------------------------------------------------------------------

async def test_delete_trash_restore_roundtrip(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    bug = await _make_bug(client, headers)

    assert (await client.delete(f"/api/v1/bugs/{bug['id']}", headers=headers)).status_code == 204
    assert (await client.get(f"/api/v1/bugs/{bug['id']}", headers=headers)).status_code == 404

    trash = await client.get("/api/v1/bugs/trash", headers=headers)
    assert any(t["id"] == bug["id"] for t in trash.json())

    restore = await client.post(f"/api/v1/bugs/{bug['id']}/restore", headers=headers)
    assert restore.status_code == 200
    assert (await client.get(f"/api/v1/bugs/{bug['id']}", headers=headers)).status_code == 200


# ---------------------------------------------------------------------------
# Bulk actions (Stage 9 regression coverage — partial success, not
# all-or-nothing)
# ---------------------------------------------------------------------------

async def test_bulk_status_update_partial_success(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    bug1 = await _make_bug(client, headers)
    bug2 = await _make_bug(client, headers)
    untouched = await _make_bug(client, headers)
    fake_id = str(uuid.uuid4())

    resp = await client.post(
        "/api/v1/bugs/bulk/status",
        json={"bug_ids": [bug1["id"], bug2["id"], fake_id], "status": "closed"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body["updated"]) == sorted([bug1["id"], bug2["id"]])
    assert body["not_found"] == [fake_id]

    assert (await client.get(f"/api/v1/bugs/{bug1['id']}", headers=headers)).json()["status"] == "closed"
    assert (await client.get(f"/api/v1/bugs/{untouched['id']}", headers=headers)).json()["status"] == "open"


async def test_bulk_tag_add_and_remove(client, make_tenant_key):
    _, headers = await make_tenant_key("admin")
    bug = await _make_bug(client, headers, tags=["existing"])

    add_resp = await client.post(
        "/api/v1/bugs/bulk/tag", json={"bug_ids": [bug["id"]], "tag": "new-tag", "action": "add"}, headers=headers,
    )
    assert add_resp.status_code == 200
    tags_after_add = (await client.get(f"/api/v1/bugs/{bug['id']}", headers=headers)).json()["tags"]
    assert set(tags_after_add) == {"existing", "new-tag"}

    remove_resp = await client.post(
        "/api/v1/bugs/bulk/tag", json={"bug_ids": [bug["id"]], "tag": "existing", "action": "remove"}, headers=headers,
    )
    assert remove_resp.status_code == 200
    tags_after_remove = (await client.get(f"/api/v1/bugs/{bug['id']}", headers=headers)).json()["tags"]
    assert tags_after_remove == ["new-tag"]
