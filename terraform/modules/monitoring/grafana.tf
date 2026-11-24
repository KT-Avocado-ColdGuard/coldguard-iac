# KT Grafana의 CloudWatch 데이터 소스용 읽기 전용 IAM 사용자
#
# 액세스 키는 Terraform State에 비밀값이 남지 않도록 콘솔에서 직접 발급합니다.
# 콘솔에서 만든 키가 남아 있어도 destroy되도록 force_destroy를 켭니다.
resource "aws_iam_user" "grafana" {
  name          = "${var.name}-${var.environment}-grafana-cloudwatch"
  force_destroy = true

  tags = {
    Name = "${var.name}-${var.environment}-grafana-cloudwatch"
  }
}

# CloudWatch 지표·로그 읽기
resource "aws_iam_user_policy_attachment" "grafana_cloudwatch" {
  user       = aws_iam_user.grafana.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess"
}

# Grafana CloudWatch 데이터 소스가 차원 값과 리전 목록을 조회할 때 쓰는 권한
resource "aws_iam_user_policy" "grafana_lookup" {
  name = "${var.name}-${var.environment}-grafana-lookup"
  user = aws_iam_user.grafana.name

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "GrafanaResourceLookup"
        Effect = "Allow"

        Action = [
          "ec2:DescribeTags",
          "ec2:DescribeInstances",
          "ec2:DescribeRegions",
          "tag:GetResources"
        ]

        Resource = "*"
      }
    ]
  })
}
