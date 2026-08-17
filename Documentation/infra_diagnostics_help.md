# Infrastructure Diagnostics — Help Guide

> **Status:** Phases 1–4 fully implemented.

---

## Table of Contents

- [1. What is Infrastructure Diagnostics?](#1-what-is-infrastructure-diagnostics)
- [2. Supported Services](#2-supported-services)
- [3. API Reference](#3-api-reference)
- [4. MySQL Questionnaire](#4-mysql-questionnaire)
- [5. RabbitMQ Questionnaire](#5-rabbitmq-questionnaire)
- [6. Keystone Questionnaire](#6-keystone-questionnaire)
- [7. Parameterised Questions](#7-parameterised-questions)
- [8. Offline Use — Markdown Export](#8-offline-use--markdown-export)
- [9. Analysis Engine](#9-analysis-engine)
- [10. Run Persistence](#10-run-persistence)
- [11. Frontend UI (Phase 4)](#11-frontend-ui-phase-4)

---

## 1. What is Infrastructure Diagnostics?

Infrastructure Diagnostics is a guided questionnaire tool for collecting structured diagnostic evidence from infrastructure components — MySQL, RabbitMQ, and Keystone — when a service failure is suspected to originate at the infrastructure level rather than the application level.

The tool presents the operator with a series of commands to run on the target system, collects the pasted output, and analyses it automatically to produce a structured findings report with severity ratings and fix steps.

**It is standalone by default** — no JAR report is required. However, when a JAR report is available, it can optionally be supplied as context to pre-fill parameter prompts and enable cross-reference checks comparing application config against infrastructure evidence.

### How it differs from JAR Analyser manual collection

| | JAR Analyser Manual Collection | Infrastructure Diagnostics |
|---|---|---|
| Target | Java application host | Infrastructure component (MySQL server, RabbitMQ broker, Keystone service) |
| Scope | Application-layer evidence (JVM, service config, SSL config) | Infrastructure-layer evidence (DB grants, broker vhost permissions, Keystone endpoint catalogue) |
| Requires a JAR report | Yes — scoped to a specific report | No — standalone by default |
| JAR report context | N/A | Optional — pre-fills parameters, enables cross-reference checks |

---

## 2. Supported Services

Three services are supported. Each has a dedicated questionnaire covering service status, SSL/TLS, service-specific configuration, and connectivity.

| Service | ID | Sections | Items | Required Items |
|---|---|---|---|---|
| MySQL | `mysql` | 4 | 15 | 9 |
| RabbitMQ | `rabbitmq` | 4 | 17 | 10 |
| Keystone (OpenStack Identity) | `keystone` | 4 | 16 | 11 |

Retrieve the live counts at any time:

```
GET /api/v1/infra-diagnostics/services
```

---

## 3. API Reference

All endpoints require authentication. Any role (`admin`, `operator`, `auditor`, `readonly`) may access read endpoints. `POST /{service}/analyse` requires `admin` or `operator`.

### Endpoint Summary

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/infra-diagnostics/services` | List supported services with metadata |
| `GET` | `/api/v1/infra-diagnostics/{service}/questionnaire` | Get questionnaire (optional `?report_id=` for pre-fill) |
| `GET` | `/api/v1/infra-diagnostics/{service}/questionnaire/markdown` | Get questionnaire as Markdown |
| `POST` | `/api/v1/infra-diagnostics/{service}/analyse` | Submit responses, run analysis, persist run |
| `GET` | `/api/v1/infra-diagnostics/runs` | List stored runs |
| `GET` | `/api/v1/infra-diagnostics/runs/{run_id}` | Get a stored run with full findings and responses |
| `GET` | `/api/v1/infra-diagnostics/runs/{run_id}/markdown` | Export a stored run as Markdown |

---

### GET /api/v1/infra-diagnostics/services

Returns the list of supported services with display metadata and live question counts.

**Response 200:**
```json
[
  {
    "id": "mysql",
    "display_name": "MySQL",
    "description": "MySQL database server — connectivity, SSL/TLS, user permissions, replication",
    "icon": "database",
    "section_count": 4,
    "question_count": 15
  },
  {
    "id": "rabbitmq",
    "display_name": "RabbitMQ",
    "description": "RabbitMQ message broker — service status, SSL/TLS, vhost permissions, queue health",
    "icon": "message-square",
    "section_count": 4,
    "question_count": 17
  },
  {
    "id": "keystone",
    "display_name": "Keystone",
    "description": "OpenStack Keystone identity service — token endpoint, SSL/TLS, service accounts, endpoint catalogue",
    "icon": "key",
    "section_count": 4,
    "question_count": 16
  }
]
```

---

### GET /api/v1/infra-diagnostics/{service}/questionnaire

Returns the full structured questionnaire for the specified service.

`{service}` must be one of: `mysql`, `rabbitmq`, `keystone`. Returns **404** for unknown values.

**Query params:**
- `report_id` (optional) — if supplied, the response includes a `prefill` field containing parameter values extracted from the report's configuration. If the report is not found, the questionnaire is returned without prefill.

**Response 200:**
```json
{
  "service": "mysql",
  "display_name": "MySQL",
  "total_sections": 4,
  "total_items": 15,
  "required_items": 9,
  "sections": [
    {
      "id": "mysql.service_status",
      "title": "Service Status",
      "description": "Confirm the MySQL daemon is running and collect version and log information.",
      "items": [
        {
          "id": "mysql.service_status",
          "label": "MySQL service status",
          "context": "Confirms whether the MySQL daemon is running and shows recent state transitions.",
          "command": "systemctl status mysql --no-pager -l 2>/dev/null || systemctl status mysqld --no-pager -l 2>/dev/null",
          "input_type": "command_output",
          "required": true
        }
      ]
    }
  ],
  "prefill": {
    "mysql.param.service_user": "ecs_app",
    "mysql.param.host": "db-host-01"
  }
}
```

**Item fields:**

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable dot-namespaced identifier (e.g. `mysql.ssl_variables`) |
| `label` | string | Readable name shown in the UI |
| `context` | string | Why this item matters |
| `command` | string \| null | Exact shell command to run. `null` for parameter prompt items |
| `input_type` | string | `command_output` or `text` |
| `required` | boolean | Whether a response is required for a complete submission |

Items with `input_type: "text"` and `command: null` are **parameter prompts** — the operator supplies a value that is substituted into subsequent command strings in the same section (see [Section 7](#7-parameterised-questions)).

---

### GET /api/v1/infra-diagnostics/{service}/questionnaire/markdown

Returns the questionnaire as a Markdown document for offline use. Response is `text/markdown` with `Content-Disposition: attachment`. Filename: `infra-diag-{service}.md`. Returns **404** for unknown service IDs.

---

### POST /api/v1/infra-diagnostics/{service}/analyse

Submit questionnaire responses for analysis. Runs the analysis engine synchronously, persists the run, and returns findings immediately.

Requires `admin` or `operator` role.

**Request body:**
```json
{
  "responses": {
    "mysql.service_status": "● mysql.service\n   Active: active (running) since ...",
    "mysql.ssl_variables": "Variable_name\tValue\nhave_ssl\tDISABLED\nssl_ca\t\nssl_cert\t\nssl_key\t",
    "mysql.user_exists": "user\thost\tplugin\necs_app\t%\tcaching_sha2_password",
    "mysql.param.service_user": "ecs_app",
    "mysql.param.host": "%"
  },
  "label": "MySQL on db-host-01 — post-deployment check",
  "report_id": "uuid-of-jar-report"
}
```

`responses` is a flat map of `item_id → pasted text`. Parameter prompt responses are included in the same map. `label` and `report_id` are optional.

**Response 201:**
```json
{
  "run_id": "uuid",
  "service": "mysql",
  "label": "MySQL on db-host-01 — post-deployment check",
  "created_at": "2025-01-15T14:32:00+00:00",
  "missing_required": ["mysql.user_grants"],
  "summary": {
    "total_findings": 2,
    "critical": 1,
    "high": 1,
    "medium": 0,
    "low": 0,
    "cert_files_analysed": 0,
    "log_items_scanned": 1,
    "ports_checked": 1,
    "missing_required_count": 1,
    "response_count": 5
  },
  "findings": [
    {
      "category": "SSL/TLS",
      "severity": "critical",
      "source": "service_check",
      "service": "mysql",
      "message": "MySQL SSL is disabled (have_ssl = DISABLED). Services configured for SSL connections will fail.",
      "item_id": "mysql.ssl_variables",
      "causes": ["MySQL was not started with SSL configuration."],
      "fix_steps": [
        "Set ssl_cert, ssl_key, ssl_ca in /etc/mysql/my.cnf under [mysqld].",
        "Restart MySQL: systemctl restart mysql",
        "Verify: SHOW VARIABLES LIKE '%ssl%' — have_ssl should be YES."
      ],
      "trigger_line": null,
      "ai_annotations": null
    }
  ],
  "cert_results": [],
  "port_results": [],
  "log_findings": [],
  "ai_summary": null
}
```

**404** if `{service}` is not supported. **422** if `responses` is missing or empty.

---

### GET /api/v1/infra-diagnostics/runs

List stored infrastructure diagnostic runs, newest first.

**Query params:** `service` (filter by service id), `page` (default 1), `page_size` (default 20, max 100)

**Response 200:**
```json
{
  "items": [
    {
      "run_id": "uuid",
      "service": "mysql",
      "label": "MySQL on db-host-01 — post-deployment check",
      "created_at": "2025-01-15T14:32:00+00:00",
      "summary": { "total_findings": 2, "critical": 1, "high": 1, "medium": 0, "low": 0 }
    }
  ],
  "total": 12,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

---

### GET /api/v1/infra-diagnostics/runs/{run_id}

Retrieve a stored run with full findings and submitted responses.

**Response 200:**
```json
{
  "run_id": "uuid",
  "service": "mysql",
  "label": "MySQL on db-host-01 — post-deployment check",
  "created_at": "2025-01-15T14:32:00+00:00",
  "responses": { "mysql.service_status": "...", "mysql.ssl_variables": "..." },
  "findings": [ "...same structure as POST response..." ],
  "cert_results": [],
  "port_results": [{ "item_id": "mysql.port", "port": "3306", "status": "OPEN", "open": true }],
  "log_findings": [],
  "summary": { "total_findings": 2, "critical": 1, "high": 1, "medium": 0, "low": 0 },
  "ai_summary": null
}
```

**404** if run not found.

---

### Reserved AI endpoints (501 stubs)

The following endpoints are reserved for future AI agent integration. They currently return `501 Not Implemented` and are excluded from the API docs schema.

| Method | Path |
|---|---|
| `POST` | `/api/v1/infra-diagnostics/{service}/ai-chat` |
| `POST` | `/api/v1/infra-diagnostics/runs/{run_id}/ai-analyse` |
| `GET` | `/api/v1/infra-diagnostics/runs/{run_id}/ai-summary` |

---

## 4. MySQL Questionnaire

4 sections, 15 items, 9 required.

### Section 1 — Service Status (5 items, 4 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `mysql.service_status` | MySQL service status | yes | command_output |
| `mysql.version` | MySQL version | yes | command_output |
| `mysql.error_log` | MySQL error log (last 100 lines) | yes | command_output |
| `mysql.port` | Port 3306 listening | yes | command_output |
| `mysql.firewall` | Firewall rules for port 3306 | no | command_output |

### Section 2 — SSL / TLS (3 items, 1 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `mysql.ssl_variables` | SSL system variables | yes | command_output |
| `mysql.ssl_cert_info` | SSL certificate details | no | command_output |
| `mysql.ssl_cert_path` | SSL cert file path (if non-default) | no | text |

### Section 3 — User & Permissions (4 items, 4 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `mysql.param.service_user` | Service account username | yes | text (parameter prompt) |
| `mysql.param.host` | Service account host | yes | text (parameter prompt) |
| `mysql.user_exists` | Service account existence | yes | command_output |
| `mysql.user_grants` | Service account grants | yes | command_output |

### Section 4 — Connectivity & Capacity (3 items, 0 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `mysql.max_connections` | Max connections setting | no | command_output |
| `mysql.threads_connected` | Current connection count | no | command_output |
| `mysql.replication_status` | Replication status (if applicable) | no | command_output |

---

## 5. RabbitMQ Questionnaire

4 sections, 17 items, 10 required.

### Section 1 — Service Status (7 items, 5 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `rabbitmq.service_status` | RabbitMQ service status | yes | command_output |
| `rabbitmq.broker_status` | Broker status | yes | command_output |
| `rabbitmq.version` | Broker version | yes | command_output |
| `rabbitmq.error_log` | Error log (last 100 lines) | yes | command_output |
| `rabbitmq.port_amqps` | AMQPS port 5671 listening | yes | command_output |
| `rabbitmq.port_amqp` | AMQP port 5672 listening | no | command_output |
| `rabbitmq.firewall` | Firewall rules for ports 5671/5672 | no | command_output |

### Section 2 — SSL / TLS (3 items, 1 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `rabbitmq.ssl_config` | SSL configuration | yes | command_output |
| `rabbitmq.ca_cert_info` | CA certificate details | no | command_output |
| `rabbitmq.server_cert_info` | Server certificate details | no | command_output |

### Section 3 — Vhost & Permissions (4 items, 4 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `rabbitmq.param.vhost` | Target vhost | yes | text (parameter prompt) |
| `rabbitmq.vhost_list` | Vhost list | yes | command_output |
| `rabbitmq.user_list` | User list | yes | command_output |
| `rabbitmq.permissions` | Permissions on target vhost | yes | command_output |

### Section 4 — Queue & Exchange Health (3 items, 0 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `rabbitmq.queue_list` | Queue list with depth and consumers | no | command_output |
| `rabbitmq.exchange_list` | Exchange list | no | command_output |
| `rabbitmq.connection_list` | Active connections | no | command_output |

---

## 6. Keystone Questionnaire

4 sections, 16 items, 11 required.

### Section 1 — Service Status (6 items, 5 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `keystone.param.keystone_host` | Keystone hostname or IP | yes | text (parameter prompt) |
| `keystone.service_status` | Keystone / Apache service status | yes | command_output |
| `keystone.version` | Keystone / OpenStack client version | yes | command_output |
| `keystone.error_log` | Keystone error log (last 100 lines) | yes | command_output |
| `keystone.port_check` | Token endpoint HTTP status | yes | command_output |
| `keystone.firewall` | Firewall rules for port 5000 | no | command_output |

### Section 2 — SSL / TLS (2 items, 1 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `keystone.live_cert` | Live certificate from endpoint | yes | command_output |
| `keystone.cert_chain` | Full certificate chain | no | command_output |

### Section 3 — Service Account (5 items, 4 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `keystone.param.service_user` | Service account username | yes | text (parameter prompt) |
| `keystone.param.project` | Project / tenant name | yes | text (parameter prompt) |
| `keystone.user_show` | Service account details | yes | command_output |
| `keystone.role_assignments` | Service account role assignments | yes | command_output |
| `keystone.project_show` | Project / tenant details | no | command_output |

### Section 4 — Endpoint Catalogue & Token (3 items, 1 required)

| ID | Label | Required | Input type |
|---|---|---|---|
| `keystone.endpoint_list` | Identity endpoint catalogue | yes | command_output |
| `keystone.token_issue` | Token issuance test | no | command_output |
| `keystone.fernet_keys` | Fernet key directory | no | command_output |

---

## 7. Parameterised Questions

Several questions require operator-supplied values before the command can be shown. These are **parameter prompt** items: `input_type: "text"` with `command: null`.

Parameter prompts appear at the start of the section that needs them. When the operator fills in a parameter prompt, the UI substitutes the value into the `command` strings of subsequent items in the same section before displaying them.

**Example:** Once the operator types `ecs_app` into `mysql.param.service_user`, the `mysql.user_exists` command updates immediately to:

```sql
SELECT user, host, plugin, account_locked FROM mysql.user WHERE user='ecs_app';
```

Parameter prompt responses are submitted in the same `responses` map as command outputs, keyed by their item ID (e.g. `"mysql.param.service_user": "ecs_app"`).

**Parameter prompts by service:**

| Item ID | Substituted into |
|---|---|
| `mysql.param.service_user` | `mysql.user_exists`, `mysql.user_grants` |
| `mysql.param.host` | `mysql.user_grants` |
| `rabbitmq.param.vhost` | `rabbitmq.permissions`, `rabbitmq.queue_list`, `rabbitmq.exchange_list` |
| `keystone.param.keystone_host` | `keystone.port_check`, `keystone.live_cert`, `keystone.cert_chain` |
| `keystone.param.service_user` | `keystone.user_show`, `keystone.role_assignments` |
| `keystone.param.project` | `keystone.role_assignments`, `keystone.project_show` |

When a JAR report is supplied via `?report_id=`, the questionnaire response includes a `prefill` field that pre-populates these prompts:

| Parameter prompt | Extracted from report config |
|---|---|
| `mysql.param.service_user` | `spring.datasource.username` |
| `mysql.param.host` | Host parsed from `spring.datasource.url` |
| `rabbitmq.param.vhost` | `spring.rabbitmq.virtual-host` |
| `keystone.param.keystone_host` | Host parsed from `openstack.auth.url` or `spring.security.oauth2.resourceserver.jwt.issuer-uri` |
| `keystone.param.service_user` | `openstack.credentials.username` |
| `keystone.param.project` | `openstack.credentials.project-name` |

Encrypted (`ENC(...)`) or placeholder (`${...}`) values are skipped silently — the operator fills those in manually.

---

## 8. Offline Use — Markdown Export

Each questionnaire can be exported as a Markdown document for operators who prefer to work offline or share the command list with a colleague before a maintenance window.

```
GET /api/v1/infra-diagnostics/mysql/questionnaire/markdown
GET /api/v1/infra-diagnostics/rabbitmq/questionnaire/markdown
GET /api/v1/infra-diagnostics/keystone/questionnaire/markdown
```

The exported document lists every section and item with the exact command to run, the context explaining why it matters, and a `*(required)*` marker on mandatory items.

**Example excerpt (MySQL):**

```markdown
# Infrastructure Diagnostic Request — MySQL

Run each command on the **MySQL** server and paste the output into the
Infrastructure Diagnostics tool.

## Service Status
_Confirm the MySQL daemon is running and collect version and log information._

### MySQL service status *(required)*
Confirms whether the MySQL daemon is running and shows recent state transitions.

```bash
systemctl status mysql --no-pager -l 2>/dev/null || systemctl status mysqld --no-pager -l 2>/dev/null
```
```

---

## 9. Analysis Engine

The analysis engine runs synchronously when responses are submitted to `POST /{service}/analyse`. It applies shared passes (certificate analysis, port status, log scanning) followed by service-specific checks.

### Findings Schema

Every finding in the `findings` list has this structure:

```json
{
  "category":     "SSL/TLS",
  "severity":     "critical",
  "source":       "service_check",
  "service":      "mysql",
  "message":      "MySQL SSL is disabled (have_ssl = DISABLED). Services configured for SSL connections will fail.",
  "item_id":      "mysql.ssl_variables",
  "causes":       ["MySQL was not started with SSL configuration."],
  "fix_steps":    ["Set ssl_cert, ssl_key, ssl_ca in /etc/mysql/my.cnf under [mysqld]."],
  "trigger_line": null,
  "ai_annotations": null
}
```

| Field | Values |
|---|---|
| `category` | `SSL/TLS`, `Auth`, `Connectivity`, `Configuration`, `Capacity`, `Messaging`, `Replication`, `Service` |
| `severity` | `critical`, `high`, `medium`, `low` |
| `source` | `service_check`, `log_scan`, `cert_analysis`, `port_check`, `cross_reference` |
| `ai_annotations` | Always `null` — reserved for future AI agent integration |

### Shared Passes (all services)

| Pass | Triggered by | Detects |
|---|---|---|
| Certificate analysis | Items whose ID contains `.cert`, `.ssl`, or `.live_cert` | Expired cert, expiring within 30 days |
| Port status | Items ending in `.port`, `.port_amqps`, `.port_amqp`, `.port_check` | Port closed → `Connectivity / high` |
| Log scanning | Items ending in `.error_log`, `.service_status`, `.broker_status` | KB pattern matches (MySQL, RabbitMQ, SSL/TLS entries) |

### MySQL Service-Specific Checks

**SSL Variables (`mysql.ssl_variables`)**

| Condition | Finding |
|---|---|
| `have_ssl = DISABLED` | `SSL/TLS / critical` |
| `have_ssl = YES` but `ssl_cert` empty | `SSL/TLS / high` |

**User Existence (`mysql.user_exists`)**

| Condition | Finding |
|---|---|
| Empty result (no rows) | `Auth / critical` — account does not exist |
| `account_locked = Y` | `Auth / critical` — account is locked |
| `plugin = caching_sha2_password` | `Auth / high` — may be incompatible with older JDBC connectors |

**User Grants (`mysql.user_grants`)**

| Condition | Finding |
|---|---|
| No rows returned | `Auth / critical` — no grants found |
| `GRANT USAGE` only | `Auth / critical` — no database permissions |
| Missing `SELECT` | `Auth / high` |
| Missing `INSERT`/`UPDATE`/`DELETE` | `Auth / medium` |

**Connection Capacity (`mysql.max_connections` + `mysql.threads_connected`)**

| Condition | Finding |
|---|---|
| `Threads_connected` ≥ 90% of `max_connections` | `Capacity / high` |
| `Threads_connected` = `max_connections` | `Capacity / critical` |

**Replication (`mysql.replication_status`)**

| Condition | Finding |
|---|---|
| `Seconds_Behind_Source` > 60 | `Replication / medium` |
| `Last_SQL_Error` non-empty | `Replication / high` |
| `Replica_SQL_Running = No` | `Replication / high` |

**MySQL Cross-Reference Checks** (requires `report_id`)

| Condition | Finding |
|---|---|
| `spring.datasource.url` host ≠ `mysql.param.host` | `Configuration / medium` — may be diagnosing the wrong host |
| HikariCP pool size set and `Threads_connected` near that value | `Capacity / high` — app pool near its configured maximum |

---

### RabbitMQ Service-Specific Checks

**Broker Status (`rabbitmq.broker_status`)**

| Condition | Finding |
|---|---|
| `memory_alarm` present | `Capacity / critical` — broker will block publishers |
| `disk_free_alarm` present | `Capacity / critical` — broker will block publishers |
| RabbitMQ app not in running applications | `Service / critical` |

**SSL Configuration (`rabbitmq.ssl_config`)**

| Condition | Finding |
|---|---|
| No SSL listener found | `SSL/TLS / high` — AMQPS not configured |
| `verify` not set to `verify_peer` | `SSL/TLS / medium` |
| `fail_if_no_peer_cert = false` | `SSL/TLS / low` — mTLS not enforced |

**Vhost Check (`rabbitmq.vhost_list`)**

| Condition | Finding |
|---|---|
| `rabbitmq.param.vhost` not in list | `Configuration / critical` — vhost does not exist |

**User & Permissions (`rabbitmq.user_list` + `rabbitmq.permissions`)**

| Condition | Finding |
|---|---|
| Service user not in user list | `Auth / critical` |
| User not in permissions list for the vhost | `Auth / critical` |

**Queue Health (`rabbitmq.queue_list`)**

| Condition | Finding |
|---|---|
| Any queue with `consumers = 0` and messages > 0 | `Messaging / high` |
| Any queue with `messages > 10000` | `Messaging / medium` |

**RabbitMQ Cross-Reference Checks** (requires `report_id`)

| Condition | Finding |
|---|---|
| `spring.rabbitmq.virtual-host` ≠ `rabbitmq.param.vhost` | `Configuration / high` — vhost mismatch |
| `spring.rabbitmq.ssl.enabled = true` but no SSL listener found | `SSL/TLS / critical` — app expects AMQPS but broker has none |
| `spring.rabbitmq.port = 5672` but only 5671 is open | `Configuration / high` — wrong port |

---

### Keystone Service-Specific Checks

**Token Endpoint (`keystone.port_check`)**

| Condition | Finding |
|---|---|
| HTTP status `503`/`502`/`500` | `Service / critical` |
| HTTP status `000` (curl failed) | `Service / critical` — endpoint unreachable |
| HTTP status `401`/`403` | `Service / high` |

**Service Account (`keystone.user_show`)**

| Condition | Finding |
|---|---|
| `No user with a name or ID` in output | `Auth / critical` — account does not exist |
| `enabled: False` | `Auth / critical` — account is disabled |

**Role Assignments (`keystone.role_assignments`)**

| Condition | Finding |
|---|---|
| Empty result | `Auth / critical` — no role assignments on the project |

**Endpoint Catalogue (`keystone.endpoint_list`)**

| Condition | Finding |
|---|---|
| No identity endpoint in list | `Configuration / critical` |
| Endpoint URL contains `localhost` or `127.0.0.1` | `Configuration / high` — localhost-bound; remote clients cannot reach it |
| Endpoint `enabled: False` | `Configuration / critical` |

**Fernet Keys (`keystone.fernet_keys`)**

| Condition | Finding |
|---|---|
| Directory empty or does not exist | `Configuration / critical` — token issuance will fail |
| Newest key older than 24 hours | `Configuration / medium` — keys may not have been rotated |

**Keystone Cross-Reference Checks** (requires `report_id`)

| Condition | Finding |
|---|---|
| Keystone host in report config ≠ `keystone.param.keystone_host` | `Configuration / medium` — may be diagnosing the wrong host |
| Project name in report config ≠ `keystone.param.project` | `Configuration / medium` — project mismatch |

---

## 10. Run Persistence

Runs are stored in the existing `JarDiagnosticRun` table. The `bundle_filename` column acts as a service discriminator:

| Service | `bundle_filename` |
|---|---|
| MySQL | `[infra:mysql]` |
| RabbitMQ | `[infra:rabbitmq]` |
| Keystone | `[infra:keystone]` |

`GET /api/v1/infra-diagnostics/runs` filters by `bundle_filename LIKE '[infra:%'` to return only infrastructure runs, never JAR analyser runs.

**Column usage:**

| Column | Content |
|---|---|
| `report_id` | FK to the associated JAR report (nullable — most infra runs have no parent report) |
| `run_label` | Operator-supplied label (e.g. `"MySQL on db-host-01 — post-deployment check"`) |
| `report_data` | JSON: `{"responses": {...}, "report_id": "..."}` — full submitted responses |
| `findings_json` | Full findings list (with `ai_annotations: null` on each finding) |
| `summary_json` | Summary counts |
| `cert_results_json` | Per-cert analysis results |
| `port_results_json` | Per-port open/closed results |
| `log_findings_json` | KB matches from log/status text |
| `config_issues_json` | Cross-reference and config issues |

Migration `042_infra_diagnostic_runs` made `report_id` nullable and added `run_label` and `report_data` columns.

---

## 11. Frontend UI (Phase 4)

The UI is integrated into the JAR Analyser tab. Two entry points:

- **From the report browser** — "🔧 Infrastructure Diagnostics" button in the header navigates to the landing page (standalone, no report context)
- **From a JAR report** — "🔧 Diagnose Infrastructure" button on the report header navigates to the landing page with the report ID carried through, enabling parameter pre-fill and cross-reference checks

### InfraDiagnosticsLandingPage

Shows the three service cards (fetched from `GET /services`) with question counts and a Start button each. Below the cards, the last 5 runs across all services are listed with finding counts and a View link. If a `reportId` is in context, an info banner is shown.

### InfraWizardPage

Questionnaire wizard for a single service. Differences from `ManualDiagnosticsPage`:

- Parameter prompt items (`input_type: "text"`, `command: null`) render as single-line text inputs rather than textareas
- Commands containing `<param_name>` placeholders are resolved live as the operator types into parameter prompts
- Optional label field at the top of the wizard
- If `reportId` is supplied and the questionnaire returns `prefill` values, parameter prompts are pre-populated and a dismissible info banner is shown
- Submit payload includes `label` and `report_id`

### InfraRunPage

Findings display for a completed run. Features:

- Summary bar (critical / high / medium / low counts)
- Findings list — each finding is expandable to show causes and fix steps; cross-reference findings are badged
- Port check results table
- Certificate analysis results
- Collapsible responses accordion showing all submitted command outputs
- "⬇ Export Markdown" button calls `GET /runs/{run_id}/markdown`
- Reserved `data-slot="ai-summary"` div for future AI agent integration

### Files

| File | Description |
|---|---|
| `frontend/src/components/jar-analyser/InfraDiagnosticsLandingPage.tsx` | Service selector + recent runs |
| `frontend/src/components/jar-analyser/InfraWizardPage.tsx` | Questionnaire wizard |
| `frontend/src/components/jar-analyser/InfraRunPage.tsx` | Findings display |
| `frontend/src/pages/JarAnalyserPage.tsx` | 3 new view states wired up |
| `frontend/src/components/jar-analyser/ReportBrowser.tsx` | `onInfraDiagnostics` prop + button added |
| `frontend/src/components/jar-analyser/TopLevelReport.tsx` | `onInfraDiagnostics` prop + button added |
