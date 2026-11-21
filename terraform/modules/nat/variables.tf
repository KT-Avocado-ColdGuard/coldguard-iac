variable "name" {
  description = "프로젝트 이름"
  type        = string
}

variable "environment" {
  description = "배포 환경"
  type        = string
}

variable "instances" {
  description = "EC2 인스턴스 구성"

  type = map(object({
    subnet        = string
    instance_type = string
    volume_size   = number
    ami           = optional(string)
  }))
}

variable "public_subnet_ids" {
  description = "퍼블릭 서브넷 ID 목록"
  type        = map(string)
}

variable "nat_sg_id" {
  description = "NAT Security Group ID"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR for NAT rules"
  type        = string
}

variable "nat_instance_profile_name" {
  description = "IAM Instance Profile name for NAT EC2"
  type        = string
}