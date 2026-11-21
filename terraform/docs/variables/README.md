# ColdGuard 변수 및 설정 가이드

## 변수의 역할

루트 `variables.tf`는 배포마다 달라지는 이름, AWS 리전, 네트워크, EC2 사양, EKS API 접근 범위를 입력으로 받습니다. 같은 모듈 코드를 재사용하면서 환경별 값만 `terraform.tfvars`로 지정할 수 있습니다. 모듈 입력값은 루트 `main.tf`가 전달하므로 일반 사용자는 루트 변수만 설정합니다.

## 루트 변수 목록

`variables.tf`의 9개 변수 모두 `default`가 없으므로 필수입니다. `availability_zones`는 현재 코드에서 선언되어 있으나 리소스나 모듈 입력에 참조되지 않습니다. AZ 배치는 `subnets[*].az`가 결정합니다.

| 변수명 | 타입 | 기본값 | 필수 여부 | 설명 |
|---|---|---|---|---|
| `name` | `string` | 없음 | 예 | 리소스 이름 접두어에 쓰는 프로젝트명 |
| `owner` | `string` | 없음 | 예 | AWS Provider의 공통 `Owner` 태그. 공백 문자열은 검증 오류 |
| `vpc_cidr` | `string` | 없음 | 예 | VPC IPv4 CIDR 및 NAT 전환 스크립트의 내부망 범위 |
| `environment` | `string` | 없음 | 예 | 리소스 이름과 `Env` 태그에 쓰는 환경명 |
| `aws_region` | `string` | 없음 | 예 | AWS Provider 리전과 S3 VPC Endpoint 서비스명 |
| `availability_zones` | `list(string)` | 없음 | 예 | 현재 선언만 되어 있고 리소스에는 미반영 |
| `subnets` | `map(object)` | 없음 | 예 | Subnet별 AZ, CIDR, Public 여부 |
| `instances` | `map(object)` | 없음 | 예 | `nat_` 및 `router_`로 시작하는 EC2 구성 |
| `eks_public_access_cidrs` | `list(string)` | 없음 | 예 | EKS Public API Endpoint에 허용할 IPv4 CIDR |

### `subnets` 객체 속성

| 속성 | 타입 | 필수 여부 | 설명 |
|---|---|---|---|
| 맵 키 | `string` | 예 | 코드가 `private_a`, `private_c`를 직접 참조합니다. NAT 경로의 `private_` → `nat_` 키 변환에도 쓰입니다. |
| `az` | `string` | 예 | Subnet의 Availability Zone |
| `cidr` | `string` | 예 | VPC CIDR에 포함되는 Subnet CIDR. 서로 중복되지 않아야 합니다. |
| `public` | `bool` | 예 | `true`이면 Public Subnet, `false`이면 Private Subnet |

### `instances` 객체 속성

| 속성 | 타입 | 필수 여부 | 설명 |
|---|---|---|---|
| 맵 키 | `string` | 예 | `nat_` 또는 `router_` 접두어로 모듈을 선택합니다. Failover는 `nat_a`, `nat_c`를 직접 참조합니다. |
| `subnet` | `string` | 예 | `subnets`의 Public Subnet 키. NAT·Router 모듈 모두 Public Subnet ID에서 조회합니다. |
| `instance_type` | `string` | 예 | EC2 인스턴스 유형 |
| `volume_size` | `number` | 예 | Root EBS `gp3` 크기(GiB) |
| `ami` | `string` | 아니요 | 생략하면 SSM의 Ubuntu 24.04 AMI ID를 사용합니다. |

## `terraform.tfvars`에 값 할당

`terraform/`에서 `terraform.tfvars.example`을 복사해 편집합니다. Terraform은 이 파일을 자동으로 읽습니다. 아래는 **구조를 보여 주는 예시**이며 CIDR, 담당자, EKS API 접근 범위는 실제 환경에 맞게 결정해야 합니다. 기존 `terraform.tfvars.example`에는 `instances`와 `eks_public_access_cidrs`가 빠져 있으므로 반드시 추가하세요.

```hcl
name               = "coldguard"
owner              = "team-owner"
environment        = "prod"
aws_region         = "ap-northeast-2"
vpc_cidr           = "10.0.0.0/16"
availability_zones = ["ap-northeast-2a", "ap-northeast-2c"]

subnets = {
  public_a  = { az = "ap-northeast-2a", cidr = "10.0.1.0/24",  public = true }
  public_c  = { az = "ap-northeast-2c", cidr = "10.0.2.0/24",  public = true }
  private_a = { az = "ap-northeast-2a", cidr = "10.0.3.0/24",  public = false }
  private_c = { az = "ap-northeast-2c", cidr = "10.0.12.0/24", public = false }
}

instances = {
  nat_a    = { subnet = "public_a", instance_type = "t3.micro", volume_size = 10 }
  nat_c    = { subnet = "public_c", instance_type = "t3.micro", volume_size = 10 }
  router_a = { subnet = "public_a", instance_type = "t3.micro", volume_size = 10 }
}

eks_public_access_cidrs = ["203.0.113.10/32"]
```

`203.0.113.10/32`는 문서용 예시 주소입니다. 실제 관리자 공인 IP/CIDR로 교체해야 EKS Public API에 접근할 수 있습니다. `owner`에는 실제 담당자를 입력하세요. AMI를 직접 지정하려면 해당 인스턴스 객체에 `ami = "ami-..."`를 추가하고 대상 리전에서 사용 가능한지 확인합니다.

## 변수 변경과 리소스 영향

| 변수 | 주로 영향을 받는 리소스·동작 |
|---|---|
| `name`, `environment` | VPC, EC2, IAM, EKS, ECR, Failover 리소스 이름과 태그. 이름 변경은 교체를 유발할 수 있습니다. |
| `owner` | Provider 공통 `Owner` 태그 변경 |
| `vpc_cidr` | VPC CIDR 및 NAT `iptables` 사용자 데이터. 네트워크 재구성이 필요할 수 있습니다. |
| `aws_region` | Provider 대상 리전 및 S3 Endpoint 서비스명. 기존 State를 다른 리전에서 재사용하기 전에 계획을 면밀히 확인해야 합니다. |
| `availability_zones` | 현재 리소스 영향 없음. 실제 AZ는 `subnets[*].az`로 설정합니다. |
| `subnets` | Public/Private Subnet, Route Table, NAT/Router 배치, NAT Security Group 허용 CIDR, EKS Subnet. 키·CIDR·AZ 변경은 교체나 참조 오류를 유발할 수 있습니다. |
| `instances` | `nat_` 항목은 ENI/EIP/Launch Template/ASG, `router_` 항목은 EC2를 구성합니다. 크기·AMI·디스크 변경은 인스턴스 교체 또는 갱신을 유발할 수 있습니다. |
| `eks_public_access_cidrs` | EKS Public API Endpoint의 허용 CIDR 목록 |

EKS Node Group의 인스턴스 타입과 디스크 크기는 루트 `main.tf`에서 `t3.medium`, `20`으로 전달하고, 크기 조절 값은 모듈 `main.tf`에서 3으로 고정합니다. 이 항목들은 현재 루트 `terraform.tfvars`로 조절할 수 없습니다. ECR Repository 이름도 루트 `main.tf`에서 `app`으로 전달합니다. 변경 전에는 [사용 가이드](../../README.md#step-7-변수-변경-적용)의 `terraform plan`을 확인하세요.
