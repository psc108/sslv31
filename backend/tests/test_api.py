"""Integration tests for API endpoints — CA, certificate, export, audit."""

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_health_no_auth(self, client_no_auth: AsyncClient):
        response = await client_no_auth.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded")
        assert "version" in data


@pytest.mark.asyncio
class TestAuth:
    async def test_missing_api_key(self, client_no_auth: AsyncClient):
        response = await client_no_auth.get("/api/v1/ca")
        assert response.status_code == 401

    async def test_invalid_api_key(self, client_no_auth: AsyncClient):
        response = await client_no_auth.get("/api/v1/ca", headers={"X-API-Key": "wrong"})
        assert response.status_code == 401

    async def test_valid_api_key(self, client: AsyncClient):
        response = await client.get("/api/v1/ca")
        assert response.status_code == 200


@pytest.mark.asyncio
class TestCAEndpoints:
    async def test_create_root_ca(self, client: AsyncClient):
        response = await client.post("/api/v1/ca", json={
            "subject": {"cn": "Test Root CA", "o": "Test", "ou": "", "c": "GB", "st": "", "l": ""},
            "key_algo": "RSA",
            "key_size": 2048,
            "validity_days": 3650,
            "path_length": 1,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["cn"] == "Test Root CA"
        assert data["is_root"] is True
        assert "-----BEGIN CERTIFICATE-----" in data["cert_pem"]

    async def test_list_cas(self, client: AsyncClient):
        response = await client.get("/api/v1/ca")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_create_intermediate_ca(self, client: AsyncClient):
        # Get root CA id
        list_resp = await client.get("/api/v1/ca")
        root_ca = [ca for ca in list_resp.json() if ca["is_root"]][0]

        response = await client.post("/api/v1/ca", json={
            "subject": {"cn": "Test Intermediate CA", "o": "Test", "ou": "", "c": "GB", "st": "", "l": ""},
            "key_algo": "RSA",
            "key_size": 2048,
            "validity_days": 1825,
            "parent_ca_id": root_ca["id"],
            "path_length": 0,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["is_root"] is False
        assert data["parent_ca_id"] == root_ca["id"]


@pytest.mark.asyncio
class TestCertificateEndpoints:
    async def test_issue_server_cert(self, client: AsyncClient):
        # Get a CA
        cas = (await client.get("/api/v1/ca")).json()
        ca_id = cas[0]["id"]

        response = await client.post("/api/v1/cert", json={
            "profile": "server",
            "signing_ca_id": ca_id,
            "subject": {"cn": "api.test.local", "o": "", "ou": "", "c": "", "st": "", "l": ""},
            "san": [{"type": "dns", "value": "api.test.local"}, {"type": "ip", "value": "10.0.0.1"}],
            "key_algo": "RSA",
            "key_size": 2048,
            "validity_days": 365,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["profile"] == "server"
        assert data["status"] == "valid"
        assert len(data["serial"]) > 0

    async def test_server_cert_requires_san(self, client: AsyncClient):
        cas = (await client.get("/api/v1/ca")).json()
        ca_id = cas[0]["id"]

        response = await client.post("/api/v1/cert", json={
            "profile": "server",
            "signing_ca_id": ca_id,
            "subject": {"cn": "no-san.test.local", "o": "", "ou": "", "c": "", "st": "", "l": ""},
            "san": [],
            "key_algo": "RSA",
            "key_size": 2048,
            "validity_days": 365,
        })
        assert response.status_code == 422

    async def test_list_certificates(self, client: AsyncClient):
        response = await client.get("/api/v1/cert")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    async def test_revoke_certificate(self, client: AsyncClient):
        # Get a cert
        certs = (await client.get("/api/v1/cert")).json()
        if certs["items"]:
            serial = certs["items"][0]["serial"]
            response = await client.delete(f"/api/v1/cert/{serial}")
            assert response.status_code == 200
            assert response.json()["status"] == "revoked"


@pytest.mark.asyncio
class TestExportEndpoints:
    async def test_export_pem(self, client: AsyncClient):
        # Issue a cert first
        cas = (await client.get("/api/v1/ca")).json()
        ca_id = cas[0]["id"]
        cert_resp = await client.post("/api/v1/cert", json={
            "profile": "server",
            "signing_ca_id": ca_id,
            "subject": {"cn": "export.test.local", "o": "", "ou": "", "c": "", "st": "", "l": ""},
            "san": [{"type": "dns", "value": "export.test.local"}],
            "key_algo": "RSA",
            "key_size": 2048,
            "validity_days": 30,
        })
        serial = cert_resp.json()["serial"]

        response = await client.get(f"/api/v1/export/{serial}/pem")
        assert response.status_code == 200
        assert b"BEGIN CERTIFICATE" in response.content

    async def test_export_der(self, client: AsyncClient):
        certs = (await client.get("/api/v1/cert")).json()
        valid_certs = [c for c in certs["items"] if c["status"] == "valid"]
        if valid_certs:
            serial = valid_certs[0]["serial"]
            response = await client.get(f"/api/v1/export/{serial}/der")
            assert response.status_code == 200
            assert b"BEGIN" not in response.content


@pytest.mark.asyncio
class TestCSREndpoints:
    async def test_create_csr_new_key(self, client: AsyncClient):
        response = await client.post("/api/v1/csr", json={
            "mode": "new_key",
            "subject": {"cn": "csr.test.local", "o": "Test", "ou": "", "c": "GB", "st": "", "l": ""},
            "san": [{"type": "dns", "value": "csr.test.local"}],
            "key_algo": "RSA",
            "key_size": 2048,
            "store_key": True,
            "digest": "sha256",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "pending"
        assert "BEGIN CERTIFICATE REQUEST" in data["csr_pem"]
        assert data["verification"]["signature"] == "pass"

    async def test_list_csrs(self, client: AsyncClient):
        response = await client.get("/api/v1/csr")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


@pytest.mark.asyncio
class TestAuditEndpoints:
    async def test_audit_log(self, client: AsyncClient):
        response = await client.get("/api/v1/audit")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert data["total"] > 0  # Previous test operations should have logged events

    async def test_audit_filter_by_type(self, client: AsyncClient):
        response = await client.get("/api/v1/audit?event_type=CA_CREATED")
        assert response.status_code == 200


@pytest.mark.asyncio
class TestBackupEndpoints:
    async def test_create_backup(self, client: AsyncClient):
        response = await client.post("/api/v1/backup")
        assert response.status_code == 201
        data = response.json()
        assert "filename" in data
        assert "sha256" in data
        assert data["filename"].startswith("backup-")

    async def test_list_backups(self, client: AsyncClient):
        response = await client.get("/api/v1/backup")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
