# 백업·내보내기 버킷
#
# prefix별 용도
#   mysql/   MySQL 백업 CronJob
#   history/ 데이터 이력 내보내기 CronJob
#   audit/   감사 로그 내보내기 CronJob(선택)
#
# 프로젝트 종료 후 전부 삭제하므로 객체가 남아 있어도 destroy되도록 force_destroy를 켭니다.
resource "aws_s3_bucket" "backup" {
  bucket_prefix = "${var.name}-${var.environment}-backup-"
  force_destroy = true

  tags = {
    Name = "${var.name}-${var.environment}-backup"
  }
}

# ACL 비활성화(버킷 소유자 적용)
resource "aws_s3_bucket_ownership_controls" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# 퍼블릭 액세스 전부 차단
resource "aws_s3_bucket_public_access_block" "backup" {
  bucket = aws_s3_bucket.backup.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 실수로 지우거나 덮어쓴 객체를 되돌릴 수 있도록 버전 관리
resource "aws_s3_bucket_versioning" "backup" {
  bucket = aws_s3_bucket.backup.id

  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3 기본 암호화
resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 보관 기간
# 시연 기간 기준 값입니다. 운영 환경이라면 기간을 늘립니다.
resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    id     = "mysql-7d"
    status = "Enabled"

    filter {
      prefix = "mysql/"
    }

    expiration {
      days = 7
    }
  }

  rule {
    id     = "history-30d"
    status = "Enabled"

    filter {
      prefix = "history/"
    }

    expiration {
      days = 30
    }
  }

  rule {
    id     = "audit-30d"
    status = "Enabled"

    filter {
      prefix = "audit/"
    }

    expiration {
      days = 30
    }
  }

  # 버킷 전체: 이전 버전 3일 보관, 끝나지 않은 멀티파트 업로드 1일 뒤 정리
  rule {
    id     = "noncurrent-3d"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 3
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.backup]
}

# HTTPS가 아닌 요청 거부
resource "aws_s3_bucket_policy" "backup" {
  bucket = aws_s3_bucket.backup.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"

        Resource = [
          aws_s3_bucket.backup.arn,
          "${aws_s3_bucket.backup.arn}/*"
        ]

        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.backup]
}
