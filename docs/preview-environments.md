# PR 프리뷰 환경

PR 하나마다 그 브랜치만의 서버가 뜬다. PR을 닫으면 사라진다.

**해결하는 문제**: dev 환경이 하나뿐이라 여러 사람이 각자 기능을 확인하려면 `dev`에 머지해야 하고, 나중에 머지한 사람 코드가 앞사람 걸 덮는다. 뭔가 깨졌을 때 누구 코드 때문인지 구분도 안 된다.

<picture>
  <source media="(prefers-color-scheme: dark)"  srcset="diagrams/out/preview-env-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="diagrams/out/preview-env.png">
  <img alt="PR에 preview 라벨을 붙이면 이미지 빌드·ApplicationSet 감지를 거쳐 임시 환경이 생기고, PR을 닫으면 사라지는 흐름" src="diagrams/out/preview-env.png">
</picture>

---

## 쓰는 법

```
1. PR 을 연다
2. `preview` 라벨을 붙인다          ← 이게 자리 예약이다
3. 3~5분 뒤 아래 주소가 뜬다
4. 다 봤으면 라벨을 떼거나 PR 을 닫는다
```

현재 `apps/preview/applicationset.yaml`의 host는 의도적으로 해석되지 않는
`pr-<PR번호>.api.example.invalid`다. IDC DNS/TLS를 정한 뒤 실제 1단 preview host
패턴으로 교체해야 URL이 열린다. 예를 들어 Cloudflare Universal SSL을 쓴다면
`https://pr-27-api.tapple.co.kr`처럼 평평한 이름을 사용한다.

**라벨을 붙였는데 안 뜬다면** 3~5분을 기다렸는지 확인한다. 이미지 빌드(약 2~3분) → ArgoCD가 PR 목록을 다시 읽는 주기(2분)를 거쳐야 한다.

## 무엇이 격리되고 무엇이 공유되나

| | 격리 | 비고 |
|---|---|---|
| 주소 | **PR마다 다름** | `pr-27...` / `pr-28...` |
| database | **PR마다 다름** | `tapple_pr27` / `tapple_pr28` |
| 앱 프로세스 | **PR마다 다름** | 서로 재시작해도 무관 |
| PostgreSQL 인스턴스 | 공유 | 한 대를 나눠 쓴다. 이게 죽으면 프리뷰 전부가 같이 죽는다 |
| 모니터링 스택 | 공유 | Grafana에서 `Service` 드롭다운으로 `taple-pr27` 선택 |
| 시크릿 | 공유 | 프리뷰 환경의 app·DB·GHCR credential을 모든 PR이 같이 쓴다 |

A가 마이그레이션을 추가해도 B의 database에는 영향이 없다. 각자 Flyway가 자기 database에 스키마를 만든다.

**내부의 신뢰된 PR만 대상이다.** PR별 시크릿 격리가 없으므로 fork나 외부 기여
PR에는 `preview` 라벨을 붙이지 않는다. 외부 PR을 받게 되면 PR별 credential과
namespace 격리를 먼저 설계해야 한다.

## 동시에 몇 개까지

**6개.** 무제한이 아니다.

```
노드 여유    9.8Gi
PR 당        1Gi
공유 DB      1Gi (1회)
```

7번째 PR에 라벨을 붙이면 파드가 `Pending`에서 멈춘다 — 메모리가 없어 스케줄이 안 된다. 안 쓰는 PR의 라벨을 떼면 자리가 난다.

**`preview` 라벨이 곧 자리 예약이다.** 다 봤으면 떼는 게 예의다.

## 되는 것 / 안 되는 것

| | |
|---|---|
| ✅ API 호출·응답 확인 | `curl`, Postman, FE 로컬 개발 서버 연결 |
| ✅ Swagger | `/swagger-ui.html` 로 계약 확인 |
| ✅ DB 직접 접속 | [db-access.md §3-2](db-access.md) — 쓰기도 열려 있다 |
| ✅ 앱 로그 | `kubectl logs -n preview -l app.kubernetes.io/instance=tapple-preview-<번호>` |
| ✅ 마이그레이션 시험 | 자기 database라 마음껏 |
| ❌ **구글 로그인** | 아래 참고 |
| ❌ 파일 업로드(S3) | 자격증명이 더미다 |
| ❌ Discord 알림 | 더미다 |

### 구글 로그인이 안 되는 이유

Google OAuth는 리다이렉트 URI를 **와일드카드 없이 사전 등록**해야 하고 **HTTPS만** 받는다. 프리뷰 주소는 PR마다 달라지고 지금은 `http`다. 그래서 등록 자체가 불가능하다.

같은 이유로 **지금 dev 환경도 로그인이 안 된다.** 프리뷰가 만든 제약이 아니라 실도메인+TLS가 붙기 전의 공통 한계다.

로그인이 필요한 화면은 HTTPS와 OAuth callback이 연결된 운영 도메인에서 확인한다.

## FE 개발자가 붙는 법

프리뷰의 CORS에 로컬 개발 서버 주소가 열려 있다.

```
http://localhost:3000
http://localhost:5173
```

FE 로컬 `.env`의 API 주소만 바꾸면 된다.

```
VITE_SERVER_API_URL=https://pr-27-api.tapple.co.kr/v1
```

BE가 `dev`에 머지하기를 기다리지 않고 PR 단계에서 바로 붙어볼 수 있다.

---

## 운영자용

### 구조

