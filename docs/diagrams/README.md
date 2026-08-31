# 다이어그램 재생성

자동화하지 않았다. 클러스터 구조는 몇 주에 한 번 바뀌므로 사람이 다시 뽑는 게 싸다. 대신 **절차를 여기 남겨** 누구든 5분에 재생성할 수 있게 한다.

그림은 두 종류다. 라이브 클러스터에서 뽑은 그림은 `LIVE SNAPSHOT`, 매니페스트와 운영
결정을 설명하는 흐름도는 `DESIRED STATE`다. 두 종류를 한 그림에서 섞지 않는다.

현재 `architecture-app`과 `architecture-platform`은 2026-08-12의 **ESO 전환 전 snapshot**이다.
실제 IDC 클러스터에 이 커밋을 배포하고 모든 Application·ExternalSecret이 Healthy가 되기 전에는
덮어쓰지 않는다. 반면 나머지 흐름도는 이 저장소가 의도하는 상태를 설명한다.

## 두 도구를 나눠 쓴다

| 산출물 | 도구 | 이유 |
|---|---|---|
| `architecture-app` · `architecture-platform` | **KubeDiagrams** | 클러스터의 실제 상태에서 **파생**시킨다. 손으로 그리면 반드시 낡는다 |
| `branch-flow` · `cicd-flow` · `traffic-flow` · `gitops-tree` · `preview-env` · `secret-supply-chain` | **mingrammer/diagrams** | 매니페스트 밖 GitHub·AWS 제어/데이터 흐름이 있다. 아래 참고 |

**mingrammer 로 그리는 것들이 왜 파생될 수 없나**

- `app → postgres` — `POSTGRES_URL` 환경변수 안의 접속 문자열이다. k8s 참조가 아니라 값이라 도구가 추론할 수 없다
- `app → otel-collector` — 같은 이유(`OTEL_URL`)
- `root-app → Application 14개 + ApplicationSet 1개` — ArgoCD Application 의 `directory.recurse: true` 한 줄에 숨어 있다
- `Ansible → secret-zero → STS → Secrets Manager → ESO → Kubernetes Secret` — 인증·신뢰·데이터 경계가 여러 시스템에 걸쳐 있다
- CI/CD 전체 — GitHub Actions·ghcr·infra 배포 브랜치·PR·required check는 클러스터 리소스가 아니다
- Cloudflare-only 443 UFW, 앱 Ingress enable gate, 외부 uptime monitor — host·DNS·운영 결정이라 k8s object만으로는 완전한 경로를 알 수 없다

두 그림은 대체 관계가 아니라 **축이 다르다.** KubeDiagrams 는 "무엇이 있는가"(인벤토리와 소유 관계), mingrammer 는 "누가 누구를 부르는가"(트래픽과 제어).

## 한 번만 하는 준비

```bash
brew install graphviz                    # 두 도구 모두 이걸로 렌더한다

cd docs/diagrams
uv venv --python 3.12                    # 3.14 는 diagrams 의존성 휠이 없을 수 있다
export CFLAGS="-I$(brew --prefix graphviz)/include"   # pygraphviz 컴파일용
export LDFLAGS="-L$(brew --prefix graphviz)/lib"
uv pip install --python .venv/bin/python "KubeDiagrams==0.8.0" "diagrams==0.25.1"
```

`--python .venv/bin/python` 을 빼면 안 된다. `CONDA_PREFIX` 가 설정된 환경에서는 uv 가 그 conda 환경을 대상으로 골라 엉뚱한 곳에 설치한다.

## 아키텍처 (KubeDiagrams)

라이브 클러스터에서 뽑는다. 레포 매니페스트로 뽑으면 upstream 차트로 오는 것들(grafana·loki·tempo·prometheus·argocd·traefik)이 Application 안에 URL 로만 있어서 **그림에서 빠진다.**

```bash
export KUBECONFIG=~/.kube/tapple-admin.yaml
mkdir -p .snapshot out

# kind 를 골라서 뽑는다. `get all` 은 ReplicaSet·EndpointSlice 까지 들어와 박스가 수십 개 늘어난다
for ns in app db dev-app dev-db; do
  kubectl get deployment,statefulset,service,ingress,pvc,cronjob -n $ns -o yaml > .snapshot/10-$ns.yaml
done
for ns in monitoring argocd external-secrets kube-system; do
  kubectl get deployment,statefulset,daemonset,service,pvc -n $ns -o yaml > .snapshot/20-$ns.yaml
done

.venv/bin/kube-diagrams -c kube-diagrams.yaml -o out/architecture-app      -f png .snapshot/10-*.yaml
.venv/bin/kube-diagrams -c kube-diagrams.yaml -o out/architecture-platform -f png .snapshot/20-monitoring.yaml
```

