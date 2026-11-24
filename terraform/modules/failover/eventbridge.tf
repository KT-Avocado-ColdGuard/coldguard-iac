# CloudWatch Alarm 상태 변경 감지
resource "aws_cloudwatch_event_rule" "nat_failover" {
  name        = "${var.name}-${var.environment}-nat-failover-rule"
  description = "Trigger NAT failover when a NAT alarm enters ALARM state"

  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]

    detail = {
      alarmName = [
        for alarm in aws_cloudwatch_metric_alarm.nat :
        alarm.alarm_name
      ]

      state = {
        value = ["ALARM"]
      }
    }
  })
}

# EventBridge에서 Lambda 호출
resource "aws_cloudwatch_event_target" "nat_failover" {
  rule      = aws_cloudwatch_event_rule.nat_failover.name
  target_id = "NATFailoverLambda"
  arn       = aws_lambda_function.failover.arn

  # EventBridge 전달 실패 시 재시도
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 2
  }

  # 최종 전달 실패 시 SQS에 저장
  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }

  depends_on = [
    aws_sqs_queue_policy.eventbridge_dlq,
    aws_lambda_permission.eventbridge
  ]
}

# EventBridge에 Lambda 실행 권한 부여
resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeNATFailover"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.failover.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.nat_failover.arn
}

# EventBridge 전달 실패 DLQ
resource "aws_sqs_queue" "eventbridge_dlq" {
  name = "${var.name}-${var.environment}-eventbridge-dlq"

  # 최대 14일 보관
  message_retention_seconds = 1209600

  sqs_managed_sse_enabled = true

  tags = {
    Name = "${var.name}-${var.environment}-eventbridge-dlq"
  }
}

# EventBridge가 DLQ에 메시지를 보낼 수 있는 권한
resource "aws_sqs_queue_policy" "eventbridge_dlq" {
  queue_url = aws_sqs_queue.eventbridge_dlq.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "AllowEventBridgeSendMessage"
        Effect = "Allow"

        Principal = {
          Service = "events.amazonaws.com"
        }

        Action = "sqs:SendMessage"

        Resource = aws_sqs_queue.eventbridge_dlq.arn

        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_cloudwatch_event_rule.nat_failover.arn
          }
        }
      }
    ]
  })
}
