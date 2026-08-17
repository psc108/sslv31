resource "aws_sns_topic" "alarms" {
  name = "${var.environment_name}-alarms"

  tags = {
    Name        = "${var.environment_name}-alarms"
    Environment = var.environment_name
  }
}

resource "aws_sns_topic_subscription" "build_manager_webhook" {
  count     = var.alarm_webhook_url != "" ? 1 : 0
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "https"
  endpoint  = var.alarm_webhook_url

  endpoint_auto_confirms = true
}
