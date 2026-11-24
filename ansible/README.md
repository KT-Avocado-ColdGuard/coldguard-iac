# ColdGuard 온프레미스 Ansible 설치 및 운영 가이드

이 문서는 **Ubuntu VM 안에서** ColdGuard 기본 환경을 설치하고 검증하는 절차입니다. 명령어의 기본 실행 위치는 별도 표시가 없으면 **Ubuntu VM의 터미널, 저장소의 `ansible/` 디렉터리**입니다. Windows VS Code는 파일을 편집하거나 VM 콘솔을 여는 용도로 사용하실 수 있지만, 이 플레이북은 Windows에서 원격 SSH로 실행하는 구성이 아닙니다.

## 1. 프로젝트 개요

| 구분 | 담당 범위 | 실행 위치 및 주의사항 |
|---|---|---|
| Terraform | 저장소의 `terraform/`, `bootstrap/`에서 AWS 인프라와 EKS 관련 리소스를 관리합니다. | 이 Ansible 플레이북은 Terraform을 실행하거나 VMware VM을 생성하지 않습니다. |
| Ansible | 이미 생성된 Ubuntu VM에 패키지, Tailscale, UFW, 단일 K3s 서버와 로컬 kubeconfig를 구성합니다. | VM 안에서 `localhost`를 대상으로 실행합니다. `inventory/hosts.ini`의 `ansible_connection=local`과 `setup.yml`의 `connection: local`이 이를 지정합니다. |
| 담당자 | VMware VM·네트워크·계정 준비, Git/Ansible 사전 설치, Tailscale Auth Key 발급, Vault 생성, 변수 검토, 실행과 검증을 수행합니다. | Tailscale 관리자 콘솔에서 키와 ACL/Grants를 관리합니다. |

| Role | 주요 역할 |
|---|---|
| Common | Ubuntu 24.04 확인, APT 캐시 갱신, 필수 도구 설치 및 패키지 검증 |
| Tailscale | 공식 APT 저장소 등록, 지정 버전 설치, Tailnet 가입, SNAT 설정 및 연결 확인 |
| Firewall | UFW 기본 정책, SSH·Tailscale 인터페이스·K3s 대역 허용 규칙 적용 |
| K3s | IPv4 forwarding, K3s 설치와 설정, 사용자 kubeconfig 구성, Node Ready 확인 |

> [!IMPORTANT]
> 이 코드는 **현재 VM 자체**를 변경합니다. `hosts.ini`의 `localhost`를 다른 서버 주소로 바꾸는 것만으로 원격 배포용 플레이북이 되지 않습니다.

## 2. 시스템 요구사항

| 항목 | 기준 환경 | 코드에서 확인한 조건 | 수정·확인 필요 여부 | 주의사항 |
|---|---|---|---|---|
| 서버/가상화 | VMware Workstation의 Ubuntu Server 24.04 LTS VM | Common Role은 Ubuntu `>=24.04`, `<24.10`을 검사합니다. | **본인 VM 확인** | 다른 배포판이나 Ubuntu 24.10은 검사에 실패합니다. |
| VM 자원 | vCPU 4개, RAM 8GB, 디스크 50GB | 자원 크기를 검사하거나 할당하는 Task는 없습니다. | **VM 생성 시 설정** | 이 수치는 제공된 환경 기준이며 코드가 보장하는 최소 사양은 아닙니다. |
| 계정 | sudo 권한이 있는 일반 사용자 | 플레이북은 `become: true`; K3s는 실행 계정을 별도로 감지합니다. | **sudo 권한 확인** | root로 실행하면 kubeconfig 대상도 root가 됩니다. |
| 네트워크 | 인터넷 및 DNS 연결 | APT, Tailscale 공식 저장소, `https://get.k3s.io`에 접근합니다. | **VM에서 확인** | VM의 기본 IPv4 경로와 VMware NAT/방화벽을 확인하십시오. |
| 사전 프로그램 | Python 3, Git, Ansible, `community.general` Collection | UFW Role은 `community.general.ufw`를 사용합니다. | **사전 설치** | Git은 Common Role에서도 설치하지만 Clone하려면 먼저 필요합니다. |
| 인증 | Tailscale Auth Key와 별도 Vault 비밀번호 | 미가입 상태에서 `tailscale_auth_key`를 사용합니다. | **직접 준비** | 두 비밀은 서로 다른 용도입니다. |

| 환경 | 사용자 | 호스트명 | VMware NAT/VM IPv4 | 게이트웨이/Tailscale IPv4 | 성격 |
|---|---|---|---|---|---|
| 운영 **예시** | `avocado` | `facility-01` | `192.168.188.0/24` / `192.168.188.100` | `192.168.188.2` / 환경별 할당 | 제공된 운영 예시이며 자동 설정값은 아닙니다. |
| 테스트 **예시** | `student` | VM별 상이 | `192.168.120.180` | Tailscale `100.80.93.54` | 제공된 테스트 VM의 관측값입니다. |

> [!WARNING]
> **다른 VM에 운영 예시의 `192.168.188.100`, 게이트웨이, NAT 대역을 그대로 지정하지 마십시오.** VMware 네트워크와 주소 충돌을 확인한 뒤 해당 VM의 실제 값을 사용하십시오. 이 플레이북은 VM의 고정 IP나 호스트명을 설정하지 않습니다.

## 3. 디렉터리 구조

다음은 README 작성 전 확인한 `ansible/`의 실제 파일입니다. `group_vars/vault.yml`은 저장소에 없으며 각 VM에서 직접 생성합니다.

```text
ansible/
├── ansible.cfg
├── inventory/
│   └── hosts.ini
├── group_vars/
│   └── all.yml
├── playbooks/
│   └── setup.yml
└── roles/
    ├── common/tasks/main.yml
    ├── tailscale/tasks/main.yml
    ├── firewall/tasks/main.yml
    └── k3s/
        ├── tasks/main.yml
        └── templates/config.yaml.j2
```

