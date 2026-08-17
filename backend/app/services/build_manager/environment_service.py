"""Environment service — instantiation, IP allocation, lifecycle."""

import asyncio
import ipaddress
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models.build_manager import BMEnvironment, BMEnvironmentCert, BMHost, BMNetworkPool, BMTemplate, BMTemplateVersion

logger = logging.getLogger(__name__)


async def compute_available_pool_ips(db: AsyncSession, pool: BMNetworkPool, count: int) -> list[str]:
    """Compute up to `count` available IPs from a pool's CIDR, excluding
    network/broadcast/gateway addresses, the pool's own explicit
    reservations, and IPs already assigned to a registered BMHost.

    Shared by GET /network-pools/{id}/available (build_manager.py) and
    allocate_ips_async() below — was previously duplicated inline in the
    endpoint only, with no other caller able to reuse the same reservation
    logic for template-driven allocation."""
    network = ipaddress.ip_network(pool.cidr, strict=False)
    reserved_raw = json.loads(pool.reserved) if pool.reserved else []

    reserved_ips: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = {network.network_address, network.broadcast_address}
    if pool.gateway:
        try:
            reserved_ips.add(ipaddress.ip_address(pool.gateway))
        except ValueError:
            pass
    for entry in reserved_raw:
        if "-" in entry:
            parts = entry.split("-")
            try:
                start = ipaddress.ip_address(parts[0].strip())
                end = ipaddress.ip_address(parts[1].strip())
                current = start
                while current <= end:
                    reserved_ips.add(current)
                    current = ipaddress.ip_address(int(current) + 1)
            except ValueError:
                pass
        else:
            try:
                reserved_ips.add(ipaddress.ip_address(entry.strip()))
            except ValueError:
                pass

    host_result = await db.execute(select(BMHost.ip))
    allocated_ips = set()
    for row in host_result.all():
        try:
            allocated_ips.add(ipaddress.ip_address(row[0]))
        except ValueError:
            pass

    available = []
    for addr in network.hosts():
        if addr in reserved_ips or addr in allocated_ips:
            continue
        available.append(str(addr))
        if len(available) >= count:
            break
    return available


def allocate_ips(spec: dict, overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Allocate IPs from the template's network pool, with optional user overrides.

    For Docker hosts (identified by inventory_host_id with connection_type=docker),
    the allocation stores the container name rather than an IP.

    Returns: {role: ip_address_or_container_name}
    """
    overrides = overrides or {}
    allocations: dict[str, str] = {}

    hosts = spec.get("hosts", [])
    network = spec.get("network", {})
    pool = network.get("pool", "") or network.get("subnet", "")
    range_start = network.get("range_start", 10)
    range_end = network.get("range_end", 50)
    # Handle string range values (e.g. "192.168.50.10")
    if isinstance(range_start, str):
        try:
            range_start = int(range_start.split(".")[-1])
        except (ValueError, IndexError):
            range_start = 10
    if isinstance(range_end, str):
        try:
            range_end = int(range_end.split(".")[-1])
        except (ValueError, IndexError):
            range_end = 50

    # If user provided overrides for all roles, use them
    roles = [h["role"] for h in hosts]
    for role in roles:
        if role in overrides:
            allocations[role] = overrides[role]

    # Auto-allocate remaining from pool
    if pool and any(r not in allocations for r in roles):
        try:
            net = ipaddress.ip_network(pool, strict=False)
            available = [str(net.network_address + i) for i in range(range_start, range_end + 1)]
            used = set(allocations.values())
            for role in roles:
                if role not in allocations:
                    for ip in available:
                        if ip not in used:
                            allocations[role] = ip
                            used.add(ip)
                            break
        except (ValueError, StopIteration):
            logger.warning(f"Failed to allocate IPs from pool: {pool}")

    # Fallback: use role name directly (user must provide valid hostnames)
    for role in roles:
        if role not in allocations:
            allocations[role] = role

    return allocations


async def allocate_ips_async(db: AsyncSession, spec: dict, overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Async counterpart of allocate_ips() — adds support for a template's
    network block referencing a real Inventory network pool
    (network: {"pool_id": "..."}) rather than a raw subnet/range baked
    directly into the spec. Resolved against the pool's *current* state
    (existing host IPs, reservations) at environment-creation time — not
    cached in the template — so a pool's available addresses stay accurate
    even if hosts get added/removed after the template was built.

    Falls straight through to the sync allocate_ips() for every other case
    (no network block at all -> Docker auto-provision fallback; a raw
    subnet/range_start/range_end block, e.g. from an older template or one
    built outside the UI -> unchanged legacy behaviour) — zero behavior
    change for anything that doesn't use a pool reference."""
    network = spec.get("network", {})
    pool_id = network.get("pool_id")
    if not pool_id:
        return allocate_ips(spec, overrides)

    overrides = overrides or {}
    hosts = spec.get("hosts", [])
    roles = [h["role"] for h in hosts]
    allocations: dict[str, str] = {role: overrides[role] for role in roles if role in overrides}

    needed = [r for r in roles if r not in allocations]
    if needed:
        result = await db.execute(select(BMNetworkPool).where(BMNetworkPool.id == pool_id))
        pool = result.scalar_one_or_none()
        if not pool:
            logger.warning(f"Template references network pool {pool_id} which no longer exists")
        else:
            used = set(allocations.values())
            available = [ip for ip in await compute_available_pool_ips(db, pool, count=len(needed) + len(used)) if ip not in used]
            for role, ip in zip(needed, available):
                allocations[role] = ip

    # Same fallback as allocate_ips() — a role the pool couldn't cover
    # (pool exhausted, pool deleted) falls back to its own name rather than
    # being silently dropped from the allocation map.
    for role in roles:
        if role not in allocations:
            allocations[role] = role

    return allocations


async def instantiate_environment(
    db: AsyncSession, name: str, template_id: str, version: int,
    ip_overrides: dict[str, str] | None, variable_overrides: dict[str, Any] | None,
    created_by: str, tenant_id: str, ttl_hours: float | None = None,
) -> BMEnvironment:
    """Create a new environment from a template version."""
    # Get the template version spec
    result = await db.execute(
        select(BMTemplateVersion)
        .where(BMTemplateVersion.template_id == template_id, BMTemplateVersion.version == version)
    )
    tv = result.scalar_one_or_none()
    if not tv:
        raise ValueError(f"Template version {version} not found")

    spec = json.loads(tv.spec)
    ip_allocations = await allocate_ips_async(db, spec, ip_overrides)

    env = BMEnvironment(
        name=name,
        template_id=template_id,
        template_version=version,
        status="pending",
        ip_allocations=json.dumps(ip_allocations),
        variables=json.dumps(variable_overrides or {}),
        created_by=created_by,
        tenant_id=tenant_id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours) if ttl_hours else None,
    )
    db.add(env)
    await db.commit()
    await db.refresh(env)
    return env


