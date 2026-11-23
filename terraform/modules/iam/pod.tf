# EKS Pod Identity Role
#
# 연결(ServiceAccount ↔ Role)은 클러스터가 있어야 하므로 eks 모듈에서 만듭니다.

# 백업·이력 내보내기 CronJob
resource "aws_iam_role" "backup" {
  name = "${var.name}-${var.environment}-backup-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "pods.eks.amazonaws.com"
        }

        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })

  tags = {
    Name = "${var.name}-${var.environment}-backup-role"
  }
}

# 백업 버킷의 정해진 prefix에만 쓰기
resource "aws_iam_role_policy" "backup" {
  name = "${var.name}-${var.environment}-backup-policy"
  role = aws_iam_role.backup.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "WriteBackupObjects"
        Effect = "Allow"

        Action = [
          "s3:PutObject",
          "s3:AbortMultipartUpload"
        ]

        Resource = [
          "${var.backup_bucket_arn}/mysql/*",
          "${var.backup_bucket_arn}/history/*",
          "${var.backup_bucket_arn}/audit/*"
        ]
      },
      {
        Sid      = "ListBackupPrefixes"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.backup_bucket_arn

        Condition = {
          StringLike = {
            "s3:prefix" = ["mysql/*", "history/*", "audit/*"]
          }
        }
      }
    ]
  })
}
