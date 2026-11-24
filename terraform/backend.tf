# AWS 인프라 State 저장소
#
# 버킷은 Terraform 밖에서 한 번만 만듭니다. Terraform은 자기 State를 담는 버킷을 관리할 수 없습니다.
# 생성 설정은 README의 "State 관리"를 참조합니다.
# backend 블록에는 변수를 쓸 수 없으므로 값을 직접 적습니다.
terraform {
  backend "s3" {
    bucket       = "coldguard-prod-tfstate-1q2w3e4r"
    key          = "terraform/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
