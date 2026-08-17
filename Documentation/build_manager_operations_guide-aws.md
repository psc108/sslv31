# Build Manager — AWS Operations Guide

This guide covers AWS-specific provisioning features of the Build Manager.
Sections 1–16 (on-premises/Docker operations) are in the main
[Build Manager Operations Guide](build_manager_operations_guide.md).

---

## 17. AWS Overview & Concepts

### What This Covers

The Build Manager AWS feature set provisions full application stacks into AWS
using OpenTofu (open-source Terraform fork). It handles:

- VPC, subnets, security groups, NAT gateway, route tables
- EC2 instances (Ubuntu 24.04, IMDSv2 enforced, encrypted EBS)
- Application Load Balancers (ALB) and Network Load Balancers (NLB)
- RDS MySQL / Aurora MySQL / RDS PostgreSQL / Aurora PostgreSQL (managed)
- Route 53 DNS records
- CloudWatch log groups, alarms, dashboards, SNS notifications
- Certificate issuance via the SSL Cert Manager's own CA (no ACM dependency
  for internal services)

### Relationship to On-Premises Build Manager

AWS environments use the same Template and Environment data model as
Docker/SSH environments. The template spec gains an optional `aws` block.
Templates without an `aws` block are unaffected — no breaking change.

### Credential Model

AWS credentials are STS temporary tokens (Access Key ID + Secret Access Key +
Session Token). They are held **in process memory only** — never written to
disk or the database. They are cleared automatically when the container
restarts. The 12-hour STS token lifetime is sufficient for any single
provisioning run.

See **Section 18** for credential setup.

### OpenTofu

OpenTofu 1.8.3 is installed in the container at `/usr/local/bin/tofu`.
State is stored in S3 (`certmanager-tofu-state-<account_id>`).
Locks use DynamoDB (`certmanager-tofu-locks`).
Both are bootstrapped automatically on first use.

### Account & Region

- Account ID: resolved from STS `get-caller-identity` at validation time
- Default region: `eu-west-2` (configurable per template)
- Region is set in the template `aws` block, not per-environment

---

## 18. AWS Credentials

### Overview

Before any AWS operation you must supply STS temporary credentials via the
**AWS credentials not configured** banner on the Environments page or the
dedicated credential form.

Credentials are scoped to the current browser session and the running
container process. They are not shared between users.

### Obtaining Credentials

Run your existing MFA script to get a session token:

```powershell
. C:\Users\<you>\aws-creds.ps1
```

This writes `aws-env-vars.ps1` with the three values. Copy them from there
into the credential form in the UI.

### Entering Credentials in the UI

1. Navigate to **Environments**
2. The orange **⚠ AWS credentials not configured** banner appears at the top
   (only shown when at least one AWS template exists)
3. Click **Configure**
4. Paste:
   - **Access Key ID** — starts with `ASIA`
   - **Secret Access Key**
   - **Session Token** — long `IQoJ...` string
   - **Region** — defaults to `eu-west-2`
5. Click **Save & Validate**

The banner turns green showing account ID and validation time on success.

### API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/build/aws/credentials` | Admin | Store STS credentials |
| `POST` | `/api/v1/build/aws/validate-credentials` | Admin | Validate via STS |
| `GET` | `/api/v1/build/aws/credential-status` | Admin, Operator | Current status |
| `DELETE` | `/api/v1/build/aws/credentials` | Admin | Clear from memory |

### Token Expiry

STS tokens last 12 hours. When a token expires mid-operation the job will
fail with an `ExpiredTokenException`. Re-enter credentials and retry the job.
The credential status banner shows the validation timestamp so you can judge
remaining lifetime.

### Security Notes

- Credentials are never logged, audited, or persisted
- The secret key and session token fields use `type="password"` in the UI
- Only admin role can store or clear credentials; operator role can read status

---

## 19. Product Catalogue — AWS vs Linux Host Products

### Deployment Targets

Every product in the catalogue has a `deployment_targets` field that controls
where it can be used:

