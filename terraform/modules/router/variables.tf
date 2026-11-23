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
  description = "Public Subnet IDs"
  type        = map(string)
}

variable "router_sg_id" {
  description = "Router Security Group ID"
  type        = string
}

variable "router_instance_profile_name" {
  description = "IAM Instance Profile name for Router EC2"
  type        = string
}

variable "private_route_table_ids" {
  description = "Tailscale 경로를 추가할 Private Route Table ID"
  type        = map(string)
}

variable "routed_cidrs" {
  description = "서브넷 라우터로 보낼 목적지 CIDR"
  type        = list(string)
}
