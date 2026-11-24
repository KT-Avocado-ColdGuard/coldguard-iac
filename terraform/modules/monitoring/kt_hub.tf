# KT 허브 상태 알람
#
# 서브넷 라우터가 1분마다 KT 허브의 각 구성 요소 상태 확인 주소를 호출하고,
# 성공하면 1, 실패하면 0을 ProbeSuccess 지표로 올립니다.
# 라우터나 KT 허브가 통째로 죽어 지표가 끊겨도 알람이 울리도록 누락 데이터를 장애로 봅니다.
resource "aws_cloudwatch_metric_alarm" "kt_hub" {
  for_each = var.kt_hub_components

  alarm_name        = "${var.name}-${var.environment}-kt-hub-${each.key}-down"
  alarm_description = "KT 허브 ${each.key} 상태 확인이 3분 연속 실패했습니다."

  namespace   = var.kt_hub_probe_namespace
  metric_name = "ProbeSuccess"

  dimensions = {
    Component = each.key
  }

  statistic = "Minimum"
  period    = 60

  comparison_operator = "LessThanThreshold"
  threshold           = 1

  evaluation_periods  = 3
  datapoints_to_alarm = 3

  treat_missing_data = "breaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "${var.name}-${var.environment}-kt-hub-${each.key}-down"
  }
}
