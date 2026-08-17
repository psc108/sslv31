"""Backup endpoints — create, list, download, and delete backup archives."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_api_key, require_permission, AuthContext
from app.services.backup_engine import create_backup, list_backups, verify_backup
from app.services.audit import audit_event

router = APIRouter(prefix="/api/v1/backup", tags=["Backup"])


@router.post("", status_code=201)
async def trigger_backup(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("backup:manage")),
) -> dict:
    """Trigger an immediate backup."""
    try:
        filename, size, checksum = create_backup()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backup failed: {e}")

    await audit_event(
        db=db,
        event_type="BACKUP_CREATED",
        severity="INFO",
        request=request,
        subject_type="backup",
        subject_id=filename,
        detail={"size": size, "sha256": checksum},
        description=f"Backup created: {filename}",
    )
    await db.commit()

    return {"filename": filename, "size": size, "sha256": checksum}


@router.get("")
async def get_backup_list(
    _: str = Depends(require_api_key),
) -> list[dict]:
    """List available backup archives."""
    return list_backups()


@router.get("/{filename}")
async def download_backup(
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("backup:manage")),
) -> Response:
    """Download a backup archive."""
    filepath = settings.BACKUP_DIR / filename
    if not filepath.exists() or not filename.startswith("backup-"):
        raise HTTPException(status_code=404, detail="Backup not found")

    await audit_event(
        db=db,
        event_type="BACKUP_DOWNLOAD",
        severity="WARNING",
        request=request,
        subject_type="backup",
        subject_id=filename,
    )
    await db.commit()

    content = filepath.read_bytes()
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{filename}/verify")
async def verify_backup_archive(
    filename: str,
    _: str = Depends(require_api_key),
) -> dict:
    """Verify a backup archive is valid without restoring it."""
    filepath = settings.BACKUP_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Backup not found")

    try:
        return verify_backup(filepath)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/{filename}", status_code=200)
async def delete_backup(
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require_permission("backup:manage")),
) -> dict:
    """Delete a backup archive."""
    filepath = settings.BACKUP_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Backup not found")

    filepath.unlink()
    checksum_file = filepath.with_suffix(".enc.sha256")
    if checksum_file.exists():
        checksum_file.unlink()

    await audit_event(
        db=db,
        event_type="BACKUP_DELETED",
        severity="INFO",
        request=request,
        subject_type="backup",
        subject_id=filename,
    )
    await db.commit()

    return {"status": "deleted", "filename": filename}
