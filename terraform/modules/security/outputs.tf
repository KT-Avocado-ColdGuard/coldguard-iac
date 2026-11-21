#nat instance security group 출력
output "nat_sg_id" {
  description = "NAT Security Group ID"

  value = aws_security_group.nat.id
}

#subnet router security group 출력
output "router_sg_id" {
  description = "Router Security Group ID"

  value = aws_security_group.router.id
}

