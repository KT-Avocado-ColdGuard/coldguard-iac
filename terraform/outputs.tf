# Root outputs will be added when module outputs are defined.

# EKS Cluster
output "eks_cluster_name" {
  description = "EKS Cluster Name"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS Cluster API Endpoint"
  value       = module.eks.cluster_endpoint
}

# EKS Managed Node Group
output "eks_node_group_name" {
  description = "EKS Managed Node Group Name"
  value       = module.eks.node_group_name
}

# ECR Repository
output "ecr_repository_urls" {
  description = "ECR Repository URLs"
  value       = module.ecr.repository_urls
}