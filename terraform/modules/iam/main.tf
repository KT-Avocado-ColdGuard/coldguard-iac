# AWS 계정 및 리전 정보 조회
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
