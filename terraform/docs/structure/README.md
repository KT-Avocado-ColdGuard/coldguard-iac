# ColdGuard 프로젝트 구조 및 모듈 가이드

## 프로젝트 개요

루트 구성은 AWS Provider와 공통 태그를 설정하고 8개 모듈을 연결합니다. VPC와 Subnet을 만든 뒤 NAT와 Router를 배치하며, NAT ENI를 Private Route Table의 기본 경로로 사용합니다. EKS는 Private Subnet을, ECR은 애플리케이션 이미지 저장소를 구성합니다. NAT ASG 장애 감지와 경로 전환은 `failover` 모듈이 담당합니다.

## 디렉터리 구조

```text
terraform/
├── README.md                         # 배포·운영 가이드와 문서 링크
├── ColdGuard_Validation_README.md    # NAT 장애 전환의 기존 검증 기록
├── backend.tf                        # 원격 Backend 미설정 안내 주석
├── versions.tf                       # Terraform 및 Provider 버전 조건
├── .terraform.lock.hcl               # init이 기록한 Provider 버전·해시
├── .terraform/                       # init이 설치한 로컬 작업 파일
├── provider.tf                       # AWS 리전과 공통 태그
├── variables.tf                      # 루트 입력 변수
├── terraform.tfvars.example          # 입력값 예시(필수 변수 일부 누락)
├── terraform.tfvars                  # 현재 로컬 입력값
├── locals.tf                         # 이름 접두어 및 공통 태그
├── main.tf                           # 모듈 연결과 Private 기본 경로
├── outputs.tf                        # EKS/ECR 출력
├── terraform.tfstate                 # 현재 로컬 State
├── terraform.tfstate.backup          # 이전 로컬 State 백업
├── network-test.txt                  # 이전 terraform plan 출력 기록
├── docs/
│   ├── variables/README.md           # 변수 및 설정 가이드
│   └── structure/README.md           # 이 구조·모듈 가이드
├── kubernetes/
│   ├── storageclass-gp3.yaml         # EBS CSI gp3 StorageClass
│   ├── ebs-test.yaml                  # PVC와 Pod 테스트 매니페스트
│   └── nat-failover-test.yaml         # NAT 경로 확인용 Pod 매니페스트
└── modules/
    ├── network/                      # VPC, Subnet, Route Table, S3 Endpoint
    ├── security/                     # NAT/Router Security Group와 규칙
    ├── iam/                          # EC2, Lambda, EKS IAM 역할과 정책
    ├── nat/                          # NAT 고정 ENI/EIP와 ASG
    │   └── scripts/nat-user-data.sh.tftpl
    ├── router/                       # Tailscale Router EC2
    │   └── scripts/router-user-data.sh.tftpl
    ├── failover/                     # 경보, Lambda, EventBridge, SQS, SNS
    │   ├── lambda/failover.py
    │   └── failover.zip              # archive_file이 쓰는 ZIP 경로
    ├── eks/                          # EKS Cluster, Node Group, Add-on
    ├── ecr/                          # ECR Repository와 수명 주기 정책
    ├── automation/                   # 현재 비어 있음
    ├── budget/                       # 현재 비어 있음
    ├── monitoring/                   # 현재 비어 있음
    └── storage/                      # 현재 비어 있음
```

구현된 8개 모듈에는 각각 `main.tf`(리소스와 데이터 조회), `variables.tf`(Input), `outputs.tf`(Output)가 있습니다. 나머지 4개 모듈 디렉터리는 비어 있으며 루트에서 호출하지 않습니다. `scripts/`와 `lambda/`의 파일은 해당 모듈의 `main.tf`에서 참조합니다. `failover.zip`은 `archive_file`의 출력 경로이므로 배포 시 Python 원본에서 생성됩니다. `kubernetes/` 파일은 Terraform 리소스로 선언되지 않았으며 별도로 적용하는 매니페스트입니다.

## 루트 파일별 역할

| 파일명 | 역할 | 주요 내용 |
|---|---|---|
| `versions.tf` | 버전 제약 | Terraform `>= 1.0.0`, AWS Provider `~> 6.0`, Archive Provider `~> 2.0` |
| `.terraform.lock.hcl` | Provider 잠금 | `terraform init`이 선택한 Provider 버전과 무결성 해시 |
| `.terraform/` | 로컬 작업 디렉터리 | Provider 설치 파일과 초기화 결과. 직접 편집하지 않음 |
| `provider.tf` | AWS Provider | `aws_region`, `local.common_tags` 적용 |
| `backend.tf` | Backend 안내 | 원격 Backend 미설정 주석. 기본 로컬 State 사용 |
| `variables.tf` | Input 선언 | 9개 루트 변수 타입 및 `owner` 검증 |
| `terraform.tfvars.example` | 예시 입력 | 이름, 리전, VPC, AZ, Subnet 예시. `instances`와 EKS API CIDR은 누락 |
| `terraform.tfvars` | 실제 입력 | 현재 작업 공간의 루트 변수 값. 비밀값 노출에 주의 |
| `locals.tf` | 공통 값 | 이름 접두어, `Project`·`Owner`·`Env`·`ManagedBy` 태그 |
| `main.tf` | 구성 연결 | 8개 모듈 호출, Private Route Table의 NAT ENI 기본 경로 |
| `outputs.tf` | 사용자 출력 | EKS Cluster 이름·Endpoint, Node Group 이름, ECR URL |
| `terraform.tfstate` | 로컬 State | Terraform 관리 리소스 상태. 수동 편집 금지 |
| `terraform.tfstate.backup` | State 백업 | 이전 로컬 State 사본. 수동 편집 금지 |
| `network-test.txt` | 계획 기록 | 과거 Terraform plan 출력; 현재 인프라 상태의 근거로 사용하지 않음 |
| `ColdGuard_Validation_README.md` | 검증 기록 | NAT Failover/Failback과 알림 시험 결과 및 한계 |

