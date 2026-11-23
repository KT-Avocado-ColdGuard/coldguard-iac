# AWS 내부 알림 공용 SNS
# NAT 장애 전환, Failover Lambda 오류, KT 허브 상태 알람이 모두 이 토픽으로 갑니다.
# 애플리케이션 알림은 KT의 Alertmanager가 Slack·메일로 직접 보냅니다.
resource "aws_sns_topic" "alerts" {
  name = "${var.name}-${var.environment}-alerts"

  tags = {
    Name = "${var.name}-${var.environment}-alerts"
  }
}

# 이메일 구독
# 생성 후 받은 메일에서 "Confirm subscription"을 눌러야 알림이 옵니다.
resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
