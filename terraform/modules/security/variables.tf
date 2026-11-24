variable "name" {
  description = "프로젝트 이름"
  type        = string
}

variable "environment" {
  description = "배포 환경"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR (라우터 인바운드 허용 범위)"
  type        = string
}

variable "router_vpc_ingress_enabled" {
  description = "VPC → tailnet 경로를 쓸 때 라우터 SG에 VPC 인그레스를 열지 여부"
  type        = bool
  default     = false
}


variable "subnets" {
  description = "서브넷 정보"
  type = map(object({
    az     = string
    cidr   = string
    public = bool
  }))
}