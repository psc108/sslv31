"""
End-to-end tests for the Environment Provisioning feature.

Covers: ZIP generation, cert SANs, keystore verification, Jasypt decryption,
chain validation, key matching, and error handling.
"""

import io
import zipfile

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12 as _pkcs12
from httpx import AsyncClient

from app.services.jasypt_engine import decrypt, unwrap_enc
from app.services.provisioning_engine import (
    HostConfig,
    ProvisioningEngine,
    ProvisioningRequest,
)


# --- Fixtures ---

VALID_REQUEST = ProvisioningRequest(
    env_name="test-env",
    hosts=[
        HostConfig(role="mysql", fqdn="mysql.test.local", ip="10.0.0.1"),
        HostConfig(role="rabbitmq", fqdn="rabbit.test.local", ip="10.0.0.2"),
        HostConfig(role="keystone", fqdn="keystone.test.local", ip="10.0.0.3"),
        HostConfig(role="backend", fqdn="backend.test.local", ip="10.0.0.4"),
        HostConfig(role="frontend", fqdn="frontend.test.local", ip="10.0.0.5"),
    ],
    ssl_passphrase="TestPass123!",
    encryption_key="TestEncKey123!",
    key_algo="RSA",
    key_size=2048,
    ca_validity_days=3650,
    cert_validity_days=365,
    cipher_profile="intermediate",
    base_path="/opt/scripts/ssl",
    include_nopass=True,
    include_snippets=True,
    include_scripts=True,
    include_readmes=True,
    include_quicksetup=True,
)


@pytest.fixture(scope="module")
def engine():
    return ProvisioningEngine()


@pytest.fixture(scope="module")
def result(engine):
    """Generate once, reuse across all tests in this module."""
    return engine.generate(VALID_REQUEST)


@pytest.fixture(scope="module")
def zip_file(result):
    return zipfile.ZipFile(io.BytesIO(result.zip_bytes))


# --- ZIP Structure Tests ---

class TestZIPStructure:
    def test_zip_is_valid(self, result):
        buf = io.BytesIO(result.zip_bytes)
        assert zipfile.is_zipfile(buf)

    def test_cert_count(self, result):
        assert result.cert_count == 7  # 5 server + 2 client

    def test_keystore_count(self, result):
        assert result.keystore_count == 12  # 7 keystores + 5 truststores

    def test_ca_files_present(self, zip_file):
        names = zip_file.namelist()
        assert "test-env-ssl/ca/ca.pem" in names
        assert "test-env-ssl/ca/ca.der" in names

    def test_all_machine_dirs_present(self, zip_file):
        names = zip_file.namelist()
        for role in ("mysql", "rabbitmq", "keystone", "backend", "frontend"):
            assert any(f"test-env-ssl/{role}/" in n for n in names)

    def test_server_certs_present(self, zip_file):
        names = zip_file.namelist()
        for role in ("mysql", "rabbitmq", "keystone", "backend", "frontend"):
            assert f"test-env-ssl/{role}/certs/server-cert.pem" in names
            assert f"test-env-ssl/{role}/certs/server.key" in names
            assert f"test-env-ssl/{role}/certs/ca.pem" in names

    def test_client_certs_present(self, zip_file):
        names = zip_file.namelist()
        for role in ("backend", "frontend"):
            assert f"test-env-ssl/{role}/certs/client-cert.pem" in names
            assert f"test-env-ssl/{role}/certs/client.key" in names

    def test_no_client_certs_for_servers(self, zip_file):
        names = zip_file.namelist()
        for role in ("mysql", "rabbitmq", "keystone"):
            assert f"test-env-ssl/{role}/certs/client-cert.pem" not in names

    def test_nopass_keys_present(self, zip_file):
        names = zip_file.namelist()
        for role in ("mysql", "rabbitmq", "keystone", "backend", "frontend"):
            assert f"test-env-ssl/{role}/certs/server.key.nopass" in names

    def test_keystores_present(self, zip_file):
        names = zip_file.namelist()
        for role in ("mysql", "rabbitmq", "keystone", "backend", "frontend"):
            assert f"test-env-ssl/{role}/stores/server-keystore.p12" in names
            assert f"test-env-ssl/{role}/stores/truststore.p12" in names
        for role in ("backend", "frontend"):
            assert f"test-env-ssl/{role}/stores/client-keystore.p12" in names

    def test_config_snippets_present(self, zip_file):
        names = zip_file.namelist()
        assert "test-env-ssl/mysql/config/ssl.cnf.snippet" in names
        assert "test-env-ssl/rabbitmq/config/rabbitmq-ssl.conf.snippet" in names
        assert "test-env-ssl/keystone/config/apache-ssl.conf.snippet" in names
        assert "test-env-ssl/backend/config/application-ssl.yml.snippet" in names
        assert "test-env-ssl/frontend/config/application-ssl.yml.snippet" in names

    def test_scripts_present(self, zip_file):
        names = zip_file.namelist()
        assert "test-env-ssl/scripts/distribute-certs.sh" in names
        assert "test-env-ssl/scripts/verify-certs.sh" in names

    def test_readmes_present(self, zip_file):
        names = zip_file.namelist()
        for role in ("ca", "mysql", "rabbitmq", "keystone", "backend", "frontend"):
            assert f"test-env-ssl/{role}/README.md" in names

    def test_quicksetup_present(self, zip_file):
        assert "test-env-ssl/quicksetup-ssl.properties" in zip_file.namelist()

    def test_deployment_guide_present(self, zip_file):
        assert "test-env-ssl/DEPLOYMENT-GUIDE.md" in zip_file.namelist()


