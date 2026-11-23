
variable "name" {
  type = string
}

variable "environment" {
  type = string
}

variable "cluster_role_arn" {
  type = string
}

variable "node_role_arn" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "public_access_cidrs" {
  description = "CIDRs allowed to access the public EKS API endpoint"
  type        = list(string)
}

variable "node_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "node_disk_size" {
  type    = number
  default = 20
}

variable "node_desired_size" {
  type    = number
  default = 3
}

variable "node_min_size" {
  type    = number
  default = 3
}

variable "node_max_size" {
  type    = number
  default = 3
}

variable "ebs_csi_role_arn" {
  description = "IAM Role ARN for EBS CSI Driver Pod Identity"
  type        = string
}

variable "public_access_enabled" {
  description = "EKS Public API Endpoint 사용 여부"
  type        = bool
  default     = true
}

variable "cluster_admin_arns" {
  description = "클러스터 관리자 권한을 줄 IAM 사용자·Role ARN (클러스터 생성자 제외)"
  type        = list(string)
  default     = []
}

variable "pod_identity_associations" {
  description = "Pod Identity 연결 목록"

  type = map(object({
    namespace       = string
    service_account = string
    role_arn        = string
  }))

  default = {}
}

variable "router_sg_id" {
  description = "Kubernetes API 443 접근을 허용할 서브넷 라우터 Security Group ID"
  type        = string
}
