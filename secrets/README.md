# 시크릿 운영

AWS Secrets Manager가 유일한 값 원본이다.
Git에는 값, 암호문, 복호화 키를 두지 않는다.
`charts/tapple-secrets/values.yaml`이 JSON property와 Kubernetes Secret key의 canonical 계약이다.
ESO 2.10.0이 16개 JSON source를 20개 ExternalSecret으로 동기화한다.

```text
Ansible ─stdin/no_log─> aws-bootstrap ─> ESO ─STS─> IAM role 6개
                                                    │
Secrets Manager JSON source 16개 ───────────────────┘
        └─> SecretStore 10개 ─> ExternalSecret 20개 ─> Kubernetes Secret
```

`external-secrets/aws-bootstrap`은 순환 의존을 끊는 secret-zero다.
bootstrap IAM user는 Secrets Manager를 직접 읽지 못한다.
bootstrap access key 소유자는 session tag를 골라 6개 role을 모두 가정할 수 있다.
session tag는 오설정 방지와 감사 정보이며 탈취 방지 경계가 아니다.
장기 key가 부담이 되면 IAM Roles Anywhere의 단기 자격증명으로 교체한다.

ESO는 cluster-wide Secret 권한을 가진 단일 controller다.
현재 namespace를 다른 팀에 위임하지 않으므로 이 운영 경계를 수용한다.
외부와 fork PR의 코드는 이 클러스터에서 실행하지 않는다.
멀티테넌트로 바뀌면 prod와 non-prod controller 및 bootstrap principal을 분리한다.

## 계약

역할과 Store 수는 6개와 10개다.

| IAM role | Store가 있는 namespace | 허용 prefix |
|---|---|---|
| `tapple-secrets-prod` | `app`, `db` | `/tapple/prod/` |
| `tapple-secrets-dev` | `dev-app`, `dev-db` | `/tapple/dev/` |
| `tapple-secrets-preview` | `preview` | `/tapple/preview/` |
| `tapple-secrets-monitoring` | `monitoring` | `/tapple/platform/monitoring/` |
| `tapple-secrets-argocd` | `argocd` | `/tapple/platform/argocd/` |
| `tapple-secrets-shared` | `app`, `dev-app`, `preview` | `/tapple/shared/` |

source는 16개다.

| Secrets Manager source | target `namespace/Secret` |
|---|---|
| `/tapple/prod/app-secrets` | `app/app-secrets` |
| `/tapple/prod/postgres-app` | `app/postgres-app`, `db/postgres-app` |
| `/tapple/prod/postgres-secrets` | `db/postgres-secrets` |
| `/tapple/prod/postgres-readonly` | `db/postgres-readonly` |
| `/tapple/prod/backup-s3` | `db/backup-s3` |
| `/tapple/dev/app-secrets` | `dev-app/app-secrets` |
| `/tapple/dev/postgres-app` | `dev-app/postgres-app`, `dev-db/postgres-app` |
| `/tapple/dev/postgres-secrets` | `dev-db/postgres-secrets` |
| `/tapple/preview/app-secrets` | `preview/app-secrets` |
| `/tapple/preview/postgres-app` | `preview/postgres-app` |
| `/tapple/preview/postgres-preview-secrets` | `preview/postgres-preview-secrets` |
| `/tapple/shared/ghcr-pull` | 각 앱 namespace의 `ghcr-pull` 3개 |
| `/tapple/platform/monitoring/grafana-admin` | `monitoring/grafana-admin` |
| `/tapple/platform/monitoring/grafana-origin-tls` | `monitoring/grafana-origin-tls` |
| `/tapple/platform/monitoring/alertmanager-discord` | `monitoring/alertmanager-discord` |
| `/tapple/platform/argocd/preview-github-token` | `argocd/preview-github-token` |

`postgres-app` source는 `POSTGRES_PASSWORD` 하나만 가진다.
사용자명은 비밀이 아니며 values와 role bootstrap Job에 고정한다.
prod는 `tapple_app`을 사용한다.
dev는 `tapple_dev_app`을 사용한다.
preview는 `tapple_preview_app`을 공유한다.
관리자 Secret은 앱 namespace에 복제하지 않는다.

