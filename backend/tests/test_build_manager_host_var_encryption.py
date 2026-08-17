"""Stage 4 of the Build Manager hardening plan — BMHostVar.encrypted was a
display-only label; ticking it never actually encrypted the value at rest.
These tests confirm it now genuinely does, using the same Fernet key as
secrets_service.py's own BMSecret encryption.
"""
import logging

import pytest

from app.services.build_manager.secrets_service import encrypt_value, decrypt_value


def test_encrypt_decrypt_round_trip():
    ciphertext = encrypt_value("super-secret-value")
    assert ciphertext != "super-secret-value"
    assert decrypt_value(ciphertext) == "super-secret-value"


@pytest.mark.usefixtures("setup_db")
async def test_list_secrets_shows_masked_preview_not_full_value(client):
    """Stage 4, item 6.3 — mask_value() was defined but never called anywhere.
    list_secrets() now uses it for a masked preview, never the real value."""
    resp = await client.post("/api/v1/build/secrets", json={"name": "db-root-pw", "value": "correcthorsebatterystaple"})
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/build/secrets")
    assert resp.status_code == 200
    entry = next(s for s in resp.json() if s["name"] == "db-root-pw")
    assert "value" not in entry
    assert entry["masked_value"] != "correcthorsebatterystaple"
    assert entry["masked_value"].startswith("co")
    assert entry["masked_value"].endswith("le")


async def _create_host(client) -> str:
    resp = await client.post("/api/v1/build/hosts", json={
        "hostname": "encvar-test-host", "ip": "10.0.0.55", "connection_type": "ssh",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.usefixtures("setup_db")
async def test_encrypted_host_var_is_ciphertext_at_rest(client):
    from app.core.database import async_session
    from app.models.build_manager import BMHostVar
    from sqlalchemy import select

    host_id = await _create_host(client)
    resp = await client.post(f"/api/v1/build/hosts/{host_id}/vars", json={
        "key": "db_password", "value": "hunter2", "encrypted": True,
    })
    assert resp.status_code == 201
    assert resp.json()["value"] == "***"  # never echoed back in the write response

    async with async_session() as session:
        row = (await session.execute(
            select(BMHostVar).where(BMHostVar.host_id == host_id, BMHostVar.key == "db_password")
        )).scalar_one()
        assert row.value != "hunter2"
        assert decrypt_value(row.value) == "hunter2"


@pytest.mark.usefixtures("setup_db")
async def test_unencrypted_host_var_stored_as_plaintext(client):
    from app.core.database import async_session
    from app.models.build_manager import BMHostVar
    from sqlalchemy import select

    host_id = await _create_host(client)
    await client.post(f"/api/v1/build/hosts/{host_id}/vars", json={
        "key": "region", "value": "eu-west-1", "encrypted": False,
    })

    async with async_session() as session:
        row = (await session.execute(
            select(BMHostVar).where(BMHostVar.host_id == host_id, BMHostVar.key == "region")
        )).scalar_one()
        assert row.value == "eu-west-1"


@pytest.mark.usefixtures("setup_db")
async def test_reveal_host_var_decrypts_correctly(client):
    host_id = await _create_host(client)
    await client.post(f"/api/v1/build/hosts/{host_id}/vars", json={
        "key": "api_token", "value": "tok-abc123", "encrypted": True,
    })

    resp = await client.get(f"/api/v1/build/hosts/{host_id}/vars/api_token/reveal")
    assert resp.status_code == 200
    assert resp.json()["value"] == "tok-abc123"


@pytest.mark.usefixtures("setup_db")
async def test_reveal_host_var_requires_admin_not_operator():
    from app.api.v1.build_manager import router

    for r in router.routes:
        if r.path == "/api/v1/build/hosts/{host_id}/vars/{var_key}/reveal" and "GET" in r.methods:
            for dep in r.dependant.dependencies:
                fn = dep.call
                freevars = getattr(fn.__code__, "co_freevars", ())
                if "allowed_roles" in freevars:
                    idx = freevars.index("allowed_roles")
                    assert fn.__closure__[idx].cell_contents == ("admin",)
                    return
    pytest.fail("reveal route or its role dependency not found")


@pytest.mark.usefixtures("setup_db")
async def test_reveal_handles_legacy_plaintext_gracefully(client, caplog):
    """A row from before this fix could have encrypted=True with a plaintext
    value already stored — must not crash, just fall back with a warning."""
    from app.core.database import async_session
    from app.models.build_manager import BMHostVar
    import uuid

    host_id = await _create_host(client)
    async with async_session() as session:
        session.add(BMHostVar(id=str(uuid.uuid4()), host_id=host_id, key="legacy", value="plaintext-legacy", encrypted=True))
        await session.commit()

    with caplog.at_level(logging.WARNING):
        resp = await client.get(f"/api/v1/build/hosts/{host_id}/vars/legacy/reveal")

    assert resp.status_code == 200
    assert resp.json()["value"] == "plaintext-legacy"
    assert any("legacy plaintext" in r.message for r in caplog.records)
