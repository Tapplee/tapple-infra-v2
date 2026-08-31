# IDC 단일 노드 k3s 결정 기록

이 문서는 홈서버 compose에서 IDC k3s로 옮기는 결정과 남은 gate를 기록한다.
구현 사용법은 [root README](../README.md)가 정답이다.
실패 시 명령은 [runbooks](../runbooks/)가 정답이다.

현재는 운영 전이다.
2026-08 임시 VPS 결과는 과거 검증이며 최종 배포 증거가 아니다.
최종 목표는 특정 공급자에 종속되지 않은 임대 IDC 물리 서버 한 대다.

## 범위

현재 운영은 홈서버의 Docker Compose와 self-hosted GitHub Actions runner다.
PostgreSQL 16도 같은 홈서버에 있다.
새 구조는 prod, dev, preview, PostgreSQL, 관측 stack을 k3s 한 노드에 둔다.
Ansible은 host와 cluster bootstrap을 맡는다.
Argo CD는 bootstrap 이후 desired state를 맡는다.
짧은 중단은 허용한다.
고가용성은 목표가 아니다.

## 결정 ledger

| ID | 선택 | 이유 | 비용과 재검토 조건 |
|---|---|---|---|
| D1 | generic IDC 물리 서버 한 대 | 공급자 제품에 설계를 묶지 않는다 | 장비 교체와 원격 손 시간은 공급자 SLA에 의존한다 |
| D2 | 8 vCPU, 32GiB, NVMe 기준 | prod, dev, preview, 관측 stack을 한 노드에 수용한다 | 실제 사양과 runtime 사용량을 보고 증설한다 |
| D3 | 단일 노드 k3s | 운영 단위와 비용이 작다 | control plane과 workload의 SPOF를 수용한다 |
| D4 | PostgreSQL StatefulSet과 local-path PV | DB도 GitOps로 재현한다 | 노드 소실 시 PV도 잃으므로 외부 backup이 필수다 |
| D5 | 앱은 Deployment | self-heal과 Git rollback을 얻는다 | 단일 replica와 Recreate는 배포 중 짧게 중단된다 |
| D6 | OTel, Prometheus, Loki, Tempo, Grafana 자체 운영 | metric, log, trace를 한 경로로 본다 | 같은 노드 소실을 감지하지 못해 외부 monitor가 필요하다 |
| D7 | trace head sampling `1.0` | 초기 규모에서 전체 trace가 진단에 유리하다 | 저장과 memory 사용량이 커지면 retention 또는 sampling을 재검토한다 |
| D8 | Ansible bootstrap과 Argo CD reconciliation 분리 | host 작업과 cluster desired state의 책임이 다르다 | 두 도구의 순서와 health gate를 유지해야 한다 |
| D9 | Traefik Ingress 기본 off | DNS와 TLS 전 오노출을 막는다 | host와 origin TLS를 함께 준비해야 공개할 수 있다 |
| D10 | Cloudflare proxy, Full strict, origin CIDR 443만 | origin 우회와 평문 경로를 막는다 | Cloudflare CIDR 변경을 Ansible에 반영해야 한다 |
| D11 | 앱 media와 DB backup을 다른 S3 경계로 분리 | credential 침해 범위를 나눈다 | bucket과 IAM 운영이 늘어난다 |
| D12 | 전용 S3 backup writer는 put-only | cluster 침해가 기존 restore point 삭제로 번지지 않는다 | 복구에는 별도 read identity가 필요하다 |
| D13 | software RTO 목표 약 10분 | 대체 노드 준비 뒤 자동 재구축을 측정한다 | 물리 장비 조달 시간은 이 목표에 포함하지 않는다 |
| D14 | backup CronJob은 restore 전 suspended | 업로드 성공을 복구 가능성으로 오인하지 않는다 | 활성화 전에 외부 restore 리허설이 필요하다 |
| D15 | AWS Secrets Manager와 ESO 2.10.0 | Git에 값 없이 환경별 source를 운영한다 | 장기 secret-zero와 cluster-wide ESO 권한을 수용한다 |
| D16 | 16 JSON source, 20 ExternalSecret, 10 Store, 6 role | 관리자, 앱 DB, 환경, shared 값을 분리한다 | object와 rotation 절차가 늘어난다 |
| D17 | upstream chart는 version pin과 격리된 AppProject로 직접 쓰고 rendered image는 digest로 고정한다 | chart vendor patch 부담을 줄이며 registry tag 변조를 막는다 | 동일 version chart package 교체 위험은 남는다. 위협 모델이 커지면 chart를 vendor한다 |
| D18 | PostgreSQL은 공식 16.15 image digest와 raw manifest | 단일 인스턴스에 operator와 Bitnami chart는 과하다 | patch upgrade와 failover를 직접 운영한다 |
| D19 | 앱만 자체 Helm chart를 쓴다 | 환경별 값과 반복 배포에 template 이점이 있다 | DB는 raw manifest와 별도 규칙을 유지한다 |
| D20 | prod와 dev는 namespace로 분리한다 | cluster 두 대보다 싸고 경계가 명시적이다 | node와 control plane 장애는 공유한다 |
| D21 | AppProject를 bootstrap, platform, ESO, monitoring, prod, dev, preview로 분리한다 | 외부 chart의 source, destination, cluster kind Cartesian product를 없앤다 | ESO는 필수 cluster RBAC를 여전히 가진다 |
| D22 | 사용자 workload는 default-deny다 | PR과 앱의 lateral movement를 줄인다 | public 443 목적지를 FQDN으로 제한하지 못한다 |
| D23 | custom workload와 ESO는 PSA restricted를 enforce한다 | audit만으로는 위험한 Pod를 막지 못한다 | monitoring과 Argo upstream chart는 warn/audit에 남긴다 |
| D24 | 앱은 환경별 최소권한 DB role을 쓴다 | 앱 침해가 DB 관리자 권한으로 번지지 않는다 | bootstrap Job과 password rotation 순서가 늘어난다 |
| D25 | prod/dev image는 SHA tag와 digest를 같이 기록한다 | 가독성과 immutable execution을 함께 얻는다 | preview는 ApplicationSet 제약으로 tag만 사용한다 |
| D26 | preview는 한 namespace와 한 DB Pod를 공유한다 | 32GiB 노드에서 동시 6개를 수용한다 | PR 간 credential과 DB trust boundary가 없다 |
| D27 | preview DB 삭제는 PostDelete exact-name hook이다 | 마지막 접속 시각을 잘못 추측하지 않는다 | 연결이 남으면 삭제보다 실패를 선택한다 |
| D28 | public code, credential workflow는 trusted same-repo만 실행 | 공개 검토와 runtime trust를 분리한다 | infra read-only 정적 CI만 fork diff를 검사한다 |
| D29 | kubectl과 Argo CD는 infra admin만 사용한다 | cluster credential 배포를 줄인다 | 일반 maintainer는 Grafana와 앱 surface만 사용한다 |
| D30 | Git approval count는 현재 0 | review 역할 정책을 이번 migration과 분리한다 | 사람 검토를 강제하지 않으며 추후 별도 결정한다 |

