# ColdGuard

ColdGuard의 AWS 인프라를 Terraform으로 생성하고 관리하는 방법입니다. 코드는 VPC, NAT 및 라우터 EC2, 장애 전환, EKS, ECR을 구성합니다.

## 문서 안내

| 문서 | 목적 |
|---|---|
| [변수 및 설정 가이드](docs/variables/README.md) | 입력 변수, `terraform.tfvars` 작성 방법과 변경 영향 |
| [프로젝트 구조 및 모듈 가이드](docs/structure/README.md) | 파일 구성, AWS 리소스, 모듈 연결 관계 |
| [Terraform 사용 가이드](#terraform-사용-가이드) | 설치부터 배포, EKS 초기 설정, 검증, 변경, 삭제까지의 작업 순서 |

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
| Git Bash | 아래 Bash 명령어와 EKS 초기 설정 스크립트 실행에 사용 |
| kubectl | Terraform 배포 후 EKS 및 Kubernetes 리소스 확인에 사용 |

Terraform, AWS CLI, Git, Git Bash, kubectl을 설치하고 명령어를 실행할 수 있는지 확인합니다. AWS 계정에는 코드가 선언한 EC2/VPC, IAM, Auto Scaling, Lambda, CloudWatch, EventBridge, SQS, SNS, EKS, ECR 리소스를 생성·변경·삭제할 권한이 필요합니다. 조직의 승인 및 비용 정책도 확인합니다.

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

### Step 3. 입력값 설정 및 공인 IP 등록

`terraform/`에서 예시 파일을 복사한 뒤 `terraform.tfvars`를 편집합니다.

```bash
cp terraform.tfvars.example terraform.tfvars
```

예시 파일에는 `instances`와 `eks_public_access_cidrs`가 포함되어 있습니다. `owner`의 예시 팀 이름, 네트워크 대역, 인스턴스 구성 및 공인 IP를 자신의 환경에 맞게 바꾸세요. `subnets`에는 코드가 직접 참조하는 `private_a`, `private_c`가 필요하고, NAT 장애 전환에는 `nat_a`, `nat_c` 인스턴스 키가 필요합니다. 두 NAT 인스턴스의 `subnet`은 각각 존재하는 Public Subnet 키를 가리켜야 합니다. 상세 예시와 타입은 [변수 및 설정 가이드](docs/variables/README.md)를 참조합니다.

#### 공인 IP 확인

EKS Kubernetes Public API 접근을 제한하는 `eks_public_access_cidrs`에는 실제 접속할 PC의 공인 IP가 필요합니다. Windows Git Bash에서 확인합니다.

```bash
curl -4 https://checkip.amazonaws.com
```

출력 예시입니다.

```text
203.0.113.10
```

`203.0.113.10`은 문서용 주소입니다. 실제 출력된 공인 IPv4 주소를 사용하세요.

#### terraform.tfvars에 공인 IP 등록

앞에서 복사한 `terraform.tfvars`의 기존 `eks_public_access_cidrs` 값을 수정합니다.

```hcl
eks_public_access_cidrs = ["203.0.113.10/32"]
```

| 항목 | 설명 |
|---|---|
| `eks_public_access_cidrs` | EKS Public API 접근 허용 IP 대역 |
| `203.0.113.10` | 사용자 공인 IP 예시이며 실제 값으로 교체해야 합니다. |
| `/32` | 단일 IPv4 주소만 허용합니다. |
| 설정 시점 | `terraform plan`, `terraform apply` 실행 전입니다. |
| IP 변경 시 | 변수 수정 후 Terraform 변경 계획을 확인하고 적용합니다. |

팀원이 각자의 AWS 계정에 배포한다면 각자 자신의 공인 IP를 설정해야 합니다. VPN이나 프록시를 사용하면 EKS API에 접속하는 출발지 공인 IP가 달라질 수 있으므로 해당 환경에서 확인하세요. `0.0.0.0/0`으로 모든 IP를 허용하지 마세요. 이 변수는 EKS Public API의 네트워크 접근만 제한하며 AWS 웹 콘솔 로그인 자체를 제한하지 않습니다. Public API 허용 IP에 들어 있더라도 IAM 및 Kubernetes 접근 권한이 별도로 필요합니다.

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
terraform output aws_region
terraform output eks_cluster_name
terraform output ecr_repository_urls
```

AWS CLI에서도 현재 리전의 EKS Cluster와 ECR Repository를 조회할 수 있습니다. 예시 이름의 `coldguard-prod`는 실제 `name` 및 `environment` 값으로 바꿉니다.

```bash
aws eks describe-cluster --region ap-northeast-2 --name coldguard-prod-eks --query 'cluster.status'
aws ecr describe-repositories --region ap-northeast-2 --query 'repositories[].repositoryName'
```

`terraform output`이 비어 있거나 AWS 조회가 실패하면 `apply`의 종료 결과, 현재 계정, 리전을 확인합니다. Kubernetes 매니페스트는 `kubernetes/`에 별도로 있으며 `terraform apply`가 적용하지 않습니다.

### Step 7. EKS 초기 설정 및 gp3 StorageClass 자동 적용

Terraform은 EKS 클러스터와 EBS CSI Driver Add-on을 생성합니다. `gp3` StorageClass는 `kubernetes/storageclass-gp3.yaml`로 별도 관리하므로, `terraform apply` 후 다음 스크립트로 적용합니다. 작업 위치는 계속 `terraform/`입니다.

| 항목 | 요구 사항 |
|---|---|
| Terraform | 설치 및 `terraform apply` 완료 |
| AWS CLI | 설치 및 배포한 AWS 계정으로 인증 완료 |
| kubectl | 설치 필요 |
| Git Bash | Bash 스크립트 실행 환경 |
| EKS 접근 권한 | IAM 및 Kubernetes 접근 권한 필요 |
| 공인 IP | 현재 PC의 출발지 공인 IP가 `eks_public_access_cidrs`에 허용되어 있어야 합니다. |

`terraform apply`가 끝났더라도 현재 PC의 공인 IP가 허용되지 않으면 `kubectl` 접속이 실패할 수 있습니다. 실행 전 Git Bash에서 `kubectl version --client`로 설치를 확인하고, Step 3에서 설정한 IP와 현재 IP를 비교하세요.

```bash
kubectl version --client
bash scripts/setup-eks.sh
```

스크립트는 다음 순서로 작업합니다.

1. Terraform Output `eks_cluster_name`과 `aws_region`을 읽습니다.
2. 현재 AWS 리전과 `aws sts get-caller-identity`의 인증 계정을 표시합니다.
3. `aws eks update-kubeconfig`로 스크립트를 실행하는 환경의 kubeconfig에 클러스터 접속 정보를 등록합니다.
4. 모든 EKS Worker Node가 Ready 상태가 될 때까지 기다립니다.
5. `kube-system`의 `ebs-csi-controller` Deployment 준비 상태를 확인합니다.
6. `kubectl apply -f kubernetes/storageclass-gp3.yaml`로 gp3 StorageClass를 적용합니다.
7. `kubectl get storageclass gp3`로 생성 결과를 확인합니다.

`aws eks update-kubeconfig`는 클러스터를 생성하지 않고, 명령을 실행한 PC 또는 환경의 kubeconfig에 접속 정보를 등록합니다. 일반적으로 `terraform apply`만으로 로컬 kubeconfig가 등록되지는 않습니다. 이 프로젝트에서는 스크립트가 해당 명령을 실행하므로 스크립트 실행 전에 별도로 등록할 필요가 없습니다. 스크립트 실행 환경에는 AWS CLI 인증과 EKS API 접근 권한이 있어야 합니다.

### Step 8. Argo CD 설치 및 접속

`setup-eks.sh`가 성공적으로 끝난 뒤, 같은 Git Bash에서 `terraform/` 디렉터리를 작업 위치로 유지합니다. `install-argocd.sh`는 Terraform 출력값으로 EKS 클러스터와 리전을 확인하고, Helm 차트로 Argo CD를 `argocd` 네임스페이스에 설치합니다. 실행 전에 `helm version`으로 Helm 설치 여부를 확인합니다.

```bash
helm version
bash scripts/install-argocd.sh
```

설치 결과는 다음 명령으로 확인합니다.

```bash
helm status argocd -n argocd
kubectl get pods -n argocd
kubectl get svc -n argocd
```

웹 UI에 접속하려면 별도의 Git Bash 창에서 포트 포워딩을 실행하고 `https://localhost:8080`을 엽니다. 사용자 이름은 `admin`이며, 초기 비밀번호는 아래 명령으로 확인합니다. 포트 포워딩 명령을 실행한 창은 접속하는 동안 열어 둡니다.

```bash
kubectl port-forward -n argocd svc/argocd-server 8080:443
```

```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

### Step 9. 인프라 및 Kubernetes 구성 검증

EKS를 관리하는 위치에 따라 kubeconfig가 필요한 곳이 달라집니다.

| 관리 방식 | kubeconfig 설정 | 설명 |
|---|---|---|
| AWS Management Console | 불필요 | 클러스터, Node Group, Add-on 상태를 조회합니다. |
| 로컬 PC의 kubectl | 필요 | Pod, Deployment, StorageClass 등 Kubernetes 리소스를 관리합니다. |
| `setup-eks.sh` 자동화 스크립트 | 스크립트에서 자동 설정 | kubeconfig 등록부터 gp3 적용까지 실행합니다. |
| AWS CloudShell | CloudShell 환경에서 설정 필요 | 로컬 PC의 kubeconfig 설정은 필요하지 않습니다. |
| Argo CD 및 CI/CD | 로컬 PC에서는 불필요 | 배포 시스템 자체에 클러스터 접근 설정이 필요합니다. |

**AWS 웹 콘솔에서 EKS 리소스 상태를 조회하는 것만으로는 로컬 kubeconfig 설정이 필요하지 않습니다.** 다만 gp3 StorageClass 적용에는 Kubernetes API 접근이 필요하며, `setup-eks.sh`가 kubeconfig 설정과 YAML 적용을 함께 처리합니다.

스크립트 실행 후 EKS Node와 시스템 Pod, StorageClass를 확인합니다.

```bash
kubectl get nodes -o wide
kubectl get pods -n kube-system
kubectl get storageclass
```

AWS CLI에서 실제 Terraform Output을 사용해 Add-on을 확인할 수도 있습니다. 예시 변수값이라면 리전은 `ap-northeast-2`, 클러스터 이름은 `coldguard-prod-eks`이지만 배포값에 따라 달라집니다.

```bash
REGION="$(terraform output -raw aws_region)"
CLUSTER_NAME="$(terraform output -raw eks_cluster_name)"
aws eks list-addons \
  --region "$REGION" \
  --cluster-name "$CLUSTER_NAME"
```

`kubernetes/storageclass-gp3.yaml`의 실제 설정은 다음과 같습니다.

| 항목 | 설정값 | 의미 |
|---|---|---|
| 이름 | `gp3` | 생성할 StorageClass 이름입니다. |
| Provisioner | `ebs.csi.aws.com` | EBS CSI Driver가 볼륨을 생성합니다. |
| EBS 유형 | `gp3` | gp3 EBS 볼륨을 사용합니다. |
| 바인딩 | `WaitForFirstConsumer` | Pod가 사용될 위치가 정해질 때 볼륨을 바인딩합니다. |
| 회수 정책 | `Delete` | 연결된 PVC 삭제 시 동적으로 생성된 볼륨을 삭제합니다. |
| 확장 허용 | `true` | 볼륨 크기 확장을 허용합니다. |

Terraform과 초기 설정 스크립트가 담당하는 작업 범위는 다음과 같습니다.

| 작업 | 관리 도구 | 담당 영역 |
|---|---|---|
| VPC, Subnet, NAT, IAM, EKS, ECR 생성 | Terraform | IaC |
| NAT 장애 전환 인프라 구성 | Terraform / Lambda | IaC |
| EKS 초기 kubeconfig 등록 | `setup-eks.sh` / AWS CLI | IaC 초기 설정 |
| gp3 StorageClass 적용 | `setup-eks.sh` / kubectl | IaC 초기 설정 |
| ECR 컨테이너 이미지 Build 및 Push | Docker / GitHub Actions | CI/CD |
| Kubernetes 애플리케이션 배포 | Helm / Argo CD / kubectl | CI/CD / Kubernetes |
| 실제 서비스 운영 및 모니터링 | AWS Console / Kubernetes / Grafana | 운영 담당 |

Terraform은 ECR Repository를 만들지만 이미지를 빌드하거나 업로드하지 않습니다. 애플리케이션의 Kubernetes 배포와 운영 구성도 별도 작업입니다.

### Step 10. 변수 변경 적용

`terraform.tfvars`를 수정한 뒤 새 계획을 검토하고 적용합니다. 특히 CIDR, Subnet, 인스턴스 사양 및 EKS API 허용 CIDR의 영향은 [변수 및 설정 가이드](docs/variables/README.md)에 정리했습니다.

```bash
terraform plan -out=tfplan
terraform apply tfplan
```

### Step 11. 리소스 삭제

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
| 필수 변수 입력 요청 또는 `No value for required variable` | `terraform.tfvars`에 9개 루트 변수가 모두 있는지 확인합니다. 예시 파일을 복사하고 환경별 값을 수정했는지 확인합니다. |
| `Invalid index` 또는 키 조회 오류 | `subnets`의 `private_a`·`private_c`, `instances`의 `nat_a`·`nat_c`, 인스턴스의 Public Subnet 참조를 확인합니다. |
| AWS 인증·권한 오류 | `aws sts get-caller-identity`, `AWS_PROFILE`, IAM 권한과 계정 정책을 확인합니다. |
| AZ/CIDR 충돌 | `aws_region`, Subnet AZ, VPC·Subnet CIDR의 포함 및 중복 여부를 확인합니다. |
| Provider 설치 실패 | 네트워크 접근과 `terraform init` 결과를 확인합니다. |
| State 잠금 또는 기존 리소스 충돌 | 같은 State를 사용하는 다른 작업을 확인하고, 올바른 State·계정·리전인지 검토합니다. State 파일을 임의 삭제하지 마세요. |
| EKS API 연결 시간 초과 또는 `kubectl` 연결 실패 | 현재 출발지 공인 IP가 `eks_public_access_cidrs`에 포함되는지, VPN·프록시 사용 여부와 클러스터 상태를 확인합니다. |
| kubeconfig 인증 오류 또는 `Unauthorized` | `aws sts get-caller-identity`로 계정을 확인하고 IAM 및 Kubernetes 접근 권한을 검토한 뒤 `bash scripts/setup-eks.sh`를 다시 실행합니다. |
| Node Ready 대기 또는 EBS CSI Driver 준비 실패 | `kubectl get nodes -o wide`, `kubectl get pods -n kube-system`, Add-on 상태를 확인합니다. 준비 실패 시 스크립트는 gp3 적용 전에 중단됩니다. |
| gp3 StorageClass 적용 실패 | kubeconfig와 Kubernetes 권한, EBS CSI Driver 준비 상태 및 `kubernetes/storageclass-gp3.yaml` 경로를 확인합니다. |

검증 명령을 실행했다고 해서 AWS 배포 성공이 보장되지는 않습니다. NAT 장애 전환의 과거 시험 결과는 [검증 기록](ColdGuard_Validation_README.md)에 따로 정리되어 있습니다.
