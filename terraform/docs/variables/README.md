# ColdGuard 변수 및 설정 가이드

## 변수의 역할

루트 `variables.tf`는 배포마다 달라지는 이름, AWS 리전, 네트워크, EC2 사양, EKS 노드 사양, EKS API 접근 범위, GitHub Actions 저장소를 입력으로 받습니다. 같은 모듈 코드를 재사용하면서 환경별 값만 `terraform.tfvars`로 지정할 수 있습니다. 모듈 입력값은 루트 `main.tf`가 전달하므로 일반 사용자는 루트 변수만 설정합니다.

## 루트 변수 목록

`variables.tf`에는 필수 변수 10개와 기본값이 있는 선택 변수 6개가 있습니다. AZ 배치는 `subnets[*].az`가 결정합니다.

### 필수 변수

| 변수명 | 타입 | 필수 여부 | 설명 |
|---|---|---|---|
| `name` | `string` | 예 | 리소스 이름 접두어에 쓰는 프로젝트명 |
| `owner` | `string` | 예 | AWS Provider의 공통 `Owner` 태그. 공백 문자열은 검증 오류 |
| `environment` | `string` | 예 | 리소스 이름과 `Env` 태그에 쓰는 환경명 |
| `aws_region` | `string` | 예 | AWS Provider 리전과 S3 VPC Endpoint 서비스명 |
| `vpc_cidr` | `string` | 예 | VPC IPv4 CIDR. NAT `iptables` 사용자 데이터의 내부망 범위로도 쓰입니다. |
| `subnets` | `map(object)` | 예 | Subnet별 AZ, CIDR, Public 여부 |
| `instances` | `map(object)` | 예 | `nat_` 및 `router_`로 시작하는 EC2 구성 |
| `eks_public_access_cidrs` | `list(string)` | 예 | EKS Public API Endpoint에 허용할 IPv4 CIDR |
| `eks_node_group` | `object` | 예 | EKS Managed Node Group의 인스턴스 유형, 디스크 크기, 노드 수 |
| `github_repository` | `string` | 예 | ECR에 이미지를 Push·Pull할 GitHub 저장소(`OWNER/REPO`). `main` 브랜치의 워크플로만 Role을 맡을 수 있습니다. |

### 선택 변수

| 변수명 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `eks_cluster_admin_arns` | `list(string)` | `[]` | EKS 관리자 권한(Access Entry)을 줄 IAM ARN. apply하는 사람은 자동으로 관리자이므로 넣지 않습니다. |
| `eks_cluster_viewer_arns` | `list(string)` | `[]` | EKS 조회 전용 권한(Access Entry, `AmazonEKSViewPolicy`)을 줄 IAM ARN. Secret 값은 볼 수 없습니다. IAM Identity Center 역할은 경로를 포함한 ARN 그대로 넣습니다. |
| `eks_public_access_enabled` | `bool` | `true` | EKS Public API Endpoint 사용 여부. Tailscale 접속 확인 후 `false`로 바꿉니다. `false`이면 `eks_public_access_cidrs`는 적용되지 않지만, 라우터 장애 때 다시 `true`로 켜서 비상 접속할 주소로 남겨 둡니다. |
| `alert_email` | `string` | `""` | AWS 내부 알림 SNS 이메일 구독. 비워 두면 구독을 만들지 않습니다. |
| `router_routed_cidrs` | `list(string)` | `[]` | Private Route Table에서 서브넷 라우터 ENI로 보낼 목적지 CIDR. 값을 넣으면 라우터 SG에 VPC 인그레스도 함께 열립니다. EKS의 tailnet 송신은 operator egress를 쓰므로 기본값은 비어 있습니다. |
| `backup_service_account` | `object` | `coldguard` / `s3-backup` | 백업 CronJob에 S3 권한을 연결할 Namespace와 ServiceAccount |

`alert_email`에 넣는 개인 이메일은 `terraform.tfvars`에만 두고 커밋하지 않습니다.

### `subnets` 객체 속성

| 속성 | 타입 | 필수 여부 | 설명 |
|---|---|---|---|
| 맵 키 | `string` | 예 | 코드가 `private_a`, `private_c`를 직접 참조합니다. NAT 경로의 `private_` → `nat_` 키 변환에도 쓰입니다. |
| `az` | `string` | 예 | Subnet의 Availability Zone |
| `cidr` | `string` | 예 | VPC CIDR에 포함되는 Subnet CIDR. 서로 겹치지 않아야 합니다. |
| `public` | `bool` | 예 | `true`이면 Public Subnet, `false`이면 Private Subnet |

### `instances` 객체 속성

| 속성 | 타입 | 필수 여부 | 설명 |
|---|---|---|---|
| 맵 키 | `string` | 예 | `nat_` 또는 `router_` 접두어로 모듈을 선택합니다. Failover는 `nat_a`, `nat_c`를 직접 참조합니다. |
| `subnet` | `string` | 예 | `subnets`의 Public Subnet 키. NAT·Router 모듈 모두 Public Subnet ID에서 조회합니다. |
| `instance_type` | `string` | 예 | EC2 인스턴스 유형 |
| `volume_size` | `number` | 예 | Root EBS `gp3` 크기(GiB) |
| `ami` | `string` | 아니요 | 생략하면 SSM의 Ubuntu 24.04 AMI ID를 사용합니다. |

### `eks_node_group` 객체 속성

| 속성 | 타입 | 설명 |
|---|---|---|
| `instance_type` | `string` | Worker Node 인스턴스 유형 |
| `disk_size` | `number` | Worker Node Root EBS 크기(GiB) |
| `desired_size` | `number` | 유지할 노드 수 |
| `min_size` | `number` | 최소 노드 수 |
| `max_size` | `number` | 최대 노드 수 |

