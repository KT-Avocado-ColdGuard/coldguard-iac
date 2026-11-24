locals {
  name_prefix = "${var.name}-${var.environment}"

  common_tags = {
    Project   = "ColdGuard"
    Owner     = var.owner
    Env       = var.environment
    ManagedBy = "Terraform"
  }

  # ECR Repository (이름: <name>-<environment>-<key>)
  # EKS 이미지는 노드 Role(AmazonEC2ContainerRegistryReadOnly)로 받고,
  # 시설 K3s 이미지는 시설별 Pull 전용 IAM 사용자로 받습니다.
  ecr_eks_repositories    = ["control-api", "central-worker"]
  ecr_onprem_repositories = ["collector", "controller", "field-web"]

  # ECR Pull 전용 IAM 사용자를 둘 시설 (MQTT·DB의 site_id와 같은 값)
  onprem_sites = ["site01", "site02"]
}