# ColdGuard — NAT 자동 Failover / 수동 Failback 검증 README

> 검증 기준: 2026-11-20 · AWS 리전 `ap-northeast-2`  
> 프로젝트: ColdGuard (`prod`)  
> 이 문서는 실제 수행한 테스트와 아직 확인하지 않은 항목을 구분합니다.

## 1. 개요

ColdGuard는 두 AZ(`ap-northeast-2a`, `ap-northeast-2c`)에 고정 ENI/EIP를 사용하는 NAT EC2와 Auto Scaling Group(ASG)을 각각 배치합니다. 각 Private Route Table의 기본 경로(`0.0.0.0/0`)는 평소 동일 AZ의 NAT ENI로 향합니다. NAT ASG의 `GroupInServiceInstances`가 0으로 관측되면 CloudWatch Alarm → EventBridge → Lambda를 거쳐 장애 AZ의 Private Route Table 기본 경로를 반대 AZ의 NAT ENI로 전환합니다. NAT가 복구되어도 경로는 **자동으로 원복하지 않고 운영자가 수동 Failback**합니다.

```text
Normal:    Private A → NAT-A → IGW → Internet
           Private C → NAT-C → IGW → Internet
NAT-A 장애: Private A ─┐
                      ├→ NAT-C → IGW → Internet
           Private C ─┘
NAT-C 장애: Private C ─┐
                      ├→ NAT-A → IGW → Internet
           Private A ─┘
```

장애 처리 보호 기능: Lambda Errors/Throttles CloudWatch Alarm → SNS, Lambda 비동기 실행 실패 OnFailure Destination → SQS, EventBridge 대상 전달 실패 DLQ → SQS.

## 2. 테스트 환경과 주의사항

- AWS: 서울 리전 `ap-northeast-2`; VPC CIDR `10.80.0.0/16`.
- NAT-A/C: ASG 각각 `Min=1, Desired=1, Max=1`; 고정 ENI 및 연결된 EIP.
- CloudWatch NAT 장애 알람: `AWS/AutoScaling` / `GroupInServiceInstances` / `Minimum` / 60초 / 임계값 1 미만.
- Failover Lambda: `coldguard-prod-nat-failover`, Python, 예약 동시성 1. 자동 Failback 없음.
- 본 문서에 나온 리소스 ID는 **2026-11-20 재배포 환경의 예시**입니다. `terraform destroy` 후 다시 생성하면 ID와 EIP가 달라질 수 있으므로 실제 값을 조회한 뒤 실행해야 합니다.
- 장애 테스트는 Private EC2의 인터넷 연결을 끊을 수 있습니다. 운영 서비스에 바로 실행하지 마세요.
- AWS 콘솔에서 수동으로 생성한 EC2/보안 그룹은 Terraform 관리 대상이 아닐 수 있습니다. `destroy` 전 별도 정리하세요.
- 테스트용 파일에는 계정 자격 증명이나 비밀키를 포함하지 않습니다.

## 3. 검증 결과 요약

| 번호 | 항목 | 결과 | 근거 / 한계 |
|---|---|---|---|
| 1 | NAT-A 장애 → NAT-C 자동 Failover | **성공** | CloudWatch NAT-A ALARM, Private RT-A 경로 NAT-C ENI 전환, Private A 외부 통신 성공 |
| 2 | NAT-A 복구 후 수동 Failback | **성공** | 자동 원복 없음 확인, 수동 `replace-route`, NAT-A EIP로 외부 통신 성공 |
| 3 | NAT-C 장애 → NAT-A 자동 Failover | **성공** | Private C에서 NAT-A 공인 IP와 Ping 성공; CloudWatch/경로 전환은 테스트 과정에서 확인한 것으로 보고됨 |
| 4 | NAT-C 복구 후 수동 Failback | **성공** | Private RT-C가 NAT-C ENI, NAT-C EIP 출력, Ping 손실 0% |
| 5 | ASG EC2 교체 및 NAT 기능 | **성공** | 인스턴스 자동 재생성, NAT 설정 4개 및 Private 통신 2개 양쪽 확인했다고 보고됨 |
| 6 | Lambda Errors → CloudWatch → SNS | **성공** | 의도적 `AttributeError`, ALARM 및 SNS 이메일 수신, 이후 자동 OK 복귀 |
| 7 | Lambda 비동기 처리 실패 → SQS OnFailure | **성공** | `RetriesExhausted`, `approximateInvokeCount=3`, 오류 기록 수신 |
| 8 | Lambda Throttles → CloudWatch → SNS | **성공** | 예약 동시성 0으로 테스트, `Throttles=3`, 이메일 수신, 동시성 1 복구 |
| 9 | EventBridge 전달 실패 → 테스트용 SQS DLQ | **메시지 수신 확인** | 발행/수신 EventId 일치; `ERROR_CODE` 메시지 속성은 추가 확인 필요 |
| 10 | 정확한 RTO 측정 | **미진행** | 추후 별도 실시 |
| 11 | NAT 서비스만 중단되는 장애 감지 | **미진행** | ASG 인스턴스 수 기반 감지만으로는 감지 어려움 |

