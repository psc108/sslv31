"""OpenTofu workspace management — per-environment directory under /data/tofu/."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

WORKSPACE_BASE = Path("/data/tofu")
ARCHIVE_BASE = WORKSPACE_BASE / "archive"


def get_workspace_dir(environment_name: str) -> Path:
    return WORKSPACE_BASE / environment_name


def workspace_exists(environment_name: str) -> bool:
    return get_workspace_dir(environment_name).exists()


def init_workspace(environment_name: str, tf_files: dict[str, str]) -> Path:
    """Create workspace directory and write generated .tf files."""
    workspace = get_workspace_dir(environment_name)
    workspace.mkdir(parents=True, exist_ok=True)
    for filename, content in tf_files.items():
        (workspace / filename).write_text(content, encoding="utf-8")
    return workspace


def write_var_file(environment_name: str, variables: dict) -> Path:
    """Write terraform.tfvars.json from a variables dict."""
    workspace = get_workspace_dir(environment_name)
    var_file = workspace / "terraform.tfvars.json"
    var_file.write_text(json.dumps(variables, indent=2), encoding="utf-8")
    return var_file


def archive_workspace(environment_name: str) -> Path | None:
    """Move workspace to archive directory after destroy."""
    workspace = get_workspace_dir(environment_name)
    if not workspace.exists():
        return None
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest = ARCHIVE_BASE / f"{environment_name}_{ts}"
    ARCHIVE_BASE.mkdir(parents=True, exist_ok=True)
    shutil.move(str(workspace), str(dest))
    return dest


def get_plan_file(environment_name: str) -> Path:
    return get_workspace_dir(environment_name) / "tfplan"


def plan_exists(environment_name: str) -> bool:
    return get_plan_file(environment_name).exists()
