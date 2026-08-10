# 팀원 DB 접속 가이드

k3s 클러스터의 **dev·prod PostgreSQL**에 붙는 방법. 로컬 개발 DB(`docker-compose-dev.yml`)는 이 문서 범위가 아니다.

> **먼저 알아둘 것**: 두 DB 모두 `ClusterIP`라 인터넷에서 직접 안 보인다. 접속은 `kubectl port-forward`로 터널을 뚫어 **내 컴퓨터의 localhost**를 클러스터 안 DB에 연결하는 방식이다. DBeaver·TablePlus·psql 등 평소 쓰는 도구를 그대로 쓴다.

| | dev | prod |
|---|---|---|
| DB명 | `tapple_dev` | `tapple` |
| 계정 | `tapple` (앱과 같은 계정) | `tapple_ro` (**조회 전용**) |
| 권한 | 읽기·쓰기·DDL | `SELECT`만 |
| 비밀번호 | 클러스터에서 직접 꺼낸다 (아래 3단계) | 운영자에게 요청 |
| 네임스페이스 | `dev-db` | `db` |

**왜 prod는 조회 전용인가**: 실데이터라 실수 한 번이 백업 복구로 이어진다. prod에 쓰기가 필요한 작업은 마이그레이션(Flyway)으로 올리거나 운영자에게 요청한다.

---

## 1. 준비 (한 번만)

**kubectl 설치**
```bash
brew install kubectl        # macOS
```

**kubeconfig 받기** — 운영자에게 요청한다. 운영자는 노드에서 이렇게 발급한다:
```bash
./scripts/gen-team-kubeconfig.sh <노드IP> > 이름-kubeconfig.yaml
```
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

**비밀번호 꺼내기** (새 터미널)
```bash
kubectl get secret postgres-secrets -n dev-db -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d; echo
```

**붙기**
```bash
psql "postgresql://tapple@localhost:15432/tapple_dev"
```
GUI 도구라면:

| 항목 | 값 |
|---|---|
| Host | `localhost` |
| Port | `15432` |
| Database | `tapple_dev` |
| User | `tapple` |
| Password | 위에서 꺼낸 값 |
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

## 4. 자주 막히는 것

**`error: unable to listen on any of the requested ports`**
그 포트를 이미 쓰고 있다. 다른 번호로 바꾸거나 범인을 찾는다:
```bash
lsof -iTCP:15432 -sTCP:LISTEN
```

**`Forbidden: User "system:serviceaccount:team-access:teammate" cannot ...`**
권한 밖의 일을 시도했거나(예: `kubectl exec`, prod 시크릿 읽기) 토큰이 만료됐다. 의도한 작업이 막혔다면 운영자에게 말한다 — Role을 넓혀야 하는 경우일 수 있다.

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
ssh root@<노드IP>
cd /path/to/tapple-infra-v2
./scripts/gen-team-kubeconfig.sh <노드IP> 2160h > 이름-kubeconfig.yaml   # 90일
```
파일은 안전한 경로로 전달한다(1Password 등). Slack·카톡 평문 전송은 피한다.

**회수** — 토큰은 만료로 자동 회수되지만 즉시 끊어야 하면 SA를 다시 만든다. 발급된 모든 토큰이 한 번에 무효화된다:
```bash
kubectl delete sa teammate -n team-access
# ArgoCD selfHeal 이 곧 되살리므로, 되살아난 뒤 새로 발급하면 이전 토큰은 전부 무효
```

**권한 범위 변경** — `manifests/cluster/team-access.yaml`을 고쳐 커밋한다. ArgoCD가 반영한다. `kubectl edit`로 직접 고치면 selfHeal이 되돌린다.

**prod 읽기전용 계정** — `manifests/postgres/readonly-role-job.yaml`이 PostSync 훅으로 만든다. 비밀번호는 `postgres-readonly` SealedSecret에 있고 이렇게 꺼낸다:
```bash
kubectl get secret postgres-readonly -n db -o jsonpath='{.data.RO_PASSWORD}' | base64 -d; echo
```
비밀번호를 바꾸려면 새 값으로 다시 씰링해 커밋한다 — Job이 다음 sync에서 `ALTER ROLE`로 맞춘다.

**권한 확인**
```bash
kubectl auth can-i --as=system:serviceaccount:team-access:teammate create pods/portforward -n dev-db   # yes
kubectl auth can-i --as=system:serviceaccount:team-access:teammate delete pods -n db                   # no
kubectl auth can-i --as=system:serviceaccount:team-access:teammate get secrets -n db                   # no
```