## 4. 공통 상태 조회 명령

다음 명령은 모두 Git Bash + AWS CLI 기준입니다. Windows Git Bash 환경에서 실행한 예시입니다.

### ASG 상태

```bash
aws autoscaling describe-auto-scaling-groups \
  --region ap-northeast-2 \
  --query "AutoScalingGroups[?contains(AutoScalingGroupName, 'coldguard')].[AutoScalingGroupName,MinSize,DesiredCapacity,Instances[].LifecycleState]" \
  --output json
```

정상 상태: NAT-A/C 각각 Min=1, Desired=1, `InService` 1대.

### Private Route Table

```bash
aws ec2 describe-route-tables \
  --region ap-northeast-2 \
  --filters "Name=tag:Name,Values=coldguard-prod-private-rt-a,coldguard-prod-private-rt-c" \
  --query "RouteTables[].{Name:Tags[?Key=='Name'].Value|[0],ID:RouteTableId,DefaultRoute:Routes[?DestinationCidrBlock=='0.0.0.0/0'].[NetworkInterfaceId,State]}" \
  --output json
```

2026-11-20 테스트 배포 당시:

| 구성 | RT ID | 고정 ENI |
|---|---|---|
| Private A / NAT-A | `rtb-xxxxxxxx` | `eni-xxxxxxxx` |
| Private C / NAT-C | `rtb-xxxxxxxx` | `eni-xxxxxxxx` |

**반드시 현재 배포값을 먼저 조회하세요.**

## 5. NAT-A 장애 → NAT-C Failover

1. Private A 테스트 EC2에서 `curl` 및 `ping`으로 정상 인터넷을 확인합니다.
2. AWS 콘솔 → EC2 → Auto Scaling 그룹 → `coldguard-prod-nat-a-asg`에서 Min=0, Desired=0으로 설정합니다. NAT-C는 1대로 유지합니다.
3. CloudWatch의 `coldguard-prod-nat-a-failover-alarm`이 `ALARM`인지 확인합니다.
4. Private RT-A의 기본 경로가 NAT-C 고정 ENI로 변경됐는지 확인합니다.
5. Private A 테스트 EC2에서 외부 공인 IP가 NAT-C EIP로 바뀌고 Ping이 성공하는지 확인합니다.

```bash
# Private A 테스트 EC2
curl -4 --max-time 10 https://checkip.amazonaws.com
ping -c 4 8.8.8.8
```

**기록된 시험 결과(이전 배포):** Failover 시 출구 IP `<NAT-C EIP>`, Ping 4/4 수신·손실 0%. 이 IP는 이후 재배포 값과 다릅니다.

### NAT-A 수동 Failback

1. NAT-A ASG를 Min=1, Desired=1로 복구합니다.
2. `InService`, EC2 상태 검사, NAT 서비스 및 iptables를 확인합니다.
3. 자동으로 NAT-A 경로가 복원되지 않았는지 확인합니다.
4. 담당자가 수동으로 Private RT-A 기본 경로를 NAT-A ENI로 교체합니다.

```bash
aws ec2 replace-route \
  --region ap-northeast-2 \
  --route-table-id <현재-PRIVATE-RT-A-ID> \
  --destination-cidr-block 0.0.0.0/0 \
  --network-interface-id <현재-NAT-A-ENI-ID>
```

`<...>` 부분은 조회한 ID로 교체 후 실행합니다. 기존 연결이 순간적으로 끊길 수 있습니다.

**기록된 시험 결과(이전 배포):** 수동 원복 후 NAT-A 출구 IP `3.35.186.183`, Ping 4/4·손실 0%.

## 6. NAT-C 장애 → NAT-A Failover 및 수동 Failback

1. Private C에서 외부 통신 정상 확인.
2. `coldguard-prod-nat-c-asg`를 Min=0, Desired=0으로 설정합니다. NAT-A는 유지합니다.
3. NAT-C 알람 확인 후 Private RT-C가 NAT-A ENI로 변경되었는지 확인합니다.
4. Private C에서 NAT-A의 EIP를 확인하고 Ping 성공을 확인합니다.
5. NAT-C ASG를 Min=1, Desired=1로 복구하고 NAT 내부 설정을 확인합니다.
6. 자동 Failback이 발생하지 않았음을 확인한 뒤 수동으로 RT-C를 NAT-C ENI로 원복합니다.

