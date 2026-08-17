# acm.tf — ACM certificate (DNS-validated via Route 53)
# Skipped entirely when acm_certificate_arn is provided or domain_name is empty.

locals {
  create_acm  = var.acm_certificate_arn == "" && var.domain_name != ""
  use_route53 = var.route53_zone_name != ""
}

data "aws_route53_zone" "main" {
  count        = local.use_route53 ? 1 : 0
  name         = var.route53_zone_name
  private_zone = false
}

resource "aws_acm_certificate" "main" {
  count                     = local.create_acm ? 1 : 0
  domain_name               = var.domain_name
  subject_alternative_names = var.subject_alternative_names
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${var.environment_name}-cert" }
}

resource "aws_route53_record" "cert_validation" {
  for_each = local.create_acm && local.use_route53 ? {
    for dvo in aws_acm_certificate.main[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  } : {}

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.main[0].zone_id
}

resource "aws_acm_certificate_validation" "main" {
  count                   = local.create_acm && local.use_route53 ? 1 : 0
  certificate_arn         = aws_acm_certificate.main[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

locals {
  certificate_arn = (
    var.acm_certificate_arn != "" ? var.acm_certificate_arn :
    local.create_acm && local.use_route53 ? aws_acm_certificate_validation.main[0].certificate_arn :
    local.create_acm ? aws_acm_certificate.main[0].arn :
    ""
  )
}
