resource "aws_security_group" "alb" {
  name        = "${var.environment_name}-sg-alb"
  description = "ALB — HTTPS/HTTP inbound from internet"
  vpc_id      = aws_vpc.main.id

  ingress { from_port = 443; to_port = 443; protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"]; description = "HTTPS" }
  ingress { from_port = 80;  to_port = 80;  protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"]; description = "HTTP redirect" }
  egress  { from_port = 0;   to_port = 0;   protocol = "-1";  cidr_blocks = ["0.0.0.0/0"] }

  tags = { Name = "${var.environment_name}-sg-alb" }
}

resource "aws_security_group" "nlb" {
  name        = "${var.environment_name}-sg-nlb"
  description = "NLB — TCP inbound on service ports"
  vpc_id      = aws_vpc.main.id

  ingress { from_port = 5671; to_port = 5671; protocol = "tcp"; cidr_blocks = var.nlb_allowed_cidrs; description = "AMQPS" }
  ingress { from_port = 3306; to_port = 3306; protocol = "tcp"; cidr_blocks = var.nlb_allowed_cidrs; description = "MySQL TLS" }
  egress  { from_port = 0;    to_port = 0;    protocol = "-1";  cidr_blocks = ["0.0.0.0/0"] }

  tags = { Name = "${var.environment_name}-sg-nlb" }
}

resource "aws_security_group" "internal_alb" {
  name        = "${var.environment_name}-sg-internal-alb"
  description = "Internal ALB — HTTPS from app tier (service-to-service)"
  vpc_id      = aws_vpc.main.id

  ingress { from_port = 443; to_port = 443; protocol = "tcp"; security_groups = [aws_security_group.app.id]; description = "HTTPS from app tier" }
  egress  { from_port = 0;   to_port = 0;   protocol = "-1";  cidr_blocks = ["0.0.0.0/0"] }

  tags = { Name = "${var.environment_name}-sg-internal-alb" }
}

resource "aws_security_group" "app" {
  name        = "${var.environment_name}-sg-app"
  description = "App EC2 — inbound from ALB/NLB/internal-ALB + SSH from management"
  vpc_id      = aws_vpc.main.id

  ingress { from_port = 443;  to_port = 443;  protocol = "tcp"; security_groups = [aws_security_group.alb.id]; description = "HTTPS from external ALB" }
  ingress { from_port = 80;   to_port = 80;   protocol = "tcp"; security_groups = [aws_security_group.alb.id]; description = "HTTP from external ALB" }
  ingress { from_port = 8000; to_port = 8000; protocol = "tcp"; security_groups = [aws_security_group.alb.id]; description = "App port from external ALB" }
  ingress { from_port = 8090; to_port = 8106; protocol = "tcp"; security_groups = [aws_security_group.internal_alb.id]; description = "Backend services from internal ALB" }
  ingress { from_port = 5671; to_port = 5671; protocol = "tcp"; security_groups = [aws_security_group.nlb.id]; description = "AMQPS from NLB" }
  ingress { from_port = 3306; to_port = 3306; protocol = "tcp"; security_groups = [aws_security_group.nlb.id]; description = "MySQL from NLB" }

  dynamic "ingress" {
    for_each = length(var.management_cidrs) > 0 ? [1] : []
    content {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.management_cidrs
      description = "SSH from management"
    }
  }

  egress { from_port = 0; to_port = 0; protocol = "-1"; cidr_blocks = ["0.0.0.0/0"] }

  tags = { Name = "${var.environment_name}-sg-app" }
}

resource "aws_security_group" "rds" {
  name        = "${var.environment_name}-sg-rds"
  description = "RDS — MySQL/PostgreSQL from app tier only"
  vpc_id      = aws_vpc.main.id

  ingress { from_port = 3306; to_port = 3306; protocol = "tcp"; security_groups = [aws_security_group.app.id]; description = "MySQL from app" }
  ingress { from_port = 5432; to_port = 5432; protocol = "tcp"; security_groups = [aws_security_group.app.id]; description = "PostgreSQL from app" }
  ingress { from_port = 3306; to_port = 3306; protocol = "tcp"; security_groups = [aws_security_group.nlb.id]; description = "MySQL from NLB" }
  egress  { from_port = 0;    to_port = 0;    protocol = "-1";  cidr_blocks = ["0.0.0.0/0"] }

  tags = { Name = "${var.environment_name}-sg-rds" }
}
