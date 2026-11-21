
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2 = boto3.client("ec2")
cloudwatch = boto3.client("cloudwatch")

# Terraform에서 전달받은 알람별 RT 및 백업 ENI 정보
ROUTES = json.loads(os.environ["ROUTES"])


def parse_timestamp(value):
    """AWS 이벤트의 시각을 UTC datetime으로 변환"""
    if not value:
        raise ValueError("Event timestamp is missing")

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).astimezone(timezone.utc)


def alarm_is_current(alarm_name, event_timestamp):
    """현재 알람 상태와 이벤트의 유효성 확인"""

    response = cloudwatch.describe_alarms(
        AlarmNames=[alarm_name]
    )

    alarms = response.get("MetricAlarms", [])

    if len(alarms) != 1:
        raise RuntimeError(
            f"CloudWatch alarm not found: {alarm_name}"
        )

    alarm = alarms[0]

    # 이미 복구된 알람이라면 변경하지 않음
    if alarm["StateValue"] != "ALARM":
        logger.info(
            "Alarm is no longer ALARM: %s",
            alarm_name
        )
        return False

    # 이벤트 이후 알람 상태가 다시 바뀐 적이 있다면
    # 이전 장애 이벤트는 무시
    current_transition = alarm.get(
        "StateTransitionedTimestamp"
    )

    if current_transition is None:
        raise RuntimeError(
            "Alarm transition timestamp is unavailable"
        )

    event_time = parse_timestamp(event_timestamp)

    if current_transition > event_time+ timedelta(seconds=2):
        logger.info(
            "Outdated alarm event ignored: %s",
            alarm_name
        )
        return False

    return True


def backup_nat_is_healthy(eni_id):
    """백업 NAT의 ENI 연결 및 EC2 기본 상태 확인"""

    response = ec2.describe_network_interfaces(
        NetworkInterfaceIds=[eni_id]
    )

    eni = response["NetworkInterfaces"][0]
    attachment = eni.get("Attachment", {})

    if eni["Status"] != "in-use":
        return False

    if attachment.get("Status") != "attached":
        return False

    instance_id = attachment.get("InstanceId")

    if not instance_id:
        return False

    response = ec2.describe_instance_status(
        InstanceIds=[instance_id],
        IncludeAllInstances=True
    )

    statuses = response.get("InstanceStatuses", [])

    if not statuses:
        return False

    status = statuses[0]

    return (
        status["InstanceState"]["Name"] == "running"
        and status["InstanceStatus"]["Status"] == "ok"
        and status["SystemStatus"]["Status"] == "ok"
    )


def lambda_handler(event, context):

    # 1. CloudWatch Alarm 이벤트인지 확인
    if (
        event.get("source") != "aws.cloudwatch"
        or event.get("detail-type")
        != "CloudWatch Alarm State Change"
    ):
        return {"status": "ignored", "reason": "invalid_event"}

    detail = event.get("detail", {})
    alarm_name = detail.get("alarmName")
    state = detail.get("state", {})

    # 2. ALARM 이벤트만 처리
    if state.get("value") != "ALARM":
        return {"status": "ignored", "reason": "not_alarm"}

    # 3. 등록된 NAT 알람인지 확인
    if alarm_name not in ROUTES:
        return {"status": "ignored", "reason": "unknown_alarm"}

    # 4. 현재도 유효한 장애 이벤트인지 확인
    if not alarm_is_current(
        alarm_name,
        state.get("timestamp")
    ):
        return {"status": "ignored", "reason": "stale_alarm"}

    # 5. 변경 대상 정보 가져오기
    config = ROUTES[alarm_name]

    route_table_id = config["route_table_id"]
    backup_eni_id = config["backup_eni"]

    # 6. 백업 NAT 기본 상태 확인
    if not backup_nat_is_healthy(backup_eni_id):
        logger.error(
            "Backup NAT is not healthy: %s",
            backup_eni_id
        )
        raise RuntimeError(
            f"Backup NAT unavailable: {backup_eni_id}"
        )

    # 7. Private Route Table 경로 변경
    ec2.replace_route(
        RouteTableId=route_table_id,
        DestinationCidrBlock="0.0.0.0/0",
        NetworkInterfaceId=backup_eni_id
    )

    logger.info(
        "NAT Failover completed: %s, RT=%s, ENI=%s",
        alarm_name,
        route_table_id,
        backup_eni_id
    )

    return {
        "status": "failover_completed",
        "alarm": alarm_name,
        "route_table_id": route_table_id,
        "backup_eni": backup_eni_id
    }
