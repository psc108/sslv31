# alb.tf — Application Load Balancer (L7)

resource "aws_lb" "app" {
  name               = "${var.environment_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.sg_alb_id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = var.enable_deletion_protection
  enable_http2               = true
  idle_timeout               = 60

  dynamic "access_logs" {
    for_each = var.logs_bucket != "" ? [1] : []
    content {
      bucket  = var.logs_bucket
      prefix  = "alb/${var.environment_name}"
      enabled = true
    }
  }

  tags = { Name = "${var.environment_name}-alb" }
}

# HTTP → HTTPS redirect
resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# HTTPS listener — only created when a certificate ARN is available
resource "aws_lb_listener" "https" {
  count             = local.certificate_arn != "" ? 1 : 0
  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = local.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

# --- Target groups ---

resource "aws_lb_target_group" "frontend" {
  name        = "${var.environment_name}-tg-frontend"
  port        = 443
  protocol    = "HTTPS"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    enabled             = true
    path                = "/health"
    protocol            = "HTTPS"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400
    enabled         = var.enable_stickiness
  }

  tags = { Name = "${var.environment_name}-tg-frontend" }
}

resource "aws_lb_target_group" "backend" {
  name        = "${var.environment_name}-tg-backend"
  port        = 8000
  protocol    = "HTTPS"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    enabled             = true
    path                = "/health"
    protocol            = "HTTPS"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = { Name = "${var.environment_name}-tg-backend" }
}

# --- Path-based routing rules ---

resource "aws_lb_listener_rule" "api" {
  count        = local.certificate_arn != "" ? 1 : 0
  listener_arn = aws_lb_listener.https[0].arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    path_pattern { values = ["/api/*"] }
  }
}

resource "aws_lb_listener_rule" "health" {
  count        = local.certificate_arn != "" ? 1 : 0
  listener_arn = aws_lb_listener.https[0].arn
  priority     = 90

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    path_pattern { values = ["/health", "/health/*"] }
  }
}

# --- Internal ALB (service-to-service HTTPS within the VPC) ---

resource "aws_lb" "internal" {
  count              = var.create_internal_alb ? 1 : 0
  name               = "${var.environment_name}-alb-internal"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [var.sg_internal_alb_id]
  subnets            = var.private_subnet_ids

  enable_deletion_protection = var.enable_deletion_protection
  enable_http2               = true
  idle_timeout               = 60

  tags = { Name = "${var.environment_name}-alb-internal" }
}

resource "aws_lb_listener" "internal_https" {
  count             = var.create_internal_alb && local.certificate_arn != "" ? 1 : 0
  load_balancer_arn = aws_lb.internal[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = local.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend_internal[0].arn
  }
}

resource "aws_lb_target_group" "backend_internal" {
  count       = var.create_internal_alb ? 1 : 0
  name        = "${var.environment_name}-tg-backend-int"
  port        = 8090
  protocol    = "HTTPS"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    enabled             = true
    path                = "/health"
    protocol            = "HTTPS"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = { Name = "${var.environment_name}-tg-backend-int" }
}

resource "aws_lb_target_group_attachment" "backend_internal" {
  for_each = var.create_internal_alb ? {
    for k, v in var.instances : k => v
    if v.service_role == "backend"
  } : {}

  target_group_arn = aws_lb_target_group.backend_internal[0].arn
  target_id        = each.value.instance_id
  port             = 8090
}


resource "aws_lb_target_group_attachment" "frontend" {
  for_each = {
    for k, v in var.instances : k => v
    if v.service_role == "frontend"
  }

  target_group_arn = aws_lb_target_group.frontend.arn
  target_id        = each.value.instance_id
  port             = 443
}

resource "aws_lb_target_group_attachment" "backend" {
  for_each = {
    for k, v in var.instances : k => v
    if v.service_role == "backend"
  }

  target_group_arn = aws_lb_target_group.backend.arn
  target_id        = each.value.instance_id
  port             = 8000
}