async def build_environment_snapshot(db: AsyncSession, environment_id: str) -> dict[str, Any] | None:
    """Captures an environment's build context — OS, per-host product
    versions, IP allocations, issued certs — as a plain dict, for a caller
    to persist elsewhere (BMJob.build_snapshot_json, set at submit_job()
    time). This is the only way that context survives destroy_environment()
    below, which hard-deletes the BMEnvironment row itself (jobs are merely
    detached, not the environment data preserved) — so callers should snapshot
    at job creation, not try to reconstruct this after the fact. Returns None
    if the environment can't be found (already destroyed, bad id, etc.)."""
    result = await db.execute(
        select(BMEnvironment).options(
            selectinload(BMEnvironment.template),
            selectinload(BMEnvironment.certs),
        ).where(BMEnvironment.id == environment_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        return None

    spec: dict[str, Any] = {}
    if env.template_id and env.template_version is not None:
        v_result = await db.execute(
            select(BMTemplateVersion).where(
                BMTemplateVersion.template_id == env.template_id,
                BMTemplateVersion.version == env.template_version,
            )
        )
        version_row = v_result.scalar_one_or_none()
        if version_row:
            spec = json.loads(version_row.spec)

    return {
        "environment_id": env.id,
        "environment_name": env.name,
        "template_id": env.template_id,
        "template_name": env.template.name if env.template else None,
        "template_version": env.template_version,
        "status": env.status,
        "base_os": spec.get("base_os"),
        "base_os_version": spec.get("base_os_version"),
        "hosts": [
            {"role": h.get("role"), "products": h.get("products", [])}
            for h in spec.get("hosts", [])
        ],
        "ip_allocations": json.loads(env.ip_allocations) if env.ip_allocations else {},
        "certs": [{"role": c.role, "cert_type": c.cert_type} for c in env.certs],
    }


async def destroy_expired_environments(db: AsyncSession) -> list[str]:
    """Find every environment past its TTL and destroy it. Returns the names
    of environments destroyed this pass. Called on a periodic background
    loop (run_environment_ttl_scheduler) — not tied to any API request, so
    these destroys aren't audit_event()'d (no Request to attribute them to);
    they're logged instead, same as this app's other background jobs."""
    # TZDateTime stores everything as naive UTC (see app/models/base.py) —
    # compare against a naive UTC "now" to match, not an aware one.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await db.execute(
        select(BMEnvironment).where(
            BMEnvironment.expires_at.isnot(None),
            BMEnvironment.expires_at <= now,
            BMEnvironment.status != "destroyed",
        )
    )
    expired = result.scalars().all()
    destroyed_names = []
    for env in expired:
        try:
            await destroy_environment(db, env.id)
            destroyed_names.append(env.name)
            logger.info(f"TTL expired — auto-destroyed Build Manager environment '{env.name}' ({env.id})")
        except Exception as e:
            logger.error(f"Failed to auto-destroy expired environment {env.id}: {e}")
    return destroyed_names


async def run_environment_ttl_scheduler(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Background task: check for TTL-expired environments on a recurring
    interval (mirrors run_expiry_scanner's periodic-poll pattern)."""
    from app.core.config import settings

    interval = settings.BM_TTL_CHECK_INTERVAL_MINUTES * 60
    while True:
        try:
            async with session_factory() as db:
                await destroy_expired_environments(db)
        except Exception as e:
            logger.error(f"Environment TTL scheduler error: {e}")
        await asyncio.sleep(interval)


async def _get_environment_container_names(db: AsyncSession, env: BMEnvironment) -> list[str]:
    """Docker container names actually backing this environment's hosts.

    Shared by destroy_environment() so both the manual /destroy endpoint and
    TTL auto-destroy clean up the same containers the same way — found via
    TTL auto-destroy never having done this at all (it only deleted the DB
    row), leaving every Docker container from an expired environment running
    indefinitely, exactly the kind of stray container that caused real
    port-collision/network-attachment failures for later builds this
    session. Mirrors _ensure_docker_hosts_ready's own two-branch lookup
    (build_manager.py): prefer BMHost.container_name via inventory_host_id
    when present, else treat non-IP ip_allocations values as container
    names."""
    from app.models.build_manager import BMHost, BMTemplateVersion

    ver_result = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    tv = ver_result.scalar_one_or_none()
    if not tv:
        return []

    spec = json.loads(tv.spec)
    inv_host_ids = [h["inventory_host_id"] for h in spec.get("hosts", []) if h.get("inventory_host_id")]
    if inv_host_ids:
        inv_result = await db.execute(select(BMHost).where(BMHost.id.in_(inv_host_ids)))
        return [
            h.container_name for h in inv_result.scalars().all()
            if h.connection_type == "docker" and h.container_name
        ]

    container_names = []
    ip_allocs = json.loads(env.ip_allocations) if env.ip_allocations else {}
    for role, addr in ip_allocs.items():
        try:
            ipaddress.ip_address(addr)
        except ValueError:
            container_names.append(addr)
    return container_names


async def destroy_environment(db: AsyncSession, environment_id: str) -> BMEnvironment:
    """Revoke certs, delete the environment row so the name can be reused,
    and remove any Docker containers backing it — used by both the manual
    /destroy endpoint and TTL auto-destroy, so an environment that expires
    on its own cleans up exactly like one destroyed by hand."""
    from app.models.build_manager import BMJob

    result = await db.execute(
        select(BMEnvironment).options(selectinload(BMEnvironment.certs))
        .where(BMEnvironment.id == environment_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        raise ValueError("Environment not found")

    container_names = await _get_environment_container_names(db, env)

    now = datetime.now(timezone.utc)

    # Revoke all certs
    for cert in env.certs:
        if not cert.revoked_at:
            cert.revoked_at = now
    await db.flush()

    # Revoke cert bindings and mark actual certs as revoked
    from app.services.build_manager.cert_lifecycle import revoke_environment_bindings
    await revoke_environment_bindings(db, environment_id)

    # Detach jobs from this environment (so they survive deletion for audit)
    from sqlalchemy import update
    await db.execute(
        update(BMJob).where(BMJob.environment_id == environment_id).values(environment_id=None)
    )
    await db.flush()

    # Capture response data before deletion
    env_name = env.name
    env_id = env.id

    # Delete the environment row (frees the unique name)
    await db.delete(env)
    await db.commit()

    # Return a detached object for the API response
    placeholder = BMEnvironment(
        id=env_id, name=env_name, status="destroyed",
        template_id=env.template_id, template_version=env.template_version,
        tenant_id=env.tenant_id,
    )

    if container_names:
        # Best-effort: the environment row is already gone at this point, so
        # a Docker-side failure here (socket unreachable, container already
        # gone, etc.) must not make destroy_environment() look like it
        # failed overall — that would incorrectly tell destroy_expired_environments()
        # to skip marking this environment as destroyed, and the manual
        # /destroy endpoint to return a 404/500, even though the actual,
        # authoritative DB-level destroy already succeeded.
        from app.services.build_manager.container_manager import cleanup_containers_for_environment
        try:
            await cleanup_containers_for_environment(container_names)
        except Exception as e:
            logger.warning(f"Environment '{env_name}' destroyed, but container cleanup failed: {e}")

    return placeholder