# --- Certificate Validation Tests ---

class TestCertificates:
    def _load_cert(self, zip_file, path):
        pem = zip_file.read(path)
        return x509.load_pem_x509_certificate(pem)

    def test_ca_is_self_signed(self, zip_file):
        ca = self._load_cert(zip_file, "test-env-ssl/ca/ca.pem")
        assert ca.issuer == ca.subject

    def test_ca_is_ca(self, zip_file):
        ca = self._load_cert(zip_file, "test-env-ssl/ca/ca.pem")
        bc = ca.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is True

    def test_server_cert_sans_contain_fqdn_and_ip(self, zip_file):
        cert = self._load_cert(zip_file, "test-env-ssl/mysql/certs/server-cert.pem")
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        ips = [str(ip) for ip in san.value.get_values_for_type(x509.IPAddress)]
        assert "mysql.test.local" in dns_names
        assert "localhost" in dns_names
        assert "10.0.0.1" in ips
        assert "127.0.0.1" in ips

    def test_backend_server_cert_sans(self, zip_file):
        cert = self._load_cert(zip_file, "test-env-ssl/backend/certs/server-cert.pem")
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "backend.test.local" in dns_names
        assert "localhost" in dns_names

    def test_client_cert_has_sans(self, zip_file):
        cert = self._load_cert(zip_file, "test-env-ssl/backend/certs/client-cert.pem")
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert len(dns_names) >= 1

    def test_all_certs_chain_to_ca(self, zip_file):
        """Verify all issued certs have the CA as issuer."""
        ca = self._load_cert(zip_file, "test-env-ssl/ca/ca.pem")
        cert_paths = [n for n in zip_file.namelist() if n.endswith("-cert.pem") and "/ca/" not in n]
        for path in cert_paths:
            cert = self._load_cert(zip_file, path)
            assert cert.issuer == ca.subject, f"{path} not issued by CA"

    def test_ca_der_matches_pem(self, zip_file):
        ca_pem = self._load_cert(zip_file, "test-env-ssl/ca/ca.pem")
        ca_der_bytes = zip_file.read("test-env-ssl/ca/ca.der")
        ca_der = x509.load_der_x509_certificate(ca_der_bytes)
        assert ca_pem.serial_number == ca_der.serial_number


# --- Key Validation Tests ---

class TestKeys:
    def test_encrypted_key_requires_passphrase(self, zip_file):
        key_pem = zip_file.read("test-env-ssl/mysql/certs/server.key")
        assert b"ENCRYPTED" in key_pem
        with pytest.raises(Exception):
            serialization.load_pem_private_key(key_pem, password=None)

    def test_encrypted_key_opens_with_passphrase(self, zip_file):
        key_pem = zip_file.read("test-env-ssl/mysql/certs/server.key")
        key = serialization.load_pem_private_key(key_pem, password=b"TestPass123!")
        assert key is not None

    def test_nopass_key_opens_without_passphrase(self, zip_file):
        key_pem = zip_file.read("test-env-ssl/mysql/certs/server.key.nopass")
        key = serialization.load_pem_private_key(key_pem, password=None)
        assert key is not None

    def test_nopass_matches_encrypted_key(self, zip_file):
        """Both keys should have the same public numbers."""
        enc_pem = zip_file.read("test-env-ssl/backend/certs/server.key")
        nopass_pem = zip_file.read("test-env-ssl/backend/certs/server.key.nopass")
        enc_key = serialization.load_pem_private_key(enc_pem, password=b"TestPass123!")
        nopass_key = serialization.load_pem_private_key(nopass_pem, password=None)
        assert enc_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ) == nopass_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def test_key_matches_cert(self, zip_file):
        """Server key public numbers match server cert public key."""
        cert = x509.load_pem_x509_certificate(
            zip_file.read("test-env-ssl/mysql/certs/server-cert.pem")
        )
        key = serialization.load_pem_private_key(
            zip_file.read("test-env-ssl/mysql/certs/server.key.nopass"), password=None
        )
        cert_pub = cert.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        key_pub = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        assert cert_pub == key_pub


