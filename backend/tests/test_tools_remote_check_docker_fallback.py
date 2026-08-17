"""Remote Check tool's localhost -> host.docker.internal fallback.

This tool's connection is made from the backend container's own network
namespace, not the browser's — so checking "localhost" (or 127.0.0.1/::1)
against a port Docker published on the real host (e.g. a Build Manager
environment's RabbitMQ management UI on host port 15671) always failed:
"localhost" there means the certmanager container itself, which has nothing
listening on that port. host.docker.internal routes back to the real host,
so a failed localhost-alias check is now retried through it before giving up.
"""
import datetime
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _self_signed_der() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test.internal")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.DER)


@pytest.mark.usefixtures("setup_db")
async def test_localhost_falls_back_to_docker_host_gateway(client):
    from app.api.v1 import tools

    der = _self_signed_der()

    def fake_fetch(hostname, port, ctx):
        if hostname == tools._DOCKER_HOST_GATEWAY:
            return der
        raise ConnectionRefusedError(111, "Connection refused")

    with patch.object(tools, "_fetch_remote_cert", side_effect=fake_fetch):
        resp = await client.post("/api/v1/tools/remote-check", data={"hostname": "localhost", "port": 15671})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hostname"] == "localhost"
    assert body["resolved_via"] == "host.docker.internal"


@pytest.mark.usefixtures("setup_db")
async def test_non_localhost_hostname_is_never_retried(client):
    """A real external hostname failing must report its own error, not
    silently probe host.docker.internal (which would be meaningless for it)."""
    from app.api.v1 import tools

    def fake_fetch(hostname, port, ctx):
        raise ConnectionRefusedError(111, "Connection refused")

    with patch.object(tools, "_fetch_remote_cert", side_effect=fake_fetch) as mocked:
        resp = await client.post("/api/v1/tools/remote-check", data={"hostname": "example.com", "port": 443})
    assert resp.status_code == 422
    assert "Connection refused" in resp.json()["detail"]
    mocked.assert_called_once()  # no host.docker.internal retry attempted


@pytest.mark.usefixtures("setup_db")
async def test_localhost_reports_original_error_when_fallback_also_fails(client):
    from app.api.v1 import tools

    def fake_fetch(hostname, port, ctx):
        raise ConnectionRefusedError(111, "Connection refused")

    with patch.object(tools, "_fetch_remote_cert", side_effect=fake_fetch):
        resp = await client.post("/api/v1/tools/remote-check", data={"hostname": "127.0.0.1", "port": 15671})
    assert resp.status_code == 422
    assert "127.0.0.1" in resp.json()["detail"]
