# EKS Cluster·Node·Add-on

# EKS Cluster IAM Role
resource "aws_iam_role" "eks_cluster" {
  name = "${var.name}-${var.environment}-eks-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "eks.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.name}-${var.environment}-eks-cluster-role"
  }
}

# EKS Cluster 관리 권한
resource "aws_iam_role_policy_attachment" "eks_cluster" {
  role = aws_iam_role.eks_cluster.name

  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# EKS Worker Node IAM Role
resource "aws_iam_role" "eks_node" {
  name = "${var.name}-${var.environment}-eks-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "ec2.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.name}-${var.environment}-eks-node-role"
  }
}

# Worker Node가 EKS Cluster에 연결할 때 필요한 권한
resource "aws_iam_role_policy_attachment" "eks_worker" {
  role = aws_iam_role.eks_node.name

  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

# ECR에서 컨테이너 이미지를 다운로드하는 권한
resource "aws_iam_role_policy_attachment" "eks_ecr" {
  role = aws_iam_role.eks_node.name

  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# VPC CNI 네트워크 인터페이스 관리 권한
resource "aws_iam_role_policy_attachment" "eks_cni" {
  role = aws_iam_role.eks_node.name

  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

# EKS EBS CSI Driver IAM Role
resource "aws_iam_role" "eks_ebs_csi" {
  name = "${var.name}-${var.environment}-eks-ebs-csi-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "pods.eks.amazonaws.com"
        }

        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })

  tags = {
    Name = "${var.name}-${var.environment}-eks-ebs-csi-role"
  }
}

# EBS 볼륨 관리 권한
resource "aws_iam_role_policy_attachment" "eks_ebs_csi" {
  role = aws_iam_role.eks_ebs_csi.name

  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}
