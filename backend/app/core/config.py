from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "/etc/certmanager/certmanager.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_VERSION: str = "0.1.0"

    # Required secrets
    CERT_MASTER_KEY: str
    API_KEY: str

    # Application
    BASE_URL: str = "https://certs.cso.internal"
    DATA_DIR: Path = Path("/var/lib/certmanager")
    JDK_HOME: Path | None = None
    CFR_JAR_PATH: Path | None = None  # CFR decompiler jar for the JAR Analyser's decompile feature
    VINEFLOWER_JAR_PATH: Path | None = None  # Vineflower — second decompiler engine, run alongside CFR
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Path = Path("/var/log/certmanager/app.log")

    # PKI Infrastructure
    PKI_BASE_URL: str = ""  # e.g. http://pki.internal — if empty, CDP/AIA/OCSP disabled
    CRL_VALIDITY_DAYS: int = 7

    # EST Protocol (RFC 7030)
    EST_CA_ID: str = ""  # CA ID to use for EST enrollment (empty = auto-select first available)

    # Auth / RBAC
    JWT_SECRET: str = ""  # If empty, falls back to CERT_MASTER_KEY
    JWT_EXPIRE_HOURS: int = 24

    # Certificate constraints
    MAX_CERT_DAYS: int = 398

    # Export
    EXPORT_TTL_HOURS: int = 24

    # Backup
    BACKUP_DIR: Path = Path("/var/lib/certmanager/backups")
    BACKUP_ENABLED: bool = True
    BACKUP_INTERVAL_HOURS: int = 24
    BACKUP_RETAIN_COUNT: int = 5

    # Bootstrap
    BOOTSTRAP_IP: str = "127.0.0.1"
    BOOTSTRAP_EXTRA_SANS: str = ""
    BOOTSTRAP_CA_CN: str = "Internal Root CA"
    BOOTSTRAP_CA_DAYS: int = 3650
    BOOTSTRAP_CERT_DAYS: int = 398

    # Monitoring
    EXPIRY_SCAN_INTERVAL_HOURS: int = 24
    EXPIRY_WARN_DAYS: str = "60,30,7"

    # Notifications
    NOTIFY_WEBHOOK_URL: str | None = None

    # Rate Limiting (0 = disabled)
    RATE_LIMIT_CERT_ISSUE: int = 10       # per user per minute
    RATE_LIMIT_CSR_GENERATE: int = 20     # per user per minute
    RATE_LIMIT_OCSP: int = 100            # global per second
    RATE_LIMIT_CRL: int = 10              # per IP per minute
    RATE_LIMIT_LOGIN: int = 5             # per IP per minute
    RATE_LIMIT_EXPORT_KEY: int = 10       # per user per minute
    RATE_LIMIT_GENERAL: int = 60          # per user per minute
    # Build Manager's Jobs page polls GET /build/jobs/{id} + /output every
    # ~1s while a job is running/selected (2 req/s sustained) — that alone
    # exceeds RATE_LIMIT_GENERAL's 1 req/s average, so job-status/output
    # polling gets its own, deliberately generous budget rather than sharing
    # the general one meant for one-off API calls.
    RATE_LIMIT_JOB_POLLING: int = 300     # per user per minute

    # Brute Force Protection
    LOGIN_MAX_ATTEMPTS: int = 5           # failed attempts before lockout
    LOGIN_LOCKOUT_MINUTES: int = 15       # lockout duration

    # Key Ceremony
    SIGNING_SESSION_TIMEOUT_MINUTES: int = 15  # default session timeout

    # Database
    DATABASE_URL: str = ""  # If empty, uses SQLite at DATA_DIR/certmanager.db
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_STATEMENT_TIMEOUT: int = 30000  # milliseconds (PostgreSQL only)

    # SMTP / Email Notifications
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "PKI Alerts <pki@corp.internal>"
    SMTP_TLS: str = "starttls"  # starttls, ssl, none
    SMTP_ENABLED: bool = False
    NOTIFICATION_DIGEST_HOUR: int = 8  # Hour (UTC) to send daily digest

    # Key Escrow
    KEY_ESCROW_RECOVERY_KEY: str = ""  # Separate Fernet key for escrow (if empty, derived from CERT_MASTER_KEY)
    KEY_RECOVERY_APPROVALS_REQUIRED: int = 2  # M-of-N: how many admins must approve

    # SCEP Protocol
    SCEP_ENABLED: bool = False
    SCEP_CA_ID: str = ""  # CA ID for SCEP enrollment (empty = auto-select)
    SCEP_CHALLENGE_PASSWORD: str = ""  # Shared secret for enrollment (empty = open enrollment)
    SCEP_PROFILE: str = "server"  # Certificate profile for SCEP-enrolled certs
    SCEP_MAX_VALIDITY_DAYS: int = 365  # Max validity for SCEP certs

    # LDAP / Active Directory
    LDAP_ENABLED: bool = False
    LDAP_URL: str = ""  # e.g. ldaps://dc.corp.internal:636
    LDAP_STARTTLS: bool = False  # Use STARTTLS on ldap:// (port 389)
    LDAP_BIND_DN: str = ""  # Service account DN for searches (empty = anonymous bind)
    LDAP_BIND_PASSWORD: str = ""  # Service account password
    LDAP_SEARCH_BASE: str = ""  # e.g. ou=People,dc=corp,dc=internal
    LDAP_SEARCH_FILTER: str = "(uid={username})"  # {username} is replaced at runtime
    LDAP_USER_DN_TEMPLATE: str = ""  # Direct bind: uid={username},ou=People,dc=corp,dc=internal
    LDAP_TLS_CA_CERT: str = ""  # Path to CA cert for LDAP TLS validation
    LDAP_TIMEOUT: int = 10  # Connection timeout seconds
    # Group-to-role mapping
    LDAP_ROLE_ADMIN: str = ""  # e.g. cn=pki-admins,ou=Groups,dc=corp,dc=internal
    LDAP_ROLE_OPERATOR: str = ""  # e.g. cn=pki-operators,ou=Groups,dc=corp,dc=internal
    LDAP_ROLE_AUDITOR: str = ""  # e.g. cn=pki-auditors,ou=Groups,dc=corp,dc=internal
    LDAP_ROLE_DEFAULT: str = "readonly"  # Role when no group matches
    LDAP_GROUP_ATTRIBUTE: str = "memberOf"  # User attribute containing group DNs

    # ML Diagnostic Pipeline (Neural/phase5)
    ML_SCORER_PATH: Path | None = None   # fitted AnomalyScorer .pkl — if None, anomaly scoring is skipped
    ML_LOG_PATH: Path | None = None      # single log file (or use ML_LOG_PATHS for multi-source)
    ML_LOG_PATHS: str | None = None      # colon-separated list of paths/globs/dirs e.g. /var/log/app:/var/log/gw/*.log
    ML_TAIL_LINES: int = 10_000          # max lines to read from tail of each log file

    # Build Manager
    BM_SSH_KEY_PATH: str = "/data/ssh/id_ed25519"
    BM_MAX_PARALLEL_JOBS: int = 3
    BM_ANSIBLE_TIMEOUT: int = 1800  # 30 minutes default job timeout
    BM_HOST_KEY_CHECKING: bool = False
    BM_TTL_CHECK_INTERVAL_MINUTES: int = 5
    BM_SECRET_ROTATION_CHECK_INTERVAL_MINUTES: int = 60
    # Automatic job retry: a job that reports specific fatal/unreachable
    # hosts (not a hard config/logic error, which never gets host-level
    # results at all) is automatically re-submitted, limited to just those
    # hosts, up to this many times before being left as a real, final
    # failure. Added after live testing found this Docker host's network can
    # intermittently kill an in-progress SSH session for reasons outside
    # Ansible/this app's control — undetectable in advance, but often
    # transient enough that a later attempt succeeds. The delay started at
    # 20s but a real live build still failed 4/4 attempts, each dying at the
    # very first task (a fresh SSH connection failing to even establish) —
    # evidence the disruption on this host can last in extended multi-minute
    # windows, not just brief few-second bursts, so 20s wasn't giving retries
    # a real chance to land in a clear window.
    BM_MAX_AUTO_RETRIES: int = 5
    BM_AUTO_RETRY_DELAY_SECONDS: int = 90

    @property
    def db_path(self) -> Path:
        return self.DATA_DIR / "certmanager.db"

    @property
    def db_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.db_url

    @property
    def is_mysql(self) -> bool:
        return "mysql" in self.db_url

    @property
    def is_sqlite(self) -> bool:
        # FTS5 full-text search (Improvements Plan Stage 11) is SQLite-only —
        # gates every FTS5-specific code path so Postgres/MySQL deployments
        # keep working via the ILIKE/word-overlap fallback instead of erroring.
        return not (self.is_postgres or self.is_mysql)

    @property
    def self_cert_dir(self) -> Path:
        return self.DATA_DIR / "self"

    @property
    def exports_dir(self) -> Path:
        return self.DATA_DIR / "exports"


def _validate_settings() -> Settings:
    """Load and validate settings on import. Fail fast on missing required config."""
    import sys
    try:
        s = Settings()  # type: ignore[call-arg]
    except Exception as e:
        print(f"FATAL: Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate CERT_MASTER_KEY format (must be valid Fernet key)
    try:
        from cryptography.fernet import Fernet
        Fernet(s.CERT_MASTER_KEY.encode())
    except Exception:
        print("FATAL: CERT_MASTER_KEY is not a valid Fernet key.", file=sys.stderr)
        print("  Generate one with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"", file=sys.stderr)
        sys.exit(1)

    # Validate API_KEY minimum length
    if len(s.API_KEY) < 16:
        print("FATAL: API_KEY must be at least 16 characters.", file=sys.stderr)
        sys.exit(1)

    return s


settings = _validate_settings()
