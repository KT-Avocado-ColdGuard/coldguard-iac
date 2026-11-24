variable "name" {
  description = "프로젝트 이름"
  type        = string
}

variable "environment" {
  description = "배포 환경"
  type        = string
}

# 알림 이메일. 비워 두면 구독을 만들지 않습니다.
variable "alert_email" {
  description = "SNS 알림을 받을 이메일 주소"
  type        = string
  default     = ""
}

# 서브넷 라우터가 KT 허브를 확인해 올리는 지표 이름공간
variable "kt_hub_probe_namespace" {
  description = "KT 허브 상태 확인 지표의 CloudWatch 이름공간"
  type        = string
  default     = "ColdGuard/KTHub"
}

# 확인 대상 구성 요소. 지표의 Component 차원 값과 같아야 합니다.
variable "kt_hub_components" {
  description = "KT 허브에서 상태를 확인할 구성 요소"
  type        = set(string)
  default     = ["prometheus", "alertmanager", "loki", "grafana"]
}
