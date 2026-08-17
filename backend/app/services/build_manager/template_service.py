"""Template service — CRUD, versioning, YAML export/import."""

import json
import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.build_manager import BMTemplate, BMTemplateVersion

logger = logging.getLogger(__name__)

REQUIRED_SPEC_FIELDS = {"hosts"}

# Fixed set of choices offered in the Template Builder's timeout dropdown —
# kept small and deliberate (not an arbitrary int) so every value has
# actually been exercised, rather than someone picking e.g. 7 minutes and
# discovering only live that it's too short for their template. 90/120 added
# after the Full Stack golden path kept tripping an intermittent SSH failure
# around the ~32-minute mark even with the 60-minute cap already raised once
# — the extra headroom lets a build survive one stall/retry within a single
# job instead of needing the auto-retry path to kick in.
ALLOWED_ANSIBLE_TIMEOUT_MINUTES = {30, 40, 50, 60, 90, 120}

# ssl-cert-manager itself is always started with -p 80:80 -p 8000:8000, so
# these two host ports are permanently unavailable to any Build Manager
# host container — reject them here with a clear message instead of letting
# container creation fail later with an opaque "port already allocated".
RESERVED_HOST_PORTS = {80, 8000}


def validate_spec(spec: dict) -> list[str]:
    """Validate a template spec. Returns list of errors (empty = valid)."""
    errors = []
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    for field in REQUIRED_SPEC_FIELDS:
        if field not in spec:
            errors.append(f"Missing required field: {field}")
    if "hosts" in spec:
        if not isinstance(spec["hosts"], list) or len(spec["hosts"]) == 0:
            errors.append("hosts must be a non-empty array")
        else:
            for i, host in enumerate(spec["hosts"]):
                if "role" not in host:
                    errors.append(f"hosts[{i}]: missing 'role'")
                if "expose_ports" in host:
                    ports = host["expose_ports"]
                    if not isinstance(ports, list) or not all(isinstance(p, int) for p in ports):
                        errors.append(f"hosts[{i}].expose_ports must be a list of integers")
                    else:
                        out_of_range = [p for p in ports if not (1 <= p <= 65535)]
                        if out_of_range:
                            errors.append(f"hosts[{i}].expose_ports: {out_of_range} out of valid TCP port range (1-65535)")
                        reserved = [p for p in ports if p in RESERVED_HOST_PORTS]
                        if reserved:
                            errors.append(
                                f"hosts[{i}].expose_ports: {reserved} reserved for the Cert Manager "
                                f"container itself and can never be published by another host"
                            )
    if "network" in spec:
        net = spec["network"]
        if not isinstance(net, dict):
            errors.append("network must be an object")
    if "ansible_timeout_minutes" in spec:
        value = spec["ansible_timeout_minutes"]
        if value not in ALLOWED_ANSIBLE_TIMEOUT_MINUTES:
            errors.append(
                f"ansible_timeout_minutes must be one of {sorted(ALLOWED_ANSIBLE_TIMEOUT_MINUTES)}, got {value!r}"
            )
    return errors


def resolve_ansible_timeout_seconds(spec: dict, env_variables: dict | None = None) -> int:
    """The Ansible job timeout for a build from this template, in seconds.

    env_variables (an environment's own stored variables, not the template
    spec) can carry a per-environment ansible_timeout_minutes override —
    e.g. one environment built from a shared template needing more headroom
    than every other environment using it, without editing the template
    itself (which every other environment from it would also inherit).
    Takes priority over the template's own value when present.

    Defaults to 30 minutes — the exact behaviour every template had before
    this became configurable — so a template with no ansible_timeout_minutes
    key at all (every builtin/existing template as of this change) keeps
    working unchanged."""
    override = (env_variables or {}).get("ansible_timeout_minutes")
    if override is not None:
        return override * 60
    return spec.get("ansible_timeout_minutes", 30) * 60


