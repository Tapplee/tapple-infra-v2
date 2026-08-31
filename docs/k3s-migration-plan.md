# 홈서버 → IDC 단일 노드 k3s 이전 & 운영 자동화 계획

> 결정 기록 + 단계별 계획. 구현체는 이 레포 루트([README.md](../README.md)).
> v2 (2026-08-07): **D4 변경 — PostgreSQL을 호스트가 아닌 k3s 내부(StatefulSet)로 운영.** 리소스 배분·Phase 순서 재계산.
> v3 (2026-08-10): **D2 변경 — 노드 4 vCPU/16GB → 8 vCPU/32GB.** dev 환경(D18)을 같은 클러스터에 상주시키기로 하면서 리소스 전면 재배분.
> v4 (2026-08-10): **tapple로 이식.** 원안은 UMC PRODUCT(AWS EC2+RDS 탈출)용으로 작성됐고, 매니페스트 구조·결정(D1~D19)은 그대로 유효하다. tapple의 출발점만 다르다 — 아래 As-Is 참고. 검증은 임시 VPS(141.164.40.139)에서 먼저 한다.
> v5 (2026-08-31): **최종 목표를 특정 VPS/iwinv 상품이 아닌 임대한 generic IDC 물리 서버 한 대**로 확정. Ansible을 canonical bootstrap으로 추가하고, 시크릿을 AWS Secrets Manager(JSON) + ESO 2.10.0으로 교체했다. 2026-08 임시 VPS 수치는 과거 검증 기록일 뿐 현재 목표가 아니다.

---

## 1. 개요

| 항목 | 내용 |
|---|---|
| 서비스 | tapple — NFC 명함/공개 프로필 (Spring Boot 멀티모듈 + PostgreSQL/Flyway) |
| 규모 | 트래픽 가벼움, 배포 잦음 |
| 목표 | 홈서버 docker compose 단일 배포 → 단일 노드 k3s + GitOps + OTel 관측성 |
| 핵심 원칙 | 비용 최소화, 단일 노드(SPOF 감수), 배포·복구 자동화. 대체 노드 준비 후 소프트웨어 복구 목표는 ~10분 |

### As-Is
**실운영은 두 갈래이고 k3s는 아직 테스트다.** 홈서버를 폐기할 계획이 아니다.

- 로컬: 개발자 각자 `docker-compose-dev.yml` (postgres 포트 미노출)
- 홈서버(맥) + docker compose, GitHub Actions self-hosted runner(`deploy.yml`)가 main push마다 재기동
- DB: 같은 홈서버의 `postgres:16-alpine` 컨테이너 — DB명 `tapple`, 유저 `tapple` (`.env` 실측)
- 레거시: AWS EC2 + Docker Hub 경로(`cicd-prod.yml`)가 workflow_dispatch 전용으로 남아 있음 (백업 경로)
- 관측: `tapple-infra`(v1)의 compose Grafana 스택 — 부하 리그와 공용
- 비용: 홈서버 전기·회선(클라우드 청구 없음). IDC 물리 서버 임대료와 회선·원격 손 비용은 발주 전 확인

### To-Be
- Ubuntu 22.04/24.04 x86_64 IDC 물리 서버 한 대에 prod + dev 전부 수용. 현재 용량 가정은 8 vCPU / 32GB이며 실제 발주 사양으로 재검증
- **App도 DB도 k3s 안** — 클러스터 상태 전체가 Git으로 복원됨
- OTel 풀스택 자체 호스팅 + ArgoCD GitOps + Cloudflare 프론트
- Ansible이 host·k3s·Argo CD·secret-zero까지 재현하고, 이후 클러스터 상태는 Argo CD가 소유

### 이전으로 얻는 것 (홈서버 대비 — 컷오버 시점은 미정)
- 배포가 `git push` → ArgoCD pull로 바뀜. self-hosted runner가 맥에 붙어 있을 필요 없음
- 롤백이 Git revert 한 번. 지금은 compose 재기동
- prod/dev 분리가 네임스페이스로 생김 (현재 dev는 사실상 없음)
- 노드·DB·앱 리소스 한도가 명시됨 — 맥에서 다른 프로세스와 메모리를 다투지 않음

---

## 2. 확정된 결정 (Decision Record)

