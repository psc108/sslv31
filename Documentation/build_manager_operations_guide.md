# Build Manager � Operations Guide

## 1. Overview & Concepts

Build Manager is a companion application to SSL Cert Manager that automates on-premises application deployment using Ansible. It runs inside the same Docker container, shares the same UI and authentication system, and integrates with SSL Cert Manager for automatic certificate provisioning.

### Core Concepts

| Concept | Description |
|---------|-------------|
| Template | A versioned blueprint defining the complete environment � hosts, software, certificates, network, and playbook sequence |
| Template Version | An immutable snapshot of a template. Every edit creates a new version. Old versions are preserved for audit and rollback |
| Environment | A running instance created from a specific template version. Has real IPs, real certificates, and real state |
| Host | A target machine (VM or container) managed by Ansible via SSH |
| Host Group | A logical grouping of hosts for targeting and variable assignment |
| Job | An Ansible playbook execution � tracked with status, output, and duration |
| IP Pool | A network range defined in a template. IPs are allocated from the pool on environment instantiation |
| Service Role | The primary function of a host (frontend, backend, mysql, rabbitmq, keystone) |

### How It Works

```
Template (blueprint)
     �
     ?
Instantiate ? Environment (pending)
     �           - IPs allocated
     �           - Hosts registered
     ?
Build ? Environment (active)
     �    - Base provisioning (Java, CA trust, JKS)
     �    - Certificates issued per host
     �    - Software installed per role
     �    - Services configured and started
     ?
Operate ? Health checks, cert renewal, monitoring
     �
     ?
Destroy ? Environment (destroyed)
           - Certificates revoked
           - Environment record deleted from DB
           - Target host services persist until next build purges them
```

### Relationship to SSL Cert Manager

SSL Cert Manager is the **sole certificate authority** for all Build Manager deployments. Build Manager calls SSL Cert Manager's internal API to:
- Issue server and client certificates per host role
- Revoke certificates when environments are destroyed
- Renew certificates approaching expiry
- Export CA chains for trust store distribution

There is no external CA dependency. All certificates are scoped to their environment and have a clear lifecycle.

---

## 2. Quick Start

### Prerequisites

- Docker Desktop running
- The `docker-compose.build-manager.yml` file (includes certmanager + 5 target containers)
- API key or admin login credentials

### UI Navigation

The application has two modes accessible via a pill toggle at the top of the sidebar:

- **?? Certificates** � SSL Cert Manager (CA management, certificate issuance, tools)
- **?? Build Mgr** � Build Manager (templates, environments, jobs, inventory)

Clicking the toggle switches the entire sidebar navigation and redirects to that module's dashboard. The mode auto-detects based on the current URL � navigating to any `/bm*`, `/inventory`, `/environments`, or `/jobs` route automatically switches to Build Manager mode.

The selected mode persists in browser localStorage across page refreshes.

### Start the Dev Environment

```bash
cd docker
docker compose -f docker-compose.build-manager.yml up -d
```

This starts 6 containers:
- `certmanager` � main application (FastAPI + React + Ansible), with Docker socket mounted for network discovery
- `target-frontend` � simulates the Nginx host (systemd, privileged)
- `target-backend` � simulates the FastAPI host (systemd, privileged)
- `target-mysql` � simulates the MySQL host (systemd, privileged)
- `target-rabbitmq` � simulates the RabbitMQ host (systemd, privileged)
- `target-keystone` � simulates the Keystone host (systemd, privileged)

The certmanager container mounts `/var/run/docker.sock` (read-only) to enable Docker network discovery for the Network Pools feature. This allows the UI to list available Docker networks and pre-fill pool configuration from them.

Target containers run Ubuntu 24.04 with **systemd as PID 1** (privileged mode, cgroup mounts, tmpfs on `/run`). This accurately simulates real VMs � `systemctl` works, services start/stop correctly, and Ansible's `service` module behaves identically to production.

### Verify Connectivity

1. Open the UI at `http://127.0.0.1`
2. Log in (default: `admin` / `admin`)
3. Navigate to **Build Manager ? Inventory**
4. Click **Test SSH** on any host � should show a green success with latency

### First Workflow (once templates are implemented)

1. **Create a template** � define hosts, roles, network pool, cert config
2. **Instantiate an environment** � allocate IPs, create host records
3. **Build** � runs the playbook sequence (base provisioning ? services)
4. **Monitor** � health checks confirm services are running
5. **Destroy** � revokes certs, tears down, marks destroyed

---

## 3. Templates

Templates are versioned blueprints that define a complete deployment environment. Every environment is created from a template � there is no ad-hoc deployment.

### Template Lifecycle

```
Create template (v1)
     �
     ?
Edit ? new version (v2, v3, ...)
     �
     ?
Instantiate ? environment linked to exact version
     �
     ?
Delete (only if no active environments reference it)
```

### Template Properties

| Field | Description |
|-------|-------------|
| Name | Unique template name (e.g. `production-stack`, `dev-minimal`) |
| Description | Readable purpose |
| Tags | JSON array of labels for filtering (e.g. `["production", "full-stack"]`) |
| Current Version | The latest version number (auto-incremented) |
| Created By | User who created the template |

### Template Spec (Version Payload)

Each version contains a `spec` JSON object defining the full environment blueprint:

```json
{
  "hosts": [
    {
      "role": "frontend",
      "hostname_pattern": "{{env_name}}-frontend",
      "os": "ubuntu:24.04",
      "software": ["nginx"],
      "certs": ["server_tls"]
    },
    {
      "role": "backend",
      "hostname_pattern": "{{env_name}}-backend",
      "os": "ubuntu:24.04",
      "software": ["python3", "java17"],
      "certs": ["server_tls", "client_mtls"]
    },
    {
      "role": "mysql",
      "hostname_pattern": "{{env_name}}-mysql",
      "os": "ubuntu:24.04",
      "software": ["mysql-server"],
      "certs": ["server_tls"]
    },
    {
      "role": "rabbitmq",
      "hostname_pattern": "{{env_name}}-rabbitmq",
      "os": "ubuntu:24.04",
      "software": ["rabbitmq-server"],
      "certs": ["server_tls"]
    },
    {
      "role": "keystone",
      "hostname_pattern": "{{env_name}}-keystone",
      "os": "ubuntu:24.04",
      "software": ["keystone"],
      "certs": ["server_tls"]
    }
  ],
  "network": {
    "subnet": "192.168.50.0/24",
    "range_start": "192.168.50.10",
    "range_end": "192.168.50.50"
  },
  "certificates": {
    "ca": "internal-ca",
    "key_algorithm": "RSA",
    "key_size": 2048,
    "validity_days": 365,
    "san_include_localhost": true
  },
  "playbook_sequence": [
    "base-provision.yml",
    "certificates.yml",
    "services.yml",
    "health-check.yml"
  ]
}
```

### Spec Validation

The template service validates specs on save:
- `hosts` must be a non-empty list
- Each host must have `role` and `hostname_pattern`
- `network` must include `subnet`, `range_start`, `range_end`
- IP range must be valid and `range_start` = `range_end`

Invalid specs are rejected with a 400 error and descriptive message.

### Versioning

Every save creates a new **immutable** version:
- Versions are numbered sequentially (v1, v2, v3, ...)
- A **change note** is required for every new version (explains what changed)
- The `is_current` flag marks the latest version
- Old versions are never modified or deleted
- Environments link to the exact version they were instantiated from

**Creating a new version (UI):**
1. Navigate to **Build Manager ? Templates**
2. Select a template from the list
3. Edit the spec JSON in the editor
4. Enter a change note (required)
5. Click **Save New Version**

**Creating a new version (API):**
```bash
curl -X PUT http://127.0.0.1:8000/api/v1/build/templates/<id> \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "spec": { ... },
    "change_note": "Added RabbitMQ TLS client cert requirement"
  }'
```

### Version History

View all versions of a template:

```bash
curl http://127.0.0.1:8000/api/v1/build/templates/<id>/versions \
  -H "Authorization: Bearer <token>"
```

Response includes version number, change note, creation timestamp, and `is_current` flag for each version.

### YAML Export / Import

Templates can be exported as YAML for git versioning, sharing, or backup.

**Export:**
```bash
curl http://127.0.0.1:8000/api/v1/build/templates/<id>/versions/<v>/export \
  -H "Authorization: Bearer <token>"
```

Returns:
```yaml
name: production-stack
description: Full 5-host production deployment
tags:
  - production
  - full-stack
version: 3
change_note: Added health check playbook
spec:
  hosts:
    - role: frontend
      hostname_pattern: "{{env_name}}-frontend"
      ...
```

**Import:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/templates/import \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"yaml_content": "name: my-template\ndescription: ...\nspec:\n  hosts: ...\n"}'
```

Import creates a new template with v1 from the YAML content. If the template name already exists, the request is rejected.

### Delete Protection

A template cannot be deleted if any **non-destroyed** environment references it. This prevents orphaning active deployments.

```
DELETE /api/v1/build/templates/<id>

# If active environments exist:
409 Conflict: "Cannot delete template with active environments"

# If all referencing environments are destroyed:
200 OK: Template deleted
```

---

## 4. Environments

An environment is a running instance of a template version. It has real IP allocations, real certificates, and real infrastructure state.

### Environment States

| Status | Description |
|--------|-------------|
| `pending` | Instantiated � IPs allocated, hosts registered, not yet built |
| `provisioning` | Build job is running (playbooks executing) |
| `active` | Fully deployed and operational |
| `degraded` | Partially operational (some hosts failed) |
| `failed` | Build failed (check job output for errors) |

### Instantiation

Creating an environment from a template:

**Via UI:**
1. Navigate to **Build Manager ? Environments**
2. Click **New Environment**
3. Select a template (uses current version)
4. Optionally provide IP overrides and variable overrides
5. Click **Instantiate**

**Via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/environments \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "dev-01",
    "template_id": "<template-uuid>",
    "ip_overrides": {
      "frontend": "192.168.50.20",
      "backend": "192.168.50.21"
    },
    "variable_overrides": {
      "mysql_port": "3307",
      "domain": "dev.internal"
    }
  }'
```

**What happens on instantiation:**
1. Template's current version spec is read
2. IPs are allocated from the network pool (or user overrides applied)
3. Environment record is created with status `pending`
4. IP allocations and variable overrides are stored

### IP Allocation

See **Section 10 � IP Allocation & Networking** for full details.

### Building an Environment

After instantiation, trigger the build to deploy infrastructure:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/environments/<id>/build \
  -H "Authorization: Bearer <token>"
```

This issues certificates for all hosts, then runs `site.yml` which executes base provisioning followed by product deployment. Status transitions: `pending` ? `provisioning` ? `active` (or `failed`).

The Build action is the only deployment action needed � it always runs the full flow (certs + base + products) in a single pass.

### Destroying an Environment

```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/environments/<id>/destroy \
  -H "Authorization: Bearer <token>"
```

**What happens on destroy:**
1. All certificates issued to this environment are **revoked** via SSL Cert Manager
2. Environment record is **deleted** from the database (frees the name for reuse)
3. Associated environment certs and product configs are cascade-deleted
4. IP allocations are released

**Important:** Destroy is a **database-only** operation. Services deployed on target hosts are NOT stopped or removed. They persist until the next build's purge step cleans them (every role starts with a purge of existing installations). This is intentional � the nuke-before-install pattern ensures clean state on every build without requiring a separate teardown playbook.

### Rebuilding an Environment

```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/environments/<id>/rebuild \
  -H "Authorization: Bearer <token>"
```

Rebuild revokes existing certificates, re-issues new ones, and runs the full `site.yml` playbook. Useful when an environment is in a `failed` state or needs fresh certificates.

### Environment Certificates

View all certificates issued to an environment:

```bash
curl http://127.0.0.1:8000/api/v1/build/environments/<id>/certs \
  -H "Authorization: Bearer <token>"
```

Returns a list of certificate records with serial number, role, cert type, and revocation status. Certificates are ephemeral � they exist only for the lifetime of the environment.

### Environment Variables

Variable overrides provided at instantiation are merged with template defaults at build time. They are passed to Ansible as extra vars.

Common overrides:
- `domain` � base domain for certificate SANs
- `mysql_port` � non-standard port
- `tls_min_version` � minimum TLS version (e.g. `1.2`, `1.3`)

### Base Provisioning (Stage 3)

Base provisioning is the first step after instantiation. It prepares all hosts with the common infrastructure needed before any service-specific deployment.

**What it does per host:**
1. Installs OpenJDK 17
2. Installs `ca-certificates` package
3. Deploys the CA chain PEM to the OS-specific trust store path
4. Runs the OS-specific trust update command to register the internal CA in the system store
5. Issues a host-specific server certificate (CN: `<role>.<domain>`, SANs include localhost, 127.0.0.1, container hostname)
6. Deploys server cert + key to `/etc/ssl/certs/` and `/etc/ssl/private/`
7. Builds a Java TrustStore (JKS) at `/etc/pki/java/truststore.jks` containing the CA chain
8. Builds a Java KeyStore (JKS) at `/etc/pki/java/keystore.jks` containing the server cert + key
9. Issues a client certificate if the host spec includes `client_certs: [...]` (CN: `<role>-client.<domain>`, passed as `client_cert_pem`/`client_key_pem` host vars)

**OS Trust Store Integration:**

The base role installs the internal CA into the Linux system trust store so that `curl`, `wget`, `apt`, `pip`, and any application using the system CA bundle will trust certificates issued by the Build Manager CA.

| OS Family | CA File Path | Update Command |
|-----------|-------------|----------------|
| Debian/Ubuntu | `/usr/local/share/ca-certificates/internal/internal-ca.crt` | `update-ca-certificates` |
| RHEL/CentOS | `/etc/pki/ca-trust/source/anchors/internal-ca.crt` | `update-ca-trust extract` |
| Alpine | `/usr/local/share/ca-certificates/internal-ca.crt` | `update-ca-certificates` |
| Arch | `/etc/ca-certificates/trust-source/anchors/internal-ca.crt` | `trust extract-compat` |

The trust update runs as an explicit task (not a handler) immediately after deploying the CA file. This guarantees the system store is updated even if a later task in the play fails.

**What this enables:**
- `curl https://target-backend:8000/` works without `--cacert` or `-k`
- `apt-get` can fetch from internal HTTPS repos signed by the CA
- Python `requests` / `httpx` trust the CA via the system bundle
- Node.js respects the system store when `NODE_EXTRA_CA_CERTS` is unset (or set to the system bundle)
- Any app linked against OpenSSL's default cert dir (`/etc/ssl/certs/`) trusts the CA

**Trigger via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/environments/<id>/provision \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{
  "environment_id": "<uuid>",
  "job_id": "<uuid>",
  "status": "provisioning",
  "certs_issued": 5
}
```

**Check provisioning status:**
```bash
curl http://127.0.0.1:8000/api/v1/build/environments/<id>/provision-status \
  -H "Authorization: Bearer <token>"
```

Returns the count of active/revoked certs and details per host role.

**File layout on each provisioned host (Debian/Ubuntu):**

| Path | Contents |
|------|----------|
| `/usr/local/share/ca-certificates/internal/internal-ca.crt` | CA chain PEM (input to `update-ca-certificates`) |
| `/etc/ssl/certs/ca-certificates.crt` | System CA bundle (auto-generated, includes internal CA) |
| `/etc/ssl/certs/server.pem` | Server certificate |
| `/etc/ssl/private/server-key.pem` | Server private key (mode 0600) |
| `/etc/ssl/certs/server-fullchain.pem` | Server cert + CA chain |
| `/etc/pki/java/truststore.jks` | Java TrustStore (CA chain) |
| `/etc/pki/java/keystore.jks` | Java KeyStore (server cert + key) |

**Idempotency:** The base role is safe to re-run. Certificates are re-issued on each provision (old ones remain valid until environment destroy revokes them).

**Ansible role:** `base` (located at `/opt/certmanager/playbooks/roles/base/`)

---

## 5. Inventory

The inventory system manages the hosts that Build Manager deploys to. Hosts can be physical VMs, cloud instances, or Docker containers (for development). The inventory also manages host groups for Ansible targeting and network pools for IP allocation.

### Hosts

A host represents a single target machine. Ansible connects to it either via SSH (real VMs, cloud instances) or via Docker container name (dev containers on the same Docker network).

**Host properties:**

| Field | Description |
|-------|-------------|
| Hostname | Unique name used as the Ansible inventory hostname (e.g. `target-frontend`) |
| Connection Type | `docker` � connect via container name; `ssh` � connect via IP address |
| Container Name | Docker container name (Docker hosts only � used for Ansible connectivity and DNS) |
| IP Address | Network address � used for certificate SANs and documentation; Ansible uses container name for Docker hosts |
| SSH Port | Default: 22 |
| SSH User | User for Ansible connections (default: `root`) |
| OS Type | `ubuntu`, `debian`, `rhel`, `centos`, `almalinux`, `rocky`, `alpine` |
| OS Version | e.g. `24.04`, `8`, `3.19` |
| Service Role | Primary function: `frontend`, `backend`, `mysql`, `rabbitmq`, `keystone`, `generic` |
| Tags | Free-form comma-separated labels for filtering |
| Groups | Host group memberships (assigned at creation or edit time) |
| Status | `unknown`, `online`, `offline` � updated by the SSH connectivity test |

### Adding a Host

**Via UI:**
1. Navigate to **Build Manager ? Inventory ? Hosts** tab
2. Click **+ Add Host** � the form expands inline
3. Fill in the fields:
   - **Hostname** � unique name (required)
   - **Connection Type** � select `Docker Container` or `SSH (Real Host/VM)`
   - **Container Name** � shown for Docker hosts; the Docker container name Ansible connects to
   - **IP Address** � select from a network pool or enter manually (required)
   - **Port**, **SSH User**, **OS Type**, **OS Version**, **Service Role**, **Tags**
   - **Groups** � tick any group checkboxes to assign membership
4. Click **Save**
5. Click **?? Test** to verify SSH connectivity

**Validation errors** are shown inline above the form. Pydantic validation errors include the field name � e.g. `ip: String should have at least 1 character` means the IP field was left blank.

**Via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/hosts \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "hostname": "target-frontend",
    "ip": "172.20.0.10",
    "connection_type": "docker",
    "container_name": "target-frontend",
    "port": 22,
    "ssh_user": "root",
    "os_type": "ubuntu",
    "os_version": "24.04",
    "service_role": "frontend",
    "tags": "dev,nginx",
    "group_ids": []
  }'
```

**Supported `os_type` values:** `ubuntu`, `debian`, `rhel`, `centos`, `almalinux`, `rocky`, `alpine`

### Host Connection Types

| Type | Icon | Ansible Connects Via | Use Case |
|------|------|---------------------|----------|
| `docker` | ?? | Container name (Docker DNS) | Dev containers on the same Docker network |
| `ssh` | ??? | IP address | Production VMs, cloud instances, remote hosts |

For Docker hosts, the `container_name` field is what Ansible uses for the actual connection. The IP is still recorded for certificate SANs and documentation. The API returns a computed `ansible_host` field: container name for Docker hosts, IP for SSH hosts.

### SSH Connectivity Test

Tests that the certmanager container can reach the host via SSH.

**Via UI:** Click the **?? Test** button next to any host. Shows green (success + latency) or red (failure + error message).

**Via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/hosts/<host-id>/test \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{
  "success": true,
  "latency_ms": 215,
  "message": "SSH connection successful"
}
```

**Common failures:**

| Error | Cause | Fix |
|-------|-------|-----|
| Connection refused | sshd not running on target | Check target container is up: `docker ps` |
| Permission denied | SSH key not authorised | Verify key in `/root/.ssh/authorized_keys` on target |
| Timeout | Network issue or wrong IP/hostname | Verify host IP/container name, check Docker network |
| Host key verification failed | Known hosts mismatch | See Host-Key Verification below � `host_key_checking` in `/data/ansible.cfg` is unrelated to this; Build Manager enforces its own per-host pinning independently |

### Host-Key Verification (TOFU Pinning)

Ansible's own `ansible.cfg` `host_key_checking` setting defaults off (`False`) � every SSH connection this app makes, including the actual Ansible job run, would otherwise trust whatever host key the target currently presents, which protects *authentication* (via per-host SSH credentials) but not against a MITM substituting the target entirely.

Build Manager pins each registered SSH-type host's real host key independently of that setting, using trust-on-first-use (TOFU):

- The first time a host is successfully reached � via **Test Connection**, a **pre-flight check**, or a job run against an environment that references it � its Ed25519 host key is recorded on the `BMHost` row.
- Every subsequent connection compares the currently-presented key against the pinned one. A match proceeds normally. A mismatch **blocks** the connection (test/preflight fails; a job referencing that host fails immediately, before Ansible even starts) with a message naming the host and when it was originally pinned.
- Enforcement covers both the connection-test/preflight path and the real Ansible run: a per-job `known_hosts` file is built from each in-scope host's pinned key and passed to `ansible-playbook` via `--ssh-common-args="-o UserKnownHostsFile=... -o StrictHostKeyChecking=yes"`, so a pinned host is genuinely protected during the actual playbook execution, not just when clicking "Test".
- **Docker-hosted hosts are never pinned or enforced** � their containers are recreated fresh on every build, so there's no stable identity to pin against; this only applies to `connection_type: ssh` hosts.
- **Ad-hoc jobs with no `environment_id`** skip enforcement entirely � there's no way to know which registered hosts are in scope without an environment to resolve them from.

**A host key legitimately changes** on OS reinstall or hardware replacement. When that happens, confirm the change is expected out-of-band, then re-accept it:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/hosts/<host-id>/accept-host-key \
  -H "Authorization: Bearer <token>"
```

Admin-only � this overrides a security block, so it's audited (`BM_HOST_KEY_ACCEPTED`, `WARNING` severity). Via the UI, a "? Accept New Key" button appears on the host test-result banner whenever a test fails specifically because the key changed (as opposed to the host simply being unreachable).

### Host Groups

Groups are logical collections of hosts used for targeting Ansible playbooks at a subset of hosts and applying shared variables.

**Creating a group:**
1. Navigate to **Build Manager ? Inventory ? Groups** tab
2. Click **+ Add Group**, enter name and description
3. Click **Save**
4. Assign hosts to the group when adding or editing hosts

**Auto-generated groups:** The inventory system automatically creates groups based on service role (e.g. `role_frontend`, `role_mysql`). These appear in the Ansible inventory export.

**Via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/groups \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "web-tier", "description": "All web-facing hosts"}'
```

### Host Variables

Key-value pairs attached to a host, passed to Ansible as host vars at playbook runtime.

```bash
# Set a plain variable
curl -X POST http://127.0.0.1:8000/api/v1/build/hosts/<host-id>/vars \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"key": "mysql_port", "value": "3306", "encrypted": false}'

# Set an encrypted variable (passwords, secrets)
curl -X POST http://127.0.0.1:8000/api/v1/build/hosts/<host-id>/vars \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"key": "mysql_root_password", "value": "s3cret", "encrypted": true}'
```

Encrypted variables are stored with AES-256-GCM and only decrypted at playbook runtime.

### Ansible Inventory Export

Build Manager generates Ansible-compatible dynamic inventory JSON used internally by the job engine and available for manual Ansible runs.

```bash
curl http://127.0.0.1:8000/api/v1/build/inventory \
  -H "Authorization: Bearer <token>"
```

**Response format:**
```json
{
  "_meta": {
    "hostvars": {
      "target-frontend": {
        "ansible_host": "target-frontend",
        "ansible_port": 22,
        "ansible_user": "root",
        "os_type": "ubuntu",
        "os_version": "24.04",
        "service_role": "frontend"
      }
    }
  },
  "all": {
    "hosts": ["target-frontend", "target-backend", "target-mysql"]
  },
  "role_frontend": { "hosts": ["target-frontend"] },
  "role_backend":  { "hosts": ["target-backend"] },
  "role_mysql":    { "hosts": ["target-mysql"] }
}
```

### SSH Key Management

Build Manager uses Ed25519 SSH keys for Ansible connectivity.

- **Key location:** `/data/ssh/id_ed25519` (private), `/data/ssh/id_ed25519.pub` (public)
- **Generated:** Automatically on first container start
- **Distribution:** Shared to target containers via Docker volume (dev) or manual deployment (production)
- **Retrieve public key:** `GET /api/v1/build/ssh-key`

**For production VMs:**
```bash
# Get the public key
curl http://127.0.0.1:8000/api/v1/build/ssh-key \
  -H "Authorization: Bearer <token>"