```bash
# 2026-11-20 배포에서 사용한 수동 Failback 명령 (재배포 시 ID 교체 필수)
aws ec2 replace-route \
  --region ap-northeast-2 \
  --route-table-id rtb-080c83c16e09037a0 \
  --destination-cidr-block 0.0.0.0/0 \
  --network-interface-id eni-0a12bffddf2704fa6
```

**실제 복구 후 확인 결과:** Private RT-C `eni-0a12bffddf2704fa6` (`active`), 출구 IP `43.200.28.221`(NAT-C EIP), Ping 4/4 수신·손실 0%, 평균 약 28.9ms.

## 7. ASG EC2 강제 종료 및 고정 NAT 기능 검증

ASG Min/Desired/Max를 각각 1로 유지하면서 **NAT EC2 인스턴스만 종료**합니다. ASG가 새 인스턴스를 생성하면 새 Instance ID, 기존 고정 ENI/EIP 유지 여부 및 인터넷 통신을 확인합니다.

### NAT EC2 안에서 실행할 4개 명령

```bash
sudo sysctl net.ipv4.ip_forward
sudo systemctl status coldguard-nat --no-pager
sudo iptables -t nat -S POSTROUTING
sudo iptables -S FORWARD
```

정상 예시: `ip_forward=1`, `active (exited)`, `-A POSTROUTING -s 10.80.0.0/16 -o ens5 -j MASQUERADE`, FORWARD 경로 허용.

### Private EC2 안에서 실행할 2개 명령

```bash
curl -4 --max-time 10 https://checkip.amazonaws.com
ping -c 4 8.8.8.8
```

ASG 재생성 직후 인터넷이 통하더라도 **어느 NAT EIP로 나가는지** 반드시 비교합니다. Failover가 이미 발생했다면 새 인스턴스가 정상화되어도 수동 Failback이 필요합니다.

## 8. Lambda Errors → CloudWatch → SNS

**목적:** 라우팅 변경 전에 의도적인 Python 오류를 발생시켜 알림 경로를 확인합니다.

Lambda 콘솔 → `coldguard-prod-nat-failover` → 테스트 → 동기 호출에 다음 이벤트를 입력합니다.

```json
{
  "source": "aws.cloudwatch",
  "detail-type": "CloudWatch Alarm State Change",
  "detail": {
    "alarmName": "coldguard-prod-nat-a-failover-alarm",
    "state": "INVALID_TEST_STATE"
  }
}
```

이벤트의 `state`가 문자열이므로 현재 `failover.py`의 `.get()` 호출에서 `AttributeError`가 발생합니다. 이 오류는 `replace_route` 이전에 발생하므로 라우팅 변경이 수행되지 않습니다.

**실제 결과:** 오류 `AttributeError: 'str' object has no attribute 'get'` 기록, CloudWatch `coldguard-prod-lambda-errors` ALARM, SNS `coldguard-prod-failover-alert` 구독 이메일 수신. 이후 오류가 중단되어 알람이 자동으로 OK 복귀.

## 9. Lambda 비동기 실패 → SQS OnFailure Destination

위 JSON을 Lambda 콘솔에서 **비동기 호출**로 실행한 뒤 SQS `coldguard-prod-failover-dlq`에서 메시지를 폴링합니다. 비동기 호출 접수 성공은 함수 실행 성공과 다릅니다.

**실제 수신 결과 핵심 필드:**

```json
{
  "requestContext": {
    "condition": "RetriesExhausted",
    "approximateInvokeCount": 3
  },
  "responseContext": {
    "functionError": "Unhandled"
  },
  "responsePayload": {
    "errorType": "AttributeError",
    "errorMessage": "'str' object has no attribute 'get'"
  }
}
```

최초 호출 + 재시도 2회가 모두 실패하여 SQS에 실행 실패 기록이 저장된 것을 확인했습니다. 이 구성은 Lambda 비동기 `OnFailure Destination`이며 EventBridge 전달 실패 DLQ와 구분됩니다.

## 10. Lambda Throttles → CloudWatch → SNS

**목적:** 동시 실행 제한으로 Lambda가 거부되는 상황의 경보 및 이메일 수신 확인.

**주의:** 예약 동시성을 0으로 설정한 동안에는 NAT 장애 시 자동 Failover Lambda 호출이 차단될 수 있습니다. 반드시 테스트 후 1로 복구하세요.

