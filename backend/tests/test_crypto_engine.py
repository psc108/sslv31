"""Tests for CryptoEngine — key generation, CA creation, cert issuance, export."""

import os
import pytest
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519

from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry


@pytest.fixture
def engine():
    return CryptoEngine()


@pytest.fixture
def subject():
    return SubjectInfo(cn="test.example.com", o="Test Org", c="GB")


class TestKeyGeneration:
    def test_rsa_2048(self, engine):
        key = engine.generate_keypair("RSA", 2048)
        assert isinstance(key, rsa.RSAPrivateKey)
        assert key.key_size == 2048

    def test_rsa_4096(self, engine):
        key = engine.generate_keypair("RSA", 4096)
        assert key.key_size == 4096

    def test_ecdsa_p256(self, engine):
        key = engine.generate_keypair("ECDSA", 256)
        assert isinstance(key, ec.EllipticCurvePrivateKey)

    def test_ecdsa_p384(self, engine):
        key = engine.generate_keypair("ECDSA", 384)
        assert isinstance(key, ec.EllipticCurvePrivateKey)

    def test_ed25519(self, engine):
        key = engine.generate_keypair("Ed25519", 256)
        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_invalid_algo(self, engine):
        with pytest.raises(ValueError):
            engine.generate_keypair("DSA", 2048)

    def test_invalid_rsa_size(self, engine):
        with pytest.raises(ValueError):
            engine.generate_keypair("RSA", 1024)


class TestRootCA:
    def test_create_root_ca(self, engine, subject):
        key = engine.generate_keypair("RSA", 2048)
        cert = engine.create_root_ca(subject, key, 365)

        assert cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value == "test.example.com"
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is True
        assert bc.value.path_length == 1

    def test_root_ca_key_usage(self, engine, subject):
        key = engine.generate_keypair("RSA", 2048)
        cert = engine.create_root_ca(subject, key, 365)

        ku = cert.extensions.get_extension_for_class(x509.KeyUsage)
        assert ku.value.key_cert_sign is True
        assert ku.value.crl_sign is True

    def test_root_ca_serial_random(self, engine, subject):
        key = engine.generate_keypair("RSA", 2048)
        cert1 = engine.create_root_ca(subject, key, 365)
        cert2 = engine.create_root_ca(subject, key, 365)
        assert cert1.serial_number != cert2.serial_number


class TestCertificateIssuance:
    def test_server_cert_with_san(self, engine, subject):
        ca_key = engine.generate_keypair("RSA", 2048)
        ca_cert = engine.create_root_ca(subject, ca_key, 3650)

        leaf_key = engine.generate_keypair("RSA", 2048)
        san_list = [SANEntry(type="dns", value="api.test.com"), SANEntry(type="ip", value="10.0.0.1")]

        leaf_subject = SubjectInfo(cn="api.test.com")
        cert = engine.issue_certificate("server", leaf_subject, san_list, leaf_key, ca_key, ca_cert, 365)

        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is False

        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "api.test.com" in dns_names

    def test_server_cert_requires_san(self, engine, subject):
        ca_key = engine.generate_keypair("RSA", 2048)
        ca_cert = engine.create_root_ca(subject, ca_key, 3650)
        leaf_key = engine.generate_keypair("RSA", 2048)

        with pytest.raises(ValueError, match="SAN"):
            engine.issue_certificate("server", subject, [], leaf_key, ca_key, ca_cert, 365)

    def test_client_cert(self, engine, subject):
        ca_key = engine.generate_keypair("RSA", 2048)
        ca_cert = engine.create_root_ca(subject, ca_key, 3650)
        leaf_key = engine.generate_keypair("RSA", 2048)

        cert = engine.issue_certificate("client", subject, [], leaf_key, ca_key, ca_cert, 365)
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        assert x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH in eku.value


class TestExport:
    def test_export_pem(self, engine, subject):
        key = engine.generate_keypair("RSA", 2048)
        cert = engine.create_root_ca(subject, key, 365)
        pem = engine.export_cert_pem(cert)
        assert pem.startswith(b"-----BEGIN CERTIFICATE-----")

    def test_export_der(self, engine, subject):
        key = engine.generate_keypair("RSA", 2048)
        cert = engine.create_root_ca(subject, key, 365)
        der = engine.export_der(cert)
        assert len(der) > 0
        assert not der.startswith(b"-----")

    def test_export_pkcs12(self, engine, subject):
        ca_key = engine.generate_keypair("RSA", 2048)
        ca_cert = engine.create_root_ca(subject, ca_key, 3650)
        leaf_key = engine.generate_keypair("RSA", 2048)
        san_list = [SANEntry(type="dns", value="test.com")]
        cert = engine.issue_certificate("server", subject, san_list, leaf_key, ca_key, ca_cert, 365)

        p12 = engine.export_pkcs12(cert, leaf_key, [ca_cert], password="testpass123")
        assert len(p12) > 0


class TestKeyEncryption:
    def test_encrypt_decrypt_key(self, engine):
        master_key = Fernet.generate_key().decode()
        key = engine.generate_keypair("RSA", 2048)
        key_pem = engine.export_key_pem(key)

        encrypted = engine.encrypt_key_blob(key_pem, master_key)
        assert encrypted != key_pem
        assert b"BEGIN" not in encrypted

        decrypted = engine.decrypt_key_blob(encrypted, master_key)
        assert decrypted == key_pem


class TestCSR:
    def test_generate_csr(self, engine, subject):
        key = engine.generate_keypair("RSA", 2048)
        san_list = [SANEntry(type="dns", value="test.com")]
        csr = engine.generate_csr(subject, san_list, key)

        assert csr.is_signature_valid
        cn = csr.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
        assert cn == "test.example.com"

    def test_verify_csr(self, engine, subject):
        key = engine.generate_keypair("RSA", 2048)
        csr = engine.generate_csr(subject, [], key)
        result = engine.verify_csr(csr)
        assert result["signature"] == "pass"
        assert result["cn_present"] == "pass"
        assert result["key_size"] == "pass"

    def test_export_csr_pem(self, engine, subject):
        key = engine.generate_keypair("RSA", 2048)
        csr = engine.generate_csr(subject, [], key)
        pem = engine.export_csr_pem(csr)
        assert b"BEGIN CERTIFICATE REQUEST" in pem
