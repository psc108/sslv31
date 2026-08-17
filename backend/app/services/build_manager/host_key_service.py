"""Host-key verification (TOFU pinning) — Enhancement Plan Stage 9.

Every SSH connection this app makes uses StrictHostKeyChecking=no, so
per-host credentials (Hardening Plan Stage 5) protect *authentication* but
not against a MITM substituting the target entirely. This module pins each
BMHost's real ssh-keyscan output (not just a display fingerprint) on first
successful connection, and rejects a later, different key unless an admin
explicitly re-accepts it via accept_new_host_key.

Only meaningful for connection_type == "ssh" — Docker-hosted containers are
recreated fresh on every build and have no stable identity to pin against;
callers are expected to skip Docker hosts before calling into this module.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.build_manager import BMEnvironment, BMHost, BMTemplateVersion

logger = logging.getLogger(__name__)


def _rejects_as_ssh_option(value: str) -> bool:
    """Same injection guard as test_ssh_connectivity's — a value starting
    with '-' could be interpreted as a flag by ssh-keyscan."""
    return value.startswith("-")


async def fetch_host_key(host: str, port: int = 22, timeout: int = 5) -> str | None:
    """Run ssh-keyscan for the host's Ed25519 key. Returns the raw
    known_hosts-format line, or None if unreachable/no key returned."""
    if _rejects_as_ssh_option(host):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh-keyscan", "-p", str(port), "-t", "ed25519", host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0 or not stdout:
            return None
        # ssh-keyscan can emit comment lines and/or multiple key types even
        # when only one was requested — keep the first non-comment line.
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
        return None
    except (asyncio.TimeoutError, Exception):
        logger.warning("ssh-keyscan failed for %s:%s", host, port)
        return None


def _key_material(line: str) -> str | None:
    """Extract the 'ssh-ed25519 AAAA...' portion, ignoring the leading
    host/IP column — so pinning survives being looked up by a different
    address representation (hostname vs IP) than it was pinned under."""
    parts = line.split(None, 2)
    if len(parts) < 2:
        return None
    return " ".join(parts[1:])


async def verify_or_pin_host_key(db: AsyncSession, host: BMHost) -> tuple[bool, str]:
    """TOFU check for one host. Returns (ok, message):
    - No key observed at all: (False, "could not retrieve host key").
    - Never pinned before: pins now, (True, "pinned on first connection").
    - Matches the pinned key: (True, "host key verified").
    - Differs from the pinned key: (False, "host key changed" — blocks).
    """
    current_line = await fetch_host_key(host.ip, host.port)
    if not current_line:
        return False, f"Could not retrieve host key for {host.hostname} ({host.ip}) — host unreachable or ssh-keyscan failed"

    current_material = _key_material(current_line)
    if not current_material:
        return False, f"Could not parse host key returned for {host.hostname} ({host.ip})"

    if not host.pinned_host_key:
        host.pinned_host_key = current_line
        host.host_key_pinned_at = datetime.now(timezone.utc)
        await db.commit()
        return True, f"Host key pinned for {host.hostname} (first successful connection)"

    pinned_material = _key_material(host.pinned_host_key)
    if current_material == pinned_material:
        return True, "Host key verified"

    return False, (
        f"Host key for {host.hostname} ({host.ip}) has CHANGED since it was pinned "
        f"on {host.host_key_pinned_at.isoformat() if host.host_key_pinned_at else 'unknown'} — "
        "possible MITM, or the host was legitimately reinstalled/replaced. "
        "Re-accept the new key explicitly if this is expected."
    )


async def accept_new_host_key(db: AsyncSession, host: BMHost) -> str:
    """Explicitly re-pin a host to its currently-observed key (admin action,
    used once a changed key has been confirmed legitimate out-of-band — e.g.
    the host was reinstalled). Raises ValueError if the host isn't reachable
    right now, since there'd be nothing real to pin."""
    current_line = await fetch_host_key(host.ip, host.port)
    if not current_line:
        raise ValueError(f"Could not retrieve current host key for {host.hostname} ({host.ip}) — host unreachable")

    host.pinned_host_key = current_line
    host.host_key_pinned_at = datetime.now(timezone.utc)
    await db.commit()
    return current_line


async def resolve_ssh_hosts(db: AsyncSession, environment_id: str) -> list[BMHost]:
    """Every registered connection_type == "ssh" host referenced by an
    environment's current template spec — the same resolution preflight
    checks use, reused here so job execution enforces pinning against
    exactly the hosts that are actually in play for that environment.
    Docker-hosted and unregistered hosts are never returned; there's no
    stable identity to pin against for either."""
    env_result = await db.execute(select(BMEnvironment).where(BMEnvironment.id == environment_id))
    env = env_result.scalar_one_or_none()
    if not env:
        return []

    ver_result = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        return []

    spec = json.loads(version.spec)
    inv_host_ids = [h["inventory_host_id"] for h in spec.get("hosts", []) if h.get("inventory_host_id")]
    if not inv_host_ids:
        return []

    inv_result = await db.execute(select(BMHost).where(BMHost.id.in_(inv_host_ids)))
    return [h for h in inv_result.scalars().all() if h.connection_type == "ssh"]