async def create_template(
    db: AsyncSession, name: str, description: str, tags: str,
    spec: dict, change_note: str, created_by: str, tenant_id: str,
    origin: str = "user",
) -> BMTemplate:
    """Create a new template with its first version."""
    # Check uniqueness — BMTemplate.name has a DB-level unique constraint,
    # but relying on that alone means the failure surfaces as an unhandled
    # IntegrityError instead of a clear, catchable error the API layer can
    # turn into a proper 409.
    existing = await db.execute(select(BMTemplate).where(BMTemplate.name == name))
    if existing.scalar_one_or_none():
        raise ValueError(f"Template '{name}' already exists")

    template = BMTemplate(
        name=name, description=description, tags=tags,
        created_by=created_by, tenant_id=tenant_id, origin=origin,
    )
    db.add(template)
    await db.flush()

    version = BMTemplateVersion(
        template_id=template.id, version=1,
        spec=json.dumps(spec), change_note=change_note,
        created_by=created_by, is_current=True,
    )
    db.add(version)
    await db.commit()

    # Re-fetch with relationships
    result = await db.execute(
        select(BMTemplate).options(selectinload(BMTemplate.versions))
        .where(BMTemplate.id == template.id)
    )
    return result.scalar_one()


async def save_new_version(
    db: AsyncSession, template_id: str, spec: dict,
    change_note: str, created_by: str,
) -> BMTemplateVersion:
    """Save a new version of an existing template."""
    # Get current max version
    result = await db.execute(
        select(BMTemplateVersion)
        .where(BMTemplateVersion.template_id == template_id)
        .order_by(BMTemplateVersion.version.desc())
    )
    versions = result.scalars().all()
    next_version = (versions[0].version + 1) if versions else 1

    # Carry forward ansible_timeout_minutes from the previous version if the
    # incoming spec doesn't set it. A raw spec edit (BMTemplatesPage's JSON
    # textarea, or a YAML re-import) can easily omit an already-tuned
    # timeout without meaning to, silently resetting a template that needed
    # extra headroom (e.g. the Full Stack golden path's 60+ minutes) back
    # down to resolve_ansible_timeout_seconds()'s 30-minute default — this
    # is exactly how that value has gone missing across past versions.
    # Once deliberately set, it should only change via an explicit new value.
    if "ansible_timeout_minutes" not in spec and versions:
        prev_spec = json.loads(versions[0].spec)
        if "ansible_timeout_minutes" in prev_spec:
            spec = {**spec, "ansible_timeout_minutes": prev_spec["ansible_timeout_minutes"]}

    # Mark all existing as not current
    await db.execute(
        update(BMTemplateVersion)
        .where(BMTemplateVersion.template_id == template_id)
        .values(is_current=False)
    )

    new_ver = BMTemplateVersion(
        template_id=template_id, version=next_version,
        spec=json.dumps(spec), change_note=change_note,
        created_by=created_by, is_current=True,
    )
    db.add(new_ver)
    await db.commit()
    await db.refresh(new_ver)
    return new_ver


def _local_repo_product() -> dict:
    """The local_repo product entry shared by every host in the Full Stack
    template that consumes the pkg-cache host's pre-seeded package cache —
    factored out since it's identical across 5 hosts. /mnt/pkg-cache is
    where this host's nfs_client product (see _nfs_client_pkg_cache_product)
    mounts the pkg-cache host's real NFS export — deliberately real NFS, not
    a Docker named volume: every host here happens to be a container on the
    same Docker engine in this lab, but on real on-prem/AWS deployments
    they'll be genuinely separate machines with no shared Docker daemon to
    fake a shared directory with a volume bind. Only a real network
    filesystem works across actually-separate hosts, so the golden path
    rehearses that architecture rather than a lab-only shortcut."""
    return {"product": "local_repo", "version": "1", "vars": {"local_repo_cache_dir": "/mnt/pkg-cache"}}


def _nfs_client_pkg_cache_product() -> dict:
    """The nfs_client product entry shared by every host in the Full Stack
    template that mounts the pkg-cache host's NFS export — factored out
    since it's identical across 5 hosts. Must come before
    _local_repo_product() in a host's products list: the mount has to exist
    at /mnt/pkg-cache before local_repo's role checks for
    /mnt/pkg-cache/apt/Packages.gz."""
    return {"product": "nfs_client", "version": "4", "vars": {"nfs_mounts": [
        {"src": "pkg-cache:/srv/nfs-export", "path": "/mnt/pkg-cache", "opts": "nolock,vers=3"},
    ]}}


