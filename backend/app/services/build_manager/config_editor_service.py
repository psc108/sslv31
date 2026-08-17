"""Config editor service — file registry, read, metadata, validate, save."""

import configparser
import json as json_mod
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jinja2
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.build_manager import BMConfigFile, BMConfigFileVersion

logger = logging.getLogger(__name__)

# Base paths inside the container
_PLAYBOOKS = "/opt/certmanager/playbooks"
_DATA_PLAYBOOKS = "/data/playbooks"
_APP = "/opt/certmanager/app"
_DATA = "/data"

# File registry seed data: (path, display_name, category, format, purpose, editable)
_SEED_FILES: list[tuple[str, str, str, str, str, bool]] = [
    # System
    ("/data/ansible.cfg", "ansible.cfg", "system", "ini", "Ansible runtime configuration (forks, timeout, SSH args, roles path)", True),
    ("/etc/nginx/sites-available/default", "nginx site config", "system", "nginx", "Reverse proxy config for frontend + API", True),

    # Playbooks
    (f"{_PLAYBOOKS}/site.yml", "site.yml", "playbooks", "yaml", "Master playbook — orchestrates base + products", True),
    (f"{_PLAYBOOKS}/base-provision.yml", "base-provision.yml", "playbooks", "yaml", "Base host provisioning entry point", True),
    (f"{_PLAYBOOKS}/products.yml", "products.yml", "playbooks", "yaml", "Product deployment entry point", True),
    (f"{_PLAYBOOKS}/verify.yml", "verify.yml", "playbooks", "yaml", "Post-deployment TLS verification", True),

    # Roles — Tasks
    (f"{_PLAYBOOKS}/roles/base/tasks/main.yml", "base/tasks/main.yml", "roles", "yaml", "Base provisioning: Java, CA trust, certs, JKS", True),
    (f"{_PLAYBOOKS}/roles/base/handlers/main.yml", "base/handlers/main.yml", "roles", "yaml", "Handlers for CA trust updates", True),
    (f"{_PLAYBOOKS}/roles/nginx/tasks/main.yml", "nginx/tasks/main.yml", "roles", "yaml", "Nginx install + TLS config", True),
    (f"{_PLAYBOOKS}/roles/nginx/handlers/main.yml", "nginx/handlers/main.yml", "roles", "yaml", "Nginx reload/restart handlers", True),
    (f"{_PLAYBOOKS}/roles/mysql/tasks/main.yml", "mysql/tasks/main.yml", "roles", "yaml", "MySQL install + TLS + users/databases", True),
    (f"{_PLAYBOOKS}/roles/mysql/handlers/main.yml", "mysql/handlers/main.yml", "roles", "yaml", "MySQL restart handler", True),
    (f"{_PLAYBOOKS}/roles/rabbitmq/tasks/main.yml", "rabbitmq/tasks/main.yml", "roles", "yaml", "RabbitMQ install + TLS + users/vhosts", True),
    (f"{_PLAYBOOKS}/roles/rabbitmq/handlers/main.yml", "rabbitmq/handlers/main.yml", "roles", "yaml", "RabbitMQ restart handler", True),
    (f"{_PLAYBOOKS}/roles/keystone/tasks/main.yml", "keystone/tasks/main.yml", "roles", "yaml", "Keystone install (pip venv) + Apache TLS", True),
    (f"{_PLAYBOOKS}/roles/keystone/handlers/main.yml", "keystone/handlers/main.yml", "roles", "yaml", "Apache restart handler", True),
    (f"{_PLAYBOOKS}/roles/uvicorn/tasks/main.yml", "uvicorn/tasks/main.yml", "roles", "yaml", "Uvicorn/FastAPI deployment", True),
    (f"{_PLAYBOOKS}/roles/uvicorn/handlers/main.yml", "uvicorn/handlers/main.yml", "roles", "yaml", "Uvicorn restart handler", True),
    (f"{_PLAYBOOKS}/roles/nodejs/tasks/main.yml", "nodejs/tasks/main.yml", "roles", "yaml", "Node.js install (NodeSource)", True),
    (f"{_PLAYBOOKS}/roles/openjdk/tasks/main.yml", "openjdk/tasks/main.yml", "roles", "yaml", "OpenJDK verification", True),
    (f"{_PLAYBOOKS}/roles/redis/tasks/main.yml", "redis/tasks/main.yml", "roles", "yaml", "Redis install + TLS", True),
    (f"{_PLAYBOOKS}/roles/postgresql/tasks/main.yml", "postgresql/tasks/main.yml", "roles", "yaml", "PostgreSQL install + TLS", True),
    (f"{_PLAYBOOKS}/roles/mongodb/tasks/main.yml", "mongodb/tasks/main.yml", "roles", "yaml", "MongoDB install + TLS", True),
    (f"{_PLAYBOOKS}/roles/haproxy/tasks/main.yml", "haproxy/tasks/main.yml", "roles", "yaml", "HAProxy install + TLS", True),
    (f"{_PLAYBOOKS}/roles/docker_ce/tasks/main.yml", "docker_ce/tasks/main.yml", "roles", "yaml", "Docker CE install", True),
    (f"{_PLAYBOOKS}/roles/golang/tasks/main.yml", "golang/tasks/main.yml", "roles", "yaml", "Go install", True),
    (f"{_PLAYBOOKS}/roles/rust/tasks/main.yml", "rust/tasks/main.yml", "roles", "yaml", "Rust install (rustup)", True),
    (f"{_PLAYBOOKS}/roles/chrony/tasks/main.yml", "chrony/tasks/main.yml", "roles", "yaml", "NTP time sync", True),
    (f"{_PLAYBOOKS}/roles/ufw/tasks/main.yml", "ufw/tasks/main.yml", "roles", "yaml", "UFW firewall rules", True),
    (f"{_PLAYBOOKS}/roles/fail2ban/tasks/main.yml", "fail2ban/tasks/main.yml", "roles", "yaml", "Fail2Ban intrusion prevention", True),
    (f"{_PLAYBOOKS}/roles/git/tasks/main.yml", "git/tasks/main.yml", "roles", "yaml", "Git install", True),
    (f"{_PLAYBOOKS}/roles/python/tasks/main.yml", "python/tasks/main.yml", "roles", "yaml", "Python install", True),
    (f"{_PLAYBOOKS}/roles/common/tasks/sudo_users.yml", "common/sudo_users.yml", "roles", "yaml", "Sudo user creation (shared)", True),
    (f"{_PLAYBOOKS}/roles/common/tasks/file_deployments.yml", "common/file_deployments.yml", "roles", "yaml", "File deployment (shared)", True),

    # Templates (Jinja2)
    (f"{_PLAYBOOKS}/roles/nginx/templates/nginx.conf.j2", "nginx.conf.j2", "templates", "jinja2", "Nginx main config template", True),
    (f"{_PLAYBOOKS}/roles/nginx/templates/default-server.conf.j2", "default-server.conf.j2", "templates", "jinja2", "Nginx server block template", True),
    (f"{_PLAYBOOKS}/roles/rabbitmq/templates/rabbitmq.conf.j2", "rabbitmq.conf.j2", "templates", "jinja2", "RabbitMQ config template", True),
    (f"{_PLAYBOOKS}/roles/keystone/templates/keystone.conf.j2", "keystone.conf.j2", "templates", "jinja2", "Keystone config template", True),
    (f"{_PLAYBOOKS}/roles/keystone/templates/wsgi-keystone.conf.j2", "wsgi-keystone.conf.j2", "templates", "jinja2", "Apache WSGI config for Keystone", True),
    (f"{_PLAYBOOKS}/roles/uvicorn/templates/uvicorn.service.j2", "uvicorn.service.j2", "templates", "jinja2", "Systemd unit for Uvicorn", True),
    (f"{_APP}/templates/bundle_readme.txt.j2", "bundle_readme.txt.j2", "templates", "jinja2", "README included in cert bundle ZIPs", True),
    (f"{_APP}/templates/provisioning/mysql_ssl_cnf.j2", "mysql_ssl_cnf.j2", "templates", "jinja2", "MySQL SSL config snippet generator", True),
    (f"{_APP}/templates/provisioning/rabbitmq_ssl_conf.j2", "rabbitmq_ssl_conf.j2", "templates", "jinja2", "RabbitMQ SSL config snippet generator", True),
    (f"{_APP}/templates/provisioning/spring_boot_ssl.j2", "spring_boot_ssl.j2", "templates", "jinja2", "Spring Boot SSL properties generator", True),

    # Docker
    ("/opt/certmanager/docker-compose.build-manager.yml", "docker-compose.build-manager.yml", "docker", "yaml", "Docker Compose for Build Manager dev environment", True),

    # Generated/Runtime (read-only)
    ("/data/ansible_inventory.py", "ansible_inventory.py", "generated", "python", "Dynamic Ansible inventory script (auto-generated per job)", False),
    ("/data/.master_key", ".master_key", "generated", "text", "Fernet encryption key", False),
    ("/data/.api_key", ".api_key", "generated", "text", "Legacy API key", False),
]


