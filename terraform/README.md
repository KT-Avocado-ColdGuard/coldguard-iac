# ColdGuard

ColdGuard의 AWS 인프라를 Terraform으로 생성하고 관리하는 방법입니다. 코드는 VPC, NAT 및 라우터 EC2, 장애 전환, EKS, ECR을 구성합니다.

## 문서 안내

| 문서 | 목적 |
|---|---|
| [변수 및 설정 가이드](docs/variables/README.md) | 입력 변수, `terraform.tfvars` 작성 방법과 변경 영향 |
| [프로젝트 구조 및 모듈 가이드](docs/structure/README.md) | 파일 구성, AWS 리소스, 모듈 연결 관계 |
| [Terraform 사용 가이드](#terraform-사용-가이드) | 설치부터 검증, 배포, 변경, 삭제까지의 작업 순서 |

기존 [NAT 장애 전환 검증 기록](ColdGuard_Validation_README.md)은 실제 수행한 테스트 결과와 한계를 별도로 기록합니다.

## Terraform 사용 가이드

### Step 1. 도구와 AWS 권한 준비

| 항목 | 요구 사항 |
|---|---|
| Terraform | `>= 1.0.0` (`versions.tf` 기준) |
| AWS Provider | `~> 6.0` (`terraform init`에서 설치) |
| Archive Provider | `~> 2.0` (`terraform init`에서 설치) |
| AWS CLI | CLI v2 권장; 계정 인증·배포 결과 확인에 사용 |
| Git | 저장소를 내려받을 때 사용 |

Terraform, AWS CLI, Git을 설치하고 실행 파일이 `PATH`에 있는지 확인합니다. AWS 계정에는 코드가 선언한 EC2/VPC, IAM, Auto Scaling, Lambda, CloudWatch, EventBridge, SQS, SNS, EKS, ECR 리소스를 생성·변경·삭제할 권한이 필요합니다. 조직의 승인 및 비용 정책도 확인합니다.

Git Bash에서 버전을 확인합니다.

```bash
terraform version
aws --version
git --version
```

AWS CLI 자격 증명을 설정합니다. SSO를 사용하는 조직이라면 조직에서 지정한 방식으로 로그인하고, 아래 `aws sts` 명령으로 현재 계정을 확인합니다. Access Key를 사용하는 경우에는 다음 명령을 실행하고 CLI 프롬프트에 값을 입력합니다.

```bash
aws configure
aws sts get-caller-identity
```

자격 증명을 `terraform.tfvars`에 넣지 마세요. AWS CLI 프로필을 쓴다면 실행 전에 `AWS_PROFILE`을 지정합니다.

### Step 2. 프로젝트 내려받기 및 이동

저장소 URL은 팀에서 제공받은 실제 URL로 지정합니다. 이미 코드를 받은 경우에는 `git clone`을 생략합니다. 다음 명령은 Git Bash 기준입니다.

```bash
REPOSITORY_URL="팀에서-제공받은-저장소-URL"
git clone "$REPOSITORY_URL" avocado
cd avocado/terraform
```

### Step 3. 입력값 설정

`terraform/`에서 예시 파일을 복사한 뒤 `terraform.tfvars`를 편집합니다.

```bash
cp terraform.tfvars.example terraform.tfvars
```

예시 파일에는 필수 변수 `instances`와 `eks_public_access_cidrs`가 없습니다. 두 값을 추가해야 합니다. `owner`의 `<담당자>`도 실제 담당자로 교체하세요. `subnets`에는 코드가 직접 참조하는 `private_a`, `private_c`가 필요하고, NAT 장애 전환에는 `nat_a`, `nat_c` 인스턴스 키가 필요합니다. 두 NAT 인스턴스의 `subnet`은 각각 존재하는 Public Subnet 키를 가리켜야 합니다. 상세 예시와 타입은 [변수 및 설정 가이드](docs/variables/README.md)를 참조합니다.

### Step 4. 초기화 및 코드 검증

작업 위치는 계속 `terraform/`입니다. `init`은 Provider와 모듈을 준비합니다.

```bash
terraform init
```

서식을 확인하고 구성의 정적 유효성을 검증합니다. `fmt -check`는 파일을 수정하지 않습니다.

```bash
terraform fmt -check -recursive
terraform validate
```

### Step 5. 변경 계획 확인

현재 인증 계정과 `aws_region`, CIDR, 생성·교체·삭제 리소스를 검토합니다. 처음 배포하는 작업 공간이라면 많은 리소스가 생성 대상으로 나타납니다.

```bash
terraform plan -out=tfplan
```

> **주의:** EKS, EC2, EBS, EIP 등은 비용이 발생할 수 있습니다. `plan` 결과에 예상하지 못한 삭제 또는 교체가 있으면 `apply` 전에 변수와 State를 확인하세요.

### Step 6. 인프라 배포

검토한 저장 계획을 적용합니다.

```bash
terraform apply tfplan
```

실행 후 루트 출력값을 확인합니다.

```bash
terraform output
terraform output eks_cluster_name
terraform output ecr_repository_urls
```

AWS CLI에서도 현재 리전의 EKS Cluster와 ECR Repository를 조회할 수 있습니다. 예시 이름의 `coldguard-prod`는 실제 `name` 및 `environment` 값으로 바꿉니다.

```bash
aws eks describe-cluster --region ap-northeast-2 --name coldguard-prod-eks --query 'cluster.status'
aws ecr describe-repositories --region ap-northeast-2 --query 'repositories[].repositoryName'
```

`terraform output`이 비어 있거나 AWS 조회가 실패하면 `apply`의 종료 결과, 현재 계정, 리전을 확인합니다. Kubernetes 매니페스트는 `kubernetes/`에 별도로 있으며 `terraform apply`가 적용하지 않습니다.

### Step 7. 변수 변경 적용

`terraform.tfvars`를 수정한 뒤 새 계획을 검토하고 적용합니다. 특히 CIDR, Subnet, 인스턴스 사양 및 EKS API 허용 CIDR의 영향은 [변수 및 설정 가이드](docs/variables/README.md)에 정리했습니다.

```bash
terraform plan -out=tfplan
terraform apply tfplan
```

### Step 8. 리소스 삭제

삭제 계획을 먼저 확인하고 필요할 때 실행합니다.

```bash
terraform plan -destroy
terraform destroy
```

> **주의:** 이 명령은 해당 State가 관리하는 인프라를 삭제합니다. 서비스 중단과 데이터 손실 가능성이 있습니다. ECR은 `force_delete = true`이므로 이미지가 있어도 Repository가 삭제될 수 있습니다. 콘솔에서 별도로 만든 리소스는 Terraform이 삭제하지 않을 수 있습니다.

## State 관리

`backend.tf`에는 원격 Backend 설정이 없습니다. 현재 구성은 기본 로컬 State를 사용합니다. `terraform.tfstate`, `terraform.tfstate.backup`, 저장된 계획 파일에는 민감한 정보가 포함될 수 있으므로 공유하거나 새로 커밋하지 마세요. 팀 작업 전에는 State 저장·잠금 방식을 합의하고, 동일한 State를 동시에 수정하지 않아야 합니다. 기존 State를 버리고 새 작업 공간에서 `apply`하면 기존 리소스와 충돌하거나 중복 생성될 수 있습니다.

## 자주 발생하는 오류

| 증상 | 확인 및 해결 |
|---|---|
| 필수 변수 입력 요청 또는 `No value for required variable` | `terraform.tfvars`에 9개 루트 변수가 모두 있는지 확인합니다. 예시 파일에 없는 `instances`, `eks_public_access_cidrs`를 추가합니다. |
| `Invalid index` 또는 키 조회 오류 | `subnets`의 `private_a`·`private_c`, `instances`의 `nat_a`·`nat_c`, 인스턴스의 Public Subnet 참조를 확인합니다. |
| AWS 인증·권한 오류 | `aws sts get-caller-identity`, `AWS_PROFILE`, IAM 권한과 계정 정책을 확인합니다. |
| AZ/CIDR 충돌 | `aws_region`, Subnet AZ, VPC·Subnet CIDR의 포함 및 중복 여부를 확인합니다. |
| Provider 설치 실패 | 네트워크 접근과 `terraform init` 결과를 확인합니다. |
| State 잠금 또는 기존 리소스 충돌 | 같은 State를 사용하는 다른 작업을 확인하고, 올바른 State·계정·리전인지 검토합니다. State 파일을 임의 삭제하지 마세요. |

검증 명령을 실행했다고 해서 AWS 배포 성공이 보장되지는 않습니다. NAT 장애 전환의 과거 시험 결과는 [검증 기록](ColdGuard_Validation_README.md)에 따로 정리되어 있습니다.
