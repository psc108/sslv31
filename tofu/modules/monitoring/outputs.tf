output "sns_topic_arn" {
  value = aws_sns_topic.alarms.arn
}

output "dashboard_url" {
  value = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${var.environment_name}-overview"
}

output "log_group_names" {
  value = { for k, v in aws_cloudwatch_log_group.main : k => v.name }
}
