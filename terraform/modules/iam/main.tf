#iam role 생성 ->NAT용
resource "aws_iam_role" "nat" {
  name = "${var.name}-${var.environment}-nat-role"

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
    Name = "${var.name}-${var.environment}-nat-role"
  }
}

#SSM 권한 연결
resource "aws_iam_role_policy_attachment" "nat_ssm" {
  role       = aws_iam_role.nat.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"

}

#NAT instance profile 설정
resource "aws_iam_instance_profile" "nat" {
  name = "${var.name}-${var.environment}-nat-profile"
  role = aws_iam_role.nat.name

  tags = {
    Name = "${var.name}-${var.environment}-nat-profile"
  }

}

#iam role 생성 -> 라우터용
resource "aws_iam_role" "router" {
  name = "${var.name}-${var.environment}-router-role"

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
    Name = "${var.name}-${var.environment}-router-role"
  }
}

#SSM 권한 연결
resource "aws_iam_role_policy_attachment" "router_ssm" {
  role       = aws_iam_role.router.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}


#라우터 instance profile 설정
resource "aws_iam_instance_profile" "router" {
  name = "${var.name}-${var.environment}-router-profile"
  role = aws_iam_role.router.name

  tags = {
    Name = "${var.name}-${var.environment}-router-profile"
  }
}

# failover lambda iam role생성
resource "aws_iam_role" "failover" {
  name = "${var.name}-${var.environment}-failover-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.name}-${var.environment}-failover-role"
  }
}

#cloudwatch logs 권한 추가
resource "aws_iam_role_policy_attachment" "failover_logs" {
  role       = aws_iam_role.failover.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# AWS 계정 및 리전 정보 조회
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}


# Failover Lambda 전용 IAM 정책
resource "aws_iam_role_policy" "failover" {
  name = "${var.name}-${var.environment}-failover-policy"
  role = aws_iam_role.failover.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "ReplacePrivateRoutes"
        Effect = "Allow"

        Action = [
          "ec2:ReplaceRoute"
        ]

        Resource = [
          for rt_id in values(var.private_route_table_ids) :
          "arn:aws:ec2:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:route-table/${rt_id}"
        ]
      },
      {
        Sid    = "SendFailedEvents"
        Effect = "Allow"

        Action = [
          "sqs:SendMessage"
        ]

        Resource = "arn:aws:sqs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:${var.name}-${var.environment}-failover-dlq"
      },
      {
        Sid    = "CheckNATInstanceHealth"
        Effect = "Allow"

        Action = [
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeInstanceStatus"
        ]

        Resource = "*"
      },
      {
        Sid    = "CheckNATAlarms"
        Effect = "Allow"

        Action = [
          "cloudwatch:DescribeAlarms"
        ]

        Resource = [
          "arn:aws:cloudwatch:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:alarm:${var.name}-${var.environment}-nat-a-failover-alarm",
          "arn:aws:cloudwatch:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:alarm:${var.name}-${var.environment}-nat-c-failover-alarm"
        ]
      }
    ]
  })
}


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