"""Container manager — creates/removes Docker containers for build environments via Docker Engine API."""

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Docker Engine API via Unix socket
DOCKER_TRANSPORT = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
DOCKER_BASE = "http://docker"

# The target image name (built by docker-compose.build-manager.yml)
TARGET_IMAGE = "docker-target-frontend"  # Will be detected dynamically
NETWORK_NAME = "docker_bm-net"
VOLUME_NAME = "docker_certmanager-data"


_RHEL_OS_FAMILIES = {"rhel", "redhat", "centos", "rocky", "alma"}


async def _get_target_image(base_os: str = "ubuntu") -> str:
    """Detect the target image name from existing target containers, matching
    the requested OS family.

    Multiple OS-family images can coexist (see docker-compose.build-manager.yml
    — a plain "/target-*" fixture container for Ubuntu, a "/target-rhel8-*"
    one for RHEL), so a bare "any target-* container" match would pick
    whichever happens to exist first regardless of which OS the caller
    actually wants. Matching on whether "rhel" appears in the container's own
    name keeps this in sync with new OS-family fixtures without needing a
    hardcoded list of names here.
    """
    is_rhel = base_os.lower() in _RHEL_OS_FAMILIES
    fallback = "docker-target-rhel8" if is_rhel else "docker-target-frontend"
    async with httpx.AsyncClient(transport=DOCKER_TRANSPORT, base_url=DOCKER_BASE) as client:
        # Look for any existing target-* container to get the image name
        resp = await client.get("/containers/json", params={"all": "true"})
        if resp.status_code == 200:
            containers = resp.json()
            for c in containers:
                names = c.get("Names", [])
                for name in names:
                    if not name.startswith("/target-"):
                        continue
                    if ("rhel" in name.lower()) == is_rhel:
                        return c["Image"]
    # Fallback: try common image names
    return fallback


async def _get_network_name() -> str:
    """Detect the bm-net network name (may be prefixed by compose project).

    Anchored to the network(s) ssl-cert-manager's own container is actually
    attached to, not a substring scan over every network Docker knows about
    — found via a real failure where a second, unrelated "bm-net" network
    (no "docker_" prefix, not attached to ssl-cert-manager at all) existed
    alongside the real "docker_bm-net". Docker's /networks API doesn't
    guarantee stable ordering, so scanning all networks for anything
    containing "bm-net" non-deterministically returned the wrong one on
    some calls. A target container built onto the wrong network becomes
    completely unreachable from ssl-cert-manager — this surfaced as a
    baffling SSH-readiness timeout, not a clear "wrong network" error,
    since the container itself boots and starts sshd just fine."""
    async with httpx.AsyncClient(transport=DOCKER_TRANSPORT, base_url=DOCKER_BASE) as client:
        resp = await client.get("/containers/ssl-cert-manager/json")
        if resp.status_code == 200:
            networks = resp.json().get("NetworkSettings", {}).get("Networks", {})
            for name in networks:
                if "bm-net" in name:
                    return name
    return "docker_bm-net"


async def _get_volume_name() -> str:
    """Detect the certmanager-data volume name."""
    async with httpx.AsyncClient(transport=DOCKER_TRANSPORT, base_url=DOCKER_BASE) as client:
        resp = await client.get("/volumes")
        if resp.status_code == 200:
            data = resp.json()
            for vol in data.get("Volumes", []):
                name = vol.get("Name", "")
                if "certmanager-data" in name:
                    return name
    return "docker_certmanager-data"


async def container_exists(container_name: str) -> bool:
    """Check if a container with the given name exists."""
    async with httpx.AsyncClient(transport=DOCKER_TRANSPORT, base_url=DOCKER_BASE) as client:
        resp = await client.get(f"/containers/{container_name}/json")
        return resp.status_code == 200


async def _is_container_running(container_name: str) -> bool:
    async with httpx.AsyncClient(transport=DOCKER_TRANSPORT, base_url=DOCKER_BASE) as client:
        resp = await client.get(f"/containers/{container_name}/json")
        if resp.status_code != 200:
            return False
        return bool(resp.json().get("State", {}).get("Running"))


