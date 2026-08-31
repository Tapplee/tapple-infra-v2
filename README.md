# tapple-infra-v2

IDC의 Ubuntu x86_64 물리 서버 한 대를 위한 k3s GitOps desired state다.
기준 용량은 8 vCPU와 32GiB 메모리다.
이 구조는 짧은 중단을 허용하며 고가용성은 제공하지 않는다.

현재는 운영 전이다.
매니페스트와 자동화는 구현됐지만 AWS 값 주입, IDC 설치, 복구 리허설, DNS 컷오버는 아직 수동 gate다.
상세 결정과 tradeoff는 [아키텍처 결정 기록](docs/k3s-migration-plan.md)에 있다.

## 공개 저장소 경계

저장소에는 시크릿 값, 암호문, private key, kubeconfig를 커밋하지 않는다.
AWS Secrets Manager 이름, JSON property 계약, IAM 정책은 공개 정보로 취급한다.
backend의 credential-bearing build, preview, deploy workflow는 fork PR 코드를 실행하지 않는다.
infra 정적 검증은 read-only token과 GitHub-hosted runner에서 fork diff를 검사할 수 있다.
프리뷰는 같은 저장소의 `MEMBER`, `OWNER`, `COLLABORATOR` PR만 만든다.
ApplicationSet은 작성자 관계를 직접 거르지 못하므로 `preview` label이 maintainer의 보안 승인이다.
외부 PR이 열려도 backend image, preview, deploy 권한으로 이어지지 않는다.
GitHub secret scanning과 push protection 활성화는 운영 전 수동 gate다.
공개 라이선스와 기여 정책은 이 저장소의 현재 범위가 아니다.

## 아키텍처

```text
GitHub protected main ──pull──> Argo CD ──> K3s on one IDC node
       ^                              │
       │ image tag + digest PR        ├─ prod: app + PostgreSQL
tapple-be Actions ──push──> GHCR      ├─ dev: app + PostgreSQL
                                      ├─ preview: PR apps + shared PostgreSQL
AWS Secrets Manager ──ESO─────────────┤
apps ──OTLP 100% head sampling────────> OTel ──> Prometheus/Loki/Tempo/Grafana
PostgreSQL ──gated backup─────────────> dedicated S3 bucket
```

Ansible은 호스트, k3s, Argo CD, secret-zero, root Application을 순서대로 만든다.
`ansible/playbooks/bootstrap.yml`이 설치와 재해 복구의 유일한 bootstrap 경로다.
Argo CD는 7개 AppProject로 bootstrap, local platform, ESO, monitoring, prod, dev, preview 범위를 나눈다.
외부 monitoring chart는 `monitoring` namespace와 namespaced kind만 사용한다.
ESO chart의 cluster-scoped 권한은 `external-secrets` project로 별도 격리한다.
직접 쓰는 upstream chart는 version을, 그 chart가 만드는 모든 workload image는 digest를 고정한다.
chart package 자체는 vendor하지 않아 동일 version 교체 위험은 남으며, CI render contract도 merge 후 원격 교체를 차단하지는 못한다.
내장 `default` AppProject는 모든 source와 destination을 거부한다.
AWS Secrets Manager는 시크릿의 원본이다.
ESO는 6개 IAM role과 10개 namespaced SecretStore를 사용한다.
16개 JSON source는 20개 ExternalSecret으로 동기화된다.
애플리케이션은 DB 관리자 계정이 아니라 환경별 고정 role을 사용한다.
prod와 dev의 tag+digest 갱신 흐름은 구현됐다.
현재 bootstrap values의 digest는 비어 있으며, trust root 후 첫 신뢰 배포 PR이 채우기 전까지는 SHA tag fallback이다.
preview는 ApplicationSet이 제공하는 head SHA tag를 사용한다.
PR을 닫거나 `preview` 라벨을 떼면 PostDelete hook이 해당 PR database만 삭제한다.

## 보안 경계

