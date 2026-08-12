# 재해 복구 런북 (RTO ~10분)

노드 소실 시 전체 재구축 절차. **Phase 9에서 리허설 1회 필수** — 리허설 전까지 이 문서는 초안.

## 전제

- 오브젝트 스토리지에 있어야 하는 것: ① 최신 pg_dump ② sealed-secrets 컨트롤러 개인키(`sealed-secrets-key.yaml`) ③ (선택) k3s sqlite 스냅샷
- 로컬에 있어야 하는 것: kubeconfig 접근 수단, iwinv 콘솔 계정

## 절차

```bash
# 1. iwinv 콘솔에서 노드 생성 (gna_4.16_n, Ubuntu 22.04, SSH 키)

# 2. 기본 세팅 + k3s + ArgoCD (스크립트 2개)
ADMIN_IP=<내IP> ./infra/node-bootstrap.sh
./infra/k3s-setup.sh   # 내부에서 root-app apply까지 수행

# 3. sealed-secrets 개인키 복원 — 컨트롤러가 새 키를 만들기 전에!
#    (순서 밀렸으면 복원 후 컨트롤러 파드 재시작)
kubectl apply -f sealed-secrets-key.yaml   # 오브젝트 스토리지에서 내려받은 백업
kubectl rollout restart deployment sealed-secrets-controller -n kube-system

# 4. ArgoCD가 클러스터 전체 자동 복원 대기 (secrets → postgres → app 순)
kubectl get applications -n argocd -w

# 5. DB 복원
kubectl exec -n db postgres-0 -- sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < taple-<최신>.dump

# 6. Cloudflare A 레코드가 새 노드 IP인지 확인 → 앱 헬스체크
#    grafana-k3s 레코드도 같이 바꿀 것 (docs/monitoring-access.md)
curl -s https://<도메인>/actuator/health

# 7. Grafana 팀원 계정 재등록
#    사용자 목록은 Grafana 의 sqlite(PVC)에 있어 Git 이 복원해주지 않는다.
#    대시보드·데이터소스는 자동 복원되므로 사람만 다시 넣으면 된다.
#    절차: docs/monitoring-access.md 의 "팀원 등록"
```

## 검증 체크리스트

- [ ] `kubectl get pod -A` 전부 Running
- [ ] `kubectl get pod postgres-0 -n db -o jsonpath='{.status.qosClass}'` = Guaranteed
- [ ] 앱 → DB 쿼리 정상 (헬스체크 200)
- [ ] 다음 pg-backup CronJob 성공 확인
- [ ] Grafana 로그인 + 팀원 계정 재등록 완료 (Git 이 복원하지 않는 유일한 상태)
