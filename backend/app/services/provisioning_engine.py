"""
Environment Provisioning Engine.

Orchestrates CA creation, certificate issuance, key encryption,
keystore/truststore generation, config snippet rendering, and ZIP assembly
for a complete SSP environment SSL bundle.
"""

import io
import ipaddress
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12 as _pkcs12
from jinja2 import Environment, FileSystemLoader

from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry
from app.services.jasypt_engine import encrypt as jasypt_encrypt, wrap_enc


TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "provisioning"

# Cipher profile definitions
CIPHER_PROFILES = {
    "modern": {
        "label": "Modern (TLS 1.3 only)",
        "description": "Best security. Requires Java 11+, OpenSSL 1.1.1+.",
        "protocols": "TLSv1.3",
        "ciphers": "TLS_AES_256_GCM_SHA384,TLS_AES_128_GCM_SHA256,TLS_CHACHA20_POLY1305_SHA256",
        "openssl_ciphers": "TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256:TLS_CHACHA20_POLY1305_SHA256",
    },
    "intermediate": {
        "label": "Intermediate (TLS 1.2 + 1.3)",
        "description": "Recommended. Supports Java 8u292+, OpenSSL 1.0.2+.",
        "protocols": "TLSv1.2,TLSv1.3",
        "ciphers": "TLS_AES_256_GCM_SHA384,TLS_AES_128_GCM_SHA256,TLS_CHACHA20_POLY1305_SHA256,ECDHE-ECDSA-AES256-GCM-SHA384,ECDHE-RSA-AES256-GCM-SHA384,ECDHE-ECDSA-AES128-GCM-SHA256,ECDHE-RSA-AES128-GCM-SHA256,DHE-RSA-AES256-GCM-SHA384,DHE-RSA-AES128-GCM-SHA256",
        "openssl_ciphers": "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256",
    },
    "legacy": {
        "label": "Legacy (TLS 1.1 + 1.2 + 1.3)",
        "description": "Weak security. Only if required by Java 7 or very old clients.",
        "protocols": "TLSv1.1,TLSv1.2,TLSv1.3",
        "ciphers": "TLS_AES_256_GCM_SHA384,TLS_AES_128_GCM_SHA256,TLS_CHACHA20_POLY1305_SHA256,ECDHE-ECDSA-AES256-GCM-SHA384,ECDHE-RSA-AES256-GCM-SHA384,ECDHE-ECDSA-AES128-GCM-SHA256,ECDHE-RSA-AES128-GCM-SHA256,DHE-RSA-AES256-GCM-SHA384,DHE-RSA-AES128-GCM-SHA256,ECDHE-RSA-AES256-SHA384,ECDHE-RSA-AES128-SHA256,AES256-GCM-SHA384,AES128-GCM-SHA256,AES256-SHA256",
        "openssl_ciphers": "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-SHA384:AES256-GCM-SHA384:AES128-GCM-SHA256:AES256-SHA256",
    },
}


@dataclass
class HostConfig:
    role: str  # mysql, rabbitmq, keystone, backend, frontend
    fqdn: str
    ip: str


@dataclass
class ProvisioningRequest:
    env_name: str
    hosts: list[HostConfig]
    ssl_passphrase: str
    encryption_key: str
    key_algo: str = "RSA"
    key_size: int = 2048
    ca_validity_days: int = 3650
    cert_validity_days: int = 365
    cipher_profile: str = "intermediate"
    base_path: str = "/opt/scripts/ssl"
    include_nopass: bool = True
    include_snippets: bool = True
    include_scripts: bool = True
    include_readmes: bool = True
    include_quicksetup: bool = True


@dataclass
class GeneratedCert:
    role: str
    cert_type: str  # server or client
    cert_pem: bytes
    key_pem_encrypted: bytes
    key_pem_nopass: bytes
    cert_obj: x509.Certificate
    key_obj: object


