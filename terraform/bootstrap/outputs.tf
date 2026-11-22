# 기존 EKS Cluster
output "eks_cluster_name" {
  description = "Target EKS Cluster"
  value       = var.eks_cluster_name
}

# gp3 StorageClass
output "gp3_storageclass_name" {
  description = "gp3 StorageClass Name"
  value       = kubernetes_storage_class_v1.gp3.metadata[0].name
}

# Argo CD Namespace
output "argocd_namespace" {
  description = "Argo CD Namespace"
  value       = helm_release.argocd.namespace
}

# Argo CD Helm Chart
output "argocd_chart_version" {
  description = "Argo CD Helm Chart Version"
  value       = var.argocd_chart_version
}