| 파일 | 역할 | 사용 시 주의사항 |
|---|---|---|
| `ansible.cfg` | 기본 inventory를 `./inventory/hosts.ini`, Role 경로를 `./roles`로 지정합니다. | **`ansible/`에서 명령을 실행**하면 상대 경로가 명확합니다. |
| `inventory/hosts.ini` | `[onprem]` 그룹에 `localhost ansible_connection=local`을 정의합니다. | 대상은 현재 Ubuntu VM입니다. |
| `group_vars/all.yml` | Tailscale, UFW, K3s의 일반 변수를 정의합니다. | 모든 선언 변수는 7절에 설명합니다. |
| `group_vars/vault.yml` | **각 VM에서 생성할 암호화 파일**입니다. `setup.yml`이 이 경로를 읽습니다. | Git 추적 대상이 아니며 `.gitignore`에 등록되어 있습니다. |
| `playbooks/setup.yml` | `onprem`에 `become: true`, facts 수집 후 네 Role을 순서대로 실행합니다. | `all.yml`과 `vault.yml`을 `vars_files`로 직접 읽습니다. |
| `roles/common/tasks/main.yml` | OS 검사, APT 설치, 패키지 존재 검증을 합니다. | Ubuntu 24.04 전용 검사입니다. |
| `roles/tailscale/tasks/main.yml` | 저장소·버전·인증·서비스·SNAT·IP 검증을 합니다. | 기존 연결의 Tailnet 이름은 확인하지 않습니다. |
| `roles/firewall/tasks/main.yml` | UFW 규칙과 기본 정책을 적용하고 활성 상태를 확인합니다. | 규칙을 적용하기 전에 SSH 접근 경로를 확인하십시오. |
| `roles/k3s/tasks/main.yml` | forwarding, K3s, kubeconfig, Node Ready를 처리합니다. | 기존 바이너리가 있으면 설치 단계는 건너뜁니다. |
| `roles/k3s/templates/config.yaml.j2` | K3s의 node IP, Pod/Service CIDR, Traefik 비활성화 여부를 렌더링합니다. | 출력은 root 소유의 `/etc/rancher/k3s/config.yaml`입니다. |

## 4. Ansible 실행 구조

```text
Ubuntu VM
  │
  ├── Git / Ansible 사전 설치
  ├── GitHub Clone
  ├── group_vars/all.yml 검토
  ├── group_vars/vault.yml 생성
  └── playbooks/setup.yml 실행
        │
        ├── Common
        ├── Tailscale
        ├── Firewall
        └── K3s
```

`setup.yml`의 `roles` 배열이 실행 순서를 정합니다. Common이 UFW 등을 설치하고, Tailscale이 인터페이스와 연결을 준비한 다음 Firewall이 접근 규칙과 기본 차단 정책을 적용합니다. 따라서 방화벽 활성화 전에 SSH와 Tailscale 허용 규칙이 먼저 등록됩니다. 마지막 K3s는 `/etc/sysctl.d/90-coldguard-k3s.conf`에 `net.ipv4.ip_forward = 1`을 기록하고 즉시 적용합니다. Pod 네트워크의 패킷을 노드가 전달해야 하므로 forwarding이 필요합니다. UFW의 routed 기본 정책은 별도로 `deny`이므로 실제 Pod 통신은 12절에서 확인하십시오.

## 5. 사전 준비

**실행 위치: Ubuntu VM 터미널.** 인터넷에 연결된 Ubuntu 24.04에서 다음을 실행합니다. `sudo`는 패키지 설치에 필요한 관리자 권한입니다.

```bash
sudo apt update
sudo apt install -y git ansible python3
git --version
ansible --version
python3 --version
```

UFW 모듈을 Ansible이 찾는지도 확인합니다. 다음 `ansible-doc`가 모듈 설명을 표시하면 준비된 것입니다.

```bash
ansible-doc community.general.ufw
```

모듈을 찾지 못한다면 Ubuntu VM에서 Collection을 설치하고 다시 확인합니다.

```bash
ansible-galaxy collection install community.general
ansible-doc community.general.ufw
```

> [!NOTE]
> `ansible --version`에 표시된 **ansible-core 버전**과 설치하려는 `community.general` 릴리스의 지원 범위를 확인하십시오. 설치 후에도 `ansible-doc` 또는 문법 검사가 실패하면 호환되는 Collection 릴리스를 선택해야 합니다. 저장소에는 Collection 버전을 고정하는 `requirements.yml`이 없습니다.

## 6. GitHub 저장소 Clone 및 실행 환경 준비

**실행 위치: Ubuntu VM 터미널.** 아래 URL은 이 저장소의 Git `origin`에서 확인한 값입니다. `coldguard`는 VM 안에 생성할 작업 폴더 이름이며 원하는 이름으로 바꿀 경우 이후 `cd`도 함께 바꾸십시오.

```bash
git clone https://github.com/KT-Avocado-ColdGuard/coldguard-iac.git coldguard
cd coldguard/ansible
pwd
find . -maxdepth 4 -type f -print
```

`pwd`가 `.../coldguard/ansible`을 가리키는지 확인하십시오. `find`에는 `ansible.cfg`, inventory, 변수, 플레이북, Role 파일이 보여야 합니다. `ansible.cfg`는 이 디렉터리에서 명령을 실행할 때 기본 inventory와 Role 경로를 제공합니다. `hosts.ini`는 원격 호스트 목록이 아니라 **현재 VM을 가리키는 로컬 inventory**입니다.

이미 Clone한 저장소를 갱신할 때는 다음을 실행합니다. 로컬에서 `all.yml`을 수정했다면 `git pull` 전에 변경 내용을 확인하고 보존하십시오. VM마다 다른 일반 변수는 Clone 이후 다시 검토해야 합니다.

```bash
cd ~/coldguard
git status --short
git pull
cd ansible
```

## 7. 변수 설정 가이드

