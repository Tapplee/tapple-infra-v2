# 팀원 DB 접속 가이드

k3s 클러스터의 **dev·prod PostgreSQL**에 붙는 방법. 로컬 개발 DB(`docker-compose-dev.yml`)는 이 문서 범위가 아니다.

> **먼저 알아둘 것**: 두 DB 모두 `ClusterIP`라 인터넷에서 직접 안 보인다. 접속은 `kubectl port-forward`로 터널을 뚫어 **내 컴퓨터의 localhost**를 클러스터 안 DB에 연결하는 방식이다. DBeaver·TablePlus·psql 등 평소 쓰는 도구를 그대로 쓴다.

| | dev | prod | PR 프리뷰 |
|---|---|---|---|
| DB명 | `tapple_dev` | `tapple` | `tapple_pr<PR번호>` |
| 계정 | `tapple` (앱과 같은 계정) | `tapple_ro` (**조회 전용**) | `tapple` |
| 권한 | 읽기·쓰기·DDL | `SELECT`만 | 읽기·쓰기·DDL |
| 비밀번호 | Secret에서 psql에 직접 전달(표시 안 함) | 운영자에게 요청 | Secret에서 psql에 직접 전달(표시 안 함) |
| 네임스페이스 | `dev-db` | `db` | `preview` |
| 포트(권장) | 15432 | 15433 | 15434 |

**왜 prod는 조회 전용인가**: 실데이터라 실수 한 번이 백업 복구로 이어진다. prod에 쓰기가 필요한 작업은 마이그레이션(Flyway)으로 올리거나 운영자에게 요청한다.

---

## 1. 준비 (한 번만)

**kubectl 설치**
```bash
brew install kubectl        # macOS
```

**kubeconfig 받기** — 운영자에게 요청한다. 운영자는 노드에서 이렇게 발급한다:
```bash
./scripts/gen-team-kubeconfig.sh <IDC_NODE_IP> > 이름-kubeconfig.yaml
```

API `6443`은 인터넷 전체에 열려 있지 않다. 운영자는 발급 전에 팀원의 고정 egress
또는 VPN CIDR를 `ansible/inventories/idc/hosts.yml`의 `common_k3s_api_cidrs`에 넣고
playbook을 다시 실행한다. 개인 IP가 자주 바뀐다면 `/32`를 계속 추가하지 말고 VPN
egress 하나로 모은다. `0.0.0.0/0`은 허용하지 않는다.

받은 파일을 두고 셸에서 지정한다:
```bash
mkdir -p ~/.kube && mv ~/Downloads/이름-kubeconfig.yaml ~/.kube/tapple.yaml
chmod 600 ~/.kube/tapple.yaml
export KUBECONFIG=~/.kube/tapple.yaml     # 매번. 영구히 하려면 ~/.zshrc 에 추가
```

**확인**
```bash
kubectl get pods -n dev-db
# NAME         READY   STATUS    RESTARTS   AGE
# postgres-0   1/1     Running   0          3h
```
`Forbidden`이 나오면 kubeconfig가 안 잡혔거나 만료된 것이다. 유효기간은 기본 90일.

> 이 kubeconfig로 할 수 있는 건 dev·prod DB 조회와 port-forward뿐이다. 파드 삭제·컨테이너 접속·다른 네임스페이스는 막혀 있다 — 잘못 눌러서 뭘 망가뜨릴 수 없으니 마음 편히 써도 된다.

---

## 2. dev DB 접속

**터널 열기** (이 터미널은 접속하는 동안 계속 열어둔다)
```bash
kubectl port-forward -n dev-db svc/postgres 15432:5432
# Forwarding from 127.0.0.1:15432 -> 5432
```
로컬 5432는 이미 쓰고 있을 가능성이 높아 **15432**로 받았다.

**붙기** (새 터미널) — 비밀번호는 명령 치환 결과로 psql 프로세스에만 전달하며
터미널이나 셸 기록에 출력하지 않는다.

```bash
PGPASSWORD="$(kubectl get secret postgres-secrets -n dev-db -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)" psql --host=localhost --port=15432 --username=tapple --dbname=tapple_dev
```
GUI 도구라면:

| 항목 | 값 |
|---|---|
| Host | `localhost` |
| Port | `15432` |
| Database | `tapple_dev` |
| User | `tapple` |
| Password | 운영자가 승인된 비밀 관리 도구로 전달한 값 |
| SSL | 끔 (터널 안이라 이미 암호화돼 있다) |

터널을 닫으면(`Ctrl+C`) 연결도 끊긴다. GUI가 "connection lost"를 띄우면 터널이 죽은 것이니 다시 열면 된다.

---

## 3. prod DB 접속 (조회 전용)

