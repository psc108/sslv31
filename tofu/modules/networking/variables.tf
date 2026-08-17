variable "environment_name"   { type = string }
variable "vpc_cidr"           { type = string; default = "10.0.0.0/16" }
variable "az_count"           { type = number; default = 2 }
variable "single_nat_gateway" { type = bool;   default = true }
variable "management_cidrs"   { type = list(string); default = [] }
variable "nlb_allowed_cidrs"  { type = list(string); default = ["0.0.0.0/0"] }