**편집 위치: Ubuntu VM의 `ansible/group_vars/all.yml`**입니다. Windows VS Code로 파일을 편집한다면 VM에서 받은 저장소의 같은 파일인지 확인하십시오. 아래 표는 이 파일에 선언된 **14개 변수를 모두** 포함합니다. `수정 필요 여부`는 현재 코드의 기본값으로 시작하는 경우를 기준으로 합니다.

| 변수명 | 기본값 | 사용 Role | 역할 | 수정 필요 여부 | 변경 시 주의사항 |
|---|---|---|---|---|---|
| `tailscale_version` | `"1.104.7"` | Tailscale | `apt-cache madison tailscale`에서 같은 버전의 패키지를 찾아 설치하고 설치 버전을 검증합니다. | **원하는 버전이 다를 때 수정** | 공식 APT 저장소에 해당 릴리스가 있어야 합니다. `allow_downgrade: true`도 설정되어 있으므로 버전 변경 전 영향을 확인하십시오. |
| `tailscale_snat_subnet_routes` | `false` | **현재 미사용** | 변수만 선언되어 있습니다. | 수정해도 현재 동작에 영향 없음 | Role은 `tailscale up`과 `tailscale set`에 `--snat-subnet-routes=false`를 직접 전달합니다. 광고할 서브넷 경로도 설정하지 않습니다. |
| `ufw_default_incoming` | `deny` | Firewall | 들어오는 연결의 기본 정책입니다. | 기본값 유지 권장 | 허용 규칙에 없는 신규 포트는 차단됩니다. |
| `ufw_default_outgoing` | `allow` | Firewall | 나가는 연결의 기본 정책입니다. | 기본값 유지 권장 | 변경하면 APT, Tailscale, DNS 및 Pod 통신을 다시 검증하십시오. |
| `ufw_default_routed` | `deny` | Firewall | 전달되는 트래픽의 UFW 기본 정책입니다. | 기본값 유지 후 통신 검증 | IP forwarding `1`과 별개의 정책입니다. Pod/외부 경로가 막히면 함께 점검하십시오. |
| `ufw_ssh_port` | `"22"` | Firewall | SSH TCP 입력 허용 포트입니다. | **VM의 SSH 포트가 다르면 수정** | `sshd`의 실제 포트와 맞춰야 합니다. UFW 활성화 전 콘솔 접근을 확보하십시오. |
| `ufw_tailscale_interface` | `"tailscale0"` | Firewall | 해당 입력 인터페이스의 트래픽을 허용합니다. | 인터페이스가 다를 때만 수정 | `ip link show tailscale0` 등으로 실제 이름을 확인하십시오. |
| `ufw_k3s_pod_cidr` | `"10.42.0.0/16"` | Firewall | Pod 대역을 출발지로 하는 입력 허용 규칙입니다. | **`k3s_cluster_cidr` 변경 시 함께 수정** | 서로 다르면 K3s가 쓰는 대역과 UFW 허용 대역이 어긋납니다. |
| `ufw_k3s_service_cidr` | `"10.43.0.0/16"` | Firewall | Service 대역을 출발지로 하는 입력 허용 규칙입니다. | **`k3s_service_cidr` 변경 시 함께 수정** | Service ClusterIP 대역과 일치시켜 검증하십시오. |
| `k3s_version` | `"v1.37.2+k3s1"` | K3s | 첫 설치 시 공식 설치 스크립트의 `INSTALL_K3S_VERSION`으로 전달하고 실행 결과를 검증합니다. | **원하는 릴리스가 다르면 수정** | 실제 배포 가능한 릴리스인지 확인하십시오. 기존 설치의 자동 업그레이드 기능은 없습니다. |
| `k3s_node_ip` | `"{{ ansible_default_ipv4.address }}"` | K3s | Ansible facts가 감지한 기본 IPv4를 K3s `node-ip`에 넣습니다. | 보통 **수정 불필요** | 기본 경로가 원하는 VM 인터페이스가 아니면 실제 주소를 확인한 뒤 수정하십시오. 단순히 운영 예시 IP를 복사하지 마십시오. |
| `k3s_cluster_cidr` | `"10.42.0.0/16"` | K3s | K3s Pod IP 대역을 `cluster-cidr`로 설정합니다. | 기본값 유지 권장 | 다른 네트워크와 겹치면 계획적으로 변경하고 `ufw_k3s_pod_cidr`도 맞추십시오. 기존 클러스터의 대역 변경은 단순 재실행으로 안전하게 끝난다고 가정하지 마십시오. |
| `k3s_service_cidr` | `"10.43.0.0/16"` | K3s | K3s Service ClusterIP 대역을 `service-cidr`로 설정합니다. | 기본값 유지 권장 | `ufw_k3s_service_cidr`와 맞추고 기존 서비스·DNS 영향을 검토하십시오. |
| `k3s_disable_traefik` | `true` | K3s | `true`이면 설정 파일에 `disable: [traefik]`을 렌더링합니다. | 기본값 유지 권장 | `false`로 바꾸면 이 비활성화 항목이 빠집니다. 실제 설치 상태를 다시 검증하십시오. |

### 자동 감지 IP와 계정

`k3s_node_ip`의 기본값은 Ansible이 VM에서 수집한 `ansible_default_ipv4.address`입니다. 예를 들어 운영 예시 VM의 기본 IPv4가 `192.168.188.100`이면 그 값이, 테스트 예시 VM에서 `192.168.120.180`이면 그 값이 선택될 수 있습니다. **이는 예시이며 실제 선택값은 VM의 라우팅과 facts에 따릅니다.** VM에서 다음 명령으로 기본 경로에 선택되는 `src` 주소를 확인하고, 실행 중 `Show K3s installation settings` 출력의 `Node IP`와 대조하십시오.

```bash
ip -4 route get 1.1.1.1
```

K3s Role의 `Detect local login user` Task는 `become: false`로 `id -un`을 실행합니다. 따라서 `student`로 플레이북을 실행하면 일반적으로 `/home/student/.kube/config`, `avocado`로 실행하면 `/home/avocado/.kube/config`를 만듭니다. 실제 홈 경로는 `getent passwd` 결과로 결정하므로 사용자 이름을 경로에 하드코딩하지 않았습니다. **플레이북을 실행할 계정**을 먼저 결정하고 그 계정에 sudo 권한이 있는지 확인하십시오. Role은 홈 디렉터리의 그룹 이름이 사용자 이름과 같다고 가정합니다.

