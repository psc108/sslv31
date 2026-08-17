variable "environment_name"  { type = string }
variable "ssh_public_key"    { type = string; sensitive = true }
variable "artefacts_bucket"  { type = string; default = "" }
variable "create_bastion"    { type = bool;   default = false }
variable "management_cidrs"  { type = list(string); default = [] }
variable "private_subnet_ids" { type = list(string) }
variable "public_subnet_ids"  { type = list(string) }
variable "sg_app_id"          { type = string }
variable "vpc_id"             { type = string }

variable "hosts" {
  type = map(object({
    os_type        = string
    instance_type  = string
    service_role   = string
    root_volume_gb = number
    az_index       = number
  }))
  default = {}
}
