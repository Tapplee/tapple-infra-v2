# 재해 복구 런북

노드 소실 시 전체 재구축 절차. **Phase 9에서 리허설 1회 필수** — 리허설 전까지 이 문서는 초안.

`10분`은 교체 노드와 네트워크가 이미 준비된 뒤 Ansible/GitOps로 소프트웨어를
복구하는 구간의 목표일 뿐이다. 단일 물리 서버의 교체·재설치·원격 손 대응 시간은
IDC 공급자에 달려 있어 전체 RTO는 수시간이 될 수 있다. 실제 RTO는 첫 복구 리허설에서
`노드 준비`, `클러스터 수렴`, `DB restore`를 나눠 측정한 뒤 확정한다.

## 전제

- 오브젝트 스토리지에 있어야 하는 것: ① 최신 pg_dump ② (선택) k3s sqlite 스냅샷
- AWS에 남아 있어야 하는 것: `/tapple/` 이름의 Secrets Manager JSON Secret,
  `tapple-external-secrets-iam` CloudFormation stack, 환경별 `tapple-secrets-*` IAM Role
- 운영자 비밀 관리 도구에 있어야 하는 것: `tapple-external-secrets-bootstrap` access key.
  이 값은 백업 파일이나 Git에 복사하지 않는다. 유실했으면 기존 값을 찾지 말고 새 access key를 발급한다.
- Ansible controller에 있어야 하는 것: Ansible, 이 레포 복사본, 검증한 IDC 노드
  SSH host key, SSH private key, IDC 콘솔 접근 수단, AWS 운영 권한
- 아래 원격 검증에 쓰는 `IDC_SSH_USER`는 root 또는 passwordless sudo 가능 계정이어야 한다.
  bootstrap에서 `--ask-become-pass`를 썼다면 검증은 root로 하거나 해당 계정의 제한된
  passwordless `k3s` 실행 권한을 먼저 준비한다. restore는 stdin을 써서 sudo 암호를 받을 수 없다.
- `charts/tapple-secrets/values.yaml`의 AWS 계정 ID가 실제 계정으로 커밋되어 있어야 한다.

## 절차

