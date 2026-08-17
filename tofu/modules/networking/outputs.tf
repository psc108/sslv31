output "vpc_id"             { value = aws_vpc.main.id }
output "public_subnet_ids"  { value = aws_subnet.public[*].id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "sg_alb_id"          { value = aws_security_group.alb.id }
output "sg_internal_alb_id" { value = aws_security_group.internal_alb.id }
output "sg_nlb_id"          { value = aws_security_group.nlb.id }
output "sg_app_id"          { value = aws_security_group.app.id }
output "sg_rds_id"          { value = aws_security_group.rds.id }
