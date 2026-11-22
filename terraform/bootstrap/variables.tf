# AWS Region
variable "aws_region" {
  description = "AWS Region"
  type        = string
}

# 기존 EKS 클러스터 이름
variable "eks_cluster_name" {
  description = "Existing EKS Cluster Name"
  type        = string
}

# Argo CD Helm Chart 버전
variable "argocd_chart_version" {
  description = "Helm Chart Version for Argo CD 3.6.1"
  type        = string
  default     = "10.15.0"
}