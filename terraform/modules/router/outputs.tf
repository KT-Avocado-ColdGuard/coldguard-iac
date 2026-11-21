#라우터 인스턴스 아이디 목록
output "router_instance_ids" {
  description = "Router EC2 Instance IDs"

  value = {
    for key, instance in aws_instance.router :
    key => instance.id
  }
}

#라우터 사설 ip 목록
output "router_private_ips" {
  description = "Router EC2 Private IPs"

  value = {
    for key, instance in aws_instance.router :
    key => instance.private_ip
  }
}

#라우터 공인 ip 목록
output "router_public_ips" {
  description = "Router EC2 Public IPs"

  value = {
    for key, instance in aws_instance.router :
    key => instance.public_ip
  }
}