@dataclass
class ProvisioningResult:
    zip_bytes: bytes
    ca_id: str
    cert_count: int
    keystore_count: int


class ProvisioningEngine:
    """Generates a complete SSL bundle for an SSP environment."""

    def __init__(self):
        self.crypto = CryptoEngine()
        self._jinja = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            keep_trailing_newline=True,
        )

    def generate(self, req: ProvisioningRequest) -> ProvisioningResult:
        """Main entry point — generates everything and returns ZIP bytes."""
        # 1. Create CA
        ca_key, ca_cert = self._create_ca(req)
        ca_pem = self.crypto.export_cert_pem(ca_cert)
        ca_der = self.crypto.export_der(ca_cert)

        # 2. Issue certificates
        certs = self._issue_all_certs(req, ca_key, ca_cert)

        # 3. Build keystores/truststores
        stores = self._build_stores(req, certs, ca_cert)

        # 4. Compute Jasypt encrypted values
        enc_ssl_pass = wrap_enc(jasypt_encrypt(req.ssl_passphrase, req.encryption_key))

        # 5. Render config snippets
        cipher = CIPHER_PROFILES.get(req.cipher_profile, CIPHER_PROFILES["intermediate"])
        template_ctx = self._build_template_context(req, enc_ssl_pass, cipher)

        # 6. Assemble ZIP
        zip_bytes = self._assemble_zip(req, ca_pem, ca_der, certs, stores, template_ctx, cipher)

        return ProvisioningResult(
            zip_bytes=zip_bytes,
            ca_id="provisioned",
            cert_count=len(certs),
            keystore_count=len(stores),
        )

    def _create_ca(self, req: ProvisioningRequest):
        """Create a dedicated CA for this environment."""
        ca_key = self.crypto.generate_keypair(req.key_algo, req.key_size)
        ca_subject = SubjectInfo(cn=f"{req.env_name} Internal CA")
        ca_cert = self.crypto.create_root_ca(
            subject=ca_subject,
            key=ca_key,
            validity_days=req.ca_validity_days,
            path_length=0,
        )
        return ca_key, ca_cert

    def _issue_all_certs(self, req: ProvisioningRequest, ca_key, ca_cert) -> list[GeneratedCert]:
        """Issue all server and client certificates."""
        certs: list[GeneratedCert] = []
        hosts_by_role = {h.role: h for h in req.hosts}

        # Server certs for all 5 machines
        for role in ("mysql", "rabbitmq", "keystone", "backend", "frontend"):
            host = hosts_by_role.get(role)
            if not host:
                continue
            cert = self._issue_cert(req, ca_key, ca_cert, host, "server")
            certs.append(cert)

        # Client certs for backend and frontend only
        for role in ("backend", "frontend"):
            host = hosts_by_role.get(role)
            if not host:
                continue
            cert = self._issue_cert(req, ca_key, ca_cert, host, "client")
            certs.append(cert)

        return certs

    def _issue_cert(self, req: ProvisioningRequest, ca_key, ca_cert, host: HostConfig, cert_type: str) -> GeneratedCert:
        """Issue a single certificate."""
        key = self.crypto.generate_keypair(req.key_algo, req.key_size)

        cn = f"{host.fqdn}" if cert_type == "server" else f"{host.role}-client.{host.fqdn}"
        subject = SubjectInfo(cn=cn)

        # SANs: FQDN + IP + localhost + 127.0.0.1
        san_list = [
            SANEntry(type="dns", value=host.fqdn),
            SANEntry(type="ip", value=host.ip),
            SANEntry(type="dns", value="localhost"),
            SANEntry(type="ip", value="127.0.0.1"),
        ]

        profile = "server" if cert_type == "server" else "client"
        cert_obj = self.crypto.issue_certificate(
            profile=profile,
            subject=subject,
            san_list=san_list,
            key=key,
            signing_ca_key=ca_key,
            signing_ca_cert=ca_cert,
            validity_days=req.cert_validity_days,
        )

        # Export keys
        key_pem_encrypted = self.crypto.export_key_pem(key, passphrase=req.ssl_passphrase)
        key_pem_nopass = self.crypto.export_key_pem(key, passphrase=None)
        cert_pem = self.crypto.export_cert_pem(cert_obj)

        return GeneratedCert(
            role=host.role,
            cert_type=cert_type,
            cert_pem=cert_pem,
            key_pem_encrypted=key_pem_encrypted,
            key_pem_nopass=key_pem_nopass,
            cert_obj=cert_obj,
            key_obj=key,
        )

    def _build_stores(self, req: ProvisioningRequest, certs: list[GeneratedCert], ca_cert) -> dict[str, bytes]:
        """Build PKCS#12 keystores and truststores."""
        stores: dict[str, bytes] = {}
        pwd = req.ssl_passphrase.encode()

        # Truststore (same for all machines — just the CA cert)
        truststore = _pkcs12.serialize_key_and_certificates(
            b"ca",
            None,
            None,
            [ca_cert],
            serialization.NoEncryption(),
        )
        # Actually, PKCS#12 without a key needs a different approach
        # Use serialize_key_and_certificates with a dummy approach — or just the CA cert
        # The proper way for a truststore is to include CA as additional cert
        # We'll use keytool-style: create a PKCS12 with just the CA cert
        truststore = self._build_truststore_p12(ca_cert, pwd)

        for cert in certs:
            role = cert.role
            prefix = f"{role}/{cert.cert_type}"
            # Keystore: cert + key
            keystore = self.crypto.export_pkcs12(
                cert=cert.cert_obj,
                key=cert.key_obj,
                chain=[ca_cert],
                password=req.ssl_passphrase,
                friendly_name=cert.cert_type,
            )
            stores[f"{role}/{cert.cert_type}-keystore.p12"] = keystore

        # One truststore per machine
        for role in ("mysql", "rabbitmq", "keystone", "backend", "frontend"):
            stores[f"{role}/truststore.p12"] = truststore

        return stores

    def _build_truststore_p12(self, ca_cert: x509.Certificate, password: bytes) -> bytes:
        """Build a PKCS#12 truststore containing only the CA certificate."""
        # PKCS#12 with no private key, just the CA cert as a trusted cert
        return _pkcs12.serialize_key_and_certificates(
            b"ca",
            None,
            ca_cert,
            None,
            serialization.BestAvailableEncryption(password),
        )

    def _build_template_context(self, req: ProvisioningRequest, enc_ssl_pass: str, cipher: dict) -> dict:
        """Build the Jinja2 template context."""
        hosts_by_role = {h.role: h for h in req.hosts}
        return {
            "env_name": req.env_name,
            "base_path": req.base_path,
            "ssl_passphrase": req.ssl_passphrase,
            "enc_ssl_passphrase": enc_ssl_pass,
            "encryption_key": req.encryption_key,
            "cipher_profile": req.cipher_profile,
            "cipher": cipher,
            "hosts": hosts_by_role,
            "ca_validity_days": req.ca_validity_days,
            "cert_validity_days": req.cert_validity_days,
            "key_algo": req.key_algo,
            "key_size": req.key_size,
        }

    def _assemble_zip(self, req: ProvisioningRequest, ca_pem: bytes, ca_der: bytes,
                      certs: list[GeneratedCert], stores: dict[str, bytes],
                      ctx: dict, cipher: dict) -> bytes:
        """Assemble the final ZIP bundle."""
        buf = io.BytesIO()
        prefix = f"{req.env_name}-ssl"

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # CA directory
            zf.writestr(f"{prefix}/ca/ca.pem", ca_pem)
            zf.writestr(f"{prefix}/ca/ca.der", ca_der)

            # Per-machine certs
            for cert in certs:
                role = cert.role
                ct = cert.cert_type
                base = f"{prefix}/{role}/certs"
                zf.writestr(f"{base}/{ct}-cert.pem", cert.cert_pem)
                zf.writestr(f"{base}/{ct}.key", cert.key_pem_encrypted)
                if req.include_nopass:
                    zf.writestr(f"{base}/{ct}.key.nopass", cert.key_pem_nopass)

            # CA cert in each machine's certs dir
            for role in ("mysql", "rabbitmq", "keystone", "backend", "frontend"):
                zf.writestr(f"{prefix}/{role}/certs/ca.pem", ca_pem)

            # Stores
            for path, data in stores.items():
                zf.writestr(f"{prefix}/{path.rsplit('/', 1)[0]}/stores/{path.rsplit('/', 1)[1]}", data)

            # Config snippets
            if req.include_snippets:
                self._write_snippets(zf, prefix, ctx)

            # Scripts
            if req.include_scripts:
                self._write_scripts(zf, prefix, ctx)

            # READMEs
            if req.include_readmes:
                self._write_readmes(zf, prefix, ctx)

            # quicksetup-ssl.properties
            if req.include_quicksetup:
                self._write_quicksetup(zf, prefix, ctx)

            # Deployment guide
            self._write_deployment_guide(zf, prefix, ctx)

        return buf.getvalue()

    def _render(self, template_name: str, ctx: dict) -> str:
        """Render a Jinja2 template, falling back to inline if file doesn't exist."""
        try:
            tmpl = self._jinja.get_template(template_name)
            return tmpl.render(**ctx)
        except Exception:
            return f"# Template '{template_name}' not yet available\n"

    def _write_snippets(self, zf: zipfile.ZipFile, prefix: str, ctx: dict):
        """Write config snippets for each service."""
        snippets = {
            "mysql": ("config/ssl.cnf.snippet", "mysql_ssl_cnf.j2"),
            "rabbitmq": ("config/rabbitmq-ssl.conf.snippet", "rabbitmq_ssl_conf.j2"),
            "keystone": ("config/apache-ssl.conf.snippet", "apache_keystone_ssl.j2"),
            "backend": ("config/application-ssl.yml.snippet", "spring_boot_ssl.j2"),
            "frontend": ("config/application-ssl.yml.snippet", "spring_boot_ssl.j2"),
        }
        for role, (out_path, tmpl_name) in snippets.items():
            role_ctx = {**ctx, "role": role}
            content = self._render(tmpl_name, role_ctx)
            zf.writestr(f"{prefix}/{role}/{out_path}", content)

    def _write_scripts(self, zf: zipfile.ZipFile, prefix: str, ctx: dict):
        """Write deployment and verification scripts."""
        zf.writestr(f"{prefix}/scripts/distribute-certs.sh", self._render("distribute_certs.j2", ctx))
        zf.writestr(f"{prefix}/scripts/verify-certs.sh", self._render("verify_certs.j2", ctx))

    def _write_readmes(self, zf: zipfile.ZipFile, prefix: str, ctx: dict):
        """Write per-machine README files."""
        for role in ("ca", "mysql", "rabbitmq", "keystone", "backend", "frontend"):
            role_ctx = {**ctx, "role": role}
            content = self._render("machine_readme.j2", role_ctx)
            zf.writestr(f"{prefix}/{role}/README.md", content)

    def _write_quicksetup(self, zf: zipfile.ZipFile, prefix: str, ctx: dict):
        """Write quicksetup-ssl.properties."""
        content = self._render("quicksetup_ssl.j2", ctx)
        zf.writestr(f"{prefix}/quicksetup-ssl.properties", content)

    def _write_deployment_guide(self, zf: zipfile.ZipFile, prefix: str, ctx: dict):
        """Write the deployment guide."""
        content = self._render("deployment_guide.j2", ctx)
        zf.writestr(f"{prefix}/DEPLOYMENT-GUIDE.md", content)
