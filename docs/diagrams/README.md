# 다이어그램 재생성

자동화하지 않았다. 클러스터 구조는 몇 주에 한 번 바뀌므로 사람이 다시 뽑는 게 싸다. 대신 **절차를 여기 남겨** 누구든 5분에 재생성할 수 있게 한다.

이미지에는 스냅샷 날짜를 함께 표기한다 — 낡은 그림을 읽는 사람이 낡았다는 걸 알아야 한다.

## 두 도구를 나눠 쓴다

| 산출물 | 도구 | 이유 |
|---|---|---|
| `architecture-app` · `architecture-platform` | **KubeDiagrams** | 클러스터의 실제 상태에서 **파생**시킨다. 손으로 그리면 반드시 낡는다 |
| `cicd-flow` · `traffic-flow` · `gitops-tree` | **mingrammer/diagrams** | 매니페스트에 없는 것들이다. 아래 참고 |

**mingrammer 로 그리는 것들이 왜 파생될 수 없나**

- `app → postgres` — `POSTGRES_URL` 환경변수 안의 접속 문자열이다. k8s 참조가 아니라 값이라 도구가 추론할 수 없다
- `app → otel-collector` — 같은 이유(`OTEL_URL`)
- `root-app → 자식 13개` — ArgoCD Application 의 `directory.recurse: true` 한 줄에 숨어 있다
- CI/CD 전체 — GitHub Actions·ghcr·git 커밋은 클러스터 리소스가 아니다

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
for ns in monitoring argocd kube-system; do
  kubectl get deployment,statefulset,daemonset,service,pvc -n $ns -o yaml > .snapshot/20-$ns.yaml
done

.venv/bin/kube-diagrams -c kube-diagrams.yaml -o out/architecture-app      -f png .snapshot/10-*.yaml
.venv/bin/kube-diagrams -c kube-diagrams.yaml -o out/architecture-platform -f png .snapshot/20-monitoring.yaml
```

주의할 점 세 개.

- **네임스페이스 목록(`kubectl get ns`)을 입력에 넣지 마라.** 네임스페이스가 클러스터 박스와 별도 노드로 이중 렌더되어 떠 있는 육각형이 생긴다. 리소스만 넣으면 박스는 자동으로 만들어진다
- **`-f dot` 으로 뽑아 `dot` 으로 재렌더하지 마라.** 같은 이중 렌더 문제가 생긴다. 배경색을 바꾸려는 게 목적이었는데, 배경은 투명으로 둬도 된다 — 모든 글자가 불투명한 밝은 박스 안에 있어 다크 모드에서도 읽힌다
- `manifests/monitoring` 의 ConfigMap 9개(대시보드 JSON)는 위 kind 목록에 없어 자동으로 빠진다. 넣으면 박스만 9개 늘고 정보는 늘지 않는다

`kube-diagrams.yaml` 은 라벨 기반 클러스터 박스(`K8s Instance`·`Helm Chart` 등)를 줄이려고 둔 커스텀 설정이다. 현재 버전에서는 `recommended: false` 가 그 박스를 완전히 없애지는 못한다 — 중첩이 거슬리면 스냅샷에서 해당 라벨을 지워야 하지만, 그 라벨이 Service 셀렉터 매칭에도 쓰여 화살표가 사라질 수 있으니 주의.

## 흐름도 (mingrammer)

```bash
.venv/bin/python cicd_flow.py       # 배포 파이프라인
.venv/bin/python traffic_flow.py    # 요청·관측·운영 접근 경로
.venv/bin/python gitops_tree.py     # root-app → 자식 13개, sync wave 순서
```

각 스크립트가 라이트·다크 두 벌을 만든다. `theme.py` 가 그 색 세트를 갖고 있다.

**배경을 `transparent` 로 두면 안 된다.** `diagrams` 의 `Cluster` 는 자체 밝은 배경색을 갖고 있어서, 글자만 밝게 바꾸면 밝은 박스 위 밝은 글자가 되어 읽을 수 없다. 페이지 배경·클러스터 배경·글자색을 한 세트로 지정한다.

## 커밋 대상

```
out/*.png          커밋한다 — README 가 참조한다
*.py, *.yaml       커밋한다 — 재생성 수단
.venv/ .snapshot/  커밋하지 않는다 (.gitignore)
```