### 변경이 적용되는 범위

| 변경 대상 | 다음 실행의 실제 동작 | 추가 확인 |
|---|---|---|
| UFW 정책·포트·대역·인터페이스 | Firewall Role이 지정한 규칙·정책을 적용합니다. | 기존에 불필요해진 이전 규칙을 삭제하는 Task는 없습니다. `sudo ufw status verbose`로 중복·잔존 규칙을 확인하십시오. |
| K3s node IP·CIDR·Traefik | 템플릿이 달라지면 `config.yaml`을 갱신하고, 기존 K3s 바이너리가 있는 경우 서비스를 재시작합니다. | 네트워크 대역 변경은 기존 Pod/Service에 영향을 줄 수 있으므로 백업과 검증이 필요합니다. |
| Tailscale 버전 | 사용 가능한 APT 버전을 찾아 지정 버전을 설치하고 실행 버전을 비교합니다. | APT 저장소의 실제 패키지 버전을 확인하십시오. 미지원 버전이면 실패합니다. |
| K3s 버전 | 새 설치 시에만 설치 스크립트에 전달합니다. | 기존 `/usr/local/bin/k3s`가 있으면 설치를 건너뛰고 버전 검증에서 불일치를 보고합니다. **변수 변경만으로 자동 업그레이드되지 않습니다.** |

Pod CIDR와 Service CIDR를 변경할 때는 각각 **`k3s_cluster_cidr`와 `ufw_k3s_pod_cidr`**, **`k3s_service_cidr`와 `ufw_k3s_service_cidr`**를 함께 검토하십시오. VM의 VMware NAT, LAN, Tailnet 경로와 대역이 겹치지 않아야 합니다. 기존 클러스터에 적용한다면 현재 리소스와 라우팅을 먼저 백업·검증하십시오.

## 8. Ansible Vault 설정

Vault는 Auth Key를 평문 변수 파일이나 명령줄에 적지 않기 위한 암호화 파일입니다. **Vault 비밀번호**는 `vault.yml`을 열기 위한 비밀번호이고, **Tailscale Auth Key**는 Tailscale 관리자 콘솔에서 발급받아 VM을 Tailnet에 가입시키는 인증 값입니다. 서로 바꿔 사용할 수 없습니다. 키를 발급할 때 필요한 태그·만료·재사용 정책은 Tailnet 관리자가 결정합니다.

| 항목 | 위치/사용 시점 | 주의사항 |
|---|---|---|
| Vault 파일 | Ubuntu VM의 `ansible/group_vars/vault.yml`; `setup.yml`이 매 실행마다 읽습니다. | **각 Ubuntu VM에서 직접 생성**합니다. 저장소에 업로드하지 않습니다. |
| Vault 비밀번호 | `ansible-vault` 편집 또는 `--ask-vault-pass` 실행 시 프롬프트에 입력합니다. | README, Git, 채팅, 명령줄 인수에 기록하지 마십시오. |
| Tailscale Auth Key | Vault 안의 `tailscale_auth_key` 값입니다. | 최초 가입이 필요한 상태에서만 Role이 검사·사용합니다. |

**실행 위치: Ubuntu VM의 `~/coldguard/ansible`.** 다음 명령으로 파일을 새로 만듭니다. 편집기가 열리면 아래 YAML을 입력하되 **`발급받은-인증키`를 본인의 실제 키로 교체**하고 저장하십시오. 생성 시 입력하는 비밀번호는 Auth Key가 아니라 Vault 비밀번호입니다.

```bash
ansible-vault create group_vars/vault.yml
```

```yaml
---
tailscale_auth_key: "발급받은-인증키"
```

수정이 필요하면 평문 파일로 복호화해 두지 말고 아래 명령으로 편집하십시오. `head` 출력이 `$ANSIBLE_VAULT;`로 시작하면 파일이 암호화된 형태입니다. `git check-ignore`는 루트 `.gitignore`의 제외 규칙이 적용되는지 보여줍니다.

```bash
ansible-vault edit group_vars/vault.yml
head -n 1 group_vars/vault.yml
git check-ignore -v group_vars/vault.yml
```

> [!WARNING]
> `.gitignore`는 `ansible/group_vars/vault.yml`을 제외하지만 이미 추적한 파일의 업로드까지 막지는 못합니다. 커밋 전 `git status --short`로 비밀 파일이 포함되지 않았는지 확인하십시오. 실제 Auth Key와 Vault 비밀번호를 공유하거나 README에 기록하지 마십시오.

키에 `tag:test-vm`이 이미 지정되어 있다면 현재 Role의 `tailscale up --auth-key=file:...` 명령은 추가 태그 옵션 없이 그 키로 가입을 시도합니다. 실제 가입·태그·ACL/Grants는 **Tailscale 관리자 콘솔**에서 확인하십시오. 이미 `Running`이면 가입 Task가 스킵되며 **현재 Tailnet이 의도한 곳인지 코드는 검사하지 않습니다.** 최초 실행과 재실행 모두 `setup.yml`이 Vault 파일을 읽으므로 `--ask-vault-pass`를 사용합니다.

## 9. Role별 동작 설명

### Common

| 항목 | 실제 동작 |
|---|---|
| 목적/파일 | Ubuntu 24.04 검사와 공통 도구 설치: `roles/common/tasks/main.yml` |
| 입력 변수 | `all.yml`의 직접 사용 변수는 없습니다. Ansible OS facts를 사용합니다. |
| 순서/주요 Task | OS 버전 assert → APT 캐시 갱신(`cache_valid_time: 3600`) → `git`, `buildah`, `openssl`, `mosquitto-clients`, `curl`, `ca-certificates`, `ufw` 설치 → `package_facts`로 모두 존재하는지 assert |
| 검증 | 11절의 버전 명령 및 `dpkg -s mosquitto-clients curl ca-certificates ufw`를 확인하십시오. |
| 재실행/주의 | 설치된 패키지는 유지합니다. APT 캐시 유효 시간이 지나면 캐시 갱신으로 `changed`가 나올 수 있습니다. Git은 Clone용으로 사전 설치해야 합니다. |

