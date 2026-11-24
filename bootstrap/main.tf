
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

  # 알림 링크에 쓰는 Argo CD 주소. tailnet 이름이 들어가므로 저장소에 두지 않고 tfvars로 받습니다.
  set = var.argocd_url == "" ? [] : [
    {
      name  = "notifications.argocdUrl"
      value = var.argocd_url
    }
  ]
}

# ==========================================
# Tailscale Kubernetes Operator
# ==========================================
# 설치 전에 tailscale 네임스페이스와 operator-oauth Secret을 kubectl로 만들어야 합니다.
# Secret이 없으면 operator Pod가 뜨지 않으므로, 준비되기 전까지는 tailscale_operator_enabled를 false로 둡니다.
resource "helm_release" "tailscale_operator" {
  count = var.tailscale_operator_enabled ? 1 : 0

  name       = "tailscale-operator"
  repository = "https://pkgs.tailscale.com/helmcharts"
  chart      = "tailscale-operator"

  version = var.tailscale_operator_chart_version

  namespace        = "tailscale"
  create_namespace = true

  wait    = true
  atomic  = true
  timeout = 600

  values = [
    file("${path.module}/values/tailscale-operator.yaml")
  ]
}

# ==========================================
# 루트 Application (app-of-apps)
# ==========================================
# coldguard-gitops의 argocd/ 폴더를 바라봅니다. 폴더가 main에 올라가기 전에는 동기화 오류가 나므로
# gitops_root_app_enabled를 false로 두었다가, 폴더가 머지된 뒤 true로 바꿉니다.
resource "helm_release" "root_app" {
  count = var.gitops_root_app_enabled ? 1 : 0

  name      = "coldguard-root-app"
  chart     = "${path.module}/charts/root-app"
  namespace = "argocd"

  values = [
    yamlencode({
      repoURL        = var.gitops_repo_url
      targetRevision = var.gitops_target_revision
      path           = "argocd"
    })
  ]

  depends_on = [helm_release.argocd]
}
