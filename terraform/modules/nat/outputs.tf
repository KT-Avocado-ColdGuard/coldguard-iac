# nat  고정 eni ip 목록 출력
output "nat_eni_ids" {
  description = "NAT 고정 ENI ID 목록"

  value = {
    for key, eni in aws_network_interface.nat :
    key => eni.id
  }
}

# nat 고정 eip 목록 출력
output "nat_eip_ids" {
  description = "NAT 고정 EIP ID 목록(ex: eipalloc-12345678)"

  value = {
    for key, eip in aws_eip.nat :
    key => eip.id
  }
}

# nat 고정 아이피 주소 목록 출력
output "nat_public_ips" {
  description = "NAT Public IP 목록(ex: 203.0.113.10)"

  value = {
    for key, eip in aws_eip.nat :
    key => eip.public_ip
  }
}

# nat 오토스케일링 그룹 이름 출력
output "nat_asg_names" {
  description = "NAT Auto Scaling Group names"

  value = {
    for key, asg in aws_autoscaling_group.nat :
    key => asg.name
  }
}

# nat 시작 템플릿(launch_template) 아이디 출력
output "nat_launch_template_ids" {
  description = "NAT Launch Template IDs"

  value = {
    for key, lt in aws_launch_template.nat :
    key => lt.id
  }
}