### Tailscale

| 항목 | 실제 동작 |
|---|---|
| 목적/파일 | VPN 설치·가입·검증: `roles/tailscale/tasks/main.yml` |
| 입력 변수 | `tailscale_version`, Vault의 `tailscale_auth_key`(미가입 시). `tailscale_snat_subnet_routes`는 **사용하지 않습니다**. |
| 순서/주요 Task | Ubuntu Noble 공식 GPG 키와 APT 목록 다운로드 → 캐시 갱신 → `apt-cache madison tailscale` 결과에서 버전 선택/검증 → 지정 패키지 설치 → `tailscaled` 활성화 → JSON `BackendState` 확인 → `NeedsLogin`/`NoState`일 때 임시 0600 파일로 Auth Key 전달 및 파일 삭제 → `tailscale set --snat-subnet-routes=false` → 버전·`Running`·IPv4 확인 |
| 검증 | 11절의 `tailscale status`, `tailscale ip -4`, 서비스 상태와 관리자 콘솔의 기기·Tailnet을 확인하십시오. |
| 재실행/주의 | `Running`이면 재가입하지 않습니다. 이미 다른 Tailnet에서 `Running`이어도 자동 전환하지 않습니다. `tailscale set`은 매번 실행되지만 `changed_when: false`입니다. SNAT 비활성화가 적용된 상태인지는 별도로 확인해야 하며 서브넷 경로 광고는 코드에 없습니다. |

### Firewall

| 항목 | 실제 동작 |
|---|---|
| 목적/파일 | UFW 규칙·기본 정책·활성화: `roles/firewall/tasks/main.yml` |
| 입력 변수 | `ufw_default_incoming`, `ufw_default_outgoing`, `ufw_default_routed`, `ufw_ssh_port`, `ufw_tailscale_interface`, `ufw_k3s_pod_cidr`, `ufw_k3s_service_cidr` |
| 순서/주요 Task | UFW 설치 확인 → SSH·Tailscale·Pod·Service 허용 → incoming/outgoing/routed 정책 설정 → UFW 활성화 → `Status: active` 검증·상태 출력 |
| 검증 | `sudo ufw status verbose`에서 활성 상태, 기본 정책, 실제 허용 규칙을 확인하십시오. |
| 재실행/주의 | 같은 UFW 규칙을 반복 추가하지 않도록 모듈이 현재 상태를 확인합니다. 이전에 다른 값으로 생성한 규칙을 자동 제거하는 Task는 없습니다. |

| 규칙/정책 | 기본값 | 방향/범위 | 변경 위치 |
|---|---|---|---|
| Incoming | `deny` | 기본 입력 정책 | `ufw_default_incoming` |
| Outgoing | `allow` | 기본 출력 정책 | `ufw_default_outgoing` |
| Routed | `deny` | 기본 전달 정책 | `ufw_default_routed` |
| SSH | `22/tcp` 허용 | 들어오는 TCP | `ufw_ssh_port` |
| Tailscale | `tailscale0` 허용 | 해당 입력 인터페이스 | `ufw_tailscale_interface` |
| K3s Pod | `10.42.0.0/16` 허용 | 해당 출발지의 입력 | `ufw_k3s_pod_cidr` |
| K3s Service | `10.43.0.0/16` 허용 | 해당 출발지의 입력 | `ufw_k3s_service_cidr` |

> [!WARNING]
> UFW 활성화는 SSH 연결을 끊을 수 있습니다. **실제 SSH 포트**와 `ufw_ssh_port`를 맞추고 VMware 콘솔에서 복구할 수 있는지 확인한 후 실행하십시오. Pod/Service의 `from_ip` 규칙과 `routed: deny`만으로 모든 Kubernetes 전달 경로가 허용된다고 단정할 수 없습니다.

### K3s

| 항목 | 실제 동작 |
|---|---|
| 목적/파일 | 단일 K3s 서버 설치·검증: `roles/k3s/tasks/main.yml`, `roles/k3s/templates/config.yaml.j2` |
| 입력 변수 | `k3s_version`, `k3s_node_ip`, `k3s_cluster_cidr`, `k3s_service_cidr`, `k3s_disable_traefik` |
| 순서/주요 Task | 실행 사용자 자동 감지 → node IP 검사 → forwarding 파일 작성·`sysctl -p` → K3s 설정 렌더링 → `/usr/local/bin/k3s`가 없을 때만 공식 설치 스크립트 다운로드·설치 → 서비스 활성화/설정 변경 시 재시작 → 버전 검증 → 사용자 홈의 `.kube/config` 복사 및 `.bashrc`에 `KUBECONFIG` 등록 → 최대 12회 재시도하며 Node Ready 확인 |
| 검증 | 11절의 `k3s --version`, `kubectl get nodes -o wide`, Pod와 StorageClass, 서비스 상태를 확인하십시오. |
| 재실행/주의 | 바이너리가 있으면 설치 Task는 스킵합니다. 설정 파일이 변하면 기존 서비스는 재시작됩니다. 버전 변수만 바꾸면 설치가 스킵되고 검증 단계에서 실패할 수 있습니다. |

| 템플릿 입력 | 실제 `/etc/rancher/k3s/config.yaml` 항목 | 의미 |
|---|---|---|
| `k3s_node_ip` | `node-ip` | 노드에 사용할 IPv4입니다. |
| `k3s_cluster_cidr` | `cluster-cidr` | Pod 주소 대역입니다. |
| `k3s_service_cidr` | `service-cidr` | Service 주소 대역입니다. |
| `k3s_disable_traefik: true` | `disable:` 아래 `traefik` | 번들 Traefik을 비활성화합니다. `false`이면 이 항목을 출력하지 않습니다. |

