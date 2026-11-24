# NAT ASG 장애 감지 CloudWatch Alarm
resource "aws_cloudwatch_metric_alarm" "nat" {
  for_each = var.nat_asg_names

  alarm_name = "${var.name}-${var.environment}-${replace(each.key, "_", "-")}-failover-alarm"

  alarm_description = "NAT Auto Scaling Group has no InService instances"

  namespace   = "AWS/AutoScaling"
  metric_name = "GroupInServiceInstances"

  dimensions = {
    AutoScalingGroupName = each.value
  }

  statistic = "Minimum"
  period    = 60

  comparison_operator = "LessThanThreshold"
  threshold           = 1

  evaluation_periods  = 1
  datapoints_to_alarm = 1

  treat_missing_data = "missing"

  # 장애 전환이 일어났을 때와 NAT가 복구되었을 때 모두 알립니다.
  # 복구 알림을 받으면 담당자가 수동 Failback을 진행합니다.
  alarm_actions = [var.alert_topic_arn]
  ok_actions    = [var.alert_topic_arn]

  tags = {
    Name = "${var.name}-${var.environment}-${replace(each.key, "_", "-")}-failover-alarm"
  }
}
