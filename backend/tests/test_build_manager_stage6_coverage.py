"""Stage 6 of the Build Manager hardening plan — test coverage baseline.

Zero test files existed for this ~8,000-line module's core, unglamorous logic
before Stages 1-5 (each of which added its own narrow regression test for the
specific bug it fixed). This file closes the broader gap called out in the
plan: catalogue compatibility checking, the secrets encrypt/rotate round-trip,
config editor save/validate/restore, and a smoke test of the real
build -> destroy environment lifecycle (real Docker-free provisioning: cert
issuance + job creation + cert-binding revocation, not mocked).
"""
import uuid

import pytest

from app.services.build_manager.catalogue_service import _version_gte, check_compatibility
from app.services.build_manager.secrets_service import (
    create_secret, get_secret, update_secret, rotate_secret, delete_secret, decrypt_value,
)


# --- catalogue_service.py: _version_gte ---

@pytest.mark.parametrize("actual,minimum,expected", [
    ("24.04", "22.04", True),
    ("22.04", "24.04", False),
    ("24.04", "24.04", True),
    ("9", "8", True),
    ("8", "9", False),
])
def test_version_gte_numeric_dotted(actual, minimum, expected):
    assert _version_gte(actual, minimum) is expected


def test_version_gte_falls_back_to_string_compare_on_non_numeric():
    # Non-numeric parts (e.g. Debian codenames) can't be int()-parsed — falls
    # back to a plain string comparison rather than raising.
    assert _version_gte("buster", "buster") is True
    assert _version_gte("bullseye", "buster") is False  # 'l' < 's' lexicographically
    assert _version_gte("buster", "bullseye") is True


# --- catalogue_service.py: check_compatibility ---

@pytest.mark.usefixtures("setup_db")
async def _seed_product(client, name: str, supported_os=None, requires=None, conflicts_with=None) -> tuple[str, str]:
    """Create a catalogue product + version via the API, return (product_id, version_id)."""
    resp = await client.post("/api/v1/build/catalogue", json={
        "name": name, "display_name": name.title(), "category": "other", "dependencies": [],
    })
    assert resp.status_code == 201, resp.text
    product_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/build/catalogue/{product_id}/versions", json={
        "version": "1.0",
        "supported_os": supported_os or [],
        "requires": requires or [],
        "conflicts_with": conflicts_with or [],
        "is_latest": True,
    })
    assert resp.status_code == 201, resp.text
    return product_id, resp.json()["id"]


@pytest.mark.usefixtures("setup_db")
async def test_check_compatibility_flags_unsupported_os(client):
    from app.core.database import async_session

    _, version_id = await _seed_product(
        client, f"stage6-os-{uuid.uuid4().hex[:8]}",
        supported_os=[{"os": "rhel", "min": "8"}],
    )
    async with async_session() as db:
        result = await check_compatibility(
            db, "ubuntu", "24.04",
            [{"role": "host-01", "selections": [{"product_id": "x", "version_id": version_id}]}],
        )
    assert result["valid"] is False
    assert any("Not supported on ubuntu" in e["message"] for e in result["errors"])


@pytest.mark.usefixtures("setup_db")
async def test_check_compatibility_auto_adds_required_dependency(client):
    from app.core.database import async_session

    dep_name = f"stage6-dep-{uuid.uuid4().hex[:8]}"
    await _seed_product(client, dep_name)
    _, version_id = await _seed_product(
        client, f"stage6-main-{uuid.uuid4().hex[:8]}",
        requires=[{"product": dep_name, "reason": "needs it"}],
    )
    async with async_session() as db:
        result = await check_compatibility(
            db, "ubuntu", "24.04",
            [{"role": "host-01", "selections": [{"product_id": "x", "version_id": version_id}]}],
        )
    assert result["valid"] is True
    assert any(d["product"] == dep_name for d in result["auto_dependencies"])


