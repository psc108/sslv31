"""Template name uniqueness — clear error instead of an unhandled 500.

BMTemplate.name has a DB-level unique constraint, but create_template()
never checked for a collision before inserting, so saving a template with
an already-used name surfaced as an unhandled IntegrityError rather than a
clean, catchable error — the Template Builder UI's generic "Failed to save
template" fallback fired because the response didn't have the expected
{"detail": "..."} shape. Reported by the user via the Template Builder UI
(saving as "test" failed, "test1" succeeded — a template named "test"
already existed); reproduced and fixed at the service layer so both
POST /templates and POST /catalogue/build-template get the fix.
"""
import uuid

import pytest


@pytest.mark.usefixtures("setup_db")
async def test_create_template_with_duplicate_name_returns_clear_409(client):
    name = f"dup-template-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/templates", json={
        "name": name, "spec": {"hosts": [{"role": "generic1"}]},
    })
    assert resp.status_code == 201, resp.text

    resp = await client.post("/api/v1/build/templates", json={
        "name": name, "spec": {"hosts": [{"role": "generic1"}]},
    })
    assert resp.status_code == 409, resp.text
    assert name in resp.json()["detail"]
    assert "already exists" in resp.json()["detail"]


@pytest.mark.usefixtures("setup_db")
async def test_build_template_from_catalogue_with_duplicate_name_returns_clear_409(client):
    """Same fix, exercised through the Template Builder's actual save
    endpoint — this is the one the user hit."""
    name = f"dup-builder-template-{uuid.uuid4().hex[:8]}"
    payload = {
        "base_os": "ubuntu", "base_os_version": "24.04",
        "hosts": [{"role": "web1", "products": []}],
        "template_name": name,
        "template_description": "", "template_tags": "", "change_note": "test",
    }
    resp = await client.post("/api/v1/build/catalogue/build-template", json=payload)
    assert resp.status_code == 201, resp.text

    resp = await client.post("/api/v1/build/catalogue/build-template", json=payload)
    assert resp.status_code == 409, resp.text
    assert name in resp.json()["detail"]
    assert "already exists" in resp.json()["detail"]


@pytest.mark.usefixtures("setup_db")
async def test_create_template_with_new_name_still_succeeds(client):
    """Regression: the uniqueness check must not block genuinely new names."""
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"unique-template-{uuid.uuid4().hex[:8]}", "spec": {"hosts": [{"role": "generic1"}]},
    })
    assert resp.status_code == 201, resp.text
