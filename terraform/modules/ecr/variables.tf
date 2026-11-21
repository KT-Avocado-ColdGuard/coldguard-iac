variable "name" {
  type = string
}

variable "environment" {
  type = string
}

variable "repository_names" {
  description = "ECR repository names"
  type        = set(string)

  default = ["app"]
}