| # | 결정 항목 | 확정값 | 근거 |
|---|---|---|---|
| D1 | 호스팅 | **임대한 generic IDC 물리 서버 한 대** | 한 공급자 제품명에 설계를 묶지 않는다. 실제 사양·회선·원격 손 SLA는 발주 시 확정 |
| D2 | 서버 용량 | **8 vCPU / 32GB / NVMe 가정** (v3에서 4 vCPU/16GB → 8 vCPU/32GB) | dev·프리뷰 공유 DB까지 상주시킨 현재 예산은 requests 후 여유 ~8.4Gi / ~2.2 vCPU다. 실제 물리 CPU·메모리로 다시 검증 |
| D3 | 오케스트레이터 | **k3s 단일 노드** | 경량 컨트롤 플레인, 내장 Traefik/local-path |
| D4 | 데이터베이스 | **PostgreSQL StatefulSet, k3s 내부** (v2에서 변경) | 단일 노드라 호스트 분리의 가용성 이점이 절대적이지 않음. k3s 안에 넣으면 DB까지 GitOps 관리 → 재구축 시 ArgoCD apply로 전체 복원. eviction 리스크는 Guaranteed QoS + PriorityClass로 방어 |
| D5 | 앱 실행 | k8s Deployment (`app` 네임스페이스, Burstable) | 배포·롤백·자가치유 |
| D6 | 관측성 | OTel 풀스택 자체 호스팅 (Collector + Tempo + Loki + Prometheus + Grafana) — **조여서** 운영 | egress 0. 샘플링·짧은 보존 필수 |
| D7 | 운영 자동화 | Ansible(host·k3s·Argo CD·secret-zero) + Argo CD(GitOps) + GitHub Actions | bootstrap과 지속 reconciliation의 책임을 분리. Git=클러스터 상태, 자동 동기화·롤백 |
| D8 | CI | GitHub Actions: 빌드 → `ghcr.io` → 매니페스트 이미지 태그 갱신 | ArgoCD가 감지해 자동 배포(풀형) |
| D9 | 인그레스 | Traefik (k3s 내장) | 별도 설치 불필요 |
| D10 | TLS/프론트 | Cloudflare 프록시(orange cloud) + origin cert, DNS도 Cloudflare | TLS 대행, 실 IP 은닉, 캐시, 무료 DDoS 방어 |
| D11 | 미디어/파일 | S3 호환 오브젝트 스토리지(공급자 발주 시 확정) | 노드 소실과 분리하고 외부 백업·미디어 원본으로 사용 |
| D12 | 트래픽 | 발주 회선 한도와 실측 트래픽에 알림 설정 | 과거 iwinv 600GB 가정은 폐기. 공급자 조건을 설계 사실로 고정하지 않는다 |
| D13 | 가용성(SLO) | 짧은 다운 허용. **~10분은 대체 노드가 준비된 뒤 소프트웨어 재구축 목표** | 물리 장비 교체·IDC 원격 손은 공급자 의존이며 수시간 이상 걸릴 수 있다 |
| D14 | 백업/DR | `pg_dump` **CronJob**(k8s) → versioning·보존 정책을 켠 외부 오브젝트 스토리지(매일 + 배포 직전, dump+SHA-256), k3s sqlite 스냅샷, Ansible + 재구축 런북. 운영 컷오버 전에는 `suspend: true` | DB가 k3s 안이므로 백업도 k8s 매니페스트로 Git 관리. 노드와 다른 장애 영역에 저장하고 checksum 확인·restore 리허설 후 예약 실행을 켠다 |
| D15 | 시크릿 | **AWS Secrets Manager + ESO 2.10.0**. Kubernetes Secret 계약별 JSON source 13개, 환경별 IAM role 6개, namespaced `SecretStore` 10개, `ExternalSecret` 15개 | Git에는 이름·property 계약만 둔다. 역할은 `GetSecretValue`를 자기 경로에 제한하고 custom health가 Ready까지 다음 wave를 막는다 |
| D16 | 서드파티 Helm | **vendoring 안 함.** ArgoCD Application이 upstream chart repo URL + values.yaml만 참조 | Git에는 values만. 차트 복사·포크 불필요 |
| D17 | PostgreSQL 차트 | **Bitnami 차트 사용 안 함** — 공식 `postgres` 이미지 + 자작 StatefulSet | 2025-08 Broadcom이 Bitnami 무료 이미지 중단(bitnamilegacy 이관). 단일 노드엔 StatefulSet ~60줄이면 충분, 오퍼레이터(CloudNativePG)는 과함 |
| D18 | 환경 분리 (v3 추가) | **같은 클러스터, 네임스페이스로 prod/dev 분리.** 브랜치로 환경을 나누지 않고 `apps/prod`·`apps/dev` 디렉터리 + `values.yaml`/`values-dev.yaml`로 분리. 앱 레포 브랜치는 트리거(develop→dev, main→prod) | 클러스터 2개는 비용 2배. dev는 `dev-low` PriorityClass로 압박 시 먼저 축출시켜 prod 보호. dev DB는 빈 DB + Flyway(운영 데이터 미복사) |
| D19 | 자작 앱 패키징 (v3 명문화) | **앱은 자작 Helm 차트, DB는 raw manifest** | 앱은 배포마다 `image.tag`가 바뀌어 템플릿·값 분리의 실익이 있고, 단일 인스턴스 DB는 바뀔 값이 없어 템플릿이 빈 껍데기 |

---

## 3. 목표 아키텍처

