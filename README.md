# tapple-infra-v2 — k3s GitOps

단일 노드 k3s 클러스터(**8 vCPU / 32GB**)의 **전체 상태 정의**. Git 커밋 = 배포. 배경과 결정 기록(D1~D19)은 [docs/k3s-migration-plan.md](docs/k3s-migration-plan.md).

앱 코드는 [tapple-be](https://github.com/Tapplee/tapple-be), AWS 시절 인프라와 **모니터링 대시보드 원본**은 [tapple-infra](https://github.com/Tapplee/tapple-infra)(v1), 부하 리그는 [tapple-loadtest](https://github.com/Tapplee/tapple-loadtest).

> 현재 상태: **임시 VPS에서 검증 중** (8 vCPU/31GB Ubuntu 24.04). ingress host는 그 VPS의 `nip.io` 주소로 잡혀 있다. iwinv 노드로 옮길 때 values의 host 두 줄만 실도메인으로 교체.
>
> 2026-08-12 기준 **Application 15개 전부 Synced/Healthy**. 돌아가는 것: prod·dev 두 환경, PR 프리뷰(PR 당 임시 환경), DB 네트워크 격리, 팀원 최소권한 DB 접속, 모니터링 스택. **실운영은 아직 홈서버 + 로컬 compose 다.** 컷오버는 도메인+TLS 뒤.

**이 레포는 public이다.** SealedSecret 암호문만 커밋하고 평문 시크릿은 절대 올리지 않는다(secret scanning + push protection 켜져 있음). ArgoCD는 public 레포라 자격증명 없이 pull한다 — private로 되돌리면 deploy key 등록이 필요해진다.

## 그림으로 보기

> 2026-08-12 클러스터 스냅샷. 재생성 절차는 [docs/diagrams/README.md](docs/diagrams/README.md). CI 자동화는 없다 — 구조가 바뀌면 손으로 다시 뽑는다.

**아키텍처** — 앱·DB 네임스페이스의 실제 리소스. 라이브 클러스터에서 KubeDiagrams 로 파생시킨 것이라 이 시점의 사실이다.

**prod 는 `app` + `db`, dev 는 `dev-app` + `dev-db`다.** prod 에 접두어가 없는 게 원래 매니페스트 관례라 이름만으로는 드러나지 않아, 각 리소스에 `environment` 라벨을 붙여 그림에 `환경: prod` / `환경: dev` 박스로 나오게 했다. `kubectl get ns -l environment=prod` 로도 고를 수 있다.

`data-postgres-0` PVC 하나만 그 박스 밖에 있다. StatefulSet 의 `spec.volumeClaimTemplates` 가 불변 필드라 라벨을 추가할 수 없다 — 넣으면 기존 워크로드 갱신이 admission 단계에서 거부된다.

<picture>
  <img alt="app·db·dev-app·dev-db 네임스페이스의 Deployment·StatefulSet·Service·Ingress·PVC 구성" src="docs/diagrams/out/architecture-app.png">
</picture>

모니터링 스택은 [architecture-platform.png](docs/diagrams/out/architecture-platform.png) 로 따로 뽑아뒀다 (grafana·prometheus·loki·tempo·otel-collector).

**트래픽 흐름** — 누가 누구를 부르는가. 파랑이 사용자 요청, 보라가 관측 데이터 push, 빨강이 운영자·팀원 접근이다. 이 연결들은 환경변수 안의 문자열이라 매니페스트에서 파생시킬 수 없어 손으로 그렸다.

<picture>
  <source media="(prefers-color-scheme: dark)"  srcset="docs/diagrams/out/traffic-flow-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/diagrams/out/traffic-flow.png">
  <img alt="인터넷에서 traefik·ingress·service를 거쳐 앱에 닿고, 앱이 postgres와 otel-collector로 나가는 경로" src="docs/diagrams/out/traffic-flow.png">
</picture>

**배포 흐름** — 코드 push 부터 클러스터 반영까지. 빨간 화살표의 방향이 이 설계의 핵심이다: **ArgoCD 가 GitHub 을 읽는다(pull).** 앱 레포에서 클러스터로 가는 화살표가 없다.

<picture>
  <source media="(prefers-color-scheme: dark)"  srcset="docs/diagrams/out/cicd-flow-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/diagrams/out/cicd-flow.png">
  <img alt="push에서 GitHub Actions·ghcr·인프라 레포 태그 커밋을 거쳐 ArgoCD가 pull 배포하는 흐름" src="docs/diagrams/out/cicd-flow.png">
</picture>

**브랜치 하나가 올라가는 길** — 기능 브랜치를 따서 dev 를 거쳐 prod 까지 가는 순서와, 잘못됐을 때 되돌리는 두 경로. **주황이 사람이 눌러야 하는 것, 파랑이 자동, 빨강이 되돌리기**다. 여러 명이 동시에 작업할 때 `dev` 를 서로 덮는 문제는 아래 PR 프리뷰가 담당한다.

<picture>
  <source media="(prefers-color-scheme: dark)"  srcset="docs/diagrams/out/branch-flow-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/diagrams/out/branch-flow.png">
  <img alt="기능 브랜치에서 dev·main을 거쳐 배포되고, ArgoCD UI 또는 git revert로 되돌리는 흐름" src="docs/diagrams/out/branch-flow.png">
</picture>

사람이 누르는 지점이 **네 곳뿐**이다 — 브랜치 따기, dev 로 Squash 머지, dev 에서 확인, main 으로 Merge commit. 나머지는 자동이다.

되돌리기는 두 경로가 있고 성질이 다르다.

| | 방법 | 속도 | Git 상태 |
|---|---|---|---|
| ⓐ | ArgoCD UI → HISTORY → 이전 버전 | 초 단위 | 그대로. **self-heal 이 다시 최신으로 되돌릴 수 있다** — 임시 조치 |
| ⓑ | `git revert` → push | 분 단위 (빌드 포함) | Git 이 정답지로 남는다. **영구 조치** |

급하면 ⓐ 로 막고, ⓑ 로 마무리한다. ⓐ 만 하고 끝내면 다음 sync 에서 되살아난다.

**PR 프리뷰** — PR 하나마다 그 브랜치만의 서버가 뜬다. `dev` 환경이 하나뿐이라 여러 명이 각자 확인하려면 `dev` 에 머지해야 하고, 나중에 머지한 사람이 앞사람 걸 덮는다. 그 문제를 없앤다. 사용법은 [docs/preview-environments.md](docs/preview-environments.md).

<picture>
  <source media="(prefers-color-scheme: dark)"  srcset="docs/diagrams/out/preview-env-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/diagrams/out/preview-env.png">
  <img alt="PR에 preview 라벨을 붙이면 이미지 빌드·ApplicationSet 감지를 거쳐 임시 환경이 생기고, PR을 닫으면 사라지는 흐름" src="docs/diagrams/out/preview-env.png">
</picture>

`preview` 라벨을 붙이면 3~5분 뒤 `pr-<번호>.api.<호스트>` 가 뜨고, PR 을 닫으면 사라진다. **라벨이 곧 자리 예약**이라 다 본 PR 은 떼야 한다 — 동시 6개가 상한이다.

**GitOps 제어 흐름** — 수동 apply 는 `bootstrap/root-app.yaml` 하나뿐이고, 나머지 14개 Application 은 그것이 만든다. 점선이 순서 의존(sync wave)이다.

`preview` 의 ApplicationSet 만 성질이 다르다 — Application 을 **런타임에 더 만든다**. Git 에 없는 Application 이 클러스터에 생기는 유일한 경로다.

<picture>
  <source media="(prefers-color-scheme: dark)"  srcset="docs/diagrams/out/gitops-tree-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/diagrams/out/gitops-tree.png">
  <img alt="root-app 하나가 wave -3부터 2까지 14개 Application을 만들고, preview의 ApplicationSet이 PR마다 Application을 더 만드는 구조" src="docs/diagrams/out/gitops-tree.png">
</picture>

## 구조

아래 트리는 **항상 맞는 부분**이다. 위 그림은 특정 시점의 스냅샷이고, 이 트리는 레포 구조 자체라 커밋 diff 에 드러나고 검색도 된다.

```
bootstrap/root-app.yaml     재구축 시 수동 apply하는 유일한 파일 (app-of-apps 루트)
apps/                       ArgoCD Application 정의 — root가 재귀 sync
  platform/                 환경 공용
    cluster.yaml              wave -3  → manifests/cluster/ (네임스페이스·PriorityClass·RBAC)
    sealed-secrets.yaml       wave -2  upstream 차트 (시크릿 복호화 컨트롤러)
    secrets.yaml              wave -1  → secrets/ (prod·dev 모두 커버)
    monitoring/               wave 2   기존 compose 스택 이식 — prod·dev 공유
  prod/
    postgres.yaml             wave 0   → manifests/postgres/        [db]
    tapple-server.yaml        wave 1   → charts/tapple-server/      [app]
  dev/
    postgres.yaml             wave 0   → manifests/postgres-dev/    [dev-db]
    tapple-server.yaml        wave 1   → 같은 차트 + values-dev.yaml [dev-app]
  preview/                    PR 프리뷰 — docs/preview-environments.md
    postgres.yaml               공유 DB 1대                          [preview]
    applicationset.yaml         PR 하나당 Application 자동 생성·삭제
charts/tapple-server/       자작 Helm 차트 (환경 공용) + values.yaml(prod)·values-dev.yaml·values-preview.yaml
manifests/cluster/          네임스페이스 6개 + PriorityClass 4종 + team-access.yaml (팀원 RBAC)
manifests/postgres/         prod DB — StatefulSet·Service·NetworkPolicy·백업 CronJob·읽기전용 롤 Job
manifests/postgres-dev/     dev DB — 축소판 (백업 없음, 우선순위 최하) + NetworkPolicy
manifests/postgres-preview/ 프리뷰 공유 DB + 고아 database 정리 CronJob
manifests/monitoring/       대시보드 7개 + 알림 규칙 ConfigMap — 전부 gen-configmaps.py 산출물, 직접 고치지 말 것
secrets/                    kubeseal로 암호화된 SealedSecret 14종 (평문 금지 — secrets/README.md)
infra/                      노드 부트스트랩 셸 스크립트 (Phase 1~2)
scripts/gen-configmaps.py   v1의 대시보드·규칙 원본 → ConfigMap 변환
scripts/gen-team-kubeconfig.sh  팀원용 SA 토큰 kubeconfig 발급 (기본 90일)
.github/workflows/seal-secret.yml  SSH 없이 시크릿 재씰링 — Actions 금고 값을 읽어 secrets/ 에 커밋
runbooks/                   재해 복구 절차
docs/db-access.md           팀원 DB 접속 가이드 (port-forward + 최소권한 RBAC)
docs/monitoring-access.md   팀원 Grafana 접속 — 구글 로그인, PR별 지표·로그 찾는 법
docs/preview-environments.md  PR 프리뷰 사용법 — 팀원이 먼저 읽을 문서
docs/diagrams/              위 그림들의 생성 스크립트 (직접 실행, CI 자동화 없음)
```

## 동작 원리 (한 줄씩)

- **ArgoCD app-of-apps**: `root-app` 하나가 `apps/`를 재귀 sync해 Application들을 만들고, 각 Application이 자기 소스를 클러스터에 sync.
- **sync-wave**: 클러스터 기반(-3) → 컨트롤러(-2) → 시크릿(-1) → DB(0) → 앱(1) → 모니터링(2).
- **앱만 Helm**: 배포마다 바뀌는 값(image.tag)이 있는 건 앱뿐. DB는 바뀔 값이 없어 raw yaml (D17·D19).
- **upstream은 vendoring 안 함** (D16): Application 안에 차트 repo URL + `valuesObject`만.
- **배포 트리거는 앱 레포**: tapple-be의 `cd-gitops.yml`이 ghcr에 이미지를 밀고 이 레포의 `image.tag` 한 줄을 커밋한다. ArgoCD가 그걸 감지해 배포.
- **프리뷰는 Git 에 없다**: ApplicationSet 이 GitHub PR 목록을 2분마다 읽어 `preview` 라벨이 붙은 PR 만큼 Application 을 만든다. 라벨을 떼거나 PR 을 닫으면 지운다 — 커밋이 필요 없는 유일한 배포 경로다.
- **시크릿은 레포에서 다시 만든다**: 클러스터에 SSH 하지 않는다. Actions 금고에 값을 넣고 `seal-secret.yml` 을 돌리면 워크플로가 공개 인증서로 씰링해 `secrets/` 에 커밋한다.

## 모니터링 원본은 이 레포가 아니다

`manifests/monitoring/*`은 **산출물**이다. 원본(대시보드 json·Prometheus·Loki 규칙)은 v1 `tapple-infra/monitoring/grafana/config`가 소유한다 — 부하 리그의 monitoring EC2가 같은 경로를 clone해 쓰기 때문에 옮기면 리그가 깨진다.

```bash
# 원본 고친 뒤 재생성 → 커밋
python3 scripts/gen-configmaps.py                        # 기본값: ../tapple-infra/monitoring/grafana/config
python3 scripts/gen-configmaps.py /다른/경로/config       # 원본 위치가 다르면
```

대시보드의 `Service` 드롭다운은 하드코딩이 아니라 **쿼리 변수**(`label_values(service_name)`)다. 그래서 환경마다 이름을 다르게 두면 드롭다운에서 골라 볼 수 있다 — prod `taple`, dev `taple-dev`. 같은 이름을 쓰면 두 환경 지표가 한 그래프에 섞인다.

이 값(`SPRING_APPLICATION_NAME`)은 Prometheus 의 `application` 라벨과 Loki·Tempo 의 `service_name` 에 동시에 반영된다. `DEPLOY_ENV`(→ `deployment_environment`)는 alertmanager 알림 제목이 우선 참조하는 라벨이라 함께 유지한다.

| 신호 | prod / dev 구분 |
|---|---|
| 대시보드 | `Service` 드롭다운 (`taple` / `taple-dev`) |
| Prometheus 알림 | 필터 없이 `sum by (application, service_name)` — 앱별로 따로 발생 |
| 알림 제목 | `deployment_environment` = prod / dev |
| Loki 로그 알림 | **prod 만** — 규칙이 `{service_name="taple"}` 하드코딩. dev 가 알림을 보내지 않는 건 의도된 동작 |

## 환경 (prod / dev)

**클러스터는 하나, 네임스페이스로 분리.** 브랜치로 환경을 나누지 않는다(안티패턴) — 인프라 레포는 항상 `main` 한 브랜치, 환경 차이는 디렉터리와 values 파일로만.

| | prod | dev | PR 프리뷰 |
|---|---|---|---|
| 네임스페이스 | `app` · `db` | `dev-app` · `dev-db` | `preview` (전부 한 곳) |
| 앱 리소스 (req / lim) | 4Gi·1000m / 6Gi·3000m | 2Gi·250m / 3Gi·1500m | 1Gi·200m / 2Gi·1500m |
| DB | 전용 8Gi Guaranteed | 전용 2Gi | 공유 1대 1Gi, PR 당 database |
| PriorityClass | `app-important` / `db-critical` | `dev-low` | `preview-lowest` (**가장 먼저 축출**) |
| DB명 | `tapple` | `tapple_dev` | `tapple_pr<PR번호>` |
| 백업 | pg_dump CronJob | 없음 | 없음 (7일 미접속 시 database 삭제) |
| 관측 | `service_name=taple` | `taple-dev` | `taple-pr<번호>` |
| 트리거 | `main` push | `dev` push | PR 에 `preview` 라벨 |

**동시 프리뷰는 6개까지다.** 노드 여유(9.8Gi)를 PR 당 1Gi 로 나눈 값이고, 7번째는 `Pending` 에서 멈춘다. `preview` 라벨이 곧 자리 예약이라 다 본 PR 은 라벨을 떼야 한다.

## 네트워크 격리

**네임스페이스는 이름만 나눈다. 네트워크는 막지 않는다.** NetworkPolicy 가 없으면 `monitoring` 이든 `preview` 든 어느 파드에서나 `postgres.db.svc:5432` 에 붙을 수 있다. 프리뷰처럼 짧게 살다 사라지는 워크로드가 늘수록 위험해지므로 DB 두 대를 닫았다.

| 대상 | 허용 | 파일 |
|---|---|---|
| prod DB | `app` · `db` 네임스페이스만 | `manifests/postgres/networkpolicy.yaml` |
| dev DB | `dev-app` · `dev-db` 네임스페이스만 | `manifests/postgres-dev/networkpolicy.yaml` |
| 프리뷰 DB | 제한 없음 | 프리뷰 전용 데이터라 의도적으로 열어둠 |

팀원의 `kubectl port-forward` 는 **NetworkPolicy 대상이 아니다** — kubelet 이 노드에서 프록시하므로 파드 간 트래픽이 아니다. 그 경로의 접근 통제는 RBAC(`manifests/cluster/team-access.yaml`)이 한다.

## 리소스 예산 (8 vCPU / 32GB 노드)

`system-reserved`로 OS+k3s 몫 2Gi/1000m을 떼면 **allocatable ≈ 30Gi / 7 vCPU**.

| 대상 | requests | limits | QoS |
|---|---|---|---|
| prod PostgreSQL | 8Gi / 2000m | 8Gi / 2000m | **Guaranteed** |
| prod 앱 | 4Gi / 1000m | 6Gi / 3000m | Burstable |
| dev PostgreSQL | 2Gi / 250m | 2Gi / 1000m | Burstable |
| dev 앱 | 2Gi / 250m | 3Gi / 1500m | Burstable |
| 모니터링 스택 전체 | ~2.2Gi / 440m | ~3.3Gi | Burstable |
| ArgoCD + Traefik + sealed-secrets | ~1.3Gi / 530m | ~2Gi | Burstable |
| **합계 (requests)** | **~19.5Gi / 4.47 vCPU** | | 여유 **~10Gi / ~2.5 vCPU** |

- requests는 **스케줄러가 자리를 잡아두는 예약**일 뿐이라, 유휴 CPU는 limits 한도까지 다른 파드가 그대로 쓴다 → prod 앱은 순간 3코어까지 뻗을 수 있음.
- 축출 순서: `dev-low`(-100) → 모니터링·기본(0) → `app-important`(1000) → `db-critical`(1000000).
- PostgreSQL 튜닝값(`shared_buffers=2GB` 등)은 limits 8Gi에 맞춰져 있다 — **메모리를 바꾸면 args도 같이** 고칠 것.

## 로컬 검증 (클러스터 없이)

```bash
# prod 렌더
helm template tapple-server charts/tapple-server --set image.tag=test

# dev 렌더 (values 겹치기 — 뒤 파일이 앞을 덮어씀)
helm template dev-tapple-server charts/tapple-server \
  -f charts/tapple-server/values.yaml \
  -f charts/tapple-server/values-dev.yaml --set image.tag=test

# preview 렌더 (ApplicationSet 이 넘기는 값은 --set 으로 흉내낸다)
helm template tapple-preview-27 charts/tapple-server \
  -f charts/tapple-server/values.yaml \
  -f charts/tapple-server/values-preview.yaml \
  --set image.tag=test --set fullnameOverride=tapple-server-pr-27 \
  --set createDatabase.name=tapple_pr27

helm lint charts/tapple-server --set image.tag=test
```

클러스터가 있으면 `kubectl apply --dry-run=server -f <파일>` 이 훨씬 많이 잡는다 — 불변 필드 위반은 이것만 잡는다. **단 Job 은 spec 이 불변이라 이 검사를 통과할 수 없다**(위 함정 항목).

## 노드에 올리는 순서

```
①infra/node-bootstrap.sh  →  ②infra/k3s-setup.sh  →  ③시크릿 14종  →  앱 Running
```

②의 마지막 스텝이 `bootstrap/root-app.yaml`을 apply하고, 그때 sealed-secrets 컨트롤러가 뜬다. 시크릿을 **새로 만들어야 하는 경우**엔 그 뒤에만 가능하다(클러스터 공개키로 암호화) — 그전까지 DB·grafana·alertmanager 파드는 `CreateContainerConfigError`가 정상이다.

이미 `secrets/`에 SealedSecret이 커밋돼 있으므로 **같은 컨트롤러 키를 복원한 경우엔** ③이 자동으로 풀린다. 키를 잃으면 전부 재생성이다 — `secrets/README.md`의 개인키 백업 절차를 반드시 해둘 것.

앱 파드는 `image.tag`가 비어 있으면 Application이 `Unknown`으로 남는다(의도된 가드). tapple-be의 `cd-gitops.yml`이 태그를 커밋해야 뜬다.

## 실측으로 잡은 함정

읽어서는 안 나오고 돌려봐야 나온 것들. 매니페스트 주석에도 같은 내용이 붙어 있다.

**DB 에 붙는 Job 이 `Connection refused` 로 즉사한다.** k3s 의 NetworkPolicy 구현(kube-router)은 허용 대상 파드 IP 를 ipset 으로 관리하는데, 파드가 뜬 직후에는 그 IP 가 아직 셋에 없다. 그 창의 패킷은 `KUBE-POD-FW-*` 마지막 `REJECT --reject-with icmp-port-unreachable` 에 걸려 **timeout 이 아니라 refused** 로 돌아온다 — 그래서 방화벽 문제로 보이지 않는다. 오래 사는 파드는 재시도로 넘어가고 짧게 살다 죽는 Job 만 걸린다. 대응: 접속 전 `pg_isready` 대기 루프(최대 120초). `postgres-readonly-role` Job 이 이걸로 조용히 Failed 가 돼 `tapple_ro` 롤이 사라져 있었다.

**PVC 를 한 단계 위에 마운트하면 데이터가 조용히 사라진다.** `postgres:16` 이미지가 `/var/lib/postgresql/data` 를 `VOLUME` 으로 선언하므로 PVC 를 그 부모에 마운트하면 containerd 익명 볼륨이 PVC 를 덮는다. 쓰기는 성공하고 조회도 되는데 파드를 지우면 전부 날아간다. 원안이 `postgres:18` 기준이었고 16 으로 내리며 경로를 안 바꾼 것이 원인. 대응: `mountPath` 를 그 경로에 정확히 맞추고 `PGDATA` 를 그 하위(`/pgdata`)로.

**ArgoCD PostSync 훅이 이 클러스터에서 실행되지 않는다.** 컨트롤러가 매 sync 계획에는 넣으면서 실행 단계에서 `skipHooks:true` 로 건너뛴다. 대응: 계정 생성 같은 필수 작업은 훅이 아니라 추적 리소스(Job)로 둔다.

**Job 의 spec 은 불변이라 `apply` 로 못 고친다.** `Replace=true` 만 주면 `kubectl replace` 가 되는데 Job 의 `spec.selector` 는 컨트롤러가 만드는 값이라 매니페스트에 없다 → `spec.selector: Required value` 로 거부된다. 대응: `sync-options: Force=true,Replace=true`(삭제 후 재생성). **처음 생성될 때는 create 라 드러나지 않고 매니페스트를 고친 뒤에야 터진다.**

**StatefulSet 의 `volumeClaimTemplates` 는 불변이다.** 라벨 하나만 추가해도 기존 워크로드 갱신이 admission 에서 거부된다. 대응: 손대기 전에 `kubectl apply --dry-run=server` 로 확인.

**`kubectl auth can-i create pods/portforward` 는 권한이 있어도 `no` 를 답한다**(kubectl 1.36). 슬래시를 서브리소스로 해석하지 않는다. 대응: `--subresource=portforward`.

**노드에 `ipset` 바이너리가 없다.** 그래서 `ipset list` 가 조용히 빈 출력을 내는데, 셋이 비었다고 오독하기 쉽다. netpol 을 파볼 때 `apt-get install ipset` 먼저.

PR 프리뷰 쪽 함정 4개(라벨 필터 위치, sprig `substr` 인자 순서, PR 이벤트의 머지 커밋 체크아웃, URL 계열을 시크릿에 넣으면 안 되는 이유)는 [docs/preview-environments.md](docs/preview-environments.md#밟기-쉬운-함정-구축-중-실제로-밟은-것) 에 있다.

## 남은 TODO

- [ ] **도메인 + TLS** — 지금은 nip.io `http`. **이것 때문에 k3s 세 환경(prod·dev·preview) 전부 구글 로그인이 안 된다** (Google OAuth 는 리다이렉트 URI 사전 등록 + HTTPS 요구). 로그인 화면 확인은 홈서버에서. 고칠 곳은 `values.yaml`·`values-dev.yaml` 의 `ingress.host` 와 ApplicationSet 의 프리뷰 호스트. **프리뷰 호스트는 1단으로 평평하게** — Cloudflare Universal SSL 이 `*.tapple.co.kr` 까지만 커버하므로 `pr-27.api.tapple.co.kr` 은 인증서가 안 맞는다. `pr-27-api.tapple.co.kr` 로
- [ ] **Grafana 팀원 공개 — 사람 손 3개 남음** ([docs/monitoring-access.md](docs/monitoring-access.md)). 레포 쪽은 다 들어가 있고 스위치가 꺼져 있다: ①Cloudflare A 레코드 `grafana-k3s` → 노드 IP ②Google Console 리다이렉트 URI ③`Seal secrets` → `grafana-oauth` ④`grafana.yaml` 의 `auth.google.enabled: true`. 그때까지 **팀원이 모니터링을 볼 방법이 없다**
- [ ] Discord webhook 실값 — 지금은 더미라 알림이 아무데도 가지 않는다 (홈서버 `.env`도 `CHANGEME`)
- [ ] 컷오버 전 로테이션 — AWS 키·Google 시크릿·JWT 키. 지금 클러스터엔 더미가 들어가 있다. `JWT_SECRET_KEY` 를 바꾸면 전원이 즉시 로그아웃되고, `SLUG_RESERVATION_HMAC_KEY` 는 이전 키를 `previousKeys` 에 **남긴 채** 버전만 올려야 한다
- [ ] `PREVIEW_GITHUB_TOKEN` 만료 관리 — fine-grained PAT 이라 만료되면 **프리뷰가 조용히 안 뜬다**. 증상은 ApplicationSet 상태의 `error fetching Secret token`
- [ ] upstream 차트 버전 5종 설치 시점 최신 고정 (sealed-secrets + monitoring 4종 — 내부 이미지 태그는 compose와 동일하게 이미 고정)
- [ ] iwinv 플랜 상품 코드·월 요금 확인 — 매니페스트는 **8 vCPU / 32GB** 기준
- [ ] Traefik `trustedIPs`(Cloudflare 대역) — 없으면 로그·레이트리밋에 실 사용자 IP 대신 Cloudflare IP가 찍힘
- [ ] ghcr retention — 오래된 이미지 자동 삭제 (최근 N개 + 배포 중 태그는 보존)
- [ ] 매니페스트 lint CI (helm template·kubeconform)
- [ ] 팀원 kubeconfig 발급 — [docs/db-access.md](docs/db-access.md) §6 (토큰 기본 90일, 만료 시 재발급)
- [~] 대시보드의 AWS 잔재 — `AWS Region`·`RDS Instance` 변수와 그 패널들이 CloudWatch 데이터소스를 요구해 k3s 에서는 에러로 뜬다. **그대로 두기로 결정**했다 (원본은 v1 소유이고 부하 리그가 같은 파일을 쓴다)
- [x] PR 프리뷰 환경 — ApplicationSet(PR 생성기) + 공유 DB + PR 당 database. PR #27 로 전 과정 실측
- [x] DB 네트워크 격리 — prod·dev DB 에 NetworkPolicy. 5경우 실측
- [x] DB 접속 Job 의 NetworkPolicy 대기 루프 — 위 함정 항목 참고
- [x] PVC 마운트 경로 — 데이터가 익명 볼륨에 쌓이던 것 수정, 파드 삭제 후 생존 실측
- [x] 팀원 DB 접속 — `team-access` SA + 최소권한 Role, `scripts/gen-team-kubeconfig.sh`
- [x] SSH 없는 시크릿 재씰링 — `.github/workflows/seal-secret.yml`
- [x] 시크릿 14종 씰링 (`secrets/`) — 부팅 필수값만 실값, 나머지 더미
- [x] `ghcr-pull` 시크릿 3종 (prod·dev·preview)
- [x] BE 로그 분리 — `k3s` 프로파일 추가. `prod`·`dev` 프로파일이 `@Profile("!prod")` 등으로 코드에 물려 있어 이름을 못 바꿨고, `prod & !k3s` 조건으로 CloudWatch appender 만 뺐다
- [x] tapple-be `cd-gitops.yml` 브랜치→환경 판정 + `INFRA_REPO_TOKEN` 등록 + push 트리거 활성
- [x] k3s v1.36.3+k3s1 · ArgoCD v3.5.0 버전 고정 (`infra/k3s-setup.sh`)
- [x] DB명(`tapple`)·Hikari 풀(10) ↔ `max_connections=60` 매칭
- [x] 알림 채널 — Discord webhook, 기존 alertmanager 라우팅 그대로
- [x] 모니터링 원본/산출물 경계 — 원본은 v1 유지, 여기는 산출물만
