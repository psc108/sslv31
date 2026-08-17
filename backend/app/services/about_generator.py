"""Auto-detects every open-source product LabTool ships with, and its
exact installed version, to regenerate the About page (app/api/v1/about.py's
POST /about/regenerate) without an admin hand-transcribing `pip freeze`
output every time.

Three different detection strategies, one per source of truth:

  - Backend Python packages: `importlib.metadata` — always reflects exactly
    what's installed in *this* venv, right now (stdlib, no extra dependency,
    no subprocess).
  - Frontend packages: parses the `package.json`/`package-lock.json` pair
    the Dockerfile copies into the runtime image (see docker/Dockerfile) —
    package.json says *which* packages are shipped (`dependencies`, not
    `devDependencies`), package-lock.json says the exact resolved version of
    each.
  - Everything else (Java, nginx, OpenTofu, Ansible, the base OS) — these
    aren't Python or npm packages, so they're queried the same way a human
    would: running the tool's own `--version`-equivalent flag and parsing
    the output. CFR/Vineflower are the one exception: they're plain jars
    with no version flag, so their version only survives in a small file
    baked in at Docker build time from the build ARGs (see the Dockerfile).

Every lookup is independently best-effort — a missing binary, a moved file,
or an unexpected output format degrades that one line to "(version not
detected)" rather than failing the whole regenerate action. This runs against
a live production container; a partial page is far better than a 500.
"""
from __future__ import annotations

import json
import re
import subprocess
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

_UNKNOWN = "(version not detected)"

_FRONTEND_META_DIR = Path("/opt/certmanager/frontend-meta")
_BUNDLED_TOOLS_MANIFEST = Path("/opt/certmanager/tools/bundled_tool_versions.json")
_OS_RELEASE = Path("/etc/os-release")


def _pip_version(dist_name: str) -> str:
    try:
        return importlib_metadata.version(dist_name)
    except importlib_metadata.PackageNotFoundError:
        return _UNKNOWN