## 모듈별 리소스

| 모듈명 | 생성 리소스 | 주요 기능 | 연결 모듈 |
|---|---|---|---|
| `network` | VPC, Public/Private Subnet, IGW, Route Table·Association, S3 Gateway Endpoint | 네트워크와 기본 Public 경로 구성 | `security`, `iam`, `nat`, `router`, `failover`, `eks` |
| `security` | NAT/Router Security Group 및 Ingress/Egress Rule | Private Subnet의 NAT 유입, Router UDP 41641 허용 | `network`, `nat`, `router` |
| `iam` | NAT/Router Instance Profile, Failover Lambda Role/Policy, EKS Cluster/Node/EBS CSI Role | 서비스별 실행 권한 | `network`, `nat`, `router`, `failover`, `eks` |
| `nat` | 고정 ENI, EIP·Association, Launch Template, ASG | AZ별 NAT EC2 1대 유지, User Data로 IP 전달·`iptables` 설정 | `network`, `security`, `iam`, `failover` |
| `router` | EC2 Instance | Public Subnet에서 Tailscale과 IP forwarding 설정 | `network`, `security`, `iam` |
| `failover` | NAT/Lambda CloudWatch Alarm, Lambda, EventBridge Rule/Target, SQS, SNS | NAT ASG 장애 시 반대 AZ ENI로 경로 전환; 실패 이벤트 보관·오류 알림 | `nat`, `network`, `iam` |
| `eks` | EKS Cluster, Managed Node Group, VPC CNI·Pod Identity Agent·EBS CSI Add-on | Private Subnet의 Kubernetes Cluster와 EBS CSI 구성 | `network`, `iam`, 루트 NAT 경로 |
| `ecr` | ECR Repository, Lifecycle Policy | `app` 저장소, 이미지 스캔 및 이미지 정리 정책 | 루트 입력 |

## 모듈 Input과 Output

표의 Input은 각 모듈 `variables.tf`의 변수명입니다. Output은 각 모듈 `outputs.tf`에 실제 선언된 값입니다.

| 모듈 | Input | Output |
|---|---|---|
| `network` | `name`, `environment`, `vpc_cidr`, `subnets`, `aws_region` | `vpc_id`, `public_subnet_ids`, `private_subnet_ids`, `igw_id`, `public_route_table_id`, `private_route_table_ids`, `s3_vpc_endpoint_id` |
| `security` | `name`, `environment`, `vpc_id`, `vpc_cidr`, `subnets` | `nat_sg_id`, `router_sg_id` |
| `iam` | `name`, `environment`, `private_route_table_ids` | `nat_instance_profile_name`, `router_instance_profile_name`, `failover_lambda_role_arn`, `eks_cluster_role_arn`, `eks_node_role_arn`, `eks_cluster_role_policy_attachment_id`, `eks_node_role_policy_attachment_ids`, `eks_ebs_csi_role_arn` |
| `nat` | `name`, `environment`, `instances`, `public_subnet_ids`, `nat_sg_id`, `vpc_cidr`, `nat_instance_profile_name` | `nat_eni_ids`, `nat_eip_ids`, `nat_public_ips`, `nat_asg_names`, `nat_launch_template_ids` |
| `router` | `name`, `environment`, `instances`, `public_subnet_ids`, `router_sg_id`, `router_instance_profile_name` | `router_instance_ids`, `router_private_ips`, `router_public_ips` |
| `failover` | `name`, `environment`, `nat_asg_names`, `aws_region`, `private_route_table_ids`, `nat_eni_ids`, `lambda_role_arn` | 선언된 Output 없음 |
| `eks` | `name`, `environment`, `cluster_role_arn`, `node_role_arn`, `private_subnet_ids`, `public_access_cidrs`, `node_instance_type`, `node_disk_size`, `node_desired_size`, `node_min_size`, `node_max_size`, `ebs_csi_role_arn` | `cluster_name`, `cluster_endpoint`, `cluster_arn`, `node_group_name` |
| `ecr` | `name`, `environment`, `repository_names` | `repository_urls`, `repository_names` |

`security`의 `vpc_cidr` Input은 현재 모듈 리소스에서 사용하지 않습니다. `eks`의 `node_desired_size`, `node_min_size`, `node_max_size`도 선언되고 루트에서 전달되지만 Node Group `scaling_config`에는 숫자 `3`이 직접 지정되어 있습니다.

## 연결 및 생성 흐름

```text
루트 변수 → network ── VPC ID → security
                    ├─ Route Table ID → iam → Failover Lambda 권한
                    ├─ Public Subnet ID → nat, router
                    └─ Private Subnet ID → eks
security + iam → nat/ router
nat ENI + network Private Route Table → 루트 aws_route.private_nat (기본 경로)
nat ASG + nat ENI + Route Table ID + IAM Role → failover
루트 기본 경로 + EKS IAM Role → eks
루트 name/environment → ecr
```

루트 `aws_route.private_nat`는 `private_a`를 `nat_a`, `private_c`를 `nat_c`에 대응시킵니다. `eks`는 이 경로가 준비된 뒤 생성되도록 `depends_on`을 지정합니다. Failover Lambda는 장애 경보가 `ALARM`으로 바뀌면 반대 AZ NAT ENI로 기본 경로를 바꿉니다. 루트 경로 리소스는 `network_interface_id` 변경을 무시하므로 이 전환을 다음 `terraform plan`에서 자동으로 원복하지 않습니다. 상세한 실제 시험 결과는 [검증 기록](../../ColdGuard_Validation_README.md)을 참조합니다.