`app`, `db`, `dev-app`, `dev-db`, `preview`, `external-secrets`는 PSA `restricted:v1.36`을 enforce한다.
`monitoring`과 `argocd`는 upstream chart 호환 때문에 restricted warn/audit만 적용한다.
사용자 workload namespace는 ingress와 egress를 default-deny한다.
허용 경로는 DNS, 같은 환경 DB, OTel Collector, 필요한 public HTTPS다.
표준 Kubernetes NetworkPolicy는 S3나 외부 API를 FQDN으로 제한하지 못한다.
현재 public 443 허용은 private CIDR 접근을 막지만 임의 public 443 유출까지 막지는 못한다.
더 강한 egress 제어가 실제로 필요해지면 Cilium FQDN policy나 egress proxy를 검토한다.
플랫폼/인프라 관리자만 kubectl과 Argo CD를 사용한다.
승인된 일반 사용자는 Grafana만 사용하며 kubeconfig를 받지 않는다.
DB 운영과 readonly role 회전은 인프라 관리자 업무다.

## 배포 흐름

1. `tapple-be`의 `main` 또는 `dev`가 merge된다.
2. Actions가 이미지를 GHCR에 push한다.
3. Actions가 registry digest를 확인한다.
4. Actions가 이 저장소의 환경별 `image.tag`와 `image.digest`를 바꾸는 PR을 연다.
5. `Static validation`이 성공하면 PR이 squash merge된다.
6. Argo CD가 보호된 `main`을 pull한다.

승인 수는 현재 명시적으로 0이다.
직접 push, force-push, branch 삭제, 관리자 우회는 금지한다.
사람 역할과 리뷰 정책의 재설계는 별도 결정이다.
영구 rollback은 known-good tag와 digest로 되돌리는 PR이다.
Argo CD UI rollback은 self-heal이 되돌릴 수 있으므로 임시 조치다.

프리뷰 흐름은 [PR 프리뷰](docs/preview-environments.md)에 있다.
Git 신뢰 루트 적용 순서는 [GitHub trust root](docs/github-trust-root.md)에 있다.

## 환경

| 환경 | namespace | DB | 이미지 | Ingress | 백업 |
|---|---|---|---|---|---|
| prod | `app`, `db` | `tapple`, 전용 | 첫 배포 전 SHA tag, 이후 digest | 기본 off | S3, 현재 suspended |
| dev | `dev-app`, `dev-db` | `tapple_dev`, 전용 | 첫 배포 전 SHA tag, 이후 digest | 기본 off | 없음 |
| preview | `preview` | `tapple_pr<N>`, PostgreSQL 공유 | PR SHA tag | 기본 off | 없음 |

모든 환경은 root trace를 `1.0`으로 head sampling한다.
Collector에는 sampling processor가 없다.
이 설정은 의도적 sampling이 없다는 뜻이며 장애 중 무손실을 보장하지 않는다.
동시 preview 상한은 ResourceQuota로 6개다.

## 저장소 지도

```text
ansible/                 canonical host와 cluster bootstrap
bootstrap/               root Application
apps/                    AppProject와 Argo CD Applications
charts/tapple-server/    prod, dev, preview 앱 차트
charts/tapple-secrets/   값 없는 Secrets Manager/ESO 계약
manifests/cluster/       namespace, PSA, quota, priority, health gate
manifests/postgres*/     환경별 PostgreSQL, role, policy, backup
manifests/monitoring/    dashboard와 alert rule 산출물
infra/aws/               ESO IAM과 backup S3 CloudFormation
scripts/                 정적 산출물 생성과 수동 secret-zero 도구
docs/                    설계와 운영 설명
runbooks/                실패 시 그대로 실행할 절차
```

모니터링 dashboard와 rule의 원본은 v1 `tapple-infra/monitoring/grafana/config`다.
이 저장소의 `manifests/monitoring/*`는 생성된 산출물이다.

```bash
python3 scripts/gen-configmaps.py ../tapple-infra/monitoring/grafana/config
```

다이어그램은 [재생성 안내](docs/diagrams/README.md)를 따른다.

## 로컬 검증

CI와 같은 핵심 검증은 GitHub의 `Static validation` workflow가 수행한다.
변경 전 필요한 도구 버전은 workflow와 Ansible requirements에 고정돼 있다.