| Value | Meaning |
|-------|---------|
| `ec2` | Runs on any Linux host — EC2, bare metal, VM, or Docker container. Installed via Ansible. |
| `rds` | AWS managed service only — provisioned by OpenTofu, no EC2 host involved. |

The label `ec2` is a historical name for "standard Linux host". It applies
equally to on-premises, Docker, and AWS EC2 deployments.

### Template Builder Filtering

The Template Builder (Step 2 — Hosts & Products) filters the product
catalogue sidebar based on the deployment target chosen in Step 1:

- **On-Premises / Docker** — shows only `ec2` products. RDS-only products
  are hidden because there is no AWS account to provision them into.
- **AWS** — shows all products. The sidebar is split into two sections:
  - **Product Catalogue** — all `ec2` (Linux host) products, draggable onto
    EC2 host rows
  - **☁️ AWS Managed Services** — `rds`-only products (Aurora MySQL, RDS
    MySQL, Aurora PostgreSQL, RDS PostgreSQL), draggable onto host rows to
    signal managed database intent

When switching from AWS back to On-Premises in the builder, any `rds`-only
products already assigned to hosts are automatically removed.

### AWS Managed Service Products

| Product name | Display name | Notes |
|-------------|-------------|-------|
| `aurora-mysql` | MySQL (Aurora) | Aurora MySQL 3.x cluster, writer + optional reader |
| `mysql-rds` | MySQL (RDS) | RDS MySQL 8.0 single instance |
| `aurora-postgres` | PostgreSQL (Aurora) | Aurora PostgreSQL 16 cluster |
| `postgres-rds` | PostgreSQL (RDS) | RDS PostgreSQL 16 single instance |

These products have `deployment_targets: ["rds"]`. They cannot be placed on
on-premises or Docker templates — the backend validates this and rejects the
request if attempted.

---

## 20. AWS Template Spec

### The `aws` Block

Add an `aws` block to a template spec to enable AWS provisioning. The block
is optional — omitting it leaves the template as a Docker/SSH-only template.

```json
{
  "aws": {
    "region": "eu-west-2",
    "vpc_cidr": "10.0.0.0/16",
    "az_count": 2,
    "single_nat_gateway": true,
    "create_bastion": false,
    "load_balancers": {
      "alb": {
        "enabled": true,
        "domain_name": "",
        "route53_zone_name": ""
      },
      "nlb": {
        "enabled": false,
        "expose_mysql": false,
        "expose_rabbitmq": false
      }
    },
    "database": {
      "product": "aurora-mysql"
    },
    "storage": {
      "create_app_bucket": false
    },
    "monitoring": {
      "ec2_cpu_threshold": 80,
      "ec2_memory_threshold": 85,
      "log_retention_days": 30,
      "alarm_webhook_url": ""
    }
  }
}
```

### `aws` Block Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `region` | string | AWS region (e.g. `eu-west-2`) |
| `vpc_cidr` | string | VPC CIDR block |
| `az_count` | int | Number of availability zones (1–3) |
| `single_nat_gateway` | bool | Use one NAT GW (cheaper) vs one per AZ |
| `create_bastion` | bool | Provision a bastion EC2 host |
| `load_balancers.alb.enabled` | bool | Create an Application Load Balancer |
| `load_balancers.alb.domain_name` | string | Optional Route 53 FQDN for the ALB |
| `load_balancers.alb.route53_zone_name` | string | Route 53 hosted zone name |
| `load_balancers.nlb.enabled` | bool | Create a Network Load Balancer |
| `load_balancers.nlb.expose_mysql` | bool | NLB TCP listener on port 3306 |
| `load_balancers.nlb.expose_rabbitmq` | bool | NLB TCP listeners on 5671/5672 |
| `database.product` | string | Managed DB product name (see Section 19) |
| `storage.create_app_bucket` | bool | Create a KMS-encrypted S3 app bucket |
| `monitoring.ec2_cpu_threshold` | int | CloudWatch CPU alarm threshold (%) |
| `monitoring.ec2_memory_threshold` | int | CloudWatch memory alarm threshold (%) |
| `monitoring.log_retention_days` | int | CloudWatch log retention in days |
| `monitoring.alarm_webhook_url` | string | Optional webhook for alarm forwarding |