`postgres-secrets`는 `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`를 가진다.
`postgres-preview-secrets`는 `POSTGRES_USER`, `POSTGRES_PASSWORD`를 가진다.
`postgres-readonly`는 `RO_PASSWORD`를 가진다.
`backup-s3`는 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`, `S3_EXPECTED_BUCKET_OWNER`를 가진다.
`ghcr-pull.dockerconfigjson`은 base64가 아닌 완성된 Docker config JSON 원문이다.
origin TLS source의 `certificate`와 `private-key`는 `tls.crt`와 `tls.key`로 매핑된다.

앱 source의 전체 property 목록은 `charts/tapple-secrets/values.yaml`의 `appData`와 preview `data`가 정답이다.
문서에 같은 긴 목록을 복제하지 않는다.
ESO는 `data`에 없는 property를 가져오지 않는다.
`OTEL_TRACE_SAMPLE`은 시크릿이 아니며 세 환경의 Helm values에서 `1.0`으로 고정한다.

## 최초 구성

### IAM과 backup S3

```bash
BACKUP_BUCKET_NAME="${BACKUP_BUCKET_NAME:?전역에서 고유한 backup bucket 이름을 설정하세요}"
aws cloudformation deploy \
  --stack-name tapple-external-secrets-iam \
  --template-file infra/aws/external-secrets-iam.yaml \
  --region ap-northeast-2 \
  --capabilities CAPABILITY_NAMED_IAM

aws sts get-caller-identity --query Account --output text
```

AWS 계정 ID는 비밀이 아니다.
실제 12자리 ID를 `charts/tapple-secrets/values.yaml`에 커밋한다.
CloudFormation은 access key와 실제 Secret을 만들지 않는다.
bootstrap access key는 Console에서 한 개만 만들고 승인된 비밀 관리 도구에 바로 저장한다.

backup은 애플리케이션 media bucket과 분리한다.

```bash
aws cloudformation deploy \
  --stack-name tapple-postgres-backup-s3 \
  --template-file infra/aws/postgres-backup-s3.yaml \
  --region ap-northeast-2 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides BackupBucketName="$BACKUP_BUCKET_NAME"
