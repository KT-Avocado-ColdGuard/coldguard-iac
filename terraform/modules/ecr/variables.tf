variable "name" {
  type = string
}

variable "environment" {
  type = string
}

variable "repository_names" {
  description = "ECR repository names (<name>-<environment>- 뒤에 붙는 이름)"
  type        = set(string)
}