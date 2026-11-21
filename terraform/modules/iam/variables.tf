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