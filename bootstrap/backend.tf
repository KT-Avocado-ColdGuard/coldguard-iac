# EKS 내부 구성(Bootstrap) State 저장소
#
# AWS 인프라와 같은 버킷을 쓰고 key만 나눕니다.
terraform {
  backend "s3" {
    bucket       = "coldguard-prod-tfstate-1q2w3e4r"
    key          = "bootstrap/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