async def seed_file_registry(db: AsyncSession) -> int:
    """Populate the file registry with known config files. Idempotent."""
    existing = await db.execute(select(BMConfigFile.path))
    existing_paths = {r[0] for r in existing.all()}

    added = 0
    for path, display_name, category, fmt, purpose, editable in _SEED_FILES:
        if path in existing_paths:
            continue
        db.add(BMConfigFile(
            id=str(uuid.uuid4()),
            path=path,
            display_name=display_name,
            category=category,
            format=fmt,
            purpose=purpose,
            editable=editable,
        ))
        added += 1

    if added:
        await db.commit()
    return added


async def list_files(db: AsyncSession, category: str | None = None) -> list[dict[str, Any]]:
    """List all registered config files with metadata."""
    query = select(BMConfigFile).order_by(BMConfigFile.category, BMConfigFile.display_name)
    if category:
        query = query.where(BMConfigFile.category == category)
    result = await db.execute(query)
    files = result.scalars().all()

    out = []
    for f in files:
        p = Path(f.path)
        out.append({
            "id": f.id,
            "path": f.path,
            "display_name": f.display_name,
            "category": f.category,
            "format": f.format,
            "purpose": f.purpose,
            "editable": f.editable,
            "exists": p.exists(),
            "size": p.stat().st_size if p.exists() else 0,
            "last_modified_by": f.last_modified_by or None,
            "last_modified_at": f.last_modified_at.isoformat() if f.last_modified_at else None,
        })
    return out


