"""OpenTofu template generator — converts a Build Manager template spec into .tf files.

Phase 2: networking + compute modules only.
Later phases extend _generate_main() to add lb, database, storage, monitoring modules.
"""

from __future__ import annotations

import json
from pathlib import Path

# Account ID is read from the validated credential store at generation time
_STATE_BUCKET_TMPL = "certmanager-tofu-state-{account_id}"
_LOCK_TABLE = "certmanager-tofu-locks"
_LOGS_BUCKET_TMPL = "certmanager-logs-{account_id}"
_ARTEFACTS_BUCKET_TMPL = "certmanager-artefacts-{account_id}"

# Default instance types by service_role (catalogue aws_defaults takes precedence)
_DEFAULT_INSTANCE_TYPES: dict[str, str] = {
    "frontend":  "t3.small",
    "backend":   "t3.medium",
    "mysql":     "t3.medium",
    "rabbitmq":  "t3.medium",
    "keystone":  "t3.small",
    "bastion":   "t3.micro",
    "generic":   "t3.micro",
}


def generate_tf_files(
    spec: dict,
    environment_name: str,
    ssh_public_key: str,
    account_id: str,
) -> dict[str, str]:
    """Return {filename: content} for the environment workspace."""
    aws = spec.get("aws", {})
    files: dict[str, str] = {}
    files["providers.tf"] = _providers(environment_name, account_id, aws)
    files["variables.tf"] = _variables()
    files["main.tf"] = _main(environment_name, aws)
    files["terraform.tfvars.json"] = json.dumps(
        _tfvars(spec, environment_name, ssh_public_key, aws, account_id),
        indent=2,
    )
    return files


# ---------------------------------------------------------------------------
# providers.tf
# ---------------------------------------------------------------------------

def _providers(environment_name: str, account_id: str, aws: dict) -> str:
    region = aws.get("region", "eu-west-2")
    state_bucket = _STATE_BUCKET_TMPL.format(account_id=account_id)
    return f"""\
terraform {{
  required_version = ">= 1.8.0"

  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}

  backend "s3" {{
    bucket         = "{state_bucket}"
    key            = "build-manager/{environment_name}/terraform.tfstate"
    region         = "{region}"
    dynamodb_table = "{_LOCK_TABLE}"
    encrypt        = true
  }}
}}

provider "aws" {{
  region = var.aws_region

  default_tags {{
    tags = {{
      ManagedBy   = "opentofu"
      Project     = "certmanager"
      Environment = var.environment_name
      CreatedBy   = "build-manager"
    }}
  }}
}}
"""


# ---------------------------------------------------------------------------
# variables.tf
# ---------------------------------------------------------------------------

def _variables() -> str:
    return """\
variable "environment_name" { type = string }
variable "aws_region"       { type = string }
variable "aws_account_id"   { type = string; default = "" }
variable "vpc_cidr"         { type = string; default = "10.0.0.0/16" }
variable "az_count"         { type = number; default = 2 }
variable "single_nat_gateway" { type = bool; default = true }
variable "management_cidrs" { type = list(string); default = [] }
variable "create_bastion"   { type = bool; default = false }
variable "ssh_public_key"   { type = string; sensitive = true }
variable "artefacts_bucket" { type = string; default = "" }
variable "logs_bucket"      { type = string; default = "" }

variable "hosts" {
  description = "Map of host definitions"
  type = map(object({
    os_type        = string
    instance_type  = string
    service_role   = string
    root_volume_gb = number
    az_index       = number
  }))
  default = {}
}

# Load balancer variables
variable "domain_name"               { type = string; default = "" }
variable "subject_alternative_names" { type = list(string); default = [] }
variable "route53_zone_name"         { type = string; default = "" }
variable "acm_certificate_arn"       { type = string; default = "" }
variable "create_nlb"                { type = bool;   default = true }
variable "expose_mysql"              { type = bool;   default = false }
variable "expose_rabbitmq"           { type = bool;   default = false }
variable "create_internal_alb"       { type = bool;   default = false }
variable "enable_deletion_protection" { type = bool;  default = false }
variable "enable_stickiness"         { type = bool;   default = false }

# Database variables
variable "db_engine"                  { type = string; default = null }
variable "db_instance_class"          { type = string; default = "db.t3.medium" }
variable "db_allocated_storage"       { type = number; default = 20 }
variable "db_name"                    { type = string; default = "appdb" }
variable "db_username"                { type = string; default = "admin" }
variable "db_password"                { type = string; sensitive = true; default = "" }
variable "db_multi_az"                { type = bool;   default = false }
variable "db_deletion_protection"     { type = bool;   default = false }
variable "db_skip_final_snapshot"     { type = bool;   default = true }
variable "db_backup_retention_days"   { type = number; default = 7 }
variable "aurora_instance_count"      { type = number; default = 1 }
variable "enable_performance_insights" { type = bool;  default = false }

# Storage variables
variable "create_app_bucket"          { type = bool;   default = false }
variable "app_bucket_versioning"      { type = bool;   default = false }
variable "app_bucket_lifecycle_days"  { type = number; default = 0 }

# Monitoring variables
variable "alarm_webhook_url"          { type = string; default = "" }
variable "log_retention_days"         { type = number; default = 30 }
variable "ec2_cpu_threshold"          { type = number; default = 80 }
variable "ec2_memory_threshold"       { type = number; default = 85 }
variable "ec2_disk_threshold"         { type = number; default = 85 }
variable "alb_5xx_threshold"          { type = number; default = 10 }
variable "alb_latency_threshold_seconds" { type = number; default = 2 }
variable "rds_cpu_threshold"          { type = number; default = 80 }
variable "rds_max_connections"        { type = number; default = 100 }
variable "rds_free_storage_threshold_bytes" { type = number; default = 5368709120 }
"""