async def create_container(
    container_name: str, expose_ports: dict[str, str] | None = None,
    extra_binds: list[str] | None = None, base_os: str = "ubuntu",
) -> dict[str, Any]:
    """Create and start a target container for a plain host.

    Args:
        container_name: Name for the container (used as Docker DNS hostname)
        expose_ports: Optional port mappings {container_port: host_port}
        extra_binds: Optional additional bind mounts, each already formatted
            as a Docker "source:container_path[:mode]" string, where source
            is either a host path or (preferred for anything that needs to
            be NFS-exportable — see build_manager.py's build_environment)
            a named Docker volume. Either survives this container being
            removed/recreated for as long as the caller keeps passing the
            same source back in on every (re)build.
        base_os: Template's base_os (e.g. "ubuntu", "rhel") — selects which
            target image family to use. Only matters for a genuinely new
            container; an already-existing one keeps whatever image it was
            created with.

    Returns:
        Dict with container id and status
    """
    if await container_exists(container_name):
        # Already exists — ensure it's running. If it was genuinely stopped
        # (not just already up), starting it is functionally the same
        # cold-start as a freshly created container: systemd/sshd/networking
        # all need time to settle before Ansible can reach it — the caller
        # needs to know this so it waits for SSH-readiness the same way it
        # already does for brand-new containers, instead of assuming an
        # "already exists" container is instantly reachable.
        was_running = await _is_container_running(container_name)
        started, start_error = await start_container(container_name)
        if not started:
            # Previously ignored entirely (this branch always reported
            # "started": True regardless of the actual Docker response) — a
            # container left in "Created" (e.g. its host port already taken
            # by another container) silently stayed unreachable, and the
            # build only failed ~20 minutes later when Ansible's "Gathering
            # Facts" for that host couldn't resolve its hostname at all.
            logger.error(f"Failed to start existing container {container_name}: {start_error}")
            return {"id": container_name, "status": "error", "started": False, "error": start_error}
        return {"id": container_name, "status": "already_exists", "started": True, "cold_start": not was_running}

    image = await _get_target_image(base_os)
    network = await _get_network_name()
    volume = await _get_volume_name()

    # Build container config matching docker-compose.build-manager.yml target pattern
    config: dict[str, Any] = {
        "Image": image,
        "Hostname": container_name,
        "ExposedPorts": {"22/tcp": {}},
        "StopSignal": "SIGRTMIN+3",
        "Entrypoint": ["/entrypoint.sh"],
        "HostConfig": {
            "Privileged": True,
            "Binds": [
                f"{volume}:/certmanager-data:ro",
                "/sys/fs/cgroup:/sys/fs/cgroup:rw",
                *(extra_binds or []),
            ],
            "Tmpfs": {
                "/run": "",
                "/run/lock": "",
            },
            "RestartPolicy": {"Name": "unless-stopped"},
            "NetworkMode": network,
            # EL8's systemd (v239) doesn't reach a running state under
            # Docker's default private cgroup namespace the way newer
            # systemd (e.g. Ubuntu 24.04's v255) does — confirmed via a real
            # RHEL8 container that sat at PID 1 only forever (no journald,
            # no dbus, "systemctl is-system-running" failing to even
            # connect to the bus) until run with host cgroupns, after which
            # it booted normally. Ubuntu's image doesn't need this, so it's
            # scoped to RHEL-family only rather than applied unconditionally.
            **({"CgroupnsMode": "host"} if base_os.lower() in _RHEL_OS_FAMILIES else {}),
        },
        "NetworkingConfig": {
            "EndpointsConfig": {
                network: {"Aliases": [container_name]}
            }
        },
    }

    # Add port bindings if specified
    if expose_ports:
        port_bindings = {}
        for container_port, host_port in expose_ports.items():
            port_key = f"{container_port}/tcp"
            config["ExposedPorts"][port_key] = {}
            port_bindings[port_key] = [{"HostPort": str(host_port)}]
        config["HostConfig"]["PortBindings"] = port_bindings

    async with httpx.AsyncClient(transport=DOCKER_TRANSPORT, base_url=DOCKER_BASE, timeout=60) as client:
        # Create container
        resp = await client.post(
            "/containers/create",
            params={"name": container_name},
            json=config,
        )
        if resp.status_code not in (200, 201):
            error = resp.text
            logger.error(f"Failed to create container {container_name}: {error}")
            return {"id": None, "status": "error", "error": error}

        container_id = resp.json().get("Id", "")

        # Start container
        start_resp = await client.post(f"/containers/{container_id}/start")
        if start_resp.status_code not in (200, 204, 304):
            logger.error(f"Failed to start container {container_name}: {start_resp.text}")
            return {"id": container_id, "status": "created_not_started", "error": start_resp.text}

        logger.info(f"Created and started container: {container_name} ({container_id[:12]})")
        return {"id": container_id, "status": "created", "started": True}


async def start_container(container_name: str) -> tuple[bool, str]:
    """Start an existing container if it's stopped. Returns (success, error_detail)."""
    async with httpx.AsyncClient(transport=DOCKER_TRANSPORT, base_url=DOCKER_BASE) as client:
        resp = await client.post(f"/containers/{container_name}/start")
        if resp.status_code in (200, 204, 304):
            return True, ""
        return False, resp.text


