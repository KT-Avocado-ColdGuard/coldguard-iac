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

variable "eks_node_group" {
  description = "EKS Managed Node Group 사양과 노드 수"

  type = object({
    instance_type = string
    disk_size     = number
    desired_size  = number
    min_size      = number
    max_size      = number
  })
}

variable "github_repository" {
  description = "GitHub Actions repository"
  type        = string
}

variable "eks_public_access_enabled" {
  description = "EKS Public API Endpoint 사용 여부. Tailscale 접속 확인 후 false로 바꿉니다."
  type        = bool
  default     = true
}

variable "eks_cluster_admin_arns" {
  description = "EKS 관리자 권한을 줄 IAM 사용자·Role ARN 목록 (apply하는 사람은 제외)"
  type        = list(string)
  default     = []
}

variable "eks_cluster_viewer_arns" {
  description = "EKS 조회 전용 권한(AmazonEKSViewPolicy)을 줄 IAM 사용자·Role ARN 목록"
  type        = list(string)
  default     = []
}

variable "router_routed_cidrs" {
  description = "Private Subnet에서 서브넷 라우터로 보낼 목적지 CIDR (비우면 VPC → tailnet 경로와 라우터 SG의 VPC 인그레스를 만들지 않음)"
  type        = list(string)
  default     = []
}

variable "backup_service_account" {
  description = "백업·이력 내보내기 CronJob의 Kubernetes Namespace와 ServiceAccount"

  type = object({
    namespace = string
    name      = string
  })

  default = {
    namespace = "coldguard"
    name      = "s3-backup"
  }
}

variable "alert_email" {
  description = "AWS 내부 알림을 받을 이메일. 비워 두면 구독을 만들지 않습니다."
  type        = string
  default     = ""
}
