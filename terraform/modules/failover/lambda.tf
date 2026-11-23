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
