"""Container readiness-wait must cover cold-started existing containers too.

Found via a real live build: a role mapped (via Host Mapping) to a
pre-existing-but-stopped target-* container took create_container()'s
"already_exists" branch, not "created" — so ensure_containers_for_environment()
never waited for its SSH port to come up before Ansible's very next task
("Gathering Facts") tried to connect, and failed with "Could not resolve
hostname target-backend: Name or service not known" / host unreachable.
The same class of bug _wait_for_ssh_port_ready()'s own docstring already
describes for brand-new containers, just for a path that wasn't covered.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.build_manager import container_manager


@pytest.mark.usefixtures("setup_db")
async def test_ensure_containers_waits_for_cold_started_existing_container():
    """A host whose container already existed but was stopped (cold_start
    in create_container's result) must be waited on exactly like a
    brand-new one."""
    with patch.object(container_manager, "create_container", new=AsyncMock(
        return_value={"id": "target-backend", "status": "already_exists", "started": True, "cold_start": True},
    )), patch.object(container_manager, "_wait_for_ssh_port_ready", new=AsyncMock(return_value=True)) as mock_wait:
        await container_manager.ensure_containers_for_environment(
            [{"role": "backend", "container_name": "target-backend", "connection_type": "docker"}]
        )
    mock_wait.assert_awaited_once_with("target-backend")


@pytest.mark.usefixtures("setup_db")
async def test_ensure_containers_waits_for_brand_new_container():
    with patch.object(container_manager, "create_container", new=AsyncMock(
        return_value={"id": "abc123", "status": "created", "started": True},
    )), patch.object(container_manager, "_wait_for_ssh_port_ready", new=AsyncMock(return_value=True)) as mock_wait:
        await container_manager.ensure_containers_for_environment(
            [{"role": "pkg-cache", "container_name": "pkg-cache", "connection_type": "docker"}]
        )
    mock_wait.assert_awaited_once_with("pkg-cache")


@pytest.mark.usefixtures("setup_db")
async def test_ensure_containers_skips_wait_for_already_running_container():
    """A host whose container was already running before this call (the
    common case for the long-lived target-mysql/target-rabbitmq/etc.
    fixtures) must not pay the readiness-wait cost at all."""
    with patch.object(container_manager, "create_container", new=AsyncMock(
        return_value={"id": "target-mysql", "status": "already_exists", "started": True, "cold_start": False},
    )), patch.object(container_manager, "_wait_for_ssh_port_ready", new=AsyncMock(return_value=True)) as mock_wait:
        await container_manager.ensure_containers_for_environment(
            [{"role": "mysql", "container_name": "target-mysql", "connection_type": "docker"}]
        )
    mock_wait.assert_not_awaited()
