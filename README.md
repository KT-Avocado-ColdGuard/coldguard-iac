# ColdGuard

ColdGuard의 AWS 인프라와 EKS 내부 구성을 Terraform으로 생성하고 관리하는 방법입니다. 최상위의 `terraform/`과 `bootstrap/`은 별도의 Terraform Root Module이며, 각각 독립적으로 실행하고 별도의 State를 사용합니다. Bootstrap은 EKS 클러스터나 Worker Node를 새로 생성하지 않습니다.

| 디렉터리 | 관리 대상 | 주요 역할 |
|---|---|---|
| `terraform/` | AWS 인프라 | VPC, Subnet, NAT, 라우터 EC2, IAM, EKS, ECR, 백업 버킷, 알림 및 장애 전환 관련 AWS 리소스를 생성·관리합니다. |
| `bootstrap/` | 기존 EKS 내부 리소스 | gp3 StorageClass를 생성하고 Helm으로 Argo CD를 설치합니다. |

## 문서 안내

| 문서 | 목적 |
|---|---|
| [변수 및 설정 가이드](terraform/docs/variables/README.md) | 입력 변수, `terraform.tfvars` 작성 방법과 변경 영향 |
| [프로젝트 구조 및 모듈 가이드](terraform/docs/structure/README.md) | 파일 구성, AWS 리소스, 모듈 연결 관계 |
| [Terraform 사용 가이드](#terraform-사용-가이드) | 설치부터 AWS 인프라·Bootstrap 배포, 검증, 변경, 삭제까지의 작업 순서 |

기존 [NAT 장애 전환 검증 기록](terraform/ColdGuard_Validation_README.md)은 실제 수행한 테스트 결과와 한계를 별도로 기록합니다.

## Terraform 사용 가이드

### Step 1. 도구와 AWS 권한 준비

| 항목 | 요구 사항 |
|---|---|
| Terraform | `>= 1.10.0` (`terraform/versions.tf`, `bootstrap/versions.tf` 기준. S3 Backend 잠금 파일 기능에 필요) |
| AWS Provider | `~> 6.0` (`terraform init`에서 설치) |
| Archive Provider | `~> 2.0` (`terraform init`에서 설치) |
| Kubernetes Provider | `~> 3.0` (`bootstrap/terraform init`에서 설치) |
| Helm Provider | `~> 3.0` (`bootstrap/terraform init`에서 설치) |
| AWS CLI | CLI v2 권장; 계정 인증·배포 결과 확인에 사용 |
| Git | 저장소를 내려받을 때 사용 |
| Git Bash | 아래 Bash 명령어와 선택적 EKS 연결 스크립트 실행에 사용 |
| kubectl | 로컬 PC에서 EKS 및 Kubernetes 리소스를 확인할 때 사용 |

Terraform, AWS CLI, Git, Git Bash를 설치하고 명령어를 실행할 수 있는지 확인합니다. `kubectl`은 Step 10의 로컬 EKS 연결을 사용할 때 설치합니다. AWS 계정에는 코드가 선언한 EC2/VPC, IAM, Auto Scaling, Lambda, CloudWatch, EventBridge, SQS, SNS, EKS, ECR 리소스를 생성·변경·삭제할 권한이 필요합니다. 조직의 승인 및 비용 정책도 확인합니다.

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

### Step 2. GitHub 프로젝트 다운로드

저장소 URL은 팀에서 제공받은 실제 URL로 지정합니다. 이미 코드를 받은 경우에는 `git clone`을 생략합니다. 다음 명령은 Git Bash 기준이며, 이 문서의 모든 경로는 저장소를 `C:\Avocado`에 받았다고 가정합니다. 다른 위치에 받았다면 `/c/Avocado` 부분을 실제 경로로 바꾸세요.

```bash
REPOSITORY_URL="팀에서-제공받은-저장소-URL"
cd /c
git clone "$REPOSITORY_URL" Avocado
cd /c/Avocado/terraform
```

### Step 3. Terraform 입력값 및 공인 IP 설정

`terraform/`에서 예시 파일을 복사한 뒤 `terraform.tfvars`를 편집합니다.

```bash
cp terraform.tfvars.example terraform.tfvars
```

예시 파일에는 필수 변수 10개가 모두 들어 있고, 선택 변수는 주석으로 적혀 있습니다. `owner`의 예시 팀 이름, 네트워크 대역, 인스턴스와 EKS 노드 구성, 공인 IP, GitHub 저장소를 자신의 환경에 맞게 바꾸세요. `subnets`에는 코드가 직접 참조하는 `private_a`, `private_c`가 필요하고, NAT 장애 전환에는 `nat_a`, `nat_c` 인스턴스 키가 필요합니다. 두 NAT 인스턴스의 `subnet`은 각각 존재하는 Public Subnet 키를 가리켜야 합니다. 상세 예시와 타입은 [변수 및 설정 가이드](terraform/docs/variables/README.md)를 참조합니다.

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

#### 선택 변수

다음 변수는 기본값이 있어 비워 둬도 동작합니다. 필요한 경우 `terraform.tfvars`에 추가합니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `eks_cluster_admin_arns` | `[]` | EKS 관리자 권한을 줄 IAM ARN. **apply하는 사람은 자동으로 관리자가 되므로 넣지 않습니다.** 같은 ARN을 넣으면 이미 존재한다는 오류가 납니다. |
| `eks_public_access_enabled` | `true` | Tailscale로 private endpoint 접속을 확인한 뒤 `false`로 바꿉니다. 서브넷 라우터 장애 시 다시 `true`로 바꿔 비상 접속합니다. |
| `alert_email` | `""` | AWS 내부 알림(NAT 장애 전환, Lambda 오류, KT 허브 상태)을 받을 이메일. apply 후 받은 메일에서 구독을 확인해야 알림이 옵니다. |
| `router_routed_cidrs` | `["100.64.0.0/10"]` | Private Subnet에서 서브넷 라우터로 보낼 목적지. 온프렘 대역을 서브넷 라우터로 직접 받는다면 추가합니다. |
| `backup_service_account` | `coldguard` / `s3-backup` | 백업 CronJob의 Namespace와 ServiceAccount. 매니페스트와 이름이 같아야 S3 권한을 받습니다. |

### Step 4. AWS 인프라 Terraform 초기화 및 검증

작업 위치는 계속 `terraform/`입니다. `init`은 Provider와 모듈을 준비하고 S3 Backend에 연결합니다. State 버킷이 먼저 있어야 합니다([State 관리](#state-관리) 참조).

```bash
terraform init
```

서식을 확인하고 구성의 정적 유효성을 검증합니다. `fmt -check`는 파일을 수정하지 않습니다.

```bash
terraform fmt -check -recursive
terraform validate
```

### Step 5. AWS 인프라 변경 계획 확인

현재 인증 계정과 `aws_region`, CIDR, 생성·교체·삭제 리소스를 검토합니다. 처음 배포하는 작업 공간이라면 많은 리소스가 생성 대상으로 나타납니다.

```bash
terraform plan -out=tfplan
```

> **주의:** EKS, EC2, EBS, EIP 등은 비용이 발생할 수 있습니다. `plan` 결과에 예상하지 못한 삭제 또는 교체가 있으면 `apply` 전에 변수와 State를 확인하세요.

### Step 6. AWS 인프라 Terraform Apply

Git Bash에서 AWS 인프라 Terraform 작업 위치로 이동해 초기화, 검증, 변경 계획 확인 후 저장한 계획을 적용합니다. Step 4와 Step 5에서 이미 실행했다면 `init`과 `validate`를 다시 실행해도 됩니다. `plan` 결과를 검토한 뒤 `apply`하세요.

```bash
cd /c/Avocado/terraform

terraform init
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

첫 번째 `terraform apply`가 정상적으로 끝나면 AWS 인프라와 EKS 클러스터가 준비됩니다. **이 단계가 성공한 뒤에만 Bootstrap Terraform을 실행하세요.** 실행 후 루트 출력값을 확인합니다. EKS 클러스터 이름은 `terraform output -raw eks_cluster_name`으로 확인할 수 있습니다.

```bash
terraform output
terraform output aws_region
terraform output eks_cluster_name
terraform output -raw eks_cluster_name
terraform output ecr_repository_urls
```

#### apply 후 수동 작업

| 작업 | 방법 |
|---|---|
| 알림 메일 구독 확인 | `alert_email`을 넣었다면 AWS에서 온 메일의 **Confirm subscription**을 누릅니다. 누르지 않으면 알림이 오지 않습니다. |
| Grafana 액세스 키 발급 | IAM 콘솔에서 `terraform output grafana_user_name` 사용자의 액세스 키를 발급해 KT Grafana의 CloudWatch 데이터 소스에 넣습니다. 비밀값이 State에 남지 않도록 Terraform으로 만들지 않습니다. |
| 서브넷 라우터 Tailscale 가입 | 라우터 SG에는 SSH가 열려 있지 않습니다. SSM Session Manager로 접속하거나 Ansible의 SSM 연결로 가입시키고, 광고한 경로(`10.80.0.0/16`)는 Tailscale 관리 콘솔에서 승인합니다. |

AWS CLI에서도 현재 리전의 EKS Cluster와 ECR Repository를 조회할 수 있습니다. 예시 이름의 `coldguard-prod`는 실제 `name` 및 `environment` 값으로 바꿉니다.

```bash
aws eks describe-cluster --region ap-northeast-2 --name coldguard-prod-eks --query 'cluster.status'
aws ecr describe-repositories --region ap-northeast-2 --query 'repositories[].repositoryName'
```

`terraform output`이 비어 있거나 AWS 조회가 실패하면 `apply`의 종료 결과, 현재 계정, 리전을 확인합니다. gp3 StorageClass와 Argo CD는 다음 Bootstrap Terraform에서 생성합니다.

### Step 7. Bootstrap Terraform 변수 설정

AWS 인프라 Terraform의 첫 번째 Apply가 성공한 후 기존 EKS 클러스터 이름을 확인합니다. Bootstrap은 별도의 Terraform 실행 환경이며, 새로운 EKS 클러스터나 Worker Node를 만들지 않습니다.

```bash
cd /c/Avocado/terraform
terraform output -raw eks_cluster_name
```

프로젝트 최상위의 Bootstrap 폴더 구성은 다음과 같습니다.

```text
Avocado/
├── terraform/
└── bootstrap/
    ├── versions.tf
    ├── provider.tf
    ├── variables.tf
    ├── main.tf
    ├── outputs.tf
    └── terraform.tfvars.example
```

두 Root Module의 변수 파일은 독립적으로 관리합니다. `terraform/terraform.tfvars`의 값은 `bootstrap/`으로 자동 전달되지 않습니다.

| 파일 | 역할 |
|---|---|
| `terraform/terraform.tfvars` | AWS 인프라 변수 할당 |
| `terraform/terraform.tfvars.example` | AWS 인프라 변수 예시 |
| `bootstrap/terraform.tfvars` | Bootstrap 변수 할당 |
| `bootstrap/terraform.tfvars.example` | Bootstrap 변수 예시 |

Bootstrap 예시 파일을 복사하여 `bootstrap/terraform.tfvars`를 편집합니다.

```bash
cd /c/Avocado/bootstrap
cp terraform.tfvars.example terraform.tfvars
```

`aws_region`은 AWS 리전, `eks_cluster_name`은 연결할 기존 EKS 클러스터 이름, `argocd_chart_version`은 Argo CD Helm Chart 버전입니다. 앞의 두 변수는 필수이며, 차트 버전의 코드 기본값은 `10.15.0`입니다. 예시 설정은 다음과 같습니다. `eks_cluster_name`은 앞에서 확인한 AWS 인프라 Terraform의 출력값과 **정확히 일치**해야 합니다. 리전과 차트 버전도 실제 배포 환경 및 코드에 맞게 확인하세요.

```hcl
aws_region           = "ap-northeast-2"
eks_cluster_name     = "coldguard-prod-eks"
argocd_chart_version = "10.15.0"
```

Bootstrap의 Kubernetes Provider와 Helm Provider는 기존 EKS의 엔드포인트와 인증서를 조회하고 AWS CLI의 `eks get-token`으로 Kubernetes API에 직접 연결합니다. 로컬 kubeconfig를 사용하지 않으므로 Bootstrap 실행 전에 `setup-eks.sh`를 실행할 필요가 없습니다. AWS CLI 설치와 계정 인증, EKS 내부 리소스 생성에 필요한 IAM·Kubernetes 권한, Step 3의 `eks_public_access_cidrs`에 허용된 공인 IP에서의 EKS Public API 접근은 필요합니다. 연결이 실패하면 출발지 IP와 인증 권한을 확인하세요.

### Step 8. Bootstrap Terraform 초기화 및 Apply

작업 위치는 프로젝트 최상위의 `bootstrap/`입니다. AWS 인프라 생성과 EKS 준비가 완료된 뒤 실행합니다. 변경 계획에서 gp3 StorageClass와 Argo CD Helm Release가 생성되는지 확인한 뒤 적용합니다.

```bash
cd /c/Avocado/bootstrap

terraform init
terraform fmt -check -recursive
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

| 리소스 | 생성 방식 |
|---|---|
| gp3 StorageClass | Terraform Kubernetes Provider |
| Argo CD 3.6.1 | Terraform Helm Provider (Helm Chart `10.15.0`, 설정은 `bootstrap/values/argocd.yaml`) |

gp3 StorageClass의 설정은 다음과 같습니다.

| 항목 | 설정값 | 의미 |
|---|---|---|
| 이름 | `gp3` | 생성할 StorageClass 이름입니다. |
| Provisioner | `ebs.csi.aws.com` | EBS CSI Driver가 볼륨을 생성합니다. |
| EBS 유형 | `gp3` | gp3 EBS 볼륨을 사용합니다. |
| 바인딩 | `WaitForFirstConsumer` | Pod가 사용될 위치가 정해질 때 볼륨을 바인딩합니다. |
| 회수 정책 | `Delete` | 연결된 PVC 삭제 시 동적으로 생성된 볼륨을 삭제합니다. |
| 확장 허용 | `true` | 볼륨 크기 확장을 허용합니다. |

Argo CD는 EKS Worker Node에서 Kubernetes Pod로 실행되며, AWS EKS Control Plane에 직접 설치되지 않습니다. Argo CD 서버 서비스는 `ClusterIP`이므로 외부 LoadBalancer를 생성하지 않습니다.

| Argo CD 구성 | 설정 | 이유 |
|---|---|---|
| HA | 사용 안 함 | 노드 3대 규모에서는 과합니다. |
| ApplicationSet | 컨트롤러 0개 | 시설별 구성은 Ansible로 찍어 냅니다. 차트가 컨트롤러를 항상 만들기 때문에 개수를 0으로 둡니다. |
| Notifications | 사용 | 배포 결과를 Slack으로 보냅니다. Slack 토큰이 준비되면 values 파일의 주석을 풉니다. |
| Dex | 사용 | GitHub 로그인용입니다. OAuth App이 준비되면 values 파일의 주석을 풉니다. |
| Controller 지표 | 사용 | Prometheus Agent가 8082 지표를 수집합니다. |

### Step 9. 배포 결과 검증

Bootstrap Terraform의 출력값으로 대상 클러스터, gp3 StorageClass 이름, Argo CD 네임스페이스 및 Helm Chart 버전을 확인합니다. 이 명령에는 로컬 kubeconfig가 필요하지 않습니다.

```bash
cd /c/Avocado/bootstrap
terraform output
```

AWS CLI에서도 인프라 Terraform의 출력값을 사용해 EKS Add-on을 확인할 수 있습니다. 예시 리전과 클러스터 이름은 실제 배포값에 따라 달라집니다.

```bash
cd /c/Avocado/terraform
REGION="$(terraform output -raw aws_region)"
CLUSTER_NAME="$(terraform output -raw eks_cluster_name)"
aws eks list-addons \
  --region "$REGION" \
  --cluster-name "$CLUSTER_NAME"
```

로컬 PC에서 Node, Argo CD Pod, gp3 StorageClass 및 실제 Argo CD 서버 이미지 버전을 직접 확인하려면 Step 10에 따라 `setup-eks.sh`로 로컬 연결을 설정한 뒤 `kubectl` 명령을 실행합니다.

### Step 10. 로컬 EKS 연결 및 관리 (선택)

AWS 인프라와 Bootstrap Terraform Apply, AWS 웹 콘솔에서 EKS 상태 조회에는 `setup-eks.sh`가 필요하지 않습니다. 로컬 PC에서 `kubectl`을 사용하거나 Argo CD 웹 UI에 로컬 포트 포워딩으로 접속하려면 kubeconfig 설정이 필요합니다.

| 상황 | `setup-eks.sh` 필요 여부 |
|---|---|
| AWS 인프라 Terraform Apply | 불필요 |
| Bootstrap Terraform Apply | 불필요 |
| AWS 웹 콘솔에서 EKS 클러스터 상태 조회 | 불필요 |
| 로컬 PC에서 `kubectl`로 EKS 접근 | kubeconfig 설정 필요 |
| 스크립트를 이용한 로컬 접속 설정 및 검증 | 선택적으로 실행 |
| Argo CD 웹 UI에 로컬 포트 포워딩으로 접근 | 로컬 `kubectl` 연결 필요 |

`setup-eks.sh`는 인프라 Terraform 출력값에서 클러스터 이름과 리전을 읽고, AWS CLI 인증 계정을 표시한 뒤 `aws eks update-kubeconfig`로 로컬 kubeconfig를 등록합니다. 이어 Worker Node Ready 상태와 EBS CSI Driver 준비 상태를 확인합니다. gp3 StorageClass는 생성하지 않습니다.

스크립트가 kubeconfig를 등록하므로 `aws eks update-kubeconfig`를 별도로 실행할 필요는 없습니다. 다만 AWS CLI 인증, EKS API 네트워크 접근 및 Kubernetes 권한이 필요합니다. VPN·프록시를 사용한다면 실제 출발지 공인 IP가 Step 3에서 허용한 IP와 같은지 확인하세요.

Git Bash에서 `kubectl` 설치를 확인하고 스크립트를 실행합니다. 성공한 뒤 로컬에서 Kubernetes 리소스와 Argo CD 서버 이미지 버전을 확인합니다.

```bash
cd /c/Avocado/terraform
kubectl version --client
bash scripts/setup-eks.sh

kubectl get nodes -o wide
kubectl get pods -n argocd
kubectl get storageclass gp3
```

```bash
kubectl get deployment argocd-server \
  -n argocd \
  -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
```

Argo CD 웹 UI에 접속하려면 별도의 Git Bash 창에서 다음 명령을 실행하고 `https://localhost:8080`을 엽니다. 접속하는 동안 포트 포워딩 창을 열어 두세요. 사용자 이름은 `admin`입니다.

```bash
kubectl port-forward \
  -n argocd \
  svc/argocd-server \
  8080:443
```

초기 비밀번호는 로컬 `kubectl` 연결이 설정된 창에서 확인합니다.

```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

#### 테스트 매니페스트 (선택)

`tests/`에는 배포 후 동작을 직접 확인할 때 쓰는 매니페스트가 있습니다. Terraform과 Bootstrap은 이 파일을 적용하지 않으며, 확인이 끝나면 삭제합니다.

| 파일 | 확인 내용 |
|---|---|
| `tests/ebs-test.yaml` | gp3 StorageClass로 PVC가 만들어지고 Pod에 마운트되는지 확인합니다. |
| `tests/nat-failover-test.yaml` | AZ A 노드의 Pod가 2초마다 외부 출구 IP를 출력합니다. NAT 장애 전환 중 출구 IP가 바뀌는지 확인합니다. |

```bash
cd /c/Avocado
kubectl apply -f tests/ebs-test.yaml
kubectl get pvc gp3-test-pvc
kubectl exec gp3-test-pod -- cat /data/test.txt
kubectl delete -f tests/ebs-test.yaml
```

Terraform은 ECR Repository를 만들지만 이미지를 빌드하거나 업로드하지 않습니다. 애플리케이션의 Kubernetes 배포와 운영 구성도 별도 작업입니다.

| 작업 | 관리 도구 | 담당 영역 |
|---|---|---|
| VPC, Subnet, NAT, IAM, EKS, ECR 생성 | AWS 인프라 Terraform | IaC |
| NAT 장애 전환 인프라 구성 | AWS 인프라 Terraform / Lambda | IaC |
| gp3 StorageClass 적용 | Bootstrap Terraform / Kubernetes Provider | EKS 내부 구성 |
| Argo CD 설치 | Bootstrap Terraform / Helm Provider | EKS 내부 구성 |
| 로컬 kubeconfig 등록 및 EKS 상태 확인 | `setup-eks.sh` / AWS CLI / kubectl | 선택적 로컬 관리 |
| ECR 컨테이너 이미지 Build 및 Push | Docker / GitHub Actions | CI/CD |
| Kubernetes 애플리케이션 배포 | Helm / Argo CD / kubectl | CI/CD / Kubernetes |
| 실제 서비스 운영 및 모니터링 | AWS Console / Kubernetes / Grafana | 운영 담당 |

### Step 11. Terraform 변수 변경 적용

AWS 인프라 변수는 `terraform/terraform.tfvars`, EKS 내부 구성 변수는 `bootstrap/terraform.tfvars`에서 각각 변경합니다. 특히 AWS 인프라의 CIDR, Subnet, 인스턴스 사양 및 EKS API 허용 CIDR의 영향은 [변수 및 설정 가이드](terraform/docs/variables/README.md)에 정리했습니다. 변경한 폴더의 State와 계획을 검토한 뒤 해당 폴더에서 적용하세요.

```bash
cd /c/Avocado/terraform
terraform plan -out=tfplan
terraform apply tfplan
```

Bootstrap 변수를 변경한 경우에는 다음 명령을 사용합니다.

```bash
cd /c/Avocado/bootstrap
terraform plan -out=tfplan
terraform apply tfplan
```

### Step 12. 리소스 삭제 (Bootstrap → AWS 인프라)

두 Terraform State가 독립적이므로 생성 순서의 반대로 삭제합니다. **반드시 Bootstrap 리소스를 먼저 삭제하세요.** 삭제 계획을 확인한 뒤에만 `terraform destroy`를 실행합니다.

#### 12-1. Bootstrap 리소스 삭제

```bash
cd /c/Avocado/bootstrap

terraform plan -destroy
terraform destroy
```

Argo CD Helm Release와 gp3 StorageClass를 삭제합니다.

#### 12-2. AWS 인프라 삭제

Bootstrap 삭제가 정상적으로 끝난 뒤 AWS 인프라 Terraform 폴더로 이동합니다.

```bash
cd /c/Avocado/terraform

terraform plan -destroy
terraform destroy
```

EKS, ECR, EC2, NAT, VPC 등 AWS 인프라를 삭제합니다. EKS를 먼저 삭제하면 Bootstrap Terraform이 Kubernetes API에 접속하지 못해 내부 리소스 삭제가 실패할 수 있습니다. 실제 PVC, EBS 볼륨 및 서비스 데이터가 있다면 삭제 전에 보존 여부를 확인하세요. Argo CD가 GitOps로 배포한 애플리케이션과 관련 AWS 리소스도 먼저 정리해야 할 수 있습니다. State 파일을 임의로 삭제하지 마세요.

> **주의:** 삭제는 서비스 중단과 데이터 손실을 일으킬 수 있습니다. ECR(`force_delete`)과 백업 버킷(`force_destroy`)은 안에 이미지나 객체가 남아 있어도 함께 삭제됩니다. 콘솔에서 별도로 만든 리소스는 Terraform이 삭제하지 않습니다.

#### 12-3. State 버킷 삭제 (프로젝트 종료 시)

State 버킷은 Terraform 밖에서 만들었으므로 마지막에 콘솔에서 직접 삭제합니다. 12-1과 12-2가 모두 끝난 뒤에만 진행합니다. 버전 관리가 켜져 있어 이전 버전까지 비워야 삭제할 수 있습니다.

1. S3 콘솔에서 `coldguard-prod-tfstate-1q2w3e4r`를 선택하고 **비우기**를 실행합니다. 이전 버전도 함께 삭제됩니다.
2. 비운 버킷을 **삭제**합니다.

#### 12-4. 종료 정리 체크리스트

Terraform 밖에서 만든 것은 직접 지워야 비용이 남지 않습니다.

- [ ] 검증용으로 콘솔에서 만든 EventBridge 규칙, SQS, EC2, Security Group
- [ ] CloudWatch Logs 로그 그룹 (`/aws/lambda/...`, EKS가 만든 로그 그룹)
- [ ] EKS가 만든 EBS 볼륨 중 남은 것 (`kubernetes.io/created-for/pvc/name` 태그)
- [ ] Tailscale 관리 콘솔의 장치(서브넷 라우터)와 auth key
- [ ] State 버킷 (12-3)

## State 관리

State는 S3 버킷 `coldguard-prod-tfstate-1q2w3e4r`에 저장하고, 같은 버킷의 잠금 파일(`use_lockfile`)로 동시 실행을 막습니다. 누가 `plan`을 실행하든 같은 State를 보므로 PC마다 State가 갈라지지 않습니다.

| State 위치 (S3 key) | 관리 대상 |
|---|---|
| `terraform/terraform.tfstate` | VPC, NAT, IAM, EKS, ECR, 백업 버킷, 알림 등 AWS 인프라 |
| `bootstrap/terraform.tfstate` | gp3 StorageClass 및 Argo CD Helm Release |

두 State는 독립적입니다. AWS 인프라 State가 Bootstrap State의 리소스를 자동으로 관리하지 않습니다.

### State 버킷 (최초 1회, 콘솔에서 생성)

Terraform은 자기 State를 담는 버킷을 관리할 수 없으므로 이 버킷만 콘솔에서 만듭니다. `backend` 블록은 변수를 쓸 수 없어 버킷 이름을 `backend.tf`에 직접 적습니다. 그래서 계정 ID가 이름에 들어가지 않도록 글로벌 네임스페이스로 만들었습니다.

| 항목 | 설정 |
|---|---|
| 리전 | `ap-northeast-2` |
| 네임스페이스 | 글로벌 |
| 객체 소유권 | ACL 비활성화 |
| 퍼블릭 액세스 차단 | 4개 모두 차단 |
| 버전 관리 | 활성화 (State가 깨졌을 때 이전 버전으로 복구) |
| 기본 암호화 | SSE-S3, 버킷 키 비활성화 |
| 객체 잠금 | 비활성화 |
| 수명 주기 | 이전 버전 30일 후 삭제 |
| 버킷 정책 | HTTPS가 아닌 요청 거부 |
| 태그 | `Project=ColdGuard`, `Env=prod`, `ManagedBy=Manual` |

### 주의

- **apply는 한 사람만 합니다.** 잠금 파일이 동시 실행은 막지만, 서로 다른 브랜치의 코드로 번갈아 apply하면 리소스가 왔다 갔다 합니다. 다른 사람은 `plan`으로 확인만 합니다.
- State에는 리소스 ID와 일부 설정값이 평문으로 들어 있습니다. 버킷 접근 권한을 넓히지 마세요.
- 로컬에 남은 `terraform.tfstate`, `tfplan` 파일은 `.gitignore`로 제외됩니다. 커밋하지 마세요.

## 자주 발생하는 오류

| 증상 | 확인 및 해결 |
|---|---|
| 필수 변수 입력 요청 또는 `No value for required variable` | `terraform.tfvars`에 필수 루트 변수 10개가 모두 있는지 확인합니다. 예시 파일을 복사하고 환경별 값을 수정했는지 확인합니다. |
| `Invalid index` 또는 키 조회 오류 | `subnets`의 `private_a`·`private_c`, `instances`의 `nat_a`·`nat_c`, 인스턴스의 Public Subnet 참조를 확인합니다. |
| AWS 인증·권한 오류 | `aws sts get-caller-identity`, `AWS_PROFILE`, IAM 권한과 계정 정책을 확인합니다. |
| AZ/CIDR 충돌 | `aws_region`, Subnet AZ, VPC·Subnet CIDR의 포함 및 중복 여부를 확인합니다. |
| Provider 설치 실패 | 네트워크 접근과 `terraform init` 결과를 확인합니다. |
| `Error acquiring the state lock` | 다른 사람이 `plan`이나 `apply`를 실행 중입니다. 끝날 때까지 기다립니다. 실행하던 사람의 작업이 비정상 종료되어 잠금이 남았다면, 그 사람과 확인한 뒤에만 `terraform force-unlock <LOCK_ID>`를 실행합니다. |
| `init` 중 S3 접근 오류 | State 버킷 이름·리전, AWS 자격 증명과 S3 권한을 확인합니다. |
| EKS API 연결 시간 초과 또는 `kubectl` 연결 실패 | 현재 출발지 공인 IP가 `eks_public_access_cidrs`에 포함되는지, VPN·프록시 사용 여부와 클러스터 상태를 확인합니다. |
| kubeconfig 인증 오류 또는 `Unauthorized` | `aws sts get-caller-identity`로 계정을 확인하고 IAM 및 Kubernetes 접근 권한을 검토한 뒤 `bash scripts/setup-eks.sh`를 다시 실행합니다. |
| Node Ready 대기 또는 EBS CSI Driver 준비 실패 | `kubectl get nodes -o wide`, `kubectl get pods -n kube-system`, Add-on 상태를 확인합니다. `setup-eks.sh`는 준비 확인 중 실패하면 중단됩니다. |
| Bootstrap의 EKS API 연결 또는 인증 실패 | Bootstrap 변수의 클러스터 이름과 리전, 현재 공인 IP의 `eks_public_access_cidrs` 허용 여부, AWS CLI 인증 및 IAM·Kubernetes 권한을 확인합니다. |
| gp3 StorageClass 또는 Argo CD 적용 실패 | `bootstrap/`의 `terraform plan`과 Provider 오류를 확인합니다. EBS CSI Driver 준비 상태, Kubernetes 권한 및 Helm Release 상태도 확인합니다. |

검증 명령을 실행했다고 해서 AWS 배포 성공이 보장되지는 않습니다. NAT 장애 전환의 과거 시험 결과는 [검증 기록](terraform/ColdGuard_Validation_README.md)에 따로 정리되어 있습니다.