# Add to target host
ssh target-host "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys" < id_ed25519.pub
```

### Network Pools

Network Pools define IP address ranges for host allocation. They track reserved IPs (gateway, infrastructure) and allocated IPs (assigned to hosts) to show which addresses are available.

The **Network Pools** tab has three modes for creating a pool:

#### Manual

Fill in all fields directly:

1. Navigate to **Build Manager ? Inventory ? Network Pools** tab
2. Click **+ Add Pool**, select **Manual**
3. Fill in: name, CIDR (e.g. `172.20.0.0/16`), gateway, DNS servers, reserved IPs, description
4. Click **Save**

#### From Docker Network (existing)

Discover and import an existing Docker network:

1. Select **From Docker Network** mode � existing Docker networks appear as clickable cards showing name, CIDR, gateway, and container allocation count
2. Click a network card � the form pre-fills with name, CIDR, gateway, DNS (= gateway), reserved IPs (gateway + all currently allocated container IPs), and description
3. Edit any pre-filled values if needed
4. Click **Save**

#### From Docker Network (create new)

Create a brand-new Docker bridge network and import it as a pool in one step:

1. Select **From Docker Network** mode
2. Click the dashed **+ Create new network** tile
3. Enter a **network name** (e.g. `certmanager-net`) � required
4. Optionally enter a **subnet** (e.g. `172.20.0.0/16`) � leave blank to let Docker pick a free range automatically
5. Click **Create**

Docker automatically assigns:
- A gateway (first usable IP in the subnet, e.g. `172.20.0.1`)
- NAT/internet routing via the host's iptables (`ip_masquerade=true`)
- Embedded DNS resolver (`127.0.0.11`) for container name resolution

After creation, the new network appears as a selected card and the pool form pre-fills with the real gateway and subnet Docker assigned. Click **Save** to register it as a pool.

**When to use:** Use this when you need a fresh isolated network for a new environment. Docker bridge networks provide full internet access for target containers (package downloads, external API calls) without any manual routing configuration.

**How Docker network discovery works:**

The endpoint `GET /api/v1/build/network-pools/docker-networks` queries the Docker Engine API via the Unix socket (`/var/run/docker.sock`) mounted into the certmanager container. The create endpoint (`POST /api/v1/build/network-pools/docker-networks`) calls the same socket to create the network and returns the auto-assigned CIDR and gateway.

**Requirements:**
- The Docker socket must be mounted into the certmanager container:
  ```yaml
  volumes:
    - certmanager-data:/data
    - /var/run/docker.sock:/var/run/docker.sock:ro
  ```
- No Docker CLI installation is needed inside the container � `httpx` with a Unix socket transport is used directly

**If "No Docker networks found" appears:**
- Verify the socket is mounted: `docker exec ssl-cert-manager ls -la /var/run/docker.sock`
- Recreate the container after adding the volume mount: `docker compose up -d` (restart alone won't pick up volume changes)
- On Windows with Docker Desktop, `/var/run/docker.sock` is automatically provided to Linux containers

#### Picking IPs from a Pool

When adding a host, select **From Pool** in the IP field. This calls `GET /api/v1/build/network-pools/{id}/available` which returns the next N available IPs (excluding network/broadcast, gateway, reserved, and already-allocated IPs).

**Via API:**
```bash
# List pools
curl http://127.0.0.1:8000/api/v1/build/network-pools \
  -H "Authorization: Bearer <token>"

# Discover existing Docker networks
curl http://127.0.0.1:8000/api/v1/build/network-pools/docker-networks \
  -H "Authorization: Bearer <token>"

# Create a new Docker network
curl -X POST http://127.0.0.1:8000/api/v1/build/network-pools/docker-networks \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "certmanager-net", "subnet": "172.20.0.0/16"}'

# Create pool manually
curl -X POST http://127.0.0.1:8000/api/v1/build/network-pools \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "bm-net",
    "cidr": "172.18.0.0/16",
    "gateway": "172.18.0.1",
    "dns_servers": "172.18.0.1",
    "reserved": ["172.18.0.1", "172.18.0.2"],
    "description": "Docker bridge network"
  }'

# Get available IPs
curl "http://127.0.0.1:8000/api/v1/build/network-pools/<pool-id>/available?count=10" \
  -H "Authorization: Bearer <token>"
```

**Response from `/available`:**
```json
{
  "pool_id": "<uuid>",
  "pool_name": "bm-net",
  "cidr": "172.18.0.0/16",
  "gateway": "172.18.0.1",
  "total_hosts": 65534,
  "reserved_count": 2,
  "allocated_count": 5,
  "available": ["172.18.0.10", "172.18.0.11", "172.18.0.12"]
}
```

### Creating a Plain Host (Step-by-Step)

A "plain host" is a bare OS target with no products assigned � useful for experimentation, manual testing, or hosts that will have products added later.

#### Prerequisites

- Docker socket mounted in certmanager container
- At least one CA created in SSL Cert Manager (the build issues a server certificate)
- An unconstrained CA recommended (to allow `localhost`/`127.0.0.1` SANs)

#### Step 1: Create the Inventory Host

**Via UI:**

1. Navigate to **Build Manager ? Inventory ? Hosts** tab
2. Click **+ Add Host**
3. Fill in the form:

| Field | Value | Notes |
|-------|-------|-------|
| Hostname | `test` | Unique name � becomes the Ansible inventory hostname |
| Connection Type | `Docker Container` | For dev containers |
| Container Name | `test` | Must be unique across all Docker containers |
| IP Address | *(pick from pool or enter manually)* | Used for cert SANs only |
| SSH Port | `22` | Default |
| SSH User | `root` | Default for target containers |
| OS Type | `ubuntu` | Matches the target container image |
| OS Version | `24.04` | Matches the target container image |
| Service Role | `generic` | Or any descriptive role |

4. Click **Save**

**Via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/hosts \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "hostname": "test",
    "ip": "172.20.0.10",
    "port": 22,
    "ssh_user": "root",
    "os_type": "ubuntu",
    "os_version": "24.04",
    "service_role": "generic",
    "connection_type": "docker",
    "container_name": "test"
  }'
```

#### Step 2: Create a Template Using the Host

**Via UI:**

1. Navigate to **Build Manager ? Template Builder**
2. **Step 1** � Enter template name (e.g. `plain-test`), select base OS `ubuntu 24.04`
3. **Step 2** � Click **From Inventory** and select the `test` host
4. **Step 3** � Skip product selection (plain host has no products)
5. **Step 4** � Review and save

**Via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/templates \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "plain-test",
    "description": "Plain host for testing",
    "spec": {
      "base_os": "ubuntu",
      "base_os_version": "24.04",
      "hosts": [
        {
          "role": "test",
          "inventory_host_id": "<host-uuid>",
          "products": [],
          "certs": ["server_tls"]
        }
      ],
      "network": {},
      "certificates": {
        "key_algorithm": "RSA",
        "key_size": 2048,
        "validity_days": 365,
        "san_include_localhost": true
      }
    }
  }'
```

#### Step 3: Create an Environment

1. Navigate to **Build Manager ? Environments**
2. Click **Create Environment**
3. Select the `plain-test` template
4. Enter environment name (e.g. `test`)
5. Select a **Signing CA** (pick one marked ? Recommended)
6. Click **Create**

#### Step 4: Build the Environment

1. On the Environments page, find the `test` environment (status: `pending`)
2. Click **Build**

**What happens automatically:**

1. **Container creation** � detects `connection_type=docker`, creates a Docker container named `test` using the target image (Ubuntu 24.04 + systemd + SSH), attached to the `bm-net` network
2. **SSH key injection** � container entrypoint copies the SSH public key from the shared volume to `/root/.ssh/authorized_keys`
3. **Certificate issuance** � server certificate issued (CN: `test.<domain>`, SANs include `localhost`, `127.0.0.1`)
4. **Base provisioning** � Ansible runs the `base` role: Java 17, CA trust, PEM certs, Java TrustStore/KeyStore
5. **Status update** � environment transitions to `active`

#### Step 5: Verify

```bash
# Verify the container exists
docker ps --filter name=test

# SSH into it from certmanager
docker exec ssl-cert-manager ssh -o StrictHostKeyChecking=no -i /data/ssh/id_ed25519 root@test hostname

# Verify CA is trusted
docker exec test openssl x509 -in /etc/ssl/certs/server.pem -noout -subject -dates
```

#### Step 6: Destroy (When Done)

1. On the Environments page, click **Destroy** on the `test` environment

**What happens:** Certificates revoked, environment record deleted, `test` Docker container stopped and removed. The inventory host record remains for future rebuilds.

#### Important Notes

- **Container naming:** Container name must be unique across all Docker containers. Avoid names that conflict with existing containers (`target-frontend`, etc.)
- **Protected containers:** The 5 pre-defined target containers and `ssl-cert-manager` are protected � destroy will never remove them
- **Rebuild:** Each rebuild re-creates the container (if missing) and re-provisions from scratch
- **SSH test timing:** The Test button will fail if the container hasn't been created yet (only created at build time) � this is expected
- **Network:** Dynamically-created containers join the same Docker network as the pre-defined targets and can communicate via container name DNS

### Dev vs Production Inventory

| Aspect | Dev (Docker) | Production (VMs) |
|--------|-------------|-------------------|
| Host address | Container hostname (e.g. `target-frontend`) | Real IP or FQDN |
| SSH key distribution | Shared Docker volume | Manual or automated key push |
| Network | Docker bridge (`bm-net`) | Physical/virtual network |
| OS | Ubuntu 24.04 container (systemd, privileged) | Ubuntu 24.04+ or RHEL 8+ VM |
| Init system | systemd (PID 1) | systemd (PID 1) |
| Playbooks | Identical | Identical |
| Inventory | Same format | Same format, different values |

The only difference between dev and production is the inventory values. Playbooks, roles, and workflows are identical.

### Docker Port Exposure

In Docker dev mode, target container services are accessible from the host via port mappings in `docker-compose.build-manager.yml`:

| Container | Exposed Ports | Access URL |
|-----------|--------------|------------|
| target-frontend | 8080?80, 8443?443 | `https://localhost:8443` |
| target-backend | 8001?8000 | `https://localhost:8001` |
| target-mysql | 3306?3306 | `mysql -h 127.0.0.1 -P 3306 --ssl-mode=REQUIRED` |
| target-rabbitmq | 5671?5671, 15671?15671 | `https://localhost:15671` (management UI) |
| target-keystone | 5000?5000 | `https://localhost:5000` |

The table above covers the small set of fixed `docker-compose.build-manager.yml` fixture containers only. Environments actually built through the Build Manager (any template's hosts, e.g. the golden-path Full Stack template) use a separate, template-driven mechanism instead � see below.

**Template-driven port exposure (`expose_ports`).** Any host entry in a template's spec can carry an optional `"expose_ports": [<port>, ...]` list � an explicit set of container ports published 1:1 to the identical host port, so a real browser on the Docker host machine can reach that host directly (not just other containers on `docker_bm-net`). This is baked into the template spec itself, so it's a genuine per-template *default* � no manual step is needed at environment-creation time. The golden-path Full Stack template uses this for exactly two hosts:

| Host role | `expose_ports` | Why |
|-----------|-----------------|-----|
| `frontend-lb` | `[443]` | Client-facing tier � a real browser needs to reach it directly |
| `rabbitmq` | `[15671]` | TLS management UI � needs to be reachable outside the Docker network |
| `backend-lb` | *(none)* | Only ever addressed by `frontend-lb` inside the Docker network � but see the opt-in mechanism below if some other environment needs it exposed too |

**Per-environment opt-in.** Any role not covered by a template default can still be exposed for one specific environment via the "Expose Ports" checkbox shown per role on the environment-creation screen (gated on the platform being Docker-hosted) � this expands to that role's product(s) `default_ports` (minus port 80, see below) for that one environment only, without changing the template itself.

**Port 80 (and 8000) are permanently reserved.** The `ssl-cert-manager` container itself is always started with `-p 80:80 -p 8000:8000` � no other host container can ever publish either port. `validate_spec()` rejects `expose_ports: [80]` (or `8000`) outright with a clear error rather than letting it fail later with an opaque Docker "port already allocated" message; the per-environment opt-in checkbox silently excludes port 80 from whatever it offers, for the same reason.

**A real incident found during live verification of this feature:** the first live test of `rabbitmq`'s `expose_ports: [15671]` failed at container start with `port is already allocated` � not because of a bug in the new mechanism (the container's `HostConfig.PortBindings` genuinely did request `15671/tcp`), but because this lab's pre-existing `target-rabbitmq` fixture container (see the table above) was already permanently holding host port 15671. This is specific to this one dev box's leftover fixture containers, not a real deployment concern � a fresh Docker host (a teammate's machine, CI, or any real on-prem/AWS box) wouldn't have this collision. If you hit `port is already allocated` on a fresh build, check `docker ps -a --format '{{.Names}}\t{{.Ports}}'` for whatever else already holds that port before assuming the feature is broken.

### CA Selection for Environments

When creating an environment, the UI includes a **Signing CA** dropdown with suitability scoring:

- **? Recommended** � Unconstrained intermediate CAs (can sign for any name including `localhost`)
- **? Constrained** � CAs with Name Constraints that restrict permitted SANs

**Why this matters:** If a CA has Name Constraints (e.g. only permits `.alpha.internal`), certificates issued for `localhost` or `127.0.0.1` will be rejected by browsers. The Docker dev workflow requires localhost SANs, so an unconstrained CA must be used.

**API endpoint:** `GET /api/v1/build/signing-cas` returns all CAs with `can_sign_any`, `name_constraints`, `score`, and `recommended` fields.

## 6. Job Engine

The job engine executes Ansible playbooks asynchronously and captures all output for review.

### Job Properties

| Field | Description |
|-------|-------------|
| Name | Readable job name |
| Job Type | `playbook`, `adhoc`, `build`, `destroy` |
| Status | `pending`, `running`, `success`, `failed`, `cancelled` |
| Playbook | Path to the playbook file (relative to `/data/playbooks/`) |
| Environment ID | Optional � links job to an environment |
| Extra Vars | JSON object passed as `--extra-vars` to Ansible |
| Exit Code | Process exit code (0 = success) |
| Started At | Timestamp when execution began |
| Finished At | Timestamp when execution completed |
| Dry Run | If true, executed with `--check --diff` instead of applying changes |
| Failed Hosts | Hosts that reported `fatal:` during the run � used by Retry to re-target just those hosts |

### Submitting a Job

**Via UI:**
1. Navigate to **Build Manager ? Jobs**
2. Fill in the submit form (name, playbook path, optional extra vars JSON)
3. Click **Submit Job**

**Via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/jobs \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Base provisioning - dev-01",
    "playbook": "base-provision.yml",
    "extra_vars": {"target_group": "all"},
    "environment_id": "<env-uuid>"
  }'
```

### Job Execution

When a job is submitted:
1. A `BMJob` record is created with status `pending`
2. The async executor picks it up and transitions to `running`
3. Ansible is invoked as a subprocess: `ansible-playbook -i <inventory> <playbook> --extra-vars '{...}'`
4. stdout and stderr are captured line-by-line into `BMJobLog` records
5. On completion, exit code is recorded and status becomes `completed` or `failed`

### Viewing Job Output

The output viewer shows real-time Ansible output in a terminal-style dark panel.

**Via UI:** Click any job in the jobs table to see its output. Running jobs poll every 3 seconds for new lines.

**Via API:**
```bash
curl http://127.0.0.1:8000/api/v1/build/jobs/<id>/output \
  -H "Authorization: Bearer <token>"
```

Returns an array of log lines with stream (`stdout`/`stderr`) and line number.

### Cancelling a Job

Running jobs can be cancelled:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/jobs/<id>/cancel \
  -H "Authorization: Bearer <token>"
```

This sends SIGTERM to the Ansible subprocess. If the process doesn't exit within 10 seconds, SIGKILL is sent. Status becomes `cancelled`.

### Concurrency & Timeout

- Jobs run one at a time per environment (prevents conflicting deployments)
- Multiple jobs for different environments can run concurrently
- Default timeout: 30 minutes (configurable per job)
- Timed-out jobs are killed and marked `failed`

### Job Cleanup

Completed/failed/cancelled jobs can be deleted to reduce clutter:

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/build/jobs/<id> \
  -H "Authorization: Bearer <token>"
```

This removes the job record and all associated log lines. Running jobs cannot be deleted � cancel first.

### Filing a Bug from a Job

Improvements Plan Stages 19-20. Every job's terminal-style output panel has a "Report Bug" button (top-right, next to the log-line count) and, once any bugs exist for it, a "N bugs" badge linking to a pre-filtered list - the same pattern JAR Analyser's own report view already uses for exactly the same reason: filing a bug shouldn't mean losing the context of what you were just looking at.

Clicking Report Bug cross-navigates to Docs -> Bugs with the job pre-filled as the new bug's origin (shown as a fixed "Filed against Build Manager job #..." line rather than the usual report/service picker - a bug is linked to a report or a job, never both). The form also pre-fills a full set of context fields, all fully editable before saving:

- Title, Actual Behaviour, and Ansible Output from the job itself - playbook, failed hosts, exit code, and the actual `fatal:`/`FAILED!` lines from the run. A known exit code also gets a short "(commonly: ...)" hint next to it (e.g. exit code 4 usually means an unreachable host on current Ansible versions, though older Ansible docs call it a parser error) - a rough pointer to check first, not a diagnosis, since ansible-playbook's own exit codes are inconsistently documented and some (notably 2 and 4) mean different things across versions.
- If the job belongs to an environment: OS/distro + version (Environment section), the product/service versions on every host (App version / commit), the assigned IP addresses (Network path), and any certificates already issued for it (TLS / cert details). Relevant config gets a per-host role -> product breakdown plus the environment and template name/version.

A job that never reached an environment (or one that was destroyed before the report was filed) simply leaves those fields blank rather than guessing - only the job's own failure details are guaranteed. See the Bug Tracker section of `docs_operations_guide.md` for the full intake form and everything else Bug Tracker can do with it (assignment, attachments, status workflow).

### Related Bugs (Automated Scan)

Improvements Plan Stage 21. Once a job finishes `failed` (and isn't about to be auto-retried - a transient blip that's about to succeed on its own isn't a real failure yet), it's automatically scanned against every open bug in the tracker, using its own `fatal:`/`FAILED!` output lines, failed hosts, and playbook name as the search text - the same scoring engine Bug Tracker's own duplicate-suggestion assist and JAR Analyser's related-report scan already use. Anything that looks related shows up as an amber "Related Bugs" strip in the job's terminal view, above the log output - click one to jump straight to it.

This is a "worth checking" signal, not a confirmed match: matching is deliberately loose (any shared word counts), so it can surface false positives on generic failure text as well as genuine repeat issues. Runs best-effort - a scan failure is logged and never blocks the job from finishing. A job that succeeded, is still running, or is about to auto-retry has nothing to scan for and shows no panel; a job that failed before this feature existed simply has no result until it's re-run.

### Automatic Bug Filing (Opt-in)

Improvements Plan Stage 22. Off by default - an admin turns it on from Settings ("Automatic Bug Filing"). When enabled, it goes one step further than the scan above: if a failed job's scan finds nothing close enough, a new bug is filed automatically instead of waiting for someone to notice it in the log. If the scan does find a match, that counts as a recurrence, not a new problem - a note is added to the existing bug instead of filing a duplicate, so a flaky failure that keeps happening does not spawn a fresh bug every single run.

Auto-filed bugs are reported by "Automated (Ansible failure scan)", never a real user, and are marked with an auto-filed flag so they are never confused with something a person filed by hand - Bug Tracker shows this as a small badge on the bug. The bug's description is built from the job's playbook, failed hosts, and exit code (with the same "(commonly: ...)" exit-code hint the manual Report Bug form shows) - it is a starting point, not a root-cause analysis, since today's failure data is just hostnames and an exit code parsed out of the raw output. The first time a brand-new kind of failure shows up, someone will likely still need to open the job log to see what actually broke - this is meant to stop failures going unnoticed, not to replace reading the log.

### Error KB Guidance

Both the manual Report Bug form and auto-filed bugs also get real, curated troubleshooting guidance (not just the coarse exit-code hint above) by matching the job's own failure text against the same Error Knowledge Base used elsewhere in Docs and JAR Analyser - see "Ansible / Build Manager integration" in the Error Knowledge Base section of `docs_operations_guide.md` for how it works and, importantly, how to add and maintain entries for new Ansible failure types as they come up. Nothing here needs the app rebuilt to update - a new KB entry is picked up immediately.

### Job Status Polling

The UI polls the job list every 5 seconds when any job is in `pending` or `running` state. Individual job output polls every 3 seconds while the job is running. Polling stops automatically when all jobs reach a terminal state.

### Dry Run (Check Mode)

Both ad-hoc job submission and environment builds accept a `dry_run` flag. When set, Ansible is invoked with `--check --diff` instead of actually applying changes to the targets:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/jobs \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Preview base provisioning", "playbook": "base-provision.yml", "dry_run": true}'

curl -X POST "http://127.0.0.1:8000/api/v1/build/environments/<env-uuid>/build?dry_run=true" \
  -H "Authorization: Bearer <token>"
```

A dry-run job's `dry_run` field is persisted on the job record so it's never mistaken for a real run in job history. Building an environment with `dry_run=true` does not move the environment out of its current lifecycle status (it stays wherever it was, rather than transitioning through `provisioning`/`active`) � nothing was actually applied, so its status shouldn't change either. Retrying a job preserves its original `dry_run` value.

**Known limitation:** Ansible's check mode is a best-effort simulation, not a guarantee. `command`, `shell`, and other non-idempotent modules frequently report inaccurately � or skip reporting changes at all � under `--check`, since they have no built-in concept of "what would happen." Treat dry-run output as a helpful preview for modules that support check mode properly (most built-in modules), not as an authoritative diff for raw command/shell tasks. This is a documented limitation, not something the Build Manager detects or warns about per-task.

---

## 7. Product Catalogue & Template Builder

The Product Catalogue is a registry of all deployable software products with version metadata, OS compatibility, dependency rules, and conflict detection. The Template Builder is a guided wizard that turns product selections into validated templates.

### Product Catalogue

The catalogue ships with 9 built-in products:

| Product | Category | Default Ports | Cert Requirements |
|---------|----------|---------------|-------------------|
| Nginx | web-server | 80, 443 | Server TLS |
| FastAPI | application | 8000 | Server TLS, Client mTLS |
| MySQL | database | 3306 | Server TLS |
| RabbitMQ | messaging | 5671, 5672, 15672 | Server TLS |
| Keystone | identity | 5000 | Server TLS |
| Redis | cache | 6379 | Server TLS |
| PostgreSQL | database | 5432 | Server TLS |
| Keycloak | identity | 8443 | Server TLS |
| HAProxy | load-balancer | 443, 8404 | Server TLS |

**Product properties:**

| Field | Description |
|-------|-------------|
| Name | Machine identifier (e.g. `nginx`, `mysql`) |
| Display Name | Readable name (e.g. `Nginx`, `MySQL Server`) |
| Category | Grouping: `web-server`, `application`, `database`, `messaging`, `identity`, `cache`, `load-balancer` |
| Icon | Emoji icon for UI display |
| Default Ports | Ports the product listens on |
| Cert Requirements | What certificate types the product needs (`server_tls`, `client_mtls`) |
| Dependencies | Other products required (e.g. FastAPI depends on Python runtime) |
| Is Built-in | Whether the product was seeded (cannot be deleted) |

