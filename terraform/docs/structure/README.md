# ColdGuard 프로젝트 구조 및 모듈 가이드

## 프로젝트 개요

루트 구성은 AWS Provider와 공통 태그를 설정하고 10개 모듈을 연결합니다. VPC와 Subnet을 만든 뒤 NAT와 Router를 배치하며, NAT ENI를 Private Route Table의 기본 경로로 사용합니다. EKS는 Private Subnet을, ECR은 애플리케이션 이미지 저장소를 구성합니다. NAT ASG 장애 감지와 경로 전환은 `failover`, AWS 내부 알림과 KT 허브 상태 알람은 `monitoring`, 백업 버킷은 `storage` 모듈이 담당합니다. State는 S3 Backend에 저장합니다.

## 디렉터리 구조

저장소에 커밋되는 파일 기준입니다. `terraform init`, `plan`, `apply`가 만드는 `.terraform/`, `terraform.tfstate*`, `tfplan`과 직접 작성하는 `terraform.tfvars`는 `.gitignore`로 제외됩니다.

```text
Avocado/
├── .gitattributes                        # 실행 스크립트를 LF 줄바꿈으로 고정
├── README.md                             # 배포·운영 가이드와 문서 링크
├── ansible/                              # 서버 설정 (Ansible)
├── bootstrap/                            # EKS 내부 구성 (gp3 StorageClass, Argo CD)
│   └── values/argocd.yaml                # Argo CD Helm values
├── tests/
│   ├── ebs-test.yaml                     # gp3 PVC와 Pod 마운트 확인
│   └── nat-failover-test.yaml            # NAT 장애 전환 중 출구 IP 확인
└── terraform/
    ├── ColdGuard_Validation_README.md    # NAT 장애 전환 검증 기록
    ├── backend.tf                        # S3 Backend (State 버킷, 잠금 파일)
    ├── versions.tf                       # Terraform 및 Provider 버전 조건
    ├── .terraform.lock.hcl               # init이 기록한 Provider 버전·해시
    ├── provider.tf                       # AWS 리전과 공통 태그
    ├── variables.tf                      # 루트 입력 변수
    ├── terraform.tfvars.example          # 입력값 예시
    ├── locals.tf                         # 이름 접두어, 공통 태그, ECR·시설 목록
    ├── main.tf                           # 모듈 연결과 Private 기본 경로
    ├── outputs.tf                        # 리전, EKS, ECR, GitHub Actions Role, 시설·KT 허브 Pull 사용자 출력
    ├── docs/
    │   ├── variables/README.md           # 변수 및 설정 가이드
    │   └── structure/README.md           # 이 구조·모듈 가이드
    ├── scripts/
    │   └── setup-eks.sh                  # 로컬 kubeconfig 등록 및 상태 확인 (선택)
    └── modules/
        ├── network/                      # VPC, Subnet, Route Table, S3 Endpoint
        ├── security/                     # NAT/Router Security Group와 규칙
        ├── iam/                          # EC2, Lambda, EKS, Pod Identity, GitHub Actions, 시설·KT 허브 ECR Pull IAM
        │   ├── main.tf                   # 계정·리전 조회
        │   ├── instance.tf               # NAT·Router Instance Profile, KT 프로브 지표 권한
        │   ├── failover.tf               # Failover Lambda Role
        │   ├── eks.tf                    # EKS Cluster·Node·EBS CSI Role
        │   ├── pod.tf                    # 백업 CronJob Pod Identity Role
        │   ├── github.tf                 # GitHub Actions OIDC·Role
        │   ├── onprem.tf                 # 시설 K3s ECR Pull 전용 IAM 사용자
        │   └── kt.tf                     # KT 허브 ECR Pull 전용 IAM 사용자(통제 UI 이미지)
        ├── nat/                          # NAT 고정 ENI/EIP와 ASG
        │   └── scripts/nat-user-data.sh.tftpl
        ├── router/                       # Tailscale Router EC2, (선택) VPC → tailnet 경로
        │   └── scripts/router-user-data.sh.tftpl
        ├── failover/                     # NAT 경보, Lambda, EventBridge, SQS
        │   ├── alarm.tf                  # NAT ASG 장애 경보
        │   ├── lambda.tf                 # Lambda, 비동기 실패 SQS
        │   ├── eventbridge.tf            # 경보 → Lambda 규칙, 전달 실패 SQS
        │   ├── alerts.tf                 # Lambda 오류·제한 경보
        │   └── lambda/failover.py
        ├── eks/                          # EKS Cluster, Node Group, Add-on, Access Entry, Pod Identity 연결
        ├── ecr/                          # ECR Repository와 수명 주기 정책
        ├── monitoring/                   # 공용 SNS, KT 허브 상태 알람, Grafana IAM
        │   ├── sns.tf
        │   ├── kt_hub.tf
        │   └── grafana.tf
        └── storage/                      # 백업·이력 내보내기 S3 버킷
```