```
                     인터넷 (사용자 ~1,000명)
                              │
                    ┌─────────▼─────────┐
                    │    Cloudflare     │  TLS · 실IP 은닉 · 캐시 · DDoS
                    └─────────┬─────────┘
                              │ HTTPS
   ┌──────────────────────────▼──────────────────────────────────┐
   │ IDC 물리 서버 1대 · Ubuntu 22.04/24.04 x86_64                │
   │ 현재 용량 가정 8 vCPU / 32GB / NVMe                         │
   │                                                              │
   │ 호스트: Ansible · UFW · key-only SSH · system-reserved       │
   │                                                              │
   │ k3s (단일 노드, Secret at-rest encryption)                   │
   │   [kube-system]      Traefik                                 │
   │   [external-secrets] ESO 2.10.0 + aws-bootstrap              │
   │   [argocd]           Argo CD + Application/ESO health gate   │
   │   [db]               PostgreSQL 8Gi Guaranteed · local PV    │
   │   [app]              prod 앱 4Gi                             │
   │   [dev-db/dev-app]   dev DB·앱 · dev-low                     │
   │   [preview]          공유 DB + PR별 앱 · preview-lowest      │
   │   [monitoring]       OTel · Tempo · Loki · Prometheus · Grafana │
   └───────────────┬──────────────────────────────────────────────┘
                   │ pg_dump / k3s 스냅샷
          ┌────────▼────────┐
          │ 외부 오브젝트     │  DB 백업 · k3s 스냅샷 · 미디어
          │ 스토리지          │  (공급자 발주 시 확정)
          └──────────────────┘

   Ansible controller ──secret-zero──> ESO ──AssumeRole──> IAM roles 6개
                                                      └──> AWS Secrets Manager
                                                           JSON source 13개

배포: git push → Actions 빌드 → ghcr.io → image.tag 갱신 → Argo CD pull
재구축: 대체 노드 준비 → Ansible(host+k3s+Argo CD+health+secret-zero+root)
        → ESO Ready → GitOps 복원 → pg_restore
```

**핵심**: DB가 k3s 안이므로 클러스터 정의 전체가 Git 하나로 복원된다. 대신 DB 파드가
쫓겨나지 않도록 QoS·우선순위를 유지하고, local PV와 다른 장애 영역의 백업이 필수다.
시크릿 값은 AWS Secrets Manager가 원본이며 ESO는 STS로 환경별 역할을 가정해 허용된 JSON
Secret만 `GetSecretValue`한다.

session tag는 잘못된 namespace/Store 연결을 막고 CloudTrail 감사를 돕지만 bootstrap key
소유자가 유효한 tag를 선택할 수 있으므로 보안 경계는 아니다. 이 장기 key는 Phase 1 부채이며,
위협 모델이 커지면 IAM Roles Anywhere의 단기 자격증명으로 교체한다.
단일 ESO controller의 upstream RBAC도 cluster-wide Secret 관리 권한을 가진다. 외부 PR을
받거나 namespace 운영권을 분리하는 시점에는 prod/non-prod controller와 principal을 나눈다.
Argo CD controller는 클러스터 trust root이므로 `main` 쓰기 권한도 cluster-admin 수준으로 보고
운영 전 branch protection·필수 승인·검증 status check·GitHub MFA를 적용한다.

---

## 4. 리소스 배분 (8 vCPU / 32GB)

### 4-1. 호스트 레벨 (`system-reserved`)
| 대상 | RAM | vCPU |
|---|---|---|
| OS + k3s 컴포넌트 | ~2GB | ~1 |

→ k3s 설치 플래그: `system-reserved=cpu=1000m,memory=2Gi`, `eviction-hard=memory.available<1Gi`
→ 실측 capacity 31.3Gi에서 hard eviction 여유까지 제외하면 **allocatable ≈ 28.3Gi / 7 vCPU**

### 4-2. 파드 풀
| 파드 | requests | limits | QoS | 비고 |
|---|---|---|---|---|
| PostgreSQL (`db`) | **8Gi / 2000m** | **8Gi / 2000m** | **Guaranteed** | requests==limits(cpu·mem 둘 다). `db-critical`. `shared_buffers=2GB` |
| 앱 (`app`) | 4Gi / 1000m | 6Gi / 3000m | Burstable | `app-important`. JVM MaxRAMPercentage=75 → 힙 ~4.5Gi |
| dev PostgreSQL (`dev-db`) | 2Gi / 250m | 2Gi / 1000m | Burstable | `dev-low`. `shared_buffers=512MB` |
| dev 앱 (`dev-app`) | 2Gi / 250m | 3Gi / 1500m | Burstable | `dev-low` |
| 프리뷰 공유 PostgreSQL (`preview`) | 1Gi / 200m | 1Gi / 1000m | Burstable | `preview-lowest`. PR별 database 공유 |
| OTel 스택 (전체) | ~2.53Gi / 590m | ~4.31Gi | Burstable | prod·dev 공유. 샘플링 10% 유지 |
| ArgoCD + Traefik + External Secrets Operator | ~0.4Gi / 540m | 일부 미설정 | 혼합 | ESO는 명시, Argo CD 일부는 upstream 기본 |
| **상주 requests 합** | **~19.9Gi / 4.83 vCPU** | | | allocatable(28.3Gi / 7 vCPU) 대비 **~8.4Gi · ~2.2 vCPU 여유** |