### Host Definitions in AWS Templates

Each host in the `hosts` array maps to one EC2 instance. Three AWS-specific
fields are added per host:

```json
{
  "role": "backend",
  "hostname_pattern": "{{env_name}}-backend",
  "products": [
    { "product": "python", "version": "3.12", "vars": {} },
    { "product": "uvicorn", "version": "0.32", "vars": {} },
    { "product": "nginx",  "version": "1.26",  "vars": {} }
  ],
  "certs": ["server_tls", "client_mtls"],
  "instance_type": "t3.medium",
  "root_volume_gb": 20,
  "az_index": 1
}
```

| Field | Description |
|-------|-------------|
| `instance_type` | EC2 instance type (e.g. `t3.small`, `m6i.large`) |
| `root_volume_gb` | Root EBS volume size in GB (default 20) |
| `az_index` | Which AZ to place this host in (0-based, wraps to `az_count`) |

### Managed Database in the Spec

The `database.product` field in the `aws` block names the managed DB product
from the catalogue. The database is provisioned by OpenTofu — it does **not**
appear as a host in the `hosts` array. Its endpoint is injected into the
Ansible inventory as `rds_endpoint` after `tofu apply` completes.

### Certificate SANs

Every EC2 host cert automatically includes:
- The role name (e.g. `backend`)
- The private IP (resolved after `tofu apply`)
- The Route 53 FQDN (if `load_balancers.alb.domain_name` is set)
- `localhost` and `127.0.0.1` (always)

---

## 21. Building AWS Templates with the Template Builder

### Step 1 — Deployment Target

Select **☁️ AWS (OpenTofu + Ansible)** on the Deployment Target card. This
unlocks the AWS Configuration panel below it.

Fill in the AWS Configuration fields:

| Field | Notes |
|-------|-------|
| Region | AWS region for all resources |
| VPC CIDR | Must not overlap with other environments |
| AZ Count | 2 recommended for non-prod, 3 for prod |
| Single NAT GW | Tick for dev/test to reduce cost |
| Bastion Host | Only needed if SSM is unavailable |
| ALB Domain | Optional — leave blank if no Route 53 zone |
| Route 53 Zone | Must already exist in your account |
| Expose MySQL via NLB | Tick if apps outside the VPC need direct DB access |
| Expose AMQPS via NLB | Tick if external consumers need RabbitMQ |
| App S3 Bucket | Tick if the application needs object storage |

### Step 2 — Hosts & Products

The product catalogue sidebar shows two sections for AWS templates:

- **Product Catalogue** — Linux host products (`ec2` deployment target).
  Drag these onto EC2 host rows.
- **☁️ AWS Managed Services** — RDS/Aurora products. Drag these onto a host
  row to associate a managed database with that role. The host row becomes
  a logical placeholder — OpenTofu provisions the actual managed service,
  not an EC2 instance.

Each host row shows an instance type selector when the deployment target is
AWS. Use this to right-size each role independently.

### Step 3 — Review & Save

The summary shows all hosts, their products, and the AWS configuration.
Save the template — it will appear in the Environments page template dropdown
with a `☁️ AWS` suffix.

---

## 22. Reference Template — AWS Full Stack

A golden-path AWS template is provided out of the box:

**Reference: AWS Full Stack (Frontend + Backend + Aurora MySQL + RabbitMQ + Keystone)**

### What It Provisions

**EC2 Instances (via Ansible):**

| Role | Products | Instance Type | AZ |
|------|----------|---------------|----|
| `frontend` | nginx 1.26, python 3.12, nodejs 20 | t3.small | 0 |
| `backend` | python 3.12, uvicorn 0.32, nginx 1.26 | t3.medium | 1 |
| `rabbitmq` | rabbitmq 3.13 | t3.medium | 0 |
| `keystone` | keystone 2024.2 | t3.small | 1 |

**AWS Managed Services (via OpenTofu):**

