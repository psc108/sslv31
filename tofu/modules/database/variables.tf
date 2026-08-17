variable "environment_name"      { type = string }
variable "vpc_id"                 { type = string }
variable "private_subnet_ids"     { type = list(string) }
variable "sg_rds_id"              { type = string }

variable "db_engine" {
  description = "rds_mysql | aurora_mysql | rds_postgres | aurora_postgres | null"
  type        = string
  default     = null
}

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