@pytest.mark.usefixtures("setup_db")
async def test_check_compatibility_flags_conflict_on_same_host_as_hard_error(client):
    # Conflicts are hard errors (valid=False), not warnings — a declared
    # conflicts_with pairing means the build will concretely fail (e.g. two
    # services fighting over the same port), confirmed via a live build
    # where Adminer + Apache on the same host made nginx fail to start with
    # "Address already in use". See find_host_conflicts()'s docstring.
    from app.core.database import async_session

    other_name = f"stage6-other-{uuid.uuid4().hex[:8]}"
    _, other_version_id = await _seed_product(client, other_name)
    _, version_id = await _seed_product(
        client, f"stage6-conflicter-{uuid.uuid4().hex[:8]}",
        conflicts_with=[{"product": other_name, "reason": "port clash"}],
    )
    async with async_session() as db:
        result = await check_compatibility(
            db, "ubuntu", "24.04",
            [{"role": "host-01", "selections": [
                {"product_id": "x", "version_id": version_id},
                {"product_id": "y", "version_id": other_version_id},
            ]}],
        )
    assert result["valid"] is False
    assert any(other_name in e["message"] for e in result["errors"])
    assert result["warnings"] == []


@pytest.mark.usefixtures("setup_db")
async def test_check_compatibility_does_not_flag_conflict_across_different_hosts(client):
    # The same two conflicting products on *different* hosts is not a real
    # problem (no shared machine, no port collision) — conflicts must be
    # scoped per host, not checked across the whole template's selections.
    from app.core.database import async_session

    other_name = f"stage6-other-{uuid.uuid4().hex[:8]}"
    _, other_version_id = await _seed_product(client, other_name)
    _, version_id = await _seed_product(
        client, f"stage6-conflicter-{uuid.uuid4().hex[:8]}",
        conflicts_with=[{"product": other_name, "reason": "port clash"}],
    )
    async with async_session() as db:
        result = await check_compatibility(
            db, "ubuntu", "24.04",
            [
                {"role": "host-01", "selections": [{"product_id": "x", "version_id": version_id}]},
                {"role": "host-02", "selections": [{"product_id": "y", "version_id": other_version_id}]},
            ],
        )
    assert result["valid"] is True
    assert result["errors"] == []


# --- secrets_service.py: full CRUD + rotate round-trip ---

@pytest.mark.usefixtures("setup_db")
async def test_secret_create_get_update_rotate_delete_round_trip():
    from app.core.database import async_session

    async with async_session() as db:
        created = await create_secret(db, name=f"stage6-secret-{uuid.uuid4().hex[:8]}", value="initial-value")
        secret_id = created["id"]

        fetched = await get_secret(db, secret_id)
        assert fetched["value"] == "initial-value"
        assert fetched.get("rotated_at") is None or fetched["rotated_at"] is None

        await update_secret(db, secret_id, value="updated-value")
        fetched = await get_secret(db, secret_id)
        assert fetched["value"] == "updated-value"
        assert fetched["rotated_at"] is not None

        await rotate_secret(db, secret_id, "rotated-value")
        fetched = await get_secret(db, secret_id)
        assert fetched["value"] == "rotated-value"

        await delete_secret(db, secret_id)
        with pytest.raises(ValueError):
            await get_secret(db, secret_id)


@pytest.mark.usefixtures("setup_db")
async def test_create_secret_rejects_duplicate_name():
    from app.core.database import async_session

    name = f"stage6-dup-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        await create_secret(db, name=name, value="one")
        with pytest.raises(ValueError):
            await create_secret(db, name=name, value="two")


# --- config_editor_service.py: save/validate/restore round-trip ---

@pytest.mark.usefixtures("setup_db")
async def test_config_editor_save_validate_restore_round_trip(tmp_path):
    from app.core.database import async_session
    from app.models.build_manager import BMConfigFile
    from app.services.build_manager import config_editor_service as svc

    target = tmp_path / "test-config.yml"
    target.write_text("key: original\n")

    async with async_session() as db:
        cf = BMConfigFile(
            id=str(uuid.uuid4()), path=str(target), display_name="test-config.yml",
            category="other", format="yaml", purpose="stage 6 test fixture", editable=True,
        )
        db.add(cf)
        await db.commit()
        file_id = cf.id

        # Validate: well-formed YAML passes
        result = await svc.validate_file(db, file_id, "key: value\n")
        assert result["valid"] is True

        # Validate: malformed YAML is caught with a line number
        bad_result = await svc.validate_file(db, file_id, "key: [unterminated\n")
        assert bad_result["valid"] is False
        assert bad_result["errors"][0]["line"] >= 1

        # Save: writes to disk, creates a backup, records version 1
        save_result = await svc.save_file(db, file_id, "key: updated\n", username="tester", comment="first edit")
        assert save_result["saved"] is True
        assert save_result["version"] == 1
        assert save_result["backup"] is not None
        assert target.read_text() == "key: updated\n"

        # Save again: version increments, diff is generated
        save_result_2 = await svc.save_file(db, file_id, "key: updated-again\n", username="tester", comment="second edit")
        assert save_result_2["version"] == 2

        history = await svc.get_file_history(db, file_id)
        assert [v["version"] for v in history] == [2, 1]
        assert all(v["has_diff"] for v in history)

        # Restore version 1: writes v1's content back and records a new version
        restore_result = await svc.restore_file(db, file_id, version=1, username="tester")
        assert restore_result["saved"] is True
        assert restore_result["version"] == 3
        assert target.read_text() == "key: updated\n"

        diff = await svc.diff_versions(db, file_id, 1, 2)
        assert "updated-again" in diff["diff"]


