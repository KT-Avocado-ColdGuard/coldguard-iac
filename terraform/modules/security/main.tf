#nat instance security group 생성
resource "aws_security_group" "nat" {
  name        = "${var.name}-${var.environment}-nat-sg"
  description = "Security group for NAT instances"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name}-${var.environment}-nat-sg"
  }
}

#subnet router security group 생성
resource "aws_security_group" "router" {
  name        = "${var.name}-${var.environment}-router-sg"
  description = "Security group for Tailscale subnet router"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name}-${var.environment}-router-sg"
  }

}

#nat instance security group 인바운드 규칙, private subnet에서 오는 트래픽 허용
resource "aws_vpc_security_group_ingress_rule" "nat_private" {
  for_each = {
    for key, subnet in var.subnets :
    key => subnet if !subnet.public
  }

  security_group_id = aws_security_group.nat.id

  description = "Allow traffic from ${each.key}"

  cidr_ipv4   = each.value.cidr
  ip_protocol = "-1"
}

#nat instance security group 아웃바운드 규칙
resource "aws_vpc_security_group_egress_rule" "nat_all" {
  security_group_id = aws_security_group.nat.id

  description = "Allow all outbound traffic"

  cidr_ipv4   = "0.0.0.0/0"
  ip_protocol = "-1"
}

#subnet router security group 인바운드 규칙, udp 41641 포트 허용
resource "aws_vpc_security_group_ingress_rule" "router_tailscale" {
  security_group_id = aws_security_group.router.id

  description = "Allow Tailscale traffic on UDP port 41641"

  from_port   = 41641
  to_port     = 41641
  ip_protocol = "udp"
  cidr_ipv4   = "0.0.0.0/0"
}

#subnet router security group 아웃바운드 규칙, 모든 트래픽 허용
resource "aws_vpc_security_group_egress_rule" "router_all" {
  security_group_id = aws_security_group.router.id

  description = "Allow outbound traffic"

  cidr_ipv4   = "0.0.0.0/0"
  ip_protocol = "-1"
}

#subnet router security group 인바운드 규칙, VPC 내부에서 tailnet으로 나가는 트래픽 허용
#Private Route Table이 tailnet 대역을 라우터 ENI로 보내므로, 패킷이 라우터 SG를 통과해야 합니다.
resource "aws_vpc_security_group_ingress_rule" "router_from_vpc" {
  security_group_id = aws_security_group.router.id

  description = "Allow VPC traffic routed to tailnet"

  cidr_ipv4   = var.vpc_cidr
  ip_protocol = "-1"
}