| Service | Product | Notes |
|---------|---------|-------|
| Aurora MySQL | `aurora-mysql` 3.x | Writer + optional reader, multi-AZ |
| ALB | — | HTTP→HTTPS redirect, HTTPS→EC2 target groups |
| VPC | — | `10.0.0.0/16`, 2 AZs, single NAT GW |

### Key Differences from the On-Premises Full Stack

| On-Premises | AWS |
|-------------|-----|
| `pkg-cache` NFS host | Not needed — EC2 pulls from public apt repos |
| `mysql` EC2 host | Replaced by Aurora MySQL managed cluster |
| `nginx_lb`, `frontend-lb`, `backend-lb` hosts | Replaced by ALB (OpenTofu) |
| Docker network | VPC with public/private subnets |

### Customising the Template

Clone the reference template via the Template Builder to adjust:
- Instance types per role
- AZ count (increase to 3 for production)
- Switch `aurora-mysql` to `mysql-rds` for a simpler single-instance DB
- Enable NLB if external RabbitMQ consumers are needed
- Add Route 53 domain for the ALB

---

## 23. AWS Provisioning Flow

### Overview

AWS environment provisioning runs in this sequence:

1. **CA pre-flight** — verify a signing CA exists and is not expired
2. **Bootstrap** — create S3 state bucket + DynamoDB lock table (idempotent)
3. **`tofu plan`** — generate and display the execution plan (no changes)
4. **Plan review** — operator reviews plan in the UI before applying
5. **`tofu apply`** — provision VPC, subnets, EC2, RDS, ALB/NLB, Route 53
6. **Certificate issuance** — issue host certs using resolved EC2 IPs/FQDNs
7. **Ansible** — run playbooks against EC2 instances via SSM or SSH

### Job Types

| Job type | Triggered by | Description |
|----------|-------------|-------------|
| `tofu_plan` | Plan button | Generates plan, stores output, no infrastructure changes |
| `tofu_apply` | Apply button | Applies saved plan, provisions/updates infrastructure |
| `tofu_destroy` | Destroy AWS button | Destroys all infrastructure for the environment |
| `ansible` | Build button (post-apply) | Runs Ansible against provisioned EC2 instances |

### Timeouts

| Operation | Typical duration | Recommended timeout |
|-----------|-----------------|---------------------|
| `tofu_plan` | 30–60 s | 5 min |
| `tofu_apply` (EC2 only) | 3–5 min | 15 min |
| `tofu_apply` (with RDS/Aurora) | 10–20 min | 40 min |
| `tofu_apply` (full stack) | 15–40 min | 60 min |
| `tofu_destroy` | 5–15 min | 30 min |

Aurora clusters take 10–20 minutes to become available — this is normal.
Use a 60-minute timeout for templates that include Aurora.

### Destroy Ordering

AWS destroy runs `tofu destroy` to **completion** before the environment DB
row is marked `destroyed`. A failed destroy leaves the environment in
`destroy_failed` status — do not delete the DB row until the infrastructure
is confirmed gone in the AWS console.

---

## 24. Networking

### VPC Layout

Each environment gets its own VPC. The default CIDR is `10.0.0.0/16`.

```
VPC 10.0.0.0/16
├── Public subnets  — ALB, NAT GW (one per AZ)
└── Private subnets — EC2, RDS    (one per AZ)
```

EC2 instances are placed in private subnets. Internet access for package
installation goes via NAT Gateway. Inbound application traffic goes via ALB.

### Security Groups

| SG | Inbound | Outbound |
|----|---------|----------|
| ALB SG | 80, 443 from `0.0.0.0/0` | All to EC2 SG |
| EC2 SG | From ALB SG + NLB SG | All (for NAT) |
| RDS SG | 3306/5432 from EC2 SG | None |
| NLB SG | 3306, 5671, 5672 from `0.0.0.0/0` | All to EC2 SG |

### VPC Flow Logs

VPC flow logs are enabled by default, writing to CloudWatch log group
`/certmanager/<env-name>/vpc-flow-logs`.

---

## 25. Compute (EC2)

### AMIs

| OS | AMI selection |
|----|--------------|
| Ubuntu 24.04 | Latest `ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*` from `099720109477` |