# ---------------------------------------------------------------------------
# main.tf — module calls
# ---------------------------------------------------------------------------

def _main(environment_name: str, aws: dict) -> str:
    lb_cfg = aws.get("load_balancers", {})
    alb_cfg = lb_cfg.get("alb", {})
    alb_enabled = alb_cfg.get("enabled", True)
    lb_block = _lb_module_block() if alb_enabled else ""
    lb_outputs = _lb_outputs() if alb_enabled else ""
    db_engine = aws.get("database", {}).get("engine")
    db_block = _db_module_block() if db_engine else ""
    db_outputs = _db_outputs() if db_engine else ""
    storage_cfg = aws.get("storage", {})
    storage_block = _storage_module_block("") if storage_cfg.get("create_app_bucket") else ""
    storage_outputs = _storage_outputs() if storage_cfg.get("create_app_bucket") else ""
    monitoring_block = _monitoring_module_block(alb_enabled, db_engine)
    monitoring_outputs = _monitoring_outputs()
    return f"""\
# Generated by Build Manager — do not edit manually.

module "networking" {{
  source = "/data/tofu/modules/networking"

  environment_name   = var.environment_name
  vpc_cidr           = var.vpc_cidr
  az_count           = var.az_count
  single_nat_gateway = var.single_nat_gateway
  management_cidrs   = var.management_cidrs
}}

module "compute" {{
  source = "/data/tofu/modules/compute"

  environment_name    = var.environment_name
  hosts               = var.hosts
  ssh_public_key      = var.ssh_public_key
  artefacts_bucket    = var.artefacts_bucket
  create_bastion      = var.create_bastion
  management_cidrs    = var.management_cidrs
  private_subnet_ids  = module.networking.private_subnet_ids
  public_subnet_ids   = module.networking.public_subnet_ids
  sg_app_id           = module.networking.sg_app_id
  vpc_id              = module.networking.vpc_id

  depends_on = [module.networking]
}}
{lb_block}{db_block}{storage_block}{monitoring_block}
output "vpc_id"            {{ value = module.networking.vpc_id }}
output "private_ips"       {{ value = module.compute.private_ips }}
output "instance_ids"      {{ value = module.compute.instance_ids }}
output "bastion_public_ip" {{ value = module.compute.bastion_public_ip }}
{lb_outputs}{db_outputs}{storage_outputs}{monitoring_outputs}"""


def _lb_module_block() -> str:
    return """
module "lb" {
  source = "/data/tofu/modules/lb"

  environment_name          = var.environment_name
  vpc_id                    = module.networking.vpc_id
  public_subnet_ids         = module.networking.public_subnet_ids
  sg_alb_id                 = module.networking.sg_alb_id
  sg_internal_alb_id        = module.networking.sg_internal_alb_id
  logs_bucket               = var.logs_bucket
  domain_name               = var.domain_name
  subject_alternative_names = var.subject_alternative_names
  route53_zone_name         = var.route53_zone_name
  acm_certificate_arn       = var.acm_certificate_arn
  create_nlb                = var.create_nlb
  expose_mysql              = var.expose_mysql
  expose_rabbitmq           = var.expose_rabbitmq
  create_internal_alb       = var.create_internal_alb
  private_subnet_ids        = module.networking.private_subnet_ids
  enable_deletion_protection = var.enable_deletion_protection
  enable_stickiness         = var.enable_stickiness
  instances = {
    for k, v in module.compute.instance_ids : k => {
      instance_id  = v
      service_role = var.hosts[k].service_role
    }
  }

  depends_on = [module.compute]
}
"""


