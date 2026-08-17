resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.environment_name}-overview"

  dashboard_body = jsonencode({
    widgets = concat(
      # EC2 CPU widget (only when instances exist)
      length(var.instance_ids) > 0 ? [{
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "EC2 CPU Utilisation"
          period = 300
          stat   = "Average"
          metrics = [
            for name, id in var.instance_ids :
            ["AWS/EC2", "CPUUtilization", "InstanceId", id, { label = name }]
          ]
        }
      }] : [],

      # ALB widgets (only when ALB ARN suffix provided)
      var.alb_arn_suffix != "" ? [
        {
          type   = "metric"
          width  = 12
          height = 6
          properties = {
            title  = "ALB Request Count & Error Rate"
            period = 300
            metrics = [
              ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix, { stat = "Sum", label = "Requests" }],
              ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", var.alb_arn_suffix, { stat = "Sum", label = "5xx Errors" }],
              ["AWS/ApplicationELB", "HTTPCode_ELB_4XX_Count", "LoadBalancer", var.alb_arn_suffix, { stat = "Sum", label = "4xx Errors" }]
            ]
          }
        },
        {
          type   = "metric"
          width  = 12
          height = 6
          properties = {
            title  = "ALB Response Time (p50 / p95 / p99)"
            period = 300
            metrics = [
              ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, { stat = "p50", label = "p50" }],
              ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, { stat = "p95", label = "p95" }],
              ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, { stat = "p99", label = "p99" }]
            ]
          }
        }
      ] : [],

      # RDS widget (only when db_identifier provided)
      var.db_identifier != "" ? [{
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "RDS CPU & Connections"
          period = 300
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_identifier, { stat = "Average", label = "CPU %" }],
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", var.db_identifier, { stat = "Average", label = "Connections", yAxis = "right" }]
          ]
        }
      }] : []
    )
  })
}