> requests는 **스케줄러가 잡아두는 예약**일 뿐이라 유휴 CPU는 limits 한도까지 다른 파드가 쓴다 — prod 앱은 순간 3코어까지 뻗을 수 있다.

### 4-3. eviction 방어 (DB가 k8s 안이므로 필수)
- PostgreSQL: `requests == limits` (Guaranteed) → 메모리 압박 시 마지막에 축출
- PriorityClass 4단: `dev-low`(-100) → 모니터링·기본(0) → `app-important`(1000) → `db-critical`(1000000)
  → 압박 시 **dev가 가장 먼저 죽고 prod DB가 마지막**
- PV: local-path (NVMe 직접). 노드 소실 = 데이터 소실 → **백업이 유일한 복구선**

---

## 5. 구현 계획

### Phase 0 — 사전 준비
- [x] PostgreSQL 메이저 버전 — 홈서버 compose가 `postgres:16-alpine`이므로 **16** 고정
- [ ] IDC 물리 서버 발주: 실제 CPU·메모리·NVMe·공인 IP·회선·원격 손 SLA·월 요금 확인, Ubuntu 22.04/24.04 x86_64와 SSH key 준비
- [ ] Cloudflare 계정 + 도메인 네임서버 이전 (전파 시간 → 최우선 착수)
- [ ] 노드와 장애 영역이 다른 S3 호환 오브젝트 스토리지 버킷 + key 발급
- [ ] GitHub 레포 + `ghcr.io` 토큰
- [ ] AWS Secrets Manager 13개 JSON source와 ESO bootstrap IAM access key 준비

### Phase 1 — Ansible controller와 inventory 준비

```bash
cd ansible
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp inventories/idc/hosts.example.yml inventories/idc/hosts.yml

ansible-playbook --syntax-check playbooks/bootstrap.yml
ansible-playbook --check --tags preflight playbooks/bootstrap.yml
```

- [x] Ubuntu 22.04/24.04 x86_64 단일 host만 허용하는 preflight와 `CHANGE_ME`·명시적 confirm guard
- [ ] `ansible_host`, key+sudo `ansible_user`, `common_admin_ssh_cidrs`를 실제 값으로 설정
- [ ] 팀원 kubeconfig가 꼭 필요할 때만 `common_k3s_api_cidrs`에 고정 팀/VPN egress CIDR을 추가
- [x] UFW 인바운드 allow는 Ansible이 전부 소유: SSH allowlist·80/443·k3s pod/service CIDR만 열고 `6443`은 기본 차단. broad CIDR·public 22/6443은 변경 전 거부하고 선언 밖 과거 allow 규칙은 제거. 기존 inbound deny/reject·route allow/limit·quoted profile은 변경 전에 fail-fast
- [x] swap 비활성화, kernel module/sysctl, key-only SSH, Asia/Seoul timezone 자동화
- **검증**: `common_k3s_api_cidrs`가 비어 있으면 API는 local/SSH로만 운영. 값이 있으면 명시한 CIDR만 `6443/tcp` 허용

### Phase 2 — canonical bootstrap 실행

```bash
ansible-playbook playbooks/bootstrap.yml
```

- [x] k3s `v1.36.3+k3s1`, Argo CD `v3.5.0` 고정과 다운로드 checksum 검증
- [x] k3s Secret at-rest encryption, root-only kubeconfig, system-reserved·eviction 설정
- [x] IAM bootstrap user + `tapple-secrets-*` role 6개 CloudFormation
- [x] AWS 자격증명은 기본 hidden prompt 또는 승인된 controller 환경변수로 받고, `no_log` + stdin으로 `external-secrets/aws-bootstrap` 주입
- [x] root보다 먼저 Argo CD의 `Application`·`SecretStore`·`ExternalSecret` custom health 적용
- [x] root app 이후 네임스페이스 7개와 PriorityClass 4종은 GitOps로 배포
- **검증**: playbook 정상 종료 자체가 root `Synced+Healthy`를 뜻한다. 추가로 `kubectl describe node`, `k3s secrets-encrypt status`, 10개 `SecretStore`와 15개 `ExternalSecret`의 `Ready=True`, 하위 Application `Healthy` 확인

`infra/k3s-setup.sh`와 `scripts/bootstrap-external-secrets-aws.sh`는 복구용 fallback이다.
신규 설치와 반복 실행의 표준은 Ansible이다.

