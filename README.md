# Labtool

Web-based Self-Signed Certificate Authority, Trust Store & CSR Tool — and, sharing the same container, UI, and auth system, three companion tools: **Build Manager** (Ansible-driven environment provisioning), **JAR Analyser** (static bytecode analysis of Spring Boot bundles), and **Docs** (a wiki-style knowledge base with an integrated Bug Tracker).

## Overview

A browser-based tool for engineering and infrastructure teams to generate, manage, and distribute X.509 certificates and Java KeyStore/TrustStore artefacts across Linux, Windows, and Java environments — and to provision, document, and troubleshoot the environments those certificates get deployed into. Reached via a mode switcher in the top nav: **Cert Manager**, **Build Manager**, **JAR Analyser**, **Docs**. All four modes share one login, one set of roles (Admin/Operator/Auditor/ReadOnly), and one Docker container.

## Feature Areas

### Certificate Manager

**Certificate Management:**
- Root & Intermediate CA creation with chain visualisation
- Certificate issuance (Server TLS, Client mTLS, Code Signing, Email, Custom)
- CSR generation (new key, existing key upload, or renewal from existing cert)
- Import signed certificates from external CAs (DigiCert, Sectigo, Let's Encrypt, etc.)
- Certificate revocation & CRL generation
- Export in 7 formats: PEM, DER, Chain, Key, PKCS#12, JKS, Bundle ZIP
- Tags/labels for organisation and filtering
- Search by CN, SAN, serial number, or tag

**Java & Trust Store:**
- Java KeyStore and TrustStore builder (JKS / PKCS#12)
- TrustStore merger (combine system cacerts + internal CA)
- PEM → KeyStore converter
- Spring Boot configuration snippets

**Certificate Tools (14 utilities):**
- Decode any certificate (paste PEM or upload file)
- Remote server certificate check (connect and inspect live TLS)
- Service compatibility checker (Nginx, MySQL, RabbitMQ, Java, Keycloak, Keystone)
- Certificate chain expiry check (catches expired intermediates)
- Full TLS connection tester (custom trust, mTLS, reports Java-equivalent errors)
- Chain verification (cryptographic signature validation)
- Key / certificate match checker
- Java TLS debug command generator
- OpenSSL command generator (per-service)
- Format converter (PEM ↔ DER)
- PKCS#12 builder (combine cert + key + chain)
- Bulk certificate import
- Certificate troubleshooter wizard (guided debugging for 8 common scenarios)

**PKI Infrastructure:**
- CRL Distribution Point (CDP) and Authority Information Access (AIA) extensions
- OCSP responder (RFC 6960 compliant) with stapling support
- Certificate templates with policy enforcement (key algo, key size, validity, SAN types, CN pattern)
- 5 built-in templates: Server TLS, Client mTLS, Code Signing, Email S/MIME, Internal Service

**Access Control (RBAC):**
- User accounts with role-based access: Admin, Operator, Auditor, Read-Only
- JWT session authentication + legacy API key support
- Scoped API keys with role assignment and expiry
- Permission matrix enforced on all write operations
- Full audit trail records acting user for every operation

**Operations:**
- Full audit trail of every operation and download
- Encrypted backups (AES-256-GCM) with scheduled jobs and restore CLI
- Certificate expiry monitoring with configurable thresholds
- Webhook notifications for expiry alerts
- Calendar export (ICS) and JSON monitoring feed
- System diagnostics page (live environment info, health checks, storage)
- Recent errors panel (no SSH required)
- API key rotation
- Platform trust distribution scripts (Debian, RHEL, Alpine, Arch, Windows)

Full detail: `Documentation/ssl_cert_manager_operations_guide.md`.

### Build Manager

Ansible-driven provisioning of complete multi-host environments — templates in, running (and certificate-secured) infrastructure out. Runs inside the same container and hands off to Cert Manager automatically for every certificate a template's hosts need.

- **Templates** — versioned blueprints (hosts, host groups, IP pools, software roles, playbook sequence); every edit creates a new immutable version
- **Catalogue** — a growing library of supported services/roles (nginx, MySQL, RabbitMQ, Keystone, Redis, MongoDB, PostgreSQL, OpenLDAP, HAProxy, Docker CE, Apache, Erlang, PHP, Adminer, and more), Ubuntu and RHEL 8 both supported where the underlying role has dnf logic
- **Environments** — instantiate a template version into a real, running environment: IP allocation from pools, host registration, base provisioning (Java, CA trust, JKS), per-host certificate issuance, software install, service start
- **Jobs** — every Ansible playbook run tracked with live output, status, and duration
- **Cross-host trust** — real, verified TLS between provisioned services (e.g. Keystone→MySQL, frontend-lb→frontend), not just loopback
- **Cert Lifecycle** — renewal, health checks, and PKI posture reporting across every certificate an environment holds
- **Config Editor** — in-browser editing of a live host's config files, versioned
- **Package Cache** — pre-seeded apt/dnf package cache to speed up repeat provisioning runs
- **Preflight checks** — network-pool host reachability and per-host product conflict detection, enforced server-side before a build can start

Full detail: `Documentation/build_manager_operations_guide.md` (and `-aws.md` for AWS-backed environments).

### JAR Analyser

Static bytecode analysis of Spring Boot fat JARs, WAR files, and ZIP bundles — no JVM started, no code executed, no network calls made. Upload once; every view, export, and comparison after that is served from the stored analysis.

- **Deep extraction** — endpoints (REST/JAX-RS), dependencies, config keys and placeholders, DB migrations (Flyway) with reconstructed schema, scheduled tasks, security annotations, service topology, RabbitMQ message bus wiring
- **Decompilation** — CFR and Vineflower engines, cross-referenced against the extracted facts
- **Version diffing** — structured comparison between two analysed versions, plus a formal Change Report exportable as Markdown or PDF (breaking-change and security-change detection)
- **Exports** — OpenAPI, Postman collection, JS/TS SDK stubs, Markdown/JSON report, onboarding-oriented Reference Doc, example config documents
- **Error Knowledge Base & Diagnose** — paste a real error/stack trace (or pick a report) and get matched causes, fix steps, and report-context-aware findings; usage tracking shows which KB entries are actually pulling their weight
- **Cross-report bug pattern scan** — every newly analysed report is automatically scanned against the Bug Tracker's open bugs for likely matches
- **Nginx config generator**, pagination/deprecation/dead-endpoint detection, security posture summary, migration risk scoring

Full detail: `Documentation/jar_analyser_operations_guide.md`.

### Docs & Bug Tracker

A Library → Shelf → Document knowledge base with a full markdown editor, plus a structured Bug Tracker built on top of it — both reached from the same "Docs" mode.

**Docs:**
- CodeMirror markdown editor with live split-view preview, wiki-links (`[[Doc Name]]`), callouts, footnotes, and Mermaid diagram rendering
- Highlighting/annotations that re-anchor correctly across document versions
- Relationship Map (force-directed graph of wiki-links/shared headings/keywords, per-library or across all libraries, with persisted manual layout)
- Structured/Card view — an alternate, auto-categorised reading mode with an admin-editable category-rule mapping
- Full-text search (SQLite FTS5 with ranking/snippets where available)
- PDF and raw-Markdown export
- Version history with diff view, soft-delete Rubbish with 30-day recovery, move/bulk actions

**Bug Tracker:**
- Structured intake (severity, frequency, scope, environment, repro steps, infra-specific fields) tied to a specific JAR Analyser report/service
- Status workflow with full timeline, threaded comments, and file attachments (screenshots, logs — 25 MB max)
- Cross-report occurrence tracking and automated pattern-matching against newly analysed reports
- Assignment to real accounts, "My Bugs" filtering, dashboard metrics, email/in-app activity notifications
- "Save to Docs" — turn a resolved bug's write-up into a searchable Doc automatically

Full detail: `Documentation/docs_operations_guide.md`.

## Project Structure

```
├── backend/           # FastAPI application (Python 3.11+)
│   ├── app/
│   │   ├── api/v1/    # REST endpoint routers (cert manager, build manager,
│   │   │               #   jar-analyser, docs, bug tracker, ...)
│   │   ├── core/      # Config, database, security
│   │   ├── models/    # SQLAlchemy ORM models
│   │   ├── services/  # Business logic (crypto, keytool, backup, ...)
│   │   │   ├── build_manager/    # Provisioning engine, catalogue, ansible runner
│   │   │   ├── jar_analyser/     # Bytecode analysis, decompiler, exports
│   │   │   └── infra_diagnostics/
│   │   ├── middleware/ # Request middleware
│   │   └── templates/ # Jinja2 templates for scripts/READMEs
│   ├── alembic/       # Database migrations
│   └── tests/         # pytest test suite
├── frontend/          # React SPA (Vite + TypeScript + Tailwind)
│   └── src/
│       ├── components/ # Reusable UI components
│       │   ├── tools/       # Cert Manager tool-specific components
│       │   ├── provisioning/ # Build Manager components
│       │   ├── jar-analyser/ # JAR Analyser components
│       │   └── docs/        # Docs + Bug Tracker components
│       ├── pages/      # Page components (routed) — one mode switcher, four modes
│       └── lib/        # API client, types, utilities
├── playbooks/         # Ansible roles/playbooks used by Build Manager
├── docker/            # Dockerfile and docker-compose
├── scripts/           # Deployment, install, smoke test
└── Documentation/     # Operations guides (one per feature area) + internal planning docs
```

## Prerequisites

- Python 3.11+ (3.12 or 3.13 recommended)
- Node.js 20 LTS
- OpenJDK 17 (for keytool — optional, JKS features disabled without it)
- OpenSSL 3.x

## Quick Start (Docker — Windows)

Requires Docker Desktop for Windows.

```
cd docker
certmanager.bat start
```

Or with PowerShell:
```powershell
cd docker
.\certmanager.ps1 start
```

On first run the container auto-generates secrets and prints the API key. Retrieve it any time with:
```
certmanager.bat key
```

**Access:**
- Browser: http://127.0.0.1 (use `127.0.0.1` not `localhost` — browsers may force HTTPS on `localhost` due to cached HSTS policies)
- API docs: http://127.0.0.1/api/docs
- Direct API: http://127.0.0.1:8000/api/v1/health

**Default Login:**

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin` | Admin (full access) |

> ⚠️ **Change the default password immediately** after first login via the UI or API (`POST /api/v1/auth/change-password`). The legacy API key (shown with `certmanager.bat key`) also works and grants admin access.

You can authenticate two ways:
1. **User login** — username/password on the login page (issues a JWT token)
2. **API key** — paste the legacy API key or a scoped API key on the login page

**Management commands:**

| Command | Description |
|---------|-------------|
| `start` | Build image and start container |
| `stop` | Stop container (data preserved in volume) |
| `restart` | Restart container |
| `status` | Show container state and health check |
| `logs` | Follow live container logs |
| `key` | Display the API key |
| `build` | Rebuild image without starting |
| `destroy` | Remove container (prompts before deleting data volume) |

Data (database, keys, backups) persists in a Docker volume across restarts and rebuilds. Only `destroy` with the volume removal confirmation deletes it permanently.

---

## Quick Start (Development — Linux/macOS)

**One command setup:**

```bash
bash scripts/dev-setup.sh
```

This creates the venv, installs dependencies, generates secrets, runs migrations, and starts both servers. The API key is printed on first run.

**Default login:** username `admin`, password `admin`. Change it immediately after first login.

**Manual setup:**

```bash
# Install backend
make install-backend

# Install frontend
make install-frontend

# Generate environment file
cp backend/.env.example backend/.env
# Edit backend/.env — generate keys with:
#   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#   python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Run backend (terminal 1)
make dev-backend

# Run frontend (terminal 2)
make dev-frontend
```

**Access:**
- Frontend: http://localhost:3000
- API docs (Swagger): http://localhost:8000/api/docs
- Health check: http://localhost:8000/api/v1/health

## Production Deployment

```bash
sudo bash scripts/install.sh
```

See `Documentation/ssl_cert_manager_operations_guide.md` for full deployment instructions, service configuration guides (Nginx, MySQL, RabbitMQ, Java, Keycloak, Keystone), and the Java SSL/TLS deep dive.

## Documentation

| Document | Description |
|----------|-------------|
| `Documentation/ssl_cert_manager_operations_guide.md` | Cert Manager operations guide (34 sections) — SSL fundamentals, tool usage, service configs, Java deep-dive, PKI infrastructure, troubleshooting |
| `Documentation/build_manager_operations_guide.md` | Build Manager operations guide — templates, environments, catalogue, jobs, cert lifecycle |
| `Documentation/build_manager_operations_guide-aws.md` | Build Manager — AWS-backed environments |
| `Documentation/jar_analyser_operations_guide.md` | JAR Analyser developer reference — extraction, exports, diffing, error KB, diagnose |
| `Documentation/docs_operations_guide.md` | Docs & Bug Tracker developer reference |
| `Documentation/infra_diagnostics_help.md` | Infra diagnostics tool reference |
| `Documentation/cpi_services_reference.md` | Reference for the CPI service catalogue used by Build Manager |
| `Documentation/install-descriptions.md` | Per-service install/config notes referenced by Build Manager templates |
| `Documentation/ssl_fundamentals.md` | Standalone SSL/TLS/PKI primer |

Each of the four modes also has its own in-app Help page (e.g. `/help`, `/bm-help`, `/jar-help`, `/docs-help`), serving these same guides section-by-section. `Documentation/planning/` holds internal design/staging documents for work in progress — not required reading to use the app.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| API | FastAPI (Python 3.11+) |
| Auth | JWT (PyJWT) + Argon2 password hashing |
| Crypto | pyca/cryptography + keytool (JDK 17) |
| Database | SQLite + SQLAlchemy 2.x (async) + Alembic |
| Container | Docker + docker-compose |

## API

400+ REST endpoints across the four feature areas. Full reference in each area's operations guide or at `/api/docs` when running.

Key Cert Manager endpoints:
- `POST /api/v1/auth/login` — Authenticate (returns JWT token)
- `GET /api/v1/auth/me` — Current user info
- `POST /api/v1/ca` — Create CA (admin only)
- `POST /api/v1/cert` — Issue certificate (admin, operator)
- `POST /api/v1/csr` — Generate CSR
- `POST /api/v1/csr/renew` — Renew from existing cert (auto-extract)
- `GET /api/v1/export/{serial}/{fmt}` — Export certificate
- `GET /api/v1/users` — List users (admin only)
- `POST /api/v1/users` — Create user (admin only)
- `GET /api/v1/api-keys` — List scoped API keys (admin only)
- `POST /api/v1/api-keys` — Create scoped API key (admin only)
- `GET /api/v1/templates` — List certificate templates
- `POST /api/v1/tools/compatibility-check` — Service compatibility check
- `POST /api/v1/tools/connection-test` — Full TLS handshake test
- `GET /api/v1/diagnostics` — System diagnostics
- `GET /api/v1/help/sections` — Operations guide (in-app help)

Key Build Manager / JAR Analyser / Docs endpoints:
- `POST /api/v1/build/templates`, `POST /api/v1/build/environments/{id}/build` — Create a template, build an environment
- `GET /api/v1/build/jobs/{id}` — Job status/output
- `POST /api/v1/jar-analyser/upload` — Upload a JAR/WAR/ZIP for analysis
- `GET /api/v1/jar-analyser/reports/{id}` — Full analysis report
- `POST /api/v1/jar-analyser/reports/{id}/diagnose` — Match pasted error text against the report + Error KB
- `GET /api/v1/docs/search`, `GET /api/v1/docs/error-kb/search` — Full-text doc search / Error KB search
- `GET /api/v1/bugs`, `POST /api/v1/bugs`, `POST /api/v1/bugs/{id}/attachments` — Bug list/create, file attachments

## Roles & Permissions

| Action | Admin | Operator | Auditor | ReadOnly |
|--------|:-----:|:--------:|:-------:|:--------:|
| Create/delete CA | ✓ | ✗ | ✗ | ✗ |
| Issue certificate | ✓ | ✓ | ✗ | ✗ |
| Revoke certificate | ✓ | ✓ | ✗ | ✗ |
| Export with private key | ✓ | ✓ | ✗ | ✗ |
| View certificates | ✓ | ✓ | ✓ | ✓ |
| View audit log | ✓ | ✓ | ✓ | ✗ |
| Manage users & keys | ✓ | ✗ | ✗ | ✗ |
| Manage templates | ✓ | ✓ | ✗ | ✗ |
| System settings | ✓ | ✗ | ✗ | ✗ |
| Backup/restore | ✓ | ✗ | ✗ | ✗ |

The same four-role model applies in Build Manager, JAR Analyser, and Docs/Bug Tracker, with the same general shape (Operator = create/read/update, Admin adds delete, Auditor/ReadOnly = read-only) — see each area's own operations guide for its exact permission matrix.

## License

Internal tool — not publicly licensed.
# sslv31
