# PR 프리뷰

프리뷰는 내부의 신뢰된 same-repository PR만 대상으로 한다.
fork와 외부 PR의 코드는 build, preview, deploy하지 않는다.
동시 상한은 6개다.
Ingress는 실제 DNS와 TLS를 정하기 전까지 기본 off다.

## 사용 조건

PR은 다음 조건을 모두 만족해야 한다.

- `tapple-be` 저장소에서 만든 branch다.
- 작성자는 `MEMBER`, `OWNER`, `COLLABORATOR` 중 하나다.
- maintainer가 head repository와 작성자 관계를 확인했다.
- maintainer가 `preview` label을 붙였다.
- backend `cd-gitops`가 PR head SHA 이미지를 GHCR에 push했다.

backend workflow는 same-repository와 author association을 fail-closed로 검사한다.
ApplicationSet PR generator는 author association을 직접 필터링하지 못하고 `preview` label을 본다.
따라서 `preview` label은 신뢰 검토를 끝냈다는 보안 승인이다.
fork 또는 외부 PR에 이 label을 붙이지 않는다.
외부 작성자는 label을 직접 붙일 권한을 갖지 않는다.

## 수명주기

```text
trusted PR + preview label
  -> backend image:<head SHA 12자리>
  -> ApplicationSet poll
  -> Argo Application
  -> createdb Job
  -> Deployment + Service

label 제거 또는 PR close
  -> workload prune
  -> PostDelete dropdb Job
  -> Application 삭제
```

ApplicationSet은 120초마다 PR을 확인한다.
Application 이름은 `tapple-preview-<PR번호>`다.
workload 이름은 `tapple-server-pr-<PR번호>`다.
database 이름은 `tapple_pr<PR번호>`다.
관측 service name은 `taple-pr<PR번호>`다.

## 격리 범위

모든 프리뷰는 `preview` namespace를 공유한다.
모든 프리뷰는 PostgreSQL Pod 한 대를 공유한다.
각 PR은 database를 따로 사용한다.
동시 Deployment 수와 namespace 자원은 ResourceQuota가 제한한다.
PSA `restricted:v1.36`이 enforce된다.
default-deny NetworkPolicy가 ingress와 egress를 차단한다.
앱은 DNS, preview PostgreSQL, OTel Collector, private CIDR을 제외한 public HTTPS만 사용할 수 있다.
prod와 dev DB 경로는 허용하지 않는다.

이 구조는 PR 사이의 강한 보안 격리가 아니다.
모든 PR은 같은 `app-secrets`와 `postgres-app` Secret을 사용한다.
모든 PR은 같은 `tapple_preview_app` database role을 사용한다.
그 role은 여러 `tapple_pr<N>` database의 owner가 된다.
신뢰된 내부 코드는 다른 preview database에 접근하거나 public HTTPS로 preview Secret을 내보낼 수 있다.
따라서 상호 불신 코드, fork, 외부 기여 코드는 절대 실행하지 않는다.
상호 불신 실행이 필요해지면 PR별 credential, namespace, NetworkPolicy, database role을 함께 분리한다.

## 확인 방법

현재 외부 URL은 없다.
일반 maintainer는 승인된 Grafana 계정으로 `taple-pr<번호>`를 선택해 로그, metric, trace를 본다.
kubectl과 port-forward는 인프라 관리자만 사용한다.

```bash
kubectl get application -n argocd tapple-preview-27
kubectl get deployment/tapple-server-pr-27 service/tapple-server-pr-27 \
  job/tapple-server-pr-27-createdb -n preview
kubectl port-forward -n preview service/tapple-server-pr-27 18080:80
curl -fsS http://127.0.0.1:18080/actuator/health
```

실제 HTTPS host, Cloudflare proxied DNS, PR별 TLS 공급 경로를 설계한 뒤에만 Ingress를 켠다.
HTTP placeholder와 `.example.invalid` host는 외부 공개 경로가 아니다.
Google OAuth는 동적 callback URL을 사전 등록하지 않으므로 프리뷰에서 지원하지 않는다.

## database 생성

createdb Job은 앱보다 먼저 실행된다.
허용 owner는 `tapple_preview_app` 하나다.
없는 `tapple_pr<N>` database만 생성하므로 재실행해도 안전하다.
admin Secret은 상시 platform `secrets` Application이 관리한다.

```bash
kubectl get job -n preview tapple-server-pr-27-createdb
kubectl logs -n preview job/tapple-server-pr-27-createdb
```

## database 삭제

PR을 닫거나 label을 떼면 Argo CD가 Application 리소스를 먼저 prune한다.
그 뒤 `PostDelete` hook이 같은 `createDatabase.name`을 삭제한다.
렌더와 runtime은 `^tapple_pr[0-9]+$`만 허용한다.
`postgres`, template, bootstrap, prod, dev 이름은 명시적으로 거부한다.
cleanup은 접속 시각이나 파일 수정 시각을 추측하지 않는다.

dropdb Job은 기존 연결을 강제로 끊지 않는다.
연결, Secret, DB 장애로 DROP이 실패하면 Application은 `DeletionError`로 남는다.
실패 Job도 원인 확인을 위해 남는다.
원인을 고친 뒤 Application 삭제를 다시 시도한다.

```bash
kubectl get application -n argocd tapple-preview-27
kubectl get job -n preview tapple-server-pr-27-dropdb
kubectl logs -n preview job/tapple-server-pr-27-dropdb
```

수동 DROP은 자동 hook을 복구할 수 없는 경우에만 인프라 관리자가 수행한다.
대상 이름을 다시 확인하고 preview bootstrap database에 접속한다.

```bash
kubectl exec -it -n preview postgres-preview-0 -- sh -ceu '
  target_db=tapple_pr27
  suffix="${target_db#tapple_pr}"
  case "$suffix" in ""|*[!0-9]*) exit 64 ;; esac
  exec dropdb -U "$POSTGRES_USER" "$target_db"
'
```

## 운영 준비

- `/tapple/platform/argocd/preview-github-token`은 PR read-only PAT를 가진다.
- `/tapple/preview/app-secrets`는 prod와 dev 값을 재사용하지 않는다.
- `/tapple/preview/postgres-app`은 shared preview app password를 가진다.
- `/tapple/preview/postgres-preview-secrets`는 preview 관리자 자격증명을 가진다.
- `/tapple/shared/ghcr-pull`은 read-only package credential을 가진다.
- 5개 관련 ExternalSecret이 `Ready=True`인지 확인한다.
- `preview` label 권한을 신뢰된 maintainer로 제한한다.
- fork PR에 label을 붙여도 backend image가 생성되지 않는지 실제로 확인한다.

## 알려진 tradeoff

한 namespace와 한 PostgreSQL은 메모리를 아낀다.
대신 PR 사이 credential과 DB trust boundary가 없다.
SHA tag는 ApplicationSet만으로 즉시 프리뷰를 만들 수 있다.
대신 prod와 dev의 immutable digest 수준은 제공하지 않는다.
PostDelete hook은 정확한 PR database만 지운다.
대신 연결이 남으면 자동 정리보다 안전한 실패를 선택한다.
