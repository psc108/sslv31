"""Package cache service — manages the per-OS package cache for offline provisioning."""

import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CACHE_DIR = Path("/data/pkg-cache")
MANIFEST_PATH = CACHE_DIR / "manifest.json"
BIN_CACHE_DIR = CACHE_DIR / "bin"

# OS family → cache subdirectory and index file
_OS_CACHE = {
    "Debian":  {"dir": "apt", "index": "Packages.gz",           "pkg_ext": "*.deb", "label": "Ubuntu/Debian"},
    "RedHat":  {"dir": "rpm", "index": "repodata/repomd.xml",   "pkg_ext": "*.rpm", "label": "RHEL/CentOS"},
    "Alpine":  {"dir": "apk", "index": "APKINDEX.tar.gz",       "pkg_ext": "*.apk", "label": "Alpine"},
}


def _os_cache_status(os_family: str) -> dict:
    """Return status for a single OS family cache."""
    cfg = _OS_CACHE[os_family]
    cache_dir = CACHE_DIR / cfg["dir"]
    index_file = cache_dir / cfg["index"]
    pkg_files = list(cache_dir.glob(cfg["pkg_ext"])) if cache_dir.exists() else []

    # Read manifest fragment if present
    frag_path = CACHE_DIR / f"manifest-{cfg['dir']}.json"
    frag = {}
    if frag_path.exists():
        try:
            frag = json.loads(frag_path.read_text())
        except Exception:
            logger.exception("Failed to parse package cache manifest fragment %s", frag_path)

    ready = index_file.exists() and len(pkg_files) > 0
    return {
        "os_family": os_family,
        "label": cfg["label"],
        "status": "ready" if ready else ("incomplete" if cache_dir.exists() else "empty"),
        "package_count": len(pkg_files),
        "synced_at": frag.get("synced_at"),
        "synced_by_host": frag.get("synced_by_host"),
        "packages": frag.get("packages", []),
    }


def get_cache_status() -> dict:
    """Return current cache status for all OS families."""
    manifest = {}
    if MANIFEST_PATH.exists():
        try:
            manifest = json.loads(MANIFEST_PATH.read_text())
        except Exception:
            logger.exception("Failed to parse package cache manifest %s", MANIFEST_PATH)

    bin_info = manifest.get("bin", {})
    os_statuses = {family: _os_cache_status(family) for family in _OS_CACHE}

    ready_families = [f for f, s in os_statuses.items() if s["status"] == "ready"]
    any_ready = len(ready_families) > 0

    if not any_ready and not MANIFEST_PATH.exists():
        overall = "empty"
        message = "No package cache synced. Run a sync for each OS family you deploy to."
    elif any_ready:
        overall = "ready"
        labels = [_OS_CACHE[f]["label"] for f in ready_families]
        message = f"Cache ready for: {', '.join(labels)}."
    else:
        overall = "incomplete"
        message = "Cache directories exist but indexes are missing. Re-run sync."

    return {
        "status": overall,
        "message": message,
        "generated_at": manifest.get("generated_at"),
        "os_families": os_statuses,
        "bin": {
            "nodejs_x64":   bin_info.get("nodejs_x64", False),
            "nodejs_arm64": bin_info.get("nodejs_arm64", False),
            "go_amd64":     bin_info.get("go_amd64", False),
            "go_arm64":     bin_info.get("go_arm64", False),
        },
    }


async def submit_cache_sync(
    db: AsyncSession,
    created_by: str = "system",
    ubuntu_host: str = "",
    rhel_host: str = "",
    alpine_host: str = "",
) -> object:
    """Submit a pkg-cache-sync job. Pass inventory hostnames for each OS family to sync."""
    from app.services.build_manager.ansible_runner import submit_job

    extra_vars: dict = {}
    if ubuntu_host:
        extra_vars["sync_ubuntu_host"] = ubuntu_host
    if rhel_host:
        extra_vars["sync_rhel_host"] = rhel_host
    if alpine_host:
        extra_vars["sync_alpine_host"] = alpine_host

    families = [h for h in [ubuntu_host, rhel_host, alpine_host] if h]
    name = f"Package Cache Sync ({', '.join(families) if families else 'binaries only'})"

    return await submit_job(
        db=db,
        name=name,
        playbook="pkg-cache-sync.yml",
        job_type="pkg_cache_sync",
        created_by=created_by,
        extra_vars=extra_vars,
    )