템플릿에는 ServiceLB 또는 local-path를 끄는 설정이 **없습니다**. 따라서 이 플레이북은 둘을 명시적으로 비활성화하지 않으며, 설치 후 실제 상태는 `kubectl get pods -A`와 `kubectl get storageclass`로 확인하십시오. `/etc/rancher/k3s/config.yaml`은 root 소유 `0600`입니다. `.kube/config`도 사용자 전용 `0600`으로 복사되며 `.bashrc`에는 `export KUBECONFIG="$HOME/.kube/config"`가 들어갑니다. 현재 셸에 즉시 적용하려면 새로 로그인하거나 다음을 실행하십시오.

```bash
source ~/.bashrc
```

## 10. Playbook 실행 방법

**실행 위치: Ubuntu VM의 `~/coldguard/ansible`.** 문법 검사는 YAML, Playbook 및 모듈 참조를 확인합니다. 설치나 네트워크 통신을 실행하는 검사는 아닙니다.

```bash
ansible-playbook playbooks/setup.yml \
  --syntax-check \
  --ask-vault-pass
```

실제 설치 명령은 다음과 같습니다. `BECOME password`에는 **현재 Ubuntu 계정의 sudo 비밀번호**, `Vault password`에는 **Vault 파일을 만들 때 정한 비밀번호**를 입력합니다. Auth Key는 명령 입력창이 아니라 암호화된 `vault.yml`에서 읽습니다.

```bash
ansible-playbook playbooks/setup.yml \
  --ask-become-pass \
  --ask-vault-pass
```

Role은 Common → Tailscale → Firewall → K3s 순서입니다. 출력의 `ok`는 이미 원하는 상태, `changed`는 변경 적용, `skipped`는 조건에 따라 실행하지 않음, `failed`는 오류를 뜻합니다. 마지막 `PLAY RECAP`의 `unreachable`과 `failed`가 0인지 먼저 확인하십시오. `changed`가 있어도 최초 설치나 APT 캐시 갱신이라면 정상일 수 있습니다. 실패하면 **첫 실패 Task 이름과 메시지**, Vault/권한 프롬프트, 인터넷·DNS, APT의 요구 버전, Tailscale 상태, UFW 규칙, K3s 서비스를 차례로 확인하십시오. 설치 후 검증은 11~12절의 명령으로 진행하십시오.

## 11. 설치 후 검증 가이드

**실행 위치: Ubuntu VM 터미널.** `kubectl` 명령은 플레이북을 실행한 **같은 일반 사용자**로, 새 로그인 셸에서 실행하십시오. 각 행의 명령을 순서대로 실행해 결과를 비교하십시오.

| 대상 | 확인 명령어 | 성공 기준 |
|---|---|---|
| Common | 아래 첫 코드 블록 | 각 버전이 표시되고 `dpkg -s`가 `Status: install ok installed`를 표시합니다. |
| Tailscale | 아래 둘째 코드 블록 | `tailscale version` 첫 줄이 지정 버전, `status`에 의도한 Tailnet의 기기가 보이고 IPv4가 표시되며 `tailscaled`가 `active`입니다. |
| Firewall/forwarding | 아래 셋째 코드 블록 | UFW `Status: active`; 의도한 정책·규칙 확인. `net.ipv4.ip_forward = 1`입니다. |
| K3s | 아래 넷째 코드 블록 | 버전 일치, Node `Ready`, 시스템 Pod 상태 확인, StorageClass 출력, `k3s` 서비스 `active`입니다. Pod의 일시적 초기화 상태는 잠시 후 재확인하십시오. |

```bash
git --version
buildah --version
openssl version
dpkg -s mosquitto-clients curl ca-certificates ufw
```

```bash
tailscale version
tailscale status
tailscale ip -4
sudo systemctl is-active tailscaled
```

```bash
sudo ufw status verbose
sysctl net.ipv4.ip_forward
```

```bash
k3s --version
kubectl get nodes -o wide
kubectl get pods -A
kubectl get storageclass
sudo systemctl is-active k3s
```

`kubectl`이 kubeconfig를 찾지 못하면 `source ~/.bashrc` 후 다시 실행하고 `ls -l ~/.kube/config`로 소유자·권한을 확인하십시오. 이 파일은 클러스터 관리자 접근 정보를 담으므로 다른 사용자에게 복사하지 마십시오.

## 12. Kubernetes 네트워크 검증

**실행 위치: Ubuntu VM의 플레이북 실행 사용자 셸.** 다음 테스트는 일회용 BusyBox Pod를 만들고 내부 DNS, 외부 DNS, 외부 IPv4를 확인합니다. `kubectl get pod`에서 `Running`이 될 때까지 확인한 다음 `exec` 명령을 실행하십시오.

```bash
kubectl run network-test \
  --image=busybox:1.36 \
  --restart=Never \
  --command -- sleep 3600

kubectl get pod network-test -o wide
kubectl exec network-test -- nslookup kubernetes.default.svc.cluster.local
kubectl exec network-test -- nslookup google.com
kubectl exec network-test -- ping -c 3 -W 2 1.1.1.1
```

내부 DNS는 Kubernetes Service 주소를, 외부 DNS는 조회 결과를 반환해야 합니다. Ping은 응답 3회와 패킷 손실률 0%가 목표입니다. 검증이 끝나면 Pod를 삭제합니다.

```bash
kubectl delete pod network-test
```

| 항목 | 제공된 **테스트 VM의 실제 관측 결과** | 다른 VM에서 기대할 내용 |
|---|---|---|
| Pod IP | `10.42.0.6` | Pod CIDR 안의 주소이며 동일한 IP를 보장하지 않습니다. |
| CoreDNS 주소 | `10.43.0.10` | 클러스터 설정과 서비스 배치에 따라 확인하십시오. |
| Kubernetes Service IP | `10.43.0.1` | Service CIDR과 현재 서비스에서 확인하십시오. |
| 외부 DNS/Ping | DNS 조회 성공, Ping 3회 성공, 손실률 0% | 각 VM에서 실제 통신을 다시 검증하십시오. |
| 정리 | 테스트 Pod 정상 삭제 | `kubectl get pod network-test`에서 더 이상 조회되지 않아야 합니다. |

