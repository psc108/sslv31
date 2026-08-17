"""Ansible runner — executes playbooks as async jobs with output capture."""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.build_manager import BMJob, BMJobLog, BMEnvironment

logger = logging.getLogger(__name__)

# Track running jobs for concurrency control
_running_jobs: dict[str, asyncio.subprocess.Process] = {}

PLAYBOOK_DIR = Path("/data/playbooks")
BUILTIN_PLAYBOOK_DIR = Path("/opt/certmanager/playbooks")

# Matches Ansible's standard per-host failure lines, e.g.
# "fatal: [target-mysql]: FAILED! => {...}" / "fatal: [target-mysql]: UNREACHABLE! => {...}"
_FATAL_HOST_RE = re.compile(r"^fatal: \[([^\]]+)\]:")


def _should_auto_retry(status: str, failed_hosts: set[str] | list[str], auto_retry_count: int, max_retries: int) -> bool:
    """Only auto-retry a failure that actually named specific fatal/
    unreachable hosts — a hard config/logic error (bad playbook, missing
    role, validation failure) never gets a host-level result at all, so
    failed_hosts stays empty and this correctly leaves it as a real, final
    failure instead of retrying something that will just fail identically
    again."""
    return status == "failed" and bool(failed_hosts) and auto_retry_count < max_retries


def _strip_auto_retry_prefix(name: str) -> str:
    """Strip a previous "Auto-retry N: " prefix so retry attempt 2 reads
    "Auto-retry 2: original name" instead of stacking onto attempt 1's
    own prefixed name."""
    if name.startswith("Auto-retry ") and ": " in name:
        return name.split(": ", 1)[1]
    return name


def materialise_ssh_credentials(inventory_data: dict, job_id: str) -> list[Path]:
    """Turn the internal _ssh_auth_method/_ssh_credential_encrypted hostvar
    markers (Build Manager Hardening Plan, Stage 5 — see inventory_service.py)
    into real ansible_ssh_private_key_file/ansible_password values, in place,
    stripping the internal markers. Returns any temp key files created, so the
    caller can remove them once the job finishes — they must not outlive it."""
    from app.services.build_manager.secrets_service import decrypt_value

    credential_key_files: list[Path] = []
    for hostvars in inventory_data.get("_meta", {}).get("hostvars", {}).values():
        auth_method = hostvars.pop("_ssh_auth_method", None)
        credential_encrypted = hostvars.pop("_ssh_credential_encrypted", None)
        if not auth_method or not credential_encrypted:
            continue
        if auth_method == "private_key":
            key_material = decrypt_value(credential_encrypted)
            key_path = Path(f"/tmp/ansible_key_{job_id}_{uuid.uuid4().hex}")
            key_path.write_text(key_material)
            key_path.chmod(0o600)
            credential_key_files.append(key_path)
            hostvars["ansible_ssh_private_key_file"] = str(key_path)
        elif auth_method == "password":
            hostvars["ansible_password"] = decrypt_value(credential_encrypted)
    return credential_key_files


