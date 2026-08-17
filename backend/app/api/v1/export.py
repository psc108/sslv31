"""Export endpoints — download certificates in PEM, DER, P7B, P12, JKS, bundle ZIP.

Supports chain_mode (full, no_root, intermediates_only, leaf_only) and
platform-specific bundle exports (linux, windows, java, macos, all).
"""

import io
import json
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from cryptography import x509 as cx509
from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding
from cryptography.hazmat.primitives.serialization.pkcs7 import serialize_certificates

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key
from app.models.certificate import Certificate
from app.models.ca import CertificateAuthority
from app.services.crypto_engine import CryptoEngine
from app.services.chain_builder import build_chain, assemble_chain_pem, get_root_pem, validate_chain
from app.services.keytool_wrapper import KeytoolWrapper, KeytoolError
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/export", tags=["Export"])
crypto = CryptoEngine()
keytool = KeytoolWrapper()

SUPPORTED_FORMATS = ("pem", "der", "chain", "key", "p12", "pfx", "p7b", "jks", "bundle")
CHAIN_MODES = ("full", "no_root", "intermediates_only", "leaf_only")


async def _get_cert(serial: str, db: AsyncSession) -> Certificate:
    result = await db.execute(select(Certificate).where(Certificate.serial == serial))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return cert


async def _get_ca_chain(cert_record: Certificate, db: AsyncSession) -> list[str]:
    """Build full CA chain for a certificate."""
    if cert_record.signing_ca_id:
        return await build_chain(cert_record.signing_ca_id, db)
    return []


