# ==========================================
# 시설 K3s ECR Pull 전용 IAM 사용자
# ==========================================
#
# 시설 K3s의 ecr-credential-provider가 ECR 인증 토큰을 받을 때 쓰는 자격 증명입니다.
# 시설마다 사용자를 따로 두어, 한 시설의 키가 유출되면 그 시설 키만 폐기합니다.
# 액세스 키는 Terraform State에 비밀값이 남지 않도록 콘솔에서 직접 발급합니다.
# 콘솔에서 만든 키가 남아 있어도 destroy되도록 force_destroy를 켭니다.

resource "aws_iam_user" "onprem_ecr_pull" {
  for_each = toset(var.onprem_sites)

  name          = "${var.name}-${var.environment}-${each.key}-ecr-pull"
  force_destroy = true

  tags = {
    Name = "${var.name}-${var.environment}-${each.key}-ecr-pull"
  }
}

# 시설 이미지 Repository의 Pull만 허용
resource "aws_iam_user_policy" "onprem_ecr_pull" {
  for_each = aws_iam_user.onprem_ecr_pull

  name = "${var.name}-${var.environment}-${each.key}-ecr-pull-policy"
  user = each.value.name

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "ECRAuthorization"
        Effect = "Allow"

        Action = [
          "ecr:GetAuthorizationToken"
        ]

        Resource = "*"
      },
      {
        Sid    = "ECRPull"
        Effect = "Allow"

        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]

        Resource = var.onprem_ecr_repository_arns
      }
    ]
  })
}