모든 모듈에 `variables.tf`(Input)가 있고, 다른 곳에서 참조할 값이 있는 모듈은 `outputs.tf`(Output)를 둡니다. 리소스가 적은 모듈은 `main.tf` 하나에, 많은 모듈(`iam`, `failover`, `monitoring`)은 역할별 파일로 나눴습니다. `failover`는 다른 모듈이 참조할 값이 없어 `outputs.tf`가 없습니다. `scripts/`와 `lambda/`의 파일은 해당 모듈의 `main.tf`에서 참조합니다. `failover.zip`은 `archive_file`이 배포 시 `failover.py`로 만드는 파일이며 커밋하지 않습니다. `tests/`의 매니페스트는 Terraform 리소스가 아니며 확인할 때만 직접 적용합니다.

## 루트 파일별 역할

| 파일명 | 역할 | 주요 내용 |
|---|---|---|
| `versions.tf` | 버전 제약 | Terraform `>= 1.10.0`, AWS Provider `~> 6.0`, Archive Provider `~> 2.0` |
| `.terraform.lock.hcl` | Provider 잠금 | `terraform init`이 선택한 Provider 버전과 무결성 해시 |
| `provider.tf` | AWS Provider | `aws_region`, `local.common_tags` 적용 |
| `backend.tf` | State 저장소 | S3 버킷 `coldguard-prod-tfstate-1q2w3e4r`, key `terraform/terraform.tfstate`, 잠금 파일 사용 |
| `variables.tf` | Input 선언 | 필수 변수 10개, 선택 변수 6개, `owner` 검증 |
| `terraform.tfvars.example` | 예시 입력 | 필수 변수 전체와 선택 변수(주석) 예시 |
| `locals.tf` | 공통 값 | 이름 접두어, `Project`·`Owner`·`Env`·`ManagedBy` 태그, ECR Repository 목록(EKS용·시설용·KT 허브용), 시설 목록 |
| `main.tf` | 구성 연결 | 10개 모듈 호출, Private Route Table의 NAT ENI 기본 경로 |
| `outputs.tf` | 사용자 출력 | 리전, EKS, ECR, GitHub Actions Role, 시설·KT 허브 ECR Pull 사용자, 백업 버킷·Role, 알림 토픽, Grafana 사용자, 라우터 공인 IP |
| `ColdGuard_Validation_README.md` | 검증 기록 | NAT Failover/Failback과 알림 시험 결과 및 한계 |

## 모듈별 리소스