### Product Versions

Each product has one or more versions with deployment metadata:

| Field | Description |
|-------|-------------|
| Version | Semver string (e.g. `8.0.40`, `3.13.7`) |
| Ansible Role | The Ansible role name used for installation |
| Default Vars | Default Ansible variables for this version |
| Supported OS | List of compatible OS/version combinations |
| Conflicts With | Products/versions that cannot coexist on the same host |
| Requires | Products/versions that must be present |
| Release Date | When this version was released |
| EOL Date | End-of-life date (triggers advisory warnings) |
| Is Latest | Whether this is the recommended version |

**Example version entry (MySQL 8.0.40):**
```json
{
  "version": "8.0.40",
  "ansible_role": "mysql",
  "default_vars": {
    "mysql_bind_address": "0.0.0.0",
    "mysql_port": 3306,
    "mysql_tls_enabled": true
  },
  "supported_os": [
    {"os": "ubuntu", "versions": ["22.04", "24.04"]},
    {"os": "rhel", "versions": ["8", "9"]}
  ],
  "conflicts_with": [
    {"product": "postgresql", "reason": "Port conflict on default ports"}
  ],
  "is_latest": true
}
```

### Compatibility Checker

Before building a template, the compatibility checker validates product selections against:

1. **OS compatibility** � hard error if a product version doesn't support the selected OS
2. **Conflicts** � advisory warning if two products on the same host conflict
3. **EOL status** � advisory warning if a version is past its end-of-life date
4. **Dependencies** � advisory warning if a required dependency is missing

**Via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/catalogue/check-compatibility \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "base_os": "ubuntu",
    "base_os_version": "24.04",
    "selections": [
      {"product_id": "<uuid>", "version_id": "<uuid>"},
      {"product_id": "<uuid>", "version_id": "<uuid>"}
    ]
  }'
```

**Response:**
```json
{
  "compatible": true,
  "errors": [],
  "warnings": [
    {
      "type": "eol",
      "product": "MySQL",
      "version": "5.7.44",
      "message": "Version 5.7.44 reached end-of-life on 2023-10-31"
    }
  ]
}
```

Only OS incompatibility produces a hard error (`compatible: false`). Conflicts and EOL are advisory warnings � the user can proceed.

### Template Builder Wizard

The Template Builder is a multi-step UI wizard that guides users through creating a template from product selections:

**Step 1 � Base Configuration:**
- Template name and description
- Base OS and version (Ubuntu 22.04/24.04, RHEL 8/9)

**Step 2 � Host Roles:**
- Add host roles (e.g. `frontend`, `backend`, `database`)
- Assign products to each role from the catalogue
- Select specific versions for each product
- Configure per-product variables

**Step 3 � Network:**
- Subnet (e.g. `192.168.50.0/24`)
- IP range start and end
- Or skip for Docker dev mode

**Step 4 � Certificates:**
- CA selection (auto-detects available CAs)
- Key algorithm and size
- Validity period
- SAN options (include localhost, include IP)

**Step 5 � Review & Save:**
- Full spec preview (JSON)
- Compatibility check results
- Save as new template

**Via API (direct template creation from selections):**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/catalogue/build-template \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "base_os": "ubuntu",
    "base_os_version": "24.04",
    "hosts": [
      {
        "role": "frontend",
        "products": [{"version_id": "<uuid>", "vars": {}}]
      },
      {
        "role": "database",
        "products": [{"version_id": "<uuid>", "vars": {"mysql_port": 3307}}]
      }
    ],
    "network": {"subnet": "192.168.50.0/24", "range_start": "192.168.50.10", "range_end": "192.168.50.50"},
    "certificates": {"key_algorithm": "RSA", "key_size": 2048, "validity_days": 365},
    "template_name": "my-stack",
    "template_description": "Frontend + MySQL stack",
    "change_note": "Created via Template Builder"
  }'
```

The builder generates a full template spec from the selections, validates it, and saves it as a new template with version 1.

### Generated Template Spec

The Template Builder produces specs in this format:

```json
{
  "base_os": "ubuntu",
  "base_os_version": "24.04",
  "hosts": [
    {
      "role": "frontend",
      "products": [
        {
          "product_name": "nginx",
          "version": "1.26.2",
          "ansible_role": "nginx",
          "vars": {}
        }
      ]
    },
    {
      "role": "database",
      "products": [
        {
          "product_name": "mysql",
          "version": "8.0.40",
          "ansible_role": "mysql",
          "vars": {"mysql_port": 3306}
        }
      ]
    }
  ],
  "network": {
    "subnet": "192.168.50.0/24",
    "range_start": "192.168.50.10",
    "range_end": "192.168.50.50"
  },
  "certificates": {
    "key_algorithm": "RSA",
    "key_size": 2048,
    "validity_days": 365
  }
}
```

### Seeding the Catalogue

The catalogue is seeded on first run with the 9 built-in products. Seeding is idempotent � subsequent calls return 0 products added.

**Via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/catalogue/seed \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{"products_added": 9}
```

### Managing Custom Products

Admins can add custom products beyond the built-in set:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/catalogue \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "elasticsearch",
    "display_name": "Elasticsearch",
    "category": "search",
    "description": "Distributed search and analytics engine",
    "icon": "??",
    "default_ports": [9200, 9300],
    "cert_requirements": {"server_tls": true, "client_mtls": true},
    "dependencies": []
  }'
```

Custom products can be deleted (if not referenced by any active deployment). Built-in products cannot be deleted.

### UI Pages

**Catalogue page** (`/bm-catalogue`):
- Grid view of all products grouped by category
- Click a product to view versions, compatibility info, and default vars
- Admin actions: add product, add version, edit, delete

**Template Builder page** (`/bm-builder`):
- Multi-step wizard form
- Live compatibility checking as products are selected
- JSON spec preview before save
- Saves directly to the Templates list

### NFS Shared Storage (Reference Template + Persistent Named-Volume Export)

The `nfs_server`/`nfs_client` catalogue products (and their Ansible roles) already existed for any host in any template � the gap this closes is **persistence**: a Docker-hosted target container's filesystem is ephemeral, so an NFS export directory living only inside the container would vanish the moment that container is recreated. The **"Reference: NFS Shared Storage Server"** builtin template (seeded like the other reference templates, see �7 above) pairs the existing `nfs_server` product with a persistent, named Docker volume.

**How it works:**
- The template's `nfs_server` host always exports the fixed container-internal path `/srv/nfs-export` with `no_root_squash` � meaning **any container's root user that mounts this export gets full read/write/delete access**, since `no_root_squash` makes the NFS server trust the client's root identity instead of mapping it to `nobody`. All Build-Manager Docker-hosted containers already share one Docker network (`bm-net`), so any other environment's container can already reach it.
- When creating an environment from this template, the **Environments page** shows a one-line "Storage Volume Name" field for that host � a named Docker volume, e.g. `nfs-shared-storage`. That volume is mounted straight into the container at `/srv/nfs-export`; Docker creates it automatically the first time that name is used.
- **This is what makes the data persist across destroying and rebuilding the NFS environment**: reuse the same volume name on a later rebuild and the same data is there � Docker only removes a named volume if it's explicitly deleted (`docker volume rm`), never as a side effect of removing/recreating the container that uses it.
- Leaving the field blank still works � the export just lives in the container's own ephemeral storage, exactly like every other product on this platform behaves by default. Persistence is opt-in, not forced.

**Why a named volume, not a raw host directory (confirmed by testing this template for real):** the first implementation offered a plain host-path bind mount instead. On Docker Desktop for Windows, host drives are shared into the Linux VM via the **9p** filesystem protocol � and the Linux kernel's NFS server categorically refuses to export a 9p-backed directory (`exportfs: ... does not support NFS export`, with **no** export option able to work around it, `fsid=` included). A Docker named volume lives on Docker's own managed disk instead (a real `ext4`/`xfs` filesystem inside the Docker host/VM), which exports correctly � confirmed directly with `exportfs -v` succeeding against a volume-backed directory where the same command failed against a 9p-backed host path. This also means: if you ever see this same "does not support NFS export" error elsewhere, the underlying export directory is very likely sitting on a filesystem type (9p, some overlay configurations, etc.) that kernel `nfsd` can't serve, and moving it onto a real block-backed volume is the fix, not an export-options tweak.