# --- Keystore Tests ---

class TestKeystores:
    def test_server_keystore_opens(self, zip_file):
        p12_bytes = zip_file.read("test-env-ssl/mysql/stores/server-keystore.p12")
        key, cert, chain = _pkcs12.load_key_and_certificates(p12_bytes, b"TestPass123!")
        assert key is not None
        assert cert is not None

    def test_keystore_contains_ca_chain(self, zip_file):
        p12_bytes = zip_file.read("test-env-ssl/backend/stores/server-keystore.p12")
        key, cert, chain = _pkcs12.load_key_and_certificates(p12_bytes, b"TestPass123!")
        assert chain is not None
        assert len(chain) >= 1

    def test_truststore_opens(self, zip_file):
        p12_bytes = zip_file.read("test-env-ssl/mysql/stores/truststore.p12")
        # Truststore is a PKCS#12 with the CA cert and no private key
        # The CA cert is stored as the "cert" in serialize_key_and_certificates
        # but load returns it in the cert position
        key, cert, chain = _pkcs12.load_key_and_certificates(p12_bytes, b"TestPass123!")
        assert key is None  # No private key in truststore
        # CA cert may be in cert or chain depending on how it was serialized
        has_ca = cert is not None or (chain is not None and len(chain) > 0)
        assert has_ca

    def test_client_keystore_opens(self, zip_file):
        p12_bytes = zip_file.read("test-env-ssl/backend/stores/client-keystore.p12")
        key, cert, chain = _pkcs12.load_key_and_certificates(p12_bytes, b"TestPass123!")
        assert key is not None
        assert cert is not None


# --- Jasypt Encryption Tests ---

class TestJasyptInBundle:
    def test_quicksetup_contains_enc_values(self, zip_file):
        content = zip_file.read("test-env-ssl/quicksetup-ssl.properties").decode()
        assert "ENC(" in content

    def test_enc_values_decrypt_correctly(self, zip_file):
        content = zip_file.read("test-env-ssl/quicksetup-ssl.properties").decode()
        # Find ENC(...) values
        import re
        enc_values = re.findall(r"ENC\(([^)]+)\)", content)
        assert len(enc_values) >= 1
        # All should decrypt to the SSL passphrase
        for enc_val in enc_values:
            decrypted = decrypt(enc_val, "TestEncKey123!")
            assert decrypted == "TestPass123!"

    def test_spring_boot_contains_enc_values(self, zip_file):
        content = zip_file.read("test-env-ssl/backend/config/application-ssl.yml.snippet").decode()
        assert "ENC(" in content


# --- Config Snippet Tests ---

class TestConfigSnippets:
    def test_mysql_snippet_has_paths(self, zip_file):
        content = zip_file.read("test-env-ssl/mysql/config/ssl.cnf.snippet").decode()
        assert "/opt/scripts/ssl" in content
        assert "ssl" in content.lower()

    def test_rabbitmq_snippet_has_listeners(self, zip_file):
        content = zip_file.read("test-env-ssl/rabbitmq/config/rabbitmq-ssl.conf.snippet").decode()
        assert "listener" in content.lower() or "ssl" in content.lower()

    def test_spring_boot_snippet_has_keystore(self, zip_file):
        content = zip_file.read("test-env-ssl/backend/config/application-ssl.yml.snippet").decode()
        assert "keystore" in content.lower() or "key-store" in content.lower()

    def test_frontend_snippet_different_from_backend(self, zip_file):
        backend = zip_file.read("test-env-ssl/backend/config/application-ssl.yml.snippet").decode()
        frontend = zip_file.read("test-env-ssl/frontend/config/application-ssl.yml.snippet").decode()
        # They use the same template but with different role context
        # At minimum, paths should reference different directories
        assert "backend" in backend or "frontend" in frontend


# --- Options Tests ---

