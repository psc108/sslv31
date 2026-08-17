"""Pre-flight readiness checks — Enhancement Plan Stage 3.

Catches a build's *avoidable* failure modes (host unreachable, no sudo, low
disk, no package manager) before a job is even submitted, rather than letting
the user discover them 10 minutes into an Ansible run. Full credentialed
probing (sudo/disk/package manager) only applies to registered SSH-type hosts
(`BMHost.connection_type == "ssh"`) — there's no ssh_user/credential to log in
with otherwise. Docker-hosted targets (role name used directly as the
address, no "network" pool in the template) get a fresh container created at
build time, so there's genuinely nothing to probe yet.

Everything else — a role whose address came from a template "network"
pool/subnet — is, by design, expected to already be a real, reachable
machine the user stood up themselves (see environment_service.allocate_ips
and the golden-path templates' own comments on why they deliberately omit
"network" to get Docker hosts instead). Nothing in this codebase ever
creates a machine for a pool-allocated IP, so at minimum this does an
unauthenticated TCP reachability check against it — enough to turn a
same-symptom-every-time "SSH connection refused" 10 minutes into an Ansible
run into an immediate, actionable pre-flight blocker instead.
"""
import asyncio
import ipaddress
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.build_manager import BMEnvironment, BMHost, BMNetworkPool, BMTemplateVersion

logger = logging.getLogger(__name__)

TCP_PROBE_TIMEOUT_SECONDS = 5

MIN_DISK_FREE_KB = 512 * 1024  # 512MB — enough headroom to catch a genuinely full disk

_PROBE_COMMAND = (
    'echo "SUDO_OK=$( [ "$(whoami)" = root ] && echo 1 || (sudo -n true 2>/dev/null && echo 1 || echo 0) )"; '
    'echo "DISK_KB=$(df --output=avail -k / 2>/dev/null | tail -1 | tr -d \' \')"; '
    'echo "PKGMGR=$(command -v apt-get || command -v yum || command -v apk || echo none)"'
)


async def run_preflight_checks(db: AsyncSession, environment_id: str) -> dict:
    """Run a fast readiness probe against every registered SSH host in an
    environment's template spec. Returns {"ready": bool, "hosts": [...]}."""
    env_result = await db.execute(select(BMEnvironment).where(BMEnvironment.id == environment_id))
    env = env_result.scalar_one_or_none()
    if not env:
        raise ValueError("Environment not found")

    ver_result = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        raise ValueError("Template version not found")

    spec = json.loads(version.spec)
    inv_host_ids = [h["inventory_host_id"] for h in spec.get("hosts", []) if h.get("inventory_host_id")]
    inv_hosts_map: dict[str, BMHost] = {}
    if inv_host_ids:
        inv_result = await db.execute(select(BMHost).where(BMHost.id.in_(inv_host_ids)))
        for ih in inv_result.scalars().all():
            inv_hosts_map[ih.id] = ih

    ip_allocations: dict[str, str] = json.loads(env.ip_allocations) if env.ip_allocations else {}
    network_spec = spec.get("network", {})
    pool_subnet = network_spec.get("pool") or network_spec.get("subnet")
    if not pool_subnet and network_spec.get("pool_id"):
        # Template references a real Inventory network pool by ID rather
        # than a raw subnet — resolve it for a readable guidance message.
        pool_result = await db.execute(select(BMNetworkPool).where(BMNetworkPool.id == network_spec["pool_id"]))
        pool = pool_result.scalar_one_or_none()
        pool_subnet = f"{pool.name}, {pool.cidr}" if pool else None

    host_reports = []
    all_ready = True

    for host_def in spec.get("hosts", []):
        role = host_def["role"]
        inv_host = inv_hosts_map.get(host_def.get("inventory_host_id", ""))

        if inv_host and inv_host.connection_type == "ssh":
            blockers = await _check_ssh_host(db, inv_host)
            host_reports.append({"role": role, "checked": True, "ready": len(blockers) == 0, "blockers": blockers})
            if blockers:
                all_ready = False
            continue

        allocated = ip_allocations.get(role, role)
        if not _looks_like_ip(allocated):
            # Falls back to the role name itself — that's what marks this
            # role as a Docker-backed target: build_environment creates a
            # fresh container for it, so there's nothing to probe yet.
            host_reports.append({"role": role, "checked": False, "ready": True, "blockers": []})
            continue

        # An IP allocated from the template's "network" pool, with no
        # registered BMHost to hold credentials for — the codebase never
        # creates a machine for these (see module docstring), so the best
        # available check is unauthenticated TCP reachability, not a full
        # sudo/disk/package-manager probe.
        blockers = await _check_pool_allocated_host(allocated, pool_subnet)
        host_reports.append({"role": role, "checked": True, "ready": len(blockers) == 0, "blockers": blockers})
        if blockers:
            all_ready = False

    return {"ready": all_ready, "hosts": host_reports}