@pytest.mark.usefixtures("setup_db")
async def test_config_editor_save_rejects_invalid_content(tmp_path):
    from app.core.database import async_session
    from app.models.build_manager import BMConfigFile
    from app.services.build_manager import config_editor_service as svc

    target = tmp_path / "bad-config.yml"
    target.write_text("key: original\n")

    async with async_session() as db:
        cf = BMConfigFile(
            id=str(uuid.uuid4()), path=str(target), display_name="bad-config.yml",
            category="other", format="yaml", purpose="stage 6 test fixture", editable=True,
        )
        db.add(cf)
        await db.commit()

        save_result = await svc.save_file(db, cf.id, "key: [unterminated\n", username="tester")
        assert save_result["saved"] is False
        assert save_result["errors"]
        assert target.read_text() == "key: original\n"  # untouched on validation failure


@pytest.mark.usefixtures("setup_db")
async def test_config_editor_save_rejects_readonly_file(tmp_path):
    from app.core.database import async_session
    from app.models.build_manager import BMConfigFile
    from app.services.build_manager import config_editor_service as svc

    target = tmp_path / "readonly-config.txt"
    target.write_text("original\n")

    async with async_session() as db:
        cf = BMConfigFile(
            id=str(uuid.uuid4()), path=str(target), display_name="readonly-config.txt",
            category="generated", format="text", purpose="stage 6 test fixture", editable=False,
        )
        db.add(cf)
        await db.commit()

        with pytest.raises(PermissionError):
            await svc.save_file(db, cf.id, "changed\n", username="tester")


# --- Environment lifecycle smoke test: build -> destroy ---

@pytest.mark.usefixtures("setup_db")
async def test_build_and_destroy_environment_lifecycle(client):
    # A real root CA (Docker-free — pure crypto engine, no external target needed)
    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"Stage6 Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    assert resp.status_code == 201, resp.text
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"stage6-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1"}]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"stage6-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        # A real IP (not a bare role name) so ip_allocations resolves to
        # something ipaddress.ip_address() accepts — otherwise build_environment
        # treats the allocation as a Docker container name and tries to create
        # one, which needs a Docker socket this test has no business touching.
        "ip_overrides": {"generic1": "10.99.99.99"},
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"

    # Build: issues a real cert for the one host role and creates a job —
    # the actual ansible-playbook run against a fake target is out of scope
    # for this smoke test (stretch goal per the hardening plan); what matters
    # here is that cert issuance + job creation + status transition all work.
    # force=true skips the pre-flight reachability check — 10.99.99.99 is a
    # fake IP with nothing listening, which pre-flight now correctly (and
    # deliberately) blocks on; this test isn't exercising that check.
    resp = await client.post(f"/api/v1/build/environments/{env_id}/build?force=true")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    assert resp.json()["status"] == "provisioning"

    resp = await client.get(f"/api/v1/build/environments/{env_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "provisioning"
    assert len(resp.json()["certs"]) == 1  # one cert issued for the one host role

    # Stop the background Ansible run — its actual execution isn't this
    # test's concern and would otherwise linger after the test completes.
    await client.post(f"/api/v1/build/jobs/{job_id}/cancel")

    # Destroy: revokes cert bindings and deletes the environment row.
    resp = await client.post(f"/api/v1/build/environments/{env_id}/destroy")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "destroyed"

    resp = await client.get(f"/api/v1/build/environments/{env_id}")
    assert resp.status_code == 404  # environment row is gone
