# router role (AWS Tailscale 서브넷 라우터)

AWS 서브넷 라우터(`aws_router` 그룹, Ubuntu 24.04)에 다음을 설정한다. 지금은 `files/`만 있고, 작업(tasks)은 IaC 담당이 작성한다.

## 라우터가 하는 일

1. AWS VPC(`10.80.0.0/16`)를 tailnet에 광고한다. tailnet에서 VPC로 들어오는 트래픽은 라우터 사설 IP로 SNAT된다.
2. 1분마다 KT 허브 구성 요소 4개를 확인해 CloudWatch에 올린다.

VPC → tailnet 방향(EKS Pod가 KT 허브로 지표·로그를 보내는 경로)은 Tailscale Kubernetes operator의 egress 프록시가 맡으므로 라우터에는 MASQUERADE를 두지 않는다.

## 작업 목록

| 순서 | 작업 | 내용 |
|---|---|---|
| 1 | IP forwarding | `net.ipv4.ip_forward=1`(사용자 데이터에 있음), `net.ipv6.conf.all.forwarding=1` 추가 (`/etc/sysctl.d/99-coldguard-router.conf`) |
| 2 | Tailscale 가입 | tailscale role 재사용. `--auth-key`(vault), `--advertise-tags=tag:aws-router`, `--advertise-routes=10.80.0.0/16`, `--ssh`, `--hostname=coldguard-aws-router`. SNAT 켬(기본값). 이미 연결돼 있으면 건너뛴다(옵션이 다르면 `tailscale up`이 오류를 냄) |
| 3 | AWS CLI | `snap install aws-cli --classic` (Ubuntu 24.04 apt에는 없음) |
| 4 | 프로브 파일 | `files/coldguard-kt-probe.sh` → `/usr/local/bin/` (0755), `files/coldguard-kt-probe.service`·`.timer` → `/etc/systemd/system/`, `files/kt-probe.env.example` → `/etc/coldguard/kt-probe.env` |
| 5 | 타이머 | `systemctl daemon-reload`, `systemctl enable --now coldguard-kt-probe.timer` |

인증 키는 `tag:aws-router`로 Admin만 발급할 수 있다. 1회용, 1일 만료로 발급하고 가입 후 폐기한다.

## 프로브 규약

Terraform `monitoring` 모듈의 알람과 짝을 이룬다. 아래 값을 바꾸면 알람도 함께 바꿔야 한다.

| 항목 | 값 |
|---|---|
| 이름공간 | `ColdGuard/KTHub` |
| 지표 | `ProbeSuccess` (1 성공, 0 실패) |
| 차원 | `Component` = `prometheus`, `alertmanager`, `loki`, `grafana` |
| 확인 주소 | `:9090/-/healthy`, `:9093/-/healthy`, `:3100/ready`, `:3000/api/health` |
| 주기 | 1분 (알람은 3분 연속 0이거나 지표가 끊기면 ALARM) |
| 권한 | 라우터 인스턴스 role. `ColdGuard/KTHub` 이름공간에만 `PutMetricData` |

## 확인

```bash
systemctl list-timers coldguard-kt-probe.timer
journalctl -u coldguard-kt-probe -n 5      # probe prometheus=1 alertmanager=1 ...
tailscale ping coldguard-kt-hub
```

허브 스택이 올라가기 전에는 모든 값이 0이고 KT 허브 알람 4개가 ALARM인 것이 정상이다.
