locals {
  log_groups = {
    app      = "/aws/ec2/${var.environment_name}/app"
    nginx    = "/aws/ec2/${var.environment_name}/nginx"
    mysql    = "/aws/ec2/${var.environment_name}/mysql"
    rabbitmq = "/aws/ec2/${var.environment_name}/rabbitmq"
    keystone = "/aws/ec2/${var.environment_name}/keystone"
    alb      = "/aws/alb/${var.environment_name}"
    rds      = "/aws/rds/${var.environment_name}/mysql"
    vpc_flow = "/aws/vpc/${var.environment_name}/flow-logs"
  }
}

resource "aws_cloudwatch_log_group" "main" {
  for_each          = local.log_groups
  name              = each.value
  retention_in_days = var.log_retention_days

  tags = {
    Name        = each.key
    Environment = var.environment_name
  }
}
