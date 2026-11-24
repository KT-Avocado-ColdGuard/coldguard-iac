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

# Argo CD 접속 주소 (알림 링크용, 예: https://argocd.<tailnet>.ts.net)
variable "argocd_url" {
  description = "Argo CD URL used in notification links (empty to skip)"
  type        = string
  default     = ""
}

# Tailscale Kubernetes Operator
variable "tailscale_operator_enabled" {
  description = "Install the Tailscale operator (operator-oauth Secret must exist first)"
  type        = bool
  default     = false
}

variable "tailscale_operator_chart_version" {
  description = "Helm Chart Version for the Tailscale operator"
  type        = string
  default     = "1.98.3"
}

# GitOps 루트 Application
variable "gitops_root_app_enabled" {
  description = "Create the root Application pointing at coldguard-gitops/argocd"
  type        = bool
  default     = false
}

variable "gitops_repo_url" {
  description = "GitOps repository URL"
  type        = string
  default     = "https://github.com/KT-Avocado-ColdGuard/coldguard-gitops.git"
}

variable "gitops_target_revision" {
  description = "GitOps branch Argo CD follows"
  type        = string
  default     = "main"
}