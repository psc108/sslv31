# dns.tf — Route 53 A alias records for ALB and NLB

resource "aws_route53_record" "alb" {
  count   = local.use_route53 && var.domain_name != "" ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_lb.app.dns_name
    zone_id                = aws_lb.app.zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "nlb" {
  count   = var.create_nlb && local.use_route53 && var.domain_name != "" ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = "tcp.${var.domain_name}"
  type    = "A"

  alias {
    name                   = aws_lb.tcp[0].dns_name
    zone_id                = aws_lb.tcp[0].zone_id
    evaluate_target_health = true
  }
}