## 현재 구조의 보안 경계

Argo CD controller는 cluster-wide 조정 권한이 있다.
따라서 infra `main` 쓰기 권한은 cluster-admin 수준의 trust다.
AppProject는 실수 범위를 줄이지만 같은 Git root 침해를 차단하지 못한다.
내장 `default` AppProject는 모든 source와 destination을 거부한다.
dedicated project는 wave `-100`, default deny는 `-99`로 child Application보다 먼저 적용한다.
local platform source만 여러 namespace와 Namespace/PriorityClass를 관리한다.
monitoring upstream source는 `monitoring` namespace에서 cluster-scoped kind를 만들 수 없다.
ESO upstream source는 `external-secrets` namespace와 필요한 CRD/RBAC kind만 사용한다.

ESO controller도 cluster-wide Secret 관리 권한이 있다.
IAM role은 Secrets Manager read 경로를 환경별로 제한한다.
bootstrap key 소유자는 6개 role을 모두 가정할 수 있다.
session tag는 감사와 오설정 방지이며 침해 격리 경계가 아니다.

`app`, `db`, `dev-app`, `dev-db`, `preview`, `external-secrets`는 PSA restricted를 enforce한다.
`monitoring`과 `argocd`는 restricted warn/audit을 적용한다.
upstream chart가 clean해지기 전 monitoring과 argocd enforce를 켜지 않는다.

workload namespace는 ingress와 egress를 default-deny한다.
DNS, 환경 DB, OTel, 필요한 public HTTPS만 연다.
private와 special CIDR은 public HTTPS rule에서 제외한다.
표준 NetworkPolicy는 S3와 외부 API를 FQDN으로 제한하지 못한다.
Cilium은 이 필요가 실제로 생기기 전에는 도입하지 않는다.

