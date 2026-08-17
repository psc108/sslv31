output "instance_ids" {
  value = { for k, v in aws_instance.host : k => v.id }
}

output "private_ips" {
  value = { for k, v in aws_instance.host : k => v.private_ip }
}

output "bastion_public_ip" {
  value = var.create_bastion ? aws_eip.bastion[0].public_ip : null
}