def _lb_outputs() -> str:
    return """
output "alb_dns_name"          { value = module.lb.alb_dns_name }
output "alb_arn"               { value = module.lb.alb_arn }
output "nlb_dns_name"          { value = module.lb.nlb_dns_name }
output "internal_alb_dns_name" { value = module.lb.internal_alb_dns_name }
output "acm_certificate_arn"   { value = module.lb.acm_certificate_arn }
output "route53_alb_fqdn"      { value = module.lb.route53_alb_fqdn }
output "route53_nlb_fqdn"      { value = module.lb.route53_nlb_fqdn }
"""


def _db_module_block() -> str:
    return """
module "database" {
  source = "/data/tofu/modules/database"

  environment_name          = var.environment_name
  vpc_id                    = module.networking.vpc_id
  private_subnet_ids        = module.networking.private_subnet_ids
  sg_rds_id                 = module.networking.sg_rds_id
  db_engine                 = var.db_engine
  db_instance_class         = var.db_instance_class
  db_allocated_storage      = var.db_allocated_storage
  db_name                   = var.db_name
  db_username               = var.db_username
  db_password               = var.db_password
  db_multi_az               = var.db_multi_az
  db_deletion_protection    = var.db_deletion_protection
  db_skip_final_snapshot    = var.db_skip_final_snapshot
  db_backup_retention_days  = var.db_backup_retention_days
  aurora_instance_count     = var.aurora_instance_count
  enable_performance_insights = var.enable_performance_insights

  depends_on = [module.networking]
}
"""


def _db_outputs() -> str:
    return """
output "db_endpoint"        { value = module.database.db_endpoint }
output "db_reader_endpoint" { value = module.database.db_reader_endpoint }
output "db_port"            { value = module.database.db_port }
"""


def _storage_module_block(account_id: str) -> str:
    return f"""
module "storage" {{
  source = "/data/tofu/modules/storage"

  environment_name         = var.environment_name
  aws_account_id           = var.aws_account_id
  create_app_bucket        = var.create_app_bucket
  app_bucket_versioning    = var.app_bucket_versioning
  app_bucket_lifecycle_days = var.app_bucket_lifecycle_days
}}
"""


def _storage_outputs() -> str:
    return """
output "app_bucket_name" { value = module.storage.app_bucket_name }
"""


def _monitoring_module_block(alb_enabled: bool, db_engine: str | None) -> str:
    alb_suffix_expr = "module.lb.alb_arn_suffix" if alb_enabled else "\"\""
    db_id_expr = (
        "var.db_engine == \"rds_mysql\" ? \"${var.environment_name}-mysql\" : "
        "var.db_engine == \"aurora_mysql\" ? \"${var.environment_name}-aurora-mysql-0\" : "
        "var.db_engine == \"rds_postgres\" ? \"${var.environment_name}-postgres\" : "
        "var.db_engine == \"aurora_postgres\" ? \"${var.environment_name}-aurora-postgres-0\" : \"\""
    ) if db_engine else "\"\""
    return f"""
module "monitoring" {{
  source = "/data/tofu/modules/monitoring"

  environment_name    = var.environment_name
  aws_region          = var.aws_region
  instance_ids        = module.compute.instance_ids
  alb_arn_suffix      = {alb_suffix_expr}
  db_identifier       = {db_id_expr}
  alarm_webhook_url   = var.alarm_webhook_url
  log_retention_days  = var.log_retention_days
  ec2_cpu_threshold   = var.ec2_cpu_threshold
  ec2_memory_threshold = var.ec2_memory_threshold
  ec2_disk_threshold  = var.ec2_disk_threshold
  alb_5xx_threshold   = var.alb_5xx_threshold
  alb_latency_threshold_seconds = var.alb_latency_threshold_seconds
  rds_cpu_threshold   = var.rds_cpu_threshold
  rds_max_connections = var.rds_max_connections
  rds_free_storage_threshold_bytes = var.rds_free_storage_threshold_bytes

  depends_on = [module.compute]
}}
"""


def _monitoring_outputs() -> str:
    return """
output "sns_topic_arn"    { value = module.monitoring.sns_topic_arn }
output "dashboard_url"    { value = module.monitoring.dashboard_url }
output "log_group_names" { value = module.monitoring.log_group_names }
"""


# ---------------------------------------------------------------------------
# terraform.tfvars.json
# ---------------------------------------------------------------------------

