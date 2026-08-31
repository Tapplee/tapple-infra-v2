# DB 접근

DB 운영은 플랫폼/인프라 관리자만 수행한다.
일반 maintainer에게 kubeconfig, ServiceAccount token, PostgreSQL 자격증명을 발급하지 않는다.
일반 maintainer는 승인된 Grafana 계정으로 관측한다.
PostgreSQL 5432는 인터넷에 노출하지 않는다.

## 계정 경계

| 환경 | database | 앱 role | 관리자 Secret |
|---|---|---|---|
| prod | `tapple` | `tapple_app` | `db/postgres-secrets` |
| dev | `tapple_dev` | `tapple_dev_app` | `dev-db/postgres-secrets` |
| preview | `tapple_pr<N>` | `tapple_preview_app` 공유 | `preview/postgres-preview-secrets` |

앱 role은 superuser, createdb, createrole, replication 권한이 없다.
앱 password는 환경별 `postgres-app` Secret에서 온다.
앱은 관리자 Secret을 읽지 않는다.
prod의 `tapple_ro`는 조회 전용 운영 role이다.
role과 grant는 Git의 idempotent Job이 만든다.

## 접속 원칙

관리자는 root-only kubeconfig를 복사하지 않는다.
IDC 노드에 SSH한 뒤 `sudo -n k3s kubectl`을 사용한다.
로컬 port-forward가 필요하면 승인된 관리자 kubeconfig와 제한된 6443 경로만 사용한다.
password는 승인된 비밀 관리 도구에서 psql prompt로 입력한다.
Secret 값을 `kubectl get -o yaml`, 셸 인자, history, 채팅에 출력하지 않는다.

prod readonly 접속 예시다.

```bash
kubectl port-forward -n db pod/postgres-0 15432:5432
psql 'host=127.0.0.1 port=15432 dbname=tapple user=tapple_ro sslmode=disable'
```

dev 점검 예시다.

```bash
kubectl port-forward -n dev-db pod/postgres-0 15433:5432
psql 'host=127.0.0.1 port=15433 dbname=tapple_dev user=tapple_dev_app sslmode=disable'
```

port-forward는 로컬 `127.0.0.1`에만 bind한다.
`--address 0.0.0.0`을 사용하지 않는다.
port-forward 트래픽은 일반 Pod-to-Pod NetworkPolicy 검증을 대신하지 않는다.

## 관리자 작업

관리자 role은 restore, role bootstrap 장애, 승인된 migration에만 사용한다.
평상시 조회는 `tapple_ro`를 사용한다.

노드 내부에서 값 노출 없이 관리자 psql을 여는 예시다.

```bash
sudo -n k3s kubectl exec -it -n db postgres-0 -- \
  sh -ceu 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

직접 만든 role과 grant는 다음 Argo sync에서 재현되지 않는다.
지속할 변경은 `app-role-job.yaml` 또는 `readonly-role-job.yaml`에 반영한다.
앱 schema owner는 prod `tapple_app`, dev `tapple_dev_app`이다.
restore는 [재해 복구 런북](../runbooks/disaster-recovery.md)의 `--role=tapple_app` 경로를 따른다.

## readonly password 회전

원본은 `/tapple/prod/postgres-readonly`의 `RO_PASSWORD`다.
AWS Console에서 JSON 전체를 확인하고 해당 property만 바꾼다.
Secret 내용을 CLI 인자에 넣지 않는다.

```bash
before_refresh="$(kubectl get externalsecret postgres-readonly -n db \
  -o jsonpath='{.status.refreshTime}')"
kubectl annotate externalsecret postgres-readonly -n db \
  external-secrets.io/force-sync="$(date +%s)" --overwrite

attempts=0
while :; do
  after_refresh="$(kubectl get externalsecret postgres-readonly -n db \
    -o jsonpath='{.status.refreshTime}')"
  ready="$(kubectl get externalsecret postgres-readonly -n db \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
  if test "$ready" = True && test -n "$after_refresh" \
    && test "$after_refresh" != "$before_refresh"; then
    break
  fi
  attempts=$((attempts + 1))
  test "$attempts" -lt 90 || exit 1
  sleep 2
done

kubectl delete job/postgres-readonly-role -n db
kubectl wait --for=create job/postgres-readonly-role -n db --timeout=300s
kubectl wait --for=condition=Complete job/postgres-readonly-role -n db --timeout=300s
```

ExternalSecret 갱신만으로 PostgreSQL role password는 바뀌지 않는다.
마지막 Job이 `ALTER ROLE`을 완료해야 회전이 끝난다.
새 password로 readonly 접속과 쓰기 거부를 확인한 뒤 이전 값을 폐기한다.

```sql
SELECT current_user, current_database();
SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';
CREATE TABLE must_fail(id integer);
```

마지막 문장은 권한 오류로 실패해야 한다.

## 앱 password 회전

앱 password 회전은 Secret과 실제 role과 Pod를 함께 바꾼다.
환경별 정확한 순서는 [시크릿 운영 문서](../secrets/README.md#앱-db-비밀번호-회전)에 있다.
관리자 password와 앱 password를 같은 값으로 맞추지 않는다.

## 점검

```bash
kubectl get pod -n db -l app.kubernetes.io/name=postgres
kubectl get job -n db postgres-app-role postgres-readonly-role
kubectl get networkpolicy -n db
kubectl logs -n db job/postgres-app-role
kubectl logs -n db job/postgres-readonly-role
```

`Connection refused`가 Job 시작 직후만 발생하면 NetworkPolicy endpoint 반영 지연일 수 있다.
bootstrap Job은 제한된 재시도와 deadline을 가진다.
반복 실패하면 Secret key 이름, Service DNS, NetworkPolicy selector, PostgreSQL readiness를 확인한다.
password 값 자체는 출력하지 않는다.