```bash
kubectl port-forward -n db svc/postgres 15433:5432
```
포트를 dev와 다르게(**15433**) 잡는 걸 권한다 — 둘을 같이 열어두고 헷갈려서 prod에 쿼리를 던지는 사고를 막는다.

```bash
psql "postgresql://tapple_ro@localhost:15433/tapple"
```
비밀번호는 운영자에게 요청한다. dev와 달리 시크릿을 직접 못 읽는다(권한 없음).

쓰기를 시도하면 이렇게 막힌다:
```
ERROR:  permission denied for table members
```
정상이다. 버그가 아니다.

---

## 3-2. PR 프리뷰 DB 접속

PR 마다 database 가 나뉘고 postgres 인스턴스 한 대를 공유한다. **자기 PR 번호의 database 로 붙는다.**

```bash
kubectl port-forward -n preview svc/postgres-preview 15434:5432
```

```bash
# PR #27의 database. 비밀번호는 출력하지 않고 psql 프로세스에만 전달한다.
PGPASSWORD="$(kubectl get secret postgres-preview-secrets -n preview -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)" psql --host=localhost --port=15434 --username=tapple --dbname=tapple_pr27
```

| 항목 | 값 |
|---|---|
| Host / Port | `localhost` / `15434` |
| Database | `tapple_pr<PR번호>` |
| User | `tapple` |
| Password | 운영자가 승인된 비밀 관리 도구로 전달한 값 |

**dev·prod 와 달리 쓰기가 열려 있다.** 프리뷰는 버려도 되는 환경이라 마이그레이션 시험이나
데이터 조작을 마음껏 해도 된다. 다른 PR 의 database 는 별개라 영향이 없다.

`database "tapple_pr27" does not exist` 가 나오면 그 PR 에 `preview` 라벨이 없거나
환경이 아직 뜨는 중이다. 라벨을 붙이고 3~5분 뒤 다시 시도한다.

**앱 로그도 볼 수 있다** — 자기 PR 이 왜 안 뜨는지 확인하는 용도다.

```bash
kubectl logs -n preview -l app.kubernetes.io/instance=tapple-preview-27 --tail=50
```

> PR 을 닫으면 앱·Service·Ingress 는 사라지지만 **database 는 남는다.** 주 1회 도는
> 정리 CronJob 이 7일 넘게 접속이 없는 것을 지운다. 닫은 직후에도 데이터를 확인할 수 있다.

## 4. 자주 막히는 것

**`error: unable to listen on any of the requested ports`**
그 포트를 이미 쓰고 있다. 다른 번호로 바꾸거나 범인을 찾는다:
```bash
lsof -iTCP:15432 -sTCP:LISTEN
```

**`Forbidden: User "system:serviceaccount:team-access:teammate" cannot ...`**
권한 밖의 일을 시도했거나(예: `kubectl exec`, prod 시크릿 읽기) 토큰이 만료됐다. 의도한 작업이 막혔다면 운영자에게 말한다 — Role을 넓혀야 하는 경우일 수 있다.

**`i/o timeout` 또는 `connection timed out` (kubectl 자체가 연결되지 않음)**
현재 egress IP가 방화벽 allowlist에 없을 가능성이 높다. 운영자에게 현재 공인 IP나
VPN 접속 상태를 확인해 달라고 한다. 인증 오류와 달리 이 경우 API 응답 자체가 없다.

**`connection refused` (터널은 열려 있는데)**
DB 파드가 재기동 중일 수 있다.
```bash
kubectl get pod -n dev-db
```
`Running`이 아니면 잠시 기다린다. `CreateContainerConfigError`면 시크릿 문제라 운영자 몫이다.

**터널이 자꾸 끊긴다**
`port-forward`는 원래 오래 붙어 있으면 끊긴다. 끊길 때마다 다시 여는 게 정상 사용법이고, 귀찮으면 재접속 루프를 쓴다:
```bash
while true; do kubectl port-forward -n dev-db svc/postgres 15432:5432; sleep 2; done
```

---

## 5. 스키마를 바꿔야 할 때

DB에 직접 `ALTER TABLE`을 치지 않는다. dev에서도 하지 않는 게 좋다 — 다음 배포에서 Flyway가 덮거나 충돌한다.

스키마 변경은 **마이그레이션 파일**로 한다:
```
tapple-be/infrastructure/src/main/resources/db/migration/V<다음번호>__설명.sql
```
현재 V9까지 있다. `out-of-order: true`라 번호가 건너뛰어도 적용되지만, PR에서 번호 충돌은 꼭 확인한다.

---

## 6. 운영자용 — 발급과 회수

