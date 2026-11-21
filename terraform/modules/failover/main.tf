
# NAT ASG 장애 감지 CloudWatch Alarm
resource "aws_cloudwatch_metric_alarm" "nat" {
  for_each = var.nat_asg_names

  alarm_name = "${var.name}-${var.environment}-${replace(each.key, "_", "-")}-failover-alarm"

  alarm_description = "NAT Auto Scaling Group has no InService instances"

  namespace   = "AWS/AutoScaling"
  metric_name = "GroupInServiceInstances"

  dimensions = {
    AutoScalingGroupName = each.value
  }

  statistic = "Minimum"
  period    = 60

  comparison_operator = "LessThanThreshold"
  threshold           = 1

  evaluation_periods  = 1
  datapoints_to_alarm = 1

  treat_missing_data = "missing"

  tags = {
    Name = "${var.name}-${var.environment}-${replace(each.key, "_", "-")}-failover-alarm"
  }
}

# Lambda 비동기 실행 실패 기록 보관
resource "aws_sqs_queue" "failover_dlq" {
  name = "${var.name}-${var.environment}-failover-dlq"

  # 메시지 최대 14일 보관
  message_retention_seconds = 1209600

  # SQS 관리형 암호화
  sqs_managed_sse_enabled = true

  tags = {
    Name = "${var.name}-${var.environment}-failover-dlq"
  }
}

# failover.py를 ZIP 파일로 압축
data "archive_file" "failover" {
  type        = "zip"
  source_file = "${path.module}/lambda/failover.py"
  output_path = "${path.module}/failover.zip"
}


# CloudWatch 알람 이름별 Failover 대상 정보
locals {
  failover_routes = {
    (aws_cloudwatch_metric_alarm.nat["nat_a"].alarm_name) = {
      route_table_id = var.private_route_table_ids["private_a"]
      backup_eni     = var.nat_eni_ids["nat_c"]
    }

    (aws_cloudwatch_metric_alarm.nat["nat_c"].alarm_name) = {
      route_table_id = var.private_route_table_ids["private_c"]
      backup_eni     = var.nat_eni_ids["nat_a"]
    }
  }
}



# NAT Failover Lambda 생성
resource "aws_lambda_function" "failover" {
  function_name = "${var.name}-${var.environment}-nat-failover"

  # IAM 모듈에서 전달받은 역할
  role = var.lambda_role_arn

  # Python 실행 환경
  runtime = "python3.12"
  handler = "failover.lambda_handler"

  # 배포할 Python 코드
  filename         = data.archive_file.failover.output_path
  source_code_hash = data.archive_file.failover.output_base64sha256

  # 실행 환경
  memory_size = 256
  timeout     = 30

  # 동시에 최대 1개 실행
  reserved_concurrent_executions = 1

  # Python에서 사용할 환경 변수
  environment {
    variables = {
      ROUTES = jsonencode(local.failover_routes)
    }
  }

  # VPC 설정 없음: Lambda는 고객 VPC에 연결하지 않음

  tags = {
    Name = "${var.name}-${var.environment}-nat-failover"
  }
}

# Lambda 비동기 호출 실패 처리
resource "aws_lambda_function_event_invoke_config" "failover" {
  function_name = aws_lambda_function.failover.function_name

  # 함수 오류 시 최대 2번 재시도
  maximum_retry_attempts = 2

  # 오래된 비동기 이벤트 처리 제한
  maximum_event_age_in_seconds = 3600

  # 최종 실패 기록을 SQS에 저장
  destination_config {
    on_failure {
      destination = aws_sqs_queue.failover_dlq.arn
    }
  }
}


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


# Failover 장애 알림용 SNS
resource "aws_sns_topic" "failover_alert" {
  name = "${var.name}-${var.environment}-failover-alert"

  tags = {
    Name = "${var.name}-${var.environment}-failover-alert"
  }
}


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
    aws_sns_topic.failover_alert.arn
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
    aws_sns_topic.failover_alert.arn
  ]
}
