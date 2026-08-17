resource "aws_cloudwatch_metric_alarm" "alb_5xx_high" {
  count = var.alb_arn_suffix != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-alb-5xx-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = var.alb_5xx_threshold
  alarm_description   = "ALB 5xx errors above ${var.alb_5xx_threshold} in 5 minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = { LoadBalancer = var.alb_arn_suffix }
  tags       = { Environment = var.environment_name }
}

resource "aws_cloudwatch_metric_alarm" "alb_target_5xx_high" {
  count = var.alb_arn_suffix != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-alb-target-5xx-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = var.alb_5xx_threshold
  alarm_description   = "ALB target 5xx errors — application returning errors"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = { LoadBalancer = var.alb_arn_suffix }
  tags       = { Environment = var.environment_name }
}

resource "aws_cloudwatch_metric_alarm" "alb_latency_high" {
  count = var.alb_arn_suffix != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-alb-latency-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  extended_statistic  = "p95"
  threshold           = var.alb_latency_threshold_seconds
  alarm_description   = "ALB p95 response time above ${var.alb_latency_threshold_seconds}s"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = { LoadBalancer = var.alb_arn_suffix }
  tags       = { Environment = var.environment_name }
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  count = var.alb_arn_suffix != "" && var.alb_target_group_arn_suffix != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-alb-unhealthy-hosts"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "One or more ALB targets are unhealthy"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.alb_target_group_arn_suffix }
  tags       = { Environment = var.environment_name }
}
