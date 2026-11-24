output "backup_bucket_name" {
  description = "백업·내보내기 버킷 이름"
  value       = aws_s3_bucket.backup.bucket
}

output "backup_bucket_arn" {
  description = "백업·내보내기 버킷 ARN"
  value       = aws_s3_bucket.backup.arn
}