### Phase 3 — PostgreSQL (k3s 내부) + 데이터 이전
- [ ] StatefulSet 매니페스트 작성 (`manifests/postgres/`): 공식 `postgres:16` 이미지, local-path PVC, Guaranteed QoS, `db-critical` 우선순위
- [ ] 튜닝값(구현체는 ConfigMap 대신 컨테이너 args): `shared_buffers=2GB`, `effective_cache_size=6GB`, `work_mem=16MB`, `max_connections=60`(앱 Hikari 풀 10과 매칭)
- [ ] Service는 ClusterIP만 — 외부 노출 금지
- [ ] 홈서버 → 이전: `pg_dump`(홈서버 postgres 컨테이너) → `pg_restore`(파드). 컷오버 시점 재동기화
- **검증**: `kubectl exec`로 psql 접속, 테이블 100개+·인덱스 확인, `kubectl get pod -o jsonpath='{.status.qosClass}'` = Guaranteed

### Phase 4 — 앱 배포
- [ ] Dockerfile 정리, `ghcr.io` 빌드·푸시 테스트
- [ ] `app` Deployment + Service (§4-2 리소스), DB 접속은 `postgres.db.svc.cluster.local`
- [ ] 시크릿: D15의 13개 Secrets Manager JSON 계약을 채우고 ESO가 기존 Kubernetes Secret 이름으로 동기화하는지 확인
- **검증**: 파드 Running, 앱→DB 쿼리 성공

### Phase 5 — 인그레스 + Cloudflare + TLS
- [ ] Traefik IngressRoute, Cloudflare A 레코드 + orange cloud ON
- [~] Grafana Origin Certificate는 Secrets Manager→ESO 계약과 Ingress TLS 연결 완료. 실제 인증서 입력, 나머지 앱 host의 origin TLS, SSL 모드 Full (strict), 정적 에셋 캐시 규칙은 컷오버 때 적용
- **검증**: HTTPS 접속, dig로 실 IP 미노출 확인

### Phase 6 — OTel 관측성 (조여서)
- [ ] upstream Helm 차트로 배포(§D16): 트레이스 샘플링 10%, 현재 보존 Tempo 7일/Loki 90일/Prometheus 14일, 파드별 memory limit 명시
- [ ] 앱 OTel SDK 계측, Grafana 대시보드 + 알림(노드 메모리, DB 연결 수, 에러율)
- **검증**: 트레이스/로그/메트릭 수집, `kubectl top pod -n monitoring` limit 내

### Phase 7 — ArgoCD (GitOps)
- [x] ArgoCD 설치, app-of-apps로 db/app/monitoring Application 정의
- [x] custom health로 자식 Application과 ESO의 실제 Ready까지 sync wave 차단
- [x] auto-sync + self-heal
- [ ] UI는 별도 서브도메인 + Cloudflare Access
- **검증**: Git 변경 → 자동 반영, UI 롤백 동작

### Phase 8 — CI/CD (GitHub Actions)
- [x] 앱: build → `ghcr.io` 푸시(태그=커밋SHA) → 매니페스트 `image.tag` 갱신
- [x] 인프라: `.github/workflows/validate.yml`에서 Helm render/lint, Ansible syntax/lint, CloudFormation lint
- **검증**: push 한 번으로 배포까지 완주

### Phase 9 — 백업 / DR
- [ ] `pg_dump` **CronJob** (k8s, Git 관리): versioning·보존 정책·restore 검증 후 `suspend: false`, 매일 + 배포 직전(CI 트리거) → dump와 SHA-256을 오브젝트 스토리지에 업로드, 보존 일 7/주 4
- [ ] k3s sqlite 스냅샷 → 오브젝트 스토리지
- [ ] 재구축 런북: 대체 노드 준비 → Ansible → ESO/Argo CD health 통과 → GitOps 복원 → pg_restore
- [ ] **복원 리허설 1회 필수**
- **검증**: 백업 생성 확인, 테스트 복원 성공. ~10분 목표는 **대체 노드가 준비된 시점부터** 측정

### Phase 10 — 검증 & 컷오버
- [ ] 스테이징 도메인 E2E → DB 최종 재동기화 → DNS 전환
- [ ] Grafana 관찰 → 안정화 후 홈서버 compose·self-hosted runner 정리 (레거시 EC2 경로도 같이 판단)
- **검증**: 실트래픽 정상, 청구액이 예상 범위 내

---

## 6. 주의사항

### OTel 조이기
- head sampling 10%, 에러는 tail sampling 고려
- 현재 보존: Tempo 7일 / Loki 90일 / Prometheus 14일. 32GB 단일 노드에서 디스크·메모리 추세를 보고 Loki부터 줄일 것
- Tempo/Loki/Prometheus `resources.limits.memory` 반드시 설정
- 계속 빡빡하면 저장 백엔드만 Grafana Cloud 무료티어 오프로드 (egress 발생)

