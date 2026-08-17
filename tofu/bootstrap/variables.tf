variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-2"
}

variable "aws_account_id" {
  description = "AWS account ID — used in globally unique bucket names"
  type        = string
}

variable "log_retention_days" {
  description = "Days to retain logs in the logs bucket"
  type        = number
  default     = 30
}
