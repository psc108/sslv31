resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  count = var.db_identifier != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-rds-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = var.rds_cpu_threshold
  alarm_description   = "RDS CPU above ${var.rds_cpu_threshold}%"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = { DBInstanceIdentifier = var.db_identifier }
  tags       = { Environment = var.environment_name }
}

resource "aws_cloudwatch_metric_alarm" "rds_connections_high" {
  count = var.db_identifier != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-rds-connections-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = var.rds_max_connections
  alarm_description   = "RDS connections above ${var.rds_max_connections}"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = { DBInstanceIdentifier = var.db_identifier }
  tags       = { Environment = var.environment_name }
}

resource "aws_cloudwatch_metric_alarm" "rds_free_storage_low" {
  count = var.db_identifier != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-rds-storage-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = var.rds_free_storage_threshold_bytes
  alarm_description   = "RDS free storage below threshold"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = { DBInstanceIdentifier = var.db_identifier }
  tags       = { Environment = var.environment_name }
}