`architecture-platform`이라는 기존 파일명과 달리 현재 입력은 monitoring namespace뿐이다.
IDC 전환 뒤에는 `architecture-observability`(monitoring)와
`architecture-control-plane`(argocd·external-secrets·kube-system)으로 나눈다. 배포 전
desired state만으로 라이브 그림을 미리 만들지는 않는다.

재생성할 때 커밋 메시지나 PR 본문에 `capturedAt`, Git commit, k3s version,
`kubectl config current-context`, 포함 namespace를 기록한다. image tag나 시크릿 값만 바뀌면
토폴로지는 같으므로 다시 뽑지 않는다.

주의할 점 세 개.

- **네임스페이스 목록(`kubectl get ns`)을 입력에 넣지 마라.** 네임스페이스가 클러스터 박스와 별도 노드로 이중 렌더되어 떠 있는 육각형이 생긴다. 리소스만 넣으면 박스는 자동으로 만들어진다
- **`-f dot` 으로 뽑아 `dot` 으로 재렌더하지 마라.** 같은 이중 렌더 문제가 생긴다. 배경색을 바꾸려는 게 목적이었는데, 배경은 투명으로 둬도 된다 — 모든 글자가 불투명한 밝은 박스 안에 있어 다크 모드에서도 읽힌다
- `manifests/monitoring` 의 ConfigMap 9개(대시보드 JSON)는 위 kind 목록에 없어 자동으로 빠진다. 넣으면 박스만 9개 늘고 정보는 늘지 않는다

`kube-diagrams.yaml` 은 라벨 기반 클러스터 박스(`K8s Instance`·`Helm Chart` 등)를 줄이려고 둔 커스텀 설정이다. 현재 버전에서는 `recommended: false` 가 그 박스를 완전히 없애지는 못한다 — 중첩이 거슬리면 스냅샷에서 해당 라벨을 지워야 하지만, 그 라벨이 Service 셀렉터 매칭에도 쓰여 화살표가 사라질 수 있으니 주의.

## 흐름도 (mingrammer)

```bash
.venv/bin/python cicd_flow.py       # SHA image → infra PR → required CI → Argo pull
.venv/bin/python branch_flow.py     # 앱 브랜치 승격·trust-root gate·rollback
.venv/bin/python traffic_flow.py    # fail-closed ingress·Cloudflare-only 443·관측 경계
.venv/bin/python gitops_tree.py     # root-app → wave별 child Application health gate
.venv/bin/python preview_env.py     # PR 수명주기와 공유 preview 자원
.venv/bin/python secret_supply_chain.py  # Ansible·AWS IAM·Secrets Manager·ESO 신뢰 경계
```

각 스크립트가 라이트·다크 두 벌을 만든다. `theme.py` 가 그 색 세트를 갖고 있다.

세 흐름도는 현재 운영 전 **desired state와 컷오버 gate**를 함께 표시한다.

- 앱 Ingress 점선은 현재 리소스가 있다는 뜻이 아니라 실제 host·같은-host TLS Secret을 준비하고 `ingress.enabled=true`로 켠 뒤 생기는 경로다.
- `origin/main` 보호는 기존 workflow를 먼저 원격에 merge하고 `Static validation` 성공을 확인한 다음, 조직 2FA를 UI에서 수동 강제하고 branch protection을 적용하는 순서다.
- 같은 노드의 Prometheus/Alertmanager는 전체 node 소실을 알릴 수 없으므로 traffic flow의 외부 uptime monitor를 생략하지 않는다.
- `pg-backup`은 03:00 Asia/Seoul·deadline 1시간으로 정의됐지만 `suspend:true`라 외부 backup/restore 흐름은 그리지 않는다.

**배경을 `transparent` 로 두면 안 된다.** `diagrams` 의 `Cluster` 는 자체 밝은 배경색을 갖고 있어서, 글자만 밝게 바꾸면 밝은 박스 위 밝은 글자가 되어 읽을 수 없다. 페이지 배경·클러스터 배경·글자색을 한 세트로 지정한다.

## 커밋 대상

```
out/*.png          커밋한다 — README 가 참조한다
*.py, *.yaml       커밋한다 — 재생성 수단
.venv/ .snapshot/  커밋하지 않는다 (.gitignore)
```