async def read_file(db: AsyncSession, file_id: str) -> dict[str, Any]:
    """Read file content from disk."""
    result = await db.execute(select(BMConfigFile).where(BMConfigFile.id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise ValueError("File not found in registry")

    # Sensitive files: return metadata only, no content
    if f.path in ("/data/.master_key", "/data/.api_key"):
        return {
            "id": f.id,
            "path": f.path,
            "display_name": f.display_name,
            "category": f.category,
            "format": f.format,
            "purpose": f.purpose,
            "editable": False,
            "content": "*** SENSITIVE — content hidden ***",
            "exists": Path(f.path).exists(),
            "size": 0,
        }

    p = Path(f.path)
    if not p.exists():
        return {
            "id": f.id,
            "path": f.path,
            "display_name": f.display_name,
            "category": f.category,
            "format": f.format,
            "purpose": f.purpose,
            "editable": f.editable,
            "content": "",
            "exists": False,
            "size": 0,
        }

    content = p.read_text(encoding="utf-8", errors="replace")
    return {
        "id": f.id,
        "path": f.path,
        "display_name": f.display_name,
        "category": f.category,
        "format": f.format,
        "purpose": f.purpose,
        "editable": f.editable,
        "content": content,
        "exists": True,
        "size": len(content),
        "last_modified_by": f.last_modified_by or None,
        "last_modified_at": f.last_modified_at.isoformat() if f.last_modified_at else None,
    }


async def validate_file(db: AsyncSession, file_id: str, content: str) -> dict[str, Any]:
    """Validate file content by format. Returns {valid, errors}."""
    result = await db.execute(select(BMConfigFile).where(BMConfigFile.id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise ValueError("File not found in registry")

    errors = _validate_content(f.format, content)
    return {"valid": len(errors) == 0, "errors": errors}


def _validate_content(fmt: str, content: str) -> list[dict[str, Any]]:
    """Syntax-check content based on format. Returns list of error dicts."""
    errors: list[dict[str, Any]] = []
    try:
        if fmt == "yaml":
            yaml.safe_load(content)
        elif fmt == "json":
            json_mod.loads(content)
        elif fmt == "ini":
            cp = configparser.ConfigParser()
            cp.read_string(content)
        elif fmt == "jinja2":
            jinja2.Environment().parse(content)
    except yaml.YAMLError as e:
        line = getattr(e, "problem_mark", None)
        errors.append({"line": line.line + 1 if line else 1, "message": str(e)})
    except json_mod.JSONDecodeError as e:
        errors.append({"line": e.lineno or 1, "message": e.msg})
    except configparser.Error as e:
        errors.append({"line": 1, "message": str(e)})
    except jinja2.TemplateSyntaxError as e:
        errors.append({"line": e.lineno or 1, "message": e.message})
    except Exception as e:
        errors.append({"line": 1, "message": str(e)})
    return errors


async def save_file(db: AsyncSession, file_id: str, content: str, username: str, comment: str = "") -> dict[str, Any]:
    """Validate, backup, write, and record version."""
    result = await db.execute(select(BMConfigFile).where(BMConfigFile.id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise ValueError("File not found in registry")
    if not f.editable:
        raise PermissionError("File is read-only")

    # Validate before saving
    errors = _validate_content(f.format, content)
    if errors:
        return {"saved": False, "errors": errors}

    target = Path(f.path)
    backup_path_str = None

    # Read old content for diff
    old_content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""

    # Create backup
    if target.exists():
        backup_dir = Path("/data/editor-backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        safe_name = target.name.replace("/", "_")
        backup_path = backup_dir / f"{safe_name}.bak.{ts}"
        shutil.copy2(target, backup_path)
        backup_path_str = str(backup_path)

    # Atomic write: write to temp then rename
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(target)

    # Record version
    diff_patch = _generate_diff(old_content, content, f.path)
    next_version = await _next_version_number(db, file_id)
    db.add(BMConfigFileVersion(
        file_id=file_id,
        version=next_version,
        content=content,
        diff_patch=diff_patch,
        edited_by=username,
        edited_at=datetime.now(timezone.utc),
        comment=comment,
    ))

    # Update metadata
    f.last_modified_by = username
    f.last_modified_at = datetime.now(timezone.utc)
    await db.commit()

    return {"saved": True, "errors": [], "backup": backup_path_str, "version": next_version}


def _generate_diff(old: str, new: str, filename: str) -> str:
    """Generate unified diff between old and new content."""
    import difflib
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}")
    return "".join(diff)


async def _next_version_number(db: AsyncSession, file_id: str) -> int:
    """Get the next version number for a file."""
    from sqlalchemy import func as sa_func
    result = await db.execute(
        select(sa_func.max(BMConfigFileVersion.version)).where(BMConfigFileVersion.file_id == file_id)
    )
    max_v = result.scalar()
    return (max_v or 0) + 1


async def get_file_history(db: AsyncSession, file_id: str) -> list[dict[str, Any]]:
    """List all versions of a file."""
    result = await db.execute(
        select(BMConfigFileVersion)
        .where(BMConfigFileVersion.file_id == file_id)
        .order_by(BMConfigFileVersion.version.desc())
    )
    versions = result.scalars().all()
    return [{
        "version": v.version,
        "edited_by": v.edited_by,
        "edited_at": v.edited_at.isoformat() if v.edited_at else None,
        "comment": v.comment,
        "has_diff": bool(v.diff_patch),
    } for v in versions]


async def get_file_version(db: AsyncSession, file_id: str, version: int) -> dict[str, Any]:
    """Retrieve a specific version's content."""
    result = await db.execute(
        select(BMConfigFileVersion)
        .where(BMConfigFileVersion.file_id == file_id, BMConfigFileVersion.version == version)
    )
    v = result.scalar_one_or_none()
    if not v:
        raise ValueError(f"Version {version} not found")
    return {
        "version": v.version,
        "content": v.content,
        "diff_patch": v.diff_patch,
        "edited_by": v.edited_by,
        "edited_at": v.edited_at.isoformat() if v.edited_at else None,
        "comment": v.comment,
    }


async def restore_file(db: AsyncSession, file_id: str, version: int, username: str) -> dict[str, Any]:
    """Restore a file to a previous version (creates a new version)."""
    ver_data = await get_file_version(db, file_id, version)
    return await save_file(db, file_id, ver_data["content"], username, comment=f"Restored from version {version}")


async def diff_versions(db: AsyncSession, file_id: str, v1: int, v2: int) -> dict[str, Any]:
    """Generate unified diff between two versions."""
    ver1 = await get_file_version(db, file_id, v1)
    ver2 = await get_file_version(db, file_id, v2)
    # Get file path for diff header
    result = await db.execute(select(BMConfigFile.path).where(BMConfigFile.id == file_id))
    path = result.scalar() or "unknown"
    diff = _generate_diff(ver1["content"], ver2["content"], path)
    return {"diff": diff, "from_version": v1, "to_version": v2}


async def get_file_metadata(db: AsyncSession, file_id: str) -> dict[str, Any]:
    """Get file metadata without content."""
    result = await db.execute(select(BMConfigFile).where(BMConfigFile.id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise ValueError("File not found in registry")

    p = Path(f.path)
    return {
        "id": f.id,
        "path": f.path,
        "display_name": f.display_name,
        "category": f.category,
        "format": f.format,
        "purpose": f.purpose,
        "editable": f.editable,
        "exists": p.exists(),
        "size": p.stat().st_size if p.exists() else 0,
        "last_modified_by": f.last_modified_by or None,
        "last_modified_at": f.last_modified_at.isoformat() if f.last_modified_at else None,
    }