def _tfvars(
    spec: dict,
    environment_name: str,
    ssh_public_key: str,
    aws: dict,
    account_id: str,
) -> dict:
    hosts: dict[str, dict] = {}
    for host in spec.get("hosts", []):
        role = host["role"]
        service_role = host.get("service_role", "generic")
        # instance_type: explicit in spec > catalogue aws_defaults > role default
        instance_type = (
            host.get("instance_type")
            or _DEFAULT_INSTANCE_TYPES.get(service_role, "t3.micro")
        )
        hosts[role] = {
            "os_type":        host.get("os_type", "ubuntu"),
            "instance_type":  instance_type,
            "service_role":   service_role,
            "root_volume_gb": host.get("root_volume_gb", 20),
            "az_index":       host.get("az_index", 0),
        }

    lb_cfg = aws.get("load_balancers", {})
    db_cfg = aws.get("database", {})
    storage_cfg = aws.get("storage", {})
    monitoring_cfg = aws.get("monitoring", {})
    return {
        "environment_name":   environment_name,
        "aws_region":         aws.get("region", "eu-west-2"),
        "aws_account_id":     account_id,
        "vpc_cidr":           aws.get("vpc_cidr", "10.0.0.0/16"),
        "az_count":           aws.get("az_count", 2),
        "single_nat_gateway": aws.get("single_nat_gateway", True),
        "create_bastion":     aws.get("create_bastion", False),
        "management_cidrs":   aws.get("management_cidrs", []),
        "ssh_public_key":     ssh_public_key,
        "hosts":              hosts,
        "artefacts_bucket":   _ARTEFACTS_BUCKET_TMPL.format(account_id=account_id),
        "logs_bucket":        _LOGS_BUCKET_TMPL.format(account_id=account_id),
        # LB variables (step 4.5)
        "domain_name":               lb_cfg.get("alb", {}).get("domain_name", ""),
        "subject_alternative_names": lb_cfg.get("alb", {}).get("subject_alternative_names", []),
        "route53_zone_name":         lb_cfg.get("alb", {}).get("route53_zone_name", ""),
        "acm_certificate_arn":       lb_cfg.get("alb", {}).get("acm_certificate_arn", ""),
        "create_nlb":                lb_cfg.get("nlb", {}).get("enabled", True),
        "expose_mysql":              lb_cfg.get("nlb", {}).get("expose_mysql", False),
        "expose_rabbitmq":           lb_cfg.get("nlb", {}).get("expose_rabbitmq", False),
        "create_internal_alb":       lb_cfg.get("internal_alb", {}).get("enabled", False),
        "enable_deletion_protection": aws.get("enable_deletion_protection", False),
        "enable_stickiness":         aws.get("enable_stickiness", False),
        # Database variables (step 5.3)
        "db_engine":                 db_cfg.get("engine"),
        "db_instance_class":         db_cfg.get("instance_class", "db.t3.medium"),
        "db_allocated_storage":      db_cfg.get("allocated_storage", 20),
        "db_name":                   db_cfg.get("db_name", "appdb"),
        "db_username":               db_cfg.get("username", "admin"),
        "db_password":               db_cfg.get("password", ""),
        "db_multi_az":               db_cfg.get("multi_az", False),
        "db_deletion_protection":    db_cfg.get("deletion_protection", False),
        "db_skip_final_snapshot":    db_cfg.get("skip_final_snapshot", True),
        "db_backup_retention_days":  db_cfg.get("backup_retention_days", 7),
        "aurora_instance_count":     db_cfg.get("aurora_instance_count", 1),
        "enable_performance_insights": db_cfg.get("enable_performance_insights", False),
        # Storage variables (step 5.3)
        "create_app_bucket":          storage_cfg.get("create_app_bucket", False),
        "app_bucket_versioning":      storage_cfg.get("versioning", False),
        "app_bucket_lifecycle_days":  storage_cfg.get("lifecycle_days", 0),
        # Monitoring variables (step 6.2)
        "alarm_webhook_url":          monitoring_cfg.get("alarm_webhook_url", ""),
        "log_retention_days":         monitoring_cfg.get("log_retention_days", 30),
        "ec2_cpu_threshold":          monitoring_cfg.get("ec2_cpu_threshold", 80),
        "ec2_memory_threshold":       monitoring_cfg.get("ec2_memory_threshold", 85),
        "ec2_disk_threshold":         monitoring_cfg.get("ec2_disk_threshold", 85),
        "alb_5xx_threshold":          monitoring_cfg.get("alb_5xx_threshold", 10),
        "alb_latency_threshold_seconds": monitoring_cfg.get("alb_latency_threshold_seconds", 2),
        "rds_cpu_threshold":          monitoring_cfg.get("rds_cpu_threshold", 80),
        "rds_max_connections":        monitoring_cfg.get("rds_max_connections", 100),
        "rds_free_storage_threshold_bytes": monitoring_cfg.get("rds_free_storage_threshold_bytes", 5368709120),
    }
