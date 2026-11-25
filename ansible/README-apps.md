# **시설 앱 배포 / 수동 릴리스**

이 문서는 기존 시설에 설치된 애플리케이션을 별도로 배포하는 방법을 설명합니다.

이 배포 경로에서는 다음 작업을 수행하지 않습니다.

- `setup-k3s.yml` 또는 `deploy-k3s.yml` 실행
- 해당 파일의 `vars_files` 읽기
- K3s 설치
- Credential Provider 변경
- 인프라 재생성

이 문서는 `coldguard`에 이미 존재하는 다음 Deployment만 대상으로 합니다.

- collector
- controller
- field-web

## **사전 준비 사항**

- 권한이 있는 Linux 제어 노드(기존 학생 서버), Python 3 및 Ansible Core
- Tailscale 연결, 확인된 SSH 호스트 키, 권한이 있는 SSH 계정 및 sudo 접근 권한
- 시설에 `/usr/local/bin/k3s`가 이미 설치되어 있어야 합니다. 다른 경로에 설치되어 있다면 `app_kubectl` 값을 변경합니다.
- 기존 애플리케이션이 Ready 상태이고, replicas=1, Recreate 전략이어야 합니다. 해당 앱에는 HPA가 없어야 합니다.
- 기존 Secret, ConfigMap, Bound PVC 및 Service가 있어야 합니다. 기존 키와 참조는 그대로 유지됩니다.
- 최초 실행 전에 `deploy/apps-alpine.yaml`을 실제 시설 설정과 일치시켜야 합니다.
- 최초 교체 전에 운영 담당자와 사용 가능한 상태 DB 백업 또는 스냅샷이 있는지 확인합니다.
  - 이 도구는 Deployment 설정을 백업하지만 SQLite/MySQL 데이터는 백업하지 않습니다.
  - 상태 DB를 절대 삭제하지 마세요.
- 임의의 최신 태그가 아니라 CI에서 승인된 릴리스를 선택합니다. 시설에서 ECR 이미지를 가져오는 작업은 별도로 테스트되었습니다.

## **전체 템플릿을 다시 적용하지 않는 이유**

실제 실행 중인 Deployment를 읽고, 각 메인 컨테이너의 이미지, command, args만 변경합니다.

다음 항목은 모두 기존 설정을 유지합니다.

- env / envFrom
- probes
- UID/GID
- volume mounts
- PVC 참조
- labels
- ports

이렇게 하면 오래된 통합 YAML로 현재 설정을 덮어쓰는 것을 방지할 수 있습니다.

PVC, Service, Secret, ConfigMap은 적용하지 않습니다. 세 앱 모두 사전 검사를 통과해야 합니다.

기존 통합 YAML은 인프라 참조용으로 유지합니다. 향후 전체 YAML을 다시 적용할 경우 이미지가 GHCR로 되돌아가지 않도록 조율해야 합니다.

## **기존 Linux 제어 노드에 설치하기**

기존에 승인된 접근 권한을 사용합니다. 이 저장소는 접근 권한을 부여하거나 키를 배포하지 않습니다.

```
cd ~/coldguard-iac
git fetch origin
git switch --track origin/feat/ansible-app-deploy  # 최초 체크아웃, 브랜치가 push된 이후
cd ansible
python3 -m venv .venv-apps
. .venv-apps/bin/activate
python -m pip install -r requirements-apps.txt
```

현재 체크아웃에 로컬 인프라 변경 사항이 있다면 덮어쓰지 마세요. 검토용 별도 clone을 사용합니다.

기존의 추적되지 않는 Vault 파일은 새 clone에 포함되지 않으며, 아래의 독립된 inventory에서는 필요하지 않습니다.

## **로컬 입력 파일 (작성한 파일은 커밋하지 마세요)**

```
cp app-inventory.example.ini app-inventory.local.ini
cp app-release.example.json app-release.local.json
nano app-inventory.local.ini
nano app-release.local.json
```

`ansible_host`에는 시설의 Tailscale IP를 설정합니다.

각 `app_images` 값은 각각 별도의 ECR 저장소를 지정해야 하며, 다음 중 하나로 끝나야 합니다.

- 전체 40자리 commit SHA 태그
- `@sha256:` 뒤에 64자리 16진수 digest

허용되는 앱은 collector, controller, field-web뿐입니다. `central-worker`는 EKS 대상입니다.

예제 파일에는 실제로 사용할 수 있는 주소, 비밀번호, 이미지 계정 ID가 의도적으로 포함되어 있지 않습니다.

Ansible은 MQTT/DB 비밀번호를 필요로 하지 않습니다. 기존 Kubernetes Secret을 그대로 사용합니다.

비밀번호 방식 SSH/sudo를 사용하는 경우 `-k`와 `-K` 옵션으로 기존 승인 계정의 비밀번호를 입력합니다.

제어 노드에서 `-k`를 사용하려면 `sshpass`가 필요합니다. 필요한 경우 관리자가 시스템 패키지 관리자를 통해 설치할 수 있습니다.

SSH 키 방식 사용자는 `-k`를 생략할 수 있습니다. 승인된 sudo 설정에서 비밀번호가 필요하지 않은 경우에만 `-K`를 생략하세요.

호스트 키 확인을 비활성화하지 마세요. 운영 담당자에게 SSH 지문을 확인하세요.

