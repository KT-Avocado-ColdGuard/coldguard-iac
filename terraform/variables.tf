variable "name" {
  description = "프로젝트 이름"
  type        = string
}

variable "owner" {
  description = "AWS 리소스의 Owner 태그에 사용할 실제 담당자"
  type        = string

  validation {
    condition     = length(trimspace(var.owner)) > 0
    error_message = "owner에는 실제 담당자를 입력해야 합니다."
  }
}

variable "vpc_cidr" {
  description = "VPC CIDR"
  type        = string
}

variable "environment" {
  description = "개발 환경"
  type        = string
}

variable "aws_region" {
  description = "aws 리전"
  type        = string
}

variable "availability_zones" {
  description = "가용 영역"
  type        = list(string)
}

variable "subnets" {
  description = "서브넷 구성"

  type = map(object({
    az     = string
    cidr   = string
    public = bool
  }))
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

variable "eks_public_access_cidrs" {
  description = "Allowed IPv4 CIDRs for EKS public API endpoint"
  type        = list(string)
}