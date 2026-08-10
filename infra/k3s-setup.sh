#!/usr/bin/env bash
# Phase 2 — k3s 설치 + ArgoCD + root app
# 검증: kubectl describe node에서 Allocatable ≈ 30Gi / 7 vCPU (8코어·32GB 노드 기준)
set -euo pipefail

# k3s 설치 — system-reserved로 호스트 몫(OS+k3s ~2GB/1vCPU) 확보 (계획 §4-1)
# TODO(Phase 2): INSTALL_K3S_VERSION 고정 — 재구축 시 같은 버전이 깔려야 재현성 보장
curl -sfL https://get.k3s.io | sh -s - \
  --write-kubeconfig-mode=644 \
  --kubelet-arg=system-reserved=cpu=1000m,memory=2Gi \
  --kubelet-arg=eviction-hard=memory.available<1Gi

kubectl wait --for=condition=Ready node --all --timeout=120s

# ArgoCD 설치 (네임스페이스·PriorityClass는 GitOps가 만들므로 여기선 argocd만)
# TODO(Phase 7): 버전 고정 + 리소스 limit 조정(계획 §4-2: 전체 1.5Gi 내) + UI 서브도메인/Cloudflare Access
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl wait --for=condition=Available deployment/argocd-server -n argocd --timeout=300s

# private 레포 접근 자격증명 등록 (root app apply 전 필수)
# TODO(Phase 7): deploy key 발급 후 argocd CLI 또는 repo secret으로 등록

# root app — 이후 전부 GitOps
kubectl apply -n argocd -f "$(dirname "$0")/../bootstrap/root-app.yaml"

echo "k3s + ArgoCD 준비 완료. 초기 비밀번호:"
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d && echo
