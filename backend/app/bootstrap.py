"""Two-pass bootstrap for SSL Certificate Manager.

Pass 1 (--pass1): Generate root CA and Nginx listener certificate.
Pass 2 (--pass2): Run migrations, import root CA into DB, generate API key.
"""

import argparse
import os
import secrets
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.services.crypto_engine import CryptoEngine, SubjectInfo, SANEntry


def pass1() -> None:
    """Generate root CA and Nginx listener certificate."""
    master_key = os.environ.get("CERT_MASTER_KEY")
    if not master_key:
        print("ERROR: CERT_MASTER_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)

    crypto = CryptoEngine()
    self_dir = settings.self_cert_dir
    self_dir.mkdir(parents=True, exist_ok=True)

    # Check if already exists
    root_ca_path = self_dir / "root-ca.pem"
    if root_ca_path.exists():
        print("WARNING: root-ca.pem already exists. Overwriting.")

    # 1. Generate Root CA
    print(f"Generating Root CA: {settings.BOOTSTRAP_CA_CN}")
    ca_key = crypto.generate_keypair("RSA", 4096)
    ca_subject = SubjectInfo(cn=settings.BOOTSTRAP_CA_CN)
    ca_cert = crypto.create_root_ca(
        subject=ca_subject,
        key=ca_key,
        validity_days=settings.BOOTSTRAP_CA_DAYS,
        path_length=1,
    )

    # Write root CA
    ca_cert_pem = crypto.export_cert_pem(ca_cert)
    root_ca_path.write_bytes(ca_cert_pem)
    os.chmod(root_ca_path, 0o644)
    print(f"  Written: {root_ca_path}")

    # Write CA private key (encrypted at rest for pass2 import)
    ca_key_pem = crypto.export_key_pem(ca_key)
    ca_key_path = self_dir / "root-ca-key.pem"
    ca_key_path.write_bytes(ca_key_pem)
    os.chmod(ca_key_path, 0o600)
    print(f"  Written: {ca_key_path} (protect this file)")

    # Also write DER for Windows
    ca_der = crypto.export_der(ca_cert)
    der_path = self_dir / "root-ca.cer"
    der_path.write_bytes(ca_der)
    os.chmod(der_path, 0o644)

    # 2. Generate Nginx listener keypair
    print("Generating Nginx listener certificate...")
    listener_key = crypto.generate_keypair("RSA", 2048)

    # Build SAN list
    san_list: list[SANEntry] = []

    # Primary hostname from BASE_URL
    from urllib.parse import urlparse
    hostname = urlparse(settings.BASE_URL).hostname or "localhost"
    san_list.append(SANEntry(type="dns", value=hostname))

    # System hostname
    sys_hostname = socket.gethostname()
    if sys_hostname != hostname:
        san_list.append(SANEntry(type="dns", value=sys_hostname))

    # localhost
    san_list.append(SANEntry(type="dns", value="localhost"))

    # BOOTSTRAP_IP
    san_list.append(SANEntry(type="ip", value=settings.BOOTSTRAP_IP))
    if settings.BOOTSTRAP_IP != "127.0.0.1":
        san_list.append(SANEntry(type="ip", value="127.0.0.1"))

    # Extra SANs
    if settings.BOOTSTRAP_EXTRA_SANS:
        for extra in settings.BOOTSTRAP_EXTRA_SANS.split(","):
            extra = extra.strip()
            if extra:
                san_list.append(SANEntry(type="dns", value=extra))

    listener_subject = SubjectInfo(cn=hostname)
    listener_cert = crypto.issue_certificate(
        profile="server",
        subject=listener_subject,
        san_list=san_list,
        key=listener_key,
        signing_ca_key=ca_key,
        signing_ca_cert=ca_cert,
        validity_days=settings.BOOTSTRAP_CERT_DAYS,
    )

    # Write listener cert and key
    cert_path = self_dir / "server.pem"
    key_path = self_dir / "server-key.pem"

    cert_pem = crypto.export_cert_pem(listener_cert)
    key_pem = crypto.export_key_pem(listener_key)

    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)
    os.chmod(cert_path, 0o644)
    os.chmod(key_path, 0o600)

    print(f"  Written: {cert_path}")
    print(f"  Written: {key_path}")
    print(f"  SANs: {', '.join(s.value for s in san_list)}")
    print()
    print("Pass 1 complete. Reload Nginx, then run --pass2.")


