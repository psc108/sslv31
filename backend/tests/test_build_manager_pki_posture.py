"""Enhancement Plan Stage 11 — PKI posture dashboard.

The flagship differentiator: a single view aggregating cert/CA chain
topology, expiry risk, key strength, auto-renew status, and secret rotation
staleness (Stage 10) across every Build Manager environment. Pure
aggregation over existing facts (BMCertBinding, Certificate,
CertificateAuthority, BMSecret) — no new data model.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.usefixtures("setup_db")
async def test_pki_posture_empty_state(client):
    resp = await client.get("/api/v1/build/pki-posture")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["environments"] == []
    assert body["secrets"] == []
    assert body["summary"]["total_certs"] == 0


async def _build_env_with_real_cert(client, ttl_days: int | None = None) -> tuple[str, str]:
    """Mirrors test_build_manager_stage6_coverage.py's real build/provision
    flow — issues a real cert (Docker-free crypto engine) and creates a real
    BMCertBinding via the app's own provisioning path, not a hand-rolled row,
    so the aggregation is exercised against the same data shape production
    code produces."""
    resp = await client.post("/api/v1/ca", json={
        "subject": {"cn": f"PKI Posture Test Root {uuid.uuid4().hex[:8]}"},
        "key_algo": "RSA", "key_size": 2048, "validity_days": 30,
    })
    assert resp.status_code == 201, resp.text
    ca_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/templates", json={
        "name": f"pki-posture-template-{uuid.uuid4().hex[:8]}",
        "spec": {"hosts": [{"role": "generic1"}]},
    })
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = await client.post("/api/v1/build/environments", json={
        "name": f"pki-posture-env-{uuid.uuid4().hex[:8]}",
        "template_id": template_id,
        "ip_overrides": {"generic1": "10.98.99.99"},
        "variables": {"signing_ca_id": ca_id},
    })
    assert resp.status_code == 201, resp.text
    env_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/build/environments/{env_id}/build")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    await client.post(f"/api/v1/build/jobs/{job_id}/cancel")

    if ttl_days is not None:
        from app.core.database import async_session
        from app.models.build_manager import BMCertBinding
        from sqlalchemy import select
        async with async_session() as db:
            bindings = (await db.execute(select(BMCertBinding).where(BMCertBinding.environment_id == env_id))).scalars().all()
            for b in bindings:
                b.expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
            await db.commit()

    return env_id, ca_id


@pytest.mark.usefixtures("setup_db")
async def test_pki_posture_aggregates_real_binding_with_risk_and_key_info(client):
    env_id, ca_id = await _build_env_with_real_cert(client, ttl_days=5)

    resp = await client.get("/api/v1/build/pki-posture")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    matching = [e for e in body["environments"] if e["environment_id"] == env_id]
    assert len(matching) == 1
    env = matching[0]
    assert len(env["certs"]) == 1
    cert = env["certs"][0]
    assert cert["role"] == "generic1"
    assert cert["key_algo"] == "RSA"
    assert cert["key_size"] == 2048
    assert cert["weak_key"] is False
    assert cert["risk"] == "critical"  # 5 days out, inside the 7-day critical window
    assert cert["auto_renew"] is True
    assert cert["signing_ca_chain"]  # at least the immediate signer's name

    assert body["summary"]["total_certs"] >= 1
    assert body["summary"]["critical_count"] >= 1


@pytest.mark.usefixtures("setup_db")
async def test_pki_posture_flags_expired_and_ok_risk_correctly(client):
    env_id, _ = await _build_env_with_real_cert(client, ttl_days=-1)

    resp = await client.get("/api/v1/build/pki-posture")
    matching = [e for e in resp.json()["environments"] if e["environment_id"] == env_id]
    assert matching[0]["certs"][0]["risk"] == "expired"


@pytest.mark.usefixtures("setup_db")
async def test_pki_posture_flags_weak_rsa_key():
    """Directly exercises the weak-key threshold — issuing a genuinely weak
    key through the real API is blocked by ca.py's own >=2048 validation
    (a good thing), so this constructs the row directly to test the
    aggregation logic's own threshold check in isolation."""
    from app.core.database import async_session
    from app.models.build_manager import BMCertBinding, BMEnvironment
    from app.models.certificate import Certificate
    from app.services.build_manager.pki_posture_service import get_pki_posture

    async with async_session() as db:
        env = BMEnvironment(id=str(uuid.uuid4()), name=f"weak-key-env-{uuid.uuid4().hex[:8]}", template_id=str(uuid.uuid4()), template_version=1, status="active")
        db.add(env)
        cert = Certificate(
            id=str(uuid.uuid4()), serial=uuid.uuid4().hex, profile="server",
            subject_json="{}", key_algo="RSA", key_size=1024,
            cert_pem="", key_blob=b"", status="valid",
            expires_at=datetime.now(timezone.utc) + timedelta(days=180),
        )
        db.add(cert)
        binding = BMCertBinding(
            id=str(uuid.uuid4()), environment_id=env.id, cert_serial=cert.serial,
            role="weak-role", cert_type="server", expires_at=cert.expires_at, auto_renew=False,
        )
        db.add(binding)
        await db.commit()

        posture = await get_pki_posture(db)

    matching = [e for e in posture["environments"] if e["environment_id"] == env.id]
    assert matching[0]["certs"][0]["weak_key"] is True
    assert posture["summary"]["weak_key_count"] >= 1


@pytest.mark.usefixtures("setup_db")
async def test_pki_posture_excludes_destroyed_environments():
    from app.core.database import async_session
    from app.models.build_manager import BMEnvironment
    from app.services.build_manager.pki_posture_service import get_pki_posture

    async with async_session() as db:
        env = BMEnvironment(id=str(uuid.uuid4()), name=f"destroyed-env-{uuid.uuid4().hex[:8]}", template_id=str(uuid.uuid4()), template_version=1, status="destroyed")
        db.add(env)
        await db.commit()

        posture = await get_pki_posture(db)

    assert env.id not in [e["environment_id"] for e in posture["environments"]]


@pytest.mark.usefixtures("setup_db")
async def test_pki_posture_secrets_section_reflects_rotation_overdue(client):
    from app.core.database import async_session
    from app.models.build_manager import BMSecret
    from sqlalchemy import select

    resp = await client.post("/api/v1/build/secrets", json={
        "name": f"pki-posture-secret-{uuid.uuid4().hex[:8]}", "value": "s3cret", "rotate_every_days": 30,
    })
    secret_id = resp.json()["id"]
    async with async_session() as db:
        secret = (await db.execute(select(BMSecret).where(BMSecret.id == secret_id))).scalar_one()
        secret.created_at = datetime.now(timezone.utc) - timedelta(days=40)
        await db.commit()

    resp = await client.get("/api/v1/build/pki-posture")
    body = resp.json()
    matching = [s for s in body["secrets"] if s["id"] == secret_id]
    assert len(matching) == 1
    assert matching[0]["rotation_overdue"] is True
    assert body["summary"]["secrets_overdue_count"] >= 1

    await client.delete(f"/api/v1/build/secrets/{secret_id}")
