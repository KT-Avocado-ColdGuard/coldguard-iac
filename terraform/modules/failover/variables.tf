variable "name" {
  description = "프로젝트 이름"
  type        = string
}

variable "environment" {
  description = "운영 환경"
  type        = string
}

variable "nat_asg_names" {
  description = "AZ별 NAT Auto Scaling Group 이름"
  type        = map(string)
}

# AWS 리전
variable "aws_region" {
  description = "Lambda가 AWS 리소스를 관리할 리전"
  type        = string
}

# Private Route Table ID
variable "private_route_table_ids" {
  description = "AZ별 Private Route Table ID 목록"
  type        = map(string)
}

# NAT 고정 ENI ID
variable "nat_eni_ids" {
  description = "AZ별 NAT ENI ID 목록"
  type        = map(string)
}

variable "lambda_role_arn" {
  description = "Failover Lambda IAM Role ARN"
  type        = string
}