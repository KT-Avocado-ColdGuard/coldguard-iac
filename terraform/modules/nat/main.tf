# NAT Instance ENI(엘라스틱 네트워크 인터페이스) 생성
resource "aws_network_interface" "nat" {
  for_each = var.instances

  subnet_id = var.public_subnet_ids[each.value.subnet]

  security_groups = [var.nat_sg_id]

  source_dest_check = false

  tags = {
    Name = "${var.name}-${var.environment}-nat-eni-${split("_", each.key)[1]}"
  }
}

# NAT instance EIP(엘라스틱 IP) 생성
resource "aws_eip" "nat" {
  for_each = var.instances

  domain = "vpc"

  tags = {
    Name = "${var.name}-${var.environment}-nat-eip-${split("_", each.key)[1]}"
  }

}

#EIP와 ENI 연결
resource "aws_eip_association" "nat" {
  for_each = var.instances

  allocation_id        = aws_eip.nat[each.key].id
  network_interface_id = aws_network_interface.nat[each.key].id
}

#ubuntu 24.04 AMI 가져오기
data "aws_ssm_parameter" "ubuntu_2404" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}


# NAT Launch Template 생성
resource "aws_launch_template" "nat" {
  for_each = var.instances

  name = "${var.name}-${var.environment}-${replace(each.key, "_", "-")}-lt"

  # 운영체제 및 EC2 사양
  image_id = (
    each.value.ami != null
    ? each.value.ami
    : data.aws_ssm_parameter.ubuntu_2404.value
  )

  instance_type = each.value.instance_type

  # NAT EC2 IAM Instance Profile
  iam_instance_profile {
    name = var.nat_instance_profile_name
  }

  # EC2 최초 부팅 시 NAT 설정 자동 실행
  user_data = base64encode(
    templatefile("${path.module}/scripts/nat-user-data.sh.tftpl", {
      vpc_cidr = var.vpc_cidr
    })
  )


  # 기본 EBS 디스크
  block_device_mappings {
    device_name = "/dev/sda1"

    ebs {
      volume_size           = each.value.volume_size
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  # 기존에 생성한 고정 ENI 연결
  network_interfaces {
    device_index          = 0
    network_interface_id  = aws_network_interface.nat[each.key].id
    delete_on_termination = false
  }

  # IMDSv2 사용
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  # EC2 Name 태그
  tag_specifications {
    resource_type = "instance"

    tags = {
      Name = "${var.name}-${var.environment}-${replace(each.key, "_", "-")}"
    }
  }

  tags = {
    Name = "${var.name}-${var.environment}-${replace(each.key, "_", "-")}-lt"
  }
}


#subnet 정보 조회
#instance로 생성한 subnet의 정보를 조회하여 일치하는 subnet의 전체 정보 저장
data "aws_subnet" "nat" {
  for_each = var.instances

  id = var.public_subnet_ids[each.value.subnet]
}

#각 영역에 asg 하나씩 생성
resource "aws_autoscaling_group" "nat" {
  for_each = var.instances

  name = "${var.name}-${var.environment}-${replace(each.key, "_", "-")}-asg"

  # 고정 ENI와 같은 가용 영역
  availability_zones = [
    data.aws_subnet.nat[each.key].availability_zone
  ]

  # NAT 인스턴스 1대 유지
  min_size         = 1
  desired_capacity = 1
  max_size         = 1

  # EC2 상태를 기준으로 헬스 체크
  health_check_type         = "EC2"
  health_check_grace_period = 300

  # EC2 생성 설정
  launch_template {
    id      = aws_launch_template.nat[each.key].id
    version = aws_launch_template.nat[each.key].latest_version
  }

  # EIP와 ENI 연결을 먼저 완료
  depends_on = [
    aws_eip_association.nat
  ]
  # CloudWatch ASG 메트릭 활성화
  metrics_granularity = "1Minute"

  enabled_metrics = [
    "GroupInServiceInstances"
  ]

  tag {
    key                 = "Name"
    value               = "${var.name}-${var.environment}-${replace(each.key, "_", "-")}"
    propagate_at_launch = true
  }
}