_KEYSTONE_GOLDEN_PATH_ASSETS = Path(__file__).parent / "golden_path_assets" / "keystone"

# Shared between _keystone_golden_path_vars() (the DB client's connection
# string) and the mysql host's own vars (the DB user's actual password) in
# the same SEED_TEMPLATES entry below — these two host blocks are otherwise
# independent dicts, so this is the one place both sides read the same
# value from, guaranteeing they can't drift apart. A demo/reference-template
# secret only (see keystone_admin_password's identical 'admin' convention
# elsewhere in this same function) — real deployments set their own via the
# Config editor.
_KEYSTONE_GOLDEN_PATH_DB_PASSWORD = "keystone-db-changeit"


def _keystone_golden_path_vars() -> dict:
    """SSP-specific Keystone customisation (real business/service roles,
    the matching custom policy.json, and the system-domain service
    accounts) — deliberately only ever applied here, to the golden-path
    template's own keystone host vars, and never to the generic keystone
    catalogue product's defaults. Anyone building a plain Keystone deployment
    outside this specific golden path has no use for SSP's role set or
    policy — baking it into the product itself would surprise them with
    roles/policy they never asked for. Source of truth for the actual
    content is scripts/Manual-Scripts/manual-installation-2.6.9-scripts/idm/
    (the original reference install scripts); these are that same content,
    copied here since only backend/app/ (not the repo-root scripts/
    directory) ships in the built image.

    Deliberately excludes idm/patch/common.py — a source patch to Keystone's
    own token provider internals, explicitly documented upstream as
    "applicable only for Antelope" (OpenStack 2023.1). This template targets
    2024.1/2024.2; applying an older release's internals patch to a newer
    Keystone risks breaking token issuance in a way that's hard to diagnose,
    for a version this template has no intention of downgrading to.
    """
    # This runs at module import time (SEED_TEMPLATES is a module-level
    # list) — a missing/unreadable asset file must not take the whole
    # backend down with it, so fall back to the same {} this host's
    # keystone vars had before this feature existed rather than raising.
    try:
        roles_yml = (_KEYSTONE_GOLDEN_PATH_ASSETS / "roles.yml").read_text()
        system_domain_yml = (_KEYSTONE_GOLDEN_PATH_ASSETS / "system_domain.yml").read_text()
        policy_json = (_KEYSTONE_GOLDEN_PATH_ASSETS / "policy.json").read_text()
    except OSError:
        logger.exception("Could not load Keystone golden-path assets from %s — keystone host will use bare defaults", _KEYSTONE_GOLDEN_PATH_ASSETS)
        return {}

    # The reference install runs these as two separate import_p3.py calls
    # (create_roles.sh then create_system_domain.sh), but the script only
    # cares about entry order within the file (roles/domain first, then
    # implies, then users/groups) — not file boundaries — so concatenating
    # them into the one import this role supports produces an identical
    # result in a single pass. system_domain.yml's own leading "---" is
    # dropped since a single YAML document can only have one.
    system_domain_body = system_domain_yml.split("---", 1)[-1].lstrip("\n")
    import_yaml = roles_yml.rstrip() + "\n" + system_domain_body

    return {
        "keystone_file_deployments": [
            {"path": "/etc/keystone/policy.json", "content": policy_json, "mode": "0644", "owner": "keystone"},
            {"path": "/opt/keystone/import.yml", "content": import_yaml, "mode": "0644", "owner": "keystone"},
        ],
        # Matches create_system_domain.sh's own default
        # (KEYSTONE_SYSTEM_DOMAIN_PASSWORD:-changeit) — override per
        # environment via this same field in the Config editor.
        "keystone_import_params": "password,changeit",
        # Real cross-host MySQL connection (not the sqlite default) — "mysql"
        # is the mysql host's own role name, which Docker resolves directly
        # in this template (deliberately no "network" pool — see this
        # template's own comment on why that makes every host reachable by
        # its bare role name). keystone/tasks/main.yml builds the actual
        # SSL-verified connection string from these; the DB user + password
        # must match what the mysql host below actually creates.
        "keystone_db_host": "mysql",
        "keystone_db_user": "keystone",
        "keystone_db_password": _KEYSTONE_GOLDEN_PATH_DB_PASSWORD,
        "keystone_db_name": "keystone",
        # Opts into the (advisory, non-gating) keystone->rabbitmq cross-host
        # trust check in keystone/tasks/verify.yml — Keystone has no real
        # functional dependency on RabbitMQ, this purely demonstrates the
        # same CA/trust mechanism validates against a second, independent
        # peer host too, not just mysql.
        "keystone_rabbitmq_host": "rabbitmq",
    }


