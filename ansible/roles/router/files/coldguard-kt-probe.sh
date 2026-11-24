#!/usr/bin/env bash
# ==========================================
# ColdGuard KT 허브 상태 확인
# ==========================================
# 1분마다 systemd timer가 실행한다.
# KT 허브의 구성 요소 4개를 호출해 성공이면 1, 실패면 0을
# CloudWatch ColdGuard/KTHub 이름공간의 ProbeSuccess 지표로 올린다.
#
# Terraform monitoring 모듈의 알람과 짝을 이룬다.
# 이름공간, 지표 이름, Component 값을 바꾸면 알람도 함께 바꿔야 한다.
# 권한은 라우터 인스턴스 role(PutMetricData, ColdGuard/KTHub 한정)을 쓴다.

set -uo pipefail

CONF="/etc/coldguard/kt-probe.env"
# shellcheck source=/dev/null
[ -r "$CONF" ] && . "$CONF"

HUB_HOST="${HUB_HOST:-100.98.228.126}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
NAMESPACE="${NAMESPACE:-ColdGuard/KTHub}"
TIMEOUT="${TIMEOUT:-5}"
AWS_BIN="${AWS_BIN:-$(command -v aws || echo /snap/bin/aws)}"

# Component 이름은 Terraform kt_hub_components와 같아야 한다
COMPONENTS=(prometheus alertmanager loki grafana)

check_url() {
  case "$1" in
    prometheus)   echo "http://${HUB_HOST}:9090/-/healthy" ;;
    alertmanager) echo "http://${HUB_HOST}:9093/-/healthy" ;;
    loki)         echo "http://${HUB_HOST}:3100/ready" ;;
    grafana)      echo "http://${HUB_HOST}:3000/api/health" ;;
  esac
}

ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
metrics=""
summary=""

for comp in "${COMPONENTS[@]}"; do
  if curl -fs -o /dev/null --max-time "$TIMEOUT" "$(check_url "$comp")"; then
    value=1
  else
    value=0
  fi

  summary+="${comp}=${value} "
  metrics+="{\"MetricName\":\"ProbeSuccess\",\"Dimensions\":[{\"Name\":\"Component\",\"Value\":\"${comp}\"}],\"Value\":${value},\"Unit\":\"Count\",\"Timestamp\":\"${ts}\"},"
done

metrics="[${metrics%,}]"

# 결과는 journal에 남는다: journalctl -u coldguard-kt-probe
echo "probe ${summary}"

if ! "$AWS_BIN" cloudwatch put-metric-data \
  --region "$AWS_REGION" \
  --namespace "$NAMESPACE" \
  --metric-data "$metrics"; then
  echo "put-metric-data failed" >&2
  exit 1
fi
