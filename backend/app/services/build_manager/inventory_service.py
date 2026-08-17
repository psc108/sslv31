"""Inventory service — generates dynamic Ansible inventory from database."""

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.build_manager import BMHost, BMHostGroup, BMHostGroupMember, BMHostVar

logger = logging.getLogger(__name__)

_RHEL_OS_FAMILIES = {"rhel", "redhat", "centos", "rocky", "alma"}


def _python_interpreter_for_os(os_type: str | None) -> str | None:
    """RHEL8's system /usr/bin/python3 is 3.6 — too old for modern
    ansible-core's module code, which uses `from __future__ import
    annotations` (Python 3.7+ only). Confirmed via a real task failure
    ("SyntaxError: future feature annotations is not defined") the moment
    any module ran against the default interpreter. python3.11 is installed
    alongside it (not replacing it — RHEL8's own dnf/yum tooling is tied to
    the system 3.6) specifically for Ansible to use instead. Ubuntu's
    default python3 doesn't have this problem, so this only applies to
    RHEL-family hosts.
    """
    if (os_type or "").lower() in _RHEL_OS_FAMILIES:
        return "/usr/bin/python3.11"
    return None


async def generate_ansible_inventory(
    db: AsyncSession, group_name: str | None = None, tag: str | None = None,
    environment_id: str | None = None,
) -> dict[str, Any]:
    """Generate Ansible-compatible inventory JSON.

    If environment_id is provided, builds inventory from the environment's
    template spec + ip_allocations (no bm_hosts required).

    Format:
    {
      "_meta": { "hostvars": { "hostname": { ... } } },
      "group_name": { "hosts": ["hostname", ...] },
      "all": { "hosts": [...] }
    }
    """
    # --- Environment-based inventory ---
    if environment_id:
        return await _generate_environment_inventory(db, environment_id)

    # --- Static host-based inventory (from bm_hosts table) ---
    query = select(BMHost).options(selectinload(BMHost.variables), selectinload(BMHost.group_memberships))

    if tag:
        query = query.where(BMHost.tags.contains(tag))

    result = await db.execute(query)
    hosts = result.scalars().all()

    # Build hostvars
    hostvars: dict[str, dict] = {}
    all_hosts: list[str] = []

    for host in hosts:
        all_hosts.append(host.hostname)
        # Docker hosts connect via container name; SSH hosts via IP
        if host.connection_type == "docker" and host.container_name:
            ansible_host = host.container_name
        else:
            ansible_host = host.ip
        hv: dict[str, Any] = {
            "ansible_host": ansible_host,
            "ansible_port": host.port,
            "ansible_user": host.ssh_user,
            "service_role": host.service_role,
            "os_type": host.os_type,
            "os_version": host.os_version,
        }
        # Internal-only fields (leading underscore) — never real Ansible vars.
        # ansible_runner.py materialises these into ansible_ssh_private_key_file
        # / ansible_password right before a job runs, then strips them, so a
        # per-host credential (Stage 5) is never written into a long-lived
        # inventory file, only the ephemeral one generated per job execution.
        if host.ssh_auth_method != "shared_key" and host.ssh_credential_encrypted:
            hv["_ssh_auth_method"] = host.ssh_auth_method
            hv["_ssh_credential_encrypted"] = host.ssh_credential_encrypted
        interpreter = _python_interpreter_for_os(host.os_type)
        if interpreter:
            hv["ansible_python_interpreter"] = interpreter
        for var in host.variables:
            if not var.encrypted:
                hv[var.key] = var.value
        hostvars[host.hostname] = hv

    inventory: dict[str, Any] = {
        "_meta": {"hostvars": hostvars},
        "all": {"hosts": all_hosts},
    }

    # Build groups
    groups_result = await db.execute(
        select(BMHostGroup).options(selectinload(BMHostGroup.members))
    )
    groups = groups_result.scalars().all()

    for group in groups:
        if group_name and group.name != group_name:
            continue
        member_ids = [m.host_id for m in group.members]
        group_hosts = [h.hostname for h in hosts if h.id in member_ids]
        if group_hosts:
            inventory[group.name] = {"hosts": group_hosts}

    # Service role groups (auto-generated)
    role_groups: dict[str, list[str]] = {}
    for host in hosts:
        role_groups.setdefault(host.service_role, []).append(host.hostname)
    for role, role_hosts in role_groups.items():
        inventory[f"role_{role}"] = {"hosts": role_hosts}

    return inventory