### 단일 노드 리스크
- `system-reserved` 미설정 = 노드 OOM
- DB 파드 Guaranteed QoS + PriorityClass 미설정 = 메모리 압박 시 DB 축출 위험
- 미디어는 반드시 오브젝트 스토리지 (노드 직접 서빙 금지)
- local-path PV = 노드 소실 시 데이터 소실 → 백업 리허설 필수
- k3s 업그레이드 = DB 파드 재시작 = 짧은 다운 (RTO 허용 범위)
- 물리 노드 소실 시 장비 교체·IDC 원격 손 시간은 통제 밖이며 수시간 이상일 수 있음. ~10분은 대체 노드 준비 후 소프트웨어 RTO일 뿐
- Kubernetes API `6443`은 기본 차단. 팀원 접근은 고정/VPN egress CIDR만 `common_k3s_api_cidrs`에 넣고 `0.0.0.0/0` 금지

### 시크릿 운영 부채

- bootstrap IAM user는 Secret을 직접 읽지 않지만 key 소유자는 유효한 session tag로 여섯 역할 모두를 가정할 수 있음. tag 조건은 감사·오설정 방지이지 침해 격리 경계가 아님
- 장기 bootstrap key는 Phase 1 부채. 주기적 수동 회전 후 필요 시 IAM Roles Anywhere로 교체
- Secrets Manager 자동 회전은 IDC PostgreSQL·대상 서비스로의 네트워크 경로와 무중단 회전 계약이 없어서 보류. 지금은 source·대상 시스템·workload를 함께 수동 회전
- app JSON의 DB user/password와 DB JSON의 값이 중복되는 것은 기존 `envFrom` 호환 부채. 회전 때 반드시 함께 변경

### 리사이즈 트리거
- 노드 available memory 지속 2GB 미만 or OOMKill 반복 → 상위 플랜 리사이즈 (수분)
- CPU throttling(`container_cpu_cfs_throttled_seconds`)이 지속되면 해당 파드의 limits부터 올리고, 노드 전체 사용률이 높으면 vCPU 상향
- dev까지 죽기 시작하면 이미 늦은 것 — Grafana 노드 메모리·CPU 알림을 먼저 본다

---

## 7. 리포지토리 구조

**desired state 갱신 (2026-08-31)** — 이 레포 루트가 실물이다. 구조 설명은 [README.md](../README.md).

```
tapple-infra-v2/
├─ ansible/                    # Ubuntu IDC host → k3s·Argo CD·health·secret-zero·root
├─ bootstrap/root-app.yaml     # Ansible이 마지막에 적용하는 app-of-apps 루트
├─ apps/                       # ArgoCD Application 정의 — root가 재귀 sync
│  ├─ platform/                #   환경 공용: cluster(-3)·external-secrets(-2)·secrets(-1)·monitoring(2)
│  ├─ prod/                    #   postgres(0) · tapple-server(1)
│  └─ dev/                     #   postgres(0) · tapple-server(1)
├─ charts/
│  ├─ tapple-server/          # 자작 앱 Helm 차트 + 환경별 values (D19)
│  └─ tapple-secrets/         # 10 SecretStore·15 ExternalSecret·JSON property 계약 (값 없음)
├─ manifests/
│  ├─ cluster/                 #   네임스페이스·PriorityClass·RBAC·Argo CD custom health
│  ├─ postgres/                #   prod DB — StatefulSet·Service·백업 CronJob (D17)
│  ├─ postgres-dev/            #   dev DB — 축소판
│  └─ monitoring/              #   대시보드 7 + 알림 규칙 2 (ConfigMap, 자동 생성)
├─ secrets/                    # Secrets Manager JSON 계약·최초 구성·회전 절차 (D15)
├─ infra/
│  ├─ aws/                     # ESO bootstrap IAM user·환경별 IAM Role CloudFormation
│  ├─ node-bootstrap.sh        # legacy fallback
│  └─ k3s-setup.sh             # legacy fallback
├─ scripts/
│  ├─ bootstrap-external-secrets-aws.sh  # legacy secret-zero fallback
│  └─ gen-configmaps.py        # v1(tapple-infra) 대시보드 원본 → ConfigMap 변환
├─ .github/workflows/validate.yml  # Helm·Ansible·CloudFormation 정적 검증
└─ runbooks/disaster-recovery.md

tapple-be/.github/workflows/cd-gitops.yml  # build → ghcr.io → 이 레포 image.tag bump (D8)
```

*postgres-setup.sh 삭제됨 (v2) — DB가 k3s 매니페스트로 이동.*
*upstream 차트 values는 별도 파일이 아니라 Application 안 `valuesObject` 인라인 (v3 — D16 구현 형태 확정).*

---

## 8. 미해결 항목

