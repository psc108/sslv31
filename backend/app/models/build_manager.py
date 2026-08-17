"""Build Manager models — Inventory, Templates, Environments, Jobs."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TZDateTime


# --- Templates ---

class BMTemplate(Base):
    __tablename__ = "bm_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="")  # JSON array
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="00000000-0000-0000-0000-000000000001")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    # 'builtin' | 'user' — Enhancement Plan Stage 7, mirrors the JAR Analyser
    # error-KB's origin column: seeded golden-path templates are fully
    # DB-managed and editable/deletable like any user template once seeded;
    # deleting a builtin is genuine and permanent, recoverable only by
    # re-running the seed script for that name.
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="user")

    versions: Mapped[list["BMTemplateVersion"]] = relationship("BMTemplateVersion", back_populates="template", cascade="all, delete-orphan")


class BMTemplateVersion(Base):
    __tablename__ = "bm_template_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_templates.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    spec: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    change_note: Mapped[str] = mapped_column(Text, nullable=False, default="Initial version")
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    template: Mapped["BMTemplate"] = relationship("BMTemplate", back_populates="versions")


# --- Environments ---

class BMEnvironment(Base):
    __tablename__ = "bm_environments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_templates.id"), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending, provisioning, active, degraded, destroying, destroyed
    ip_allocations: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    variables: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON overrides
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="00000000-0000-0000-0000-000000000001")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    destroyed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    # Optional opt-in auto-destroy deadline (Enhancement Plan Stage 5) — null
    # means "no TTL", the default for every existing/pre-Stage-5 environment.
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    template: Mapped["BMTemplate"] = relationship("BMTemplate")
    certs: Mapped[list["BMEnvironmentCert"]] = relationship("BMEnvironmentCert", back_populates="environment", cascade="all, delete-orphan")
    jobs: Mapped[list["BMJob"]] = relationship("BMJob", back_populates="environment", cascade="all, delete-orphan")


class BMEnvironmentCert(Base):
    __tablename__ = "bm_environment_certs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    environment_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_environments.id", ondelete="CASCADE"), nullable=False)
    cert_serial: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # frontend, backend, mysql, etc.
    cert_type: Mapped[str] = mapped_column(String(16), nullable=False, default="server")  # server, client
    issued_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    # Phase 3 — cert integration extras (added migration 067)
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    san_dns: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON list
    san_ip: Mapped[str | None] = mapped_column(Text, nullable=True)    # JSON list

    environment: Mapped["BMEnvironment"] = relationship("BMEnvironment", back_populates="certs")


# --- Jobs ---

class BMJob(Base):
    __tablename__ = "bm_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, default="ansible")  # ansible, provision, destroy
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending, running, success, failed, cancelled
    playbook: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    environment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("bm_environments.id", ondelete="SET NULL"), nullable=True)
    inventory_filter: Mapped[str] = mapped_column(Text, nullable=False, default="")  # host/group filter
    extra_vars: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # JSON list of hostnames Ansible reported fatal/unreachable for — parsed
    # from this job's own output as it streams in, not Ansible's built-in
    # .retry file mechanism (which names retry files after the playbook, not
    # the job, so concurrent/sequential runs of the same playbook would
    # clobber each other's retry file). Powers POST /jobs/{id}/retry's
    # --limit to just the hosts that actually failed; null/empty means the
    # failure happened before any host-level result (e.g. a syntax error),
    # so a retry falls back to a full re-run.
    failed_hosts: Mapped[str | None] = mapped_column(Text, nullable=True)
    # How many times this job chain has already been *automatically*
    # retried (see ansible_runner.py's _execute_job) — 0 for an original
    # submission. Capped at settings.BM_MAX_AUTO_RETRIES so a persistently
    # broken host can't retry forever; a manual POST /jobs/{id}/retry is
    # unrelated and doesn't touch this counter.
    auto_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # How long ansible_runner.py's _execute_job() waits before killing this
    # job's ansible-playbook subprocess. Resolved once at submit_job() time
    # from the owning template's spec["ansible_timeout_minutes"] (default 30
    # min if the template doesn't set one) and persisted here so the running
    # job loop never needs a second DB round-trip to look it up — an
    # auto-retry's follow-up job carries the same value forward explicitly.
    # Found necessary live: an 8-host template hit the old single global
    # 1800s constant twice in a row at ~1799.7s, a real capacity issue for
    # bigger templates, not a bug — hence configurable per template instead
    # of just raising one constant for everyone.
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    # Enhancement Plan Stage 8 — runs Ansible with --check --diff instead of
    # actually applying changes. Persisted (not just a request-time flag) so
    # a dry-run job is never mistaken for a real one in the job history.
    # Known limitation, documented rather than statically detected: command/
    # shell tasks often report inaccurately (or not at all) under --check.
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="00000000-0000-0000-0000-000000000001")
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    # Improvements Plan Stage 21 — automated cross-job bug pattern scan,
    # the same mechanism JAR Analyser's related_bug_ids_json already uses
    # (AnalysisReport, jar_analyser.py). null means "not yet scanned" (a job
    # that hasn't finished failed, or finished before this stage existed);
    # "[]" means "scanned, nothing found" — kept distinguishable rather than
    # defaulting to "[]" so the two states aren't confused.
    related_bug_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A snapshot of the environment this job was built against — OS, per-host
    # product versions, IP allocations, issued certs — captured at
    # submit_job() time (environment_service.build_environment_snapshot).
    # environment_id alone isn't durable: destroy_environment() nulls it and
    # hard-deletes the BMEnvironment row, so without this a job's own build
    # context is unrecoverable once its environment is torn down (a routine
    # occurrence for test/build workflows). Null for jobs with no
    # environment_id, and for jobs submitted before this column existed.
    build_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    environment: Mapped["BMEnvironment | None"] = relationship("BMEnvironment", back_populates="jobs")
    logs: Mapped[list["BMJobLog"]] = relationship("BMJobLog", back_populates="job", cascade="all, delete-orphan")


class BMJobLog(Base):
    __tablename__ = "bm_job_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_jobs.id", ondelete="CASCADE"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    stream: Mapped[str] = mapped_column(String(8), nullable=False, default="stdout")  # stdout, stderr
    line: Mapped[str] = mapped_column(Text, nullable=False, default="")

    job: Mapped["BMJob"] = relationship("BMJob", back_populates="logs")


# --- Product Catalogue (Stage 4) ---

class BMProduct(Base):
    __tablename__ = "bm_products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="utility")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icon: Mapped[str] = mapped_column(String(8), nullable=False, default="📦")
    default_ports: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array
    cert_requirements: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    dependencies: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # JSON list of deployment targets, e.g. ["ec2"] or ["rds"].
    # Default "ec2" covers all existing products unchanged.
    deployment_targets: Mapped[str] = mapped_column(Text, nullable=False, default='["ec2"]')
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    versions: Mapped[list["BMProductVersion"]] = relationship("BMProductVersion", back_populates="product", cascade="all, delete-orphan")


class BMProductVersion(Base):
    __tablename__ = "bm_product_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_products.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    ansible_role: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    default_vars: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    supported_os: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array
    conflicts_with: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array
    requires: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array
    release_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    eol_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    config_schema: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON — UI form schema
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Optional AWS-specific defaults for the Template Builder, e.g.
    # {"instance_type": "t3.medium", "db_instance_class": "db.t3.medium", "multi_az": false}.
    # Null for non-AWS products and existing versions — no behaviour change.
    aws_defaults: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    product: Mapped["BMProduct"] = relationship("BMProduct", back_populates="versions")


# --- Operating System Catalogue (Enhancement Plan Stage 6) ---
# Mirrors BMProduct/BMProductVersion's two-level shape (family + specific
# version) so the Template Builder's base-OS picker and host creation's OS
# dropdown stop being hardcoded — admins can add their own OS family/version,
# same CRUD/seed/origin pattern as the product catalogue and (Stage 7) the
# golden-path template catalogue.

class BMOSFamily(Base):
    __tablename__ = "bm_os_families"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)  # e.g. "ubuntu"
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "Ubuntu"
    icon: Mapped[str] = mapped_column(String(8), nullable=False, default="🐧")
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="user")  # 'builtin' | 'user'
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    versions: Mapped[list["BMOSVersion"]] = relationship("BMOSVersion", back_populates="family", cascade="all, delete-orphan")


class BMOSVersion(Base):
    __tablename__ = "bm_os_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    os_family_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_os_families.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "24.04"
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "24.04 LTS"
    eol_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    family: Mapped["BMOSFamily"] = relationship("BMOSFamily", back_populates="versions")


class BMProductConfig(Base):
    __tablename__ = "bm_product_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    environment_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_environments.id", ondelete="CASCADE"), nullable=False)
    host_role: Mapped[str] = mapped_column(String(128), nullable=False)
    product_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_product_versions.id"), nullable=False)
    config_vars: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    installed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    product_version: Mapped["BMProductVersion"] = relationship("BMProductVersion")


# --- Inventory (Stage 1) ---

class BMHost(Base):
    __tablename__ = "bm_hosts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    connection_type: Mapped[str] = mapped_column(String(16), nullable=False, default="docker")  # docker, ssh
    container_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")  # Docker container name (used for ansible_host when docker)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_user: Mapped[str] = mapped_column(String(64), nullable=False, default="root")
    os_type: Mapped[str] = mapped_column(String(32), nullable=False, default="ubuntu")  # ubuntu, rhel
    os_version: Mapped[str] = mapped_column(String(32), nullable=False, default="24.04")
    service_role: Mapped[str] = mapped_column(String(32), nullable=False, default="generic")  # frontend, backend, mysql, rabbitmq, keystone
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="")  # comma-separated
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")  # online, offline, unknown
    last_seen: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="00000000-0000-0000-0000-000000000001")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    # Build Manager Hardening Plan, Stage 5 — per-host SSH credentials.
    # "shared_key" (default) preserves the original single-shared-key behaviour
    # for every pre-existing host; "private_key"/"password" opt a host into
    # its own credential, Fernet-encrypted at rest (see secrets_service.py's
    # encrypt_value/decrypt_value). ssh_credential_encrypted holds whichever
    # of the two applies — never both, semantics driven by ssh_auth_method.
    ssh_auth_method: Mapped[str] = mapped_column(String(16), nullable=False, default="shared_key")
    ssh_credential_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Enhancement Plan Stage 9 — TOFU host-key pinning. Stores the raw
    # ssh-keyscan line (not just a fingerprint) so it can be written directly
    # into a known_hosts file for real enforcement during Ansible runs, not
    # just displayed. Null means "not yet pinned" — pinned automatically on
    # the first successful connection. Only meaningful for connection_type
    # == "ssh"; Docker-hosted containers are recreated fresh on every build
    # and have no stable identity to pin against.
    pinned_host_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    host_key_pinned_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    variables: Mapped[list["BMHostVar"]] = relationship("BMHostVar", back_populates="host", cascade="all, delete-orphan")
    group_memberships: Mapped[list["BMHostGroupMember"]] = relationship("BMHostGroupMember", back_populates="host", cascade="all, delete-orphan")


class BMHostGroup(Base):
    __tablename__ = "bm_host_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="00000000-0000-0000-0000-000000000001")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    members: Mapped[list["BMHostGroupMember"]] = relationship("BMHostGroupMember", back_populates="group", cascade="all, delete-orphan")


class BMHostGroupMember(Base):
    __tablename__ = "bm_host_group_members"

    host_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_hosts.id", ondelete="CASCADE"), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_host_groups.id", ondelete="CASCADE"), primary_key=True)

    host: Mapped["BMHost"] = relationship("BMHost", back_populates="group_memberships")
    group: Mapped["BMHostGroup"] = relationship("BMHostGroup", back_populates="members")


class BMHostVar(Base):
    __tablename__ = "bm_host_vars"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    host_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_hosts.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    host: Mapped["BMHost"] = relationship("BMHost", back_populates="variables")


# --- Certificate Bindings (Stage 11 — Lifecycle) ---

class BMCertBinding(Base):
    __tablename__ = "bm_cert_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    environment_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_environments.id", ondelete="CASCADE"), nullable=False)
    cert_serial: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(128), nullable=False)
    cert_type: Mapped[str] = mapped_column(String(16), nullable=False, default="server")
    host_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("bm_hosts.id", ondelete="SET NULL"), nullable=True)
    cert_path: Mapped[str] = mapped_column(String(512), nullable=False, default="/etc/ssl/certs/server.pem")
    key_path: Mapped[str] = mapped_column(String(512), nullable=False, default="/etc/ssl/private/server-key.pem")
    ca_path: Mapped[str] = mapped_column(String(512), nullable=False, default="/etc/ssl/certs/ca-chain.pem")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_renewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    renewal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

    environment: Mapped["BMEnvironment"] = relationship("BMEnvironment", foreign_keys=[environment_id])


# --- Secrets (Stage 12) ---

class BMSecret(Base):
    __tablename__ = "bm_secrets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")  # database, messaging, identity, custom
    linked_service: Mapped[str] = mapped_column(String(128), nullable=False, default="")  # e.g. mysql, rabbitmq
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="00000000-0000-0000-0000-000000000001")
    rotated_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    # Enhancement Plan Stage 10 — policy-driven secret rotation. Null means
    # no policy (every existing secret keeps working exactly as before).
    # Deliberately flag-only, not auto-rotate: a wrong automatic rotation
    # could break a live service still using the old credential, so this
    # only surfaces overdue secrets (UI badge + a one-shot notification) for
    # someone to act on. rotation_notified avoids re-notifying on every scan
    # tick while a secret stays overdue; reset to False whenever the value
    # actually changes (create/update/rotate), since the clock restarts then.
    rotate_every_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rotation_notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)



# --- Health Checks (Stage 13) ---

class BMHealthCheck(Base):
    __tablename__ = "bm_health_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    environment_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_environments.id", ondelete="CASCADE"), nullable=False)
    host_role: Mapped[str] = mapped_column(String(128), nullable=False)
    service_type: Mapped[str] = mapped_column(String(64), nullable=False, default="generic")
    check_type: Mapped[str] = mapped_column(String(32), nullable=False, default="health")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_checked: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)

# --- Network Pools ---

class BMNetworkPool(Base):
    __tablename__ = "bm_network_pools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    cidr: Mapped[str] = mapped_column(String(45), nullable=False)  # e.g. 192.168.50.0/24
    gateway: Mapped[str] = mapped_column(String(45), nullable=False, default="")  # e.g. 192.168.50.1
    dns_servers: Mapped[str] = mapped_column(Text, nullable=False, default="")  # comma-separated
    reserved: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array of IPs or ranges to exclude
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="00000000-0000-0000-0000-000000000001")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)


# --- Config Editor (Stage 1) ---

class BMConfigFile(Base):
    __tablename__ = "bm_config_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    path: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="yaml")
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_modified_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    last_modified_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)


class BMConfigFileVersion(Base):
    __tablename__ = "bm_config_file_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(String(36), ForeignKey("bm_config_files.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    diff_patch: Mapped[str] = mapped_column(Text, nullable=False, default="")
    edited_by: Mapped[str] = mapped_column(String(128), nullable=False)
    edited_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), nullable=False)
    comment: Mapped[str] = mapped_column(String(512), nullable=False, default="")


# --- Settings (Improvements Plan Stage 22) ---

class BMSettings(Base):
    """Single global settings row, same shape/reasoning as CategoryRule
    (app/models/docs.py) — an admin toggle affecting every tenant at once,
    not per-tenant data, so one fixed row rather than a per-tenant table.
    Fetched/created lazily via get_or_create (bug_pattern_scan.py) rather
    than seeded by the migration, so a fresh install never needs a data
    migration just to have a settings row exist."""
    __tablename__ = "bm_settings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=lambda: "global")
    # Opt-in (default off) — auto-filing a bug is a real, visible side
    # effect of every failed job, not something that should start
    # happening silently on upgrade. See bug_pattern_scan.py's
    # maybe_auto_file_bug for the full behaviour.
    auto_file_bugs_on_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
