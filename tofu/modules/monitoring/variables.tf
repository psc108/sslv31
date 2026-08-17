variable "environment_name"  { type = string }
variable "aws_region"        { type = string; default = "eu-west-2" }

variable "instance_ids" {
  description = "Map of hostname -> EC2 instance ID"
  type        = map(string)
  default     = {}
}

variable "alb_arn_suffix" {
  description = "ALB ARN suffix for CloudWatch dimensions (empty = no ALB alarms)"
  type        = string
  default     = ""
}

variable "alb_target_group_arn_suffix" {
  description = "ALB target group ARN suffix for unhealthy-host alarm"
  type        = string
  default     = ""
}

variable "db_identifier" {
  description = "RDS DB instance/cluster identifier (empty = no RDS alarms)"
  type        = string
  default     = ""
}

variable "alarm_webhook_url" {
  description = "Build Manager HTTPS endpoint for SNS alarm notifications"
  type        = string
  default     = ""
}

variable "log_retention_days"          { type = number; default = 30 }
variable "ec2_cpu_threshold"           { type = number; default = 80 }
variable "ec2_memory_threshold"        { type = number; default = 85 }
variable "ec2_disk_threshold"          { type = number; default = 85 }
variable "alb_5xx_threshold"           { type = number; default = 10 }
variable "alb_latency_threshold_seconds" { type = number; default = 2 }
variable "rds_cpu_threshold"           { type = number; default = 80 }
variable "rds_max_connections"         { type = number; default = 100 }
variable "rds_free_storage_threshold_bytes" { type = number; default = 5368709120 }