**해결됨 (v3~v5)**
- ~~1. 시크릿 방식~~ → AWS Secrets Manager(JSON source) + ESO 2.10.0 확정 (D15)
- ~~4. 앱 커넥션 풀 ↔ max_connections~~ → Hikari 10 ↔ `max_connections=60`
- ~~5. 모노레포 vs 분리 레포~~ → `Tapplee/tapple-infra-v2`로 분리 (D18)
- ~~6. Grafana 알림 채널~~ → Discord webhook, 기존 alertmanager 라우팅 이식

**남음**
1. 도메인/서브도메인 구조 — values의 `*.example.invalid`는 운영 전 fail-safe placeholder다. IDC 앱·dev·preview·ArgoCD UI 실도메인 확정 필요. Grafana는 기존 `grafana-k3s.tapple.co.kr`를 유지한다
2. IDC 물리 서버 실제 사양·회선·원격 손 SLA·월 요금 — 홈서버 대비 **순증 비용**이고 하드웨어 복구 시간의 상한을 결정한다
3. Traefik `trustedIPs` — Cloudflare 뒤에서 실 클라이언트 IP 복원
4. BE `prod` 프로파일의 CloudWatch appender — AWS 떠나면 무의미. k3s 전용 프로파일이 필요한지 결정
5. 미디어/백업용 외부 오브젝트 스토리지 — 현재 AWS S3(`taple-bucket`) 유지 또는 다른 S3 호환 공급자 선택
6. 홈서버 배포(`deploy.yml`)와의 컷오버 순서 — 두 경로가 동시에 main을 배포하지 않게 조정
7. secret-zero 장기 key 회전 주기·담당자와 IAM Roles Anywhere 전환 조건
8. Secrets Manager 자동 회전에 필요한 IDC 네트워크 경로와 무중단 회전 계약

**해결됨 (v4, tapple 이식)**
- ~~PostgreSQL 메이저 버전~~ → 현 운영과 같은 **16** 고정 (홈서버 compose가 `postgres:16-alpine`). 이전과 메이저 업그레이드를 한 번에 하지 않는다

---

## 9. 예상 결과

| 지표 | As-Is (홈서버 compose) | To-Be (k3s 단일 노드) |
|---|---|---|
| 월 비용 | 클라우드 청구 0 (전기·회선) | IDC 서버·회선·외부 스토리지 + Secrets Manager 요금 — 발주/생성 시 확정 |
| 배포 | main push → self-hosted runner가 compose 재기동 | Git push → ArgoCD pull (GitOps) |
| 롤백 | compose 수동 | Git revert |
| 환경 | prod 사실상 단일 | prod / dev 네임스페이스 분리 |
| 관측성 | compose Grafana (리그와 공용) | 클러스터 내 OTel 풀스택 |
| 가용성 | — | 짧은 다운 허용. 대체 노드 준비 후 소프트웨어 RTO ~10분; 하드웨어 교체는 공급자 의존 |
| 복구 | — | Ansible + Argo CD health gate + pg_restore |

---

## 11. PR 프리뷰 환경 (구현됨 · Secrets Manager 값 주입 대기)

`feat/new-func` 같은 브랜치를 올리면 그 PR 만의 URL 이 생기고, PR 을 닫으면 사라지는 환경.
dev 환경 하나를 여러 작업이 번갈아 쓰면서 서로 덮어쓰는 문제를 없앤다.

![PR 프리뷰 환경](diagrams/out/preview-env.png)

### 장치

ArgoCD **ApplicationSet** 의 Pull Request 생성기. PR 목록을 폴링해 PR 하나당 Application 을
자동 생성하고, PR 이 닫히면 그 Application 을 지운다.

### 설계 판단 세 개

**① 네임스페이스를 PR 마다 만들지 않고 `preview` 하나로 모은다**

PR마다 namespace를 만들면 namespace 생명주기, RBAC·NetworkPolicy, namespaced
`SecretStore`·`ExternalSecret`을 매번 같이 생성·정리해야 한다. PR 코드와 database만
분리하면 목적을 달성하므로 운영 오브젝트는 `preview` namespace 하나에 모은다.

프리뷰 전용 시크릿은 `/tapple/preview/app-secrets`와
`/tapple/preview/postgres-preview-secrets` JSON source에 두고, `tapple-secrets-preview` IAM
Role을 쓰는 `preview/aws-secretsmanager` `SecretStore`만 읽는다. 환경 공유를 명시적으로
허용한 GHCR Docker config만 `/tapple/shared/ghcr-pull`에 둔다.
prod/dev 경로를 preview에서 읽을 수는 없다.

**② DB 는 프리뷰 전용 postgres 한 대를 공유하고 PR 마다 database 를 나눈다**

database 를 나누지 않으면 여러 PR 의 Flyway 가 같은 스키마를 동시에 고쳐 서로를 깬다.
반대로 postgres 를 PR 마다 띄우면 메모리가 남지 않는다(아래 예산).
`CREATE DATABASE` 는 postgres 가 자동으로 해주지 않으므로 멱등 Job 이 필요하다.

**③ 우선순위를 dev 보다 더 낮게 둔다**

