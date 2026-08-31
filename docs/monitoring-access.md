# 모니터링 접근

승인된 사용자는 Grafana에서 metric, log, trace를 본다.
kubectl, kubeconfig, Argo CD 권한은 필요하지 않으며 발급하지 않는다.
공개 가입과 익명 접근은 꺼져 있다.

```text
https://grafana-k3s.tapple.co.kr
```

현재 주소가 열리지 않으면 아래 origin TLS와 DNS gate가 끝나지 않은 상태다.

## 사용법

`tapple` folder의 dashboard를 연다.
상단 `Service` 변수로 환경을 고른다.

| 값 | 환경 |
|---|---|
| `taple` | prod |
| `taple-dev` | dev |
| `taple-pr27` | PR 27 preview |

목록에는 실제 data가 들어온 service만 보인다.
preview가 없으면 아직 Pod가 뜨지 않았거나 요청이 없을 수 있다.

Explore의 Loki에서 log를 조회한다.

```logql
{service_name="taple-pr27"}
{service_name="taple-pr27"} |= "ERROR"
{service_name="taple-pr27"} | json | taskId=`abc123`
```

log의 trace link는 같은 요청의 Tempo trace를 연다.
세 환경은 root trace를 `1.0`으로 head sampling한다.
장애, queue 포화, exporter 실패까지 무손실을 보장하지는 않는다.

Viewer는 dashboard와 alert rule을 바꾸지 못한다.
DB와 Argo CD는 인프라 관리자 전용이다.
preview Ingress가 꺼져 있어도 Grafana의 수집 data는 볼 수 있다.

## 최초 공개

Grafana Ingress는 Traefik `websecure`만 사용한다.
UFW는 공식 Cloudflare CIDR의 443만 허용한다.
public 80과 unrestricted 443은 열지 않는다.

### origin certificate

Cloudflare에서 `grafana-k3s.tapple.co.kr`을 포함하는 Origin Certificate를 발급한다.
다음 Secrets Manager source에 JSON으로 저장한다.

```text
/tapple/platform/monitoring/grafana-origin-tls
```

property는 `certificate`와 `private-key`다.
ESO는 이를 `tls.crt`와 `tls.key`로 매핑한다.
PEM 값은 Git, 채팅, 셸 인자에 넣지 않는다.

```bash
before_refresh="$(kubectl get externalsecret grafana-origin-tls -n monitoring \
  -o jsonpath='{.status.refreshTime}')"
kubectl annotate externalsecret grafana-origin-tls -n monitoring \
  external-secrets.io/force-sync="$(date +%s)" --overwrite
kubectl wait --for=condition=Ready externalsecret/grafana-origin-tls \
  -n monitoring --timeout=180s
kubectl get externalsecret grafana-origin-tls -n monitoring \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[0].status,REFRESHED:.status.refreshTime'
```

`refreshTime`이 이전 값과 달라야 한다.
Secret 값은 출력하지 않는다.

### Cloudflare

1. `grafana-k3s A <IDC_PUBLIC_IP>`를 만든다.
2. Proxy를 켠다.
3. SSL/TLS mode를 `Full (strict)`로 둔다.
4. Always Use HTTPS를 켠다.
5. login endpoint와 rollout을 확인한다.

```bash
kubectl rollout status deployment/grafana -n monitoring --timeout=300s
curl -fsSI https://grafana-k3s.tapple.co.kr/login
```

Cloudflare edge certificate는 browser와 Cloudflare 사이를 보호한다.
Origin Certificate는 Cloudflare와 Traefik 사이를 보호한다.
Origin IP 직접 접속에서 public CA 오류가 나는 것은 정상이다.

## 사용자 승인과 회수

초기 관리자는 `/tapple/platform/monitoring/grafana-admin` source에서 온다.
`admin-password`는 20자 이상의 고유한 임의 값으로 만든다.
초기 Secret은 빈 Grafana PVC의 첫 관리자 생성에만 쓰인다.
이후 관리자 password는 Grafana UI에서 회전한다.

```text
Administration -> Users and access -> Users -> New user
Login/Email: 승인된 사용자 식별값
Role: Viewer
Password: 승인된 비밀번호 관리 도구의 고유한 임의 값
```

비밀번호는 승인된 비밀번호 관리 도구로만 전달한다.
회수는 Grafana에서 사용자를 삭제한다.
Editor와 Admin은 dashboard 운영이 필요한 최소 인원에게만 준다.

Grafana local auth에는 MFA가 없다.
MFA가 필요하면 Grafana hostname 하나에 Cloudflare Access를 추가한다.
Access policy는 deny-by-default와 승인 email allowlist를 사용한다.
Grafana local login은 두 번째 gate로 유지한다.
전체 ingress를 Cloudflare Tunnel로 바꾸는 일은 이 범위가 아니다.

Google OAuth는 사용하지 않는다.
`allow_sign_up=false`만으로 기존 local user와 Google identity를 안전하게 연결하지 못한다.
중앙 IdP와 관리되는 group이 생기면 group 기반 SSO를 검토한다.

## certificate 회전

만료 전에 새 certificate와 key를 같은 source의 새 version으로 넣는다.
ExternalSecret을 force-sync한다.
Traefik은 TLS Secret 변경을 감시하므로 Grafana 재시작은 필요 없다.
Full (strict) 외부 요청을 확인한 뒤 이전 version을 폐기한다.

## 관측 경계

`monitoring` namespace는 ingress default-deny다.
같은 namespace의 수집과 조회는 허용한다.
앱 namespace에서 OTel 4317과 4318만 허용한다.
Traefik에서 Grafana 3000만 허용한다.
monitoring egress는 현재 제한하지 않는다.

Prometheus는 node-exporter, Tempo, OTel Collector, Loki, Prometheus, Alertmanager, Grafana를 감시한다.
PostgreSQL, 외부 HTTP health, certificate 만료를 자동으로 감시한다고 가정하지 않는다.
Prometheus와 대상이 같은 단일 노드에 있다.
노드, k3s, 회선이 함께 죽으면 Alertmanager도 알림을 보내지 못한다.
운영 전 IDC 밖 uptime monitor를 구성한다.

Grafana 사용자 목록은 local-path PVC의 SQLite에 있다.
노드 소실 뒤 dashboard와 datasource는 Git에서 돌아온다.
사용자 계정은 다시 만든다.
전체 절차는 [재해 복구 런북](../runbooks/disaster-recovery.md)에 있다.
