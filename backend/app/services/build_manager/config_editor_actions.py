"""Config editor file actions — post-save actions (reload, re-run, validate)."""

import asyncio
import logging
import subprocess
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.build_manager import BMConfigFile

logger = logging.getLogger(__name__)

_PLAYBOOKS = "/opt/certmanager/playbooks"


# Action definitions keyed by file path pattern
# Each action: {id, label, icon, type, config}
def _get_actions_for_path(path: str) -> list[dict[str, Any]]:
    """Return available actions based on file path."""
    actions: list[dict[str, Any]] = []

    # Nginx configs → reload nginx
    if "nginx" in path and ("/etc/nginx/" in path or "nginx.conf" in path):
        actions.append({
            "id": "reload_nginx",
            "label": "Reload Nginx",
            "icon": "🔄",
            "type": "local_command",
            "description": "Test config and reload Nginx (nginx -t && nginx -s reload)",
        })

    # Ansible playbooks → syntax check
    if path.startswith(_PLAYBOOKS) and path.endswith(".yml"):
        actions.append({
            "id": "validate_ansible",
            "label": "Ansible Syntax Check",
            "icon": "✓",
            "type": "local_command",
            "description": "Run ansible-playbook --syntax-check on this file",
        })

    # Playbook files (not roles) → run playbook
    if path.startswith(f"{_PLAYBOOKS}/") and "/roles/" not in path and path.endswith(".yml"):
        actions.append({
            "id": "run_playbook",
            "label": "Run Playbook",
            "icon": "▶️",
            "type": "submit_job",
            "description": "Submit a Build Manager job to execute this playbook",
        })

    # Role tasks → run site.yml (re-deploy)
    if "/roles/" in path and "/tasks/" in path:
        actions.append({
            "id": "run_site",
            "label": "Re-run Deployment",
            "icon": "🚀",
            "type": "submit_job",
            "description": "Run site.yml to re-deploy all roles (includes this change)",
        })

    # ansible.cfg → validate
    if path.endswith("ansible.cfg"):
        actions.append({
            "id": "validate_ansible_cfg",
            "label": "Validate Config",
            "icon": "✓",
            "type": "local_command",
            "description": "Run ansible --version to verify config is parseable",
        })

    return actions


async def get_file_actions(db: AsyncSession, file_id: str) -> list[dict[str, Any]]:
    """Get available post-save actions for a file."""
    result = await db.execute(select(BMConfigFile).where(BMConfigFile.id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise ValueError("File not found in registry")
    return _get_actions_for_path(f.path)


async def execute_action(
    db: AsyncSession, file_id: str, action_id: str
) -> dict[str, Any]:
    """Execute a post-save action. Returns {success, output, error}."""
    result = await db.execute(select(BMConfigFile).where(BMConfigFile.id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise ValueError("File not found in registry")

    actions = _get_actions_for_path(f.path)
    action = next((a for a in actions if a["id"] == action_id), None)
    if not action:
        raise ValueError(f"Action '{action_id}' not available for this file")

    if action_id == "reload_nginx":
        return await _exec_reload_nginx()
    elif action_id == "validate_ansible":
        return await _exec_validate_ansible(f.path)
    elif action_id == "validate_ansible_cfg":
        return await _exec_validate_ansible_cfg()
    elif action_id == "run_playbook":
        return await _exec_run_playbook(db, f.path)
    elif action_id == "run_site":
        return await _exec_run_playbook(db, f"{_PLAYBOOKS}/site.yml")
    else:
        return {"success": False, "output": "", "error": f"Unknown action: {action_id}"}


async def _exec_reload_nginx() -> dict[str, Any]:
    """Test nginx config and reload."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "nginx", "-t",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return {
                "success": False,
                "output": stderr.decode(errors="replace"),
                "error": "nginx -t failed — config not reloaded",
            }

        proc2 = await asyncio.create_subprocess_exec(
            "nginx", "-s", "reload",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout2, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=10)
        if proc2.returncode != 0:
            return {
                "success": False,
                "output": stderr2.decode(errors="replace"),
                "error": "nginx -s reload failed",
            }

        return {"success": True, "output": "nginx: configuration test passed, reload successful", "error": ""}
    except asyncio.TimeoutError:
        return {"success": False, "output": "", "error": "Command timed out"}
    except FileNotFoundError:
        return {"success": False, "output": "", "error": "nginx binary not found"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


async def _exec_validate_ansible(playbook_path: str) -> dict[str, Any]:
    """Run ansible-playbook --syntax-check."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ansible-playbook", "--syntax-check", playbook_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "ANSIBLE_CONFIG": "/data/ansible.cfg"},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        if proc.returncode == 0:
            return {"success": True, "output": output.strip() or "Syntax check passed", "error": ""}
        return {"success": False, "output": output.strip(), "error": "Syntax check failed"}
    except asyncio.TimeoutError:
        return {"success": False, "output": "", "error": "Syntax check timed out (30s)"}
    except FileNotFoundError:
        return {"success": False, "output": "", "error": "ansible-playbook binary not found"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


async def _exec_validate_ansible_cfg() -> dict[str, Any]:
    """Validate ansible.cfg by running ansible --version."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ansible", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "ANSIBLE_CONFIG": "/data/ansible.cfg"},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        output = stdout.decode(errors="replace")
        if proc.returncode == 0:
            # Extract first line (version)
            first_line = output.split("\n")[0] if output else "OK"
            return {"success": True, "output": first_line, "error": ""}
        return {"success": False, "output": stderr.decode(errors="replace"), "error": "Config validation failed"}
    except asyncio.TimeoutError:
        return {"success": False, "output": "", "error": "Command timed out"}
    except FileNotFoundError:
        return {"success": False, "output": "", "error": "ansible binary not found"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


async def _exec_run_playbook(db: AsyncSession, playbook_path: str) -> dict[str, Any]:
    """Submit a Build Manager job to run a playbook."""
    try:
        from app.services.build_manager.ansible_runner import submit_job
        import os

        playbook_name = os.path.basename(playbook_path)
        job = await submit_job(
            db=db,
            name=f"Editor: run {playbook_name}",
            playbook=playbook_name,
            extra_vars={},
            job_type="playbook",
        )
        return {
            "success": True,
            "output": f"Job submitted: {job.id}",
            "error": "",
            "job_id": job.id,
        }
    except Exception as e:
        return {"success": False, "output": "", "error": f"Failed to submit job: {e}"}