def _run(cmd: list[str]) -> str | None:
    """Runs a version-probing command, combining stdout+stderr (several of
    these — java -version, nginx -v — write to stderr despite exiting 0).
    Returns None on any failure (binary missing, non-zero exit, timeout)
    rather than raising, since every caller treats "couldn't detect" as a
    normal, expected outcome."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, check=False,
        )
        combined = (result.stdout or "") + (result.stderr or "")
        return combined.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _extract(pattern: str, text: str | None) -> str:
    if not text:
        return _UNKNOWN
    m = re.search(pattern, text)
    return m.group(1) if m else _UNKNOWN


def _frontend_versions() -> dict[str, str]:
    """Maps npm package name -> resolved version, for every entry in
    package.json's `dependencies` (not `devDependencies` — those aren't
    shipped in the built bundle). Returns {} if the manifest files aren't
    present (e.g. running outside the Docker image, or an image built
    before the Dockerfile started copying them in)."""
    pkg_path = _FRONTEND_META_DIR / "package.json"
    lock_path = _FRONTEND_META_DIR / "package-lock.json"
    if not pkg_path.exists() or not lock_path.exists():
        return {}
    try:
        deps = json.loads(pkg_path.read_text(encoding="utf-8")).get("dependencies", {})
        lock_packages = json.loads(lock_path.read_text(encoding="utf-8")).get("packages", {})
    except (json.JSONDecodeError, OSError):
        return {}
    versions: dict[str, str] = {}
    for name in deps:
        info = lock_packages.get(f"node_modules/{name}")
        versions[name] = info.get("version", _UNKNOWN) if info else _UNKNOWN
    return versions


def _bundled_tool_versions() -> dict[str, str]:
    if not _BUNDLED_TOOLS_MANIFEST.exists():
        return {}
    try:
        return json.loads(_BUNDLED_TOOLS_MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _os_pretty_name() -> str:
    if not _OS_RELEASE.exists():
        return _UNKNOWN
    try:
        for line in _OS_RELEASE.read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return _UNKNOWN


# Human-readable label per package_key, for the structured version-change
# changelog (about.py's regenerate_about() / GET /about/changelog) — keys
# match whatever detect_all_versions() below uses, both for the flat
# top-level tools and for the nested backend/frontend dicts. Same "needs a
# manual edit when a genuinely new dependency is added" maintenance as
# generate_about_content()'s own prose below, not automatically derived.
DISPLAY_NAMES: dict[str, str] = {
    "python": "Python", "nginx": "nginx", "jre": "Eclipse Temurin JRE",
    "cfr": "CFR", "vineflower": "Vineflower", "ansible-core": "ansible-core",
    "ansible.posix": "ansible.posix", "opentofu": "OpenTofu",
    "fastapi": "FastAPI", "uvicorn": "Uvicorn", "gunicorn": "Gunicorn",
    "sqlalchemy": "SQLAlchemy", "alembic": "Alembic", "aiosqlite": "aiosqlite",
    "asyncpg": "asyncpg", "aiomysql": "aiomysql", "pymysql": "PyMySQL",
    "cryptography": "cryptography", "pyasn1": "pyasn1", "jinja2": "Jinja2",
    "pyyaml": "PyYAML", "markdown": "Markdown", "weasyprint": "WeasyPrint",
    "slowapi": "slowapi", "pyjwt": "PyJWT", "argon2-cffi": "argon2-cffi",
    "ldap3": "ldap3", "httpx": "httpx", "boto3": "boto3", "botocore": "botocore",
    "pydantic": "Pydantic", "pydantic-settings": "pydantic-settings",
    "react": "React", "react-dom": "React DOM", "react-router-dom": "react-router-dom",
    "@tanstack/react-query": "@tanstack/react-query", "axios": "axios",
    "@codemirror/view": "@codemirror/view", "@codemirror/state": "@codemirror/state",
    "@codemirror/language": "@codemirror/language", "@codemirror/commands": "@codemirror/commands",
    "@codemirror/autocomplete": "@codemirror/autocomplete", "@codemirror/search": "@codemirror/search",
    "@lezer/highlight": "@lezer/highlight", "react-markdown": "react-markdown",
    "remark-gfm": "remark-gfm", "rehype-highlight": "rehype-highlight",
    "rehype-slug": "rehype-slug", "mermaid": "mermaid", "d3-force": "d3-force",
    "highlight.js": "highlight.js", "lucide-react": "lucide-react", "sonner": "sonner",
    "class-variance-authority": "class-variance-authority", "clsx": "clsx",
    "tailwind-merge": "tailwind-merge",
}


def display_name_for(package_key: str) -> str:
    return DISPLAY_NAMES.get(package_key, package_key)


def flatten_versions(detected: dict[str, Any]) -> dict[str, str]:
    """Flattens detect_all_versions()'s nested shape into a single
    {package_key: version} dict, for diffing one regenerate's detections
    against the previous one (about.py's regenerate_about()). Skips any
    entry that wasn't actually detected (_UNKNOWN) — nothing meaningful to
    diff for those, and keeping them would make every regenerate "changed"
    bookkeeping noisy with fake transitions to/from "(version not
    detected)"."""
    flat: dict[str, str] = {}
    top_level = {
        "python": detected.get("python_version"),
        "nginx": detected.get("nginx_version"),
        "jre": detected.get("jre_version"),
        "cfr": detected.get("cfr_version"),
        "vineflower": detected.get("vineflower_version"),
        "ansible-core": detected.get("ansible_core_version"),
        "ansible.posix": detected.get("ansible_posix_version"),
        "opentofu": detected.get("tofu_version"),
    }
    for key, version in top_level.items():
        if version and version != _UNKNOWN:
            flat[key] = version
    for key, version in detected.get("backend", {}).items():
        if version and version != _UNKNOWN:
            flat[key] = version
    for key, version in detected.get("frontend", {}).items():
        if version and version != _UNKNOWN:
            flat[key] = version
    return flat