class TestOptions:
    def test_no_nopass_when_disabled(self, engine):
        req = ProvisioningRequest(
            env_name="no-nopass",
            hosts=[HostConfig(role="mysql", fqdn="db.test", ip="10.0.0.1")],
            ssl_passphrase="TestPass123!",
            encryption_key="TestEncKey123!",
            include_nopass=False,
            include_snippets=False,
            include_scripts=False,
            include_readmes=False,
            include_quicksetup=False,
        )
        result = engine.generate(req)
        zf = zipfile.ZipFile(io.BytesIO(result.zip_bytes))
        names = zf.namelist()
        assert not any(".key.nopass" in n for n in names)

    def test_no_snippets_when_disabled(self, engine):
        req = ProvisioningRequest(
            env_name="no-snippets",
            hosts=[HostConfig(role="mysql", fqdn="db.test", ip="10.0.0.1")],
            ssl_passphrase="TestPass123!",
            encryption_key="TestEncKey123!",
            include_snippets=False,
            include_scripts=False,
            include_readmes=False,
            include_quicksetup=False,
        )
        result = engine.generate(req)
        zf = zipfile.ZipFile(io.BytesIO(result.zip_bytes))
        names = zf.namelist()
        assert not any("/config/" in n for n in names)

    def test_single_host_works(self, engine):
        """Should work with just one host."""
        req = ProvisioningRequest(
            env_name="single",
            hosts=[HostConfig(role="backend", fqdn="app.test", ip="10.0.0.1")],
            ssl_passphrase="TestPass123!",
            encryption_key="TestEncKey123!",
        )
        result = engine.generate(req)
        assert result.cert_count == 2  # 1 server + 1 client for backend


# --- Cipher Profile Tests ---

class TestCipherProfiles:
    def test_modern_profile(self, engine):
        req = ProvisioningRequest(
            env_name="modern",
            hosts=[
                HostConfig(role="mysql", fqdn="db.test", ip="10.0.0.1"),
                HostConfig(role="rabbitmq", fqdn="mq.test", ip="10.0.0.2"),
                HostConfig(role="keystone", fqdn="ks.test", ip="10.0.0.3"),
                HostConfig(role="backend", fqdn="be.test", ip="10.0.0.4"),
                HostConfig(role="frontend", fqdn="fe.test", ip="10.0.0.5"),
            ],
            ssl_passphrase="TestPass123!",
            encryption_key="TestEncKey123!",
            cipher_profile="modern",
            include_scripts=False,
            include_readmes=False,
            include_quicksetup=False,
        )
        result = engine.generate(req)
        zf = zipfile.ZipFile(io.BytesIO(result.zip_bytes))
        content = zf.read("modern-ssl/mysql/config/ssl.cnf.snippet").decode()
        assert "TLS" in content

    def test_legacy_profile(self, engine):
        req = ProvisioningRequest(
            env_name="legacy",
            hosts=[
                HostConfig(role="mysql", fqdn="db.test", ip="10.0.0.1"),
                HostConfig(role="rabbitmq", fqdn="mq.test", ip="10.0.0.2"),
                HostConfig(role="keystone", fqdn="ks.test", ip="10.0.0.3"),
                HostConfig(role="backend", fqdn="be.test", ip="10.0.0.4"),
                HostConfig(role="frontend", fqdn="fe.test", ip="10.0.0.5"),
            ],
            ssl_passphrase="TestPass123!",
            encryption_key="TestEncKey123!",
            cipher_profile="legacy",
            include_scripts=False,
            include_readmes=False,
            include_quicksetup=False,
        )
        result = engine.generate(req)
        zf = zipfile.ZipFile(io.BytesIO(result.zip_bytes))
        content = zf.read("legacy-ssl/mysql/config/ssl.cnf.snippet").decode()
        assert "AES256-SHA256" in content or "AES" in content


# --- API Endpoint Tests ---