async def _generate_environment_inventory(db: AsyncSession, environment_id: str) -> dict[str, Any]:
    """Build inventory from environment template spec + ip_allocations."""
    from app.models.build_manager import BMEnvironment, BMTemplate, BMTemplateVersion

    result = await db.execute(
        select(BMEnvironment).where(BMEnvironment.id == environment_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        return {"_meta": {"hostvars": {}}, "all": {"hosts": []}}

    # Get template spec
    ver_result = await db.execute(
        select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        return {"_meta": {"hostvars": {}}, "all": {"hosts": []}}

    spec = json.loads(version.spec)
    ip_allocations = json.loads(env.ip_allocations) if env.ip_allocations else {}

    # Step 5.4 — read tofu outputs for AWS environments (rds_endpoint etc.)
    tofu_outputs: dict = {}
    if spec.get("aws"):
        try:
            from app.services.build_manager.tofu_workspace import get_workspace_dir, workspace_exists
            from app.services.build_manager.tofu_runner import run_tofu_output
            ws = get_workspace_dir(env.name)
            if workspace_exists(env.name):
                import asyncio
                tofu_outputs = await run_tofu_output(ws)
        except Exception:
            pass

    hostvars: dict[str, dict] = {}
    all_hosts: list[str] = []
    role_groups: dict[str, list[str]] = {}

    # Pre-load inventory hosts if referenced in spec
    inventory_host_ids = [h["inventory_host_id"] for h in spec.get("hosts", []) if h.get("inventory_host_id")]
    inv_hosts_map: dict[str, BMHost] = {}
    if inventory_host_ids:
        inv_result = await db.execute(
            select(BMHost).where(BMHost.id.in_(inventory_host_ids))
        )
        for ih in inv_result.scalars().all():
            inv_hosts_map[ih.id] = ih

    for host_def in spec.get("hosts", []):
        role = host_def["role"]
        # The hostname in inventory is the role name (matches --limit filter)
        hostname = role

        # Determine ansible_host: Docker hosts use container name, SSH hosts use IP
        ansible_host = ip_allocations.get(role, role)
        inv_host = inv_hosts_map.get(host_def.get("inventory_host_id", ""))
        if inv_host:
            if inv_host.connection_type == "docker" and inv_host.container_name:
                ansible_host = inv_host.container_name
            elif inv_host.ip:
                ansible_host = inv_host.ip

        all_hosts.append(hostname)
        # Step 3.5 — cert file paths for this host (written by cert_integration.py)
        cert_base = f"/data/environments/{env.name}/certs/{role}"
        env_cert_base = f"/data/environments/{env.name}/certs"
        hostvars[hostname] = {
            "ansible_host": ansible_host,
            "ansible_port": 22,
            "ansible_user": "root",
            "service_role": role,
            "os_type": spec.get("base_os", "ubuntu"),
            "os_version": spec.get("base_os_version", "24.04"),
            "environment_name": env.name,
            "environment_id": environment_id,
            "cert_crt": f"{cert_base}/server.crt",
            "cert_key": f"{cert_base}/server.key",
            "cert_chain": f"{cert_base}/fullchain.pem",
            "ca_chain": f"{env_cert_base}/ca-chain.pem",
            "truststore_jks": f"{env_cert_base}/truststore.jks",
        }
        interpreter = _python_interpreter_for_os(spec.get("base_os", "ubuntu"))
        if interpreter:
            hostvars[hostname]["ansible_python_interpreter"] = interpreter
        # Step 5.4 — inject RDS endpoint for AWS environments
        if tofu_outputs.get("db_endpoint"):
            hostvars[hostname]["rds_endpoint"] = tofu_outputs["db_endpoint"]
        if tofu_outputs.get("db_reader_endpoint"):
            hostvars[hostname]["rds_reader_endpoint"] = tofu_outputs["db_reader_endpoint"]
        if tofu_outputs.get("db_port"):
            hostvars[hostname]["rds_port"] = tofu_outputs["db_port"]
        # See the equivalent comment in generate_ansible_inventory() above —
        # materialised into real Ansible vars by ansible_runner.py per job run.
        if inv_host and inv_host.ssh_auth_method != "shared_key" and inv_host.ssh_credential_encrypted:
            hostvars[hostname]["_ssh_auth_method"] = inv_host.ssh_auth_method
            hostvars[hostname]["_ssh_credential_encrypted"] = inv_host.ssh_credential_encrypted
        group_key = f"role_{role.replace('-', '_')}"
        role_groups.setdefault(group_key, []).append(hostname)

    inventory: dict[str, Any] = {
        "_meta": {"hostvars": hostvars},
        "all": {"hosts": all_hosts},
    }
    for group_name, group_hosts in role_groups.items():
        inventory[group_name] = {"hosts": group_hosts}

    return inventory
