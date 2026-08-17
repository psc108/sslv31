variable "environment_name"            { type = string }
variable "vpc_id"                       { type = string }
variable "public_subnet_ids"            { type = list(string) }
variable "sg_alb_id"                    { type = string }
variable "logs_bucket"                  { type = string; default = "" }
variable "enable_deletion_protection"   { type = bool;   default = false }
variable "enable_stickiness"            { type = bool;   default = false }

variable "domain_name"                  { type = string; default = "" }
variable "subject_alternative_names"    { type = list(string); default = [] }
variable "route53_zone_name"            { type = string; default = "" }
variable "acm_certificate_arn"          { type = string; default = "" }

variable "create_nlb"          { type = bool;         default = true }
variable "expose_mysql"        { type = bool;         default = false }
variable "expose_rabbitmq"     { type = bool;         default = false }
variable "create_internal_alb" { type = bool;         default = false }
variable "private_subnet_ids"  { type = list(string); default = [] }
variable "sg_internal_alb_id"  { type = string;       default = "" }

variable "instances" {
  description = "Map of instance_id + service_role from compute module"
  type = map(object({
    instance_id  = string
    service_role = string
  }))
  default = {}
}