## 13. 멱등성 검증

멱등성은 같은 플레이북을 다시 실행해도 이미 맞는 설정을 불필요하게 중복 변경하지 않는 성질입니다. 최초 실행에는 패키지 설치, 가입, 규칙·설정 생성으로 `changed`가 나옵니다. **재실행 시에도 10절의 동일한 명령과 Vault 비밀번호**를 사용하십시오.

```bash
ansible-playbook playbooks/setup.yml \
  --ask-become-pass \
  --ask-vault-pass
```

| 재실행 항목 | 코드에서 확인한 동작 |
|---|---|
| Tailscale 가입 | BackendState가 `Running`이면 Auth Key 검증과 가입 블록을 건너뜁니다. 다른 Tailnet인지 검사하지는 않습니다. |
| K3s 설치 | `/usr/local/bin/k3s`가 있으면 다운로드와 설치를 건너뜁니다. 버전 검증은 계속합니다. |
| UFW 규칙 | `community.general.ufw`가 같은 규칙의 현재 상태를 사용해 중복 추가를 피합니다. 과거 규칙 제거는 자동화되지 않았습니다. |
| APT 캐시 | `cache_valid_time: 3600`이 지나면 캐시 갱신으로 `changed`가 다시 나올 수 있습니다. |
| `changed=0` | 그 실행에서 Ansible이 보고한 변경이 없었다는 뜻입니다. 외부 네트워크나 기존 Tailnet의 정확성까지 보증하지는 않습니다. |

제공된 **테스트 VM의 최종 재실행 결과**는 아래와 같습니다. 새 VM의 Task 개수와 `skipped` 수는 환경에 따라 달라질 수 있습니다.

```text
PLAY RECAP
localhost : ok=56 changed=0 unreachable=0 failed=0 skipped=8
```

## 14. 트러블슈팅

아래 원인은 **가능한 원인 또는 코드에서 확인되는 동작**입니다. 해당 VM의 로그와 네트워크 상태를 확인한 뒤 판단하십시오. 비밀값이 담긴 출력은 공유하지 마십시오.

| 증상 | 가능한 원인/코드 동작 | 확인 명령어 또는 위치 | 해결 방법 |
|---|---|---|---|
| Auth Key가 없거나 잘못됨 | `NeedsLogin`/`NoState`에서 키가 없으면 assert 실패; 잘못된 키면 가입 실패 | `tailscale status`, `ansible-vault edit group_vars/vault.yml`, 관리자 콘솔 | **유효한 키**를 Vault의 `tailscale_auth_key`에 넣고 다시 실행하십시오. 키와 Vault 비밀번호를 혼동하지 마십시오. |
| Tailscale 요구 버전이 없음 | `apt-cache madison` 결과에 `tailscale_version`이 없어 assert 실패 | `apt-cache madison tailscale` | 저장소·APT 갱신을 확인하고 **설치 가능한 버전**으로 `all.yml`을 조정하십시오. 실패 메시지의 `1.104.7`은 코드에 고정되어 있어 다른 값을 설정해도 그 숫자가 표시될 수 있습니다. |
| `Running`이지만 다른 Tailnet에 연결됨 | Role은 BackendState만 검사하며 Tailnet 정체성을 검증하지 않음 | `tailscale status`, Tailscale 관리자 콘솔 | 관리 콘솔의 기기·Tailnet을 확인하십시오. 전환이 필요하면 담당자가 현재 연결을 검토하고 올바른 Tailnet으로 재가입한 뒤 다시 검증하십시오. |
| UFW 후 SSH/Tailscale 접속 불가 | 실제 SSH 포트, 인터페이스, ACL/Grants 또는 방화벽 규칙 불일치 가능 | **VMware 콘솔**에서 `sudo ufw status verbose`, `tailscale status` | 콘솔로 접속하여 **실제 포트와 `ufw_ssh_port`**, `tailscale0`, Tailnet 정책을 대조하고 규칙을 수정하십시오. |
| IPv4 forwarding이 `0` | K3s Role 이전에 확인했거나 sysctl 적용 실패 가능 | `sysctl net.ipv4.ip_forward`, `cat /etc/sysctl.d/90-coldguard-k3s.conf` | K3s Role 실패 지점을 확인하고 플레이북을 재실행하십시오. |
| UFW Routed가 `disabled`로 표시 | 표시 의미나 실제 전달 상태는 UFW/시스템 설정에 따라 다를 수 있으며, Role은 `policy: deny`만 설정·활성 상태만 검증 | `sudo ufw status verbose`, `sysctl net.ipv4.ip_forward` | **표시만으로 원인을 확정하지 말고** 12절의 Pod DNS·Ping과 현재 UFW 정책을 함께 확인하십시오. 전달 경로가 막혔다면 해당 VM의 UFW/라우팅 설정을 조사하십시오. |
| K3s Node가 `Ready`가 아님 | 서비스 시작 실패, CIDR 충돌, CNI·방화벽·DNS 문제 등 가능 | `sudo systemctl status k3s`, `sudo journalctl -u k3s -n 100 --no-pager`, `kubectl get nodes -o wide` | 첫 오류부터 확인하고 VM IP, CIDR, forwarding, UFW, 인터넷을 점검하십시오. Role은 15초 wait를 최대 12회 시도합니다. |
| `kubectl` kubeconfig 권한 오류 | 다른 사용자로 실행했거나 파일 소유권/권한·환경변수 불일치 | `id -un`, `ls -l ~/.kube/config`, `echo "$KUBECONFIG"` | 플레이북을 실행한 일반 사용자로 로그인하고 `source ~/.bashrc` 후 다시 확인하십시오. 다른 사용자로 실행했다면 대상 홈을 확인하십시오. |
| `/etc/rancher/k3s/config.yaml: permission denied` 경고 | 해당 파일은 root 소유 `0600`이라 일반 사용자에게 읽기 권한이 없음 | `sudo ls -l /etc/rancher/k3s/config.yaml`, `ls -l ~/.kube/config` | 파일 내용을 확인할 때만 `sudo`를 사용하십시오. 일반 `kubectl`은 사용자용 `~/.kube/config`를 사용하도록 설정하십시오. 경고가 나왔다고 해서 무조건 설치 실패로 단정하지 마십시오. |
| Pod 외부 DNS 조회 실패 | CoreDNS, 상위 DNS, Pod 라우팅·방화벽 문제 가능 | `kubectl get pods -A`, `kubectl exec network-test -- nslookup google.com` | 내부 DNS 결과와 비교하고 CoreDNS 상태, VM DNS, UFW 및 CIDR을 점검하십시오. |
| Pod 외부 인터넷 접속 실패 | forwarding, NAT/VMware, UFW routed 정책, 외부 경로 문제 가능 | `sysctl net.ipv4.ip_forward`, `sudo ufw status verbose`, `kubectl exec network-test -- ping -c 3 -W 2 1.1.1.1` | VM 자체의 인터넷 접속과 Pod 접속을 분리해 확인하고 라우팅·방화벽을 수정하십시오. |
| Tailscale Ping이 한 방향만 성공 | ACL/Grants, 상대 기기의 방화벽, 경로/NAT 등 여러 원인 가능 | 양쪽 VM의 `tailscale status`, `tailscale ping <상대-기기>`, 관리자 콘솔 | 양쪽에서 대상·정책·방화벽·경로를 각각 확인하십시오. 한 방향 결과만으로 원인을 확정하지 마십시오. |
| Tailscale이 DERP 경로를 사용 | 직접 경로 협상이 되지 않은 상태일 수 있으며 원인은 환경별로 다름 | `tailscale ping <상대-기기>`, `tailscale netcheck` | 양쪽 네트워크의 NAT·방화벽·UDP 허용 상태와 Tailnet 정책을 확인하십시오. DERP 표시만으로 연결 실패라고 판단하지 마십시오. |