preview는 trusted code를 위한 비용 경계다.
preview PR은 app Secret과 `tapple_preview_app` role을 공유한다.
preview PR끼리는 상호 불신 보안 경계가 아니다.
`preview` label은 maintainer가 same-repository와 작성자 관계를 확인한 뒤 붙이는 보안 승인이다.

## 자원 기준

kubelet은 OS와 k3s에 CPU 1000m와 memory 2GiB를 system-reserved로 둔다.
hard eviction은 memory, nodefs, imagefs, node inode, image inode를 모두 명시한다.
한 항목만 덮어쓰면 다른 default가 사라질 수 있으므로 전체 set을 유지한다.

| workload | request | limit | priority |
|---|---|---|---|
| prod PostgreSQL | 2000m, 8Gi | 2000m, 8Gi | `db-critical` |
| prod app | 1000m, 4Gi | 3000m, 6Gi | `app-important` |
| dev PostgreSQL | 250m, 2Gi | 1000m, 2Gi | `dev-low` |
| dev app | 250m, 2Gi | 1500m, 3Gi | `dev-low` |
| preview PostgreSQL | 200m, 1Gi | 1000m, 1Gi | `preview-lowest` |
| preview app 하나 | 200m, 1Gi | 1500m, 2Gi | `preview-lowest` |

prod PostgreSQL은 CPU와 memory request가 limit와 같아 Guaranteed QoS다.
preview와 dev는 memory pressure에서 prod보다 먼저 축출된다.
platform workload도 CI가 모든 container와 init container의 request 및 memory limit를 검사한다.
실제 node allocatable과 system Pod 사용량은 IDC 배포 뒤 다시 측정한다.

증설 신호는 available memory 2GiB 미만 지속, 반복 OOMKill, 지속 CPU throttling, DiskPressure다.
preview가 6개보다 적게 안정적으로 뜨면 quota를 늘리지 않고 node부터 측정한다.

## 구현 완료

- [x] Ubuntu 22.04/24.04 x86_64 Ansible preflight와 명시적 confirmation
- [x] key-only SSH, UFW allowlist, swap, sysctl, timezone
- [x] k3s version과 checksum pin, Secret at-rest encryption, full hard eviction
- [x] Argo CD version과 checksum pin, resource patch, custom health gate
- [x] canonical Ansible bootstrap과 legacy installer 제거
- [x] 7개 dedicated AppProject와 disabled default project
- [x] prod, dev, preview PostgreSQL과 고정 image digest
- [x] 환경별 최소권한 app role과 prod readonly role Job
- [x] prod와 dev app Deployment, Service, fail-closed Ingress
- [x] prod/dev tag+digest 배포 PR flow
- [x] trusted same-repository PR workflow guard
- [x] preview ResourceQuota, shared DB, createdb와 PostDelete dropdb
- [x] 사용자 namespace default-deny와 allow-first sync wave
- [x] 단계적 PSA enforcement
- [x] AWS IAM, 16 source, 20 ExternalSecret 계약
- [x] OTel 전량 trace path와 resource limits
- [x] S3 stack, put-only writer, checksum과 complete marker backup Job
- [x] backup terminal failure와 stale alert
- [x] Helm, schema, policy, Ansible, CloudFormation 정적 CI

구현 완료는 실제 IDC에서 검증됐다는 뜻이 아니다.

## 남은 외부 gate

### 1. 공급자와 host

- [ ] 실제 CPU, memory, NVMe, 공인 IP를 확인한다.
- [ ] 회선 제한, 원격 손 SLA, 월 비용을 기록한다.
- [ ] Ubuntu와 SSH key를 준비한다.
- [ ] inventory의 모든 `CHANGE_ME`와 관리자 CIDR을 바꾼다.

### 2. AWS와 Secret

- [ ] 실제 계정 ID를 values에 넣는다.
- [ ] IAM stack을 배포하고 bootstrap key를 안전하게 보관한다.
- [ ] 16개 JSON source를 만든다.
- [ ] S3 stack을 실제 전역 고유 bucket 이름으로 배포한다.
- [ ] writer key와 별도 restore read identity를 준비한다.
- [ ] 10개 Store와 20개 ExternalSecret의 Ready를 확인한다.

### 3. GitHub trust root

- [ ] 두 저장소의 workflow 변경을 먼저 배포한다.
- [ ] `Static validation` 성공을 확인한다.
- [ ] secret scanning과 push protection을 켠다.
- [ ] 조직 secure 2FA를 켠다.
- [ ] `scripts/configure-github-trust-root.sh --apply`를 실행한다.
- [ ] direct push, admin bypass, force push, deletion 거부를 확인한다.
- [ ] prod와 dev의 첫 trusted deploy PR로 빈 digest를 채우고 실제 Pod의 `repository@digest`를 확인한다.
- [ ] fork PR이 backend image build, preview, deploy를 실행하지 않는지 확인한다.
- [ ] infra fork validation이 read-only token과 GitHub-hosted runner만 쓰는지 확인한다.