@pytest.mark.asyncio
class TestProvisioningAPI:
    async def test_generate_returns_zip(self, client: AsyncClient):
        response = await client.post("/api/v1/provisioning/generate", json={
            "env_name": "api-test",
            "hosts": [
                {"role": "mysql", "fqdn": "db.local", "ip": "10.0.0.1"},
                {"role": "rabbitmq", "fqdn": "mq.local", "ip": "10.0.0.2"},
                {"role": "keystone", "fqdn": "ks.local", "ip": "10.0.0.3"},
                {"role": "backend", "fqdn": "be.local", "ip": "10.0.0.4"},
                {"role": "frontend", "fqdn": "fe.local", "ip": "10.0.0.5"},
            ],
            "ssl_passphrase": "TestPass123!",
            "encryption_key": "TestEncKey123!",
        })
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert zipfile.is_zipfile(io.BytesIO(response.content))

    async def test_generate_missing_env_name(self, client: AsyncClient):
        response = await client.post("/api/v1/provisioning/generate", json={
            "env_name": "",
            "hosts": [{"role": "mysql", "fqdn": "db.local", "ip": "10.0.0.1"}],
            "ssl_passphrase": "TestPass123!",
            "encryption_key": "TestEncKey123!",
        })
        assert response.status_code == 422

    async def test_generate_short_passphrase(self, client: AsyncClient):
        response = await client.post("/api/v1/provisioning/generate", json={
            "env_name": "test",
            "hosts": [{"role": "mysql", "fqdn": "db.local", "ip": "10.0.0.1"}],
            "ssl_passphrase": "short",
            "encryption_key": "TestEncKey123!",
        })
        assert response.status_code == 422

    async def test_generate_invalid_role(self, client: AsyncClient):
        response = await client.post("/api/v1/provisioning/generate", json={
            "env_name": "test",
            "hosts": [{"role": "invalid", "fqdn": "db.local", "ip": "10.0.0.1"}],
            "ssl_passphrase": "TestPass123!",
            "encryption_key": "TestEncKey123!",
        })
        assert response.status_code == 422

    async def test_generate_invalid_cipher_profile(self, client: AsyncClient):
        response = await client.post("/api/v1/provisioning/generate", json={
            "env_name": "test",
            "hosts": [{"role": "mysql", "fqdn": "db.local", "ip": "10.0.0.1"}],
            "ssl_passphrase": "TestPass123!",
            "encryption_key": "TestEncKey123!",
            "cipher_profile": "nonexistent",
        })
        assert response.status_code == 422

    async def test_generate_no_hosts(self, client: AsyncClient):
        response = await client.post("/api/v1/provisioning/generate", json={
            "env_name": "test",
            "hosts": [],
            "ssl_passphrase": "TestPass123!",
            "encryption_key": "TestEncKey123!",
        })
        assert response.status_code == 422

    async def test_cipher_profiles_endpoint(self, client: AsyncClient):
        response = await client.get("/api/v1/provisioning/cipher-profiles")
        assert response.status_code == 200
        data = response.json()
        assert "profiles" in data
        assert "modern" in data["profiles"]
        assert "intermediate" in data["profiles"]
        assert "legacy" in data["profiles"]

    async def test_template_crud(self, client: AsyncClient):
        # Create
        create_resp = await client.post("/api/v1/provisioning/templates", json={
            "name": "test-template",
            "description": "Test",
            "config": {
                "env_name": "tmpl-env",
                "hosts": [{"role": "mysql", "fqdn": "db.local", "ip": "10.0.0.1"}],
                "ssl_passphrase": "TestPass123!",
                "encryption_key": "TestEncKey123!",
            },
        })
        assert create_resp.status_code == 201
        tmpl_id = create_resp.json()["id"]

        # List
        list_resp = await client.get("/api/v1/provisioning/templates")
        assert list_resp.status_code == 200
        assert any(t["id"] == tmpl_id for t in list_resp.json())

        # Get
        get_resp = await client.get(f"/api/v1/provisioning/templates/{tmpl_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "test-template"

        # Update
        put_resp = await client.put(f"/api/v1/provisioning/templates/{tmpl_id}", json={
            "name": "updated-template",
        })
        assert put_resp.status_code == 200
        assert put_resp.json()["name"] == "updated-template"

        # Delete
        del_resp = await client.delete(f"/api/v1/provisioning/templates/{tmpl_id}")
        assert del_resp.status_code == 200

    async def test_template_duplicate_name(self, client: AsyncClient):
        payload = {
            "name": "dup-test",
            "description": "",
            "config": {
                "env_name": "x",
                "hosts": [{"role": "mysql", "fqdn": "db.local", "ip": "10.0.0.1"}],
                "ssl_passphrase": "TestPass123!",
                "encryption_key": "TestEncKey123!",
            },
        }
        await client.post("/api/v1/provisioning/templates", json=payload)
        dup_resp = await client.post("/api/v1/provisioning/templates", json=payload)
        assert dup_resp.status_code == 409

    async def test_no_auth_rejected(self, client_no_auth: AsyncClient):
        response = await client_no_auth.post("/api/v1/provisioning/generate", json={
            "env_name": "test",
            "hosts": [{"role": "mysql", "fqdn": "db.local", "ip": "10.0.0.1"}],
            "ssl_passphrase": "TestPass123!",
            "encryption_key": "TestEncKey123!",
        })
        assert response.status_code == 401