```bash
# 기존 값 확인 (1)
aws lambda get-function-concurrency \
  --region ap-northeast-2 \
  --function-name coldguard-prod-nat-failover

# 테스트 중에만 0 설정
aws lambda put-function-concurrency \
  --region ap-northeast-2 \
  --function-name coldguard-prod-nat-failover \
  --reserved-concurrent-executions 0

# 동기 호출 → TooManyRequestsException 예상
aws lambda invoke \
  --region ap-northeast-2 \
  --function-name coldguard-prod-nat-failover \
  --invocation-type RequestResponse \
  --payload '{"source":"throttle-test"}' \
  --cli-binary-format raw-in-base64-out \
  throttle-result.json

# 반드시 즉시 복구
aws lambda put-function-concurrency \
  --region ap-northeast-2 \
  --function-name coldguard-prod-nat-failover \
  --reserved-concurrent-executions 1
```

**실제 결과:** `Throttles` 지표 합계 3회, `coldguard-prod-lambda-throttles` ALARM, SNS 이메일 수신, 예약 동시성 1 복구 확인.

## 11. EventBridge 대상 전달 실패 → 테스트용 SQS DLQ

**목적:** 기존 운영용 EventBridge Rule 및 Lambda 권한을 수정하지 않고 EventBridge의 대상 전달 실패 시 SQS 보관 동작 확인.

사용 리소스:
- 임시 EventBridge 규칙 `coldguard-eventbridge-dlq-test-rule`
- 임시 SQS `coldguard-eventbridge-dlq-test`
- 대상: 기존 Lambda `coldguard-prod-nat-failover` (운영 Rule만 호출 허용됨)
- DLQ SQS Queue Policy: `events.amazonaws.com`의 `sqs:SendMessage`, 테스트 Rule ARN으로 제한
- Retry Policy: `MaximumRetryAttempts=2`, `MaximumEventAgeInSeconds=3600`

### 임시 Rule 생성

```bash
aws events put-rule \
  --region ap-northeast-2 \
  --name coldguard-eventbridge-dlq-test-rule \
  --event-bus-name default \
  --state ENABLED \
  --event-pattern '{"source":["coldguard.dlq-test"],"detail-type":["DLQ Test"]}'
```

### DLQ 정책 및 대상

테스트 SQS Queue Policy는 EventBridge 서비스가 이 테스트 규칙의 ARN에서 발행한 메시지만 쓰도록 구성합니다. 실제 검증에서는 아래 ARN을 사용했습니다.

```text
Rule:  arn:aws:events:ap-northeast-2:<ACCOUNT_ID>:rule/coldguard-eventbridge-dlq-test-rule
Queue: arn:aws:sqs:ap-northeast-2:<ACCOUNT_ID>:coldguard-eventbridge-dlq-test
```

대상 JSON (`eventbridge-dlq-target.json`):

```json
[
  {
    "Id": "DLQTestLambda",
    "Arn": "arn:aws:lambda:ap-northeast-2:<ACCOUNT_ID>:function:...",
    "RetryPolicy": {
      "MaximumRetryAttempts": 2,
      "MaximumEventAgeInSeconds": 3600
    },
    "DeadLetterConfig": {
      "Arn": "arn:aws:sqs:ap-northeast-2:<ACCOUNT_ID>:coldguard-eventbridge-dlq-test"
    }
  }
]
```

```bash
aws events put-targets \
  --region ap-northeast-2 \
  --rule coldguard-eventbridge-dlq-test-rule \
  --targets file://eventbridge-dlq-target.json
```

등록 확인: `FailedEntryCount=0`.

### 이벤트 발행

```bash
aws events put-events \
  --region ap-northeast-2 \
  --entries '[{"Source":"coldguard.dlq-test","DetailType":"DLQ Test","Detail":"{\"test\":\"eventbridge-dlq\"}","EventBusName":"default"}]'
```

**실제 결과:** 발행 결과 `FailedEntryCount=0`, `EventId=8dbfbb9e-d432-4725-a87f-3904f0c0e939`. 테스트용 SQS에서 동일 ID의 다음 이벤트 본문 수신:

```json
{
  "version": "0",
  "id": "8dbfbb9e-d432-4725-a87f-3904f0c0e939",
  "detail-type": "DLQ Test",
  "source": "coldguard.dlq-test",
  "region": "ap-northeast-2",
  "detail": {"test": "eventbridge-dlq"}
}
```

