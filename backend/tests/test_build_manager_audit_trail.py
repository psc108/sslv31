"""Enhancement Plan Stage 1 — audit trail for Build Manager actions.

Build Manager mutations (host/group/template/environment/secret/catalogue/
config-file CRUD) never called the app's existing hash-chained audit_event()
before, despite CA/cert operations already doing so. These tests confirm a
representative sample of state-changing endpoints now write an AuditEvent row
with the right event_type/subject_type/severity, and — the one hard rule from
this stage's decision point — that secret material never appears in the
audit `detail` JSON, even when the endpoint's own response would show it.
"""
import json
import uuid

import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent


async def _latest_event(db, event_type: str) -> AuditEvent:
    result = await db.execute(
        select(AuditEvent).where(AuditEvent.event_type == event_type).order_by(AuditEvent.id.desc())
    )
    event = result.scalars().first()
    assert event is not None, f"No audit event of type {event_type} found"
    return event


@pytest.mark.usefixtures("setup_db")
async def test_create_host_writes_info_audit_event(client):
    from app.core.database import async_session

    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": f"audit-host-{uuid.uuid4().hex[:8]}", "ip": "10.1.1.1", "connection_type": "ssh",
    })
    assert resp.status_code == 201, resp.text
    host_id = resp.json()["id"]

    async with async_session() as db:
        event = await _latest_event(db, "BM_HOST_CREATED")
        assert event.severity == "INFO"
        assert event.subject_type == "bm_host"
        assert event.subject_id == host_id


@pytest.mark.usefixtures("setup_db")
async def test_delete_host_writes_warning_audit_event(client):
    from app.core.database import async_session

    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": f"audit-host-del-{uuid.uuid4().hex[:8]}", "ip": "10.1.1.2", "connection_type": "ssh",
    })
    host_id = resp.json()["id"]

    resp = await client.delete(f"/api/v1/build/hosts/{host_id}")
    assert resp.status_code == 204

    async with async_session() as db:
        event = await _latest_event(db, "BM_HOST_DELETED")
        assert event.severity == "WARNING"
        assert event.subject_id == host_id


@pytest.mark.usefixtures("setup_db")
async def test_set_host_var_audit_never_contains_value(client):
    from app.core.database import async_session

    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": f"audit-hostvar-{uuid.uuid4().hex[:8]}", "ip": "10.1.1.3", "connection_type": "ssh",
    })
    host_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/build/hosts/{host_id}/vars", json={
        "key": "db_password", "value": "super-secret-plaintext-value", "encrypted": True,
    })
    assert resp.status_code == 201

    async with async_session() as db:
        event = await _latest_event(db, "BM_HOST_VAR_SET")
        assert event.subject_type == "bm_host_var"
        detail = json.loads(event.detail_json)
        assert detail == {"host_id": host_id, "key": "db_password", "encrypted": True}
        assert "super-secret-plaintext-value" not in event.detail_json
        assert "super-secret-plaintext-value" not in (event.description or "")


@pytest.mark.usefixtures("setup_db")
async def test_create_group_writes_audit_event(client):
    from app.core.database import async_session

    name = f"audit-group-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/groups", json={"name": name, "description": ""})
    assert resp.status_code == 201, resp.text
    group_id = resp.json()["id"]

    async with async_session() as db:
        event = await _latest_event(db, "BM_HOST_GROUP_CREATED")
        assert event.subject_id == group_id
        assert json.loads(event.detail_json)["name"] == name


@pytest.mark.usefixtures("setup_db")
async def test_create_network_pool_writes_audit_event(client):
    from app.core.database import async_session

    name = f"audit-pool-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/network-pools", json={
        "name": name, "cidr": "10.50.0.0/24", "gateway": "10.50.0.1",
    })
    assert resp.status_code == 201, resp.text
    pool_id = resp.json()["id"]

    async with async_session() as db:
        event = await _latest_event(db, "BM_NETWORK_POOL_CREATED")
        assert event.subject_id == pool_id


