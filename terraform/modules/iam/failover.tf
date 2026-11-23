# NAT Failover Lambda

# failover lambda iam role생성
resource "aws_iam_role" "failover" {
  name = "${var.name}-${var.environment}-failover-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.name}-${var.environment}-failover-role"
  }
}

#cloudwatch logs 권한 추가
resource "aws_iam_role_policy_attachment" "failover_logs" {
  role       = aws_iam_role.failover.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Failover Lambda 전용 IAM 정책
resource "aws_iam_role_policy" "failover" {
  name = "${var.name}-${var.environment}-failover-policy"
  role = aws_iam_role.failover.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "ReplacePrivateRoutes"
        Effect = "Allow"

        Action = [
          "ec2:ReplaceRoute"
        ]

        Resource = [
          for rt_id in values(var.private_route_table_ids) :
          "arn:aws:ec2:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:route-table/${rt_id}"
        ]
      },
      {
        Sid    = "SendFailedEvents"
        Effect = "Allow"

        Action = [
          "sqs:SendMessage"
        ]

        Resource = "arn:aws:sqs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:${var.name}-${var.environment}-failover-dlq"
      },
      {
        Sid    = "CheckNATInstanceHealth"
        Effect = "Allow"

        Action = [
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeInstanceStatus"
        ]

        Resource = "*"
      },
      {
        Sid    = "CheckNATAlarms"
        Effect = "Allow"

        Action = [
          "cloudwatch:DescribeAlarms"
        ]

        Resource = [
          "arn:aws:cloudwatch:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:alarm:${var.name}-${var.environment}-nat-a-failover-alarm",
          "arn:aws:cloudwatch:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:alarm:${var.name}-${var.environment}-nat-c-failover-alarm"
        ]
      }
    ]
  })
}