**kubeconfig 발급**
```bash
ssh root@<IDC_NODE_IP>
cd /path/to/tapple-infra-v2
./scripts/gen-team-kubeconfig.sh <IDC_NODE_IP> 2160h > 이름-kubeconfig.yaml   # 90일
```
파일은 안전한 경로로 전달한다(1Password 등). Slack·카톡 평문 전송은 피한다.

**회수** — 토큰은 만료로 자동 회수되지만 즉시 끊어야 하면 SA를 다시 만든다. 발급된 모든 토큰이 한 번에 무효화된다:
```bash
kubectl delete sa teammate -n team-access
# ArgoCD selfHeal 이 곧 되살리므로, 되살아난 뒤 새로 발급하면 이전 토큰은 전부 무효
```

더 이상 쓰지 않는 개인/VPN CIDR은 inventory에서 제거하고 playbook을 다시 실행한다.
전용 노드의 UFW 인바운드 allow는 Ansible이 전부 소유하므로, 원하는 규칙을 먼저 보장한 뒤
inventory에 없는 과거 규칙을 자동으로 제거하고 최종 상태를 검증한다.

```bash
cd /path/to/tapple-infra-v2/ansible
ansible-playbook playbooks/bootstrap.yml
ufw status verbose
```

**권한 범위 변경** — `manifests/cluster/team-access.yaml`을 고쳐 커밋한다. ArgoCD가 반영한다. `kubectl edit`로 직접 고치면 selfHeal이 되돌린다.

**prod 읽기전용 계정** — `manifests/postgres/readonly-role-job.yaml`(추적 Job)이 만든다. `\gexec`로 idempotent하니 몇 번 돌아도 같고, 비밀번호는 매번 시크릿 값으로 동기화된다.

> PostSync 훅으로도 만들어봤지만 이 클러스터에서 실행되지 않았다 — 컨트롤러가 매 sync 계획에는 `PostSync/0 hook batch/Job:db/postgres-readonly-role`로 넣으면서 실행 단계에서 `skipHooks:true`로 건너뛴다. 그래서 평범한 Job으로 되돌렸고, 그 경로는 롤을 완전히 지운 상태에서 재생성까지 실측했다.

비밀번호 원본은 AWS Secrets Manager의 JSON Secret
`/tapple/prod/postgres-readonly`이고 property는 `RO_PASSWORD`다. 팀원에게는
승인된 비밀 관리 도구로만 전달하고 Kubernetes Secret이나 Secrets Manager
값을 터미널에 출력하지 않는다.

읽기전용 비밀번호를 바꿀 때는 AWS Console에서 위 JSON Secret의
`RO_PASSWORD`만 갱신한다. 다른 property를 지우지 않도록 JSON 전체를 확인한 뒤
ExternalSecret을 즉시 동기화하고, 완료된 Job을 지워 ArgoCD가 새 Secret으로 다시
실행하게 한다. 비밀 JSON 내용을 CLI의 `--secret-string` 인자에 직접 넣지 않는다.

```bash
kubectl annotate externalsecret postgres-readonly -n db \
  external-secrets.io/force-sync="$(date +%s)" --overwrite
kubectl wait --for=condition=Ready externalsecret/postgres-readonly \
  -n db --timeout=180s
kubectl get externalsecret postgres-readonly -n db \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[0].status,REFRESHED:.status.refreshTime'

kubectl delete job postgres-readonly-role -n db
kubectl wait --for=create job/postgres-readonly-role -n db --timeout=180s
kubectl wait --for=condition=Complete job/postgres-readonly-role -n db --timeout=180s
```

Secret 갱신만으로 PostgreSQL role 비밀번호는 바뀌지 않는다. 마지막 Job 재실행이
`ALTER ROLE`을 수행해야 회전이 끝난다.

### 주 DB 계정 비밀번호 회전

`POSTGRES_PASSWORD`는 컨테이너 최초 초기화에만 쓰인다. Secrets Manager와 Kubernetes Secret만
바꾸거나 PostgreSQL Pod를 재시작해서는 기존 role 비밀번호가 바뀌지 않는다. 점검 창에서
다음 순서를 끊지 않고 수행한다.

1. 비밀 관리 도구에서 새 비밀번호를 만들고 AWS Console에서 다음 두 JSON
   Secret의 `POSTGRES_PASSWORD` property를 **같은 값으로 모두** 갱신한다.

   - `/tapple/prod/postgres-secrets`
   - `/tapple/prod/app-secrets`

   하나만 바꾸면 DB와 앱이 서로 다른 비밀번호를 읽어 장애가 난다. AWS Console의
   JSON editor를 쓰거나, 반드시 `umask 077`로 만든 임시 JSON 파일을
   `--secret-string file://<임시파일>`로 읽히고 즉시 삭제한다. 비밀 JSON을 CLI
   인자나 Git에 넣지 않는다.
