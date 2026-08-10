#!/usr/bin/env bash
# 팀원용 kubeconfig 발급 — 노드에서 실행 (docs/db-access.md)
#
#   ./scripts/gen-team-kubeconfig.sh <노드IP> [유효기간] > 팀원이름-kubeconfig.yaml
#
# 노드의 /etc/rancher/k3s/k3s.yaml 을 그대로 주면 cluster-admin 이 넘어간다.
# 이 스크립트는 teammate ServiceAccount(manifests/cluster/team-access.yaml)의 토큰만 담아,
# dev·prod DB 로의 port-forward 외에는 아무것도 못 하는 kubeconfig 를 만든다.
set -euo pipefail

NODE_IP="${1:?사용법: $0 <노드IP> [유효기간(예: 8760h)]}"
TTL="${2:-2160h}" # 기본 90일. 길게 주고 싶으면 인자로 (API 서버 상한에 걸리면 잘린다)

export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
SA_NS=team-access
SA_NAME=teammate

kubectl get serviceaccount "$SA_NAME" -n "$SA_NS" >/dev/null 2>&1 || {
  echo "ServiceAccount ${SA_NS}/${SA_NAME} 가 없다 — manifests/cluster/team-access.yaml 이 sync 됐는지 확인" >&2
  exit 1
}

TOKEN=$(kubectl create token "$SA_NAME" -n "$SA_NS" --duration="$TTL")
CA=$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

cat <<YAML
# tapple k3s — 팀원용 (dev·prod DB port-forward 전용)
# 유효기간 ${TTL}. 만료되면 운영자에게 재발급 요청.
#   사용: export KUBECONFIG=\$PWD/이파일.yaml
apiVersion: v1
kind: Config
clusters:
  - name: tapple
    cluster:
      server: https://${NODE_IP}:6443
      certificate-authority-data: ${CA}
users:
  - name: teammate
    user:
      token: ${TOKEN}
contexts:
  - name: tapple
    context:
      cluster: tapple
      user: teammate
      namespace: dev-db
current-context: tapple
YAML