AMIs are resolved at plan time using a `data "aws_ami"` lookup — always
picks the latest patched image.

### Instance Configuration

- IMDSv2 enforced (`http_tokens = "required"`)
- Root volume: gp3, encrypted with AWS-managed key, 20 GB default (configurable per host)
- IAM instance profile grants: SSM Session Manager, CloudWatch agent,
  S3 read access to the artefacts bucket
- `san_include_localhost: true` on all host certs (always on)

### SSM vs SSH

SSM Session Manager is the preferred connection method — no inbound SSH port
required. Ansible uses the `aws_ssm` connection plugin when SSM is available.
SSH is available as fallback if the instance profile lacks SSM permissions.

---

## 26. Load Balancers

### Application Load Balancer (ALB)

Created when `load_balancers.alb.enabled: true` in the template `aws` block.

- HTTP (port 80) → redirect to HTTPS (301)
- HTTPS (port 443) → forward to target group
- TLS certificate: issued by the SSL Cert Manager CA (not ACM)
- Replaces the `nginx_lb` / `frontend-lb` / `backend-lb` hosts used in
  on-premises templates

### Network Load Balancer (NLB)

Created when `load_balancers.nlb.enabled: true`. Used for TCP passthrough to
services that need direct TLS (MySQL, AMQP).

- `expose_mysql: true` → TCP port 3306 → MySQL/Aurora EC2 or RDS endpoint
- `expose_rabbitmq: true` → TCP ports 5671/5672 → RabbitMQ EC2 instances

### Route 53

When `load_balancers.alb.domain_name` and `load_balancers.alb.route53_zone_name`
are both set:

- ALB gets an A alias record: the value of `domain_name`
- This FQDN is injected into Ansible inventory and used as a cert SAN

---

## 27. Database (RDS / Aurora)

### Supported Products

| Catalogue product | Engine | Type | Notes |
|------------------|--------|------|-------|
| `aurora-mysql` | Aurora MySQL 3.x | Cluster | Writer + optional reader, auto-failover |
| `mysql-rds` | MySQL 8.0 | Single instance | Simpler, lower cost |
| `aurora-postgres` | Aurora PostgreSQL 16 | Cluster | Writer + optional reader |
| `postgres-rds` | PostgreSQL 16 | Single instance | Simpler, lower cost |

Set `database.product` in the `aws` block to the catalogue product name.
The database does not appear as a host — it is provisioned entirely by
OpenTofu.

### Security

- `require_secure_transport = ON` enforced via parameter group (MySQL/Aurora)
- `ssl = on` enforced via parameter group (PostgreSQL)
- RDS endpoint injected into Ansible inventory as `rds_endpoint` host var
- DB password stored as a Build Manager Secret, referenced in Ansible vars

### Aurora vs RDS Single Instance

Use Aurora when you need:
- Automatic multi-AZ failover
- Read replicas (add `aurora_instance_count > 1`)
- Auto-scaling storage

Use RDS single instance for:
- Dev/test environments where cost matters
- Simpler operational model
- Faster provisioning (~5 min vs ~15 min for Aurora)

---

## 28. Monitoring (CloudWatch)

### Log Groups

Eight log groups are created per environment:

| Log group | Purpose |
|-----------|---------| 
| `/certmanager/<env>/app` | Application logs |
| `/certmanager/<env>/nginx` | Nginx access/error |
| `/certmanager/<env>/mysql` | MySQL slow query / error |
| `/certmanager/<env>/rabbitmq` | RabbitMQ logs |
| `/certmanager/<env>/system` | OS syslog |
| `/certmanager/<env>/audit` | Audit trail |
| `/certmanager/<env>/vpc-flow-logs` | VPC flow logs |
| `/certmanager/<env>/cloudwatch-agent` | Agent health |

### Alarms

Standard alarms created per environment:

| Alarm | Default threshold |
|-------|------------------|
| EC2 CPU high | > 80% for 5 min (configurable via `ec2_cpu_threshold`) |
| EC2 memory high | > 85% for 5 min (configurable via `ec2_memory_threshold`) |
| EC2 status check failed | ≥ 1 for 1 min |
| ALB 5xx errors | > 10 per min |
| ALB target unhealthy | ≥ 1 for 1 min |
| RDS CPU high | > 80% for 5 min |
| RDS storage low | < 10 GB |