# Golden-path reference templates (Enhancement Plan Stage 7) — curated,
# genuinely deployable multi-service specs that showcase cert automation
# across a realistic stack, rather than every user starting from an empty
# builder. Product/version names match catalogue_service.py's SEED_PRODUCTS
# exactly (specs reference products by name+version string, not by DB id —
# see build_template_spec()'s output shape — so these don't depend on the
# product catalogue's version UUIDs, only on the named versions existing).
SEED_TEMPLATES: list[dict] = [
    {
        "name": "Reference: Full Stack (Frontend + Backend + MySQL + RabbitMQ + Keystone)",
        "description": "A realistic 8-host stack with TLS on every service — a shared apt package cache served over real NFS, frontend-lb/backend-lb load balancers, frontend proxy, FastAPI backend, MySQL, RabbitMQ, and Keystone identity. Shows cert automation across a full deployment, not just one host. The pkg-cache host builds first, runs an NFS server, and pre-downloads every apt package the other hosts need into the export; they mount it with the NFS Client product and read from it instead of the network — found necessary via real live builds, where hosts installing packages over the network (some individually large, e.g. Keystone's Apache + build-toolchain install) could break their SSH connection mid-task on a resource-constrained Docker host. This deliberately uses real NFS rather than a Docker-only shortcut (a shared named volume): every host here happens to be a container on the same Docker engine in this lab, but real on-prem/AWS deployments are genuinely separate machines with no shared Docker daemon, so only a real network filesystem carries over — see 'Golden-Path Template Pitfalls' in §7 of the operations guide for the full incident writeup of why an nfs-server host was earlier (mis-)believed to be inherently unstable in a container, and why it wasn't. backend-lb and frontend-lb are modeled directly on the real application's own load-balancer configs (also traced via the JAR Analyser): each terminates its own client-facing TLS, then re-encrypts outbound to its upstream (backend/frontend respectively) — not a passthrough tunnel.",
        "tags": "reference,full-stack",
        "spec": {
            "base_os": "ubuntu", "base_os_version": "24.04",
            # Hosts are declared in build order, not alphabetical/logical
            # grouping order: the package cache first (everything else's
            # installs depend on it being ready), then infrastructure other
            # services depend on (mysql, rabbitmq), then identity (keystone),
            # then the application tiers that talk to all of them (backend,
            # frontend). site.yml's single play runs with serial: 1 and
            # processes hosts in exactly this declared order (see
            # inventory_service.py's _generate_environment_inventory) — each
            # host fully finishes before the next one starts.
            "hosts": [
                {"role": "pkg-cache", "hostname_pattern": "{{env_name}}-pkg-cache",
                 # nfs_server must come before pkg_cache_seed: it creates and
                 # exports /srv/nfs-export; pkg_cache_seed then writes an
                 # "apt" subdirectory inside it and downloads packages there.
                 "products": [
                     {"product": "nfs_server", "version": "4", "vars": {
                         "nfs_exports": [{"path": "/srv/nfs-export", "clients": "*", "options": "rw,sync,no_subtree_check,no_root_squash,fsid=0"}],
                     }},
                     {"product": "pkg_cache_seed", "version": "1", "vars": {
                         "pkg_cache_seed_dir": "/srv/nfs-export/apt",
                         "pkg_cache_seed_packages": [
                             "nginx", "python3-pip", "python3-venv",
                             "mysql-server", "mysql-client",
                             "erlang-nox", "rabbitmq-server",
                             "apache2", "apache2-dev", "python3-dev", "gcc",
                             "libffi-dev", "libssl-dev", "pkg-config",
                         ],
                     }},
                 ],
                 "certs": []},
                {"role": "mysql", "hostname_pattern": "{{env_name}}-mysql",
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     # Real "keystone" database + user, not just a bare
                     # server — this is what makes keystone's cross-host
                     # connection (see _keystone_golden_path_vars) an actual
                     # working, SSL-verified login, not an unreachable
                     # config value pointing at nothing. Password must match
                     # keystone_db_password there — see
                     # _KEYSTONE_GOLDEN_PATH_DB_PASSWORD's own comment for
                     # why both sides read the same constant.
                     {"product": "mysql", "version": "8.4", "vars": {
                         "mysql_databases": [{"name": "keystone"}],
                         "mysql_users": [{
                             "name": "keystone", "password": _KEYSTONE_GOLDEN_PATH_DB_PASSWORD,
                             "host": "%", "priv": "keystone.*:ALL PRIVILEGES",
                         }],
                     }},
                 ],
                 "certs": ["server_tls"]},
                {"role": "rabbitmq", "hostname_pattern": "{{env_name}}-rabbitmq",
                 # No separate "erlang" product here: no such Ansible role
                 # exists either (same class of bug as keystone's old "apache"
                 # entry — would crash the build with "role not found"), and
                 # it's redundant anyway — the rabbitmq role's own "Install
                 # RabbitMQ and Erlang" task already installs erlang-nox.
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "rabbitmq", "version": "3.13", "vars": {}},
                 ],
                 # Published to the Docker host by default so the TLS
                 # management UI is reachable from a real browser without any
                 # manual per-environment step.
                 "expose_ports": [15671],
                 "certs": ["server_tls"]},
                {"role": "keystone", "hostname_pattern": "{{env_name}}-keystone",
                 # No separate "apache" product here: no such Ansible role
                 # exists (would crash the build with "role not found"), and
                 # it would be redundant anyway — the keystone role already
                 # installs Apache + mod_wsgi itself as part of its own setup.
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "keystone", "version": "2024.2", "vars": _keystone_golden_path_vars()},
                 ],
                 "certs": ["server_tls"]},
                {"role": "backend", "hostname_pattern": "{{env_name}}-backend",
                 # Base software per the guide's Backend node: Python and nginx
                 # (nginx fronts both frontend and backend nodes there). Java
                 # is also required on a backend node per the guide, but needs
                 # no separate product entry here — the base role already
                 # installs OpenJDK on every host unconditionally (it's needed
                 # to build each host's TLS keystore/truststore).
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "python", "version": "3.12", "vars": {}},
                     {"product": "uvicorn", "version": "0.32", "vars": {}},
                     {"product": "nginx", "version": "1.26", "vars": {}},
                 ],
                 "certs": ["server_tls", "client_mtls"]},
                {"role": "frontend", "hostname_pattern": "{{env_name}}-frontend",
                 # Base software per the on-prem install guide's Frontend node:
                 # Python, Node.js and nginx (nginx as the public-facing proxy).
                 # Node.js isn't apt-based (it has its own separate tarball
                 # cache under /certmanager-data/pkg-cache/bin/, unrelated to
                 # this apt cache), so it isn't covered here.
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "nginx", "version": "1.26", "vars": {}},
                     {"product": "python", "version": "3.12", "vars": {}},
                     {"product": "nodejs", "version": "20", "vars": {}},
                 ],
                 "certs": ["server_tls"]},
                {"role": "backend-lb", "hostname_pattern": "{{env_name}}-backend-lb",
                 # Backend-tier load balancer — modeled directly on the real
                 # application's own backend-lb nginx config (captured via the
                 # JAR Analyser). Fronts the backend host's uvicorn service
                 # (port 8000), terminating its own client-facing TLS then
                 # re-encrypting outbound, matching the real app's
                 # terminate-and-re-encrypt design (not a passthrough tunnel).
                 # Also reads from the shared NFS package cache like every
                 # other host — nginx is already in pkg-cache's seeded list.
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "nginx_lb", "version": "1", "vars": {"lb_upstreams": [
                         {"name": "backend", "path": "/", "host": "backend", "port": 8000},
                     ]}},
                 ],
                 "certs": ["server_tls"]},
                {"role": "frontend-lb", "hostname_pattern": "{{env_name}}-frontend-lb",
                 # Frontend-tier (client-facing) load balancer — same
                 # nginx_lb product as backend-lb, configured to front the
                 # frontend host's nginx (port 443) instead.
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "nginx_lb", "version": "1", "vars": {"lb_upstreams": [
                         {"name": "frontend", "path": "/", "host": "frontend", "port": 443},
                     ]}},
                 ],
                 # Published to the Docker host by default — this is the
                 # client-facing tier, so a real browser needs to reach it
                 # directly. backend-lb deliberately has no expose_ports:
                 # it's only ever addressed by frontend-lb inside the Docker
                 # network. Port 80 is never published here — it's always
                 # owned by the ssl-cert-manager container itself.
                 "expose_ports": [443],
                 "certs": ["server_tls"]},
            ],
            # Deliberately no "network" pool: allocate_ips() only falls back
            # to using each role name directly as its Docker container name
            # when no pool is defined — that's what makes build_environment
            # recognise every host here as a Docker target to create, rather
            # than expecting real reachable SSH hosts at auto-allocated IPs
            # that don't exist in this environment. Same mechanism the NFS
            # Shared Storage Server template below already relies on. Only
            # one environment built from this template can exist at a time,
            # since container names are the literal role names with no
            # per-environment prefix.
            "certificates": {"key_algorithm": "RSA", "key_size": 2048, "validity_days": 365, "san_include_localhost": True},
            # This 8-host build genuinely needs more than the 30-minute
            # default — confirmed by two real, reproducible timeouts at
            # ~1799.7s each before this was raised. 60 minutes was then
            # proven sufficient by a real full build completing in ~1933s.
            "ansible_timeout_minutes": 60,
        },
    },
    {
        "name": "Reference: RHEL8 Full Stack (Frontend + Backend + MySQL + RabbitMQ + Keystone)",
        "description": "The same 8-host reference stack as the Ubuntu Full Stack template, on RHEL 8 (dnf-based roles, RPM package cache) instead of Ubuntu — same shared cross-host CA trust story: keystone's real SSL-verified MySQL connection, the advisory keystone->rabbitmq trust demonstration, and backend-lb/frontend-lb terminate-and-re-encrypt reverse proxies. Uses the same _keystone_golden_path_vars()/_KEYSTONE_GOLDEN_PATH_DB_PASSWORD as the Ubuntu template so both sides of the keystone<->mysql credential pair can never drift apart between the two OS variants. See the Ubuntu Full Stack template's own description for the full pkg-cache/NFS rationale, which applies identically here.",
        "tags": "reference,full-stack,rhel8",
        "spec": {
            "base_os": "rhel", "base_os_version": "8",
            "hosts": [
                {"role": "pkg-cache", "hostname_pattern": "{{env_name}}-pkg-cache",
                 "products": [
                     {"product": "nfs_server", "version": "4", "vars": {
                         "nfs_exports": [{"path": "/srv/nfs-export", "clients": "*", "options": "rw,sync,no_subtree_check,no_root_squash,fsid=0"}],
                     }},
                     {"product": "pkg_cache_seed", "version": "1", "vars": {
                         "pkg_cache_seed_dir": "/srv/nfs-export/rpm",
                         "pkg_cache_seed_packages": [
                             "nginx", "httpd", "httpd-devel", "mod_ssl", "curl",
                             "python3.11", "python3.11-devel", "python3.11-pip", "python3.11-packaging",
                             "gcc", "libffi-devel", "pkgconf-pkg-config", "annobin", "redhat-rpm-config", "git",
                         ],
                     }},
                 ],
                 "certs": []},
                {"role": "mysql", "hostname_pattern": "{{env_name}}-mysql",
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     # Real "keystone" database + user, matching the Ubuntu
                     # template's mysql host — see _KEYSTONE_GOLDEN_PATH_DB_PASSWORD's
                     # own comment for why both sides read the same constant.
                     {"product": "mysql", "version": "8.0", "vars": {
                         "mysql_databases": [{"name": "keystone"}],
                         "mysql_users": [{
                             "name": "keystone", "password": _KEYSTONE_GOLDEN_PATH_DB_PASSWORD,
                             "host": "%", "priv": "keystone.*:ALL PRIVILEGES",
                         }],
                     }},
                 ],
                 "certs": ["server_tls"]},
                {"role": "rabbitmq", "hostname_pattern": "{{env_name}}-rabbitmq",
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "rabbitmq", "version": "3.13", "vars": {}},
                 ],
                 "expose_ports": [15671],
                 "certs": ["server_tls"]},
                {"role": "keystone", "hostname_pattern": "{{env_name}}-keystone",
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "keystone", "version": "2024.2", "vars": _keystone_golden_path_vars()},
                 ],
                 "certs": ["server_tls"]},
                {"role": "backend", "hostname_pattern": "{{env_name}}-backend",
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "python", "version": "3.11", "vars": {}},
                     {"product": "uvicorn", "version": "0.32", "vars": {}},
                     {"product": "nginx", "version": "1.26", "vars": {}},
                 ],
                 "certs": ["server_tls", "client_mtls"]},
                {"role": "frontend", "hostname_pattern": "{{env_name}}-frontend",
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "nginx", "version": "1.26", "vars": {}},
                     {"product": "python", "version": "3.11", "vars": {}},
                     {"product": "nodejs", "version": "20", "vars": {}},
                 ],
                 "certs": ["server_tls"]},
                {"role": "backend-lb", "hostname_pattern": "{{env_name}}-backend-lb",
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "nginx_lb", "version": "1", "vars": {"lb_upstreams": [
                         {"name": "backend", "path": "/", "host": "backend", "port": 8000},
                     ]}},
                 ],
                 "certs": ["server_tls"]},
                {"role": "frontend-lb", "hostname_pattern": "{{env_name}}-frontend-lb",
                 "products": [
                     _nfs_client_pkg_cache_product(),
                     _local_repo_product(),
                     {"product": "nginx_lb", "version": "1", "vars": {"lb_upstreams": [
                         {"name": "frontend", "path": "/", "host": "frontend", "port": 443},
                     ]}},
                 ],
                 "expose_ports": [443],
                 "certs": ["server_tls"]},
            ],
            "certificates": {"key_algorithm": "RSA", "key_size": 2048, "validity_days": 365, "san_include_localhost": True},
            # RHEL8's dnf installs and Apache+mod_wsgi build step for Keystone
            # run measurably slower than the Ubuntu apt equivalents on this
            # same lab hardware — 120 minutes proven sufficient by a real full
            # build (see 'Diagnose keystone MySQL auth failure on RHEL8 build'
            # in the operations guide); 60 minutes (the Ubuntu template's own
            # value) was not enough here.
            "ansible_timeout_minutes": 120,
        },
    },
    {
        "name": "Reference: Minimal Web + Database",
        "description": "The smallest realistic starting point — an Nginx frontend and a MySQL database, both with TLS. Good first template to clone and extend.",
        "tags": "reference,minimal",
        "spec": {
            "base_os": "ubuntu", "base_os_version": "24.04",
            "hosts": [
                {"role": "web", "hostname_pattern": "{{env_name}}-web",
                 "products": [{"product": "nginx", "version": "1.26", "vars": {}}],
                 "certs": ["server_tls"]},
                {"role": "db", "hostname_pattern": "{{env_name}}-db",
                 "products": [{"product": "mysql", "version": "8.4", "vars": {}}],
                 "certs": ["server_tls"]},
            ],
            "network": {"subnet": "192.168.61.0/24", "range_start": "192.168.61.10", "range_end": "192.168.61.50"},
            "certificates": {"key_algorithm": "RSA", "key_size": 2048, "validity_days": 365, "san_include_localhost": True},
        },
    },
    {
        "name": "Reference: NFS Shared Storage Server",
        "description": (
            "A single NFS server host exporting a directory with no_root_squash "
            "(any client's root user gets full CRUD). Every build binds a named Docker "
            "volume at the fixed export path /srv/nfs-export — this isn't optional: "
            "testing this template for real found the kernel NFS server refuses to "
            "export both a plain host-path bind (which can land on a passthrough "
            "filesystem — e.g. Docker Desktop for Windows shares host drives via 9p) "
            "and a bare container's own overlay2 root filesystem, so a named volume "
            "(a real Docker-managed ext4/xfs filesystem) is the only option that "
            "actually exports. Optionally supply a Storage Volume Name for that host's "
            "role so the served data survives destroying and rebuilding this "
            "environment as long as you reuse the same volume name; leave it blank and "
            "one is auto-generated per environment (still reused across rebuilds of the "
            "same environment, just not shared with a different one). Connect any "
            "other host to this share by adding the existing NFS Client product and "
            "pointing its mount at <this role or hostname>:/srv/nfs-export."
        ),
        "tags": "reference,storage,nfs",
        "spec": {
            "base_os": "ubuntu", "base_os_version": "24.04",
            "hosts": [
                {"role": "nfs-server", "hostname_pattern": "{{env_name}}-nfs-server",
                 "products": [{"product": "nfs_server", "version": "4", "vars": {
                     # fsid=0 is standard practice for a single-export NFS server —
                     # doesn't enable NFSv4 on its own (this appliance is v3-only,
                     # see the NFS Client product's default mount opts), but is
                     # harmless and avoids relying on the underlying filesystem's
                     # own device/inode numbers.
                     "nfs_exports": [{"path": "/srv/nfs-export", "clients": "*", "options": "rw,sync,no_subtree_check,no_root_squash,fsid=0"}],
                 }}],
                 "certs": []},
            ],
            # Deliberately no "network" pool: allocate_ips() only falls back
            # to using each role name directly as its Docker container name
            # when no pool is defined — that's what makes build_environment
            # recognise this host as a Docker target to create/bind-mount at
            # all. Defining a pool here would auto-allocate a real-looking
            # IP instead, silently skipping container creation entirely
            # (caught by live-testing this template, not by review).
        },
    },
]