이 독립된 앱 배포 플레이북에서 암호화된 vars 파일을 읽도록 inventory를 변경하지 않는 한 `--ask-vault-pass`를 추가하지 마세요.

평문 비밀 정보나 상태 스냅샷을 절대 커밋하지 마세요.

## **시설 연결 없이 검증하기**

```
python -m unittest discover -s tests -v
ansible-playbook -i app-inventory.example.ini playbooks/deploy-apps.yml --syntax-check
```

## **연결 확인 및 배포 계획 (Kubernetes 변경 없음)**

```
ansible -i app-inventory.local.ini onprem -m ping -k -K
ansible-playbook -i app-inventory.local.ini playbooks/deploy-apps.yml \
  -k -K -e @app-release.local.json -e app_mode=plan
```

계획 모드에서는 읽기 전용 Kubernetes 호출만 수행합니다.

시설에 임시 비공개 helper/request 파일과 로컬 실행 잠금 디렉터리가 생성되며, 가능한 경우 정리됩니다.

출력에는 기존/새 이미지와 `would_change`가 표시됩니다. Kubernetes 리소스는 수정되지 않습니다.

`--check` 옵션은 `app_mode=apply`가 지정되어 있어도 계획 모드로 강제합니다.

자격 증명이나 전체 Deployment 객체는 출력하지 않습니다.

## **합의된 테스트 시간에 배포 적용하기**

다섯 개의 시뮬레이터를 계속 실행 상태로 유지합니다.

각 서비스에서 Recreate 전략으로 인해 잠시 중단이 발생할 수 있습니다.

이 전략에서는 이전 Pod와 새 메인 Pod가 동시에 실행되지 않습니다.

먼저 상태 백업을 확인하세요.

```
ansible-playbook -i app-inventory.local.ini playbooks/deploy-apps.yml \
  -k -K -e @app-release.local.json \
  -e app_mode=apply -e app_confirm_apply=true
```

배포 순서는 다음과 같습니다.

1. collector
2. controller
3. field-web

각 서비스의 롤아웃이 완료된 후 다음 서비스로 진행합니다.

실패하면 이후 서비스는 변경하지 않습니다.

helper는 이번 실행에서 변경된 앱을 역순으로 복원하려고 시도하지만, 복원이 성공하더라도 **명령은 실패 상태로 반환됩니다.**

롤백이 실패하거나 관련 없는 템플릿 변경이 감지되면 작업을 중단하고 운영 담당자의 검토가 필요합니다.

SSH 연결이 끊기거나 프로세스가 강제 종료되면 배포와 자동 롤백 모두 중단될 수 있습니다. 재시도하기 전에 시설 상태와 비공개 스냅샷을 확인하세요.

중단 후 무작정 다시 실행하지 마세요.

비공개 스냅샷은 시설에 다음 경로로 보관됩니다.

```
/var/lib/coldguard/app-deployments/<UTC-time>-<random>/snapshot.json
```

실제 환경 변수에 비밀 값이 포함될 수 있으므로 권한이 있는 배포 계정만 접근해야 합니다.

이 파일은 GitHub나 제어 노드로 복사되지 않습니다.

성공 출력에는 `backup_dir`이 표시됩니다. 이 경로와 이미지 digest를 기록하세요.

## **명시적 롤백**

출력에서 확인한 **이번 실행의 실제** `backup_dir` 을 사용하세요. 시간상 가장 최신일 것이라고 추측한 디렉터리를 사용하면 안 됩니다.

```
ansible-playbook -i app-inventory.local.ini playbooks/deploy-apps.yml \
  -k -K -e app_mode=rollback -e app_confirm_apply=true \
  -e app_backup_dir=/var/lib/coldguard/app-deployments/REPLACE_WITH_REAL_RUN
```

이미지, command, args만 복원됩니다.

다른 작업자가 배포 이후 Pod 템플릿을 변경했다면 롤백을 거부합니다.

패치 전에 Kubernetes `resourceVersion`을 확인합니다.

이 작업은 데이터베이스 롤백이 아닙니다. 상태 또는 스키마 변경과 호환되지 않는 릴리스는 피하세요.

## **기능 검증 / 별도로 필요한 확인**

- 롤아웃 성공은 readiness/liveness probe 통과를 의미하며, MQTT/DB의 전체 연동이 정상이라는 뜻은 아닙니다.
- 운영 담당자: `fz01`~`fz05`의 최신 telemetry와 seq가 MySQL에서 증가하는지, 중복이 없는지 확인합니다.
- 개발 담당자: 현장 웹의 상태 및 로그 검색, 장치별 문 조작을 확인합니다.
- Controller: 허용된 명령은 적용되고, 만료/범위 초과/잠금 명령은 거부되는지 확인합니다.
- 모니터링 담당자: 9201/9202 메트릭, 문/냉각 및 미전송 이벤트를 확인합니다.
- 재시작/롤백: 기존 상태 파일과 설정이 유지되는지 확인하고 테스트 시간을 사전에 조율합니다.
- Service, PVC, ConfigMap, CA 및 Secret 참조는 변경되지 않습니다.

## **범위**

수동 Ansible 실행이 릴리스 트리거입니다.

GitHub self-hosted runner나 자동 프로덕션 배포는 설치되지 않습니다.

현재 ECR Credential Provider를 재사용합니다.

앱 릴리스 과정에서 인프라 설정/배포 플레이북을 실행하지 마세요.