### SNS & Webhooks

An SNS topic is created per environment. Alarms publish to it.
If `monitoring.alarm_webhook_url` is set, a subscription forwards alarm
notifications to that URL. The Build Manager's own webhook endpoint
(`POST /api/v1/build/aws/alarm-webhook`) can receive these and update
environment status to `degraded` automatically.

### CloudWatch Dashboard

A per-environment dashboard is created with widgets for EC2 CPU, ALB
request count, ALB 5xx rate, and RDS CPU. The dashboard URL is shown in
the environment detail **☁️ AWS Infrastructure** tab.

---

## 29. Troubleshooting AWS Environments

### Credentials Expired Mid-Job

**Symptom:** Job fails with `ExpiredTokenException` or `InvalidClientTokenId`.

**Fix:** Re-enter credentials via the banner, then retry the job from the
Jobs page. The retry will pick up the new credentials.

### `tofu apply` Timeout

**Symptom:** Job status `failed` with timeout message, infrastructure
partially created.

**Fix:**
1. Check the AWS console — resources may have been created successfully
   despite the timeout
2. If resources exist, run a `tofu plan` to see current state
3. If state is consistent, mark the environment active manually via the API
4. If state is inconsistent, run `tofu destroy` and start again

### Aurora / RDS Creation Slow

Aurora clusters take 10–20 minutes to become available. This is normal.
Use a 60-minute timeout for templates that include Aurora. RDS single
instance is typically ready in 5–8 minutes.

### EC2 Instance Not Reachable via SSM

**Symptom:** Ansible job fails with SSM connection error.

**Checks:**
1. Instance profile has `AmazonSSMManagedInstanceCore` policy
2. SSM agent is running — check `/certmanager/<env>/cloudwatch-agent` log group
3. Instance is in a private subnet with NAT gateway route to `0.0.0.0/0`
4. Security group allows outbound HTTPS (443) to SSM endpoints

### Destroy Fails

**Symptom:** `tofu_destroy` job fails, environment stuck in `destroy_failed`.

**Fix:**
1. Check the job output for the specific resource that failed
2. Manually delete the resource in the AWS console
3. Re-run destroy — OpenTofu will skip already-deleted resources
4. Do not delete the environment DB row until destroy completes

### State Lock Stuck

**Symptom:** `tofu plan` or `tofu apply` fails with `Error acquiring the state lock`.

**Fix:** Check DynamoDB table `certmanager-tofu-locks` for a stale lock entry.
Delete the lock item for the affected environment's state key. This is safe
if no other operation is actively running against that environment.

### RDS-Only Product on On-Premises Template

**Symptom:** Template save fails with validation error about deployment targets.

**Fix:** RDS products (`aurora-mysql`, `mysql-rds`, etc.) cannot be used in
on-premises or Docker templates. Switch the deployment target to AWS in the
Template Builder Step 1, or replace the managed DB product with the EC2
equivalent (`mysql`).

---

## Appendix B — AWS API Reference

### Credential Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/build/aws/credentials` | Admin | Store STS credentials |
| `POST` | `/api/v1/build/aws/validate-credentials` | Admin | Validate via STS |
| `GET` | `/api/v1/build/aws/credential-status` | Admin, Operator | Current status |
| `DELETE` | `/api/v1/build/aws/credentials` | Admin | Clear from memory |

### Environment Provisioning Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/build/environments/{id}/plan` | Generate OpenTofu plan |
| `POST` | `/api/v1/build/environments/{id}/apply` | Apply saved plan |
| `POST` | `/api/v1/build/environments/{id}/tofu-destroy` | Destroy AWS infrastructure |
| `GET` | `/api/v1/build/environments/{id}/outputs` | Get OpenTofu outputs (IPs, endpoints, ARNs) |

### Alarm Webhook

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/build/aws/alarm-webhook` | Receive CloudWatch alarm notifications |