def _looks_like_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


async def _check_pool_allocated_host(ip: str, pool_subnet: str | None, port: int = 22) -> list[str]:
    """Unauthenticated TCP reachability check for a network-pool-allocated
    host with no registered BMHost/credentials. Can't verify sudo/disk/
    package manager without login credentials, but catching "nothing is
    listening here" now — instead of 10 minutes into an Ansible run — is
    the whole point of pre-flight."""
    pool_note = f' from its template\'s network pool ({pool_subnet})' if pool_subnet else ""
    guidance = (
        f"No SSH-reachable host found at {ip}:{port}. This address was allocated{pool_note}, "
        "which the Build Manager expects to already be a real, running machine with SSH access — "
        "nothing is created automatically for it. Either provision a real host reachable at this "
        "address first, or remove the template's \"network\" block to use auto-created local Docker "
        "test hosts instead."
    )
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=TCP_PROBE_TIMEOUT_SECONDS
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return []
    except Exception:
        return [guidance]


async def _check_ssh_host(db: AsyncSession, host: BMHost) -> list[str]:
    """Probe one SSH host. Returns a list of readable blockers (empty = ready)."""
    from app.services.build_manager import test_ssh_connectivity

    blockers: list[str] = []

    connectivity = await test_ssh_connectivity(
        host.ip, host.port, host.ssh_user,
        auth_method=host.ssh_auth_method, credential_encrypted=host.ssh_credential_encrypted,
    )
    if not connectivity.success:
        return [f"SSH unreachable: {connectivity.message}"]

    # Host-key verification (TOFU pinning, Enhancement Plan Stage 9) — catch
    # a changed/MITM'd host key here, before the build even starts, rather
    # than only when the actual Ansible run enforces it.
    from app.services.build_manager.host_key_service import verify_or_pin_host_key
    key_ok, key_message = await verify_or_pin_host_key(db, host)
    if not key_ok:
        return [key_message]

    from app.services.build_manager.ssh_credentials import SSHCredential

    try:
        async with SSHCredential(host.ssh_auth_method, host.ssh_credential_encrypted) as cred:
            sshpass_prefix = cred.sshpass_prefix()
            args = [*sshpass_prefix, "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5"]
            if sshpass_prefix:
                args += ["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"]
            args += cred.key_args()
            args += ["-p", str(host.port), f"{host.ssh_user}@{host.ip}", _PROBE_COMMAND]

            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        output = stdout.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("Pre-flight probe failed for host %s: %s", host.id, e)
        return [f"Readiness probe failed: {e}"]

    sudo_ok = "SUDO_OK=1" in output
    disk_kb = None
    pkgmgr = None
    for line in output.splitlines():
        if line.startswith("DISK_KB="):
            try:
                disk_kb = int(line.split("=", 1)[1].strip())
            except ValueError:
                disk_kb = None
        elif line.startswith("PKGMGR="):
            pkgmgr = line.split("=", 1)[1].strip()

    if not sudo_ok:
        blockers.append("No root/passwordless-sudo access")
    if disk_kb is not None and disk_kb < MIN_DISK_FREE_KB:
        blockers.append(f"Low disk space: {disk_kb // 1024}MB free (need at least {MIN_DISK_FREE_KB // 1024}MB)")
    if pkgmgr == "none":
        blockers.append("No supported package manager found (apt-get/yum/apk)")

    return blockers