**Connecting another environment as a client:** add the existing **NFS Client** product to any host in any template (no code change needed � it's already in the catalogue) and fill in its `nfs_mounts` list:
- `src`: `<nfs-server role or hostname>:/srv/nfs-export` (e.g. `nfs-server:/srv/nfs-export` if both are in the same environment, or the NFS server environment's actual container hostname if cross-environment)
- `path`: wherever you want it mounted on the client, e.g. `/mnt/shared`
- `opts`: leave as the default `nolock,vers=3` (see below for why) unless you have a specific reason to change it

The NFS Client product's `nfs_mounts` list defaults to empty and isn't required to submit � adding the product to a host doesn't force a connection; it's genuinely optional per host.

**Mount options, confirmed by testing this end-to-end:** clients must mount with `vers=3` � the default NFS protocol negotiation (which tries NFSv4 first) fails against this server with `mount.nfs: ... No such file or directory`, because NFSv4 needs a properly configured pseudo-filesystem root to serve a single export cleanly, which this minimal single-purpose appliance doesn't set up (out of scope for "the only reason for this server is to serve one directory"). NFSv3, mounting the export directly, works reliably and was confirmed with a real cross-container test: a second container on `bm-net`, running as root, successfully created, read, and deleted a file on the export. `nolock` is included because `rpc.statd` isn't running in these minimal target containers, and NFS's remote-locking handshake would otherwise just print a warning and behave less predictably.

**Known limitation, stated plainly:** `nfs-kernel-server` running inside a privileged container depends on the underlying Docker host's kernel actually supporting `nfsd` � confirmed working on the Docker Desktop for Windows setup this was tested against (`nfs-server.service` starts and stays active), but this is still worth re-checking on any new deployment target. If `nfs-kernel-server` fails to start at all (as opposed to starting but failing to export, or a client failing to mount), check `journalctl`/`systemctl status nfs-kernel-server` inside the container for the underlying kernel-support error.

**Also used by the "Reference: Full Stack" template (as of its version 8):** that template's `pkg-cache` host runs `nfs_server` (exporting `/srv/nfs-export`, same fixed path as this standalone template) and seeds the apt package cache directly into it (`pkg_cache_seed_dir: /srv/nfs-export/apt`); each of the other 5 hosts runs `nfs_client` mounting that export at `/mnt/pkg-cache`, then `local_repo` pointed at that same path. This is deliberate, not incidental: this lab's 6 hosts all happen to be containers on one Docker engine, but real on-prem/AWS deployments are genuinely separate machines with no shared Docker daemon � so the golden path uses the same real NFS mechanism that'll actually be needed there, rather than a Docker-only shortcut that wouldn't carry over. See the incident writeup immediately below for why this was temporarily replaced with a Docker named volume, and why it was safe to bring back.

### Golden-Path Template Pitfalls: the `pkg_cache_seed` Live-libc6-Upgrade Incident

This is not the "Package Cache (Offline Provisioning)" platform feature described in �15 (`/bm-pkg-cache`, `pkg-cache-sync.yml`) � that's a separate, platform-wide Debian mirror cache. This section is about the **`pkg_cache_seed`/`local_repo` products** used inside a single environment (notably the **"Reference: Full Stack"** builtin template's `pkg-cache` host), which seed a per-environment apt cache for the other hosts in the *same* build to read from instead of the network. Recorded here specifically so the next golden-path template doesn't have to rediscover this the hard way.

**Symptom:** in the Full Stack template, the `pkg-cache` host's container would repeatedly restart mid-build (`docker inspect <container> --format '{{.RestartCount}}'` climbing into the single/double digits within a couple of minutes), while every other host in the exact same build stayed at `RestartCount=0`, always. Ansible would fail with an UNREACHABLE-class error against that one host. This reproduced on every attempt, across many unrelated changes to the template (NFS-based design, then a named-Docker-volume design as a workaround, then back to real NFS again once the actual cause was found � the role was even renamed from `nfs-server` to `pkg-cache` along the way) � it was never about the export mechanism.

**Resolution note:** at the time this was investigated, the NFS-based design was abandoned in favor of a Docker named volume, because the `nfs-server` host was the one crashing and it seemed reasonable to suspect `nfsd` itself. The root cause below (a live `libc6` upgrade) turned out to have nothing to do with NFS � it was `pkg_cache_seed`'s own "Install dpkg-dev" task. Once that was fixed (see "Fix applied" below), the standalone NFS reference template and the Full Stack template's `nfs_server` host were both re-verified live and found completely stable, and Full Stack was switched back to real NFS (version 8) � since real on-prem/AWS hosts will need it and the Docker-volume design was only ever a lab-specific stopgap.

**What this turned out *not* to be** (each ruled out with a live, reproduced test � worth reading before assuming a similar symptom is the same bug):
- **Not corporate network security software** (Zscaler/AppGate) interfering with the container network � disproved by moving the whole `bm-net` bridge to a 192.168.0.0/16 subnet AppGate never routes; identical failure persisted.
- **Not the NFS kernel server** � disproved by removing NFS entirely (a separate, valid fix in its own right � see the NFS section above) and still seeing the exact same single-host restart pattern with no `nfsd` involved at all.
- **Not insufficient container settle-time before Ansible connects** � an active SSH-port-readiness wait (`_wait_for_ssh_port_ready` in `container_manager.py`) was added so every container, not just the first one, gets a real readiness check before Ansible touches it. The crash still happened.
- **Not batch size or Ansible's `serial: 1` host order** � a single-host template running *only* `pkg_cache_seed`, entirely on its own, crashed exactly the same way. A single-host template running `mysql` (genuinely heavy `apt-get install mysql-server` work) did **not** crash. This was the pivotal test: it proved the bug tracked the specific product, not "being first" or "being alone."
- **Not the package list length** � a 14-package cache list and a 2-package cache list crashed identically. All of `pkg_cache_seed`'s tasks are gated on `pkg_cache_seed_packages | length > 0`, not on the count.
- **Not the shared Docker volume** � redirecting `pkg_cache_seed_dir` to a plain path on the container's own root filesystem (no shared-volume I/O at all) still crashed, at the same ~70�90s mark every time.
- **Not the role name** � running the same product under an unrelated role name (`test1`) crashed identically. It followed the *product*, not the label.
- **Not "any real Ansible connection to a fresh container"** � a host with zero products (pure SSH connect + `gather_facts`, nothing else) stayed perfectly stable.

**Root cause, confirmed by direct reproduction:** `pkg_cache_seed`'s "Install dpkg-dev" step (needed to build the apt `Packages` index) was the *only* task in the entire product catalogue whose dependency chain happens to pull in a live upgrade of **`libc6` (glibc)** from `noble-updates`:

```
$ apt-get -s install dpkg-dev | grep libc6
Inst libc6 [2.39-0ubuntu8.7] (2.39-0ubuntu8.8 Ubuntu:24.04/noble-updates ...)
```

```
$ apt-get -s install mysql-server | grep libc6
(nothing � mysql-server's dependency chain never touches libc6)
```

Upgrading glibc live, over an active SSH session, inside a privileged container running nested `systemd` as PID 1, is a well-known hazard: any process forked while `dpkg` is mid-unpack (systemd's own internals, the SSH session's own shell) can end up executing against a half-replaced C library. This was reproduced directly: SSH'd into an isolated test container (bypassing this app and Ansible entirely, to rule out any involvement from either) and ran the exact `dpkg --configure -a && apt-get update && apt-get install dpkg-dev` sequence by hand. The session died mid-transaction at `Setting up libc6:amd64`, and `RestartCount` incremented the instant it did. No other product in the catalogue happens to trigger a core-library upgrade this way, which is why `pkg_cache_seed` was the only role that ever hit it.

**Fix applied:**
1. `docker/Dockerfile.target` now runs `apt-get update && apt-get upgrade -y && apt-get install -y dpkg-dev` at **image build time**, before the container ever boots � so `libc6` and `dpkg-dev` are already current and present when Ansible connects, and the live-upgrade window never opens.
2. `playbooks/roles/pkg_cache_seed/tasks/main.yml`'s "Install dpkg-dev" task was removed entirely (redundant now, and removing it also drops the residual risk of a future `apt-get update` mid-role rediscovering some *other* core-library upgrade).
3. Verified live: the same 14-package `pkg_cache_seed` config that reliably crash-looped before now completes cleanly (`RestartCount` stays at `0` throughout, job status `success`), both as a solo single-host template and as the `pkg-cache` host inside the full 6-host Full Stack build.

**Guidance for the next golden-path template:** before adding any task that runs `apt-get install <package>` live against a target container (as opposed to baking it into `docker/Dockerfile.target`), check what it actually pulls in:

```bash
docker exec <any-target-container> apt-get -s install <package> | grep -iE "libc6|systemd|openssl|libssl"
```

If that shows an `Inst` line for `libc6`, `systemd`, or another foundational package the container's own PID 1/init/SSH stack actively depends on, don't install it live via Ansible � add it to `docker/Dockerfile.target`'s build-time `apt-get install` list instead, so it's already resolved before the container boots. This is the general form of the bug, not something specific to `dpkg-dev`: **any** product whose dependency chain happens to force a core-library upgrade live is at risk of the same crash, regardless of how much or how little else that product installs.

**A second, unrelated incident found while switching Full Stack back to real NFS: `nfs_client`'s "Mount NFS shares" task had never actually run before.** The `nfs_client` product/role existed in the catalogue and was documented, but no template had ever exercised its "Mount NFS shares" task through a real Ansible run before Full Stack's version 8 � earlier testing of NFS mounting (in the "NFS Shared Storage" section above) was done by mounting manually over SSH with a plain shell command, not through this role. The very first real run failed instantly with `[ERROR]: couldn't resolve module/action 'mount'`. Root cause: `ansible-core` (installed alone via pip in `docker/Dockerfile`) only bundles the `ansible.builtin` collection � the `mount` module was moved out into the separate `ansible.posix` collection in ansible-core 2.10+, and that collection was never installed. Fixed by adding `venv/bin/ansible-galaxy collection install ansible.posix --ignore-certs` to `docker/Dockerfile` (`--ignore-certs` because this environment sits behind TLS-inspecting corporate network security software that `galaxy.ansible.com`'s cert chain doesn't verify cleanly against � the same class of issue already worked around a few lines above with `wget --no-check-certificate` for the JRE download) and fully-qualifying the task as `ansible.posix.mount` in `playbooks/roles/nfs_client/tasks/main.yml`. **Lesson for the next golden-path template:** a product sitting unused in the catalogue is not the same as a product that's been proven to work � any role that's never actually been driven through a real Ansible run should be treated as unverified, no matter how straightforward the module list looks, and should get one deliberate live test the first time a template actually wires it in.

### Golden-Path Template Pitfalls: Porting a Template to a New OS Family (RHEL 8)

Recorded while building the **"Reference: Full Stack (RHEL 8)"** template — a from-scratch RHEL 8 port of the existing Ubuntu Full Stack template, same 8 roles (`pkg-cache`, `mysql`, `rabbitmq`, `keystone`, `backend`, `frontend`, `backend-lb`, `frontend-lb`). Two of the issues below are general lessons that apply to *any* golden-path work, not just RHEL — worth reading even if you're not touching RHEL.

**A role can register its own hostname wrong, and nothing catches it until something calls back in.** The `keystone` role sets its own Apache `ServerName` and its self-registered Keystone API endpoint (the URL baked into the identity service catalog via `keystone-manage bootstrap --bootstrap-public-url ...`) from `{{ inventory_hostname }}`. That's the ansible-internal group/host label (e.g. `keystone`) — not necessarily anything reachable. In this lab, the actually-connectable name is `ansible_host` (e.g. `target-keystone`, resolved per-role from `ip_allocations`/`container_manager.py`, matching the SAN the host's own TLS cert was issued for). Because `GET /v3/` (the unversioned root) doesn't consult the service catalog, this looked completely fine under a plain `curl` — Apache was up, TLS worked, the JSON response was correct. It only broke on a real `openstack` CLI call that authenticates, gets a token *and a service catalog*, then makes a second request against whatever endpoint URL the catalog says to use: that second call tried to resolve bare `keystone` and failed outright. **Lesson: a role that registers its own identity/endpoint (API base URL, `ServerName`, anything another host or client will later be told to connect back to) must use `ansible_host`, not `inventory_hostname` — and the only way to catch a mismatch like this is a test that actually exercises the *second* hop (follow a returned URL/catalog entry), not just a direct request to the host you already know how to reach.** Worth an audit if you're adding a new role that self-registers a URL anywhere (a discovery endpoint, a callback address, anything written into another service's config).

**Editing a role does nothing until the image is rebuilt.** `playbooks/` is `COPY`'d into the `certmanager` image at build time (`docker/Dockerfile`) — `docker-compose.yml`'s `certmanager` service only mounts `certmanager-data:/data` and the Docker socket, nothing under the repo's `playbooks/`. Editing a task file and re-running a build against the *already-running* container silently re-runs the **old** code with no error or warning that anything is stale — the job can complete "successfully" and still not reflect the fix. After any playbook/role change, rebuild and recreate before testing:
```bash
docker compose -f docker/docker-compose.yml build certmanager
docker compose -f docker/docker-compose.yml up -d certmanager
```
Confirm the fix actually landed by diffing the *container's* copy of the file against the repo before re-running a build (`docker exec ssl-cert-manager grep ... /opt/certmanager/playbooks/...`) — don't trust that a rebuild ran cleanly just because the `docker compose build` command exited 0.

**RHEL 8's free package repos are narrower than they look.** `registry.access.redhat.com/ubi8/ubi-init` gets you BaseOS + AppStream + EPEL 8 without a subscription, but the CodeReady Builder (CRB) repo resolves to near-empty metadata without one, and UBI8 deliberately excludes some packages from its trimmed BaseOS entirely (found needing `createrepo_c` and `nfs-utils` — neither is in BaseOS/AppStream/EPEL8, and CRB doesn't have them without a real subscription either). CentOS Stream 8's public vault archive (`vault.centos.org/8-stream/...`) is a binary-compatible substitute for exactly these gaps, but it's EOL and needs `sslverify=0` even at Docker build time. Pull in anything sourced from it carefully — a broad `dnf upgrade --allowerasing` afterward can silently remove a vault-sourced package again as collateral of resolving a newer version of one of its dependencies (confirmed directly: this took out `nfs-utils` even under `--setopt=protected_packages=nfs-utils`). Prefer avoiding the dependency that forces the conflicting version in the first place (here: skip `openssl-devel`'s `krb5-devel` chain, since `cryptography`'s prebuilt wheel doesn't need a source build) over trying to hold both versions.

**A long-running job can look "stuck at running" forever, even though it actually finished.** Observed once while testing this template under unusually heavy concurrent polling (repeated manual status checks in a tight loop): the gunicorn worker process running that job's background tracking task (`ansible_runner._execute_job`) was killed by gunicorn's own worker-timeout enforcement (`--timeout 120`) partway through. The underlying `ansible-playbook` subprocess wasn't killed — it kept running independently (reparented) and finished — but the coroutine that would have written the job's final `status`/`exit_code` to the database died with its worker, so the job (and the owning environment) stayed on `running`/`provisioning` indefinitely with no error surfaced anywhere. If a job's line count and a target host's own logs (`docker exec <target> journalctl -n5`) keep advancing but the job's reported status never changes, check the `certmanager` container's own logs for `Worker (pid:...) exited with code 255` around the same timestamps — that's gunicorn killing its own worker, not Ansible failing. Not confirmed whether this occurs under normal single-session UI use or only under unusually heavy polling; flagged here rather than silently worked around.

---

## 8. Service Roles & Product Deployment

Product deployment is the second phase of a Build. After base provisioning (Java, CA trust, JKS, certs), the `site.yml` playbook reads the `host_products` dictionary and dynamically includes the Ansible role for each product assigned to a host.

### How Product Deployment Works

```
Template spec ? host_products dict ? site.yml ? include_role per product
```

1. The template spec defines products per host role:
   ```json
   {
     "role": "host-01",
     "products": [
       {"product": "mysql", "version": "8.4", "vars": {}},
       {"product": "openjdk", "version": "17", "vars": {}}
     ]
   }
   ```

2. `base_provisioner.py` extracts this into a `host_products` dict keyed by role:
   ```json
   {
     "host-01": [
       {"ansible_role": "mysql", "vars": {}},
       {"ansible_role": "openjdk", "vars": {}}
     ]
   }
   ```

3. `site.yml` passes this as an extra var. The second play looks up `host_products[service_role]` for each host and includes the matching Ansible roles in order.

### Playbook Structure

**`site.yml`** � the single playbook used by Build, Provision, and Rebuild:

```yaml
- name: Base host provisioning
  hosts: all
  become: true
  roles:
    - base

- name: Deploy products
  hosts: all
  become: true
  tasks:
    - name: Get product list for this host
      set_fact:
        my_products: "{{ host_products[service_role] | default([]) }}"

    - name: Include product roles
      include_role:
        name: "{{ item.ansible_role }}"
      vars:
        product_vars: "{{ item.vars | default({}) }}"
      loop: "{{ my_products }}"
      when: my_products | length > 0
```

### Available Roles

All roles are located at `/opt/certmanager/playbooks/roles/`.

| Role | Status | Description |
|------|--------|-------------|
| `base` | ? Complete | Java 17, CA trust, JKS TrustStore/KeyStore, PEM certs |
| `mysql` | ? Complete | MySQL Server with TLS configuration |
| `nginx` | ? Complete | Nginx with TLS reverse proxy |
| `uvicorn` | ? Complete | FastAPI/Uvicorn with TLS + optional client certs |
| `openjdk` | ? Complete | Verifies Java 17 (installed by base) |
| `python` | ? Complete | Python 3 pip + venv |
| `rabbitmq` | ? Complete | RabbitMQ with TLS on AMQP + management UI |
| `keystone` | ?? Stub | Placeholder |
| `nginx_lb` | ? Complete | TLS-terminating reverse-proxy load balancer � one generic product used twice (`frontend-lb` and `backend-lb`) |

### MySQL Role

Purges any existing MySQL installation, performs a fresh install, configures TLS, sets the root password, and creates databases and users.

**What it does:**
1. **Purge** � stops MySQL, runs `apt purge`, removes `/var/lib/mysql`, `/etc/mysql/ssl`, `/root/.my.cnf`
2. Fresh install of `mysql-server` and `mysql-client`
3. Creates `/etc/mysql/ssl/` directory
4. Deploys server cert, key, and CA to the SSL directory
5. Starts MySQL via systemd
6. Sets root password via `auth_socket` (fresh install guarantees this works)
7. Creates `/root/.my.cnf` for passwordless subsequent commands
8. Writes `/etc/mysql/mysql.conf.d/ssl.cnf` enabling `require_secure_transport`
9. Restarts MySQL to apply TLS config
10. Optionally grants `root@'%'` (over TLS) when `mysql_allow_remote_root` is set — see below
11. Creates databases (from `mysql_databases` list)
12. Creates users with privileges (from `mysql_users` list)

The **nuke-before-install** pattern ensures every build starts from a clean state regardless of what was previously deployed on the host. This eliminates password mismatch issues on re-runs.

**Remote root access:** a fresh install only ever grants `root@'localhost'` — MySQL matches accounts by user *and* origin host, not password alone, so root is unreachable from any other host (e.g. a separate Adminer container) no matter how correct the password is. Set `mysql_allow_remote_root: true` in `product_vars` to also grant `root@'%'` (still TLS-only, via `require_secure_transport`). This is on by default in Build Manager's own generated vars whenever an `adminer` product is present anywhere else in the same environment spec, so a mysql+adminer pairing built via the UI works out of the box without the flag needing to be set by hand; it stays off for every other combination. Set the flag explicitly to override either way.

**File layout on host:**

| Path | Contents |
|------|----------|
| `/etc/mysql/ssl/server-cert.pem` | Server certificate |
| `/etc/mysql/ssl/server-key.pem` | Server private key |
| `/etc/mysql/ssl/ca.pem` | CA chain |
| `/etc/mysql/mysql.conf.d/ssl.cnf` | TLS + bind configuration |
| `/root/.my.cnf` | Root credentials for CLI access |

**TLS configuration (`ssl.cnf`):**
```ini
[mysqld]
ssl-ca=/etc/mysql/ssl/ca.pem
ssl-cert=/etc/mysql/ssl/server-cert.pem
ssl-key=/etc/mysql/ssl/server-key.pem
require_secure_transport=ON
bind-address=0.0.0.0
port=3306
```

**Variables (via `product_vars`):**

| Variable | Default | Description |
|----------|---------|-------------|
| `mysql_root_password` | `root` | Root user password |
| `mysql_bind_address` | `0.0.0.0` | Bind address |
| `mysql_port` | `3306` | Listen port |
| `mysql_databases` | `[]` | List of databases to create (each: `{name: "..."}`) |
| `mysql_users` | `[]` | List of users (each: `{name, password, host, priv}`) |
| `mysql_allow_remote_root` | `false`* | Also grant `root@'%'` over TLS. *Defaults to `true` when an `adminer` product is present elsewhere in the same environment spec — see "Remote root access" above. |

**User privilege format:** `priv` uses `scope:privileges` notation, e.g. `appdb.*:ALL PRIVILEGES` or `*.*:SELECT,INSERT`.

**Example product_vars:**
```json
{
  "mysql_root_password": "s3cret",
  "mysql_databases": [{"name": "keystone"}, {"name": "appdb"}],
  "mysql_users": [
    {
      "name": "keystoneuser",
      "password": "kpass",
      "host": "%",
      "priv": "keystone.*:ALL PRIVILEGES"
    }
  ]
}
```

### Adminer Role

Installs Nginx + PHP-FPM and a self-contained `adminer.php` for browser-based MySQL administration, wrapped to force TLS to the target MySQL server (no client cert).

**Variables (via `product_vars`):**

| Variable | Default | Description |
|----------|---------|-------------|
| `adminer_default_server` | `127.0.0.1`* | Pre-fills the login form's "Server" field. *Auto-set to the paired MySQL host's actual container name when a `mysql` product is present elsewhere in the same environment spec — see below. |
| `adminer_listen_port` | `8443` | HTTPS listen port |
| `adminer_version` | `4.8.1` | Adminer release to download |

Username and password are always plain manual form fields — never auto-filled or injected by the app.

**Mysql+Adminer pairing:** when an environment spec has both a `mysql` host and an `adminer` host, Build Manager automatically fills in two values that would otherwise leave Adminer unable to reach MySQL, unless the value is already set explicitly in `product_vars`:
- `adminer_default_server` on the Adminer host defaults to the MySQL host's real container name instead of `127.0.0.1` (which would only ever point Adminer at itself).
- `mysql_allow_remote_root` on the MySQL host defaults to `true` (see MySQL Role above), since without it root has no account MySQL will accept a connection from any other host for, regardless of password.

Both remain fully overridable per-environment via Template Builder / the environment's product config.

### Nginx Role

Purges any existing Nginx installation, performs a fresh install, and configures a TLS reverse proxy with optional upstream.

**What it does:**
1. **Purge** � stops Nginx, runs `apt purge nginx nginx-common`, removes `/etc/nginx/ssl`, sites configs
2. Installs `nginx` package
3. Creates `/etc/nginx/ssl/` directory
4. Deploys fullchain cert and private key
5. Templates `nginx.conf` (main config with TLS defaults)
6. Templates `default-server.conf` (HTTPS server block)
7. Validates config with `nginx -t`
8. Enables and starts Nginx via systemd

**File layout on host:**

| Path | Contents |
|------|----------|
| `/etc/nginx/ssl/server-fullchain.pem` | Server cert + CA chain |
| `/etc/nginx/ssl/server-key.pem` | Server private key |
| `/etc/nginx/nginx.conf` | Main Nginx config |
| `/etc/nginx/sites-enabled/default` | HTTPS server block |

**Features:**
- HTTP ? HTTPS redirect (port 80 ? 443)
- TLS 1.2 and 1.3 only
- Strong cipher suite
- Optional upstream proxy_pass (if `nginx_upstream` is defined)
- Static file serving fallback
- `/health` endpoint returning 200

**Variables (via `product_vars`):**

| Variable | Default | Description |
|----------|---------|-------------|
| `nginx_upstream` | (none) | Upstream server URL for proxy_pass |
| `nginx_server_name` | `_` | Server name directive |
| `nginx_root` | `/var/www/html` | Document root for static files |

### Nginx Load Balancer (`nginx_lb`) Role

A TLS-terminating, multi-service reverse-proxy load balancer � one catalogue product, used twice in the golden-path Full Stack template as two different host roles: `frontend-lb` (client-facing, L7) and `backend-lb` (internal, fronting the backend's uvicorn service). This mirrors the real application's own deployment architecture: its `frontend-lb`/`backend-lb` nginx configs were captured directly from a real "jar of jars" bundle via the JAR Analyser (`bundle/etc/nginx/conf.d/backend.conf` and `frontend.conf`) and used as the template for this role � see the Compatibility Checker / JAR Analyser report for the original source if you need to compare.

**Design: terminate-and-re-encrypt, not passthrough.** Each `nginx_lb` host has its own server certificate and terminates its own client-facing TLS, then re-encrypts outbound to its upstream(s) over HTTPS (`proxy_pass https://<name>-upstream<path>`). This was a deliberate architectural question early in this feature's design � the real captured configs settled it: both `backend.conf` and `frontend.conf` are `listen 443 default ssl` with their own `ssl_certificate`, not a `stream {}` TCP passthrough block. `proxy_ssl_verify` is left at nginx's default (`off`) � the hop to the upstream is genuinely encrypted but not chain/hostname-verified; harden later with `proxy_ssl_verify on` + `proxy_ssl_trusted_certificate` if the lab ever needs to model that.

**What it does:**
1. **Purge** � stops Nginx, runs `apt purge nginx nginx-common`, removes `/etc/nginx/ssl`, sites configs (same nuke-before-install pattern as the plain `nginx` role)
2. Installs `nginx` package (via the shared `resilient_apt_install.yml` retry wrapper)
3. Creates `/etc/nginx/ssl/` and deploys this host's own `server-fullchain.pem` / `server-key.pem` (same per-host cert-issuance mechanism as every other TLS-facing role � one "server" cert per host role, CN `{role}.{domain}`)
4. Templates `nginx.conf` (generic TLS 1.2/1.3 defaults) and `lb-server.conf` (the actual load-balancing config)
5. Validates with `nginx -t`, enables and starts via systemd

**`lb-server.conf` structure** � built from `nginx_lb_upstreams` (see Variables below), one `upstream`/`location` pair per entry:
```nginx
upstream backend-upstream { server backend:8000; keepalive 5; }

server {
    listen 443 ssl;
    location / {
        proxy_pass https://backend-upstream/;
        proxy_ssl_verify off;
    }
}
```
Plus an HTTP?HTTPS redirect server block and a `/health` endpoint, matching the plain `nginx` role's conventions.

**Variables (via `product_vars`):**

| Variable | Default | Description |
|----------|---------|-------------|
| `lb_upstreams` | `[]` | List of upstreams to proxy: each `{name, path, host, port}` |
| `nginx_lb_sudo_users` | `""` | Comma-separated usernames to grant passwordless sudo (optional, matches other roles) |
| `nginx_lb_sudo_nopasswd` | `false` | Whether the sudo grant above is passwordless |

**Example `product_vars`** (this is exactly what the golden-path Full Stack template uses for each tier):
```json
// backend-lb � fronts the backend host's uvicorn service
{"lb_upstreams": [{"name": "backend", "path": "/", "host": "backend", "port": 8000}]}

// frontend-lb � fronts the frontend host's nginx
{"lb_upstreams": [{"name": "frontend", "path": "/", "host": "frontend", "port": 443}]}
```

Because `nginx_lb` is one catalogue product resolved independently per host role (the orchestrator's `host_products` dict is keyed by role, each with its own `product_vars`), the same Ansible role serves both tiers with completely different upstream wiring � no special-casing needed anywhere in the provisioning code.

### Uvicorn Role

Purges any existing installation, deploys a Python ASGI application (FastAPI) with TLS, optional client certificates for mTLS to downstream services, and manages it via systemd.

**What it does:**
1. **Purge** � stops uvicorn service, removes `/opt/app`, removes systemd unit
2. Installs `python3-pip`, `python3-venv`, `git`
3. Creates `appuser` system user
4. Creates `/opt/app/` directory structure
5. Deploys sample FastAPI app (if no git repo specified) OR clones the configured repository
6. Creates Python virtual environment at `/opt/app/venv`
7. Installs `fastapi` + `uvicorn[standard]` (+ `requirements.txt` if present)
8. Deploys server cert, key, and CA to `/opt/app/ssl/`
9. Deploys client cert and key to `/opt/app/ssl/` (if `client_certs` defined in host spec)
10. Templates systemd unit with TLS flags
11. Enables and starts the uvicorn service

**File layout on host:**

| Path | Contents |
|------|----------|
| `/opt/app/src/` | Application source code |
| `/opt/app/venv/` | Python virtual environment |
| `/opt/app/ssl/server.pem` | Server certificate |
| `/opt/app/ssl/server-key.pem` | Server private key |
| `/opt/app/ssl/ca.pem` | CA chain |
| `/opt/app/ssl/client.pem` | Client certificate (for mTLS to downstream) |
| `/opt/app/ssl/client-key.pem` | Client private key |
| `/etc/systemd/system/uvicorn.service` | Systemd unit file |

**Systemd unit (`uvicorn.service`):**
```ini
[Unit]
Description=Uvicorn ASGI Server
After=network.target

[Service]
Type=simple
User=appuser
Group=appuser
WorkingDirectory=/opt/app/src
ExecStart=/opt/app/venv/bin/uvicorn main:app \
    --host 0.0.0.0 --port 8000 --workers 4 \
    --ssl-keyfile /opt/app/ssl/server-key.pem \
    --ssl-certfile /opt/app/ssl/server.pem \
    --ssl-ca-certs /opt/app/ssl/ca.pem \
    --access-log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The `--ssl-*` flags are only included when `uvicorn_ssl_enabled` is true (default).

**Variables (via `product_vars`):**

| Variable | Default | Description |
|----------|---------|-------------|
| `uvicorn_port` | `8000` | Listen port |
| `uvicorn_workers` | `4` | Number of worker processes |
| `uvicorn_app_module` | `main:app` | ASGI application module path |
| `uvicorn_ssl_enabled` | `true` | Enable TLS on the listener |
| `uvicorn_app_repo` | (empty) | Git repository URL to clone (if empty, deploys sample app) |
| `uvicorn_app_branch` | `main` | Git branch to checkout |

**Sample app (deployed when no repo is specified):**
```python
from fastapi import FastAPI

app = FastAPI(title="Backend Service")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"service": "backend", "tls": True}
```

**Client certificates for mTLS:**

When the host spec includes `client_certs: [...]`, the base provisioner issues a separate client certificate (CN: `<role>-client.<domain>`) and passes it to the role as `client_cert_pem` / `client_key_pem`. These are deployed to `/opt/app/ssl/client.pem` and `/opt/app/ssl/client-key.pem`.

The application code can use these client certs when making outbound connections to services that require mTLS (e.g. MySQL with `require_secure_transport`, RabbitMQ with peer verification).

**Template spec example (backend with client certs):**
```json
{
  "role": "backend",
  "client_certs": ["mysql", "rabbitmq"],
  "products": [
    {
      "product_name": "uvicorn",
      "version": "0.34.0",
      "ansible_role": "uvicorn",
      "vars": {"uvicorn_port": 8000, "uvicorn_workers": 2}
    }
  ]
}
```

### OpenJDK Role

Verifies that Java 17 is installed (already handled by the base role). Reports the installed version.

### RabbitMQ Role

Purges any existing installation, installs Erlang + RabbitMQ from Ubuntu distro repositories, configures TLS on AMQP and management UI, creates an admin user, removes the default guest user, and creates application users.

**What it does:**
1. **Purge** � stops rabbitmq-server, runs `apt purge rabbitmq-server erlang*`, removes `/var/lib/rabbitmq`, `/etc/rabbitmq`, `/var/log/rabbitmq`, and stale repo list files
2. Installs `erlang-nox` and `rabbitmq-server` from Ubuntu distro repos (containers have internet access)
3. Deploys server cert, key (no password), and CA chain to `/etc/rabbitmq/ssl/`
4. Creates a symlink `server.key.nopass` ? `server.key` for compatibility
5. Deploys `rabbitmq.conf` from Jinja2 template (all settings configurable via form)
6. Deploys Erlang cookie
7. **Explicit restart** � restarts RabbitMQ via systemd (picks up new config + certs), waits for readiness
8. Enables management plugin (if checkbox enabled)
9. **Restart after plugin enable** � required for management SSL config to take effect
10. Creates `admin` user with the password from the form, sets `administrator` tag and full permissions
11. **Deletes the default `guest` user** (security hardening)
12. Creates vhost (if non-default specified)
13. Creates individual users with tags and permissions
14. Creates bulk users from tab-separated permissions table

**Important design decisions:**
- No Ansible handlers are used � all restarts are explicit and ordered. This prevents the handler-fires-after-password-change race condition that caused password loss on earlier builds.
- The `guest` user is deleted entirely rather than having its password changed. A new `admin` user is created instead. This follows RabbitMQ security best practices.
- Distro repos are used (not Cloudsmith/Erlang Solutions). The purge step removes any stale `.list` files from previous failed installs to prevent apt conflicts.

**File layout on host:**

| Path | Contents |
|------|----------|
| `/etc/rabbitmq/ssl/server.crt` | Server certificate |
| `/etc/rabbitmq/ssl/server.key` | Server private key (no password) |
| `/etc/rabbitmq/ssl/server.key.nopass` | Symlink ? server.key |
| `/etc/rabbitmq/ssl/ca.crt` | CA chain |
| `/etc/rabbitmq/rabbitmq.conf` | Main configuration |
| `/var/lib/rabbitmq/.erlang.cookie` | Erlang cluster cookie |

**Default configuration (`rabbitmq.conf`):**
```ini
listeners.ssl.default = 5671
ssl_options.cacertfile = /etc/rabbitmq/ssl/ca.crt
ssl_options.certfile   = /etc/rabbitmq/ssl/server.crt
ssl_options.keyfile    = /etc/rabbitmq/ssl/server.key
ssl_options.versions.1 = tlsv1.3
ssl_options.versions.2 = tlsv1.2
ssl_options.verify     = verify_none
ssl_options.fail_if_no_peer_cert = false

listeners.tcp = none

management.ssl.port       = 15671
management.ssl.cacertfile = /etc/rabbitmq/ssl/ca.crt
management.ssl.certfile   = /etc/rabbitmq/ssl/server.crt
management.ssl.keyfile    = /etc/rabbitmq/ssl/server.key

heartbeat = 580

log.file.level = info

loopback_users = none
```

Every setting in this config is individually configurable via labelled form fields in the environment creation UI. The `loopback_users = none` setting allows the admin user to connect from any host (required for Docker port-forwarded access).

**Variables (via `product_vars`):**

| Variable | Default | Description |
|----------|---------|-------------|
| `rabbitmq_admin_password` | `guest` | Password for the `admin` user (created fresh, replaces guest) |
| `rabbitmq_enable_management` | `true` | Enable management UI plugin (checkbox) |
| `rabbitmq_vhost` | `/` | VHost to create (and assign users to) |
| `rabbitmq_ssl_port` | `5671` | AMQPS listener port |
| `rabbitmq_ssl_cacertfile` | `/etc/rabbitmq/ssl/ca.crt` | CA cert path |
| `rabbitmq_ssl_certfile` | `/etc/rabbitmq/ssl/server.crt` | Server cert path |
| `rabbitmq_ssl_keyfile` | `/etc/rabbitmq/ssl/server.key` | Server key path |
| `rabbitmq_ssl_version_1` | `tlsv1.3` | Primary TLS version |
| `rabbitmq_ssl_version_2` | `tlsv1.2` | Secondary TLS version |
| `rabbitmq_ssl_verify` | `verify_none` | Peer verification mode |
| `rabbitmq_ssl_fail_if_no_peer_cert` | `false` | Reject clients without cert |
| `rabbitmq_tcp_listener` | `none` | Plain TCP listener (set to port number to enable) |
| `rabbitmq_management_ssl_port` | `15671` | Management UI HTTPS port |
| `rabbitmq_heartbeat` | `580` | Connection heartbeat (seconds) |
| `rabbitmq_log_level` | `info` | Log level |
| `rabbitmq_loopback_users` | `none` | Loopback restriction (`none` = allow all) |
| `rabbitmq_users` | `[]` | List of users (each: `{name, password, tags, vhost, configure_priv, write_priv, read_priv}`) |
| `rabbitmq_bulk_users` | (empty) | Tab-separated bulk user import (textarea) |

**Login credentials after build:**
- Username: `admin`
- Password: whatever was entered in the "Admin Password" form field
- The `guest` user no longer exists

**Accessing the management UI (Docker):**
- URL: `https://localhost:15671`
- The port is exposed via docker-compose port mapping (`15671:15671` on target-rabbitmq)
- Browser will show a certificate warning unless the CA is trusted (import the CA cert or use the cert manager's trust distribution)

**User tags:** Tags control RabbitMQ permissions. Common tags: `administrator`, `monitoring`, `policymaker`, `management`. Multiple tags are space-separated (e.g. `administrator monitoring`).

**Individual user example:**
```json
{
  "rabbitmq_users": [
    {
      "name": "appuser",
      "password": "s3cret",
      "tags": "administrator",
      "vhost": "/ssp",
      "configure_priv": ".*",
      "write_priv": ".*",
      "read_priv": ".*"
    }
  ]
}
```

**Bulk user import format:**

Paste tab-separated data matching `rabbitmqctl list_permissions` output. Each line: `username<TAB>configure<TAB>write<TAB>read`. All bulk users get their username as their initial password and are assigned to the configured vhost.

```
blobstore	.*	.*	.*
request	.*	.*	.*
fulfillment	.*	.*	.*
export	.*	.*	.*
event	.*	.*	.*
catalog	.*	.*	.*
ticket	.*	.*	.*
svcinst	.*	.*	.*
customer	.*	.*	.*
pricing	.*	.*	.*
config	.*	.*	.*
reporting	.*	.*	.*
```

This creates 12 users in one operation, each with full permissions on the configured vhost.

**CA Selection & Name Constraints:**

When creating an environment, the UI includes a CA selector dropdown. CAs with Name Constraints (e.g. only permitting `.alpha.internal`) are flagged with a warning. If a constrained CA is selected, certificates for `localhost` or `127.0.0.1` SANs will be rejected by browsers.

The recommended approach is to use an unconstrained intermediate CA (marked with ? in the dropdown). The provisioner will also auto-skip constrained CAs if no explicit selection is made.

**Troubleshooting:**

| Problem | Cause | Fix |
|---------|-------|-----|
| Can't login to management UI | Wrong username � use `admin` not `guest` | Guest is deleted; login as `admin` |
| "Not Authorised" after build | Password not applied | Check job output for errors in the password task |
| Management UI not accessible | Plugin not enabled or port not exposed | Verify `rabbitmq_enable_management: true` and port 15671 is mapped |
| Certificate error in browser | CA not trusted or Name Constraints violation | Use an unconstrained CA, or import the CA cert into browser |
| Stale apt repo errors during install | Previous failed build left `.list` files | Purge step now cleans these automatically |

### Python Role

Installs Python 3 development packages.

**What it does:**
1. Installs `python3-pip` and `python3-venv`
2. Verifies Python version
3. Reports installed version

### Product Configuration

Product variables come from two sources, merged at build time:

1. **Template defaults** � `default_vars` from the product version in the catalogue
2. **Environment overrides** � user-entered config stored in `variables.product_config`

The merge happens in `base_provisioner.py` via the `_get_product_config()` helper, which reads `variables.product_config.<role>.<product_name>` and merges it into `product_vars` passed to the Ansible role.

**UI flow:** When creating an environment, the UI renders dynamic form fields based on the product's `config_schema` (defined on the product version). Users fill in passwords, ports, database names, etc. via labelled form inputs � no JSON editing required.

**Config schema field types:**
- `text` � single-line string input
- `password` � masked input
- `number` � numeric input
- `list` � repeatable items with sub-fields (e.g. list of databases, list of users)

### Adding Custom Roles

To add a new product role:

1. Create the role directory: `playbooks/roles/<name>/tasks/main.yml`
2. Add a product to the catalogue with `ansible_role: "<name>"`
3. Add a version entry for the product (include `config_schema` for UI forms)
4. Assign the product to a host in a template
5. Build � the role will be included automatically

**Role conventions:**
- **Purge first** � remove any existing installation at the top of the role for clean-state builds
- Merge `product_vars` at the start: `set_fact` with defaults + overrides
- Use certificates from base provisioning paths (`/etc/ssl/certs/`, `/etc/ssl/private/`)
- Use `systemctl` for service management (target containers have systemd)
- Include handlers for service restart/reload
- Mark password-related tasks with `no_log: true`

### Build Flow Summary

```
User clicks Build
     �
     ?
API issues server certs per host (base_provisioner.py)
     �
     ?
API issues client certs for hosts with client_certs spec
     �
     ?
API extracts host_products from template spec
     �
     ?
API submits job: ansible-playbook site.yml
     �
     ?
Play 1: Base role on all hosts
  - Java 17, CA trust, JKS, PEM certs
     �
     ?
Play 2: Product roles per host
  - Reads host_products[service_role]
  - Includes each role in order
  - Passes product_vars + client cert vars to each role
     �
     ?
Job completes ? environment status = active
```

### Environment Actions

| Action | What it does | Allowed from states |
|--------|-------------|--------------------|
| **Build** | Issues certs + runs `site.yml` (base + products) | `pending`, `active`, `degraded`, `failed` |
| **Rebuild** | Revokes old certs, re-issues, runs `site.yml` | Any non-destroyed |
| **Destroy** | Revokes certs, deletes environment record (DB-only, services persist on hosts) | Any non-destroyed |
| **Verify TLS** | Runs `verify.yml` to check TLS on all deployed services | `active`, `degraded`, `failed` |

There is no separate "Provision" action � Build always runs the full flow (base + products) in a single pass.

---

## 9. Product Configuration Reference

Minimal working configurations for each catalogue product. All products follow the nuke-before-install pattern � every build starts clean.

### Databases & Caching

#### Redis

In-memory data store. Minimal config just needs a password:

| Field | Value |
|-------|-------|
| Password | `myredispass` |
| Port | `6379` |
| Max Memory | `256mb` |
| Enable TLS | ? |

After build, test with:
```bash
redis-cli -h <host> -p 6379 --tls --cacert /etc/redis/ssl/ca.crt -a myredispass PING
```

Cert files land in `/etc/redis/ssl/`. Config at `/etc/redis/redis.conf`.

#### PostgreSQL

Minimal config � set a superuser password and optionally create a database:

| Field | Value |
|-------|-------|
| Superuser Password | `pgpass123` |
| Port | `5432` |
| Listen Addresses | `*` |
| Enable TLS | ? |
| Databases | `[{name: "appdb"}]` |
| Users | `[{name: "appuser", password: "s3cret"}]` |

After build, test with:
```bash
psql "host=<host> port=5432 dbname=appdb user=appuser password=s3cret sslmode=require"
```

Cert files at `/etc/postgresql/ssl/`. pg_hba.conf defaults to `scram-sha-256` for all remote connections.

#### MongoDB

Minimal config � set an admin password:

| Field | Value |
|-------|-------|
| Admin Password | `mongoadmin` |
| Port | `27017` |
| Bind IP | `0.0.0.0` |
| Enable TLS | ? |

After build, test with:
```bash
mongosh --host <host> --tls --tlsCAFile /etc/mongod/ssl/ca.crt -u admin -p mongoadmin --authenticationDatabase admin
```

Note: MongoDB requires a combined PEM (cert+key) at `/etc/mongod/ssl/server.pem`. The role handles this.

#### Memcached

No auth by default � just set memory and port:

| Field | Value |
|-------|-------|
| Port | `11211` |
| Memory (MB) | `128` |
| Listen Address | `0.0.0.0` |
| Max Connections | `1024` |

After build, test with:
```bash
echo "stats" | nc <host> 11211
```

No TLS support (Memcached protocol limitation). Restrict access via network/firewall.

---

### Networking & Security

#### HAProxy

Minimal config � one frontend proxying to one backend:

| Field | Value |
|-------|-------|
| Stats Port | `8404` |
| Stats Username | `admin` |
| Stats Password | `hapass` |
| Enable TLS | ? |
| Frontends | `[{name: "http_front", bind: "*:443 ssl crt /etc/haproxy/ssl/server.pem", mode: "http", default_backend: "app_servers"}]` |
| Backends | `[{name: "app_servers", mode: "http", balance: "roundrobin", servers: "web1:10.0.0.1:8000, web2:10.0.0.2:8000"}]` |

After build:
- Stats UI: `http://<host>:8404/stats`
- Cert files at `/etc/haproxy/ssl/`
- Config at `/etc/haproxy/haproxy.cfg`

#### UFW (Firewall)

Minimal config � deny all incoming, allow SSH + your service ports:

| Field | Value |
|-------|-------|
| Default Incoming | `deny` |
| Default Outgoing | `allow` |
| Rules | `[{port: "22", proto: "tcp", action: "allow"}, {port: "443", proto: "tcp", action: "allow"}]` |

SSH (port 22) is always allowed as a safety net regardless of rules. After build:
```bash
ufw status verbose
```

#### Fail2Ban

Minimal config � just enable the SSH jail:

| Field | Value |
|-------|-------|
| Default Ban Time | `1h` |
| Find Time | `10m` |
| Max Retry | `5` |
| Jails | `[{name: "sshd", enabled: true, port: "ssh"}]` |

After build:
```bash
fail2ban-client status sshd
```

Add more jails for nginx, apache, etc. as needed.

#### WireGuard

Minimal config � set an interface address. Peers are optional (add later):

| Field | Value |
|-------|-------|
| Interface Address | `10.0.0.1/24` |
| Listen Port | `51820` |

After build, the server's public key is printed in the job output. Use it to configure peers:
```bash
wg show wg0
cat /etc/wireguard/public.key
```

To add a peer later, update the config and re-build, or manually edit `/etc/wireguard/wg0.conf`.

---

### Monitoring & Logging

#### Prometheus Node Exporter

Minimal config � just set the port (defaults work fine):

| Field | Value |
|-------|-------|
| Listen Port | `9100` |
| Extra Collectors | (blank for defaults) |

After build, metrics available at:
```bash
curl http://<host>:9100/metrics
```

Add `systemd,processes,tcpstat` to Extra Collectors for more detail.

#### Filebeat

Minimal config � ship syslog to an Elasticsearch instance:

| Field | Value |
|-------|-------|
| Inputs | `[{type: "filestream", paths: "/var/log/syslog, /var/log/auth.log"}]` |
| Output Type | `elasticsearch` |
| Output Host | `elasticsearch.internal` |
| Output Port | `9200` |

After build:
```bash
systemctl status filebeat
filebeat test output
```

Config at `/etc/filebeat/filebeat.yml`.

#### cAdvisor

Minimal config � just set the port. Requires Docker CE on the same host:

| Field | Value |
|-------|-------|
| Listen Port | `8080` |
| Docker Socket | `/var/run/docker.sock` |

After build, container metrics at:
```
http://<host>:8080/containers/
```

Note: cAdvisor auto-adds `docker_ce` as a dependency.

---

### Runtimes & Build Tools

#### Go

Minimal config � just install (defaults to `/usr/local/go`):

| Field | Value |
|-------|-------|
| Install Path | `/usr/local/go` |

After build:
```bash
source /etc/profile.d/golang.sh
go version
```

The PATH is set system-wide via `/etc/profile.d/golang.sh`.

#### Rust

Minimal config � specify which user gets rustup:

| Field | Value |
|-------|-------|
| Install for User | `root` |

After build:
```bash
source $HOME/.cargo/env
rustc --version
cargo --version
```

Installed via rustup. Each user gets their own toolchain.

#### Docker CE

Minimal config � optionally add users to the docker group:

| Field | Value |
|-------|-------|
| Users in docker group | `deploy` |
| Install Docker Compose | ? |

After build:
```bash
docker --version
docker compose version
```

Optional `daemon.json` overrides for log rotation, registry mirrors, etc.

#### GCC / Build Essentials

Minimal config � install with common extras:

| Field | Value |
|-------|-------|
| Extra Packages | `cmake,make,gdb` |

After build:
```bash
gcc --version
cmake --version
make --version
```

Add `valgrind,pkg-config,autoconf,libtool` for a more complete toolchain.

---

### System Utilities

#### Chrony (NTP)

Minimal config � use default NTP pools (works out of the box with no config):

| Field | Value |
|-------|-------|
| NTP Servers | `[{server: "pool.ntp.org", options: "iburst"}]` |
| Allow Networks | (blank � client only) |

After build:
```bash
chronyc tracking
chronyc sources
```

Critical for TLS � clock skew causes certificate validation failures.

#### rsyslog

Minimal config � forward logs to a central server:

| Field | Value |
|-------|-------|
| Remote Log Host | `logserver.internal` |
| Remote Port | `514` |
| Protocol | `tcp` |

After build, all syslog messages forward to the remote host. Config at `/etc/rsyslog.d/99-remote.conf`.

Leave Remote Log Host blank to just ensure rsyslog is installed and running locally.

#### Certbot

Minimal config � request a Let's Encrypt certificate:

| Field | Value |
|-------|-------|
| Email | `admin@example.com` |
| Domains | `example.com, www.example.com` |
| Validation Method | `webroot` |
| Webroot Path | `/var/www/html` |

After build, certs at `/etc/letsencrypt/live/<domain>/`. Auto-renewal timer is enabled.

Note: Requires the domain to be publicly accessible for HTTP-01 validation. Use `standalone` method if no web server is running.

#### Git

No configuration needed � just installs git:

After build:
```bash
git --version
```

#### Cron Jobs

Minimal config � define one or more scheduled tasks:

| Field | Value |
|-------|-------|
| Jobs | `[{name: "Rotate logs", minute: "0", hour: "2", job: "/usr/sbin/logrotate /etc/logrotate.conf", user: "root"}]` |

After build:
```bash
crontab -l -u root
```

All standard cron fields supported: minute, hour, day, month, weekday. Defaults to `*` (every).

---

### Identity & Access

#### OpenLDAP

Minimal config � set domain and admin password:

| Field | Value |
|-------|-------|
| Domain | `example.com` |
| Organisation | `Example Corp` |
| Admin Password | `ldapadmin` |
| Enable TLS (LDAPS) | ? |

After build:
```bash
ldapsearch -x -H ldap://localhost -b "dc=example,dc=com" -D "cn=admin,dc=example,dc=com" -w ldapadmin
```

TLS certs at `/etc/ldap/ssl/`. LDAPS on port 636 (requires cert deployment).

#### FreeIPA Client

Minimal config � enroll in an existing FreeIPA domain:

| Field | Value |
|-------|-------|
| IPA Server | `ipa.example.com` |
| Domain | `example.com` |
| Kerberos Realm | `EXAMPLE.COM` |
| Enroll Principal | `admin` |
| Enroll Password | `ipaadminpass` |
| Create Home Dirs | ? |

After build:
```bash
id admin@example.com
klist
```

Requires a running FreeIPA server. The client configures SSSD for centralised auth.

#### SSH Hardening

Minimal config � disable password auth, restrict root:

| Field | Value |
|-------|-------|
| SSH Port | `22` |
| Permit Root Login | `prohibit-password` |
| Password Authentication | `no` |
| Max Auth Tries | `3` |
| X11 Forwarding | `no` |
| Allowed Users | (blank � all users) |

After build, the original config is backed up to `/etc/ssh/sshd_config.bak`. The role validates with `sshd -t` before restarting.

?? **Warning:** If you set `Allowed Users`, ensure your SSH user is in the list or you'll lock yourself out.

---

### Quick Reference � All Products

| Product | Category | Ports | TLS | Key Config |
|---------|----------|-------|:---:|------------|
| Redis | database | 6379 | ? | password, maxmemory |
| PostgreSQL | database | 5432 | ? | superuser password, databases, users, pg_hba |
| MongoDB | database | 27017 | ? | admin password, databases, users |
| Memcached | database | 11211 | ? | memory, max connections |
| HAProxy | networking | 80, 443, 8404 | ? | frontends, backends, stats |
| UFW | networking | � | � | default policies, rules list |
| Fail2Ban | networking | � | � | jails, bantime, maxretry |
| WireGuard | networking | 51820 | � | interface address, peers |
| Node Exporter | monitoring | 9100 | ? | port, collectors |
| Filebeat | monitoring | � | ? | inputs, output host/port |
| cAdvisor | monitoring | 8080 | ? | port, docker socket |
| Go | runtime | � | � | install path |
| Rust | runtime | � | � | target user |
| Docker CE | runtime | 2376 | ? | docker group users, daemon.json |
| GCC | devtools | � | � | extra packages |
| Chrony | utility | � | � | NTP servers |
| rsyslog | utility | 514 | � | remote host/port |
| Certbot | utility | � | � | email, domains, method |
| Git | devtools | � | � | (none) |
| Cron Jobs | utility | � | � | jobs list |
| OpenLDAP | identity | 389, 636 | ? | domain, org, admin password |
| FreeIPA Client | identity | � | � | server, domain, realm, password |
| SSH Hardening | networking | 22 | � | root login, password auth, allowed users |

---

## 10. TLS Verification

After a build completes, you can verify that TLS is correctly configured on all deployed services using the built-in verification system.

### How It Works

1. A `verify.yml` playbook is submitted as a job against the environment's hosts
2. Each product role has a `tasks/verify.yml` that runs `openssl s_client` against the service port
3. Results are captured as structured `TLS_RESULT:{...}` JSON lines in the job output
4. The backend parses these lines and presents them in the UI

### Running Verification

**Via UI:**
1. Navigate to **Build Manager ? Environments**
2. Select an environment with status `active`, `degraded`, or `failed`
3. Click the **?? Verify TLS** button
4. Results appear in the TLS Verification panel after the job completes (auto-polls)

**Via API:**
```bash
# Start verification
curl -X POST http://127.0.0.1:8000/api/v1/build/environments/<id>/verify \
  -H "Authorization: Bearer <token>"

# Get results (poll until available=true)
curl http://127.0.0.1:8000/api/v1/build/environments/<id>/verify-results \
  -H "Authorization: Bearer <token>"
```

### What Each Role Verifies

| Role | Checks | Port |
|------|--------|------|
| Nginx | `openssl s_client` with SNI on port 443 | 443 |
| MySQL | `openssl s_client -starttls mysql` + `mysql --ssl-mode=REQUIRED` session check | 3306 |
| RabbitMQ | AMQP TLS on 5671, Management HTTPS on 15671, `rabbitmqctl status` SSL listeners | 5671, 15671 |
| Keystone | `openssl s_client` on port 5000 | 5000 |
| Uvicorn | `openssl s_client` on port 8000 | 8000 |
| OpenJDK | No TLS endpoint (runtime dependency) � skipped in results | � |
| Python | No TLS endpoint (runtime dependency) � skipped in results | � |
| Base | No TLS endpoint � skipped in results | � |
| FastAPI | Behind reverse proxy � skipped in results | � |

### Result Fields

Each TLS result contains:

| Field | Description |
|-------|-------------|
| `product` | Product name (e.g. `rabbitmq-amqp`, `mysql-session`) |
| `port` | Port checked (0 = skipped/no endpoint) |
| `status` | `ok`, `failed`, or `warning` |
| `host` | Target hostname |
| `subject` | Certificate subject CN |
| `issuer` | Certificate issuer CN |
| `protocol` | TLS protocol version (e.g. `TLSv1.3`) |
| `cipher` | Cipher suite used |
| `verify` | OpenSSL verify result (e.g. `Verify return code: 0 (ok)`) |
| `error` | Error message (if failed) |
| `detail` | Additional context |

### UI Display

The verification panel shows:
- **Summary badges** � count of passed/failed/warnings (excludes port=0 entries)
- **Results table** � Host, Product, Port, Status, Details columns
- **Details column** � combines protocol/cipher and subject: e.g. `TLSv1.3 / TLS_AES_256_GCM_SHA384 � CN = host-01.internal`
- **Certificate links** � serial numbers in the Certificates section link directly to the certificate detail page in SSL Cert Manager

Results with `port: 0` (runtime dependencies with no TLS endpoint) are filtered out of the display.

### Cached Results

The most recent verification results are cached and displayed when you select an environment. Click **?? Verify TLS** again to re-run with fresh checks.

### Troubleshooting Verification

| Problem | Cause | Fix |
|---------|-------|-----|
| All checks show "failed" | Service not running on target | Check job output for the build � service may have failed to start |
| Protocol shows empty | `openssl s_client` output format mismatch | Verify OpenSSL 3.x is installed on target |
| MySQL session check fails | MySQL not accepting TLS connections | Verify `require_secure_transport=ON` in ssl.cnf and MySQL restarted |
| RabbitMQ AMQP check fails | Plain TCP listener still active | Ensure `listeners.tcp = none` in rabbitmq.conf |
| Verify job stays "running" | Ansible stuck on unreachable host | Check SSH connectivity, cancel the job manually |

### Adding Cross-Host Trust to a New Catalogue Service

Every host in an environment gets a valid certificate from the environment's shared CA, and that CA is trusted machine-wide on every host (see [Base Provisioning](#base-provisioning-stage-3)). That is **not** the same thing as proving one service in the environment actually trusts another over TLS. This section is the checklist for wiring and proving that a **new** catalogue product's TLS is actually recognized and trusted by its peers — not just "the cert exists and looks valid," which a same-host `openssl s_client -connect 127.0.0.1:<port>` check will happily report even if no other host in the environment could ever verify it.

**Important:** the `cert_requirements` field on a product's `catalogue_service.py` entry (e.g. `{"server_tls": true, "client_mtls": false}`) is display-only metadata, surfaced in the Template Builder UI. It is never read by `base_provisioner.py` or by anything that generates Ansible tasks. Setting it does not turn on TLS, deploy a cert to a non-default path, or create any verification check — it only *documents* to a anyone building a template that this product needs TLS. All of the actual wiring below has to be written by hand, per role.

#### What you get for free (zero code, applies to every host regardless of role)

| Mechanism | Where it happens | What it buys you |
|-----------|-------------------|-------------------|
| Cert issuance from the environment's single shared CA | `base_provisioner.py`'s `provision_environment()` — reads `signing_ca_id` once, issues one cert per host, unconditionally | Every host has a valid cert+key on disk, no matter what role it runs |
| CA installed into the OS trust store | `base` role, OS-family-aware (`update-ca-certificates` / `update-ca-trust extract` / etc.) | `curl`, `openssl s_client`, `apt`/`dnf`, and any client that defaults to the OS cert bundle automatically trusts every other host's cert |
| Java TrustStore (`/etc/pki/java/truststore.jks`) and KeyStore (`/etc/pki/java/keystore.jks`) | `base` role | A JVM-based product pointed at these files gets CA trust / a signed identity for free |
| Generic PEM files (`/etc/ssl/certs/server.pem`, `/etc/ssl/private/server-key.pem`, `/etc/ssl/certs/server-fullchain.pem`) | `base` role | A starting point any product's config can be pointed at — but nothing points at them automatically |

None of this makes a new product *serve* TLS, and none of it *proves* another host actually verifies that product's cert. Both of those require explicit, per-role work — the same work that had to be done individually for `nginx_lb`, `keystone`, `mysql`, `rabbitmq`, `postgresql`, `redis`, `mongodb`, `openldap`, `haproxy`, and `docker_ce`. As of this writing, only **`keystone`** (checking `mysql` and `rabbitmq`) and **`nginx_lb`** (checking its proxied backend) have a real cross-host trust check — every other role's `TLS_VERIFY` task is a same-host loopback check only. Don't assume a product is cross-host-trusted just because it has a `TLS_VERIFY` entry in the verification table above.

#### Step-by-step: wiring a new service

**1. Make the product actually serve TLS using the deployed cert.**

In the new role's `playbooks/roles/<role>/tasks/main.yml`, add a task (after `base` has run) that points the product's own config at the cert/key `base` already deployed — either the generic PEM files or a product-specific path if the service expects one (e.g. RabbitMQ wants its own `/etc/rabbitmq/ssl/` copies, deployed like this):

```yaml
- name: Deploy server certificate
  ansible.builtin.copy:
    content: "{{ server_cert_pem }}"
    dest: /etc/rabbitmq/ssl/server.crt
    mode: "0644"
    owner: rabbitmq
    group: rabbitmq

- name: Deploy server key (no password)
  ansible.builtin.copy:
    content: "{{ server_key_pem }}"
    dest: /etc/rabbitmq/ssl/server.key
    mode: "0600"
    owner: rabbitmq
    group: rabbitmq
```

`server_cert_pem` / `server_key_pem` are already set as facts by the `base` role (from the role-prefixed `<service_role>_server_cert_pem` / `<service_role>_server_key_pem` extra vars) — you don't need to re-derive them. Then flip on TLS in the product's own config template (`ssl=on`, `tls_cert_file=...`, etc. — whatever that product calls it) and restart/reload the service.

**2. Add a same-host `TLS_VERIFY` check (proves the service presents a valid cert).**

In `playbooks/roles/<role>/tasks/verify.yml`:

```yaml
- name: "TLS_VERIFY <role>"
  ansible.builtin.shell: |
    result=$(echo | openssl s_client -connect 127.0.0.1:{{ product_vars.<role>_port | default(<port>) }} 2>&1)
    subject=$(echo "$result" | grep "subject=" | head -1 | sed 's/.*subject=//')
    issuer=$(echo "$result" | grep "issuer=" | head -1 | sed 's/.*issuer=//')
    verify=$(echo "$result" | grep "Verify return code:" | head -1 | sed 's/.*Verify return code: //')
    if echo "$result" | grep -q "CONNECTED"; then
      echo "TLS_RESULT:{\"product\":\"<role>\",\"port\":<port>,\"status\":\"ok\",\"subject\":\"$subject\",\"issuer\":\"$issuer\",\"verify\":\"$verify\"}"
    else
      echo "TLS_RESULT:{\"product\":\"<role>\",\"port\":<port>,\"status\":\"failed\",\"error\":\"Connection refused or TLS handshake failed\"}"
    fi
  register: <role>_tls_check
  changed_when: false
  failed_when: false

- name: "TLS_OUTPUT <role>"
  ansible.builtin.debug:
    msg: "{{ <role>_tls_check.stdout_lines | select('match', '^TLS_RESULT:') | list }}"
```

This alone only proves the service itself is fine — it says nothing about whether any *other* host trusts it. Do not stop here if the new service has a real peer dependency.

**3. Add a real cross-host trust check for any service this product actually depends on (or that depends on it).**

`playbooks/verify.yml` is a **separate, standalone `ansible-playbook` invocation** from `site.yml` (it's what the "Verify TLS" button/API runs) with `gather_facts: false` in its play header. This means two things that are easy to get wrong:

- `internal_ca_path` (an Ansible **fact**, set by the `base` role's own `set_fact` task) is only defined within the *same* `ansible-playbook` run that included `base` — i.e. `site.yml`. It is **undefined** in `verify.yml`, since `verify.yml` never runs `base`.
- Recomputing it the same way `base` does (branching on `ansible_facts['os_family']`) also fails in `verify.yml`, because `gather_facts: false` means `ansible_facts` is empty there too.

The reliable fix is to sidestep Ansible facts entirely and just check which of the CA's known possible on-disk paths actually exists:

```yaml
- name: Compute internal CA path for cross-host checks
  ansible.builtin.shell: |
    ls /usr/local/share/ca-certificates/internal/internal-ca.crt \
       /etc/pki/ca-trust/source/anchors/internal-ca.crt \
       /usr/local/share/ca-certificates/internal-ca.crt \
       /etc/ca-certificates/trust-source/anchors/internal-ca.crt \
       2>/dev/null | head -1
  register: <role>_verify_ca_path_result
  changed_when: false

- name: Set internal CA path fact
  ansible.builtin.set_fact:
    <role>_verify_ca_path: "{{ <role>_verify_ca_path_result.stdout | trim }}"
```

Then run the actual cross-host check **from this host, against the peer's real address**, verifying against that CA file — not against `127.0.0.1`:

```yaml
- name: "TLS_VERIFY <role>-><peer> cross-host trust"
  ansible.builtin.shell: |
    result=$(echo | openssl s_client -connect {{ product_vars.<peer>_host }}:<peer_port> -CAfile {{ <role>_verify_ca_path }} 2>&1)
    verify=$(echo "$result" | grep "Verify return code:" | head -1 | sed 's/.*Verify return code: //')
    if echo "$result" | grep -q "CONNECTED" && echo "$verify" | grep -q "^0 "; then
      echo "TLS_RESULT:{\"product\":\"<role>-to-<peer>\",\"port\":<peer_port>,\"status\":\"ok\",\"detail\":\"<Peer>'s certificate validated against the shared internal CA from a peer host\",\"verify\":\"$verify\"}"
    else
      echo "TLS_RESULT:{\"product\":\"<role>-to-<peer>\",\"port\":<peer_port>,\"status\":\"failed\",\"detail\":\"<Peer>'s certificate did NOT validate against the shared internal CA from a peer host\",\"verify\":\"$verify\"}"
    fi
  register: <role>_<peer>_trust_check
  changed_when: false
  # Gate the task (fail the play) only if this is a genuine functional
  # dependency — e.g. the product's own DB connection depends on it.
  # Use failed_when: false for a purely advisory/demonstration check.
  failed_when: "'\"status\":\"ok\"' not in <role>_<peer>_trust_check.stdout"
  when: product_vars.<peer>_host is defined

- name: "TLS_OUTPUT <role>-><peer> cross-host trust"
  ansible.builtin.debug:
    msg: "{{ <role>_<peer>_trust_check.stdout_lines | select('match', '^TLS_RESULT:') | list }}"
  when: product_vars.<peer>_host is defined
```

Add a `-starttls <proto>` flag if the peer's port uses STARTTLS rather than TLS-from-the-first-byte (MySQL on 3306 needs `-starttls mysql`; RabbitMQ's AMQPS on 5671 doesn't).

**4. If the dependency is real (not just diagnostic), wire the actual client connection to verify TLS too — not only the check.**

A `TLS_VERIFY` task proves trust is *possible*; it doesn't make the product's real runtime connection use it. For example, Keystone's real MySQL connection string is built as:

```
mysql+pymysql://{{ product_vars.keystone_db_user }}:{{ product_vars.keystone_db_password }}@{{ product_vars.keystone_db_host }}/{{ product_vars.keystone_db_name }}?ssl_ca={{ internal_ca_path }}&ssl_verify_cert=true
```

(`internal_ca_path` is safe to use directly here, since this is built in `main.yml`, which — unlike `verify.yml` — runs in the same `site.yml` play as `base` and so has the fact available.) Whatever library the new product uses for its real peer connection, find its actual TLS-verification parameters (most languages/drivers have one — `ssl_ca`/`ssl_verify_cert` for PyMySQL, `sslmode=verify-full`+`sslrootcert` for PostgreSQL, `-CAfile`/`cacertfile` for RabbitMQ's own config, etc.) and point it at the CA, not just at "TLS enabled."

**5. Rebuild the image before testing.** `playbooks/` is baked into the `ssl-cert-manager` image at build time, not live-mounted — editing files in the repo has no effect on a running container until you rebuild:

```bash
docker compose -f docker/docker-compose.yml build certmanager
docker compose -f docker/docker-compose.yml up -d certmanager
```

Confirm the change actually landed in the image before trusting a test result: `docker exec ssl-cert-manager grep -n "<role>-to-<peer>" /opt/certmanager/playbooks/roles/<role>/tasks/verify.yml`.

**6. Prove it live, with a negative control.** A check that always reports `status: ok` is worthless as proof — you have to show it can actually fail. Stand up the two real hosts (container names must exactly match their `service_role`, since Docker-fallback hosts get their bare role name as both hostname and network alias) and:

```bash
# 1. Build both hosts, confirm PLAY RECAP shows failed=0 for each
docker exec ssl-cert-manager /opt/certmanager/venv/bin/ansible-playbook \
  /opt/certmanager/playbooks/site.yml -i <inventory.ini> --extra-vars @<extra_vars.json> \
  --private-key /data/ssh/id_ed25519

# 2. Run verify.yml, confirm the new "<role>-to-<peer>" TLS_RESULT shows status:ok
docker exec ssl-cert-manager /opt/certmanager/venv/bin/ansible-playbook \
  /opt/certmanager/playbooks/verify.yml -i <inventory.ini> --extra-vars @<extra_vars.json> \
  --limit <role> --private-key /data/ssh/id_ed25519

# 3. Negative control: swap the peer's real cert for one signed by an untrusted CA
openssl req -x509 -newkey rsa:2048 -keyout rogue-ca.key -out rogue-ca.crt -days 1 -nodes -subj "/CN=Rogue Untrusted CA"
openssl req -newkey rsa:2048 -keyout peer-rogue.key -out peer-rogue.csr -nodes -subj "/CN=<peer>.internal"
openssl x509 -req -in peer-rogue.csr -CA rogue-ca.crt -CAkey rogue-ca.key -CAcreateserial \
  -out peer-rogue.crt -days 1 -extfile <(echo "subjectAltName=DNS:<peer>.internal,DNS:target-<peer>,DNS:localhost,IP:127.0.0.1,DNS:<peer>")
docker cp peer-rogue.crt <peer>:<peer's real cert path>
docker cp peer-rogue.key <peer>:<peer's real key path>
docker exec <peer> chown <service_user>:<service_user> <cert path> <key path>
docker exec <peer> systemctl restart <peer's service>

# 4. Rerun verify.yml — confirm the SAME check now shows status:failed
#    (note: if the check uses failed_when: false, the Ansible TASK itself
#    won't show as failed in PLAY RECAP — check the JSON status field, not task result)

# 5. Restore the original cert/key, restart the service again, rerun verify.yml,
#    confirm it flips back to status:ok
```

This exact sequence is what proved `nginx_lb->backend`, `keystone->mysql`, and `keystone->rabbitmq` — a check that only reports `ok` was not accepted as sufficient evidence; the fail case had to be demonstrated too.

**7. Clean up test infrastructure** once done: remove the test containers, any temp cert directories, and any `/tmp/*inventory.ini` / `/tmp/*extra_vars.json` files copied into `ssl-cert-manager` for the test — none of this is part of the actual product/environment and shouldn't be left behind.

#### Common mistakes (all previously hit and fixed on real roles)

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Modifying the generic `/etc/ssl/certs/server.pem` when the product actually reads its cert from a different, product-specific path | Negative control has no effect — the "old" cert is still presented | Check the role's own cert-deploy task (e.g. `grep -A3 "Deploy server certificate" playbooks/roles/<role>/tasks/main.yml`) for the *real* path before assuming |
| Referencing `{{ internal_ca_path }}` directly inside `verify.yml` | `'internal_ca_path' is undefined` | Use the `ls <known paths> | head -1` shell lookup instead (see step 3) |
| Two OS-branch tasks (`when: ansible_facts.os_family == "Debian"` / `"RedHat"`) both using the same `register:` name | The skipped branch's empty result silently overwrites the branch that actually ran, on whichever OS didn't match | Use distinct `register:` names per branch and select between them in the consuming task |
| Assuming `cert_requirements` in `catalogue_service.py` does something functional | New product's TLS silently doesn't work even though the catalogue "declares" it needs `server_tls` | It's UI metadata only — you still have to do steps 1-4 above by hand |
| Treating a same-host `TLS_VERIFY` pass as proof of cross-host trust | A product is assumed "trusted in the environment" when only its own loopback cert was ever checked | Add the explicit cross-host check from step 3 for any real peer dependency |

---

## 11. Certificate Lifecycle Integration

Build Manager tracks every certificate issued during environment provisioning via **cert bindings**. Each binding links an environment, host role, and certificate serial with deployment paths and lifecycle metadata.

### Cert Binding Model

When an environment is built, the provisioner issues certificates and creates bindings:

| Field | Description |
|-------|-------------|
| environment_id | Which environment owns this cert |
| cert_serial | Links to SSL Cert Manager certificate table |
| role | Host role (frontend, backend, mysql, etc.) |
| cert_type | server or client |
| expires_at | Certificate expiry timestamp |
| auto_renew | Whether auto-renewal is enabled (default: true) |
| renewal_count | How many times this binding has been renewed |

### Lifecycle Events

| Event | Action |
|-------|--------|
| Environment built | Certs issued, bindings created with auto_renew=true |
| Cert approaching expiry | Auto-renewed if within 30-day threshold |
| Manual renew | Re-issues cert with same CN/SANs, updates binding |
| Manual rotate | New key pair + new cert |
| Environment destroyed | Bindings deleted, certs marked revoked |
| Environment rebuilt | Old certs revoked, new bindings created |

### Auto-Renewal

Trigger via POST /api/v1/build/certs/auto-renew-check or UI button.
Scans bindings where environment is active, auto_renew=true, expires_at within threshold.

### UI - Cert Lifecycle Page (/bm-certs)

- All Bindings tab: grouped by environment
- Expiring Soon tab: within 30 days
- Actions: Renew, Rotate, Toggle Auto-Renew
- Serial numbers link to certificate detail page

### PKI Posture Dashboard (/bm-pki-posture)

A single, read-only view aggregating cert/CA topology, expiry risk, key strength, auto-renew status, and secret rotation staleness (�14) across every non-destroyed environment � pure aggregation over the same facts already covered above (cert bindings, the `certificates`/`certificate_authorities` tables, `BMSecret`), not a new data model.

```bash
curl http://127.0.0.1:8000/api/v1/build/pki-posture \
  -H "Authorization: Bearer <token>"
```

**Response shape:**
```json
{
  "environments": [
    {
      "environment_id": "...", "environment_name": "prod-01", "environment_status": "active",
      "certs": [
        {
          "role": "mysql", "cert_type": "server", "cert_serial": "...",
          "key_algo": "RSA", "key_size": 2048, "weak_key": false,
          "signing_ca_chain": ["Intermediate CA", "Root CA"],
          "expires_at": "2026-08-15T00:00:00", "risk": "warning",
          "auto_renew": true, "renewal_count": 2
        }
      ]
    }
  ],
  "secrets": [
    {"id": "...", "name": "mysql_root_password", "rotate_every_days": 90, "rotation_due_at": "...", "rotation_overdue": false}
  ],
  "summary": {
    "total_certs": 12, "expired_count": 0, "critical_count": 1, "warning_count": 2,
    "weak_key_count": 0, "secrets_overdue_count": 1
  }
}
```

**Risk buckets** (per cert, by `expires_at`): `expired` (past due), `critical` (=7 days), `warning` (=30 days), `ok`, `unknown` (no expiry recorded) � the same 7/30-day windows the rest of the app's expiry logic already uses.

**Weak key detection:** flags RSA keys below 2048 bits or ECDSA keys below 256 bits � the same minimums `compliance_scanner.py`'s BR-6.1.5 check enforces at issuance; this dashboard surfaces certs that predate that check or were imported from elsewhere.

**Signing chain:** `signing_ca_chain` walks `parent_ca_id` from the immediate signer up to the root, listed leaf-to-root, for a quick topology glance without opening each CA individually.

This is a read-only aggregation � renew/rotate/edit actions live on their existing pages (Cert Lifecycle, Secrets); the dashboard links out to them rather than duplicating the controls.

### Compliance Export (One-Click)

The same aggregation is downloadable as a report, for handing to a security/compliance reviewer without giving them API access:

```bash
curl -O -J http://127.0.0.1:8000/api/v1/build/pki-posture/export/pdf -H "Authorization: Bearer <token>"
curl -O -J http://127.0.0.1:8000/api/v1/build/pki-posture/export/csv -H "Authorization: Bearer <token>"
curl -O -J http://127.0.0.1:8000/api/v1/build/pki-posture/export/markdown -H "Authorization: Bearer <token>"
curl -O -J http://127.0.0.1:8000/api/v1/build/pki-posture/export/json -H "Authorization: Bearer <token>"
```

- **PDF/Markdown** � a formal report: summary counts, one table per environment (role/type/key/weak-key/signing-chain/expiry/risk/auto-renew), and a secret-rotation-status table. PDF rendering uses the same Markdown?weasyprint pipeline as the JAR Analyser's change-report export (`change_report.py`), including the same page styling.
- **CSV** � one flat file for spreadsheet import: a `record_type` column (`cert`/`secret`) distinguishes the two record shapes sharing the column layout, since a compliance CSV is expected to be a single importable file rather than a multi-sheet workbook.
- **JSON** � identical payload to `GET /pki-posture`, just served with a `Content-Disposition: attachment` header so it downloads instead of rendering inline.

**Via UI:** the PKI Posture Dashboard page has PDF/CSV/MD/JSON export buttons in its header.

**Note:** PDF export requires weasyprint's system libraries (`libpango`, `libcairo`, `libgdk-pixbuf`, `fonts-dejavu-core` � all installed in the shipped Docker image). If you're running the backend outside that image, install the equivalent packages for your distro or PDF export will fail with an `OSError` at import time; CSV/Markdown/JSON export have no such dependency.
| backend | 192.168.50.11 |
| mysql | 192.168.50.12 |
| rabbitmq | 192.168.50.13 |
| keystone | 192.168.50.14 |

**User overrides:**
Provide partial or full IP overrides at instantiation:

```json
{
  "ip_overrides": {
    "frontend": "10.0.1.100",
    "mysql": "10.0.1.200"
  }
}
```

Overridden roles use the specified IP. Remaining roles auto-allocate from the pool.

**Docker dev mode fallback:**
When the network pool is not defined or IPs are not routable in the Docker environment, allocation falls back to Docker container hostnames (e.g. `target-frontend`, `target-mysql`). This allows the same templates to work in both dev and production � only the inventory values differ.

### IP Storage

Allocated IPs are stored as a JSON object on the environment record:

```json
{
  "frontend": "192.168.50.10",
  "backend": "192.168.50.11",
  "mysql": "192.168.50.12",
  "rabbitmq": "192.168.50.13",
  "keystone": "192.168.50.14"
}
```

These are passed to Ansible as host vars during build, and used for certificate SAN generation.

### Certificate SANs from IPs

When certificates are issued for an environment, the allocated IP is included in the SAN list along with:
- The hostname pattern (resolved)
- `localhost`
- `127.0.0.1`

This ensures certificates work regardless of whether the service is accessed by hostname or IP.

### Network Isolation

In Docker dev mode, all containers share the `bm-net` bridge network. In production, environments should be on isolated VLANs or subnets. The template's subnet field documents the intended network but does not enforce isolation � that is handled by the underlying infrastructure.

---

## 12. Operations & Health Monitoring

Health checks run per-service on each host in an active environment via SSH. Results are stored and used to update environment status (active vs degraded).

### Running Health Checks
Trigger via POST /api/v1/build/environments/{id}/health-check or the UI button. Checks SSH into each host and runs service-specific commands (systemctl, curl, mysqladmin, rabbitmqctl).

### Service Checks
Build Manager resolves product dependencies automatically using a topological sort (DAG) to determine the correct installation order per host.

### How It Works

When a build is triggered:
1. The provisioner reads the template spec's `products` list per host
2. The orchestrator builds a dependency graph from the product catalogue's `dependencies` field
3. Kahn's algorithm produces a topological ordering � dependencies install before dependants
4. Products are executed in this resolved order via `include_role` in Ansible

### Example

If a host has: `[rabbitmq, erlang, openjdk]`

The catalogue says:
- `rabbitmq` depends on `erlang`
- `erlang` depends on nothing
- `openjdk` depends on nothing

Resolved order: `erlang` ? `openjdk` ? `rabbitmq` (or `openjdk` ? `erlang` ? `rabbitmq` � both valid since erlang and openjdk are independent)

### Viewing Execution Order

**Via API:**
```bash
curl http://127.0.0.1:8000/api/v1/build/environments/<id>/execution-order \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{
  "phases": [
    {"name": "Base Provisioning", "targets": "all"},
    {"name": "Product Deployment", "hosts": [
      {"role": "mq-01", "order": ["erlang", "rabbitmq"]},
      {"role": "db-01", "order": ["mysql"]}
    ]}
  ],
  "dependencies": [
    {"from": "erlang", "to": "rabbitmq", "host": "mq-01"}
  ]
}
```

### Dashboard

The Build Manager dashboard (`/bm`) shows:
- **Environment status breakdown** � active, pending, failed, degraded counts
- **Certificate health** � active certs and expiring-within-30-days count with warning
- **Product count** � total products in catalogue
- **Recent jobs** � last 5 jobs with status and timestamp

**Dashboard stats API:**
```bash
curl http://127.0.0.1:8000/api/v1/build/dashboard-stats \
  -H "Authorization: Bearer <token>"
```

### Product Defaults API

Retrieve the default configuration and schema for any product:
```bash
curl http://127.0.0.1:8000/api/v1/build/catalogue/defaults/redis \
  -H "Authorization: Bearer <token>"
```

Returns the latest version's default_vars, config_schema, ports, cert requirements, and dependencies.

---

## 13. Config Editor

The Config Editor provides an in-browser viewer and editor for all configuration files managed by the Build Manager and SSL Cert Manager. It eliminates the need to SSH into containers or rebuild Docker images to inspect or modify config files.

**UI:** Navigate to Build Manager ? Editor (`/bm-editor`)

**Access:** Admin and Operator roles only.

### Overview

The editor manages 48+ registered config files across 6 categories:

| Category | Contents | Count |
|----------|----------|-------|
| System | `ansible.cfg`, Nginx site config | 2 |
| Playbooks | `site.yml`, `base-provision.yml`, `products.yml`, `verify.yml` | 4 |
| Roles | All Ansible role `tasks/main.yml` and `handlers/main.yml` files | 28 |
| Templates | Jinja2 templates (Nginx, RabbitMQ, Keystone, Uvicorn, cert scripts) | 10 |
| Docker | `docker-compose.build-manager.yml` | 1 |
| Generated | `ansible_inventory.py`, `.master_key`, `.api_key` (read-only) | 3 |

### File Registry

All files are registered in the `bm_config_files` database table. Each entry stores:

- **path** � absolute filesystem path inside the container
- **display_name** � short name shown in the UI
- **category** � grouping (system, playbooks, roles, templates, docker, generated)
- **format** � file type (yaml, json, ini, jinja2, nginx, python, shell, text)
- **purpose** � one-line description of what the file does
- **editable** � whether the file can be modified via the editor

Files are accessed by their registry ID, never by raw path. This prevents path traversal attacks.

### Seeding the Registry

On first use, seed the file registry:

```bash
curl -X POST http://127.0.0.1/api/v1/build/editor/seed \
  -H "X-API-Key: <your-key>"
```

Response: `{"files_added": 48}`

Seeding is idempotent � running it again adds only new files not already registered.

### Using the Editor UI

1. Open **Build Manager ? Editor** in the sidebar
2. The left panel shows all registered files grouped by category
3. Use the search box or category filter buttons to find files
4. Click a file to view its content in the syntax-highlighted code viewer
5. The header shows: file name, path, format badge, editable/read-only status
6. The footer shows file size and line count

**Visual indicators:**
- Format badges: `yaml` (green), `json` (blue), `ini` (yellow), `jinja2` (purple), `nginx` (orange)
- ?? icon = read-only file
- ? red indicator = file does not exist on disk

### Code Viewer

The editor uses CodeMirror 6 for syntax-highlighted file viewing with the One Dark theme.

**Supported language modes:**

| Format | Highlighting | Notes |
|--------|-------------|-------|
| `yaml` | Full YAML syntax | Playbooks, roles, Docker Compose |
| `json` | Full JSON syntax | Config files, API responses |
| `python` | Full Python syntax | Inventory scripts |
| `jinja2` | YAML-based highlighting | Jinja2 templates (mostly YAML/conf content) |
| `shell` | Basic highlighting | Shell scripts, entrypoints |
| `ini` | Plain text | Ansible config, Alembic config |
| `nginx` | Plain text | Nginx configuration |
| `dockerfile` | Plain text | Dockerfiles |

**Features:**
- Line numbers with gutter
- Code folding (click arrows in gutter to collapse YAML/JSON blocks)
- Search/replace: click the ?? Search button or press `Ctrl+F`
- Word wrap toggle: click the ? Wrap button in the toolbar
- Bracket matching (highlights matching pairs)
- Active line highlighting

### Editing & Saving

Files marked `editable=true` can be modified directly in the browser.

**Workflow:**
1. Open a file and click the **?? Edit** button (only shown for editable files)
2. The editor switches to editable mode (yellow "? Editing" indicator in toolbar)
3. Make changes � a yellow dot appears next to the filename indicating unsaved changes
4. Click **? Validate** to syntax-check without saving (shows green tick or red errors with line numbers)
5. Click **?? Save** (or press `Ctrl+S`) � a confirmation dialog appears
6. Confirm to save � the file is validated, backed up, and written atomically
7. Click **Cancel** to discard changes and return to read-only mode

**Validation rules by format:**

| Format | Validator | What it catches |
|--------|-----------|----------------|
| `yaml` | `yaml.safe_load()` | Indentation errors, invalid syntax, duplicate keys |
| `json` | `json.loads()` | Missing commas, unclosed brackets, trailing commas |
| `ini` | `configparser.read_string()` | Missing sections, malformed key=value pairs |
| `jinja2` | `jinja2.Environment().parse()` | Unclosed blocks, invalid expressions, syntax errors |
| `nginx` | � | No validation (plain text save) |
| `shell` | � | No validation (plain text save) |

**Safety features:**
- Pre-save validation � file is rejected if syntax check fails (422 response with error details)
- Backup before overwrite � every save creates `/data/editor-backups/{filename}.bak.{timestamp}`
- Atomic write � content is written to a temp file then renamed (prevents partial writes on crash)
- Unsaved changes warning � navigating to another file prompts "Discard unsaved changes?"
- Confirmation dialog � explicit "Save" confirmation before writing to disk
- Read-only enforcement � files with `editable=false` cannot be saved (403 response)

**Keyboard shortcuts (edit mode):**
- `Ctrl+S` � Save (opens confirmation dialog)
- `Ctrl+F` � Search/replace within file

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/build/editor/files` | List all registered files with metadata |
| `GET` | `/api/v1/build/editor/files?category=roles` | Filter by category |
| `GET` | `/api/v1/build/editor/files/{id}` | Read file content + metadata |
| `GET` | `/api/v1/build/editor/files/{id}/metadata` | Metadata only (no content) |
| `PUT` | `/api/v1/build/editor/files/{id}` | Save file (validates first, creates backup) |
| `POST` | `/api/v1/build/editor/files/{id}/validate` | Validate content without saving |
| `GET` | `/api/v1/build/editor/files/{id}/history` | List version history |
| `GET` | `/api/v1/build/editor/files/{id}/history/{version}` | Get specific version content + diff |
| `POST` | `/api/v1/build/editor/files/{id}/restore/{version}` | Restore file to a previous version |
| `GET` | `/api/v1/build/editor/files/{id}/diff?v1=N&v2=M` | Unified diff between two versions |
| `GET` | `/api/v1/build/editor/files/{id}/help` | Contextual help for the file |
| `GET` | `/api/v1/build/editor/scaffolds` | List available file scaffolds |
| `POST` | `/api/v1/build/editor/scaffolds/{id}/create` | Create files from scaffold template |
| `GET` | `/api/v1/build/editor/files/{id}/actions` | List available post-save actions |
| `POST` | `/api/v1/build/editor/files/{id}/actions/{action_id}` | Execute a post-save action |
| `POST` | `/api/v1/build/editor/seed` | Seed/refresh the file registry (admin) |

### API Examples

**List all files:**
```bash
curl http://127.0.0.1/api/v1/build/editor/files \
  -H "X-API-Key: <your-key>"
```

**Read a specific file:**
```bash
curl http://127.0.0.1/api/v1/build/editor/files/<file-id> \
  -H "X-API-Key: <your-key>"
```

**Validate file content:**
```bash
curl -X POST http://127.0.0.1/api/v1/build/editor/files/<file-id>/validate \
  -H "X-API-Key: <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"content": "---\nkey: value\n"}'
```

Response (valid): `{"valid": true, "errors": []}`

Response (invalid): `{"valid": false, "errors": [{"line": 3, "message": "mapping values are not allowed here"}]}`

**Save a file:**
```bash
curl -X PUT http://127.0.0.1/api/v1/build/editor/files/<file-id> \
  -H "X-API-Key: <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"content": "---\nkey: new_value\n"}'
```

Response: `{"saved": true, "errors": [], "backup": "/data/editor-backups/main.yml.bak.20250120143022"}`

### Version History

Every save automatically records a version. The history panel shows all previous versions with editor, timestamp, and optional comment.

**UI usage:**
1. Open a file and click **?? History** � a slide-out panel appears on the right
2. Click any version to view its content in the editor
3. Click **� Diff** to toggle between content view and unified diff
4. Click **? Restore** to roll back to that version (creates a new version with comment)
5. Click **? Back** to return to the current file content

**How it works:**
- Full content is stored per version (not just diffs) for fast retrieval
- Unified diff is generated on save using Python `difflib`
- Restore creates a new version (non-destructive � the restore itself is versioned)
- Version numbers auto-increment per file starting from 1

**API examples:**

**List version history:**
```bash
curl http://127.0.0.1/api/v1/build/editor/files/<file-id>/history \
  -H "X-API-Key: <your-key>"
```

Response:
```json
[
  {"version": 3, "edited_by": "admin", "edited_at": "2025-01-20T15:30:00", "comment": "Restored from version 1", "has_diff": true},
  {"version": 2, "edited_by": "admin", "edited_at": "2025-01-20T14:30:22", "comment": "", "has_diff": true},
  {"version": 1, "edited_by": "admin", "edited_at": "2025-01-20T14:00:00", "comment": "", "has_diff": true}
]
```

**Get a specific version:**
```bash
curl http://127.0.0.1/api/v1/build/editor/files/<file-id>/history/2 \
  -H "X-API-Key: <your-key>"
```

Response includes `content` (full file at that version) and `diff_patch` (unified diff from previous version).

**Restore a version:**
```bash
curl -X POST http://127.0.0.1/api/v1/build/editor/files/<file-id>/restore/1 \
  -H "X-API-Key: <your-key>"
```

**Diff between two versions:**
```bash
curl "http://127.0.0.1/api/v1/build/editor/files/<file-id>/diff?v1=1&v2=3" \
  -H "X-API-Key: <your-key>"
```

Response: `{"diff": "--- a/path\n+++ b/path\n@@ ...\n", "from_version": 1, "to_version": 3}`

### Contextual Help

The editor includes a built-in help panel with documentation for key configuration files. Help content explains directives, provides examples, and links to related documentation.

**UI usage:**
1. Open a file and click **? Help** in the toolbar � a slide-out panel appears on the right
2. The panel shows: summary, directives table, code examples, and related documentation links
3. Click **? Help** again (or open History) to close the panel

**What's included:**
- Summary of the file's purpose and role in the system
- Directives table with key name, purpose, and default value
- Annotated code examples (copy-paste ready)
- Links to related docs (Ansible docs, product docs, internal guides)

**Files with help content (13):**

| File | Category |
|------|----------|
| `ansible.cfg` | System |
| `/etc/nginx/sites-available/default` | System |
| `site.yml` | Playbooks |
| `base-provision.yml` | Playbooks |
| `roles/base/tasks/main.yml` | Roles |
| `roles/mysql/tasks/main.yml` | Roles |
| `roles/nginx/tasks/main.yml` | Roles |
| `roles/rabbitmq/tasks/main.yml` | Roles |
| `roles/uvicorn/tasks/main.yml` | Roles |
| `rabbitmq.conf.j2` | Templates |
| `nginx.conf.j2` | Templates |
| `uvicorn.service.j2` | Templates |
| `docker-compose.build-manager.yml` | Docker |

Files without pre-populated help show a "No help available" message with a keyboard shortcuts reference.

**Mutual exclusion:** The Help panel and History panel share the same slide-out space � opening one closes the other.

**API:**
```bash
curl http://127.0.0.1/api/v1/build/editor/files/<file-id>/help \
  -H "X-API-Key: <your-key>"
```

Response:
```json
{
  "summary": "Main Ansible configuration file...",
  "directives": [
    {"key": "inventory", "purpose": "Path to dynamic inventory script", "default": "/data/ansible_inventory.py"}
  ],
  "examples": [
    {"title": "Increase SSH timeout", "code": "[defaults]\ntimeout = 60"}
  ],
  "related_docs": [
    "https://docs.ansible.com/ansible/latest/reference_appendices/config.html"
  ]
}
```

Returns 404 with `{"detail": "No help available"}` for files without pre-populated content.

### File Scaffolding

The editor includes scaffolds (file templates) for creating new configuration files without starting from scratch.

**UI usage:**
1. Click **+ New** in the sidebar header
2. Select a scaffold type from the grid
3. Fill in the required variables (role name, service name, etc.)
4. Click **Create** � files are written to disk, registered, and opened in the editor

**Available scaffolds:**

| Scaffold | Creates | Variables |
|----------|---------|----------|
| ?? Ansible Role | `roles/<name>/tasks/main.yml` + `handlers/main.yml` | Role name, description |*
| ?? Jinja2 Template | `roles/<role>/templates/<name>.j2` | Role name, template filename, description |
| ?? Systemd Service | `roles/<role>/templates/<name>.service.j2` | Role name, service name, ExecStart, user |
| ?? Nginx Server Block | `roles/<role>/templates/<name>.j2` | Role name, template filename, server name, upstream port |

\* The Ansible Role scaffold's generated `tasks/main.yml` is an intentional stub (`msg: "TODO: implement {role_name} installation"`), unlike the other three scaffolds, which generate immediately usable content. This is deliberate rather than an oversight: a real install task would have to guess a package name, service name, and config template path from the role name alone, and a wrong guess fails in a more confusing way (mid-playbook-run) than an explicit `TODO`. Edit the generated task before running any playbook that includes this role.

**API:**

**List scaffolds:**
```bash
curl http://127.0.0.1/api/v1/build/editor/scaffolds \
  -H "X-API-Key: <your-key>"
```

**Create from scaffold:**
```bash
curl -X POST http://127.0.0.1/api/v1/build/editor/scaffolds/ansible-role/create \
  -H "X-API-Key: <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"variables": {"role_name": "tomcat", "description": "Apache Tomcat deployment"}}'
```

Response:
```json
{
  "files_created": 2,
  "files": [
    {"id": "...", "path": "/opt/certmanager/playbooks/roles/tomcat/tasks/main.yml", "display_name": "tomcat/tasks/main.yml", "category": "roles", "format": "yaml"},
    {"id": "...", "path": "/opt/certmanager/playbooks/roles/tomcat/handlers/main.yml", "display_name": "tomcat/handlers/main.yml", "category": "roles", "format": "yaml"}
  ]
}
```

### Security

- **RBAC:** Only Admin and Operator roles can access the editor endpoints
- **No arbitrary file access:** Only files registered in `bm_config_files` are accessible
- **Sensitive files hidden:** `.master_key` and `.api_key` return `*** SENSITIVE � content hidden ***` instead of actual content
- **Path traversal prevention:** Files are accessed by UUID, never by client-supplied paths
- **Read-only files:** Generated files and secrets are marked `editable=false` and cannot be modified

### Post-Save Actions

After saving a file, the editor offers contextual actions based on the file type. These appear in a blue bar above the editor content.

**How it works:**
1. Save a file successfully
2. If actions are available for that file, a blue bar appears with action buttons
3. Click an action to execute it � result appears inline (green ? or red ?)
4. Dismiss the bar with ? or it clears automatically when you open another file

**Available actions by file type:**

| File Pattern | Actions |
|-------------|--------|
| Nginx configs (`/etc/nginx/`, `nginx.conf`) | ?? Reload Nginx |
| Ansible playbooks (`.yml` in playbooks dir) | ? Ansible Syntax Check, ?? Run Playbook |
| Role tasks (`/roles/*/tasks/`) | ? Ansible Syntax Check, ?? Re-run Deployment |
| `ansible.cfg` | ? Validate Config |

**Action details:**

| Action | What it does | Timeout |
|--------|-------------|--------|
| Reload Nginx | Runs `nginx -t` (test), then `nginx -s reload` if test passes | 10s |
| Ansible Syntax Check | Runs `ansible-playbook --syntax-check` on the file | 30s |
| Validate Config | Runs `ansible --version` to verify ansible.cfg is parseable | 10s |
| Run Playbook | Submits a Build Manager job to execute the playbook | � |
| Re-run Deployment | Submits a job to run `site.yml` (full base + products) | � |

**API:**

**List actions for a file:**
```bash
curl http://127.0.0.1/api/v1/build/editor/files/<file-id>/actions \
  -H "X-API-Key: <your-key>"
```

Response:
```json
[
  {"id": "validate_ansible", "label": "Ansible Syntax Check", "icon": "?", "type": "local_command", "description": "Run ansible-playbook --syntax-check on this file"},
  {"id": "run_playbook", "label": "Run Playbook", "icon": "??", "type": "submit_job", "description": "Submit a Build Manager job to execute this playbook"}
]
```

**Execute an action:**
```bash
curl -X POST http://127.0.0.1/api/v1/build/editor/files/<file-id>/actions/reload_nginx \
  -H "X-API-Key: <your-key>"
```

Response (success): `{"success": true, "output": "nginx: configuration test passed, reload successful", "error": ""}`

Response (failure): `{"success": false, "output": "nginx: [emerg] unknown directive...", "error": "nginx -t failed � config not reloaded"}`

### File Formats

| Format | Used For | Examples |
|--------|----------|----------|
| `yaml` | Ansible playbooks, roles, Docker Compose | `site.yml`, `roles/base/tasks/main.yml` |
| `ini` | Ansible config, Alembic config | `ansible.cfg` |
| `jinja2` | Ansible templates, cert script generators | `rabbitmq.conf.j2`, `nginx.conf.j2` |
| `nginx` | Nginx configuration | `/etc/nginx/sites-available/default` |
| `python` | Dynamic inventory scripts | `ansible_inventory.py` |
| `text` | Keys, tokens | `.master_key`, `.api_key` |

---

## 14. Secrets Management

### Overview

The Secrets Vault provides encrypted storage for sensitive values (passwords, tokens, connection strings) that are automatically injected into Ansible playbook runs. Secrets are encrypted at rest using Fernet (AES-128-CBC + HMAC) with the same `CERT_MASTER_KEY` used for certificate private keys.

### How It Works

1. Store secrets via the UI (`/bm-secrets`) or API
2. Secrets are encrypted with Fernet before writing to the database
3. When a build/provision job runs, all secrets are decrypted and written to a temporary extra-vars file
4. Ansible receives them as variables prefixed with `vault_` (e.g. a secret named `mysql_root_password` becomes `vault_mysql_root_password`)
5. The temp file is deleted immediately after job execution (success or failure)
6. Secret values never appear in job logs or API list responses

### Secret Categories

| Category | Use Case | Examples |
|----------|----------|----------|
| `database` | DB credentials | MySQL root password, PostgreSQL superuser password |
| `messaging` | Message broker credentials | RabbitMQ admin password, Redis auth token |
| `identity` | Identity service credentials | Keystone admin token, LDAP bind password |
| `tls` | TLS-related secrets | PKCS#12 export passwords, keystore passwords |
| `application` | App-level secrets | API keys, JWT signing keys |
| `other` | Uncategorised | Anything else |

### Using Secrets in Ansible Roles

Secrets are injected as extra-vars with the `vault_` prefix. Reference them in your Ansible roles/templates:

```yaml
# In an Ansible task (e.g. roles/mysql/tasks/main.yml)
- name: Set MySQL root password
  mysql_user:
    name: root
    password: "{{ vault_mysql_root_password }}"
    host: localhost

# In a Jinja2 template (e.g. roles/rabbitmq/templates/rabbitmq.conf.j2)
default_user = admin
default_pass = {{ vault_rabbitmq_admin_password }}
```

The naming convention: secret name `foo_bar` ? Ansible variable `vault_foo_bar`.

### UI Usage

Navigate to **Secrets** in the Build Manager sidebar:

- **Add Secret**: Click "+ Add Secret", provide name (snake_case recommended), value, category, optional linked service and description
- **Reveal**: Click the eye icon to decrypt and display the value (Admin only)
- **Rotate**: Provide a new value � the old value is overwritten immediately
- **Delete**: Permanently removes the secret (Admin only)

See Appendix A's Secrets Endpoints table for the full API reference, including request/response examples.

### Security Notes

- Secrets are encrypted at rest � the `bm_secrets.value_encrypted` column contains only ciphertext
- The encryption key is `CERT_MASTER_KEY` from the environment (Fernet key, base64-encoded)
- The temp extra-vars file is written to `/tmp` with restricted permissions and deleted in a `finally` block
- The `GET /secrets` list endpoint never returns values � only `GET /secrets/{id}` does (Admin role required)
- Rotating a secret overwrites the previous value; there is no version history
- If `CERT_MASTER_KEY` is lost, all stored secrets become unrecoverable

### Rotation Policy (Flagging, Not Auto-Rotation)

A secret can optionally have a `rotate_every_days` policy. This is **deliberately flag-only** � the secret is never rotated automatically. An automatic rotation could break a live service still using the old credential (no coordination with the target host happens), so the policy only:

- Surfaces an "? rotation overdue" badge on the Secrets page once the policy window has passed (measured from `rotated_at`, or `created_at` if it's never been rotated).
- Fires a one-shot notification (`bm_secret_rotation_overdue`, reusing the existing notification system) the first time a secret becomes overdue � a background scanner checks every `BM_SECRET_ROTATION_CHECK_INTERVAL_MINUTES` (default 60), but only notifies once per overdue period, not on every tick.

```bash
# Set a rotation policy when creating a secret
curl -X POST http://127.0.0.1:8000/api/v1/build/secrets \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"name": "mysql_root_password", "value": "...", "rotate_every_days": 90}'

# Clear a policy on an existing secret
curl -X PUT http://127.0.0.1:8000/api/v1/build/secrets/<id> \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"clear_rotation_policy": true}'
```

Actually rotating the secret (`POST /secrets/{id}/rotate`, or providing a `value` on `PUT`) resets the policy's clock and clears the overdue/notified state � there's nothing further to do once you've supplied a new value.

---

## 15. Package Cache (Offline Provisioning)

The package cache pre-downloads all catalogue product packages into the shared Docker volume so that target containers can install software without any internet access during builds. This eliminates `apt update` timeouts, network flakiness failures, and version drift between builds.

Packages are cached **per OS family** � Ubuntu/Debian `.deb` files, RHEL/CentOS `.rpm` files, and Alpine `.apk` files are stored in separate subdirectories and served via the native package manager on each target.

**UI:** Navigate to **Build Manager ? Pkg Cache** (`/bm-pkg-cache`)

**Access:** Admin and Operator roles.

### Why It Exists

Every product role runs a package manager install during provisioning. Without a cache, each build depends on:
- Ubuntu/RHEL/Alpine package mirrors being reachable
- External repos (NodeSource, Erlang Solutions) being available
- DNS resolution working inside the container network

Any of these failing causes a build failure like:
```
fatal: [host-01]: FAILED! => {"msg": "Failed to update apt cache after 5 retries: "}
```

With the cache active, all package installs resolve from a local source at highest priority � no network requests are made.

### How It Works

```
certmanager container (Ubuntu)
  /data/pkg-cache/
    apt/   ? .deb + Packages.gz     (synced from an Ubuntu/Debian inventory host)
    rpm/   ? .rpm + repodata/        (synced from a RHEL/CentOS inventory host)
    apk/   ? .apk + APKINDEX         (synced from an Alpine inventory host)
    bin/   ? Node.js, Go tarballs    (downloaded on certmanager � OS-agnostic)
    manifest.json
         �
         �  (shared Docker volume: certmanager-data)
         ?
target containers (any OS)
  /certmanager-data/pkg-cache/   ? read-only mount
```

**Why sync runs on inventory hosts, not localhost:**
The certmanager container is Ubuntu-based. It can only download `.deb` packages. To cache `.rpm` files for RHEL targets, the sync playbook must SSH into an actual RHEL host and run `dnf download` there. The downloaded packages are written directly into the shared volume, which the RHEL host can write to via the same mount.

**Sync flow per OS family:**
1. The sync job SSHes into the selected inventory host for that OS family
2. Runs the native download command (`apt-get download`, `dnf download --resolve`, `apk fetch`)
3. Packages are saved into `/certmanager-data/pkg-cache/<os>/` on the shared volume
4. A repo index is built (`dpkg-scanpackages`, `createrepo_c`, `apk index`)
5. A manifest fragment is written recording the host, timestamp, and package list

**Build flow:**
1. At the start of every build, the `local_repo` Ansible role runs on each target
2. It detects `ansible_facts.os_family` and checks for the matching cache index
3. If found, it configures the local source at highest priority and runs a fast local-only index update
4. All subsequent package installs resolve from the cache � no internet access required
5. If the cache is absent, a warning is logged and the role exits cleanly (network fallback)

### First-Time Setup

1. Navigate to **Build Manager ? Pkg Cache**
2. In the **Sync Cache** form, select one inventory host per OS family you deploy to:
   - **Ubuntu/Debian** � select any Ubuntu or Debian host from inventory
   - **RHEL/CentOS** � select any RHEL, CentOS, AlmaLinux, or Rocky host (leave blank if unused)
   - **Alpine** � select any Alpine host (leave blank if unused)
3. Click **?? Sync Cache** � you are redirected to the Jobs page
4. Monitor the `Package Cache Sync` job (takes 5�15 minutes per OS family)
5. When complete, the Pkg Cache page shows per-OS status cards with package counts
6. All subsequent builds use the local cache automatically

### Cache Status

The page shows one status card per OS family:

| Status | Meaning |
|--------|---------|
| **? Ready** | Index exists and packages are present � offline provisioning active |
| **?? Incomplete** | Cache directory exists but index is missing � re-run sync |
| **?? Empty** | No sync has been run for this OS family � builds use network |

Click a status card to expand the full list of cached packages for that OS family.

### What Gets Cached

**Ubuntu/Debian (`.deb` packages):**

| Category | Packages |
|----------|----------|
| Base provisioning | `openjdk-17-jre-headless`, `ca-certificates`, `curl`, `gnupg` |
| Python | `python3-pip`, `python3-venv` |
| MySQL | `mysql-server`, `mysql-client` |
| RabbitMQ | `erlang-nox`, `rabbitmq-server` |
| Nginx | `nginx` |
| NFS | `nfs-kernel-server`, `nfs-common` |
| Monitoring | `chrony`, `rsyslog` |
| Security | `ufw`, `fail2ban` |
| Build tools | `build-essential`, `gcc`, `g++`, `make`, `cmake`, `gdb` |
| Databases | `redis-server`, `postgresql`, `postgresql-client`, `memcached` |
| Identity | `slapd`, `ldap-utils`, `keystone`, `apache2`, `libapache2-mod-wsgi-py3` |
| Utilities | `git`, `wget`, `unzip`, `jq`, `net-tools`, `dnsutils`, `htop`, `vim`, `certbot` |

**RHEL/CentOS (`.rpm` packages):**

| Category | Packages |
|----------|----------|
| Base provisioning | `java-17-openjdk-headless`, `ca-certificates`, `curl`, `gnupg2` |
| Python | `python3-pip`, `python3` |
| MySQL | `mariadb-server`, `mariadb` |
| Nginx | `nginx` |
| NFS | `nfs-utils` |
| Monitoring | `chrony`, `rsyslog` |
| Security | `fail2ban` |
| Build tools | `gcc`, `gcc-c++`, `make`, `cmake`, `gdb` |
| Databases | `redis`, `postgresql-server`, `postgresql`, `memcached` |
| Identity | `openldap-servers`, `openldap-clients`, `httpd`, `python3-mod_wsgi` |
| Utilities | `git`, `wget`, `unzip`, `jq`, `net-tools`, `bind-utils`, `htop`, `vim`, `certbot` |

> Note: RHEL uses `mariadb` instead of `mysql-server`, `redis` instead of `redis-server`, and `nfs-utils` instead of `nfs-kernel-server`. Package names differ between OS families � this is why per-OS caching is necessary.

**Alpine (`.apk` packages):**

| Category | Packages |
|----------|----------|
| Base provisioning | `openjdk17-jre-headless`, `ca-certificates`, `curl`, `gnupg` |
| Python | `python3`, `py3-pip` |
| Web | `nginx` |
| Databases | `redis`, `postgresql16`, `memcached` |
| Identity | `openldap`, `openldap-clients` |
| Build tools | `gcc`, `g++`, `make`, `cmake` |
| Utilities | `git`, `wget`, `unzip`, `chrony`, `rsyslog` |

**Binary tarballs (all OS families):**

| Tarball | Architecture | Size |
|---------|-------------|------|
| Node.js 20 | linux-x64 | ~22 MB |
| Node.js 20 | linux-arm64 | ~22 MB |
| Go 1.23.4 | linux-amd64 | ~68 MB |
| Go 1.23.4 | linux-arm64 | ~68 MB |

Binary tarballs are architecture-specific but OS-agnostic � the same tarball works on Ubuntu, RHEL, and Alpine. They are downloaded once on the certmanager container regardless of which OS hosts are selected.

### Offline Install Behaviour by Role

| Role | Debian/Ubuntu | RHEL/CentOS | Alpine |
|------|--------------|-------------|--------|
| `local_repo` | Adds `file:///` apt source, pins priority 1001, runs `apt update` | Adds `/etc/yum.repos.d/local-cache.repo` with `priority=1`, runs `dnf clean metadata` | Prepends local path to `/etc/apk/repositories`, runs `apk update --no-network` |
| `base` | `apt install openjdk-17-jre-headless` | `dnf install java-17-openjdk-headless` | `apk add openjdk17-jre-headless` |
| `python` | `apt install python3-pip python3-venv` | `dnf install python3-pip python3` | `apk add python3 py3-pip` |
| `mysql` | `apt install mysql-server mysql-client` | `dnf install mariadb-server mariadb` | N/A |
| `rabbitmq` | `apt install erlang-nox rabbitmq-server` | Network only (Cloudsmith repo required) | N/A |
| `nginx` | `apt install nginx` | `dnf install nginx` | `apk add nginx` |
| `nodejs` | Extracts from `bin/node-v20-linux-x64.tar.xz` | Extracts from `bin/node-v20-linux-x64.tar.xz` | Extracts from `bin/node-v20-linux-x64.tar.xz` |
| `golang` | Extracts from `bin/go1.23.4.linux-amd64.tar.gz` | Extracts from `bin/go1.23.4.linux-amd64.tar.gz` | Extracts from `bin/go1.23.4.linux-amd64.tar.gz` |

### Adding a New OS Family

To add support for a new OS family (e.g. Arch Linux):

1. Add a new play to `pkg-cache-sync.yml` targeting `{{ sync_arch_host | default('') }}` that runs `pacman -Sw --noconfirm --cachedir /certmanager-data/pkg-cache/pacman <packages>`
2. Add the `Archlinux` case to `local_repo/tasks/main.yml` � configure `/etc/pacman.conf` to include the local cache directory
3. Add `arch_host` parameter to `submit_cache_sync()` in `pkg_cache_service.py`
4. Add `_OS_CACHE['Archlinux']` entry to `pkg_cache_service.py`
5. Add the new API body parameter to the `/build/pkg-cache/sync` endpoint
6. Add the Arch host dropdown to the frontend sync form

### Re-syncing

Re-run the sync periodically to pick up updated package versions. Each OS family is independent � you can re-sync Ubuntu without touching the RHEL cache.

Recommended schedule:
- After adding new products to the catalogue
- Monthly, to pick up security patches
- After any OS version upgrade on target hosts (package names or versions may change)

### Playbook Location

The sync playbook is at `/opt/certmanager/playbooks/pkg-cache-sync.yml`. It contains four plays:
1. Ubuntu/Debian � runs on `sync_ubuntu_host` (skipped if not set)
2. RHEL/CentOS � runs on `sync_rhel_host` (skipped if not set)
3. Alpine � runs on `sync_alpine_host` (skipped if not set)
4. Binary tarballs � always runs on `localhost`

To run manually for a specific OS:
```bash
docker exec ssl-cert-manager \
  ansible-playbook /opt/certmanager/playbooks/pkg-cache-sync.yml \
  --extra-vars '{"sync_ubuntu_host": "target-frontend"}'
```

### Troubleshooting the Cache

**Problem:** Sync job fails with `dpkg-scanpackages: command not found`
- `dpkg-dev` is not installed on the Ubuntu sync host
- The sync playbook installs it automatically � if it fails, run `apt-get install -y dpkg-dev` on the host manually then re-sync

**Problem:** Sync job fails with `createrepo_c: command not found` (RHEL)
- `createrepo_c` is not installed on the RHEL sync host
- Run `dnf install -y createrepo_c` on the host then re-sync

**Problem:** RHEL cache shows 0 packages
- `dnf download` requires the package repos to be configured on the sync host
- Verify the RHEL host has valid repo configuration: `dnf repolist` on the host
- EPEL may be needed for some packages: `dnf install -y epel-release`

**Problem:** Targets still downloading from internet despite cache being ready
- Verify the shared volume is mounted on the target: `docker exec <target> ls /certmanager-data/pkg-cache/apt/Packages.gz`
- If missing, recreate the target containers: `docker compose -f docker-compose.build-manager.yml up -d`
- Check the `local_repo` task output in the job log � it should show "Local apt/rpm/apk cache active"

**Problem:** `apt install` fails with `E: Unable to locate package` despite cache
- The package was not included in the sync download list
- Add it to the `apt_packages` list in `pkg-cache-sync.yml` and re-run sync
- Or temporarily remove the local cache pin on the target: `rm /etc/apt/preferences.d/local-cache && apt update`

**Problem:** RHEL host selected but no RHEL hosts appear in the dropdown
- The inventory host's `os_type` must be one of: `rhel`, `centos`, `almalinux`, `rocky`
- Check the host's OS type in **Build Manager ? Inventory** and update if needed

**Problem:** Node.js or Go tarball missing after sync
- The download failed (network issue or URL changed)
- Check the sync job output for the tarball download tasks
- The nodejs and golang roles fall back to network install automatically when the tarball is absent
- Re-run sync when network is available

### API Endpoints

| Method | Endpoint | Description | Role |
|--------|----------|-------------|------|
| `GET` | `/api/v1/build/pkg-cache/status` | Per-OS cache status, package counts, binary tarball availability | Admin, Operator |
| `POST` | `/api/v1/build/pkg-cache/sync` | Submit a cache sync job with optional per-OS host selection | Admin |

**Get cache status:**
```bash
curl http://127.0.0.1:8000/api/v1/build/pkg-cache/status \
  -H "X-API-Key: <api-key>"
```

Response:
```json
{
  "status": "ready",
  "message": "Cache ready for: Ubuntu/Debian, RHEL/CentOS.",
  "generated_at": "2025-07-15T10:30:00",
  "os_families": {
    "Debian": {
      "os_family": "Debian",
      "label": "Ubuntu/Debian",
      "status": "ready",
      "package_count": 312,
      "synced_at": "2025-07-15T10:30:00",
      "synced_by_host": "target-frontend",
      "packages": ["nginx", "mysql-server", "..."]
    },
    "RedHat": {
      "os_family": "RedHat",
      "label": "RHEL/CentOS",
      "status": "ready",
      "package_count": 287,
      "synced_at": "2025-07-15T10:45:00",
      "synced_by_host": "rhel-host-01",
      "packages": ["nginx", "mariadb-server", "..."]
    },
    "Alpine": {
      "os_family": "Alpine",
      "label": "Alpine",
      "status": "empty",
      "package_count": 0,
      "synced_at": null,
      "synced_by_host": null,
      "packages": []
    }
  },
  "bin": {
    "nodejs_x64": true,
    "nodejs_arm64": false,
    "go_amd64": true,
    "go_arm64": false
  }
}
```

**Trigger a sync:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/pkg-cache/sync \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "ubuntu_host": "target-frontend",
    "rhel_host": "rhel-host-01",
    "alpine_host": ""
  }'
```

All three host fields are optional. Omit or leave blank to skip that OS family. Binaries are always synced regardless.

Response:
```json
{
  "job_id": "<uuid>",
  "status": "pending",
  "message": "Package cache sync job submitted: Package Cache Sync (target-frontend, rhel-host-01)"
}
```

Monitor the job at `GET /api/v1/build/jobs/<job_id>/output` or via the Jobs page.
## 16. Troubleshooting

### SSH Connectivity Issues

**Problem:** Test SSH fails with "Connection refused"
- Verify target container is running: `docker ps | findstr target`
- Check sshd is running inside the container: `docker exec target-frontend service ssh status`
- Verify the container is on the `bm-net` network: `docker network inspect bm-net`

**Problem:** Test SSH fails with "Permission denied"
- Check the SSH public key was copied to the target: `docker exec target-frontend cat /root/.ssh/authorized_keys`
- Verify the shared volume is mounted: the target's entrypoint waits up to 120s for the key file at `/certmanager-data/ssh/id_ed25519.pub`
- Restart the target container if the key was generated after it started

**Problem:** Test SSH fails with "Timeout"
- Verify hostname resolution: `docker exec certmanager ping -c1 target-frontend`
- Check Docker network connectivity between containers
- Ensure no firewall rules blocking port 22 between containers

### Container Issues

**Problem:** Target containers exit immediately
- Check logs: `docker logs target-frontend`
- The entrypoint waits for the SSH key file then execs into systemd � if the certmanager container hasn't started yet, targets will wait (up to 120s then proceed without key)
- Start order: certmanager should start first (generates SSH key), then targets copy it
- Target containers require `privileged: true` and cgroup mounts for systemd to work

**Problem:** `systemctl` not found or services won't start in target containers
- Verify the target image was rebuilt with the systemd Dockerfile: `docker exec target-mysql ps 1` should show `/lib/systemd/systemd`
- Ensure `privileged: true`, `tmpfs: [/run, /run/lock]`, and `/sys/fs/cgroup:/sys/fs/cgroup:rw` are in the compose file
- Rebuild targets: `docker compose -f docker-compose.build-manager.yml build --no-cache`

**Problem:** Certmanager container won't start
- Check logs: `docker logs certmanager`
- Verify the Docker volume exists: `docker volume ls | findstr certmanager`
- Check port conflicts: ports 80 and 8000 must be free

**Problem:** Frontend changes not visible after rebuild
- `docker compose restart` does NOT pick up new images � must use `docker compose up -d` to recreate containers
- Use `--no-cache` flag on build to ensure Vite picks up all source changes: `docker compose build --no-cache certmanager`
- The Docker build uses `npx vite build` (skips TypeScript type checking for speed)

### Certificate & TLS Issues

**Problem:** Browser shows `SEC_ERROR_CERT_NOT_IN_NAME_SPACE` (Firefox) or `ERR_CERT_AUTHORITY_INVALID` (Chrome)
- The signing CA has Name Constraints that don't permit `localhost` or `127.0.0.1`
- Solution: Rebuild the environment using an unconstrained CA (select the ? recommended CA in the dropdown)
- The cert manager UI now shows a pre-flight warning when issuing certs against a constrained CA

**Problem:** RabbitMQ management UI shows certificate error
- Import the CA certificate into your browser's trust store, OR
- Accept the self-signed cert warning (development only)
- Verify the cert was issued by an unconstrained CA: check the issuer CN in the browser cert viewer

### API Issues

**Problem:** 401 Unauthorized on Build Manager endpoints
- Ensure you're authenticated (JWT token or API key in Authorization header)
- Build Manager endpoints require `admin` or `operator` role for write operations
- Read operations (list hosts, get inventory) require any authenticated role

**Problem:** 404 on `/api/v1/build/*` endpoints
- Verify the build manager router is registered (check container logs for route registration)
- Ensure you're using the correct base URL (`http://127.0.0.1:8000/api/v1/build/...`)

### Database Issues

**Problem:** Migration 021 fails
- Check if tables already exist: the migration creates `bm_hosts`, `bm_host_groups`, `bm_host_group_members`, `bm_host_vars`
- Run migrations manually: `docker exec certmanager /opt/certmanager/venv/bin/python -m alembic upgrade head`
- Check migration history: `docker exec certmanager /opt/certmanager/venv/bin/python -m alembic history`

---

## Appendix A � API Reference

### Endpoints With No Current UI Consumer

A full audit (Build Manager Hardening Plan, Stage 8) cross-referenced every endpoint below against the frontend and found no calling code. Each is fully functional and reachable directly via the API � this list exists so a maintainer doesn't mistake "no UI button" for "broken" when reading the tables below. None of these were removed; they're either API-only surface with no UI built yet, or (for the two marked *) plausibly intentional beyond this frontend.

| Path | Method(s) | Why it's unused by the UI |
|---|---|---|
| `/inventory` | GET | Ansible inventory export � consumed by `ansible-playbook` directly (see `ansible_runner.py`), not the web UI |
| `/ssh-key` | GET | SSH public key retrieval � no UI surface displays it |
| `/health/all` | GET | Health across *all* environments � the Health page only checks one environment at a time |
| `/hosts/{host_id}/vars` | GET, POST | Per-host variable CRUD � no host-detail/vars UI exists yet in the Inventory page |
| `/hosts/{host_id}/vars/{var_key}/reveal` | GET | Reveal an encrypted host var � same gap |
| `/hosts/{host_id}/vars/{var_key}` | DELETE | Delete a host var � same gap |
| `/groups/{group_id}` | PUT | Edit group � the Groups tab only supports add/delete |
| `/groups/{group_id}/members` | POST | Add group member � membership is instead set at host-creation time via `group_ids` |
| `/groups/{group_id}/members/{host_id}` | DELETE | Remove group member � same reason |
| `/network-pools/{pool_id}` | PUT | Edit pool � the Pools tab only supports add/delete |
| `/catalogue/{product_id}` | GET | Single-product lookup � the UI filters the already-fetched `GET /catalogue` list client-side instead |
| `/catalogue/defaults/{product_name}` | GET | Default vars/config schema for a product � no consumer yet |
| `/templates/{template_id}/versions/{version}` | GET | Single version lookup � only the `.../export` variant is used |
| `/environments/{env_id}/certs` | GET | Certs for one environment � the UI reads them off the environment-detail payload instead |
| `/environments/{env_id}/bindings` | GET | Cert bindings for one environment � the UI uses the global `/certs/bindings` list instead |
| `/environments/{env_id}/provision-status` | GET | Provisioning status (certs/JKS per host) � no consumer yet |
| `/environments/{environment_id}/execution-order` | GET | DAG execution order for an environment's products � no consumer yet |
| `/editor/files/{file_id}/metadata` | GET | File metadata without content � the editor always fetches the full file instead |
| `/editor/files/{file_id}/diff` | GET | Diff between two file versions � no diff viewer wired up yet (history/restore exist) |
| `/environments/{env_id}/provision` * | POST | Documented alias for `/environments/{env_id}/build` � the frontend always calls `build` directly; this alias may exist for external/scripted API consumers |
| `/jobs/{job_id}/stream` * | GET | SSE job output stream � the frontend has an unused `EventSource` reference and an inline comment noting it deliberately switched to polling `GET /jobs/{id}/output` instead, since SSE doesn't easily support auth headers |

### Inventory Endpoints

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `POST` | `/api/v1/build/hosts` | Add host | Admin, Operator |
| `GET` | `/api/v1/build/hosts` | List hosts | Any authenticated |
| `GET` | `/api/v1/build/hosts/{id}` | Get host detail | Any authenticated |
| `PUT` | `/api/v1/build/hosts/{id}` | Update host | Admin, Operator |
| `DELETE` | `/api/v1/build/hosts/{id}` | Delete host | Admin, Operator |
| `POST` | `/api/v1/build/hosts/{id}/test` | Test SSH connectivity | Admin, Operator |
| `POST` | `/api/v1/build/hosts/{id}/vars` | Set host variable | Admin, Operator |
| `DELETE` | `/api/v1/build/hosts/{id}/vars/{key}` | Delete host variable | Admin, Operator |
| `POST` | `/api/v1/build/groups` | Create group | Admin, Operator |
| `GET` | `/api/v1/build/groups` | List groups | Any authenticated |
| `PUT` | `/api/v1/build/groups/{id}` | Update group | Admin, Operator |
| `DELETE` | `/api/v1/build/groups/{id}` | Delete group | Admin, Operator |
| `GET` | `/api/v1/build/inventory` | Export Ansible inventory JSON | Admin, Operator |
| `GET` | `/api/v1/build/ssh-key` | Get SSH public key | Admin |

### Template Endpoints (Stage 2)

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `POST` | `/api/v1/build/templates` | Create template | Admin, Operator |
| `GET` | `/api/v1/build/templates` | List templates | Any authenticated |
| `GET` | `/api/v1/build/templates/{id}` | Get template + current version | Any authenticated |
| `PUT` | `/api/v1/build/templates/{id}` | Save new version | Admin, Operator |
| `GET` | `/api/v1/build/templates/{id}/versions` | List versions | Any authenticated |
| `GET` | `/api/v1/build/templates/{id}/versions/{v}/export` | Export as YAML | Any authenticated |
| `POST` | `/api/v1/build/templates/import` | Import from YAML | Admin, Operator |
| `DELETE` | `/api/v1/build/templates/{id}` | Delete template | Admin |

### Environment Endpoints (Stage 2)

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `POST` | `/api/v1/build/environments` | Instantiate from template | Admin, Operator |
| `GET` | `/api/v1/build/environments` | List environments | Any authenticated |
| `GET` | `/api/v1/build/environments/{id}` | Environment detail | Any authenticated |
| `POST` | `/api/v1/build/environments/{id}/build` | Execute full build | Admin, Operator |
| `POST` | `/api/v1/build/environments/{id}/destroy` | Destroy environment | Admin, Operator |
| `POST` | `/api/v1/build/environments/{id}/rebuild` | Destroy + rebuild | Admin, Operator |
| `POST` | `/api/v1/build/environments/{id}/provision` | Alias for build | Admin, Operator |
| `GET` | `/api/v1/build/environments/{id}/provision-status` | Provisioning status | Any authenticated |
| `GET` | `/api/v1/build/environments/{id}/certs` | List environment certs | Any authenticated |
| `POST` | `/api/v1/build/environments/{id}/verify` | Run TLS verification | Admin, Operator |
| `GET` | `/api/v1/build/environments/{id}/verify-results` | Get TLS verification results | Any authenticated |

### Job Endpoints (Stage 2)

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `POST` | `/api/v1/build/jobs` | Submit job | Admin, Operator |
| `GET` | `/api/v1/build/jobs` | List jobs | Any authenticated |
| `GET` | `/api/v1/build/jobs/{id}` | Job detail | Any authenticated |
| `GET` | `/api/v1/build/jobs/{id}/output` | Job output (incremental with `?after=N`) | Any authenticated |
| `GET` | `/api/v1/build/jobs/{id}/stream` | SSE real-time output stream | Any authenticated |
| `POST` | `/api/v1/build/jobs/{id}/cancel` | Cancel job | Admin, Operator |
| `DELETE` | `/api/v1/build/jobs/{id}` | Delete job record | Admin |

### Product Catalogue Endpoints (Stage 4)

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `GET` | `/api/v1/build/catalogue` | List products (optional `?category=`) | Any authenticated |
| `GET` | `/api/v1/build/catalogue/{id}` | Get product with versions | Any authenticated |
| `POST` | `/api/v1/build/catalogue` | Create custom product | Admin |
| `PUT` | `/api/v1/build/catalogue/{id}` | Update product | Admin |
| `DELETE` | `/api/v1/build/catalogue/{id}` | Delete product (if unused) | Admin |
| `POST` | `/api/v1/build/catalogue/{id}/versions` | Add product version | Admin |
| `PUT` | `/api/v1/build/catalogue/versions/{id}` | Update version | Admin |
| `DELETE` | `/api/v1/build/catalogue/versions/{id}` | Delete version (if unused) | Admin |
| `POST` | `/api/v1/build/catalogue/check-compatibility` | Check product compatibility | Any authenticated |
| `POST` | `/api/v1/build/catalogue/build-template` | Build template from selections | Admin, Operator |
| `POST` | `/api/v1/build/catalogue/seed` | Seed built-in products | Admin |

### Network Pool Endpoints

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `GET` | `/api/v1/build/network-pools` | List all pools | Any authenticated |
| `POST` | `/api/v1/build/network-pools` | Create pool | Admin |
| `PUT` | `/api/v1/build/network-pools/{id}` | Update pool | Admin |
| `DELETE` | `/api/v1/build/network-pools/{id}` | Delete pool | Admin |
| `GET` | `/api/v1/build/network-pools/{id}/available` | Get available IPs from pool | Admin, Operator |
| `GET` | `/api/v1/build/network-pools/docker-networks` | Discover Docker networks (via Engine API) | Admin |

### Platform & CA Endpoints (Stage 8)

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `GET` | `/api/v1/build/platform` | Auto-detect platform (docker/on-prem/aws) | Any authenticated |
| `GET` | `/api/v1/build/signing-cas` | List CAs with suitability scoring | Any authenticated |
| `GET` | `/api/v1/ca/{id}/check-constraints` | Pre-flight Name Constraints check | Any authenticated |

### Orchestrator & Dashboard Endpoints (Stage 10)

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `GET` | `/api/v1/build/dashboard-stats` | Aggregated dashboard stats (environments, certs, jobs) | Any authenticated |
| `GET` | `/api/v1/build/environments/{id}/execution-order` | DAG execution order for environment products | Any authenticated |
| `GET` | `/api/v1/build/catalogue/defaults/{product_name}` | Default vars and config schema for a product | Any authenticated |


### Certificate Lifecycle Endpoints (Stage 11)

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `GET` | `/api/v1/build/certs/bindings` | List all cert bindings across environments | Any authenticated |
| `GET` | `/api/v1/build/certs/expiring?days=30` | List bindings expiring within threshold | Any authenticated |
| `GET` | `/api/v1/build/environments/{id}/bindings` | List bindings for a specific environment | Any authenticated |
| `POST` | `/api/v1/build/certs/bindings/{id}/renew` | Renew a cert binding (re-issue same CN/SANs) | Admin, Operator |
| `POST` | `/api/v1/build/certs/bindings/{id}/rotate` | Rotate a binding (new key + cert) | Admin, Operator |
| `PATCH` | `/api/v1/build/certs/bindings/{id}/auto-renew?enabled=true` | Toggle auto-renew | Admin, Operator |
| `POST` | `/api/v1/build/certs/auto-renew-check?threshold_days=30` | Trigger bulk auto-renewal check | Admin |

### Secrets Endpoints

See section 14 (Secrets Management) for the full narrative � categories, Ansible `vault_` variable naming, UI usage, and security notes.

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `GET` | `/api/v1/build/secrets` | List all secrets (names only, no values) | Admin, Operator |
| `GET` | `/api/v1/build/secrets/{id}` | Retrieve secret with decrypted value | Admin |
| `POST` | `/api/v1/build/secrets` | Store a new encrypted secret | Admin, Operator |
| `PUT` | `/api/v1/build/secrets/{id}` | Update secret value or metadata | Admin, Operator |
| `POST` | `/api/v1/build/secrets/{id}/rotate` | Rotate secret (provide new value) | Admin, Operator |
| `DELETE` | `/api/v1/build/secrets/{id}` | Delete a secret | Admin |

**Create a secret:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/secrets \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mysql_root_password",
    "value": "S3cur3P@ss!",
    "category": "database",
    "linked_service": "mysql",
    "description": "Root password for target-mysql"
  }'
```

**List secrets (values hidden):**
```bash
curl http://127.0.0.1:8000/api/v1/build/secrets \
  -H "X-API-Key: <api-key>"
```

Response:
```json
[
  {
    "id": "8f14e45f-ceea-467e-adc3-b1cca95f3f36",
    "name": "mysql_root_password",
    "category": "database",
    "linked_service": "mysql",
    "description": "Root password for target-mysql",
    "created_by": "admin",
    "rotated_at": null,
    "created_at": "2026-01-15T10:00:00Z",
    "masked_value": "S3�����!"
  }
]
```

**Reveal a secret (Admin only):**
```bash
curl http://127.0.0.1:8000/api/v1/build/secrets/8f14e45f-ceea-467e-adc3-b1cca95f3f36 \
  -H "X-API-Key: <api-key>"
```

Response includes `"value": "S3cur3P@ss!"` in place of `masked_value`.

**Rotate a secret:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/build/secrets/8f14e45f-ceea-467e-adc3-b1cca95f3f36/rotate \
  -H "X-API-Key: <api-key>" \
  -H "Content-Type: application/json" \
  -d '{"value": "N3wS3cur3P@ss!"}'
```


### Package Cache Endpoints

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `GET` | `/api/v1/build/pkg-cache/status` | Cache status, deb count, tarball availability, last sync time | Admin, Operator |
| `POST` | `/api/v1/build/pkg-cache/sync` | Submit a cache sync job | Admin |

### Health & Observability Endpoints (Stage 13)

| Method | Path | Description | Role |
|--------|------|-------------|------|
| `GET` | `/api/v1/build/health/all` | Health results across all active environments | Any authenticated |
| `GET` | `/api/v1/build/environments/{id}/health` | Cached health results for an environment | Any authenticated |
| `POST` | `/api/v1/build/environments/{id}/health-check` | Trigger health checks (SSH into hosts) | Admin, Operator |
| `GET` | `/api/v1/build/environments/{id}/drift` | Drift report (deployed vs template spec) | Any authenticated |

### Health Check Details

Service-specific checks run via SSH:
- **nginx**: `systemctl is-active nginx` + `curl -sk https://localhost/`
- **mysql**: `systemctl is-active mysql` + `mysqladmin ping`
- **rabbitmq**: `systemctl is-active rabbitmq-server` + `rabbitmqctl status`
- **keystone**: `systemctl is-active apache2` + `curl -sk https://localhost:5000/v3/`
- **uvicorn**: `systemctl is-active uvicorn` + `curl -sk https://localhost:8000/health`

Results update environment status: all healthy ? `active`, any down ? `degraded`.

### Drift Detection

The drift report checks:
1. **Missing certs** � host roles in template spec without cert bindings
2. **Expired certs** � bindings with past expiry dates
3. **Expiring certs** � bindings expiring within 7 days
4. **Template outdated** � environment running an older template version than current

Severity levels: `critical`, `high`, `warning`, `info`


---
