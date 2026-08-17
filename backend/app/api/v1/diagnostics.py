"""System diagnostics endpoint — live application state and environment info."""

import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key
from app.models.certificate import Certificate
from app.models.ca import CertificateAuthority

router = APIRouter(prefix="/api/v1/diagnostics", tags=["Diagnostics"])

_start_time = time.time()

# In-memory ring buffer for recent errors
_error_buffer: list[dict] = []
_ERROR_BUFFER_MAX = 200


def log_error(level: str, message: str, source: str = "", context: dict | None = None) -> None:
    """Add an error to the in-memory ring buffer. Call from anywhere in the app."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        "source": source,
        "context": context or {},
    }
    _error_buffer.append(entry)
    if len(_error_buffer) > _ERROR_BUFFER_MAX:
        _error_buffer.pop(0)


def _run_cmd(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=5)
        return result.stdout.decode().strip()
    except Exception:
        return "unavailable"


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 2)


@router.get("")
async def get_diagnostics(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    """Return full system diagnostics."""

    # System info
    system = {
        "os": f"{platform.system()} {platform.release()}",
        "os_pretty": _run_cmd(["lsb_release", "-ds"]) or f"{platform.system()} {platform.version()}",
        "python_version": platform.python_version(),
        "hostname": platform.node(),
        "uptime_seconds": int(time.time() - _start_time),
    }

    # Dependencies
    openssl_ver = _run_cmd(["openssl", "version"])
    java_ver = _run_cmd(["java", "-version"])
    if java_ver == "unavailable":
        java_ver = _run_cmd(["java", "--version"])

    keytool_path = shutil.which("keytool")
    if not keytool_path and settings.JDK_HOME:
        candidate = Path(settings.JDK_HOME) / "bin" / "keytool"
        if candidate.exists():
            keytool_path = str(candidate)

    dependencies = {
        "openssl_version": openssl_ver,
        "java_version": java_ver.split("\n")[0] if java_ver != "unavailable" else "not installed",
        "keytool_available": keytool_path is not None,
        "keytool_path": keytool_path or "not found",
    }

    # Configuration (non-secret)
    configuration = {
        "data_dir": str(settings.DATA_DIR),
        "backup_dir": str(settings.BACKUP_DIR),
        "log_level": settings.LOG_LEVEL,
        "max_cert_days": settings.MAX_CERT_DAYS,
        "backup_enabled": settings.BACKUP_ENABLED,
        "backup_interval_hours": settings.BACKUP_INTERVAL_HOURS,
        "backup_retain_count": settings.BACKUP_RETAIN_COUNT,
        "base_url": settings.BASE_URL,
        "expiry_scan_interval_hours": settings.EXPIRY_SCAN_INTERVAL_HOURS,
    }

    # Storage — db_size only meaningful for a local SQLite file
    if settings.is_postgres or settings.is_mysql:
        db_size = None
    else:
        db_path = settings.db_path
        db_size = round(db_path.stat().st_size / (1024 * 1024), 2) if db_path.exists() else 0

    disk_usage = shutil.disk_usage(str(settings.DATA_DIR)) if settings.DATA_DIR.exists() else None

    backup_files = list(settings.BACKUP_DIR.glob("backup-*.enc")) if settings.BACKUP_DIR.exists() else []
    last_backup = None
    if backup_files:
        newest = max(backup_files, key=lambda f: f.stat().st_mtime)
        last_backup = datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc).isoformat()

    storage = {
        "data_dir_size_mb": _dir_size_mb(settings.DATA_DIR),
        "data_dir_free_mb": round(disk_usage.free / (1024 * 1024), 0) if disk_usage else 0,
        "db_size_mb": db_size,
        "backup_count": len(backup_files),
        "last_backup": last_backup,
        "exports_size_mb": _dir_size_mb(settings.exports_dir),
    }

    # Certificate stats
    total_q = await db.execute(select(func.count()).select_from(Certificate))
    total = total_q.scalar() or 0

    valid_q = await db.execute(select(func.count()).where(Certificate.status == "valid"))
    valid = valid_q.scalar() or 0

    expired_q = await db.execute(select(func.count()).where(Certificate.status == "expired"))
    expired = expired_q.scalar() or 0

    revoked_q = await db.execute(select(func.count()).where(Certificate.status == "revoked"))
    revoked = revoked_q.scalar() or 0

    expiring_q = await db.execute(
        select(func.count()).where(Certificate.status == "valid", Certificate.expiry_warning == True)
    )
    expiring = expiring_q.scalar() or 0

    cas_q = await db.execute(select(func.count()).select_from(CertificateAuthority))
    cas_total = cas_q.scalar() or 0

    certificates = {
        "total": total,
        "valid": valid,
        "expired": expired,
        "revoked": revoked,
        "expiring_soon": expiring,
        "cas_total": cas_total,
    }

    # Health checks
    data_dir_writable = settings.DATA_DIR.exists() and (settings.DATA_DIR / ".write_test").parent.exists()
    try:
        test_file = settings.DATA_DIR / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        data_dir_writable = True
    except Exception:
        data_dir_writable = False

    backup_dir_writable = False
    try:
        test_file = settings.BACKUP_DIR / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        backup_dir_writable = True
    except Exception:
        pass

    health = {
        "database": "ok",
        "keytool": "ok" if keytool_path else "unavailable",
        "data_dir_writable": data_dir_writable,
        "backup_dir_writable": backup_dir_writable,
    }

    return {
        "system": system,
        "dependencies": dependencies,
        "configuration": configuration,
        "storage": storage,
        "certificates": certificates,
        "health": health,
    }


@router.get("/recent-errors")
async def get_recent_errors(
    limit: int = 20,
    level: str = "WARNING",
    _: str = Depends(require_api_key),
) -> dict:
    """Return recent application errors from the in-memory buffer."""
    if limit > 100:
        limit = 100

    if level == "ERROR":
        filtered = [e for e in _error_buffer if e["level"] == "ERROR"]
    else:
        filtered = _error_buffer  # WARNING includes both WARNING and ERROR

    # Return most recent first
    recent = list(reversed(filtered))[:limit]

    return {
        "errors": recent,
        "total": len(filtered),
        "buffer_size": len(_error_buffer),
        "buffer_max": _ERROR_BUFFER_MAX,
    }


@router.post("/clear-errors")
async def clear_errors(
    _: str = Depends(require_api_key),
) -> dict:
    """Clear the in-memory error buffer."""
    count = len(_error_buffer)
    _error_buffer.clear()
    return {"cleared": count}
