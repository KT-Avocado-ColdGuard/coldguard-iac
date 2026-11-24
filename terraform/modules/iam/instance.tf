# NAT·Router EC2 Instance Profile

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

# KT 허브 상태 확인 결과를 CloudWatch 지표로 올리는 권한
# 지정한 이름공간에만 쓸 수 있습니다.
resource "aws_iam_role_policy" "router_kt_probe" {
  name = "${var.name}-${var.environment}-router-kt-probe-policy"
  role = aws_iam_role.router.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid      = "PutKTHubProbeMetrics"
        Effect   = "Allow"
        Action   = "cloudwatch:PutMetricData"
        Resource = "*"

        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = var.kt_hub_probe_namespace
          }
        }
      }
    ]
  })
}
