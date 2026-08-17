# nlb.tf — Network Load Balancer (L4 TCP passthrough)

resource "aws_lb" "tcp" {
  count              = var.create_nlb ? 1 : 0
  name               = "${var.environment_name}-nlb"
  internal           = false
  load_balancer_type = "network"
  subnets            = var.public_subnet_ids

  enable_deletion_protection       = var.enable_deletion_protection
  enable_cross_zone_load_balancing = true

  dynamic "access_logs" {
    for_each = var.logs_bucket != "" ? [1] : []
    content {
      bucket  = var.logs_bucket
      prefix  = "nlb/${var.environment_name}"
      enabled = true
    }
  }

  tags = { Name = "${var.environment_name}-nlb" }
}

# MySQL TLS (port 3306)
resource "aws_lb_listener" "mysql" {
  count             = var.create_nlb && var.expose_mysql ? 1 : 0
  load_balancer_arn = aws_lb.tcp[0].arn
  port              = 3306
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.mysql[0].arn
  }
}

resource "aws_lb_target_group" "mysql" {
  count       = var.create_nlb && var.expose_mysql ? 1 : 0
  name        = "${var.environment_name}-tg-mysql"
  port        = 3306
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    enabled             = true
    protocol            = "TCP"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = { Name = "${var.environment_name}-tg-mysql" }
}

resource "aws_lb_target_group_attachment" "mysql" {
  for_each = var.create_nlb && var.expose_mysql ? {
    for k, v in var.instances : k => v
    if v.service_role == "mysql"
  } : {}

  target_group_arn = aws_lb_target_group.mysql[0].arn
  target_id        = each.value.instance_id
  port             = 3306
}

# AMQPS (port 5671)
resource "aws_lb_listener" "amqps" {
  count             = var.create_nlb && var.expose_rabbitmq ? 1 : 0
  load_balancer_arn = aws_lb.tcp[0].arn
  port              = 5671
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.amqps[0].arn
  }
}

resource "aws_lb_target_group" "amqps" {
  count       = var.create_nlb && var.expose_rabbitmq ? 1 : 0
  name        = "${var.environment_name}-tg-amqps"
  port        = 5671
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    enabled             = true
    protocol            = "TCP"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = { Name = "${var.environment_name}-tg-amqps" }
}

resource "aws_lb_target_group_attachment" "amqps" {
  for_each = var.create_nlb && var.expose_rabbitmq ? {
    for k, v in var.instances : k => v
    if v.service_role == "rabbitmq"
  } : {}

  target_group_arn = aws_lb_target_group.amqps[0].arn
  target_id        = each.value.instance_id
  port             = 5671
}
