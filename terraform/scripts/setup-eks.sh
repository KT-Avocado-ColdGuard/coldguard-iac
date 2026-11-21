#!/usr/bin/env bash
set -euo pipefail

# ==========================================
# ColdGuard EKS Initial Setup
# ==========================================

# Terraform 프로젝트 루트로 이동
cd "$(dirname "$0")/.."

echo "================================"
echo " ColdGuard EKS Initial Setup"
echo "================================"

# 1. Terraform Output에서 클러스터 이름과 리전 가져오기
CLUSTER_NAME=$(terraform output -raw eks_cluster_name)
REGION=$(terraform output -raw aws_region)

# 2. 현재 AWS 인증 계정 확인
echo "[1/6] AWS 리전 및 인증 계정 확인"
echo "Region: $REGION"
aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output table

echo "[2/6] EKS kubeconfig 설정"

aws eks update-kubeconfig \
  --region "$REGION" \
  --name "$CLUSTER_NAME"

echo "[3/6] Worker Node 준비 확인"

kubectl wait \
  --for=condition=Ready \
  nodes --all \
  --timeout=300s

echo "[4/6] EBS CSI Driver 준비 확인"

kubectl rollout status \
  deployment/ebs-csi-controller \
  -n kube-system \
  --timeout=300s

echo "[5/6] gp3 StorageClass 적용"

kubectl apply \
  -f kubernetes/storageclass-gp3.yaml

echo "[6/6] 결과 확인"

kubectl get storageclass gp3

echo "================================"
echo " ColdGuard EKS Setup Complete"
echo "================================"