def pass2() -> None:
    """Run migrations, import root CA into DB, generate API key."""
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    self_dir = settings.self_cert_dir
    root_ca_path = self_dir / "root-ca.pem"

    if not root_ca_path.exists():
        print("ERROR: root-ca.pem not found. Run --pass1 first.", file=sys.stderr)
        sys.exit(1)

    marker = settings.DATA_DIR / ".bootstrap_complete"
    if marker.exists():
        print("ERROR: Bootstrap already complete. Use --force to re-run.", file=sys.stderr)
        sys.exit(1)

    # Run Alembic migrations
    print("Running database migrations...")
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("  Migrations applied.")

    # Import root CA into database
    print("Importing bootstrap root CA into database...")

    async def _import_ca() -> None:
        import json
        from cryptography import x509

        engine = create_async_engine(settings.db_url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        ca_pem = root_ca_path.read_text()
        ca_cert = x509.load_pem_x509_certificate(ca_pem.encode())

        from app.models.ca import CertificateAuthority
        from app.services.crypto_engine import CryptoEngine

        crypto = CryptoEngine()

        # We don't store the CA private key in DB during bootstrap
        # (it would need the encrypted blob). Re-read and encrypt.
        # Actually for bootstrap, we need the key too.
        # The key is in server-key.pem? No — the CA key isn't saved to disk unencrypted.
        # We need to save it encrypted. Let's encrypt and store.

        # For bootstrap, we store a placeholder — the key is managed via pass1 regeneration
        # Actually, let's store it properly. We need the CA key for signing.
        # Re-generate approach won't work. We need to save the CA key in pass1.

        # Check if ca-key.pem exists (we should write it in pass1)
        ca_key_path = self_dir / "root-ca-key.pem"
        if ca_key_path.exists():
            ca_key_pem = ca_key_path.read_bytes()
            key_blob = crypto.encrypt_key_blob(ca_key_pem, settings.CERT_MASTER_KEY)
        else:
            print("  WARNING: root-ca-key.pem not found. CA will not be able to sign certificates.")
            key_blob = b""

        cn = ""
        for attr in ca_cert.subject:
            if attr.oid == x509.oid.NameOID.COMMON_NAME:
                cn = attr.value
                break

        ca_record = CertificateAuthority(
            cn=cn,
            subject_json=json.dumps({"cn": cn}),
            key_algo="RSA",
            key_size=4096,
            cert_pem=ca_pem,
            key_blob=key_blob,
            path_length=1,
            is_root=True,
            source="bootstrap",
            expires_at=ca_cert.not_valid_after_utc,
        )

        async with session_factory() as session:
            session.add(ca_record)
            await session.commit()

        await engine.dispose()
        print(f"  Root CA imported: {cn}")

    asyncio.run(_import_ca())

    # Generate API key
    api_key = secrets.token_urlsafe(32)
    print()
    print("=" * 60)
    print("  API KEY (save this immediately — shown only once):")
    print(f"  {api_key}")
    print("=" * 60)
    print()
    print("  Add to /etc/certmanager/certmanager.env:")
    print(f"  API_KEY={api_key}")
    print()

    # Write marker
    marker.write_text(datetime.now(timezone.utc).isoformat())
    print("Pass 2 complete. Bootstrap finished.")


def main() -> None:
    parser = argparse.ArgumentParser(description="SSL Certificate Manager Bootstrap")
    parser.add_argument("--pass1", action="store_true", help="Generate root CA and listener cert")
    parser.add_argument("--pass2", action="store_true", help="Run migrations and generate API key")
    parser.add_argument("--force", action="store_true", help="Force re-run even if complete")

    args = parser.parse_args()

    if args.force:
        marker = settings.DATA_DIR / ".bootstrap_complete"
        if marker.exists():
            marker.unlink()

    if args.pass1:
        pass1()
    elif args.pass2:
        pass2()
    else:
        print("Specify --pass1 or --pass2. See --help for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
