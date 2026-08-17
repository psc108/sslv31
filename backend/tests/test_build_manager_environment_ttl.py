"""Enhancement Plan Stage 5 — environment TTL / scheduled auto-destroy.

BMEnvironment.expires_at is optional and opt-in — every pre-existing/no-TTL
environment has it null and is completely unaffected. destroy_expired_environments()
(the function the background scheduler calls on a recurring interval, same
pattern as the app's existing run_expiry_scanner) finds environments past
their TTL and destroys them via the existing destroy_environment() service —
no new destroy logic, just a trigger.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.services.build_manager import container_manager


@pytest.mark.usefixtures("setup_db")
async def test_create_environment_with_ttl_sets_expires_at(client):
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"ttl-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1"}]},
    })
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"ttl-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "ttl_hours": 4,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["expires_at"] is not None

    expires = datetime.fromisoformat(body["expires_at"])
    created = datetime.fromisoformat(body["created_at"])
    delta_hours = (expires - created).total_seconds() / 3600
    assert 3.9 < delta_hours < 4.1


@pytest.mark.usefixtures("setup_db")
async def test_create_environment_without_ttl_has_no_expiry(client):
    resp = await client.post("/api/v1/build/templates", json={
        "name": f"no-ttl-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1"}]},
    })
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"no-ttl-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["expires_at"] is None


@pytest.mark.usefixtures("setup_db")
async def test_destroy_expired_environments_destroys_only_past_ttl(client):
    from app.core.database import async_session
    from app.models.build_manager import BMEnvironment
    from app.services.build_manager.environment_service import destroy_expired_environments

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"expiry-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1"}]},
    })
    template_id = resp.json()["id"]

    # One already-expired environment, one with a future TTL, one with no TTL.
    expired_name = f"expired-env-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/environments", json={
        "name": expired_name, "template_id": template_id, "ttl_hours": 1,
    })
    expired_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"future-env-{uuid.uuid4().hex[:8]}", "template_id": template_id, "ttl_hours": 100,
    })
    future_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"no-ttl-env2-{uuid.uuid4().hex[:8]}", "template_id": template_id,
    })
    no_ttl_id = resp.json()["id"]

    # Force the first one's expires_at into the past directly (faster/more
    # deterministic than waiting a real hour in a test).
    async with async_session() as db:
        env = (await db.execute(select(BMEnvironment).where(BMEnvironment.id == expired_id))).scalar_one()
        env.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db.commit()

    async with async_session() as db:
        destroyed = await destroy_expired_environments(db)

    assert destroyed == [expired_name]

    resp = await client.get(f"/api/v1/build/environments/{expired_id}")
    assert resp.status_code == 404  # destroy_environment deletes the row

    resp = await client.get(f"/api/v1/build/environments/{future_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] != "destroyed"

    resp = await client.get(f"/api/v1/build/environments/{no_ttl_id}")
    assert resp.status_code == 200


@pytest.mark.usefixtures("setup_db")
async def test_destroy_expired_environments_is_a_noop_when_nothing_expired(client):
    from app.core.database import async_session
    from app.services.build_manager.environment_service import destroy_expired_environments

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"noop-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1"}]},
    })
    template_id = resp.json()["id"]
    resp = await client.post("/api/v1/build/environments", json={
        "name": f"noop-env-{uuid.uuid4().hex[:8]}", "template_id": template_id, "ttl_hours": 48,
    })
    env_id = resp.json()["id"]

    async with async_session() as db:
        destroyed = await destroy_expired_environments(db)
    assert destroyed == []

    resp = await client.get(f"/api/v1/build/environments/{env_id}")
    assert resp.status_code == 200


@pytest.mark.usefixtures("setup_db")
async def test_ttl_expiry_also_removes_docker_containers(client):
    """TTL auto-destroy previously only deleted the DB row — any Docker
    containers backing the environment were left running indefinitely.
    destroy_environment() now cleans up containers itself, so both the
    manual /destroy endpoint and TTL expiry behave identically."""
    from app.core.database import async_session
    from app.models.build_manager import BMEnvironment
    from app.services.build_manager.environment_service import destroy_expired_environments

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"ttl-docker-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "web-1"}, {"role": "web-2"}]},
    })
    template_id = resp.json()["id"]

    env_name = f"ttl-docker-env-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/build/environments", json={
        "name": env_name, "template_id": template_id, "ttl_hours": 1,
    })
    env_id = resp.json()["id"]

    async with async_session() as db:
        env = (await db.execute(select(BMEnvironment).where(BMEnvironment.id == env_id))).scalar_one()
        env.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db.commit()

    with patch.object(container_manager, "cleanup_containers_for_environment",
                       new=AsyncMock(return_value=[])) as mock_cleanup:
        async with async_session() as db:
            destroyed = await destroy_expired_environments(db)

    assert destroyed == [env_name]
    mock_cleanup.assert_awaited_once()
    cleaned_names = set(mock_cleanup.await_args.args[0])
    assert cleaned_names == {"web-1", "web-2"}


@pytest.mark.usefixtures("setup_db")
async def test_destroy_environment_resilient_to_container_cleanup_failure(client):
    """The environment row is already deleted by the time container cleanup
    runs — a Docker-side failure there (socket unreachable, container
    already gone, etc.) must not make the destroy look like it failed,
    since the authoritative DB-level destroy already succeeded."""
    from app.services.build_manager.environment_service import destroy_environment

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"resilient-destroy-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "web-1"}]},
    })
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"resilient-destroy-env-{uuid.uuid4().hex[:8]}", "template_id": template_id,
    })
    env_id = resp.json()["id"]

    from app.core.database import async_session
    with patch.object(container_manager, "cleanup_containers_for_environment",
                       new=AsyncMock(side_effect=RuntimeError("Docker socket unreachable"))):
        async with async_session() as db:
            result = await destroy_environment(db, env_id)

    assert result.status == "destroyed"
    resp = await client.get(f"/api/v1/build/environments/{env_id}")
    assert resp.status_code == 404  # row genuinely gone despite cleanup failure
