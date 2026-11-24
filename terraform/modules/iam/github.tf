# ==========================================
# GitHub Actions OIDC Provider
# ==========================================

resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com"
  ]

  tags = {
    Name = "${var.name}-${var.environment}-github-oidc"
  }
}

# ==========================================
# GitHub Actions IAM Role
# ==========================================

resource "aws_iam_role" "github_actions" {
  name = "${var.name}-${var.environment}-github-actions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        }

        Action = "sts:AssumeRoleWithWebIdentity"

        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"

            "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:ref:refs/heads/main"
          }
        }
      }
    ]
  })

  tags = {
    Name = "${var.name}-${var.environment}-github-actions-role"
  }
}

# ==========================================
# GitHub Actions ECR Push Policy
# ==========================================

resource "aws_iam_role_policy" "github_actions_ecr" {
  name = "${var.name}-${var.environment}-github-ecr-push-policy"

  role = aws_iam_role.github_actions.id

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
        Sid    = "ECRPush"
        Effect = "Allow"

        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart"
        ]

        Resource = var.ecr_repository_arns
      }
    ]
  })
}
