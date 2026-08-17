variable "environment_name"          { type = string }
variable "aws_account_id"            { type = string; default = "" }
variable "create_app_bucket"         { type = bool;   default = false }
variable "app_bucket_versioning"     { type = bool;   default = false }
variable "app_bucket_lifecycle_days" { type = number; default = 0 }