def detect_all_versions() -> dict[str, Any]:
    import sys

    tools = _bundled_tool_versions()
    java_out = _run(["java", "-version"])
    nginx_out = _run(["nginx", "-v"])
    tofu_out = _run(["tofu", "version"])
    # Absolute path — ansible-galaxy only exists inside the venv
    # (/opt/certmanager/venv/bin), which entrypoint.sh never adds to PATH
    # (it launches gunicorn via its own absolute path instead, the same
    # reason this needs one too rather than relying on bare "ansible-galaxy").
    posix_out = _run(["/opt/certmanager/venv/bin/ansible-galaxy", "collection", "list"])

    return {
        "python_version": ".".join(str(p) for p in sys.version_info[:3]),
        "os_pretty_name": _os_pretty_name(),
        "nginx_version": _extract(r"nginx/(\S+)", nginx_out),
        "jre_version": _extract(r"Temurin-(\S+?)\s*\(build", java_out),
        "backend": {
            "fastapi": _pip_version("fastapi"),
            "uvicorn": _pip_version("uvicorn"),
            "gunicorn": _pip_version("gunicorn"),
            "sqlalchemy": _pip_version("sqlalchemy"),
            "alembic": _pip_version("alembic"),
            "aiosqlite": _pip_version("aiosqlite"),
            "asyncpg": _pip_version("asyncpg"),
            "aiomysql": _pip_version("aiomysql"),
            "pymysql": _pip_version("pymysql"),
            "cryptography": _pip_version("cryptography"),
            "pyasn1": _pip_version("pyasn1"),
            "jinja2": _pip_version("jinja2"),
            "pyyaml": _pip_version("pyyaml"),
            "markdown": _pip_version("markdown"),
            "weasyprint": _pip_version("weasyprint"),
            "slowapi": _pip_version("slowapi"),
            "pyjwt": _pip_version("pyjwt"),
            "argon2-cffi": _pip_version("argon2-cffi"),
            "ldap3": _pip_version("ldap3"),
            "httpx": _pip_version("httpx"),
            "boto3": _pip_version("boto3"),
            "botocore": _pip_version("botocore"),
            "pydantic": _pip_version("pydantic"),
            "pydantic-settings": _pip_version("pydantic-settings"),
        },
        "frontend": _frontend_versions(),
        "cfr_version": tools.get("cfr_version", _UNKNOWN),
        "vineflower_version": tools.get("vineflower_version", _UNKNOWN),
        "ansible_core_version": _pip_version("ansible-core"),
        "ansible_posix_version": _extract(r"ansible\.posix\s+(\S+)", posix_out),
        "tofu_version": _extract(r"OpenTofu\s+v(\S+)", tofu_out),
    }


def _fe(v: dict[str, str], name: str) -> str:
    return v.get(name, _UNKNOWN)


