resource "aws_cloudwatch_metric_alarm" "ec2_cpu_high" {
  for_each = var.instance_ids

  alarm_name          = "${var.environment_name}-${each.key}-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = var.ec2_cpu_threshold
  alarm_description   = "EC2 CPU above ${var.ec2_cpu_threshold}% for 10 minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = { InstanceId = each.value }
  tags       = { Environment = var.environment_name }
}

resource "aws_cloudwatch_metric_alarm" "ec2_memory_high" {
  for_each = var.instance_ids

  alarm_name          = "${var.environment_name}-${each.key}-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "mem_used_percent"
  namespace           = "CertManager/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = var.ec2_memory_threshold
  alarm_description   = "EC2 memory above ${var.ec2_memory_threshold}%"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = { InstanceId = each.value, Environment = var.environment_name }
  tags       = { Environment = var.environment_name }
}

resource "aws_cloudwatch_metric_alarm" "ec2_disk_high" {
  for_each = var.instance_ids

  alarm_name          = "${var.environment_name}-${each.key}-disk-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "disk_used_percent"
  namespace           = "CertManager/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = var.ec2_disk_threshold
  alarm_description   = "EC2 disk above ${var.ec2_disk_threshold}%"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = { InstanceId = each.value, Environment = var.environment_name, path = "/" }
  tags       = { Environment = var.environment_name }
}

resource "aws_cloudwatch_metric_alarm" "ec2_status_check" {
  for_each = var.instance_ids

  alarm_name          = "${var.environment_name}-${each.key}-status-check"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "EC2 instance status check failed"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = { InstanceId = each.value }
  tags       = { Environment = var.environment_name }
}