노드 자동 확장은 사용하지 않으므로 세 값을 같게 둡니다. 작업하지 않는 시간에 노드를 내리려면 `desired_size`와 `min_size`를 `0`으로 바꿔 적용하고, 다시 쓸 때 원래 값으로 되돌립니다. `max_size`는 EKS 제약상 1 이상이어야 하므로 그대로 둡니다.

## `terraform.tfvars`에 값 할당

`terraform/`에서 `terraform.tfvars.example`을 복사해 편집합니다. Terraform은 이 파일을 자동으로 읽습니다. 아래는 현재 ColdGuard 설계값입니다. 담당자와 EKS API 접근 IP는 실제 값으로 바꿔야 합니다.

```hcl
name        = "coldguard"
owner       = "team-owner"
environment = "prod"
aws_region  = "ap-northeast-2"
vpc_cidr    = "10.80.0.0/16"

subnets = {
  public_a  = { az = "ap-northeast-2a", cidr = "10.80.0.0/24",  public = true }
  public_c  = { az = "ap-northeast-2c", cidr = "10.80.1.0/24",  public = true }
  private_a = { az = "ap-northeast-2a", cidr = "10.80.16.0/20", public = false }
  private_c = { az = "ap-northeast-2c", cidr = "10.80.32.0/20", public = false }
}

instances = {
  nat_a    = { subnet = "public_a", instance_type = "t3.micro", volume_size = 10 }
  nat_c    = { subnet = "public_c", instance_type = "t3.micro", volume_size = 10 }
  router_a = { subnet = "public_a", instance_type = "t3.micro", volume_size = 10 }
}

eks_public_access_cidrs = ["203.0.113.10/32"]

eks_node_group = {
  instance_type = "t3.medium"
  disk_size     = 20
  desired_size  = 3
  min_size      = 3
  max_size      = 3
}

github_repository = "KT-Avocado-ColdGuard/coldguard-apps"
```

`203.0.113.10/32`는 문서용 예시 주소입니다. 실제 관리자 공인 IP/CIDR로 바꿔야 EKS Public API에 접근할 수 있습니다. `owner`에는 실제 담당자를 입력하세요. AMI를 직접 지정하려면 해당 인스턴스 객체에 `ami = "ami-..."`를 추가하고 대상 리전에서 사용할 수 있는지 확인합니다.

## 변수 변경과 리소스 영향

| 변수 | 주로 영향을 받는 리소스·동작 |
|---|---|
| `name`, `environment` | VPC, EC2, IAM, EKS, ECR, Failover 리소스 이름과 태그. 이름 변경은 교체를 일으킬 수 있습니다. |
| `owner` | Provider 공통 `Owner` 태그 변경 |
| `vpc_cidr` | VPC CIDR 및 NAT `iptables` 사용자 데이터. 네트워크 재구성이 필요할 수 있습니다. |
| `aws_region` | Provider 대상 리전 및 S3 Endpoint 서비스명. 기존 State를 다른 리전에서 재사용하기 전에 계획을 꼼꼼히 확인해야 합니다. |
| `subnets` | Public/Private Subnet, Route Table, NAT/Router 배치, NAT Security Group 허용 CIDR, EKS Subnet. 키·CIDR·AZ 변경은 교체나 참조 오류를 일으킬 수 있습니다. |
| `instances` | `nat_` 항목은 ENI/EIP/Launch Template/ASG, `router_` 항목은 EC2를 구성합니다. 크기·AMI·디스크 변경은 인스턴스 교체 또는 갱신을 일으킬 수 있습니다. |
| `eks_public_access_cidrs` | EKS Public API Endpoint의 허용 CIDR 목록 |
| `eks_node_group` | 노드 수 변경은 Node Group 갱신으로 반영됩니다. 인스턴스 유형이나 디스크 크기 변경은 노드를 새로 만들어 교체합니다. |
| `github_repository` | GitHub Actions Role의 신뢰 조건. 저장소 이름이 다르면 워크플로가 Role을 맡지 못합니다. |
| `eks_cluster_admin_arns` | Access Entry와 관리자 정책 연결을 추가·삭제합니다. |
| `eks_cluster_viewer_arns` | Access Entry와 조회 정책 연결을 추가·삭제합니다. |
| `eks_public_access_enabled` | EKS Endpoint 설정 갱신. 끄면 Tailscale을 거치지 않는 `kubectl`과 Bootstrap 실행이 막힙니다. |
| `alert_email` | SNS 이메일 구독 생성·삭제 |
| `router_routed_cidrs` | Private Route Table의 서브넷 라우터 경로와 라우터 SG의 VPC 인그레스 추가·삭제 |
| `backup_service_account` | Pod Identity 연결 교체. 매니페스트의 Namespace·ServiceAccount와 같아야 합니다. |

ECR Repository 목록과 시설 목록은 변수가 아니라 루트 `locals.tf`에서 정합니다. `ecr_eks_repositories`(`control-api`, `central-worker`)와 `ecr_onprem_repositories`(`collector`, `controller`, `field-web`)가 합쳐져 `<name>-<environment>-<이름>` Repository가 됩니다. GitHub Actions Role은 모든 Repository에 Push·Pull할 수 있고, `onprem_sites`(`site01`, `site02`, MQTT·DB의 `site_id`와 같은 값)의 시설별 IAM 사용자는 `ecr_onprem_repositories`만 Pull할 수 있습니다. 변경 전에는 [사용 가이드](../../../README.md#step-11-terraform-변수-변경-적용)의 순서대로 `terraform plan`을 확인하세요.
