# 다이어그램 재생성

다이어그램은 수동 산출물이다.
KubeDiagrams 그림은 live cluster snapshot이다.
mingrammer 그림은 GitHub, AWS, 운영 경계를 포함한 desired state다.
두 종류를 한 그림으로 섞지 않는다.

현재 commit된 live snapshot은 없다.
2026-08-12 pre-ESO test snapshot은 현재 desired state와 달라 삭제했다.
실제 IDC 배포와 health gate가 끝난 뒤 아래 명령으로 새 snapshot을 만든다.
root README는 live snapshot을 canonical 설명으로 사용하지 않는다.

## 산출물

| 파일 | 원본 | 의미 |
|---|---|---|
| `architecture-app` | live cluster | app과 DB resource inventory |
| `architecture-platform` | live cluster | monitoring resource inventory |
| `cicd-flow` | `cicd_flow.py` | tag+digest PR과 Argo pull |
| `branch-flow` | `branch_flow.py` | dev, prod 승격과 rollback |
| `gitops-tree` | `gitops_tree.py` | AppProject와 sync wave health gate |
| `preview-env` | `preview_env.py` | trusted PR과 PostDelete cleanup |
| `secret-supply-chain` | `secret_supply_chain.py` | 16 source와 20 ExternalSecret |
| `traffic-flow` | `traffic_flow.py` | ingress, DB, OTel, S3, Grafana 경로 |

## 도구 설치

```bash
brew install graphviz
cd docs/diagrams
uv venv --python 3.12
export CFLAGS="-I$(brew --prefix graphviz)/include"
export LDFLAGS="-L$(brew --prefix graphviz)/lib"
uv pip install --python .venv/bin/python \
  "KubeDiagrams==0.8.0" "diagrams==0.25.1"
```

Python 3.12를 사용한다.
`--python .venv/bin/python`을 생략하지 않는다.

## live snapshot

infra 관리자는 IDC 노드의 root-only kubeconfig를 복사하지 않는다.
SSH와 `sudo -n k3s kubectl`로 값 없는 resource YAML만 가져온다.

```bash
mkdir -p .snapshot out
IDC_NODE_HOST="${IDC_NODE_HOST:?IDC node host를 설정하세요}"
IDC_SSH_USER="${IDC_SSH_USER:?infra SSH user를 설정하세요}"

for ns in app db dev-app dev-db preview; do
  ssh "$IDC_SSH_USER@$IDC_NODE_HOST" \
    "sudo -n k3s kubectl get deployment,statefulset,service,ingress,pvc,cronjob,job -n $ns -o yaml" \
    > ".snapshot/10-$ns.yaml"
done
for ns in monitoring argocd external-secrets kube-system; do
  ssh "$IDC_SSH_USER@$IDC_NODE_HOST" \
    "sudo -n k3s kubectl get deployment,statefulset,daemonset,service,pvc -n $ns -o yaml" \
    > ".snapshot/20-$ns.yaml"
done

.venv/bin/kube-diagrams -c kube-diagrams.yaml \
  -o out/architecture-app -f png .snapshot/10-*.yaml
.venv/bin/kube-diagrams -c kube-diagrams.yaml \
  -o out/architecture-platform -f png .snapshot/20-monitoring.yaml
```

Secret resource와 Pod environment는 snapshot에 넣지 않는다.
`kubectl get all`은 ReplicaSet과 EndpointSlice까지 넣어 그림을 흐린다.
Namespace object를 넣으면 namespace가 중복 렌더될 수 있다.
dashboard ConfigMap은 정보보다 box 수만 늘리므로 제외한다.

재생성 PR에 capture time, Git commit, k3s version, host 식별자, namespace 목록을 기록한다.
image tag나 Secret version만 바뀌고 topology가 같으면 다시 만들지 않는다.
IDC 전환 뒤 monitoring과 control plane snapshot을 별도 파일로 나눈다.

## desired-state flow

```bash
.venv/bin/python cicd_flow.py
.venv/bin/python branch_flow.py
.venv/bin/python traffic_flow.py
.venv/bin/python gitops_tree.py
.venv/bin/python preview_env.py
.venv/bin/python secret_supply_chain.py
```

각 script는 light와 dark PNG를 만든다.
`theme.py`가 공통 style을 가진다.

다음 점선은 아직 활성화되지 않은 gate다.

- 앱 Ingress는 실제 host와 TLS 뒤에만 생긴다.
- backup은 외부 restore 뒤 `suspend:false`로 바꿀 때만 예약 실행된다.
- 외부 uptime monitor는 IDC 밖에 따로 만들어야 한다.

preview 그림의 `preview` label은 trusted same-repository 검토를 끝냈다는 승인이다.
preview는 shared Secret과 shared DB role을 쓰므로 fork와 외부 코드를 실행하지 않는다.

## commit 대상

```text
out/*.png          commit
*.py, *.yaml       commit
.venv/, .snapshot/ ignore
```

flow script를 바꿨으면 PNG도 함께 재생성한다.
Graphviz 배경과 글자 색은 light/dark theme를 한 세트로 유지한다.
