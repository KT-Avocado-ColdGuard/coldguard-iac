variable "name" {
  description = "프로젝트 이름"
  type        = string
}

variable "environment" {
  description = "개발 환경"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR"
  type        = string
}

variable "subnets" {
  description = "서브넷 구성"

  type = map(object({
    az     = string
    cidr   = string
    public = bool
  }))
}

variable "aws_region" {
  description = "aws 리전"
  type        = string
}