`<상대-기기>`는 실제 상대 기기의 Tailscale 이름 또는 IP로 **교체**하십시오. 표의 `ansible-vault edit`는 암호화 파일을 열기 위한 명령이며, 키를 터미널 출력으로 공개하는 명령이 아닙니다.

## 15. 보안 및 운영 주의사항

> [!WARNING]
> **실제 Auth Key와 Vault 비밀번호를 GitHub, README, 채팅, 터미널 명령 인수에 남기지 마십시오.** `vault.yml`은 VM마다 생성하고 `.gitignore` 적용 여부와 `git status --short`를 커밋 전 확인하십시오. `~/.kube/config`에는 관리자 접근 정보가 있으므로 `0600` 권한을 유지하십시오.

| 항목 | 운영 시 확인할 내용 |
|---|---|
| 변경 전 보호 | **운영 VM 적용 전 VMware 스냅샷과 필요한 데이터 백업**을 만들고 복구 절차를 확인하십시오. |
| 주소 구분 | 운영·테스트 VM의 IP를 혼동하지 말고 실제 기본 IPv4와 NAT/게이트웨이를 확인하십시오. |
| Tailnet 접근 | 관리자 콘솔에서 가입 기기, 키의 태그, ACL/Grants를 확인하십시오. 코드가 기존 Tailnet의 정체성을 검사하지 않습니다. |
| 네트워크 | UFW `routed: deny` 및 Pod/Service 허용 규칙이 실제 Kubernetes 트래픽과 충돌할 수 있으므로 12절 테스트를 수행하십시오. |
| 실행 사용자 | 다른 계정으로 플레이북을 실행하면 그 계정의 홈에 kubeconfig가 만들어집니다. 사용자와 그룹 이름이 다른 환경은 Role 동작을 점검하십시오. |
| 버전 | Tailscale은 APT 패키지 가용성과 다운그레이드 영향을 확인하십시오. K3s는 변수만 변경해도 기존 설치가 업그레이드되지 않습니다. |

## 16. 작업 완료 체크리스트

- [ ] Ubuntu 24.04 VM, 자원, 네트워크, sudo 계정을 준비했습니다.
- [ ] 운영/테스트 VM의 IP·게이트웨이를 구분하고 운영 적용 전 스냅샷·백업을 만들었습니다.
- [ ] Ubuntu VM에 Git, Python 3, Ansible을 설치하고 `community.general.ufw`를 확인했습니다.
- [ ] 실제 Git 원격 주소에서 저장소를 Clone하고 `ansible/`로 이동했습니다.
- [ ] `group_vars/all.yml`의 14개 변수와 실제 VM 네트워크를 검토했습니다.
- [ ] Tailscale 관리자에게 적절한 Auth Key를 발급받고 태그·ACL/Grants를 확인했습니다.
- [ ] VM에서 `group_vars/vault.yml`을 암호화해 생성하고 Git 제외 상태를 확인했습니다.
- [ ] `--syntax-check --ask-vault-pass`로 문법을 확인했습니다.
- [ ] `--ask-become-pass --ask-vault-pass`로 `setup.yml`을 실행하고 `failed=0`을 확인했습니다.
- [ ] 의도한 Tailnet 가입, Tailscale IP, `tailscaled` 서비스를 확인했습니다.
- [ ] UFW 활성 상태·SSH/Tailscale/K3s 규칙과 IPv4 forwarding을 확인했습니다.
- [ ] K3s Node `Ready`, Pod, StorageClass, 서비스를 확인했습니다.
- [ ] 실행 사용자 `~/.kube/config`의 접근·권한을 확인했습니다.
- [ ] 테스트 Pod의 내부 DNS·외부 DNS·인터넷 통신을 확인하고 Pod를 삭제했습니다.
- [ ] 플레이북을 재실행해 `PLAY RECAP`의 변경·실패 수를 확인했습니다.
