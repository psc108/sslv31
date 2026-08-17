"""Backup engine — encrypted backup/restore of the certificate database and CA material."""

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
import logging
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from sqlalchemy.engine import make_url

from app.core.config import settings

logger = logging.getLogger(__name__)

BACKUP_SALT = b"certmanager-backup-v1"
MYSQL_DUMP_ARCNAME = "mysql-dump.sql"


def _mysql_conn_parts() -> dict:
    url = make_url(settings.db_url)
    return {
        "host": url.host or "localhost",
        "port": str(url.port or 3306),
        "user": url.username or "",
        "password": url.password or "",
        "database": url.database or "",
    }


def _mysqldump() -> bytes:
    """Dump the remote MySQL database via the mysqldump CLI (mysql-client package)."""
    parts = _mysql_conn_parts()
    cmd = [
        "mysqldump",
        f"--host={parts['host']}",
        f"--port={parts['port']}",
        f"--user={parts['user']}",
        "--single-transaction",
        "--routines",
        parts["database"],
    ]
    env = os.environ.copy()
    env["MYSQL_PWD"] = parts["password"]
    result = subprocess.run(cmd, capture_output=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"mysqldump failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def _mysql_restore(dump_sql: bytes) -> None:
    """Restore a mysqldump SQL script into the configured MySQL database.

    mysqldump's output includes DROP TABLE IF EXISTS before each CREATE TABLE,
    so this is self-contained and overwrites existing tables in place.
    """
    parts = _mysql_conn_parts()
    cmd = [
        "mysql",
        f"--host={parts['host']}",
        f"--port={parts['port']}",
        f"--user={parts['user']}",
        parts["database"],
    ]
    env = os.environ.copy()
    env["MYSQL_PWD"] = parts["password"]
    result = subprocess.run(cmd, input=dump_sql, capture_output=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"mysql restore failed: {result.stderr.decode(errors='replace').strip()}")


def _derive_backup_key(master_key: str) -> bytes:
    """Derive a separate AES-256 key from master key using HKDF."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=BACKUP_SALT,
        info=b"backup-encryption",
    )
    return hkdf.derive(master_key.encode())


def _encrypt_archive(data: bytes, master_key: str) -> bytes:
    """Encrypt backup data with AES-256-GCM."""
    key = _derive_backup_key(master_key)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext


def _decrypt_archive(encrypted: bytes, master_key: str) -> bytes:
    """Decrypt backup data."""
    key = _derive_backup_key(master_key)
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def create_backup() -> tuple[str, int, str]:
    """Create an encrypted backup archive.

    Returns: (filename, size_bytes, sha256_checksum)
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"backup-{timestamp}.enc"
    backup_path = settings.BACKUP_DIR / filename

    settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Build tar archive in memory
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if settings.is_mysql:
            dump = _mysqldump()
            info = tarfile.TarInfo(name=MYSQL_DUMP_ARCNAME)
            info.size = len(dump)
            tar.addfile(info, io.BytesIO(dump))
        elif not settings.is_postgres:
            # SQLite database (checkpoint WAL first if exists)
            db_path = settings.db_path
            if db_path.exists():
                tar.add(str(db_path), arcname="certmanager.db")
                # Also include WAL and SHM if present
                wal_path = Path(str(db_path) + "-wal")
                shm_path = Path(str(db_path) + "-shm")
                if wal_path.exists():
                    tar.add(str(wal_path), arcname="certmanager.db-wal")
                if shm_path.exists():
                    tar.add(str(shm_path), arcname="certmanager.db-shm")
        # PostgreSQL: not implemented — pre-existing gap, unrelated to this change

        # Self-cert directory
        self_dir = settings.self_cert_dir
        if self_dir.exists():
            for f in self_dir.iterdir():
                tar.add(str(f), arcname=f"self/{f.name}")

    # Encrypt
    plain_data = buf.getvalue()
    encrypted = _encrypt_archive(plain_data, settings.CERT_MASTER_KEY)

    # Write encrypted archive
    backup_path.write_bytes(encrypted)

    # SHA-256 checksum
    checksum = hashlib.sha256(encrypted).hexdigest()
    checksum_path = backup_path.with_suffix(".enc.sha256")
    checksum_path.write_text(f"{checksum}  {filename}\n")

    size = len(encrypted)
    logger.info(f"Backup created: {filename} ({size} bytes, sha256={checksum[:16]}...)")

    # Purge old backups
    _purge_old_backups()

    return filename, size, checksum


def _purge_old_backups() -> None:
    """Remove oldest backups exceeding BACKUP_RETAIN_COUNT."""
    backups = sorted(
        settings.BACKUP_DIR.glob("backup-*.enc"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    retain = settings.BACKUP_RETAIN_COUNT
    for old_backup in backups[retain:]:
        old_backup.unlink(missing_ok=True)
        checksum_file = old_backup.with_suffix(".enc.sha256")
        checksum_file.unlink(missing_ok=True)
        logger.info(f"Purged old backup: {old_backup.name}")


def list_backups() -> list[dict]:
    """List available backup archives with metadata."""
    backups = []
    for f in sorted(settings.BACKUP_DIR.glob("backup-*.enc"), reverse=True):
        stat = f.stat()
        checksum_file = f.with_suffix(".enc.sha256")
        checksum = ""
        if checksum_file.exists():
            checksum = checksum_file.read_text().split()[0]
        backups.append({
            "filename": f.name,
            "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "sha256": checksum,
        })
    return backups


def verify_backup(filepath: Path) -> dict:
    """Verify a backup archive is valid and restorable without restoring.

    Returns metadata about the backup contents.
    """
    if not filepath.exists():
        raise FileNotFoundError(f"Backup file not found: {filepath}")

    encrypted = filepath.read_bytes()

    # Verify checksum if available
    checksum_file = filepath.with_suffix(".enc.sha256")
    if checksum_file.exists():
        expected = checksum_file.read_text().split()[0]
        actual = hashlib.sha256(encrypted).hexdigest()
        if actual != expected:
            raise ValueError(f"Checksum mismatch: expected {expected}, got {actual}")

    # Decrypt
    try:
        plain_data = _decrypt_archive(encrypted, settings.CERT_MASTER_KEY)
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}")

    # Inspect tar contents
    buf = io.BytesIO(plain_data)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        members = tar.getnames()

    return {
        "valid": True,
        "filename": filepath.name,
        "size": len(encrypted),
        "files": members,
        "has_database": "certmanager.db" in members or MYSQL_DUMP_ARCNAME in members,
        "has_self_certs": any(m.startswith("self/") for m in members),
    }


def restore_backup(filepath: Path, force: bool = False) -> dict:
    """Restore from an encrypted backup archive.

    WARNING: This overwrites the current database and self-certs.
    """
    if not filepath.exists():
        raise FileNotFoundError(f"Backup file not found: {filepath}")

    # Verify first
    info = verify_backup(filepath)

    # Create a safety backup of current state before overwriting it
    logger.info("Creating safety backup before restore")
    create_backup()

    # Decrypt
    encrypted = filepath.read_bytes()
    plain_data = _decrypt_archive(encrypted, settings.CERT_MASTER_KEY)

    # Extract
    buf = io.BytesIO(plain_data)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        # Extract database
        if settings.is_mysql and MYSQL_DUMP_ARCNAME in info["files"]:
            dump_file = tar.extractfile(tar.getmember(MYSQL_DUMP_ARCNAME))
            if dump_file:
                _mysql_restore(dump_file.read())
                logger.info("MySQL database restored")
        elif "certmanager.db" in info["files"]:
            db_member = tar.getmember("certmanager.db")
            db_file = tar.extractfile(db_member)
            if db_file:
                settings.db_path.write_bytes(db_file.read())
                logger.info("Database restored")

        # Extract self-certs
        if info["has_self_certs"]:
            settings.self_cert_dir.mkdir(parents=True, exist_ok=True)
            for member in tar.getmembers():
                if member.name.startswith("self/") and member.isfile():
                    extracted = tar.extractfile(member)
                    if extracted:
                        dest = settings.self_cert_dir / Path(member.name).name
                        dest.write_bytes(extracted.read())
            logger.info("Self-certificates restored")

    return {
        "status": "restored",
        "source": filepath.name,
        "files_restored": info["files"],
    }
