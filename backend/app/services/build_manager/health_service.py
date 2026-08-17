"""Health service — per-service health checks and environment status rollup."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.build_manager import (
    BMEnvironment, BMHealthCheck, BMTemplateVersion, BMCertBinding,
)

logger = logging.getLogger(__name__)

# Service-specific check commands run via SSH on target hosts
SERVICE_CHECKS = {
    "nginx": "systemctl is-active nginx && curl -sk https://localhost/ -o /dev/null -w '%{http_code}' 2>/dev/null || echo 'DOWN'",
    "mysql": "systemctl is-active mysql && mysqladmin ping --silent 2>/dev/null || echo 'DOWN'",
    "rabbitmq": "systemctl is-active rabbitmq-server && rabbitmqctl status --quiet 2>/dev/null | head -1 || echo 'DOWN'",
    "keystone": "systemctl is-active apache2 && curl -sk https://localhost:5000/v3/ -o /dev/null -w '%{http_code}' 2>/dev/null || echo 'DOWN'",
    "uvicorn": "systemctl is-active uvicorn 2>/dev/null || systemctl is-active backend 2>/dev/null || curl -sk https://localhost:8000/health -o /dev/null -w '%{http_code}' 2>/dev/null || echo 'DOWN'",
    "generic": "echo 'OK'",
}


async def run_health_checks(db: AsyncSession, environment_id: str) -> list[dict]:
    """Run health checks for all hosts in an environment and store results."""
    env_result = await db.execute(
        select(BMEnvironment).where(BMEnvironment.id == environment_id)
    )
    env = env_result.scalar_one_or_none()
    if not env:
        raise ValueError("Environment not found")

    if env.status not in ("active", "degraded", "provisioning"):
        raise ValueError(f"Environment is '{env.status}' — health checks only run on active/degraded environments")

    # Get template spec for host definitions
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
    ip_allocations = json.loads(env.ip_allocations) if env.ip_allocations else {}

    # Clear old checks for this environment
    await db.execute(
        delete(BMHealthCheck).where(BMHealthCheck.environment_id == environment_id)
    )

    # Resolve registered BMHost records (per-host SSH credentials) for any
    # host_def that references one — same inventory_host_id convention
    # inventory_service.py's environment inventory generator uses.
    from app.models.build_manager import BMHost
    inventory_host_ids = [h["inventory_host_id"] for h in spec.get("hosts", []) if h.get("inventory_host_id")]
    inv_hosts_map: dict[str, BMHost] = {}
    if inventory_host_ids:
        inv_result = await db.execute(select(BMHost).where(BMHost.id.in_(inventory_host_ids)))
        for ih in inv_result.scalars().all():
            inv_hosts_map[ih.id] = ih

    results = []
    now = datetime.now(timezone.utc)

    for host_def in spec.get("hosts", []):
        role = host_def["role"]
        products = host_def.get("products", [])
        inv_host = inv_hosts_map.get(host_def.get("inventory_host_id", ""))
        auth_method = inv_host.ssh_auth_method if inv_host else "shared_key"
        credential_encrypted = inv_host.ssh_credential_encrypted if inv_host else None

        # Determine service types to check
        service_types = set()
        for p in products:
            product_name = p.get("ansible_role", p.get("product_name", p.get("product", "")))
            if product_name in SERVICE_CHECKS:
                service_types.add(product_name)
        if not service_types:
            service_types.add("generic")

        # Determine ansible host (container name or IP)
        ansible_host = f"target-{role}"
        host_ip = ip_allocations.get(role, "")

        for svc in service_types:
            check_cmd = SERVICE_CHECKS.get(svc, SERVICE_CHECKS["generic"])
            status, details = await _run_ssh_check(ansible_host, check_cmd, auth_method, credential_encrypted)

            check = BMHealthCheck(
                id=str(uuid.uuid4()),
                environment_id=environment_id,
                host_role=role,
                service_type=svc,
                check_type="health",
                status=status,
                details=json.dumps(details),
                last_checked=now,
            )
            db.add(check)
            results.append(_check_to_dict(check))

    # Update environment status based on results
    previous_status = env.status
    statuses = [r["status"] for r in results]
    if all(s == "healthy" for s in statuses):
        env.status = "active"
    elif any(s == "down" for s in statuses):
        env.status = "degraded"

    if env.status == "degraded" and previous_status != "degraded":
        from app.services.notification_service import notify_event
        await notify_event(
            db, "bm_environment_degraded", tenant_id=env.tenant_id,
            environment_name=env.name, environment_id=env.id,
        )

    await db.commit()
    return results


async def get_health_results(db: AsyncSession, environment_id: str) -> list[dict]:
    """Get cached health check results for an environment."""
    result = await db.execute(
        select(BMHealthCheck)
        .where(BMHealthCheck.environment_id == environment_id)
        .order_by(BMHealthCheck.host_role, BMHealthCheck.service_type)
    )
    return [_check_to_dict(c) for c in result.scalars().all()]


async def get_all_health(db: AsyncSession) -> list[dict]:
    """Get health across all active environments."""
    result = await db.execute(
        select(BMHealthCheck)
        .join(BMEnvironment, BMHealthCheck.environment_id == BMEnvironment.id)
        .where(BMEnvironment.status.in_(["active", "degraded"]))
        .order_by(BMHealthCheck.last_checked.desc())
    )
    return [_check_to_dict(c) for c in result.scalars().all()]


async def get_drift_report(db: AsyncSession, environment_id: str) -> dict:
    """Compare deployed state vs template spec for drift detection."""
    env_result = await db.execute(
        select(BMEnvironment).where(BMEnvironment.id == environment_id)
    )
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

    # Check cert bindings expiry
    bindings_result = await db.execute(
        select(BMCertBinding).where(BMCertBinding.environment_id == environment_id)
    )
    bindings = bindings_result.scalars().all()

    now = datetime.now(timezone.utc)
    drift_items = []

    # Check: do all expected hosts have cert bindings?
    expected_roles = {h["role"] for h in spec.get("hosts", [])}
    bound_roles = {b.role for b in bindings}
    missing_certs = expected_roles - bound_roles
    for role in missing_certs:
        drift_items.append({
            "type": "missing_cert",
            "role": role,
            "severity": "high",
            "message": f"Host '{role}' has no cert binding — may not have been provisioned",
        })

    # Check: cert expiry drift
    from datetime import timedelta
    for b in bindings:
        if b.expires_at and b.expires_at < now:
            drift_items.append({
                "type": "expired_cert",
                "role": b.role,
                "severity": "critical",
                "message": f"Certificate for '{b.role}' ({b.cert_type}) expired {(now - b.expires_at).days} days ago",
            })
        elif b.expires_at and b.expires_at < now + timedelta(days=7):
            drift_items.append({
                "type": "expiring_cert",
                "role": b.role,
                "severity": "warning",
                "message": f"Certificate for '{b.role}' ({b.cert_type}) expires in {(b.expires_at - now).days} days",
            })

    # Check: template version drift (is there a newer version?)
    latest_result = await db.execute(
        select(BMTemplateVersion)
        .where(BMTemplateVersion.template_id == env.template_id, BMTemplateVersion.is_current == True)
    )
    latest = latest_result.scalar_one_or_none()
    if latest and latest.version > env.template_version:
        drift_items.append({
            "type": "template_outdated",
            "role": "_environment",
            "severity": "info",
            "message": f"Running template v{env.template_version}, latest is v{latest.version}",
        })

    return {
        "environment_id": environment_id,
        "environment_name": env.name,
        "template_version": env.template_version,
        "checked_at": now.isoformat(),
        "drift_count": len(drift_items),
        "items": drift_items,
    }


async def _run_ssh_check(
    host: str, command: str, auth_method: str = "shared_key", credential_encrypted: str | None = None,
) -> tuple[str, dict]:
    """Run a health check command via SSH. Returns (status, details_dict).

    auth_method/credential_encrypted select the per-host credential (Build
    Manager Hardening Plan, Stage 5) — defaults preserve the original
    shared-key behaviour for hosts with no registered BMHost record (pure
    Docker-target environments) or that haven't opted into their own.
    """
    from app.services.build_manager.ssh_credentials import SSHCredential

    try:
        async with SSHCredential(auth_method, credential_encrypted) as cred:
            sshpass_prefix = cred.sshpass_prefix()
            args = [*sshpass_prefix, "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5"]
            if sshpass_prefix:
                args += ["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"]
            args += cred.key_args()
            args += [f"root@{host}", command]

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        output = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode == 0 and "DOWN" not in output:
            status = "healthy"
        else:
            status = "down"

        return status, {"output": output[:500], "error": err[:200], "exit_code": proc.returncode}
    except asyncio.TimeoutError:
        return "down", {"output": "", "error": "SSH timeout (15s)", "exit_code": -1}
    except Exception as e:
        return "unknown", {"output": "", "error": str(e)[:200], "exit_code": -1}


def _check_to_dict(c: BMHealthCheck) -> dict:
    return {
        "id": c.id,
        "environment_id": c.environment_id,
        "host_role": c.host_role,
        "service_type": c.service_type,
        "check_type": c.check_type,
        "status": c.status,
        "details": json.loads(c.details) if c.details else {},
        "last_checked": c.last_checked.isoformat() if c.last_checked else None,
    }
