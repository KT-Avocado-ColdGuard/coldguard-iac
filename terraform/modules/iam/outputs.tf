output "nat_instance_profile_name" {
  description = "NAT EC2 IAM Instance Profile name"
  value       = aws_iam_instance_profile.nat.name
}

output "router_instance_profile_name" {
  description = "Router EC2 IAM Instance Profile name"
  value       = aws_iam_instance_profile.router.name
}

output "failover_lambda_role_arn" {
  description = "Failover Lambda IAM Role ARN"

  value = aws_iam_role.failover.arn

  depends_on = [
    aws_iam_role_policy_attachment.failover_logs,
    aws_iam_role_policy.failover
  ]
}


# EKS IAM Role Outputs
output "eks_cluster_role_arn" {
  description = "IAM Role ARN for EKS Cluster"
  value       = aws_iam_role.eks_cluster.arn

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster
  ]
}

output "eks_node_role_arn" {
  description = "IAM Role ARN for EKS Worker Nodes"
  value       = aws_iam_role.eks_node.arn

  depends_on = [
    aws_iam_role_policy_attachment.eks_worker,
    aws_iam_role_policy_attachment.eks_ecr,
    aws_iam_role_policy_attachment.eks_cni
  ]
}

output "eks_cluster_role_policy_attachment_id" {
  value = aws_iam_role_policy_attachment.eks_cluster.id
}

output "eks_node_role_policy_attachment_ids" {
  value = [
    aws_iam_role_policy_attachment.eks_worker.id,
    aws_iam_role_policy_attachment.eks_ecr.id,
    aws_iam_role_policy_attachment.eks_cni.id
  ]
}

# EKS EBS CSI IAM Output
output "eks_ebs_csi_role_arn" {
  description = "IAM Role ARN for EKS EBS CSI Driver"

  value = aws_iam_role.eks_ebs_csi.arn

  depends_on = [
    aws_iam_role_policy_attachment.eks_ebs_csi
  ]
}

# GitHub Actions Role ARN
output "github_actions_role_arn" {
  description = "IAM Role ARN for GitHub Actions"

  value = aws_iam_role.github_actions.arn

  depends_on = [
    aws_iam_role_policy.github_actions_ecr
  ]
}