async def remove_container(container_name: str, force: bool = True) -> bool:
    """Stop and remove a container.

    Args:
        container_name: Container to remove
        force: Force kill if running

    Returns:
        True if removed successfully
    """
    # ssl-cert-manager is the only container this app must never remove —
    # the target-* fixture containers were previously also protected, but
    # they turned out to be a persistent liability: several Build Manager
    # environments this session collided with them (host ports already
    # bound, roles Host-Mapped to them carrying stale state from unrelated
    # earlier builds) with no way to clean them up short of a manual
    # `docker rm -f`. They're ordinary hosts now, removable like any other.
    protected = {"ssl-cert-manager"}
    if container_name in protected:
        logger.warning(f"Refusing to remove protected container: {container_name}")
        return False

    async with httpx.AsyncClient(transport=DOCKER_TRANSPORT, base_url=DOCKER_BASE, timeout=30) as client:
        # Stop first
        await client.post(f"/containers/{container_name}/stop", params={"t": 10})
        # Remove
        resp = await client.delete(f"/containers/{container_name}", params={"force": str(force).lower(), "v": "false"})
        if resp.status_code in (200, 204, 404):
            logger.info(f"Removed container: {container_name}")
            return True
        logger.error(f"Failed to remove container {container_name}: {resp.text}")
        return False


async def _wait_for_ssh_port_ready(container_name: str, timeout: float = 60.0, interval: float = 2.0) -> bool:
    """Poll for a real TCP connection to the container's SSH port instead of
    a blind fixed sleep. Found via a real live multi-host build: a fixed 5s
    sleep after creating a whole batch of containers wasn't enough for
    systemd/sshd/networking to fully settle in the *first*-created
    container specifically — every later container in the same batch
    benefits from however long Ansible spends processing earlier hosts
    before ever touching it, but the first host gets none of that headroom,
    and its container's own process tree was found crashing/auto-restarting
    (RestartCount climbing into double digits) while every later host in
    the same build stayed at 0 restarts every single time."""
    import asyncio
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(container_name, 22), timeout=3)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except (OSError, asyncio.TimeoutError):
            await asyncio.sleep(interval)
    return False


async def ensure_containers_for_environment(hosts: list[dict]) -> list[dict]:
    """Create containers for all Docker hosts in an environment.

    Args:
        hosts: List of host dicts with keys: container_name, connection_type,
            expose_ports (optional), extra_binds (optional)

    Returns:
        List of results per host

    Raises:
        ValueError: if any host's container failed to actually start, or
            never came up SSH-ready — previously only logged, so a failure
            here (most commonly a host port collision — see the check in
            _ensure_docker_hosts_ready) surfaced 20+ minutes later, deep
            into the Ansible run, as a baffling "Could not resolve hostname"
            on whichever host lost the race, instead of failing the build
            immediately with a clear reason.
    """
    results = []
    newly_created: list[str] = []
    failures: list[str] = []
    for host in hosts:
        if host.get("connection_type") != "docker":
            continue
        name = host.get("container_name")
        if not name:
            continue
        result = await create_container(
            name, host.get("expose_ports"), host.get("extra_binds"), host.get("base_os", "ubuntu"),
        )
        if result.get("status") in ("error", "created_not_started"):
            failures.append(f"{name}: {result.get('error', 'failed to start')}")
        # "created" covers a brand-new container; "cold_start" covers one
        # that already existed but was stopped and just got (re)started —
        # both need the same settle time before Ansible can reach them.
        # Found via a real live build: a host mapped (via Host Mapping) to
        # a pre-existing-but-stopped target-* container took this path
        # ("already_exists", not "created") and skipped the wait entirely,
        # so Ansible's very next task ("Gathering Facts") tried to SSH in
        # before the container's network alias had even registered —
        # "Could not resolve hostname" / host unreachable.
        if result.get("status") == "created" or result.get("cold_start"):
            newly_created.append(name)
        results.append({"container_name": name, **result})

    # Wait for each newly created container's SSH port to actually be
    # accepting connections, one at a time — any container already ready by
    # the time its turn comes returns immediately, so this doesn't meaningfully
    # slow down a batch where most hosts are already fine.
    for name in newly_created:
        ready = await _wait_for_ssh_port_ready(name)
        if not ready:
            failures.append(f"{name}: container did not become SSH-ready within the timeout")

    if failures:
        raise ValueError(
            "Failed to prepare Docker host(s) for this build:\n" + "\n".join(f"- {f}" for f in failures)
        )

    return results


async def cleanup_containers_for_environment(container_names: list[str]) -> list[dict]:
    """Remove containers created for an environment.

    Args:
        container_names: List of container names to remove

    Returns:
        List of results per container
    """
    results = []
    for name in container_names:
        try:
            removed = await remove_container(name)
        except Exception as e:
            logger.warning(f"Failed to remove container {name}: {e}")
            removed = False
        results.append({"container_name": name, "removed": removed})
    return results
