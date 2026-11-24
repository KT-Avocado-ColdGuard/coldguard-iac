
# EKS Cluster
resource "aws_eks_cluster" "main" {
  name     = "${var.name}-${var.environment}-eks"
  version  = "1.36"
  role_arn = var.cluster_role_arn

  access_config {
    # aws-auth ConfigMap 없이 Access Entry로만 권한을 관리합니다.
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true
  }

  vpc_config {
    subnet_ids = var.private_subnet_ids

    endpoint_private_access = true

    # Tailscale로 private endpoint에 접속할 수 있게 되면 끕니다.
    # 서브넷 라우터 장애 시 비상 접속용으로 다시 켤 수 있습니다.
    endpoint_public_access = var.public_access_enabled

    # public endpoint를 끄면 허용 CIDR은 쓰이지 않으므로 넘기지 않습니다(기존 값 유지, plan 차이 방지).
    public_access_cidrs = var.public_access_enabled ? var.public_access_cidrs : null
  }

  tags = {
    Name = "${var.name}-${var.environment}-eks"
  }
}


# EKS Managed Node Group
resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.name}-${var.environment}-node-group"

  node_role_arn = var.node_role_arn
  subnet_ids    = var.private_subnet_ids

  instance_types = [var.node_instance_type]
  ami_type       = "AL2023_x86_64_STANDARD"
  disk_size      = var.node_disk_size
  capacity_type  = "ON_DEMAND"

  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_min_size
    max_size     = var.node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  depends_on = [
    aws_eks_addon.vpc_cni
  ]

  tags = {
    Name = "${var.name}-${var.environment}-node-group"
  }
}



# ============================================
# EKS Pod Identity Agent
# ============================================

resource "aws_eks_addon" "pod_identity_agent" {
  cluster_name = aws_eks_cluster.main.name
  addon_name   = "eks-pod-identity-agent"

  depends_on = [
    aws_eks_node_group.main
  ]
}


# EKS VPC CNI
resource "aws_eks_addon" "vpc_cni" {
  cluster_name = aws_eks_cluster.main.name
  addon_name   = "vpc-cni"

  resolve_conflicts_on_create = "OVERWRITE"
}


# EKS EBS CSI Driver
resource "aws_eks_addon" "ebs_csi" {
  cluster_name = aws_eks_cluster.main.name
  addon_name   = "aws-ebs-csi-driver"

  pod_identity_association {
    service_account = "ebs-csi-controller-sa"
    role_arn        = var.ebs_csi_role_arn
  }

  depends_on = [
    aws_eks_addon.pod_identity_agent
  ]
}


# ============================================
# 클러스터 관리자 (Access Entry)
# ============================================
# 클러스터를 만든 IAM 주체는 bootstrap_cluster_creator_admin_permissions로 이미 관리자입니다.
# 같은 ARN을 이 목록에 넣으면 이미 존재한다는 오류가 납니다.
resource "aws_eks_access_entry" "admin" {
  for_each = toset(var.cluster_admin_arns)

  cluster_name  = aws_eks_cluster.main.name
  principal_arn = each.value
}

resource "aws_eks_access_policy_association" "admin" {
  for_each = toset(var.cluster_admin_arns)

  cluster_name  = aws_eks_cluster.main.name
  principal_arn = each.value
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.admin]
}


# ============================================
# 클러스터 조회 전용 (Access Entry)
# ============================================
# 보안 검토 등 읽기만 필요한 사용자용입니다. AmazonEKSViewPolicy는 Secret을 읽지 못합니다.
# IAM Identity Center 역할은 경로(aws-reserved/sso.amazonaws.com/...)를 포함한 ARN 그대로 넣습니다.
# 권한 세트 할당을 지웠다가 다시 만들면 역할 이름의 접미사가 바뀌므로 ARN도 다시 넣어야 합니다.
resource "aws_eks_access_entry" "viewer" {
  for_each = toset(var.cluster_viewer_arns)

  cluster_name  = aws_eks_cluster.main.name
  principal_arn = each.value
}

resource "aws_eks_access_policy_association" "viewer" {
  for_each = toset(var.cluster_viewer_arns)

  cluster_name  = aws_eks_cluster.main.name
  principal_arn = each.value
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.viewer]
}


# ============================================
# Pod Identity 연결 (ServiceAccount ↔ IAM Role)
# ============================================
resource "aws_eks_pod_identity_association" "app" {
  for_each = var.pod_identity_associations

  cluster_name    = aws_eks_cluster.main.name
  namespace       = each.value.namespace
  service_account = each.value.service_account
  role_arn        = each.value.role_arn

  depends_on = [aws_eks_addon.pod_identity_agent]
}


# ============================================
# Tailscale 경유 private endpoint 접속
# ============================================
# 서브넷 라우터가 tailnet 트래픽을 자기 사설 IP로 SNAT하므로 라우터 SG에서 오는 443만 열면 됩니다.
resource "aws_vpc_security_group_ingress_rule" "api_from_router" {
  security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id

  description                  = "Kubernetes API from Tailscale subnet router"
  referenced_security_group_id = var.router_sg_id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}