```

bucket은 versioning, SSE-S3, public block, bucket-owner-enforced, TLS 강제를 사용한다.
current와 noncurrent object 보존 기간은 35일이다.
stack을 삭제해도 bucket은 Retain된다.
writer는 `postgres/prod/*`에 write만 할 수 있다.
writer는 기존 backup을 list, read, delete할 수 없다.
복구 담당자는 별도의 read-only AWS identity를 사용한다.

### JSON source 입력

Console의 JSON editor가 기본 경로다.
CLI를 쓰면 값을 명령행 인자에 쓰지 않는다.

```bash
secret_file="$(mktemp)"
chmod 600 "$secret_file"
trap 'rm -f "$secret_file"' EXIT
"${EDITOR:-vi}" "$secret_file"

# 새 source만 create한다.
aws secretsmanager create-secret \
  --name /tapple/prod/app-secrets \
  --region ap-northeast-2 \
  --secret-string "file://$secret_file"

# 기존 source는 새 version을 넣는다.
aws secretsmanager put-secret-value \
  --secret-id /tapple/prod/app-secrets \
  --region ap-northeast-2 \
  --secret-string "file://$secret_file"
```

두 명령을 같은 source에 연속 실행하지 않는다.
임시 파일은 source마다 새로 만든다.
과거 Git, 테스트 클러스터, Actions에 있던 값을 재사용하지 않는다.
최초 서비스 token은 previous와 current에 같은 값을 넣고 다음 회전부터 분리한다.

### canonical bootstrap

```bash
cd ansible
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp inventories/idc/hosts.example.yml inventories/idc/hosts.yml
ansible-playbook --syntax-check playbooks/bootstrap.yml
ansible-playbook --check --tags preflight playbooks/bootstrap.yml
ansible-playbook playbooks/bootstrap.yml
```

AWS key는 hidden prompt 또는 승인된 controller secret store로 주입한다.
inventory와 `--extra-vars`에 값을 넣지 않는다.
Ansible은 `no_log`와 stdin을 사용한다.
legacy shell installer는 없다.
`scripts/bootstrap-external-secrets-aws.sh`는 수동 secret-zero 도구이며 cluster installer가 아니다.

### 준비 확인

```bash
kubectl wait --for=condition=Ready secretstore --all -A --timeout=180s
kubectl wait --for=condition=Ready externalsecret --all -A --timeout=300s
test "$(kubectl get secretstore -A --no-headers | wc -l)" -eq 10
test "$(kubectl get externalsecret -A --no-headers | wc -l)" -eq 20
```

값은 출력하지 않는다.
source나 property가 빠지면 해당 ExternalSecret과 후속 Argo wave가 Ready가 되지 않는다.

## 일반 Secret 갱신

ESO refresh 주기는 한 시간이다.
`env`와 `envFrom` 값은 실행 중 프로세스에 자동 반영되지 않는다.

```bash
kubectl annotate externalsecret app-secrets -n app \
  external-secrets.io/force-sync="$(date +%s)" --overwrite
kubectl wait --for=condition=Ready externalsecret/app-secrets -n app --timeout=180s
kubectl rollout restart deployment/tapple-server -n app
kubectl rollout status deployment/tapple-server -n app --timeout=300s
```

기존 `Ready=True`만으로 새 version 반영을 판단하지 않는다.
force-sync 전후의 `.status.refreshTime`이 달라졌는지 확인한다.

## 앱 DB 비밀번호 회전

관리자 비밀번호와 앱 비밀번호는 분리돼 있다.
PostgreSQL image의 `POSTGRES_PASSWORD`는 최초 초기화에만 사용된다.
앱 비밀번호 회전은 `postgres-app` source, Kubernetes Secret, 실제 role, 앱 Pod를 모두 바꾼다.
단일 role 회전에는 짧은 연결 실패 구간이 있으므로 점검 창에서 실행한다.

prod 예시는 다음 순서다.

1. `/tapple/prod/postgres-app`의 `POSTGRES_PASSWORD`에 새 값을 넣는다.
2. `app`과 `db`의 `postgres-app` ExternalSecret을 같은 sync ID로 갱신한다.
3. 두 ExternalSecret의 `refreshTime` 변경을 확인한다.
4. 완료된 `postgres-app-role` Job을 지운다.
5. Argo CD가 Job을 다시 만들고 완료할 때까지 기다린다.
6. 앱을 즉시 재시작한다.

```bash
set -euo pipefail

before_app="$(kubectl get externalsecret postgres-app -n app \
  -o jsonpath='{.status.refreshTime}')"
before_db="$(kubectl get externalsecret postgres-app -n db \
  -o jsonpath='{.status.refreshTime}')"
SYNC_ID="$(date +%s)"
for ns in app db; do
  kubectl annotate externalsecret postgres-app -n "$ns" \
    external-secrets.io/force-sync="$SYNC_ID" --overwrite
done

wait_for_new_refresh() {
  namespace="$1"
  before="$2"
  attempts=0
  while :; do
    after="$(kubectl get externalsecret postgres-app -n "$namespace" \
      -o jsonpath='{.status.refreshTime}')"
    ready="$(kubectl get externalsecret postgres-app -n "$namespace" \
      -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
    if test "$ready" = True && test -n "$after" && test "$after" != "$before"; then
      break
    fi
    attempts=$((attempts + 1))
    test "$attempts" -lt 90 || exit 1
    sleep 2
  done
}
wait_for_new_refresh app "$before_app"
wait_for_new_refresh db "$before_db"

kubectl delete job/postgres-app-role -n db
kubectl wait --for=create job/postgres-app-role -n db --timeout=300s
kubectl wait --for=condition=Complete job/postgres-app-role -n db --timeout=300s
kubectl rollout restart deployment/tapple-server -n app
kubectl rollout status deployment/tapple-server -n app --timeout=300s
```

Job 전 실패하면 source를 직전 version으로 되돌리고 두 ExternalSecret을 다시 동기화한다.
Job 후 실패하면 직전 password version으로 같은 전체 순서를 다시 실행한다.
dev는 `/tapple/dev/postgres-app`, `dev-app`, `dev-db`, `tapple_dev_app`을 사용한다.
preview는 `/tapple/preview/postgres-app`, `preview`, `tapple_preview_app`을 사용한다.
preview role은 모든 trusted PR database가 공유하므로 한 PR을 상호 불신 경계로 보지 않는다.

관리자 role 비밀번호 회전은 별도 점검 작업이다.
앱은 관리자 Secret을 읽지 않으므로 앱 비밀번호와 같은 값으로 맞추지 않는다.

## PostgreSQL 관리자 password 회전

점검 창에서 환경별 `postgres-secrets` source의 `POSTGRES_PASSWORD`만 바꾼다.
active backup과 DB bootstrap Job이 없을 때 실행한다.
prod 앱은 `tapple_app`을 사용하므로 관리자 password 회전 때문에 재시작하지 않는다.

```bash
set -euo pipefail
test -z "$(kubectl get jobs -n db -l app.kubernetes.io/name=pg-backup \
  -o jsonpath='{range .items[*]}{.status.active}{"\n"}{end}' | awk '$1 + 0 > 0')"

before_refresh="$(kubectl get externalsecret postgres-secrets -n db \
  -o jsonpath='{.status.refreshTime}')"
kubectl annotate externalsecret postgres-secrets -n db \
  external-secrets.io/force-sync="$(date +%s)" --overwrite

attempts=0
while :; do
  after_refresh="$(kubectl get externalsecret postgres-secrets -n db \
    -o jsonpath='{.status.refreshTime}')"
  ready="$(kubectl get externalsecret postgres-secrets -n db \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
  if test "$ready" = True && test -n "$after_refresh" \
    && test "$after_refresh" != "$before_refresh"; then
    break
  fi
  attempts=$((attempts + 1))
  test "$attempts" -lt 90 || exit 1
  sleep 2
done

# prompt에 새 값을 두 번 붙여넣는다. 화면과 command argument에는 값이 남지 않는다.
kubectl exec -it -n db postgres-0 -- sh -ceu \
  'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\\password $POSTGRES_USER"'

# 새 Secret을 사용한 TCP admin 연결이 실제로 되는지 bootstrap Job으로 검증한다.
kubectl delete job/postgres-app-role -n db
kubectl wait --for=create job/postgres-app-role -n db --timeout=300s
kubectl wait --for=condition=Complete job/postgres-app-role -n db --timeout=300s
```

실제 role 변경 전에 실패하면 source를 직전 version으로 되돌린다.
role 변경 뒤 실패하면 local socket의 `\password`로 직전 값을 복원하고 source도 되돌린다.
dev는 `/tapple/dev/postgres-secrets`와 `dev-db`에 같은 절차를 쓴다.
preview는 `/tapple/preview/postgres-preview-secrets`와 `preview`에 같은 절차를 쓴다.
DB Pod를 재시작할 필요는 없다.

## readonly 비밀번호 회전

`/tapple/prod/postgres-readonly`의 `RO_PASSWORD`를 바꾼다.
Secret 갱신만으로 실제 role은 바뀌지 않는다.

```bash
kubectl annotate externalsecret postgres-readonly -n db \
  external-secrets.io/force-sync="$(date +%s)" --overwrite
kubectl wait --for=condition=Ready externalsecret/postgres-readonly -n db --timeout=180s
kubectl delete job/postgres-readonly-role -n db
kubectl wait --for=create job/postgres-readonly-role -n db --timeout=300s
kubectl wait --for=condition=Complete job/postgres-readonly-role -n db --timeout=300s
```

자세한 권한 검증은 [DB 접근 문서](../docs/db-access.md)에 있다.

## bootstrap key 회전

새 access key를 승인된 비밀 관리 도구에 저장한다.
Ansible을 다시 실행한다.
모든 SecretStore가 Ready인지 확인한다.
그 뒤에만 이전 key를 disable하고 삭제한다.
회전 주기와 담당자는 운영 캘린더에 둔다.

## backup writer key 회전

writer에는 정상 key를 한 개만 유지한다.
정규 backup의 최대 2시간 실행 창 밖에서 회전한다.
`concurrencyPolicy: Forbid`는 수동 Job과 정규 Job의 동시 실행을 막지 않는다.
AWS Console에서 새 writer key를 만들고 승인된 비밀 관리 도구에 저장한다.
`/tapple/prod/backup-s3`에서 `AWS_ACCESS_KEY_ID`와 `AWS_SECRET_ACCESS_KEY`만 새 값으로 바꾼다.
region, bucket, expected owner property는 보존한다.
이전 key는 아래 검증이 끝날 때까지 enable 상태로 둔다.

```bash
set -euo pipefail

before_refresh="$(kubectl get externalsecret backup-s3 -n db \
  -o jsonpath='{.status.refreshTime}')"
kubectl annotate externalsecret backup-s3 -n db \
  external-secrets.io/force-sync="$(date +%s)" --overwrite

attempts=0
while :; do
  after_refresh="$(kubectl get externalsecret backup-s3 -n db \
    -o jsonpath='{.status.refreshTime}')"
  ready="$(kubectl get externalsecret backup-s3 -n db \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
  if test "$ready" = True && test -n "$after_refresh" \
    && test "$after_refresh" != "$before_refresh"; then
    break
  fi
  attempts=$((attempts + 1))
  test "$attempts" -lt 90 || exit 1
  sleep 2
done

active_backups="$(kubectl get jobs -n db \
  -l app.kubernetes.io/name=pg-backup \
  -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.active}{"\n"}{end}' \
  | awk '$2 + 0 > 0 { print $1 }')"
test -z "$active_backups"

rotation_job="pg-backup-key-rotation-$(date -u +%Y%m%d%H%M%S)"
kubectl create job -n db --from=cronjob/pg-backup "$rotation_job"
kubectl wait --for=condition=Complete "job/$rotation_job" -n db --timeout=7200s
rotation_pod_uid="$(kubectl get pod -n db -l "job-name=$rotation_job" \
  -o jsonpath='{.items[?(@.status.phase=="Succeeded")].metadata.uid}')"
case "$rotation_pod_uid" in
  ????????-????-????-????-????????????) ;;
  *) exit 1 ;;
esac
```

클러스터 밖 read-only identity로 새 dump, checksum, complete marker를 확인한다.
marker가 `-${rotation_pod_uid}.dump.complete`로 끝나는지 확인한다.
[DR 런북](../runbooks/disaster-recovery.md)의 checksum, `pg_restore --list`, 임시 DB restore를 실행한다.
미완료 multipart upload가 없는지 확인한다.
그 뒤에만 이전 writer key를 disable한다.
다음 정규 backup 성공 뒤 이전 key를 삭제한다.
실패하면 이전 key를 enable하고 Secrets Manager를 이전 version으로 되돌린다.
read identity와 writer key를 같은 보관 항목으로 합치지 않는다.

## 보존과 폐기

ExternalSecret은 `CreateOrMerge`와 `Retain`을 사용한다.
ExternalSecret 삭제나 property 제거만으로 기존 Kubernetes Secret key는 사라지지 않는다.
폐기는 source, values 계약, target Secret, workload 참조를 함께 처리한다.
소비자를 먼저 제거한다.
target key 또는 target Secret을 명시적으로 지운다.
ExternalSecret을 force-sync한다.
값이 아닌 key 목록으로 결과를 확인한다.

이 전환은 운영 전이므로 과거 SealedSecret 값은 인수하지 않는다.
과거 sealing key와 관련 GitHub Actions secret의 원본 자격증명도 공급자에서 revoke한다.
저장소 UI에서 항목을 지우는 것만으로 원본 PAT나 OAuth secret은 무효화되지 않는다.

공개 저장소이므로 운영 전 GitHub secret scanning과 push protection을 즉시 활성화·확인한다.
Actions artifact와 로그에 값이 없는지 확인한다.
로컬 `.env.local`, dump, kubeconfig, 임시 JSON은 Git 밖에 둔다.