메모리 압박 시 프리뷰가 가장 먼저 죽어야 한다. `dev-low`(-100) 아래 `preview-lowest` 를 새로 만든다.

### 메모리 예산 (2026-08-11 초기 실측, 현재는 위 §4-2와 ResourceQuota가 기준)

| | |
|---|---|
| allocatable | 28.3 Gi |
| 현재 requests | 18.5 Gi |
| 여유 | **9.8 Gi** |
| 프리뷰 공유분 (postgres-preview) | 1 Gi (1회) |
| PR 당 | 1 Gi (앱만, prod 의 1/4) |
| **당시 계산** | 약 8개 — 여유 2Gi 를 남겨 6개 권장 |

현재 상주 requests는 약 19.9Gi이고 프리뷰 DB까지 포함한 남은 메모리는 약 8.4Gi다.
`preview-budget` ResourceQuota가 `count/deployments.apps=6`과 namespace 자원 예산을
강제하므로 현재 운영 상한은 권장이 아니라 **6개**다.

### 구현 상태

- [x] **`applicationsets.argoproj.io` CRD** — 누락돼 있던 것을 설치했다. 첫 ArgoCD 설치가
      애노테이션 크기 오류로 실패했을 때 이것만 안 들어왔고 컨트롤러가 감시 대상 없이 헛돌았다
- [x] `apps/preview/applicationset.yaml` — PR 생성기 + `preview` 라벨 필터
- [x] `apps/preview/postgres.yaml` + `manifests/postgres-preview/` — 공유 postgres 1대
- [x] `manifests/cluster/preview-resourcequota.yaml` — Deployment 6개와 namespace 자원 상한 강제
- [x] `createdb` Job — 차트에 `createDatabase.enabled` 로 게이트, `\gexec` 로 멱등
- [x] `preview-lowest` PriorityClass (-1000) + `preview` 네임스페이스
- [x] `charts/tapple-server/values-preview.yaml` + `fullnameOverride` 지원
- [x] 고아 database 정리 CronJob (주 1회, 마지막 접속 7일 초과 대상)
- [x] `cd-gitops.yml` 확장 — tapple-be PR #25
- [x] `charts/tapple-secrets/` — preview·shared `SecretStore`/`ExternalSecret`과 Secrets Manager JSON 계약
- [ ] **`/tapple/platform/argocd/preview-github-token`** — PR 목록 조회용 PAT
- [ ] **`/tapple/preview/app-secrets`·`/tapple/preview/postgres-preview-secrets`** — JSON 원본
- [ ] **`/tapple/shared/ghcr-pull`** — `dockerconfigjson` property를 가진 공용 GHCR pull 원본
- [ ] 모든 preview `SecretStore`·`ExternalSecret`의 `Ready=True` 확인
- [ ] **`preview` 라벨 생성** — 레포 라벨 목록에 없으면 붙일 수 없다

### 쓰는 방법

```
1. PR 을 연다
2. `preview` 라벨을 붙인다        ← 이게 자리 예약이다
3. DNS/TLS 설정 뒤 몇 분 후 실제 1단 preview host가 뜬다
4. PR 을 닫거나 라벨을 떼면 사라진다
```

### 밟기 쉬운 함정 (구현 중 실제로 밟은 것들)

- **PR 생성기의 라벨 필터는 `github.labels` 에 있다.** `filters[]` 는 `branchMatch`·
  `targetBranchMatch`·`titleMatch` 만 받는다. `filters[].labels` 로 쓰면 admission 이
  unknown field 로 거부한다 (CRD 스키마로 확인)
- **PR 이벤트의 기본 체크아웃은 머지 커밋이다.** 그대로 빌드하면 이미지 태그가 머지 커밋
  SHA 가 되는데 ApplicationSet 은 `head_sha` 를 본다 → 찾는 이미지가 없다
- **차트의 `fullname` 을 `.Release.Name` 으로 바꾸면 안 된다.** prod 는 그대로지만
  dev 리소스 이름이 바뀌어 기존 워크로드가 재생성된다. `fullnameOverride` 를 추가해
  프리뷰만 덮어쓴다
- **PR 이 닫혀도 database 는 남는다.** ApplicationSet 이 지우는 것은 k8s 리소스뿐이다

### 할 값어치가 있나

프리뷰 환경의 값어치는 **보는 사람이 여러 명일 때** 가장 크다 — 디자이너·기획이 URL 로 확인하거나,
FE 가 BE 브랜치를 붙여보거나, 동시 PR 이 여러 개일 때. 지금은 1인이고 `dev` 브랜치가
그 역할을 하며, 로컬 compose 가 브랜치별 테스트를 담당한다.

즉 **지금 당장 필요한 것은 아니다.** 다만 아픈 지점이 하나 있다 — dev 환경이 하나뿐이라
두 작업이 겹치면 서로를 덮는다. 그게 실제로 불편해지는 시점이 도입 신호다.
