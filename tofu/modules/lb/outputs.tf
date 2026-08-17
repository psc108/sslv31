# outputs.tf — Step 4.4: includes route53_alb_fqdn and route53_nlb_fqdn
# consumed by cert_integration.build_sans_for_host for NLB-exposed service SANs

output "alb_dns_name" {
  value = aws_lb.app.dns_name
}

output "alb_arn" {
  value = aws_lb.app.arn
}

output "alb_arn_suffix" {
  value = aws_lb.app.arn_suffix
}

output "nlb_dns_name" {
  value = var.create_nlb ? aws_lb.tcp[0].dns_name : null
}

output "acm_certificate_arn" {
  value = local.certificate_arn
}

# Step 4.4 — Route 53 FQDNs for cert SAN construction
output "route53_alb_fqdn" {
  description = "Route 53 FQDN for the ALB (null if Route 53 not configured)"
  value       = local.use_route53 && var.domain_name != "" ? aws_route53_record.alb[0].fqdn : null
}

output "internal_alb_dns_name" {
  value = var.create_internal_alb ? aws_lb.internal[0].dns_name : null
}

output "route53_nlb_fqdn" {
  description = "Route 53 FQDN for the NLB (null if Route 53 not configured or NLB disabled)"
  value       = var.create_nlb && local.use_route53 && var.domain_name != "" ? aws_route53_record.nlb[0].fqdn : null
}