| 모듈명 | 생성 리소스 | 주요 기능 | 연결 모듈 |
|---|---|---|---|
| `network` | VPC, Public/Private Subnet, IGW, Route Table·Association, S3 Gateway Endpoint | 네트워크와 기본 Public 경로 구성 | `security`, `iam`, `nat`, `router`, `failover`, `eks` |
| `security` | NAT/Router Security Group 및 Ingress/Egress Rule | Private Subnet의 NAT 유입, Router UDP 41641 허용, (선택) VPC 내부 유입 허용 | `network`, `nat`, `router`, `eks` |
| `iam` | NAT/Router Instance Profile, Router KT 프로브 지표 정책, Failover Lambda Role/Policy, EKS Cluster/Node/EBS CSI Role, 백업 CronJob Role, GitHub Actions OIDC Provider·Role, 시설·KT 허브 ECR Pull IAM 사용자·정책 | 서비스별 실행 권한, CI의 ECR Push·Pull 권한, 시설 K3s·KT 허브의 ECR Pull 권한 | `network`, `ecr`, `storage`, `monitoring`, `nat`, `router`, `failover`, `eks` |
| `nat` | 고정 ENI, EIP·Association, Launch Template, ASG | AZ별 NAT EC2 1대 유지, User Data로 IP 전달·`iptables` 설정 | `network`, `security`, `iam`, `failover` |
| `router` | EC2 Instance, (선택) Private Route Table의 tailnet 경로 | Public Subnet에서 Tailscale과 IP forwarding 설정, tailnet → VPC 서브넷 라우트, KT 허브 프로브 | `network`, `security`, `iam` |
| `failover` | NAT/Lambda CloudWatch Alarm, Lambda, EventBridge Rule/Target, SQS | NAT ASG 장애 시 반대 AZ ENI로 경로 전환, 장애·복구 알림, 실패 이벤트 보관 | `nat`, `network`, `iam`, `monitoring` |
| `eks` | EKS Cluster, Managed Node Group, VPC CNI·Pod Identity Agent·EBS CSI Add-on, Access Entry, Pod Identity 연결, 클러스터 SG 443 규칙 | Private Subnet의 Kubernetes Cluster, 관리자 권한, Pod의 AWS 권한, Tailscale 경유 API 접근 | `network`, `iam`, `security`, 루트 NAT 경로 |
| `ecr` | ECR Repository, Lifecycle Policy | `control-api`, `central-worker`, `collector`, `controller`, `field-web`, `control-ui` 저장소, 이미지 스캔 및 이미지 정리 정책 | `iam` |
| `monitoring` | SNS Topic·이메일 구독, KT 허브 상태 CloudWatch Alarm, Grafana IAM 사용자·정책 | AWS 내부 알림 공용 토픽, KT 허브 장애 감지, KT Grafana의 CloudWatch 조회 | `failover`, `iam` |
| `storage` | S3 Bucket, 소유권·퍼블릭 차단·버전 관리·암호화·수명 주기·버킷 정책 | MySQL 백업과 이력·감사 로그 내보내기 저장 | `iam` |

## 모듈 Input과 Output

표의 Input은 각 모듈 `variables.tf`의 변수명입니다. Output은 각 모듈 `outputs.tf`에 실제 선언된 값입니다.

| 모듈 | Input | Output |
|---|---|---|
| `network` | `name`, `environment`, `vpc_cidr`, `subnets`, `aws_region` | `vpc_id`, `public_subnet_ids`, `private_subnet_ids`, `igw_id`, `public_route_table_id`, `private_route_table_ids`, `s3_vpc_endpoint_id` |
| `security` | `name`, `environment`, `vpc_id`, `vpc_cidr`, `subnets`, `router_vpc_ingress_enabled` | `nat_sg_id`, `router_sg_id` |
| `iam` | `name`, `environment`, `private_route_table_ids`, `github_repository`, `ecr_repository_arns`, `onprem_sites`, `onprem_ecr_repository_arns`, `kt_hub_ecr_repository_arns`, `kt_hub_probe_namespace`, `backup_bucket_arn` | `nat_instance_profile_name`, `router_instance_profile_name`, `failover_lambda_role_arn`, `eks_cluster_role_arn`, `eks_node_role_arn`, `eks_cluster_role_policy_attachment_id`, `eks_node_role_policy_attachment_ids`, `eks_ebs_csi_role_arn`, `github_actions_role_arn`, `backup_role_arn`, `onprem_ecr_pull_user_names`, `kt_hub_ecr_pull_user_name` |
| `nat` | `name`, `environment`, `instances`, `public_subnet_ids`, `nat_sg_id`, `vpc_cidr`, `nat_instance_profile_name` | `nat_eni_ids`, `nat_eip_ids`, `nat_public_ips`, `nat_asg_names`, `nat_launch_template_ids` |
| `router` | `name`, `environment`, `instances`, `public_subnet_ids`, `router_sg_id`, `router_instance_profile_name`, `private_route_table_ids`, `routed_cidrs` | `router_instance_ids`, `router_private_ips`, `router_public_ips`, `router_eni_ids` |
| `failover` | `name`, `environment`, `nat_asg_names`, `private_route_table_ids`, `nat_eni_ids`, `lambda_role_arn`, `alert_topic_arn` | 없음 |
| `eks` | `name`, `environment`, `cluster_role_arn`, `node_role_arn`, `private_subnet_ids`, `public_access_enabled`, `public_access_cidrs`, `cluster_admin_arns`, `cluster_viewer_arns`, `pod_identity_associations`, `router_sg_id`, `node_instance_type`, `node_disk_size`, `node_desired_size`, `node_min_size`, `node_max_size`, `ebs_csi_role_arn` | `cluster_name`, `cluster_endpoint`, `cluster_arn`, `node_group_name`, `cluster_security_group_id` |
| `ecr` | `name`, `environment`, `repository_names` | `repository_urls`, `repository_names`, `repository_arns` |
| `monitoring` | `name`, `environment`, `alert_email`, `alert_emails`, `kt_hub_probe_namespace`, `kt_hub_components` | `alert_topic_arn`, `kt_hub_probe_namespace`, `grafana_user_name` |
| `storage` | `name`, `environment` | `backup_bucket_name`, `backup_bucket_arn` |