2. DB와 앱 ExternalSecret을 모두 강제 동기화하고 refresh 시간이 갱신됐는지 확인한다.

   ```bash
   SYNC_ID="$(date +%s)"
   kubectl annotate externalsecret postgres-secrets -n db \
     external-secrets.io/force-sync="$SYNC_ID" --overwrite
   kubectl annotate externalsecret app-secrets -n app \
     external-secrets.io/force-sync="$SYNC_ID" --overwrite
   kubectl wait --for=condition=Ready externalsecret/postgres-secrets \
     -n db --timeout=180s
   kubectl wait --for=condition=Ready externalsecret/app-secrets \
     -n app --timeout=180s
   kubectl get externalsecret postgres-secrets -n db \
     -o custom-columns='NAME:.metadata.name,READY:.status.conditions[0].status,REFRESHED:.status.refreshTime'
   kubectl get externalsecret app-secrets -n app \
     -o custom-columns='NAME:.metadata.name,READY:.status.conditions[0].status,REFRESHED:.status.refreshTime'
   ```

3. 기존 PostgreSQL Pod의 로컬 소켓으로 접속해 실제 role 비밀번호를 바꾼다. 아래
   `\password` 프롬프트에 비밀 관리 도구의 새 값을 두 번 붙여넣는다. 입력은 화면에
   표시되지 않고 명령 인자에도 들어가지 않는다.

   ```bash
   kubectl exec -it -n db postgres-0 -- sh -ceu \
     'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\\password $POSTGRES_USER"'
   ```

4. 즉시 앱을 재시작해 새 환경변수를 읽게 하고 헬스체크를 확인한다. PostgreSQL Pod는
   재시작할 필요가 없다.

   ```bash
   kubectl rollout restart deployment/tapple-server -n app
   kubectl rollout status deployment/tapple-server -n app --timeout=300s
   curl -fsS https://api.example.invalid/actuator/health
   ```

`\password` 전에 실패하면 앱을 재시작하지 말고 두 Secrets Manager Secret을 모두
직전 version으로 되돌린 뒤 ExternalSecret을 다시 동기화한다. role 변경 뒤에는
직전 비밀번호로 되돌리는 경우도 같은 순서로 `\password`와 앱 rollout까지 완료해야
한다. dev는 `/tapple/dev/postgres-secrets`와 `/tapple/dev/app-secrets`, `dev-db`,
`dev-app`에 같은 절차를 적용한다.

**권한 확인**
```bash
SA=system:serviceaccount:team-access:teammate

# 서브리소스는 --subresource 로 물어야 한다.
# kubectl 1.36 에서 `create pods/portforward` 슬래시 형태는 권한이 있어도 no 로 답한다 — 함정.
kubectl auth can-i --as=$SA create pods --subresource=portforward -n dev-db   # yes
kubectl auth can-i --as=$SA get pods -n dev-db                                # yes
kubectl auth can-i --as=$SA get secret/postgres-secrets -n dev-db             # yes

kubectl auth can-i --as=$SA delete pods -n db                                 # no
kubectl auth can-i --as=$SA create pods --subresource=exec -n db              # no
kubectl auth can-i --as=$SA get secrets -n db                                 # no
kubectl auth can-i --as=$SA list secrets -n dev-db                            # no (get 만 줬다)
kubectl auth can-i --as=$SA get pods -n argocd                                # no

# 프리뷰
kubectl auth can-i --as=$SA create pods --subresource=portforward -n preview  # yes
kubectl auth can-i --as=$SA get secret/postgres-preview-secrets -n preview    # yes
kubectl auth can-i --as=$SA delete pods -n preview                            # no
```

**실측 기록 (2026-08-10)** — 위 절차를 처음부터 끝까지 밟아 확인한 결과:

| 검증 | 결과 |
|---|---|
| 발급된 kubeconfig 로 `kubectl get pods -n dev-db` | 성공 |
| `port-forward` 후 dev DB 접속 (`tapple`/`tapple_dev`) | 성공 |
| prod 시크릿 읽기 | `Forbidden` (의도대로 차단) |
| `tapple_ro` 로 쓰기 시도 | 거부 |
| 롤을 완전히 지운 뒤 ArgoCD sync | Job 이 자동 재생성 |

`tapple_ro`의 `GRANT SELECT ON ALL TABLES`는 **현재 테이블이 0개라 아무것도 안 잡았다** — 앱이 아직 배포되지 않아 Flyway가 안 돌았기 때문이다. 대신 `ALTER DEFAULT PRIVILEGES`가 등록돼 있어(`pg_default_acl`에 `tapple_ro=r/tapple`) Flyway가 만드는 테이블은 **자동으로** SELECT가 붙는다. 앱 배포 후 별도 GRANT 작업이 필요하지 않다.
