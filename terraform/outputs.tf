output "aws_region" {
  description = "AWS Region used for this deployment"
  value       = var.aws_region
}

# EKS Cluster
output "eks_cluster_name" {
  description = "EKS Cluster Name"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS Cluster API Endpoint"
  value       = module.eks.cluster_endpoint
}

# EKS Managed Node Group
output "eks_node_group_name" {
  description = "EKS Managed Node Group Name"
  value       = module.eks.node_group_name
}

# ECR Repository
output "ecr_repository_urls" {
  description = "ECR Repository URLs"
  value       = module.ecr.repository_urls
}

# GitHub Actions IAM Role ARN
output "github_actions_role_arn" {
  description = "GitHub Actions IAM Role ARN"
  value       = module.iam.github_actions_role_arn
}

# 백업·이력 내보내기
output "backup_bucket_name" {
  description = "백업·이력 내보내기 S3 버킷 이름"
  value       = module.storage.backup_bucket_name
}

output "backup_role_arn" {
  description = "백업 CronJob Pod Identity Role ARN"
  value       = module.iam.backup_role_arn
}

# 알림·모니터링
output "alert_topic_arn" {
  description = "AWS 내부 알림 SNS 토픽 ARN"
  value       = module.monitoring.alert_topic_arn
}

output "grafana_user_name" {
  description = "Grafana CloudWatch 데이터 소스용 IAM 사용자 (액세스 키는 콘솔에서 발급)"
  value       = module.monitoring.grafana_user_name
}

# Tailscale 서브넷 라우터
output "router_public_ips" {
  description = "Tailscale 서브넷 라우터 공인 IP"
  value       = module.router.router_public_ips
}