```
apps/preview/applicationset.yaml   PR 생성기 — preview 라벨 붙은 PR 만
apps/preview/postgres.yaml         공유 DB Application
manifests/postgres-preview/        공유 postgres + 고아 database 정리 CronJob
charts/tapple-server/values-preview.yaml
charts/tapple-secrets/              Secrets Manager JSON·SecretStore·ExternalSecret 계약
```

앱 레포(`tapple-be`)의 `cd-gitops.yml`이 `preview` 라벨 붙은 PR의 이미지를 ghcr에 올린다. ApplicationSet은 **PR head SHA**로 그 이미지를 당긴다.

### 시크릿 구성·갱신

시크릿 원본은 Git이 아니라 AWS Secrets Manager에 **환경별 Kubernetes Secret
계약 하나당 JSON Secret 하나**로 둔다. GHCR처럼 명시적으로 공유하는 값만 하나의
JSON Secret을 여러 namespace가 재사용한다. External Secrets Operator가 명시된 JSON
property만 읽어 기존 Kubernetes Secret 이름으로 동기화한다.

| 용도 | Secrets Manager 이름 / JSON property | Kubernetes Secret |
|---|---|---|
| 프리뷰 앱 | `/tapple/preview/app-secrets` / 앱 환경변수 properties | `app-secrets` |
| 프리뷰 DB | `/tapple/preview/postgres-preview-secrets` / `POSTGRES_USER`, `POSTGRES_PASSWORD` | `postgres-preview-secrets` |
| GHCR pull | `/tapple/shared/ghcr-pull` / `dockerconfigjson` | `ghcr-pull` (`.dockerconfigjson` key) |
| PR 목록 조회 | `/tapple/platform/argocd/preview-github-token` / `token` | `preview-github-token` |

`/tapple/preview/*`는 `preview` namespace의 namespaced `SecretStore`만 읽을 수 있고,
`/tapple/shared/*`에는 환경 공유를 명시적으로 허용한 GHCR Docker config만 둔다.
prod/dev 시크릿을 preview에 복사하지 않는다. 전체 Secrets Manager JSON 계약과 최초 구성 절차는
[`secrets/README.md`](../secrets/README.md)를 따른다.

Secrets Manager version을 갱신하면 ESO가 최대 1시간 안에 다시 읽는다. 즉시 반영해야 하면 해당
`ExternalSecret`에 `external-secrets.io/force-sync` 애노테이션을 갱신한다. 앱은
`envFrom`으로 값을 받으므로 Secret 동기화 후 프리뷰 Deployment를 재시작해야 한다.

`PREVIEW_GITHUB_TOKEN`은 fine-grained PAT이고 `tapple-be`에 `Contents: Read` + `Pull requests: Read`만 있으면 된다. **만료되면 프리뷰가 조용히 안 뜬다** — ApplicationSet 상태에 `error fetching Secret token`이 찍힌다.

### 정리

PR을 닫으면 Application·Deployment·Service·Ingress는 자동으로 사라진다. **database는 남는다** — ApplicationSet이 지우는 건 k8s 리소스뿐이고 database는 postgres 안의 객체다.

`preview-db-cleanup` CronJob이 매주 월요일 04:30에 **7일 넘게 접속이 없는** `tapple_pr%` database를 지운다.

즉시 지우려면:
```bash
kubectl exec -n preview postgres-preview-0 -- psql -U tapple -d preview_bootstrap \
  -c 'DROP DATABASE tapple_pr27'
```

### 밟기 쉬운 함정 (구축 중 실제로 밟은 것)

- **PR 생성기의 라벨 필터는 `github.labels`에 있다.** `filters[]`는 `branchMatch`·`targetBranchMatch`·`titleMatch`만 받는다. `filters[].labels`로 쓰면 admission이 unknown field로 거부한다
- **Go 템플릿의 `slice`는 문자열에 못 쓴다.** `{{ slice .head_sha 0 12 }}`는 `list should be type of slice or array but string`으로 죽는다. sprig의 `substr`을 쓰되 **인자 순서가 `(start, end, string)`으로 반대**다
- **PR 이벤트의 기본 체크아웃은 머지 커밋이다.** 그대로 빌드하면 이미지 태그가 머지 커밋 SHA가 되는데 ApplicationSet은 `head_sha`를 본다 → 찾는 이미지가 없다. `cd-gitops.yml`이 `ref: head.sha`로 체크아웃하는 이유
- **PR별 URL 계열은 공유 Secrets Manager JSON에 넣지 않는다.** `CORS_ALLOWED_ORIGINS`·`PUBLIC_*`·`*_REDIRECT_URI`는 PR마다 호스트가 달라야 한다. `/tapple/preview/app-secrets`는 모든 프리뷰가 공유하므로, 이 값들은 ApplicationSet이 차트 `env`로 주입한다

### 실측 기록 (2026-08-11)

PR #27로 전 과정을 확인했다.

| 단계 | 결과 |
|---|---|
| `preview` 라벨 → 이미지 빌드 | 성공 (head SHA `d0bc9782dee4`) |
| ApplicationSet → Application 생성 | `tapple-preview-27` |
| `createdb` Job | `CREATE DATABASE` / `database 준비 완료: tapple_pr27` |
| Flyway | `tapple_pr27`에 테이블 16개 |
| 외부 접근 | `HTTP 200` / `{"status":"UP"}` |
| prod DB 영향 | 없음 (16개 그대로) |
| 팀원 kubeconfig로 DB 접속 | `OK: tapple_pr27 / tapple / 테이블 16개` |
| PR 닫음 | Application·Deployment·Service·Ingress 자동 삭제 |
| 닫은 뒤 database | `tapple_pr27` 남음 (설계대로) |