async def submit_job(
    db: AsyncSession, name: str, playbook: str, job_type: str = "ansible",
    environment_id: str | None = None, inventory_filter: str = "",
    extra_vars: dict | None = None, created_by: str = "system", tenant_id: str = "00000000-0000-0000-0000-000000000001",
    dry_run: bool = False, auto_retry_count: int = 0, timeout_seconds: int | None = None,
) -> BMJob:
    """Create a job record and start execution in background.

    timeout_seconds: resolved by the caller from the owning template's
    spec["ansible_timeout_minutes"] (see
    template_service.resolve_ansible_timeout_seconds) for template-driven
    builds; omitted (None) for ad-hoc jobs with no template, which fall back
    to settings.BM_ANSIBLE_TIMEOUT.

    When environment_id is set, also snapshots that environment's build
    context (OS, per-host product versions, IP allocations, certs) onto
    the job via build_snapshot_json — the environment itself may later be
    destroyed, but the job keeps a durable record of what it actually ran
    against.
    """
    build_snapshot_json = None
    if environment_id:
        from app.services.build_manager.environment_service import build_environment_snapshot
        snapshot = await build_environment_snapshot(db, environment_id)
        if snapshot:
            build_snapshot_json = json.dumps(snapshot)

    job = BMJob(
        id=str(uuid.uuid4()),
        name=name,
        job_type=job_type,
        status="pending",
        playbook=playbook,
        environment_id=environment_id,
        inventory_filter=inventory_filter,
        extra_vars=json.dumps(extra_vars or {}),
        created_by=created_by,
        tenant_id=tenant_id,
        dry_run=dry_run,
        auto_retry_count=auto_retry_count,
        timeout_seconds=timeout_seconds or settings.BM_ANSIBLE_TIMEOUT,
        build_snapshot_json=build_snapshot_json,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Check concurrency limit
    if len(_running_jobs) >= settings.BM_MAX_PARALLEL_JOBS:
        job.status = "pending"
        await db.commit()
        logger.info(f"Job {job.id} queued (max parallel reached)")
    else:
        # Start execution in background
        asyncio.create_task(_execute_job(job.id))

    return job


async def cancel_job(db: AsyncSession, job_id: str) -> BMJob:
    """Cancel a running or pending job."""
    result = await db.execute(select(BMJob).where(BMJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found")

    if job.status in ("success", "failed", "cancelled"):
        raise ValueError(f"Job already in terminal state: {job.status}")

    # Kill process if running
    proc = _running_jobs.get(job_id)
    if proc:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        _running_jobs.pop(job_id, None)

    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)
    return job


async def _execute_job(job_id: str) -> None:
    """Execute an Ansible playbook and capture output."""
    from app.core.database import async_session

    async with async_session() as db:
        result = await db.execute(select(BMJob).where(BMJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await db.commit()

        # Generate dynamic inventory file
        from app.services.build_manager.inventory_service import generate_ansible_inventory
        inventory_data = await generate_ansible_inventory(db, environment_id=job.environment_id)

        # Materialise per-host SSH credentials (Build Manager Hardening Plan,
        # Stage 5): inventory_service.py only ever emits the internal
        # _ssh_auth_method/_ssh_credential_encrypted markers so the long-lived
        # inventory never carries decrypted material — this job's ephemeral
        # inventory script is the one place they become real ansible_* vars.
        # Key files live only as long as this job run; cleaned up in `finally`.
        credential_key_files = materialise_ssh_credentials(inventory_data, job_id)

        # Host-key verification (TOFU pinning, Enhancement Plan Stage 9) —
        # only possible for environment-scoped jobs, since ad-hoc jobs (no
        # environment_id) have no way to resolve which registered SSH hosts
        # are actually in play. A dry-run still makes a real SSH connection
        # under --check, so this still applies to dry-run jobs too. Docker-
        # hosted hosts are never returned by resolve_ssh_hosts — containers
        # are recreated fresh on every build, so there's no stable identity
        # to pin against.
        known_hosts_path: Path | None = None
        if job.environment_id:
            from app.services.build_manager.host_key_service import resolve_ssh_hosts, verify_or_pin_host_key
            ssh_hosts = await resolve_ssh_hosts(db, job.environment_id)
            key_failures: list[str] = []
            known_host_lines: list[str] = []
            for ssh_host in ssh_hosts:
                ok, message = await verify_or_pin_host_key(db, ssh_host)
                if ok:
                    known_host_lines.append(ssh_host.pinned_host_key)
                else:
                    key_failures.append(message)
            if key_failures:
                job.status = "failed"
                job.finished_at = datetime.now(timezone.utc)
                for msg in key_failures:
                    db.add(BMJobLog(id=str(uuid.uuid4()), job_id=job_id, stream="stderr", line=f"Host key verification failed: {msg}"))
                from app.services.notification_service import notify_event
                await notify_event(
                    db, "bm_job_failed", tenant_id=job.tenant_id,
                    job_name=job.name, exit_code=job.exit_code, environment_id=job.environment_id or "none",
                )
                await db.commit()
                for key_path in credential_key_files:
                    key_path.unlink(missing_ok=True)
                return
            if known_host_lines:
                known_hosts_path = Path(f"/tmp/ansible_known_hosts_{job_id}")
                known_hosts_path.write_text("\n".join(known_host_lines) + "\n")

        inventory_path = Path("/data/ansible_inventory.py")
        # Write as executable dynamic inventory script
        script = '#!/opt/certmanager/venv/bin/python3\nimport json, sys\n'
        script += f'data = {json.dumps(inventory_data)}\n'
        script += 'if "--list" in sys.argv:\n    print(json.dumps(data))\n'
        script += 'elif "--host" in sys.argv:\n    host = sys.argv[sys.argv.index("--host")+1]\n'
        script += '    print(json.dumps(data.get("_meta",{}).get("hostvars",{}).get(host,{})))\n'
        script += 'else:\n    print(json.dumps(data))\n'
        inventory_path.write_text(script)
        inventory_path.chmod(0o755)

        # Build command
        playbook_path = PLAYBOOK_DIR / job.playbook
        if not playbook_path.exists():
            playbook_path = BUILTIN_PLAYBOOK_DIR / job.playbook
        if not playbook_path.exists():
            playbook_path = Path(job.playbook)

        cmd_parts = [
            "ansible-playbook", str(playbook_path),
            "--inventory", "/data/ansible_inventory.py",
            "--private-key", "/data/ssh/id_ed25519",
        ]

        # Enforce the host-key pinning verified above (Enhancement Plan
        # Stage 9) for the actual run, not just the connection-test/preflight
        # path — a pinned-but-unenforced key would be security theatre.
        if known_hosts_path:
            cmd_parts.extend(["--ssh-common-args", f"-o UserKnownHostsFile={known_hosts_path} -o StrictHostKeyChecking=yes"])

        # Write extra vars to a temp file (avoids shell escaping issues with large PEM content)
        extra_vars = json.loads(job.extra_vars) if job.extra_vars else {}

        # Inject secrets as vault_ prefixed vars (never written to disk unencrypted except this temp file)
        from app.services.build_manager.secrets_service import get_ansible_extra_vars
        secret_vars = await get_ansible_extra_vars(db)
        extra_vars.update(secret_vars)

        extra_vars_file = Path(f"/tmp/ansible_vars_{job_id}.json")
        if extra_vars:
            extra_vars_file.write_text(json.dumps(extra_vars))
            cmd_parts.extend(["--extra-vars", f"@{extra_vars_file}"])

        # Add inventory filter (limit)
        if job.inventory_filter:
            cmd_parts.extend(["--limit", job.inventory_filter])

        # Dry-run (Enhancement Plan Stage 8) — surfaces what would change
        # without touching the target. Known limitation, documented rather
        # than statically detected: command/shell tasks often report
        # inaccurately (or not at all) under --check.
        if job.dry_run:
            cmd_parts.extend(["--check", "--diff"])

        cmd = " ".join(cmd_parts)
        logger.info(f"Job {job_id} executing: {cmd}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # PYTHONUNBUFFERED matters here, not just for prettiness: with
                # stdout/stderr going to a pipe rather than a tty, ansible-playbook
                # (itself a Python process) block-buffers by default — found via a
                # real long-running job where the job's own "output" endpoint
                # stayed at 0 lines for 25+ minutes despite ansible-playbook
                # actively executing tasks over SSH the whole time, because
                # nothing had yet forced its internal buffer to flush.
                env={"ANSIBLE_CONFIG": "/data/ansible.cfg", "PATH": "/opt/certmanager/venv/bin:/usr/local/bin:/usr/bin:/bin", "HOME": "/root", "PYTHONUNBUFFERED": "1"},
            )
            _running_jobs[job_id] = proc

            # Collect output lines with periodic DB flushes
            pending_lines: list[tuple[str, str]] = []  # (stream, text)
            failed_hosts: set[str] = set()

            async def _flush_lines():
                """Write pending lines to DB."""
                nonlocal pending_lines
                if not pending_lines:
                    return
                batch = pending_lines[:]
                pending_lines = []
                for stream, text in batch:
                    db.add(BMJobLog(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        stream=stream,
                        line=text,
                    ))
                await db.commit()

            async def _read_stream(stream, stream_name):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip()
                    pending_lines.append((stream_name, text))
                    match = _FATAL_HOST_RE.match(text)
                    if match:
                        failed_hosts.add(match.group(1))
                    # Flush every 20 lines to keep DB updated for the monitor
                    if len(pending_lines) >= 20:
                        await _flush_lines()

            # Read both streams concurrently with a timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _read_stream(proc.stdout, "stdout"),
                        _read_stream(proc.stderr, "stderr"),
                    ),
                    timeout=job.timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.terminate()
                pending_lines.append(("stderr", f"Job timed out after {job.timeout_seconds}s"))

            # Flush any remaining lines
            await _flush_lines()

            # Wait for process to fully exit (should be immediate since streams are closed)
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

            job.exit_code = proc.returncode
            job.status = "success" if proc.returncode == 0 else "failed"
            job.failed_hosts = json.dumps(sorted(failed_hosts)) if failed_hosts else None

        except Exception as e:
            logger.error(f"Job {job_id} execution error: {e}")
            job.status = "failed"
            db.add(BMJobLog(
                id=str(uuid.uuid4()), job_id=job_id,
                stream="stderr", line=f"Execution error: {e}",
            ))
        finally:
            _running_jobs.pop(job_id, None)
            job.finished_at = datetime.now(timezone.utc)

            # Automatic retry (distinct from the manual POST /jobs/{id}/retry
            # endpoint) — added after live testing found this Docker host's
            # network can intermittently kill an in-progress SSH session for
            # reasons outside Ansible/this app's control — undetectable in
            # advance, but often transient enough that a later attempt
            # succeeds.
            should_auto_retry = _should_auto_retry(job.status, failed_hosts, job.auto_retry_count, settings.BM_MAX_AUTO_RETRIES)

            if not should_auto_retry and job.status == "failed":
                from app.services.notification_service import notify_event
                await notify_event(
                    db, "bm_job_failed", tenant_id=job.tenant_id,
                    job_name=job.name, exit_code=job.exit_code, environment_id=job.environment_id or "none",
                )
                # Improvements Plan Stage 21 — automated cross-job bug
                # pattern scan, same "only once the outcome is final"
                # gating as the notification above (an about-to-be-
                # auto-retried failure isn't final yet). Best-effort by
                # design (scan_for_related_bugs never raises).
                from app.services.build_manager.bug_pattern_scan import scan_for_related_bugs, maybe_auto_file_bug
                related_bug_ids = await scan_for_related_bugs(db, job)
                job.related_bug_ids_json = json.dumps(related_bug_ids)
                # Improvements Plan Stage 22 — opt-in auto bug creation,
                # reusing the scan above so a recurrence bumps the
                # existing bug instead of filing a new one. Skips dry_run
                # jobs (a --check run didn't actually fail anything real).
                # No-op unless BMSettings.auto_file_bugs_on_failure is on.
                if not job.dry_run:
                    await maybe_auto_file_bug(db, job, related_bug_ids)
            await db.commit()
            # Clean up temp vars file and any materialised SSH key files
            extra_vars_file = Path(f"/tmp/ansible_vars_{job_id}.json")
            extra_vars_file.unlink(missing_ok=True)
            for key_path in credential_key_files:
                key_path.unlink(missing_ok=True)
            if known_hosts_path:
                known_hosts_path.unlink(missing_ok=True)

        # Update environment status based on job result. Skipped for dry-run
        # jobs (nothing was actually applied) and for a job about to be
        # auto-retried — its outcome isn't final yet, so the environment
        # must stay "provisioning" rather than flickering to "failed" and
        # back if the retry succeeds.
        if job.environment_id and job.job_type == "provision" and not job.dry_run and not should_auto_retry:
            env_result = await db.execute(
                select(BMEnvironment).where(BMEnvironment.id == job.environment_id)
            )
            env = env_result.scalar_one_or_none()
            if env and env.status == "provisioning":
                env.status = "active" if job.status == "success" else "failed"
                await db.commit()

        logger.info(f"Job {job_id} finished: {job.status} (exit={job.exit_code})")

        if should_auto_retry:
            retry_number = job.auto_retry_count + 1
            logger.info(f"Job {job_id} auto-retrying (attempt {retry_number}/{settings.BM_MAX_AUTO_RETRIES}), limited to: {sorted(failed_hosts)}")
            await asyncio.sleep(settings.BM_AUTO_RETRY_DELAY_SECONDS)
            base_name = _strip_auto_retry_prefix(job.name)
            await submit_job(
                db, name=f"Auto-retry {retry_number}: {base_name}",
                playbook=job.playbook, job_type=job.job_type,
                environment_id=job.environment_id,
                inventory_filter=",".join(sorted(failed_hosts)),
                extra_vars=json.loads(job.extra_vars) if job.extra_vars else {},
                created_by=job.created_by, tenant_id=job.tenant_id,
                dry_run=job.dry_run, auto_retry_count=retry_number,
                timeout_seconds=job.timeout_seconds,
            )