@router.get("/validate-chain/{serial}")
async def validate_certificate_chain(
    serial: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Validate the stored certificate chain is cryptographically correct."""
    cert_record = await _get_cert(serial, db)
    ca_chain = await _get_ca_chain(cert_record, db)
    all_pems = [cert_record.cert_pem] + ca_chain
    result = validate_chain(all_pems)
    result["chain_length"] = len(all_pems)
    return result


def _parse_chain_certs(chain_pem: str) -> list[cx509.Certificate]:
    """Parse all certificates from a PEM chain string."""
    certs = []
    remaining = chain_pem.encode()
    while b"-----BEGIN CERTIFICATE-----" in remaining:
        try:
            cert = cx509.load_pem_x509_certificate(remaining)
            certs.append(cert)
            end_marker = b"-----END CERTIFICATE-----"
            idx = remaining.find(end_marker)
            if idx >= 0:
                remaining = remaining[idx + len(end_marker):]
            else:
                break
        except Exception:
            break
    return certs


def _cn_filename(cert_record: Certificate) -> str:
    subject = json.loads(cert_record.subject_json)
    return subject.get("cn", "certificate").replace(" ", "_").replace("*", "wildcard")


@router.get("/{serial}/{fmt}")
async def export_certificate(
    serial: str,
    fmt: str,
    request: Request,
    chain_mode: str = Query("full", pattern="^(full|no_root|intermediates_only|leaf_only)$"),
    platform: str = Query("all", pattern="^(linux|windows|java|macos|all)$"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> Response:
    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=422, detail=f"Unsupported format: {fmt}. Supported: {', '.join(SUPPORTED_FORMATS)}")

    cert_record = await _get_cert(serial, db)
    cn = _cn_filename(cert_record)

    # Audit
    severity = "WARNING" if fmt in ("key", "p12", "pfx", "jks", "bundle") else "INFO"
    await audit_event(
        db=db, event_type="CERT_DOWNLOAD", severity=severity, request=request,
        subject_type="cert", subject_id=serial,
        detail={"format": fmt, "chain_mode": chain_mode, "platform": platform},
    )
    await db.commit()

    # Build CA chain
    ca_chain = await _get_ca_chain(cert_record, db)

    if fmt == "pem":
        return Response(
            content=cert_record.cert_pem.encode(),
            media_type="application/x-pem-file",
            headers={"Content-Disposition": f'attachment; filename="{cn}-cert.pem"'},
        )

    elif fmt == "der":
        cert_obj = cx509.load_pem_x509_certificate(cert_record.cert_pem.encode())
        return Response(
            content=crypto.export_der(cert_obj),
            media_type="application/x-x509-ca-cert",
            headers={"Content-Disposition": f'attachment; filename="{cn}-cert.cer"'},
        )

    elif fmt == "chain":
        chain_pem = assemble_chain_pem(cert_record.cert_pem, ca_chain, mode=chain_mode)
        suffix = f"-chain-{chain_mode}" if chain_mode != "full" else "-chain"
        return Response(
            content=chain_pem.encode(),
            media_type="application/x-pem-file",
            headers={"Content-Disposition": f'attachment; filename="{cn}{suffix}.pem"'},
        )

    elif fmt == "key":
        key_pem = crypto.decrypt_key_blob(cert_record.key_blob, settings.CERT_MASTER_KEY)
        return Response(
            content=key_pem,
            media_type="application/x-pem-file",
            headers={"Content-Disposition": f'attachment; filename="{cn}-key.pem"'},
        )

    elif fmt in ("p12", "pfx"):
        key_pem = crypto.decrypt_key_blob(cert_record.key_blob, settings.CERT_MASTER_KEY)
        key = load_pem_private_key(key_pem, password=None)
        cert_obj = cx509.load_pem_x509_certificate(cert_record.cert_pem.encode())

        # Parse chain certs (all CA certs)
        chain_certs = [cx509.load_pem_x509_certificate(pem.encode()) for pem in ca_chain]

        p12_bytes = crypto.export_pkcs12(
            cert=cert_obj, key=key, chain=chain_certs or None, friendly_name=cn,
        )
        ext = "pfx" if fmt == "pfx" else "p12"
        return Response(
            content=p12_bytes,
            media_type="application/x-pkcs12",
            headers={"Content-Disposition": f'attachment; filename="{cn}.{ext}"'},
        )

    elif fmt == "p7b":
        # PKCS#7 chain (no private key) — Windows native format
        cert_obj = cx509.load_pem_x509_certificate(cert_record.cert_pem.encode())
        all_certs = [cert_obj] + [cx509.load_pem_x509_certificate(pem.encode()) for pem in ca_chain]
        p7b_bytes = serialize_certificates(all_certs, Encoding.DER)
        return Response(
            content=p7b_bytes,
            media_type="application/x-pkcs7-certificates",
            headers={"Content-Disposition": f'attachment; filename="{cn}-chain.p7b"'},
        )

    elif fmt == "jks":
        if not keytool.available:
            raise HTTPException(status_code=503, detail="keytool not available — install JDK 17")

        key_pem = crypto.decrypt_key_blob(cert_record.key_blob, settings.CERT_MASTER_KEY)
        chain_pem_bytes = "".join(ca_chain).encode()

        try:
            jks_bytes = keytool.create_keystore(
                cert_pem=cert_record.cert_pem.encode(),
                key_pem=key_pem,
                chain_pem=chain_pem_bytes,
                password="changeit123!",
                alias=cn,
            )
        except KeytoolError as e:
            raise HTTPException(status_code=500, detail=str(e))

        return Response(
            content=jks_bytes,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{cn}-keystore.jks"'},
        )

    elif fmt == "bundle":
        return await _export_bundle(cert_record, ca_chain, cn, platform, db)

    raise HTTPException(status_code=422, detail=f"Unsupported format: {fmt}")


async def _export_bundle(
    cert_record: Certificate,
    ca_chain: list[str],
    cn: str,
    platform: str,
    db: AsyncSession,
) -> Response:
    """Generate platform-structured ZIP bundle."""
    key_pem = crypto.decrypt_key_blob(cert_record.key_blob, settings.CERT_MASTER_KEY)
    cert_obj = cx509.load_pem_x509_certificate(cert_record.cert_pem.encode())
    root_pem = get_root_pem(ca_chain)
    intermediates_pem = "".join(ca_chain[:-1]) if len(ca_chain) > 1 else ""
    chain_full = assemble_chain_pem(cert_record.cert_pem, ca_chain, "full")
    chain_no_root = assemble_chain_pem(cert_record.cert_pem, ca_chain, "no_root")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if platform in ("linux", "all"):
            zf.writestr("linux/cert.pem", cert_record.cert_pem)
            zf.writestr("linux/key.pem", key_pem)
            zf.writestr("linux/chain-full.pem", chain_full)
            zf.writestr("linux/chain-no-root.pem", chain_no_root)
            if intermediates_pem:
                zf.writestr("linux/intermediates.pem", intermediates_pem)
            if root_pem:
                zf.writestr("linux/root-ca.pem", root_pem)
            zf.writestr("linux/trust-import.sh", _linux_trust_script(cn))

        if platform in ("windows", "all"):
            # PFX with full chain
            key_obj = load_pem_private_key(key_pem, password=None)
            chain_certs = [cx509.load_pem_x509_certificate(p.encode()) for p in ca_chain]
            pfx = crypto.export_pkcs12(cert=cert_obj, key=key_obj, chain=chain_certs or None, friendly_name=cn)
            zf.writestr("windows/cert-with-key.pfx", pfx)

            # P7B chain
            all_certs = [cert_obj] + chain_certs
            p7b = serialize_certificates(all_certs, Encoding.DER)
            zf.writestr("windows/cert-chain.p7b", p7b)

            # Root CA DER
            if root_pem:
                root_obj = cx509.load_pem_x509_certificate(root_pem.encode())
                zf.writestr("windows/root-ca.cer", crypto.export_der(root_obj))

            # Intermediates P7B
            if intermediates_pem:
                int_certs = [cx509.load_pem_x509_certificate(p.encode()) for p in ca_chain[:-1]]
                if int_certs:
                    zf.writestr("windows/intermediates.p7b", serialize_certificates(int_certs, Encoding.DER))

            zf.writestr("windows/trust-import.ps1", _windows_ps_script(cn))
            zf.writestr("windows/trust-import.bat", _windows_bat_script(cn))

        if platform in ("java", "all"):
            # PKCS#12 keystore
            key_obj = load_pem_private_key(key_pem, password=None)
            chain_certs = [cx509.load_pem_x509_certificate(p.encode()) for p in ca_chain]
            p12 = crypto.export_pkcs12(cert=cert_obj, key=key_obj, chain=chain_certs or None, friendly_name=cn)
            zf.writestr("java/keystore.p12", p12)

            # JKS if keytool available
            if keytool.available:
                try:
                    jks = keytool.create_keystore(
                        cert_pem=cert_record.cert_pem.encode(),
                        key_pem=key_pem,
                        chain_pem="".join(ca_chain).encode(),
                        password="changeit123!",
                        alias=cn,
                    )
                    zf.writestr("java/keystore.jks", jks)
                except KeytoolError:
                    pass

                # Truststore (CA certs only)
                if ca_chain:
                    try:
                        ca_entries = [(f"ca-{i}", p.encode()) for i, p in enumerate(ca_chain)]
                        ts = keytool.create_truststore(ca_entries, "changeit123!", "JKS")
                        zf.writestr("java/truststore.jks", ts)
                    except KeytoolError:
                        pass

            zf.writestr("java/spring-boot.properties", _spring_boot_config(cn))
            zf.writestr("java/java-opts.txt", _java_opts(cn))

        if platform in ("macos", "all"):
            key_obj = load_pem_private_key(key_pem, password=None)
            chain_certs = [cx509.load_pem_x509_certificate(p.encode()) for p in ca_chain]
            p12 = crypto.export_pkcs12(cert=cert_obj, key=key_obj, chain=chain_certs or None, friendly_name=cn)
            zf.writestr("macos/cert-with-key.p12", p12)
            if root_pem:
                zf.writestr("macos/root-ca.pem", root_pem)
            zf.writestr("macos/trust-import.sh", _macos_trust_script(cn))

        zf.writestr("README.txt", _generate_readme(cn, cert_record, platform))

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{cn}-bundle.zip"'},
    )





# --- Platform trust scripts ---

def _linux_trust_script(cn: str) -> str:
    return f"""#!/bin/bash
# Trust import script for {cn}
# Supports Debian/Ubuntu, RHEL/CentOS, Alpine, Arch

set -e

if [ ! -f root-ca.pem ]; then
    echo "ERROR: root-ca.pem not found in current directory"
    exit 1
fi

# Detect distro
if [ -f /etc/debian_version ]; then
    echo "Detected: Debian/Ubuntu"
    sudo cp root-ca.pem /usr/local/share/ca-certificates/{cn}-root-ca.crt
    sudo update-ca-certificates
elif [ -f /etc/redhat-release ]; then
    echo "Detected: RHEL/CentOS"
    sudo cp root-ca.pem /etc/pki/ca-trust/source/anchors/{cn}-root-ca.pem
    sudo update-ca-trust extract
elif [ -f /etc/alpine-release ]; then
    echo "Detected: Alpine"
    sudo cp root-ca.pem /usr/local/share/ca-certificates/{cn}-root-ca.crt
    sudo update-ca-certificates
elif [ -f /etc/arch-release ]; then
    echo "Detected: Arch Linux"
    sudo cp root-ca.pem /etc/ca-certificates/trust-source/anchors/{cn}-root-ca.crt
    sudo trust extract-compat
else
    echo "Unknown distro — copy root-ca.pem to your system trust store manually"
    exit 1
fi

echo "Root CA imported successfully. Verify with:"
echo "  openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt cert.pem"
"""


def _windows_ps_script(cn: str) -> str:
    return f"""# PowerShell trust import script for {cn}
# Run as Administrator

$ErrorActionPreference = "Stop"

# Import root CA to machine trust store
if (Test-Path "root-ca.cer") {{
    Import-Certificate -FilePath .\\root-ca.cer -CertStoreLocation Cert:\\LocalMachine\\Root
    Write-Host "Root CA imported to LocalMachine\\Root" -ForegroundColor Green
}}

# Import intermediates
if (Test-Path "intermediates.p7b") {{
    Import-Certificate -FilePath .\\intermediates.p7b -CertStoreLocation Cert:\\LocalMachine\\CA
    Write-Host "Intermediates imported to LocalMachine\\CA" -ForegroundColor Green
}}

# Import PFX (cert + key) to personal store
if (Test-Path "cert-with-key.pfx") {{
    $pwd = Read-Host "Enter PFX password (or press Enter for none)" -AsSecureString
    Import-PfxCertificate -FilePath .\\cert-with-key.pfx -CertStoreLocation Cert:\\LocalMachine\\My -Password $pwd
    Write-Host "Certificate + key imported to LocalMachine\\My" -ForegroundColor Green
}}

Write-Host "`nDone. Verify with: certutil -store Root | findstr `"{cn}`"" -ForegroundColor Cyan
"""


def _windows_bat_script(cn: str) -> str:
    return f"""@echo off
REM Trust import script for {cn}
REM Run as Administrator

echo Importing root CA...
if exist root-ca.cer (
    certutil -addstore Root root-ca.cer
    if %ERRORLEVEL% EQU 0 echo Root CA imported successfully.
)

echo Importing certificate chain...
if exist cert-chain.p7b (
    certutil -addstore CA cert-chain.p7b
    if %ERRORLEVEL% EQU 0 echo Chain imported successfully.
)

echo.
echo Done. Verify with: certutil -store Root
pause
"""


def _macos_trust_script(cn: str) -> str:
    return f"""#!/bin/bash
# macOS trust import script for {cn}

set -e

if [ ! -f root-ca.pem ]; then
    echo "ERROR: root-ca.pem not found"
    exit 1
fi

echo "Importing root CA to System Keychain (requires admin password)..."
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain root-ca.pem

echo "Root CA imported. Verify with:"
echo "  security find-certificate -c '{cn}' /Library/Keychains/System.keychain"

# Import P12 if present
if [ -f cert-with-key.p12 ]; then
    echo ""
    echo "To import the certificate + key to your login keychain:"
    echo "  security import cert-with-key.p12 -k ~/Library/Keychains/login.keychain-db"
fi
"""


def _spring_boot_config(cn: str) -> str:
    return f"""# Spring Boot SSL Configuration for {cn}
# Place keystore.p12 and truststore.jks in src/main/resources/

# Server SSL (for serving HTTPS)
server.ssl.enabled=true
server.ssl.key-store=classpath:keystore.p12
server.ssl.key-store-password=changeit123!
server.ssl.key-store-type=PKCS12
server.ssl.key-alias={cn}

# Client SSL (for outbound connections trusting internal CA)
# spring.ssl.bundle.jks.internal.keystore.location=classpath:keystore.p12
# spring.ssl.bundle.jks.internal.keystore.password=changeit123!
# spring.ssl.bundle.jks.internal.truststore.location=classpath:truststore.jks
# spring.ssl.bundle.jks.internal.truststore.password=changeit123!
"""


def _java_opts(cn: str) -> str:
    return f"""# JVM SSL/TLS Options for {cn}
# Add these to JAVA_OPTS or application startup

# Use custom truststore (trusts internal CA)
-Djavax.net.ssl.trustStore=/path/to/truststore.jks
-Djavax.net.ssl.trustStorePassword=changeit123!
-Djavax.net.ssl.trustStoreType=JKS

# Use custom keystore (for mTLS client auth)
-Djavax.net.ssl.keyStore=/path/to/keystore.p12
-Djavax.net.ssl.keyStorePassword=changeit123!
-Djavax.net.ssl.keyStoreType=PKCS12

# Enable SSL debug logging (remove in production)
-Djavax.net.debug=ssl:handshake:verbose

# Disable hostname verification (DEVELOPMENT ONLY — never in production)
# -Djdk.internal.httpclient.disableHostnameVerification=true
"""


def _generate_readme(cn: str, cert: Certificate, platform: str) -> str:
    subject = json.loads(cert.subject_json)
    sections = [f"""SSL Certificate Bundle — {cn}
{'=' * 50}

Generated by SSL Certificate Manager
Serial: {cert.serial}
Profile: {cert.profile}
Subject: CN={subject.get('cn', '')}
Platform: {platform}
"""]

    if platform in ("linux", "all"):
        sections.append("""
Linux Files (linux/):
  cert.pem            Leaf certificate
  key.pem             Private key — KEEP SECURE
  chain-full.pem      Leaf + intermediates + root
  chain-no-root.pem   Leaf + intermediates (preferred for most servers)
  intermediates.pem   Intermediate CAs only (Apache SSLCertificateChainFile)
  root-ca.pem         Root CA certificate
  trust-import.sh     Auto-detect distro and import root CA

Nginx:
  ssl_certificate     /path/to/chain-no-root.pem;
  ssl_certificate_key /path/to/key.pem;

Apache:
  SSLCertificateFile    /path/to/cert.pem
  SSLCertificateKeyFile /path/to/key.pem
  SSLCertificateChainFile /path/to/intermediates.pem
""")

    if platform in ("windows", "all"):
        sections.append("""
Windows Files (windows/):
  cert-with-key.pfx   PKCS#12 — cert + key + chain (IIS, .NET)
  cert-chain.p7b      PKCS#7 chain (MMC import, certutil)
  root-ca.cer         Root CA in DER (double-click to install)
  intermediates.p7b   Intermediate CAs in PKCS#7
  trust-import.ps1    PowerShell import script (run as Admin)
  trust-import.bat    Batch import script (run as Admin)

IIS Binding:
  1. Import cert-with-key.pfx via IIS Manager → Server Certificates
  2. Bind to site → HTTPS → select imported certificate
""")

    if platform in ("java", "all"):
        sections.append("""
Java Files (java/):
  keystore.p12            PKCS#12 keystore (cert + key + chain)
  keystore.jks            JKS keystore (if keytool available)
  truststore.jks          TrustStore (CA certs only)
  spring-boot.properties  Spring Boot configuration snippet
  java-opts.txt           JVM arguments for SSL

Tomcat:
  <Connector port="8443" protocol="org.apache.coyote.http11.Http11NioProtocol"
    SSLEnabled="true" scheme="https" secure="true"
    keystoreFile="/path/to/keystore.p12"
    keystorePass="changeit123!" keystoreType="PKCS12" />
""")

    if platform in ("macos", "all"):
        sections.append("""
macOS Files (macos/):
  cert-with-key.p12   PKCS#12 (Keychain import)
  root-ca.pem         Root CA for trust import
  trust-import.sh     Import to System Keychain (requires sudo)
""")

    sections.append("""
Verification:
  openssl x509 -in linux/cert.pem -text -noout
  openssl verify -CAfile linux/root-ca.pem -untrusted linux/intermediates.pem linux/cert.pem
  openssl s_client -connect host:443 -CAfile linux/root-ca.pem
""")

    return "\n".join(sections)