### 4. cluster runtime

- [ ] Ansible bootstrap을 실제 IDC에서 실행한다.
- [ ] root와 모든 child Application이 Healthy인지 확인한다.
- [ ] PSA가 custom workload 위반을 거부하는지 확인한다.
- [ ] default-deny 이후 DNS, DB, OTel, public HTTPS가 동작하는지 확인한다.
- [ ] prod, dev, preview에서 private CIDR 접근이 거부되는지 확인한다.
- [ ] 6개 preview와 platform workload의 실제 CPU, memory, disk를 측정한다.

### 5. backup과 DR

- [ ] [backup 활성화 runbook](../runbooks/backup-activation.md)을 실행한다.
- [ ] 수동 Job의 dump, checksum, marker, SSE를 확인한다.
- [ ] 클러스터 밖에서 임시 database restore를 완료한다.
- [ ] writer의 List, Get, Delete 거부를 확인한다.
- [ ] 실제 RPO와 RTO를 기록한다.
- [ ] 그 뒤에만 CronJob `suspend`를 `false`로 바꾼다.

### 6. ingress와 cutover

- [ ] prod, dev, preview의 실제 hostname과 TLS 공급 방식을 정한다.
- [ ] Grafana origin certificate와 proxied DNS를 준비한다.
- [ ] Cloudflare Full strict와 origin 우회 차단을 확인한다.
- [ ] IDC 밖 uptime monitor를 만든다.
- [ ] staging E2E와 최종 DB 동기화를 수행한다.
- [ ] DNS를 전환한다.
- [ ] 안정화 뒤 홈서버 self-hosted deploy를 중지한다.

## cutover와 rollback

| 단계 | 성공 조건 | rollback |
|---|---|---|
| Ansible bootstrap | root와 child Application Healthy | 원인을 고치고 같은 playbook을 재실행한다 |
| Secret 공급 | Store 10개와 ExternalSecret 20개 Ready | source property와 IAM을 고치고 force-sync한다 |
| policy 적용 | 허용 smoke test 성공, 금지 test 차단 | policy commit을 revert하고 Argo sync한다 |
| app 배포 | health, DB query, OTel signal 정상 | known-good image tag와 digest PR을 merge한다 |
| backup test | 외부 checksum과 임시 restore 성공 | CronJob을 suspended로 유지한다 |
| DNS cutover 전 | staging E2E 성공 | 홈서버 경로를 그대로 유지한다 |
| DNS cutover 후, 새 DB write 전 | edge와 origin 정상 | DNS를 홈서버로 되돌린다 |
| 새 DB가 write를 받은 뒤 | 데이터 정합성 확인 | 단순 DNS rollback을 금지하고 승인된 reverse sync 계획을 실행한다 |

DB write 시작이 rollback 성격이 바뀌는 경계다.
두 DB를 동시에 writable로 두지 않는다.
old deployment workflow와 new GitOps workflow가 같은 branch를 동시에 배포하지 않게 한다.
긴급 Argo UI rollback은 임시 조치이며 Git revert PR로 마무리한다.

Secret rotation 실패는 이전 Secrets Manager version, force-sync, role Job, app restart 순서로 되돌린다.
NetworkPolicy 실패는 live edit로 끝내지 않고 Git revert로 desired state를 복구한다.
AppProject rollback은 default deny 완화, Application assignment 전환, project 제거 순서의 PR로 한다.
backup 중지는 `suspend: true`로 되돌리며 기존 S3 object를 지우지 않는다.
legacy shell bootstrap으로 우회하지 않는다.

## 완료 조건

- 실제 IDC 사양에서 resource와 eviction 기준을 확인했다.
- 공개 repo와 fork 경계가 실제 GitHub event에서 fail-closed다.
- prod와 dev는 immutable digest로 실행된다.
- workload namespace의 default-deny와 PSA enforcement를 runtime에서 확인했다.
- 16 source와 20 ExternalSecret 계약이 Ready다.
- 외부 S3 restore를 완료했고 RPO와 RTO를 기록했다.
- external uptime monitor가 node-offline을 감지한다.
- 홈서버 배포 경로를 중지했다.
- [재해 복구 런북](../runbooks/disaster-recovery.md)을 다른 대체 노드에서 끝까지 실행했다.
