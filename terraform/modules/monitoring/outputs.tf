output "alert_topic_arn" {
  description = "AWS 내부 알림 공용 SNS 토픽 ARN"
  value       = aws_sns_topic.alerts.arn
}

output "kt_hub_probe_namespace" {
  description = "KT 허브 상태 확인 지표의 CloudWatch 이름공간"
  value       = var.kt_hub_probe_namespace
}

output "grafana_user_name" {
  description = "Grafana CloudWatch 데이터 소스용 IAM 사용자 이름"
  value       = aws_iam_user.grafana.name
}
