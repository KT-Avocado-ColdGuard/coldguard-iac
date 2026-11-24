
# ==========================================
# gp3 StorageClass
# ==========================================
resource "kubernetes_storage_class_v1" "gp3" {
  metadata {
    name = "gp3"
  }

  storage_provisioner = "ebs.csi.aws.com"

  parameters = {
    type = "gp3"
  }

  reclaim_policy         = "Delete"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true
}

# ==========================================
# Argo CD 3.6.1
# Helm Chart: 10.15.0
# ==========================================
resource "helm_release" "argocd" {
  name       = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"

  version = var.argocd_chart_version

  namespace        = "argocd"
  create_namespace = true

  wait    = true
  atomic  = true
  timeout = 900

  # 설정은 values/argocd.yaml에서 관리합니다.
  values = [
    file("${path.module}/values/argocd.yaml")
  ]
}
