# AWS Provider
provider "aws" {
  region = var.aws_region
}

# 기존 EKS Cluster 정보 조회
data "aws_eks_cluster" "main" {
  name = var.eks_cluster_name
}

# Kubernetes Provider
provider "kubernetes" {
  host = data.aws_eks_cluster.main.endpoint

  cluster_ca_certificate = base64decode(
    data.aws_eks_cluster.main.certificate_authority[0].data
  )

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"

    args = [
      "eks",
      "get-token",
      "--region",
      var.aws_region,
      "--cluster-name",
      var.eks_cluster_name
    ]
  }
}

# Helm Provider 3.x
provider "helm" {
  kubernetes = {
    host = data.aws_eks_cluster.main.endpoint

    cluster_ca_certificate = base64decode(
      data.aws_eks_cluster.main.certificate_authority[0].data
    )

    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"

      args = [
        "eks",
        "get-token",
        "--region",
        var.aws_region,
        "--cluster-name",
        var.eks_cluster_name
      ]
    }
  }
}
