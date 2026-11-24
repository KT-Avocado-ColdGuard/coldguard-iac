variable "name" {
  description = "프로젝트 이름"
  type        = string
}

variable "environment" {
  description = "개발 환경"
  type        = string
}

variable "private_route_table_ids" {
  description = "Failover Lambda가 변경할 Private Route Table ID"
  type        = map(string)
}

# GitHub Actions 저장소
variable "github_repository" {
  description = "GitHub repository (OWNER/REPO)"
  type        = string
}

# GitHub Actions가 Push·Pull할 ECR Repository
variable "ecr_repository_arns" {
  description = "GitHub Actions가 Push·Pull할 ECR Repository ARN 목록"
  type        = list(string)
}
# KT 허브 상태 확인 지표 이름공간 (라우터 권한 제한)
variable "kt_hub_probe_namespace" {
  description = "라우터가 지표를 올릴 수 있는 CloudWatch 이름공간"
  type        = string
}

# 백업 CronJob이 쓸 버킷
variable "backup_bucket_arn" {
  description = "백업·내보내기 버킷 ARN"
  type        = string
}

# 시설 ECR Pull 전용 IAM 사용자
variable "onprem_sites" {
  description = "ECR Pull 전용 IAM 사용자를 만들 시설 이름 목록"
  type        = list(string)
}

variable "onprem_ecr_repository_arns" {
  description = "시설 K3s가 Pull할 ECR Repository ARN 목록"
  type        = list(string)
}
