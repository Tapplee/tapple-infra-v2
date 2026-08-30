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
- `charts/tapple-secrets/values.yaml`의 AWS 계정 ID가 실제 계정으로 커밋되어 있어야 한다.

## 절차

```bash
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
#    x86_64 Ubuntu, 공인 IP, 키 기반 root SSH가 Ansible 최초 접속 조건이다.
IDC_NODE_HOST="${IDC_NODE_HOST:?IDC_NODE_HOST에 복구한 IDC 노드 IP를 설정하세요}"

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

# 6. 노드의 root-only kubeconfig를 복사하지 말고 SSH 넘어서 ESO 준비 상태를 확인한다.
ssh root@"$IDC_NODE_HOST" \
  'k3s kubectl rollout status deployment/external-secrets -n external-secrets --timeout=300s'
ssh root@"$IDC_NODE_HOST" \
  'k3s kubectl wait --for=condition=Ready secretstore --all -A --timeout=180s'
ssh root@"$IDC_NODE_HOST" \
  'k3s kubectl wait --for=condition=Ready externalsecret --all -A --timeout=300s'
ssh root@"$IDC_NODE_HOST" 'k3s kubectl get secretstore,externalsecret -A'

# 7. ArgoCD custom health gate가
#    external-secrets → SecretStore/ExternalSecret → postgres → app 순서로 수렴시킨다.
ssh root@"$IDC_NODE_HOST" 'k3s kubectl get applications -n argocd'

# 8. 빈 PostgreSQL이 준비된 뒤 DB를 복원한다. dump는 SSH stdin으로만 넘기고
#    IDC 노드 디스크에 임시 복사하지 않는다.
ssh root@"$IDC_NODE_HOST" \
  'k3s kubectl rollout status statefulset/postgres -n db --timeout=300s'
BACKUP_FILE='/안전한/경로/taple-latest.dump'
test -r "$BACKUP_FILE"
ssh root@"$IDC_NODE_HOST" \
  'k3s kubectl exec -i -n db postgres-0 -- sh -c '\''pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists'\''' \
  < "$BACKUP_FILE"

# 9. Cloudflare A 레코드가 새 IDC 노드 IP인지 확인 → 앱 헬스체크
#    grafana-k3s 레코드도 같이 바꿀 것 (docs/monitoring-access.md)
curl -fsS https://api.example.com/actuator/health

# 10. Grafana 팀원 계정 재등록
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
