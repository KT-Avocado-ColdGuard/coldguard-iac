# Failover Lambda 자체 이상 알람
# 공용 SNS 토픽(monitoring 모듈)으로 보냅니다.

# Lambda 실행 오류 감지
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name        = "${var.name}-${var.environment}-lambda-errors"
  alarm_description = "NAT Failover Lambda execution errors"

  namespace   = "AWS/Lambda"
  metric_name = "Errors"

  dimensions = {
    FunctionName = aws_lambda_function.failover.function_name
  }

  statistic = "Sum"
  period    = 60

  comparison_operator = "GreaterThanThreshold"
  threshold           = 0

  evaluation_periods  = 1
  datapoints_to_alarm = 1

  treat_missing_data = "notBreaching"

  alarm_actions = [
    var.alert_topic_arn
  ]
}

# Lambda 실행 제한(Throttles) 감지
resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  alarm_name        = "${var.name}-${var.environment}-lambda-throttles"
  alarm_description = "NAT Failover Lambda throttled invocations"

  namespace   = "AWS/Lambda"
  metric_name = "Throttles"

  dimensions = {
    FunctionName = aws_lambda_function.failover.function_name
  }

  statistic = "Sum"
  period    = 60

  comparison_operator = "GreaterThanThreshold"
  threshold           = 0

  evaluation_periods  = 1
  datapoints_to_alarm = 1

  treat_missing_data = "notBreaching"

  alarm_actions = [
    var.alert_topic_arn
  ]
}
