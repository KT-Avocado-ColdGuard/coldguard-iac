#VPC 생성
resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr

  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.name}-${var.environment}-vpc"
  }
}

#서브넷 생성 - public
resource "aws_subnet" "public_subnet" {
  #public = true인 서브넷만 생성
  for_each = {
    for key, subnet in var.subnets :
    key => subnet if subnet.public
  }

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.name}-${var.environment}-${split("_", each.key)[0]}-subnet-${split("_", each.key)[1]}"

    "kubernetes.io/role/elb" = "1"
  }
}

#서브넷 생성 - private
resource "aws_subnet" "private_subnet" {
  #public = false인 서브넷만 생성
  for_each = {
    for key, subnet in var.subnets :
    key => subnet if !subnet.public
  }

  vpc_id            = aws_vpc.main.id
  cidr_block        = each.value.cidr
  availability_zone = each.value.az

  tags = {
    Name = "${var.name}-${var.environment}-${split("_", each.key)[0]}-subnet-${split("_", each.key)[1]}"

    "kubernetes.io/role/internal-elb" = "1"
  }
}

#Internet Gateway 생성
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.name}-${var.environment}-igw"
  }
}

#public Route Table 생성 
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.name}-${var.environment}-public-rt"
  }
}

#public route table에 0.0.0.0/0 -> Internet Gateway 연결
resource "aws_route" "public_default" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

#public route table과 public subnet 연결
resource "aws_route_table_association" "public" {
  #위에서 생성한 public subnet만 연결
  for_each = aws_subnet.public_subnet

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

#private route table 생성
resource "aws_route_table" "private" {
  #private subnet에 각각 생성
  for_each = aws_subnet.private_subnet

  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.name}-${var.environment}-private-rt-${split("_", each.key)[1]}"
  }
}

#private route table와 private subnet 연결
resource "aws_route_table_association" "private" {
  #위에서 생성한 private subnet만 연결
  for_each = aws_subnet.private_subnet

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id
}

#vpc_endpoint 생성 -> instance에서 바로 s3에 접근 가능하도록
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"

  route_table_ids = [
  for rt in aws_route_table.private : rt.id]

  tags = {
    Name = "${var.name}-${var.environment}-s3-vpce"
  }
}