```bash
helm lint charts/tapple-server --set-string image.tag=ci
helm template prod charts/tapple-server --set-string image.tag=ci >/tmp/tapple-prod.yaml
helm template dev charts/tapple-server -f charts/tapple-server/values-dev.yaml \
  --set-string image.tag=ci >/tmp/tapple-dev.yaml
helm template secrets charts/tapple-secrets \
  --set-string aws.accountId=123456789012 >/tmp/tapple-secrets.yaml

cd ansible
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
ansible-playbook --syntax-check playbooks/bootstrap.yml
ansible-playbook --check --tags preflight playbooks/bootstrap.yml
```

임시 렌더 파일에는 시크릿 값이 없어야 한다.
AWS 계정 ID는 비밀이 아닌 public config이므로 실제 12자리 값을 values에 커밋한다.
IDC inventory와 AWS credential은 공개 저장소에 커밋하지 않는다.

## 최초 설치

1. 두 저장소의 workflow 변경을 올리고 infra `Static validation`을 통과한다.
2. [GitHub trust root](docs/github-trust-root.md) 순서대로 조직 2FA와 branch protection을 적용한다.
3. prod와 dev의 첫 trusted deploy PR로 빈 image digest를 채운다.
4. 실제 AWS 계정 ID를 `charts/tapple-secrets/values.yaml`에 PR로 넣고, [시크릿 계약](secrets/README.md)에 따라 IAM과 16개 JSON source를 준비한다.
5. `ansible/inventories/idc/hosts.example.yml`을 저장소 밖의 `hosts.yml`로 복사한다.
6. 실제 IDC IP, SSH 사용자, 관리자 CIDR을 검토하고 `bootstrap_confirm=true`를 설정한다.
7. `ansible-playbook playbooks/bootstrap.yml`을 실행한다.
8. root Application과 20개 ExternalSecret의 상태를 확인한다.

trust root와 prod/dev digest, AWS account ID가 비어 있으면 Ansible bootstrap을 시작하지 않는다.

Ansible은 AWS access key를 hidden prompt 또는 승인된 controller secret store에서 받는다.
평문 자격증명을 inventory, `--extra-vars`, 환경 출력, Git diff에 넣지 않는다.

## 남은 운영 gate

- [ ] 실제 IDC 사양, 디스크, 회선, 원격 손 SLA를 확정한다.
- [ ] AWS 계정 ID와 16개 JSON source를 준비하고 20개 ExternalSecret의 `Ready=True`를 확인한다.
- [ ] GitHub secret scanning, push protection, 조직 2FA, trust-root 규칙을 활성화한다.
- [ ] trust root 후 prod와 dev의 첫 배포 PR로 실제 image digest를 채우고 `repository@digest`를 확인한다.
- [ ] fork PR이 backend image, preview, deploy 경로를 실행하지 않는지 실제 PR로 확인한다.
- [ ] infra fork 검증이 read-only token과 GitHub-hosted runner만 쓰는지 확인한다.
- [ ] default-deny 후 DNS, DB, OTel, public HTTPS와 private CIDR 차단을 실제 k3s에서 확인한다.
- [ ] 앱과 Grafana의 실제 host, Cloudflare origin TLS, proxied DNS를 준비한 뒤 Ingress를 켠다.
- [ ] [backup 활성화 runbook](runbooks/backup-activation.md)의 수동 backup과 외부 restore를 통과한다.
- [ ] RPO와 RTO를 기록한 뒤에만 `pg-backup.spec.suspend`를 `false`로 바꾼다.
- [ ] IDC 밖 uptime monitor를 구성한다.
- [ ] 기존 홈서버 self-hosted 배포 workflow를 컷오버 때 중지한다.

백업 CronJob은 현재 `suspend: true`다.
실제 S3와 restore 증거 없이 이 값을 바꾸지 않는다.
전체 노드 복구는 [재해 복구 런북](runbooks/disaster-recovery.md)을 따른다.
Grafana 계정과 TLS는 [모니터링 접근](docs/monitoring-access.md)을 따른다.
DB 관리 작업은 [DB 접근](docs/db-access.md)을 따른다.