```bash
set -euo pipefail

# 1. AWS의 시크릿 원본과 IAM이 살아 있는지 확인한다. Secret value는 조회하지 않는다.
aws cloudformation describe-stacks \
  --stack-name tapple-external-secrets-iam \
  --region ap-northeast-2 \
  --query 'Stacks[0].StackStatus' --output text
aws secretsmanager list-secrets \
  --region ap-northeast-2 \
  --filters Key=name,Values=/tapple/ \
  --query 'SecretList[].Name' --output text

# 2. IDC 콘솔에서 물리 노드를 재설치한다.
#    x86_64 Ubuntu, 공인 IP, 키 기반 SSH와 sudo(또는 root)가 Ansible 최초 접속 조건이다.
IDC_NODE_HOST="${IDC_NODE_HOST:?IDC_NODE_HOST에 복구한 IDC 노드 IP를 설정하세요}"
IDC_SSH_USER="${IDC_SSH_USER:?IDC_SSH_USER에 inventory의 SSH 사용자를 설정하세요}"
PROD_API_URL="${PROD_API_URL:?PROD_API_URL에 실제 운영 API origin을 설정하세요}"

# 3. 콘솔에 표시된 SSH host key fingerprint를 다른 경로로 확인한 뒤
#    controller의 known_hosts에 등록한다. 확인 안 된 ssh-keyscan 결과를 무조건 신뢰하지 않는다.

# 4. 실제 inventory를 만들고 IDC IP·SSH 사용자·관리자 CIDR를 검토한 뒤
#    bootstrap_confirm=true로 바꾼다. hosts.yml은 .gitignore 대상이다.
cd /safe/path/tapple-infra-v2/ansible
cp inventories/idc/hosts.example.yml inventories/idc/hosts.yml
${EDITOR:-vi} inventories/idc/hosts.yml

# 5. playbook을 실행한다. bootstrap access key 두 값은 echo 없는 prompt에만
#    붙여넣는다. --extra-vars·inventory·환경변수·명령행 인자에 넣지 않는다.
ansible-playbook playbooks/bootstrap.yml

# 6. playbook 정상 종료는 이미 root Synced+Healthy를 뜻한다. 노드의 root-only kubeconfig를
#    복사하지 말고 SSH+sudo로 계약 개수와 ESO 준비 상태를 한 번 더 확인한다.
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" '
  set -eu
  test "$(sudo -n k3s kubectl get secretstore -A --no-headers | wc -l)" -eq 10
  test "$(sudo -n k3s kubectl get externalsecret -A --no-headers | wc -l)" -eq 15
'
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl rollout status deployment/external-secrets -n external-secrets --timeout=300s'
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl wait --for=condition=Ready secretstore --all -A --timeout=180s'
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl wait --for=condition=Ready externalsecret --all -A --timeout=300s'
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" 'sudo -n k3s kubectl get secretstore,externalsecret -A'

# 7. ArgoCD custom health gate가
#    external-secrets → SecretStore/ExternalSecret → postgres → app 순서로 수렴시킨다.
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" 'sudo -n k3s kubectl get applications -n argocd'

# 8. root와 prod DB·앱 Application의 auto-sync를 잠시 끄고 앱을 0개로 만든다.
#    DNS 컷오버 전이어도 기동한 앱의 pool/background job이 DB를 잡을 수 있으므로
#    실행 중인 앱 위에 restore하지 않는다. 새 SSH/UFW 상태는 유지한다.
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  "sudo -n k3s kubectl patch application root -n argocd --type=merge -p '{\"spec\":{\"syncPolicy\":{\"automated\":null}}}'"
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  "sudo -n k3s kubectl patch application postgres -n argocd --type=merge -p '{\"spec\":{\"syncPolicy\":{\"automated\":null}}}'"
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  "sudo -n k3s kubectl patch application tapple-server -n argocd --type=merge -p '{\"spec\":{\"syncPolicy\":{\"automated\":null}}}'"
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl scale deployment/tapple-server -n app --replicas=0'
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl wait --for=delete pod -n app -l app.kubernetes.io/name=tapple-server --timeout=180s'
# restore 중간 상태를 새 백업으로 오인하지 않도록 예약 실행과 남은 backup Job도 멈춘다.
# 마지막 단계에서 postgres Application을 다시 동기화하면 Git의 desired suspend 값으로 복귀한다.
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl patch cronjob/pg-backup -n db --type=merge -p '\''{"spec":{"suspend":true}}'\'''
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl delete job -n db -l app.kubernetes.io/name=pg-backup --ignore-not-found --wait=true --timeout=180s'

# 9. PostgreSQL이 준비된 뒤 기존 DB를 강제로 끊고 빈 DB로 다시 만든 다음 복원한다.
#    dump는 SSH stdin으로만 넘기고 IDC 노드 디스크에 임시 복사하지 않는다.
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl rollout status statefulset/postgres -n db --timeout=300s'
BACKUP_FILE='/안전한/경로/taple-latest.dump'
BACKUP_SHA256_FILE="${BACKUP_FILE}.sha256"
test -s "$BACKUP_FILE"
test -r "$BACKUP_SHA256_FILE"
# 두 파일은 오브젝트 스토리지에서 version ID를 확인해 같은 백업 실행의 것으로 내려받는다.
# 버킷의 versioning/보존 정책이 켜져 있지 않다면 컷오버 전에 먼저 구성한다.
EXPECTED_BACKUP_SHA256="$(awk 'NR == 1 { print $1 }' "$BACKUP_SHA256_FILE")"
ACTUAL_BACKUP_SHA256="$(python3 - "$BACKUP_FILE" <<'PY'
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
)"
test "${#EXPECTED_BACKUP_SHA256}" -eq 64
test "$ACTUAL_BACKUP_SHA256" = "$EXPECTED_BACKUP_SHA256"
# custom-format dump가 끝까지 파싱되는지 DB 삭제 전에 PostgreSQL 16 도구로 검증한다.
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl exec -i -n db postgres-0 -- pg_restore --list >/dev/null' \
  < "$BACKUP_FILE"
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl exec -n db postgres-0 -- sh -ceu '\''dropdb --if-exists --force -U "$POSTGRES_USER" "$POSTGRES_DB"; createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'\'''
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl exec -i -n db postgres-0 -- sh -ceu '\''pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"'\''' \
  < "$BACKUP_FILE"

# restore가 끝났으므로 postgres auto-sync를 먼저 복구한다. 이 sync가 CronJob을 Git의
# desired suspend 값으로 되돌리고, restore로 바뀐 DB-local grant Job도 다시 만든다.
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  "sudo -n k3s kubectl patch application postgres -n argocd --type=merge -p '{\"spec\":{\"syncPolicy\":{\"automated\":{\"prune\":true,\"selfHeal\":true}}}}'"
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl delete job/postgres-readonly-role -n db --ignore-not-found'
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" '
  set -eu
  sudo -n k3s kubectl annotate application/postgres -n argocd \
    argocd.argoproj.io/refresh=hard --overwrite
  attempts=0
  while test -n "$(sudo -n k3s kubectl get application/postgres -n argocd \
    -o jsonpath="{.metadata.annotations.argocd\\.argoproj\\.io/refresh}")"; do
    attempts=$((attempts + 1))
    test "$attempts" -lt 300
    sleep 2
  done
'
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl wait --for=create job/postgres-readonly-role -n db --timeout=300s'
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl wait --for=condition=Complete job/postgres-readonly-role -n db --timeout=300s'
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  "sudo -n k3s kubectl wait application/postgres -n argocd --for=jsonpath='{.status.sync.status}'=Synced --timeout=600s"
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  "sudo -n k3s kubectl wait application/postgres -n argocd --for=jsonpath='{.status.health.status}'=Healthy --timeout=600s"

# 10. restore 성공 뒤 prod 앱과 root auto-sync를 다시 켠다. 실패했다면 이 단계로
#     넘어가지 말고 앱을 0개로 둔 채 원인을 수정하고 9번부터 다시 수행한다.
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  "sudo -n k3s kubectl patch application tapple-server -n argocd --type=merge -p '{\"spec\":{\"syncPolicy\":{\"automated\":{\"prune\":true,\"selfHeal\":true}}}}'"
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  "sudo -n k3s kubectl patch application root -n argocd --type=merge -p '{\"spec\":{\"syncPolicy\":{\"automated\":{\"selfHeal\":true}}}}'"
# hard refresh annotation은 Argo CD v3.5.0이 현재 Git과 live 상태를 비교한 뒤 제거한다.
# 제거를 본 후에 sync를 기다려야 scale=0 이전의 stale Synced 상태를 통과하지 않는다.
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" '
  set -eu
  sudo -n k3s kubectl annotate application/tapple-server -n argocd \
    argocd.argoproj.io/refresh=hard --overwrite
  attempts=0
  while test -n "$(sudo -n k3s kubectl get application/tapple-server -n argocd \
    -o jsonpath="{.metadata.annotations.argocd\\.argoproj\\.io/refresh}")"; do
    attempts=$((attempts + 1))
    test "$attempts" -lt 300
    sleep 2
  done
'
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  "sudo -n k3s kubectl wait application/tapple-server -n argocd --for=jsonpath='{.status.sync.status}'=Synced --timeout=600s"
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  "sudo -n k3s kubectl wait application/tapple-server -n argocd --for=jsonpath='{.status.health.status}'=Healthy --timeout=600s"
ssh "${IDC_SSH_USER}@${IDC_NODE_HOST}" \
  'sudo -n k3s kubectl rollout status deployment/tapple-server -n app --timeout=600s'

# 11. Cloudflare A 레코드가 새 IDC 노드 IP인지 확인 → 앱 헬스체크
#    grafana-k3s 레코드도 같이 바꿀 것 (docs/monitoring-access.md)
curl -fsS "${PROD_API_URL%/}/actuator/health"

# 12. Grafana 팀원 계정 재등록
#    사용자 목록은 Grafana 의 sqlite(PVC)에 있어 Git 이 복원해주지 않는다.
#    대시보드·데이터소스는 자동 복원되므로 사람만 다시 넣으면 된다.
#    절차: docs/monitoring-access.md 의 "팀원 등록"
```

## 검증 체크리스트

아래 `kubectl`은 IDC 노드에서 `k3s kubectl`로 실행하거나 위와 같이 검증한 SSH
경로로 실행한다.

- [ ] `k3s kubectl get pod -A` 전부 Running
- [ ] `k3s kubectl get secretstore,externalsecret -A`의 Ready 전부 True
- [ ] `k3s kubectl get pod postgres-0 -n db -o jsonpath='{.status.qosClass}'` = Guaranteed
- [ ] 앱 → DB 쿼리 정상 (헬스체크 200)
- [ ] 다음 pg-backup CronJob 성공 확인
- [ ] Grafana 로그인 + 팀원 계정 재등록 완료 (Git 이 복원하지 않는 유일한 상태)

`aws-bootstrap`은 재해 복구 때 매번 재생성하는 secret-zero다. Kubernetes Secret이나
과거 노드의 datastore에서 복사하지 않는다. Store가 `AccessDenied`라면 Secret value를
조회하지 말고 CloudTrail의 `AssumeRole`·`GetSecretValue` 실패와 IAM
role/session tag 조건부터 확인한다.