async def seed_golden_path_templates(db: AsyncSession, created_by: str = "system", tenant_id: str = "00000000-0000-0000-0000-000000000001") -> int:
    """Insert the curated golden-path templates if not already present
    (matched by name). Idempotent — safe to re-run, e.g. to recover a
    deleted builtin template."""
    added = 0
    for tdata in SEED_TEMPLATES:
        existing = await db.execute(select(BMTemplate).where(BMTemplate.name == tdata["name"]))
        if existing.scalar_one_or_none():
            continue
        await create_template(
            db, name=tdata["name"], description=tdata["description"], tags=tdata["tags"],
            spec=tdata["spec"], change_note="Seeded golden-path reference template",
            created_by=created_by, tenant_id=tenant_id, origin="builtin",
        )
        added += 1
    return added


async def get_template_with_current(db: AsyncSession, template_id: str) -> tuple[BMTemplate | None, BMTemplateVersion | None]:
    """Get template and its current version."""
    result = await db.execute(
        select(BMTemplate).options(selectinload(BMTemplate.versions))
        .where(BMTemplate.id == template_id)
    )
    template = result.unique().scalar_one_or_none()
    if not template:
        return None, None
    current = next((v for v in template.versions if v.is_current), None)
    return template, current


def export_as_yaml(template: BMTemplate, version: BMTemplateVersion) -> str:
    """Export a template version as YAML."""
    spec = json.loads(version.spec)
    doc = {
        "name": template.name,
        "description": template.description,
        "version": version.version,
        "change_note": version.change_note,
        "spec": spec,
    }
    return yaml.dump(doc, default_flow_style=False, sort_keys=False)


def parse_yaml_import(yaml_content: str) -> tuple[dict | None, str]:
    """Parse YAML import. Returns (parsed_dict, error_message)."""
    try:
        doc = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        return None, f"Invalid YAML: {e}"
    if not isinstance(doc, dict):
        return None, "YAML must be a mapping"
    if "name" not in doc:
        return None, "Missing 'name' field"
    if "spec" not in doc:
        return None, "Missing 'spec' field"
    return doc, ""
