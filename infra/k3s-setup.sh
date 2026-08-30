#!/usr/bin/env bash
# Legacy manual fallback — k3s 설치 + ArgoCD + secret-zero + root app
# 일반 재구축은 checksum·idempotency·preflight가 있는 ansible/playbooks/bootstrap.yml을 쓴다.
# 검증: kubectl describe node에서 Allocatable ≈ 28Gi / 7 vCPU (8코어·32GB 노드 기준)
#   capacity 31.3Gi − system-reserved 2Gi − eviction-hard 1Gi ≈ 28.3Gi
set -euo pipefail

# 재구축 재현성 — 두 버전 모두 고정. 올릴 땐 여기 두 줄만 바꾼다
K3S_VERSION="${K3S_VERSION:-v1.36.3+k3s1}"
ARGOCD_VERSION="${ARGOCD_VERSION:-v3.5.0}"

# k3s 설치 — system-reserved로 호스트 몫(OS+k3s ~2GB/1vCPU) 확보 (계획 §4-1)
# eviction-hard 는 반드시 인용부호로 감쌀 것 — `<` 가 셸 리다이렉션으로 먹혀서 설치가 죽는다
# 관리자 kubeconfig에는 cluster-admin 자격증명이 있으므로 노드의 root만 읽는다.
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${K3S_VERSION}" sh -s - \
  --write-kubeconfig-mode=600 \
  --secrets-encryption \
  --kubelet-arg=system-reserved=cpu=1000m,memory=2Gi \
  --kubelet-arg='eviction-hard=memory.available<1Gi'

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# 설치 직후엔 노드 오브젝트가 아직 없어서 wait 가 "no matching resources found" 로 즉시 실패한다
for _ in $(seq 1 60); do
  kubectl get node >/dev/null 2>&1 && break
  sleep 2
done
kubectl wait --for=condition=Ready node --all --timeout=180s

# ArgoCD 설치 (네임스페이스·PriorityClass는 GitOps가 만들므로 여기선 argocd만)
# TODO(Phase 7): 리소스 limit 조정(계획 §4-2: 전체 1.5Gi 내) + UI 서브도메인/Cloudflare Access
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -

# --server-side 필수 — client-side apply 는 applicationsets CRD 의
# last-applied-configuration 애노테이션이 262144 바이트 한도를 넘어 실패한다
kubectl apply -n argocd --server-side=true --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"

kubectl wait --for=condition=Available deployment/argocd-server -n argocd --timeout=420s
kubectl wait --for=condition=Available deployment/argocd-repo-server -n argocd --timeout=300s

# 첫 root sync부터 wave가 자식 Application·ESO의 실제 health를 기다려야 한다.
# 이후에는 cluster Application이 같은 ConfigMap을 GitOps로 계속 관리한다.
kubectl apply --server-side --field-manager=tapple-bootstrap \
  -f "$(dirname "$0")/../manifests/cluster/argocd-health.yaml"

# 이 레포가 public 인 동안은 자격증명이 필요 없다.
# private 로 되돌리면 root app apply 전에 deploy key 를 ArgoCD 에 등록해야 한다.

# Secrets Manager 역할을 AssumeRole하기 위한 유일한 secret-zero. root app보다 먼저 있어야 ESO가 기동한다.
"$(dirname "$0")/../scripts/bootstrap-external-secrets-aws.sh"

# root app — 이후 전부 GitOps
kubectl apply -n argocd -f "$(dirname "$0")/../bootstrap/root-app.yaml"

cat <<'MSG'

k3s + ArgoCD 준비 완료.

초기 admin 비밀번호:
  kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d

UI (도메인 붙기 전) — 맥에서:
  ssh -L 8080:localhost:8080 root@<노드IP> 'kubectl port-forward -n argocd svc/argocd-server 8080:443'
  → https://localhost:8080

Secrets Manager JSON Secret이 모두 준비되기 전에는 ExternalSecret이 Ready가 아니고,
해당 Secret을 쓰는 파드는 CreateContainerConfigError가 정상이다 (secrets/README.md).

상태 확인:
  kubectl get secretstore,externalsecret -A
MSG