def render_about_markdown(d: dict[str, Any]) -> str:
    """Assembles the full About page markdown from an already-detected
    version dict (detect_all_versions()'s return value) — split out from
    detection itself so about.py's regenerate_about() can detect once and
    both render the page *and* diff against the previous detection for the
    structured changelog, instead of running every subprocess/file lookup
    twice per regenerate. Structure and prose mirror the hand-written
    version this replaced (migration 089's seed content) — only the
    version numbers are dynamic; each dependency's one-line description
    only needs a manual edit again if a *new* dependency is added, same
    "keep it current" maintenance the page already asks of admins."""
    b = d["backend"]
    fe = d["frontend"]

    lines = [
        "LabTool is a self-hosted suite for SSL certificate management, "
        "infrastructure build automation, JAR bytecode analysis, and internal "
        "documentation/bug tracking. It is built entirely on open-source "
        "software; this page credits everything it is built on, with the "
        "exact versions currently deployed (useful for license evaluation "
        "before production use).",
        "",
        "*Generated automatically via the About page's \"Regenerate\" action "
        "(admin-only) — detected live from this running container, not "
        "hand-typed. Descriptive text stays fixed; only version numbers are "
        "re-detected each time.*",
        "",
        "## Runtime & base images",
        "",
        f"- **Python {d['python_version']}** (`python:3.12-slim`, {d['os_pretty_name']}) - the backend runtime",
        "- **Node.js** (`node:20-alpine`) - used only to build the frontend bundle at image build time; not present in the running container",
        f"- **nginx {d['nginx_version']}** - serves the built frontend and reverse-proxies API requests",
        f"- **Eclipse Temurin JRE {d['jre_version']}** - runs the bundled Java decompilers and `keytool`",
        "",
        "## Backend (Python)",
        "",
        "Exact versions currently installed (detected via `importlib.metadata` against the running venv):",
        "",
        f"- **FastAPI {b['fastapi']}** - the API framework",
        f"- **Uvicorn {b['uvicorn']}** / **Gunicorn {b['gunicorn']}** - ASGI server",
        f"- **SQLAlchemy {b['sqlalchemy']}** + **Alembic {b['alembic']}** - ORM and schema migrations",
        f"- **aiosqlite {b['aiosqlite']}** / **asyncpg {b['asyncpg']}** / **aiomysql {b['aiomysql']}** (with **PyMySQL {b['pymysql']}**) - async database drivers (SQLite/PostgreSQL/MySQL)",
        f"- **cryptography {b['cryptography']}** / **pyasn1 {b['pyasn1']}** - certificate and key generation/parsing",
        f"- **Jinja2 {b['jinja2']}** - config and playbook templating",
        f"- **PyYAML {b['pyyaml']}** - YAML parsing (Ansible playbooks, templates)",
        f"- **Markdown {b['markdown']}** - server-side markdown rendering (PDF export)",
        f"- **WeasyPrint {b['weasyprint']}** - PDF generation",
        f"- **slowapi {b['slowapi']}** - API rate limiting",
        f"- **PyJWT {b['pyjwt']}** - JWT authentication tokens",
        f"- **argon2-cffi {b['argon2-cffi']}** - password hashing",
        f"- **ldap3 {b['ldap3']}** - LDAP authentication",
        f"- **httpx {b['httpx']}** - outbound HTTP client",
        f"- **boto3 {b['boto3']}** (with **botocore {b['botocore']}**) - AWS SDK (S3/KMS integrations)",
        f"- **Pydantic {b['pydantic']}** / **pydantic-settings {b['pydantic-settings']}** - request validation and config",
        "",
        "## Frontend (JavaScript/TypeScript)",
        "",
        "Exact resolved versions (parsed from `frontend/package-lock.json` at request time):",
        "",
        f"- **React {_fe(fe, 'react')}** / **React DOM {_fe(fe, 'react-dom')}** - UI framework",
        f"- **react-router-dom {_fe(fe, 'react-router-dom')}** - client-side routing",
        f"- **@tanstack/react-query {_fe(fe, '@tanstack/react-query')}** - server-state and data fetching",
        f"- **axios {_fe(fe, 'axios')}** - HTTP client",
        f"- **CodeMirror** (`@codemirror/view` {_fe(fe, '@codemirror/view')}, `@codemirror/state` {_fe(fe, '@codemirror/state')}, "
        f"`@codemirror/language` {_fe(fe, '@codemirror/language')}, `@codemirror/commands` {_fe(fe, '@codemirror/commands')}, "
        f"`@codemirror/autocomplete` {_fe(fe, '@codemirror/autocomplete')}, `@codemirror/search` {_fe(fe, '@codemirror/search')}, "
        f"plus per-language packages, `@lezer/highlight` {_fe(fe, '@lezer/highlight')}) - the code and markdown editor used throughout Docs",
        f"- **react-markdown {_fe(fe, 'react-markdown')}**, **remark-gfm {_fe(fe, 'remark-gfm')}**, "
        f"**rehype-highlight {_fe(fe, 'rehype-highlight')}**, **rehype-slug {_fe(fe, 'rehype-slug')}** - markdown rendering",
        f"- **mermaid {_fe(fe, 'mermaid')}** - diagram rendering in Docs",
        f"- **d3-force {_fe(fe, 'd3-force')}** - the Doc Map's force-directed graph layout",
        f"- **highlight.js {_fe(fe, 'highlight.js')}** - syntax highlighting",
        f"- **lucide-react {_fe(fe, 'lucide-react')}** - icon set",
        f"- **sonner {_fe(fe, 'sonner')}** - toast notifications",
        f"- **class-variance-authority {_fe(fe, 'class-variance-authority')}**, **clsx {_fe(fe, 'clsx')}**, "
        f"**tailwind-merge {_fe(fe, 'tailwind-merge')}** - styling utilities",
        "- **Vite**, **TypeScript**, **ESLint**, **Tailwind CSS** - build tooling (not shipped - used only to produce the static bundle)",
        "",
        "## Bundled tools",
        "",
        f"- **CFR {d['cfr_version']}** (github.com/leibnitz27/cfr) - one of two Java decompilers used by JAR Analyser",
        f"- **Vineflower {d['vineflower_version']}** (github.com/Vineflower/vineflower) - the other Java decompiler used by JAR Analyser",
        f"- **ansible-core {d['ansible_core_version']}** + the **ansible.posix {d['ansible_posix_version']}** collection - runs every Build Manager playbook",
        f"- **OpenTofu {d['tofu_version']}** (github.com/opentofu/opentofu) - infrastructure-as-code provisioning in Build Manager",
        "",
        "## Build Manager target images",
        "",
        "The Ubuntu and RHEL8 target images Build Manager ships for exercising its own Ansible roles are themselves built from:",
        "",
        "- **Ubuntu 24.04** (`ubuntu:24.04`)",
        "- **Red Hat UBI8** (`registry.access.redhat.com/ubi8/ubi-init:8.10`)",
        "",
        "---",
        "",
        "*Admins: if we add, remove, or upgrade a dependency in a way that changes this list "
        "(a new pip/npm package, a new bundled tool, a base image bump), hit \"🔄 Regenerate\" "
        "again to pick up the new version automatically — or add its description here by hand "
        "first if it's a genuinely new entry, since the generator only re-detects versions for "
        "dependencies it already knows to look for.*",
    ]
    return "\n".join(lines) + "\n"
