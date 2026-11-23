#네트워크 모듈 생성 빠라라라라밤
module "network" {
  source = "./modules/network"

  name        = var.name
  environment = var.environment
  vpc_cidr    = var.vpc_cidr
  subnets     = var.subnets
  aws_region  = var.aws_region
}

#보안 모듈 생성 빠라라라라밤
module "security" {
  source = "./modules/security"

  name        = var.name
  environment = var.environment
  vpc_id      = module.network.vpc_id
  vpc_cidr    = var.vpc_cidr
  subnets     = var.subnets
}

#iam 모듈 생성 짜라빠빠 그대는 아름다워
module "iam" {
  source = "./modules/iam"

  name                    = var.name
  environment             = var.environment
  private_route_table_ids = module.network.private_route_table_ids

  github_repository   = var.github_repository
  ecr_repository_name = "${var.name}-${var.environment}-app"
}

#nat instance 생성 빠라라라라밤
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

  depends_on = [module.network]
}

#fail over 모듈 생성 짜라빠빠빠빠
module "failover" {
  source = "./modules/failover"

  name        = var.name
  environment = var.environment
  aws_region  = var.aws_region

  nat_asg_names = module.nat.nat_asg_names

  private_route_table_ids = module.network.private_route_table_ids
  nat_eni_ids             = module.nat.nat_eni_ids

  lambda_role_arn = module.iam.failover_lambda_role_arn
}

#priavte route table에 nat eni 연결
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

#라우터 모듈 생성 빠라라라빰 함박아 해병님
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

  depends_on = [module.network]
}

#eks 모듈 생성 짜라라라라라 그대는 아름다워 짜짜라라라짜라라바빠빠빠
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

  public_access_cidrs = var.eks_public_access_cidrs


  node_instance_type = "t3.medium"
  node_disk_size     = 20

  node_desired_size = 3
  node_min_size     = 3
  node_max_size     = 3

  depends_on = [
    aws_route.private_nat
  ]
}

# ECR Module 생성 크아아아악
module "ecr" {
  source = "./modules/ecr"

  name        = var.name
  environment = var.environment

  repository_names = ["app"]
}