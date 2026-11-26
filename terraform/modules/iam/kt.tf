# ==========================================
# KT 허브 ECR Pull 전용 IAM 사용자
# ==========================================
#
# KT 허브(docker compose)가 통제 UI 이미지를 받을 때 쓰는 자격 증명입니다.
# 허브는 K3s가 아니라서 ecr-credential-provider를 쓰지 않고, 이미지를 받기 전에 이 키로 ECR에 로그인합니다(토큰 12시간).
# 시설 사용자와 따로 두어, 허브 키가 유출되면 허브 키만 폐기합니다.
# 액세스 키는 Terraform State에 비밀값이 남지 않도록 콘솔에서 직접 발급합니다.
# 콘솔에서 만든 키가 남아 있어도 destroy되도록 force_destroy를 켭니다.

resource "aws_iam_user" "kt_hub_ecr_pull" {
  name          = "${var.name}-${var.environment}-kt-hub-ecr-pull"
  force_destroy = true

  tags = {
    Name = "${var.name}-${var.environment}-kt-hub-ecr-pull"
  }
}

# KT 허브 이미지 Repository의 Pull만 허용
resource "aws_iam_user_policy" "kt_hub_ecr_pull" {
  name = "${var.name}-${var.environment}-kt-hub-ecr-pull-policy"
  user = aws_iam_user.kt_hub_ecr_pull.name

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

        Resource = var.kt_hub_ecr_repository_arns
      }
    ]
  })
}
