# VPC, Subnet, Route Table, S3 Gateway Endpoint
module "network" {
  source = "./modules/network"

  name        = var.name
  environment = var.environment
  vpc_cidr    = var.vpc_cidr
  subnets     = var.subnets
  aws_region  = var.aws_region
}

# NAT·Router Security Group
module "security" {
  source = "./modules/security"

  name        = var.name
  environment = var.environment
  vpc_id      = module.network.vpc_id
  vpc_cidr    = var.vpc_cidr
  subnets     = var.subnets

  # VPC → tailnet 경로를 쓸 때만 라우터 SG에 VPC 인그레스를 엽니다.
  router_vpc_ingress_enabled = length(var.router_routed_cidrs) > 0
}

# NAT·Router·Lambda·EKS·GitHub Actions·시설/KT 허브 ECR Pull IAM
module "iam" {
  source = "./modules/iam"

  name                    = var.name
  environment             = var.environment
  private_route_table_ids = module.network.private_route_table_ids

  github_repository   = var.github_repository
  github_owner_id     = var.github_owner_id
  github_repo_id      = var.github_repo_id
  ecr_repository_arns = values(module.ecr.repository_arns)

  # 시설 K3s ECR Pull 전용 IAM 사용자
  onprem_sites               = local.onprem_sites
  onprem_ecr_repository_arns = [for repo in local.ecr_onprem_repositories : module.ecr.repository_arns[repo]]

  # KT 허브 ECR Pull 전용 IAM 사용자 (통제 UI 이미지)
  kt_hub_ecr_repository_arns = [for repo in local.ecr_kt_repositories : module.ecr.repository_arns[repo]]

  kt_hub_probe_namespace = module.monitoring.kt_hub_probe_namespace
  backup_bucket_arn      = module.storage.backup_bucket_arn
}

# NAT Instance (AZ별 고정 ENI·EIP + ASG)
module "nat" {
  source = "./modules/nat"

  name                      = var.name
  environment               = var.environment
  vpc_cidr                  = var.vpc_cidr
  nat_instance_profile_name = module.iam.nat_instance_profile_name

  instances = {
    for key, instance in var.instances :
    key => instance if startswith(key, "nat_")
  }

  public_subnet_ids = module.network.public_subnet_ids
  nat_sg_id         = module.security.nat_sg_id
}

# NAT 장애 감지와 Private 경로 자동 전환
module "failover" {
  source = "./modules/failover"

  name        = var.name
  environment = var.environment

  nat_asg_names = module.nat.nat_asg_names

  private_route_table_ids = module.network.private_route_table_ids
  nat_eni_ids             = module.nat.nat_eni_ids

  lambda_role_arn = module.iam.failover_lambda_role_arn
  alert_topic_arn = module.monitoring.alert_topic_arn
}

# Private Route Table 기본 경로 → 같은 AZ NAT ENI
# Failover Lambda가 바꾼 경로를 apply가 되돌리지 않도록 ENI 변경은 무시합니다.
resource "aws_route" "private_nat" {
  for_each = module.network.private_route_table_ids

  route_table_id         = each.value
  destination_cidr_block = "0.0.0.0/0"

  network_interface_id = module.nat.nat_eni_ids[
    replace(each.key, "private_", "nat_")
  ]

  # NAT ASG가 준비된 다음 경로 구성
  depends_on = [module.nat]

  lifecycle {
    ignore_changes = [
      network_interface_id
    ]
  }
}

# Tailscale Subnet Router
module "router" {
  source = "./modules/router"

  name        = var.name
  environment = var.environment

  instances = {
    for key, instance in var.instances :
    key => instance if startswith(key, "router_")
  }

  public_subnet_ids = module.network.public_subnet_ids
  router_sg_id      = module.security.router_sg_id

  router_instance_profile_name = module.iam.router_instance_profile_name

  # Private Subnet에서 tailnet으로 가는 경로
  private_route_table_ids = module.network.private_route_table_ids
  routed_cidrs            = var.router_routed_cidrs
}

# EKS Cluster와 Managed Node Group
module "eks" {
  source = "./modules/eks"

  name        = var.name
  environment = var.environment

  cluster_role_arn = module.iam.eks_cluster_role_arn
  node_role_arn    = module.iam.eks_node_role_arn
  ebs_csi_role_arn = module.iam.eks_ebs_csi_role_arn

  private_subnet_ids = [
    module.network.private_subnet_ids["private_a"],
    module.network.private_subnet_ids["private_c"]
  ]

  public_access_enabled = var.eks_public_access_enabled
  public_access_cidrs   = var.eks_public_access_cidrs
  cluster_admin_arns    = var.eks_cluster_admin_arns
  cluster_viewer_arns   = var.eks_cluster_viewer_arns
  router_sg_id          = module.security.router_sg_id

  pod_identity_associations = {
    backup = {
      namespace       = var.backup_service_account.namespace
      service_account = var.backup_service_account.name
      role_arn        = module.iam.backup_role_arn
    }
  }

  node_instance_type = var.eks_node_group.instance_type
  node_disk_size     = var.eks_node_group.disk_size
  node_desired_size  = var.eks_node_group.desired_size
  node_min_size      = var.eks_node_group.min_size
  node_max_size      = var.eks_node_group.max_size

  # 노드가 부팅할 때 NAT 경로가 있어야 클러스터에 조인할 수 있습니다.
  depends_on = [
    aws_route.private_nat
  ]
}

# 애플리케이션 이미지 ECR Repository
module "ecr" {
  source = "./modules/ecr"

  name        = var.name
  environment = var.environment

  repository_names = concat(local.ecr_eks_repositories, local.ecr_onprem_repositories, local.ecr_kt_repositories)
}

# AWS 내부 알림(SNS), KT 허브 상태 알람, Grafana 읽기 전용 IAM
module "monitoring" {
  source = "./modules/monitoring"

  name         = var.name
  environment  = var.environment
  alert_email  = var.alert_email
  alert_emails = var.alert_emails
}

# 백업·이력 내보내기 S3 버킷
module "storage" {
  source = "./modules/storage"

  name        = var.name
  environment = var.environment
}
