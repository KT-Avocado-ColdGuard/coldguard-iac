#vpc id 출력
output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

#public subnet id 출력
output "public_subnet_ids" {
  description = "Public Subnet IDs"

  value = {
    for key, subnet in aws_subnet.public_subnet :
    key => subnet.id
  }
}

#private subnet id 출력
output "private_subnet_ids" {
  description = "Private Subnet IDs"

  value = {
    for key, subnet in aws_subnet.private_subnet :
    key => subnet.id
  }
}

#internet gateway id 출력
output "igw_id" {
  description = "Internet Gateway ID"

  value = aws_internet_gateway.main.id
}

#public route table id 출력
output "public_route_table_id" {
  description = "Public Route Table ID"

  value = aws_route_table.public.id
}

#private route table id 출력
output "private_route_table_ids" {
  description = "Private Route Table IDs"

  value = {
    for key, rt in aws_route_table.private :
    key => rt.id
  }
}

#s3 vpc endpoint id 출력
output "s3_vpc_endpoint_id" {
  description = "S3 VPC Endpoint ID"

  value = aws_vpc_endpoint.s3.id
}