@pytest.mark.usefixtures("setup_db")
async def test_create_and_update_template_write_audit_events(client):
    from app.core.database import async_session

    name = f"audit-template-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/templates", json={
        "name": name, "spec": {"hosts": [{"role": "generic1"}]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    async with async_session() as db:
        event = await _latest_event(db, "BM_TEMPLATE_CREATED")
        assert event.subject_id == template_id

    resp = await client.put(f"/api/v1/build/templates/{template_id}", json={
        "spec": {"hosts": [{"role": "generic1"}, {"role": "generic2"}]},
        "change_note": "add a second host",
    })
    assert resp.status_code == 200, resp.text

    async with async_session() as db:
        event = await _latest_event(db, "BM_TEMPLATE_UPDATED")
        assert event.subject_id == template_id
        assert json.loads(event.detail_json)["new_version"] == 2


@pytest.mark.usefixtures("setup_db")
async def test_create_product_writes_audit_event(client):
    from app.core.database import async_session

    name = f"audit-product-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/catalogue", json={
        "name": name, "display_name": name.title(), "category": "other",
    })
    assert resp.status_code == 201, resp.text
    product_id = resp.json()["id"]

    async with async_session() as db:
        event = await _latest_event(db, "BM_PRODUCT_CREATED")
        assert event.subject_id == product_id


@pytest.mark.usefixtures("setup_db")
async def test_secret_lifecycle_audit_never_contains_value(client):
    from app.core.database import async_session

    name = f"audit-secret-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/secrets", json={"name": name, "value": "hunter2-plaintext"})
    assert resp.status_code == 200, resp.text
    secret_id = resp.json()["id"]

    async with async_session() as db:
        event = await _latest_event(db, "BM_SECRET_CREATED")
        assert event.severity == "INFO"
        assert event.subject_id == secret_id
        assert "hunter2-plaintext" not in event.detail_json
        assert "hunter2-plaintext" not in (event.description or "")

    resp = await client.post(f"/api/v1/build/secrets/{secret_id}/rotate", json={
        "name": name, "value": "new-plaintext-value",
    })
    assert resp.status_code == 200, resp.text

    async with async_session() as db:
        event = await _latest_event(db, "BM_SECRET_ROTATED")
        assert event.severity == "WARNING"
        assert event.subject_id == secret_id
        assert "new-plaintext-value" not in event.detail_json
        assert "new-plaintext-value" not in (event.description or "")

    resp = await client.delete(f"/api/v1/build/secrets/{secret_id}")
    assert resp.status_code == 200

    async with async_session() as db:
        event = await _latest_event(db, "BM_SECRET_DELETED")
        assert event.severity == "WARNING"
        assert event.subject_id == secret_id
        assert json.loads(event.detail_json)["name"] == name


@pytest.mark.usefixtures("setup_db")
async def test_environment_lifecycle_writes_audit_events(client):
    from app.core.database import async_session

    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Audit Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    assert resp.status_code == 201, resp.text
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"audit-env-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1"}]},
    })
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"audit-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "ip_overrides": {"generic1": "10.99.88.77"},
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    async with async_session() as db:
        event = await _latest_event(db, "BM_ENVIRONMENT_CREATED")
        assert event.subject_id == env_id

    resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    async with async_session() as db:
        event = await _latest_event(db, "BM_ENVIRONMENT_BUILD_TRIGGERED")
        assert event.subject_id == env_id

    await client.post(f"/api/v1/build/jobs/{job_id}/cancel")

    resp = await client.post(f"/api/v1/build/environments/{env_id}/destroy")
    assert resp.status_code == 200, resp.text

    async with async_session() as db:
        event = await _latest_event(db, "BM_ENVIRONMENT_DESTROYED")
        assert event.severity == "WARNING"
        assert event.subject_id == env_id


@pytest.mark.usefixtures("setup_db")
async def test_config_file_save_writes_warning_audit_event(tmp_path, client):
    from app.core.database import async_session
    from app.models.build_manager import BMConfigFile

    target = tmp_path / "audit-test-config.yml"
    target.write_text("key: original\n")

    async with async_session() as db:
        cf = BMConfigFile(
            id=str(uuid.uuid4()), path=str(target), display_name="audit-test-config.yml",
            category="other", format="yaml", purpose="audit test fixture", editable=True,
        )
        db.add(cf)
        await db.commit()
        file_id = cf.id

    resp = await client.put(f"/api/v1/build/editor/files/{file_id}", json={"content": "key: updated\n"})
    assert resp.status_code == 200, resp.text

    async with async_session() as db:
        event = await _latest_event(db, "BM_CONFIG_FILE_SAVED")
        assert event.severity == "WARNING"
        assert event.subject_id == file_id
        assert json.loads(event.detail_json)["path"] == str(target)