**판정:** EventBridge 테스트용 DLQ에 이벤트 도착 확인. 단, SQS **메시지 속성**(`ERROR_CODE`, `ERROR_MESSAGE`, `RULE_ARN`, `TARGET_ARN`) 내용은 아직 제공받지 못해 정확한 실패 사유를 문서상 확정하지 않았습니다. 또한 이 시험은 운영용 DLQ(`coldguard-prod-eventbridge-dlq`)의 실제 권한과 연동까지 직접 검증하지는 않습니다.

### 임시 테스트 리소스 정리

먼저 SQS 메시지의 `Message attributes`를 캡처·기록한 뒤 정리합니다. Git Bash에서:

```bash
# 1. 테스트 규칙의 Lambda 대상 제거
aws events remove-targets \
  --region ap-northeast-2 \
  --rule coldguard-eventbridge-dlq-test-rule \
  --ids DLQTestLambda

# 2. 테스트 규칙 삭제
aws events delete-rule \
  --region ap-northeast-2 \
  --name coldguard-eventbridge-dlq-test-rule

# 3. 테스트 전용 SQS 삭제 (메시지도 함께 삭제됨)
aws sqs delete-queue \
  --region ap-northeast-2 \
  --queue-url https://sqs.ap-northeast-2.amazonaws.com/<ACCOUNT_ID>/coldguard-eventbridge-dlq-test

# 4. Git Bash 테스트 임시 파일 정리 (Terraform 프로젝트 경로에서 실행)
rm -f eventbridge-dlq-policy.json eventbridge-dlq-attributes.json eventbridge-dlq-target.json throttle-result.json
```

**운영용** `coldguard-prod-nat-failover-rule`, `coldguard-prod-eventbridge-dlq`, `coldguard-prod-failover-dlq` 및 Lambda는 삭제하지 않습니다.

## 12. 검증 후 운영 점검

```bash
# Lambda 예약 동시성 최종 확인
aws lambda get-function-concurrency \
  --region ap-northeast-2 \
  --function-name coldguard-prod-nat-failover

# NAT 및 Lambda 경보 현황
aws cloudwatch describe-alarms \
  --region ap-northeast-2 \
  --alarm-names \
    coldguard-prod-nat-a-failover-alarm \
    coldguard-prod-nat-c-failover-alarm \
    coldguard-prod-lambda-errors \
    coldguard-prod-lambda-throttles \
  --query "MetricAlarms[].{Name:AlarmName,State:StateValue}" \
  --output table

# Terraform 계획에 원치 않는 변경이 없는지 확인
terraform plan
```

검증 완료 시 기대값: NAT-A/C ASG 각 1대, Private RT-A/C가 각자의 NAT ENI로 원복, 예약 동시성 1, 신규 오류가 없으면 알람 OK. Lambda 알람은 데이터 수집·평가가 끝나야 OK로 돌아올 수 있습니다.

## 13. 한계 및 향후 과제

1. **RTO는 아직 측정하지 않았습니다.** 장애 유도 시각부터 Private EC2의 외부 통신 재개까지 반복 측정이 필요합니다.
2. ASG `GroupInServiceInstances` 경보는 **인스턴스 수 기반**입니다. iptables 장애, NAT 서비스 장애, OS 이상 등 EC2가 InService인 상태의 통신 장애는 놓칠 수 있습니다.
3. ASG가 빠르게 인스턴스를 교체하면 `InService=0`인 구간이 CloudWatch 메트릭에서 관측되지 않을 수 있습니다.
4. 백업 NAT의 ENI 부착 및 EC2 상태 검사는 실제 외부 통신 성공까지 보장하지 않습니다.
5. Lambda 이벤트 현재성 확인은 모든 중복·경합·수동 Failback 직후 뒤늦은 이벤트를 완벽히 해결하는 것은 아닙니다. 운영 전 이벤트 순서와 경로 상태 보호를 추가 검토합니다.
6. EventBridge 테스트용 DLQ의 메시지 속성 확인 및 **운영용 DLQ 연결 자체에 대한 별도 검증**이 추가되면 더 완전한 검증이 됩니다.
7. 콘솔에서 생성한 테스트 리소스는 Terraform State에 없을 수 있습니다. 파괴/재배포 전에 잔여 리소스를 확인하세요.

---

**검증 결론:** ColdGuard의 양방향 NAT 자동 Failover 및 수동 Failback, ASG 교체 후 NAT 기능, Lambda 오류 및 제한 알림, Lambda 비동기 실패 보관, EventBridge 테스트 DLQ 메시지 수신이 확인됐습니다. 정확한 RTO 및 추가 운영 장애 시나리오는 후속 과제입니다.