`eks`의 노드 관련 Input 5개는 루트 변수 `eks_node_group`에서 전달됩니다. `iam`의 `ecr_repository_arns`는 `ecr` 모듈 Output에서 받으므로 Repository를 추가하면 GitHub Actions Push·Pull 권한도 함께 넓어집니다. `onprem_ecr_repository_arns`는 그중 `ecr_onprem_repositories`에, `kt_hub_ecr_repository_arns`는 `ecr_kt_repositories`에 해당하는 ARN만 골라 넘깁니다.

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
루트 locals ECR 목록 → ecr → Repository ARN → iam (GitHub Actions Push·Pull, 시설·KT 허브 Pull 권한)
monitoring → SNS 토픽 ARN → failover (NAT·Lambda 알람)
monitoring → KT 프로브 지표 이름공간 → iam (라우터 PutMetricData 권한)
storage → 백업 버킷 ARN → iam (백업 Role) → eks (Pod Identity 연결)
network Private Route Table + router ENI → router ((선택) VPC → tailnet 경로)
security router SG → eks (클러스터 SG 443 허용)
```

루트 `aws_route.private_nat`는 `private_a`를 `nat_a`, `private_c`를 `nat_c`에 대응시킵니다. `eks`는 이 경로가 준비된 뒤 생성되도록 `depends_on`을 지정합니다. Failover Lambda는 장애 경보가 `ALARM`으로 바뀌면 반대 AZ NAT ENI로 기본 경로를 바꿉니다. 루트 경로 리소스는 `network_interface_id` 변경을 무시하므로 이 전환을 다음 `terraform plan`에서 자동으로 원복하지 않습니다. 상세한 실제 시험 결과는 [검증 기록](../../ColdGuard_Validation_README.md)을 참조합니다.

### Tailscale 경로와 KT 허브 상태 확인

서브넷 라우터는 tailnet → VPC 방향만 맡습니다. tailnet에서 Kubernetes API로 오는 요청은 라우터가 자기 사설 IP로 SNAT하므로 클러스터 SG는 라우터 SG의 443만 허용합니다. EKS Pod가 KT 허브로 지표·로그를 보내는 VPC → tailnet 방향은 Tailscale Kubernetes operator의 egress 프록시가 맡고, 라우터를 거치지 않습니다. `router_routed_cidrs`에 값을 넣으면 Private Route Table의 tailnet 경로와 라우터 SG의 VPC 인그레스가 생겨 라우터 경유 송신도 쓸 수 있습니다(라우터에 MASQUERADE 필요).

서브넷 라우터는 1분마다 KT 허브의 구성 요소별 상태 확인 주소를 호출해 결과를 `ColdGuard/KTHub` 이름공간의 `ProbeSuccess` 지표(차원 `Component`)로 올립니다. `monitoring`의 알람은 3분 연속 실패하거나 지표가 끊기면 공용 SNS로 알립니다. 지표를 올리는 스크립트는 Ansible에서 라우터에 배포합니다.
