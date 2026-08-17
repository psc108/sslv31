"""OpenTofu runner — executes tofu commands as async jobs with output capture.

Mirrors the ansible_runner.py pattern: creates a BMJob record, runs the
subprocess in the background, streams stdout/stderr line-by-line into
BMJobLog, and updates job status on completion.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.build_manager import BMJob, BMJobLog

logger = logging.getLogger(__name__)

# Tofu timeout defaults (seconds) — tofu apply on a full stack can take 30+ min
TOFU_PLAN_TIMEOUT    = 300    # 5 min
TOFU_APPLY_TIMEOUT   = 7200  # 2 hr
TOFU_DESTROY_TIMEOUT = 3600  # 1 hr
TOFU_INIT_TIMEOUT    = 300   # 5 min


async def submit_tofu_job(
    db: AsyncSession,
    name: str,
    job_type: str,
    environment_id: str,
    workspace_dir: Path,
    tofu_cmd: list[str],
    created_by: str = "system",
    timeout_seconds: int | None = None,
) -> BMJob:
    """Create a BMJob record and start the tofu command in the background."""
    if timeout_seconds is None:
        timeout_seconds = {
            "tofu_plan":    TOFU_PLAN_TIMEOUT,
            "tofu_apply":   TOFU_APPLY_TIMEOUT,
            "tofu_destroy": TOFU_DESTROY_TIMEOUT,
            "tofu_init":    TOFU_INIT_TIMEOUT,
        }.get(job_type, TOFU_APPLY_TIMEOUT)

    job = BMJob(
        id=str(uuid.uuid4()),
        name=name,
        job_type=job_type,
        status="pending",
        playbook="",          # not used for tofu jobs
        environment_id=environment_id,
        extra_vars=json.dumps({"workspace": str(workspace_dir), "cmd": tofu_cmd}),
        created_by=created_by,
        tenant_id="00000000-0000-0000-0000-000000000001",
        timeout_seconds=timeout_seconds,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    asyncio.create_task(_execute_tofu_job(job.id, workspace_dir, tofu_cmd))
    return job


async def _execute_tofu_job(
    job_id: str,
    workspace_dir: Path,
    tofu_cmd: list[str],
) -> None:
    """Execute a tofu command and stream output into BMJobLog."""
    from app.core.database import async_session
    from app.services.build_manager.aws_credentials import get_credential_env

    async with async_session() as db:
        from sqlalchemy import select
        result = await db.execute(select(BMJob).where(BMJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await db.commit()

        # Build environment: inherit process env + AWS credentials
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/root",
        }
        try:
            env.update(get_credential_env())
        except Exception:
            pass  # credentials may not be set for non-AWS jobs

        pending_lines: list[tuple[str, str]] = []

        async def _flush():
            nonlocal pending_lines
            if not pending_lines:
                return
            batch, pending_lines = pending_lines[:], []
            for stream, text in batch:
                db.add(BMJobLog(id=str(uuid.uuid4()), job_id=job_id, stream=stream, line=text))
            await db.commit()

        async def _read(stream, name: str):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                pending_lines.append((name, text))
                if len(pending_lines) >= 20:
                    await _flush()

        try:
            proc = await asyncio.create_subprocess_exec(
                *tofu_cmd,
                cwd=str(workspace_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _read(proc.stdout, "stdout"),
                        _read(proc.stderr, "stderr"),
                    ),
                    timeout=job.timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.terminate()
                pending_lines.append(("stderr", f"Job timed out after {job.timeout_seconds}s"))

            await _flush()

            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

            job.exit_code = proc.returncode
            job.status = "success" if proc.returncode == 0 else "failed"

        except Exception as exc:
            logger.error("Tofu job %s error: %s", job_id, exc)
            job.status = "failed"
            db.add(BMJobLog(id=str(uuid.uuid4()), job_id=job_id, stream="stderr", line=str(exc)))

        job.finished_at = datetime.now(timezone.utc)
        await db.commit()

        # After a successful apply, issue certs for the environment
        if job.status == "success" and job.job_type == "tofu_apply" and job.environment_id:
            try:
                await _post_apply_certs(db, job.environment_id, workspace_dir, job_id)
            except Exception as exc:
                logger.error("Post-apply cert issuance failed for env %s: %s", job.environment_id, exc)
                db.add(BMJobLog(
                    id=str(uuid.uuid4()), job_id=job_id, stream="stderr",
                    line=f"[cert-integration] WARNING: cert issuance failed: {exc}",
                ))
                await db.commit()


async def run_tofu_output(workspace_dir: Path) -> dict:
    """Run `tofu output -json` and return parsed dict. Raises on failure."""
    from app.services.build_manager.aws_credentials import get_credential_env
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/root"}
    try:
        env.update(get_credential_env())
    except Exception:
        pass

    proc = await asyncio.create_subprocess_exec(
        "tofu", "output", "-json",
        cwd=str(workspace_dir),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"tofu output failed: {stderr.decode()}")
    raw = json.loads(stdout)
    # Unwrap: tofu output -json returns {"key": {"value": ..., "type": ...}}
    return {k: v["value"] for k, v in raw.items()}


async def _post_apply_certs(
    db,
    environment_id: str,
    workspace_dir: Path,
    job_id: str,
) -> None:
    """Issue TLS certs for all hosts after a successful tofu apply.

    Reads private IPs from tofu output, issues certs via cert_integration,
    and writes a summary log line to the job.
    """
    import json as _json
    from sqlalchemy import select as _select
    from app.models.build_manager import BMEnvironment, BMTemplateVersion, BMJobLog
    from app.services.build_manager.cert_integration import (
        issue_environment_certs,
        export_trust_bundle,
    )

    env_result = await db.execute(_select(BMEnvironment).where(BMEnvironment.id == environment_id))
    env = env_result.scalar_one_or_none()
    if not env:
        return

    ver_result = await db.execute(
        _select(BMTemplateVersion).where(
            BMTemplateVersion.template_id == env.template_id,
            BMTemplateVersion.version == env.template_version,
        )
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        return

    spec = _json.loads(version.spec)
    aws_config = spec.get("aws", {})
    variables = _json.loads(env.variables) if env.variables else {}
    signing_ca_id = variables.get("signing_ca_id")
    validity_days = spec.get("certificates", {}).get("validity_days", 365)

    # Read private IPs from tofu outputs
    try:
        outputs = await run_tofu_output(workspace_dir)
    except Exception:
        outputs = {}

    private_ips: dict[str, str] = outputs.get("private_ips") or {}

    # Fall back to ip_allocations for on-prem/Docker or if tofu outputs empty
    ip_allocations = _json.loads(env.ip_allocations) if env.ip_allocations else {}
    ip_map = {**ip_allocations, **private_ips}

    db.add(BMJobLog(
        id=str(uuid.uuid4()), job_id=job_id, stream="stdout",
        line="[cert-integration] Issuing TLS certificates for environment hosts...",
    ))
    await db.commit()

    serials = await issue_environment_certs(
        db=db,
        environment_id=environment_id,
        environment_name=env.name,
        hosts=spec.get("hosts", []),
        ip_map=ip_map,
        signing_ca_id=signing_ca_id,
        validity_days=validity_days,
        tofu_outputs=outputs if aws_config else None,
        aws_config=aws_config if aws_config else None,
    )

    await export_trust_bundle(db, env.name, signing_ca_id)

    db.add(BMJobLog(
        id=str(uuid.uuid4()), job_id=job_id, stream="stdout",
        line=f"[cert-integration] Issued {len(serials)} certificate(s): {', '.join(serials.keys())}",
    ))
    await db.commit()
