# Ubuntu 24.04 LTS AMI 조회
data "aws_ssm_parameter" "ubuntu_2404" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

#router 생성
resource "aws_instance" "router" {
  for_each = var.instances

  ami = (
    each.value.ami != null
    ? each.value.ami
    : data.aws_ssm_parameter.ubuntu_2404.value
  )

  instance_type = each.value.instance_type

  # Router 최초 부팅 시 자동 설정
  user_data = templatefile(
    "${path.module}/scripts/router-user-data.sh.tftpl",
    {}
  )

  iam_instance_profile = var.router_instance_profile_name

  # Public Subnet에 배치
  subnet_id = var.public_subnet_ids[each.value.subnet]

  # Router Security Group
  vpc_security_group_ids = [var.router_sg_id]

  # 공인 IP 자동 할당
  associate_public_ip_address = true

  # 다른 서버의 패킷을 전달할 수 있도록 설정
  source_dest_check = false

  # 운영체제 EBS
  root_block_device {
    volume_size           = each.value.volume_size
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  tags = {
    Name = "${var.name}-${var.environment}-${replace(each.key, "_", "-")}"
  }
}