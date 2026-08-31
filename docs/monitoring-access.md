# 모니터링 보는 법

브랜치별 지표·로그·트레이스는 Grafana 한 곳에서 본다.

```
https://grafana-k3s.tapple.co.kr
```

운영자가 발급한 Grafana 사용자 이름과 비밀번호로 로그인한다. 공개 회원가입과 익명 접근은
꺼져 있어 **운영자가 직접 만든 계정만** 들어올 수 있다. 자격증명은 승인된 비밀번호 관리
도구로만 전달한다. kubectl이나 kubeconfig는 필요 없다.

> 아직 열리지 않는다면 아래 운영자용 컷오버가 끝나지 않은 상태다.

## 내 PR 환경만 골라 보기

대시보드는 `tapple` 폴더 안에 있다. 각 대시보드 상단의 `Service` 드롭다운에서 환경을 고른다.

| 고를 값 | 무엇 |
|---|---|
| `taple` | prod |
| `taple-dev` | dev |
| `taple-pr27` | PR #27 프리뷰 |

목록은 실제로 데이터가 들어온 서비스만 보여준다. 내 PR이 없다면 아직 요청이 한 건도 없거나
파드가 뜨지 않은 것이다.

## 로그와 트레이스

Explore → 데이터소스 `Loki`에서 다음처럼 조회한다.

```logql
{service_name="taple-pr27"}
{service_name="taple-pr27"} |= "ERROR"
{service_name="taple-pr27"} | json | taskId=`abc123`
```

로그 한 줄의 trace 링크를 누르면 Tempo에서 같은 요청을 따라갈 수 있다. 앱이 OTLP로 직접
전송하므로 파드가 재시작돼도 보존 기간 안의 로그는 남는다. 식별자는 HMAC으로 가려 기록한다.

## 팀원 권한

| 할 수 없는 것 | 이유 |
|---|---|
| 대시보드 수정·삭제 | 기본 권한이 `Viewer`이고 원본은 Git에서 공급된다 |
| 알림 규칙 변경 | 같은 이유 |
| DB 조회 | 별도 최소권한 kubeconfig가 필요하다. [DB 접속 가이드](db-access.md) 참고 |
| Argo CD UI 사용 | 운영자 전용이다 |

프리뷰 앱 Ingress는 기본 비활성이라 아래 외부 health endpoint는 아직 열리지 않는다. 실제
preview host와 PR별 TLS Secret 공급 방식을 정하고 `ingress.enabled=true`로 전환한 뒤에만
사용한다.

```bash
curl "https://pr-27-api.tapple.co.kr/actuator/health"
```

## 운영자용: 최초 공개

Grafana Ingress는 평문 `web(:80)`에 라우팅하지 않고 `websecure(:443)`만 사용한다.
Cloudflare edge와 IDC origin 사이도 암호화하기 위해 Cloudflare Origin Certificate를 필수
Secrets Manager source로 둔다. 이 source가 없으면 ExternalSecret health gate가 후속 wave를
막는다. 호스트 UFW도 공식 Cloudflare IPv4/IPv6 대역에서 오는 `443/tcp`만 받고 공용 80과
source 제한 없는 443은 허용하지 않으므로, DNS proxy를 끄면 origin으로 직접 우회할 수 없다.

### 1. Origin Certificate를 Secrets Manager에 넣기

Cloudflare dashboard에서 `grafana-k3s.tapple.co.kr`을 포함하는 Origin Certificate와 private
key를 발급한다. AWS Secrets Manager에 다음 이름의 JSON Secret을 만든다.

```
/tapple/platform/monitoring/grafana-origin-tls
```

JSON property는 정확히 `certificate`, `private-key` 두 개다. 점이 든 Kubernetes target key는
ESO가 각각 `tls.crt`, `tls.key`로 매핑한다. PEM의 줄바꿈은 JSON 문자열 안에서 `\n`으로
인코딩한다. 아래 자리표 값은 Git·채팅·셸 인자에 넣지 않는다.

```json
{
  "certificate": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n",
  "private-key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
}
```

입력 후 값 대신 동기화 상태와 key 이름만 확인한다.

```bash
kubectl annotate externalsecret grafana-origin-tls -n monitoring \
  external-secrets.io/force-sync="$(date +%s)" --overwrite
kubectl wait --for=condition=Ready externalsecret/grafana-origin-tls \
  -n monitoring --timeout=180s
kubectl get externalsecret grafana-origin-tls -n monitoring \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[0].status,REFRESHED:.status.refreshTime'
kubectl get secret grafana-origin-tls -n monitoring \
  -o go-template='{{range $key, $_ := .data}}{{println $key}}{{end}}'
```

출력 key가 `tls.crt`, `tls.key`이고 ExternalSecret이 Ready여야 한다.

### 2. Cloudflare를 Full (strict)로 열기

1. DNS에 `grafana-k3s A <IDC_PUBLIC_IP>`를 만들고 Proxy를 켠다(orange cloud).
2. SSL/TLS encryption mode를 `Full (strict)`로 둔다. `Flexible`은 사용하지 않는다.
3. edge에서 Always Use HTTPS를 켠다.
4. `https://grafana-k3s.tapple.co.kr/login`이 열리고 Grafana rollout이 완료됐는지 확인한다.

```bash
kubectl rollout status deployment/grafana -n monitoring --timeout=300s
curl -fsSI https://grafana-k3s.tapple.co.kr/login
```

Cloudflare edge 인증서와 Origin Certificate는 용도가 다르다. Universal SSL은 브라우저↔Cloudflare,
Origin Certificate는 Cloudflare↔Traefik 구간을 보호한다. Origin Certificate는 일반 브라우저의
공개 CA 신뢰 대상이 아니므로 origin IP 직접 접속에서 인증서 오류가 나는 것이 정상이다.

### 3. 승인 계정 만들기

운영자는 `/tapple/platform/monitoring/grafana-admin`의 초기 관리자 자격증명으로 로그인한다.
`admin-password`는 승인된 비밀번호 관리 도구에서 **20자 이상의 고유한 임의 값**으로
생성해 AWS에 넣고, Kubernetes Secret 값을 터미널에 출력하지 않는다. Grafana의
`password_policy`는 UI에서 새로 설정하는 비밀번호만 검증하므로 bootstrap
`admin-password`의 강도를 대신 보장하지 않는다.

```
Administration → Users and access → Users → New user
  Login/Email: 팀원 식별값
  Role:        Viewer
  Password:    비밀번호 관리 도구로 만든 고유한 임의 값
```

새 비밀번호 정책은 12자 이상과 대·소문자, 숫자, 특수문자를 요구한다. 팀원에게는 승인된
비밀번호 관리 도구로 전달한다. 권한을 뺄 때는 사용자를 삭제한다. Editor나 Admin은 실제로
대시보드 운영이 필요한 최소 인원에게만 별도로 준다.

`grafana-admin` Secret은 **빈 PVC의 최초 관리자 생성에만** 쓰인다. AWS의
`admin-password`를 바꿔도 기존 PVC 안의 관리자 비밀번호는 자동으로 바뀌지 않으므로 이후
관리자 비밀번호는 Grafana UI에서 회전한다.

## Cloudflare Access를 붙일 때

현재 로컬 계정 allowlist만으로도 미승인 사용자는 Grafana에 로그인할 수 없다. 다만 Grafana
OSS의 로컬 인증에는 MFA가 없으므로, 팀 공개 전 Cloudflare Access의 self-hosted application을
한 겹 더 두는 것을 권장한다.

- 정책은 deny-by-default로 두고 `Emails` selector에 승인 이메일을 한 명씩 넣는다.
- UFW는 이미 443 source를 공식 Cloudflare 대역으로 제한한다. 따라서 origin IP 직접 접속은
  방화벽에서 막히며 Access를 우회할 수 없다. Cloudflare CIDR 변경 시 Ansible의 고정 목록을
  공식 목록과 대조해 갱신해야 이 경계가 계속 유효하다.
- Grafana 로컬 로그인은 두 번째 게이트로 유지한다.

이 클러스터 전체 ingress를 Tunnel로 바꾸는 것은 앱 트래픽 경로까지 바꾸므로 이번 bootstrap
범위에는 넣지 않았다. 적용할 때는 Grafana 한 hostname으로 먼저 검증한다. 구체적인 token
검증 조건은 [Cloudflare의 self-hosted application 가이드](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)를 따른다.

## 왜 Google OAuth를 쓰지 않는가

`allow_sign_up=false`만으로는 미리 만든 로컬 사용자를 Google identity와 안전하게 이메일
매칭하지 못한다. 이를 강제로 연결하는 `oauth_allow_insecure_email_lookup`은 Grafana도 대부분의
환경에서 권장하지 않는다. `gmail.com`을 `allowed_domains`로 허용하는 방식은 사실상 모든
Google 계정을 허용하므로 승인 명단도 아니다. 근거와 예외 조건은
[Grafana 인증 가이드의 email lookup 항목](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/#enable-email-lookup)에 정리돼 있다.

현재처럼 운영자가 몇 명만 관리하는 단일 팀에서는 로컬 계정이 가장 작은 동작 단위다. 인원이
늘고 Google Workspace 그룹이나 중앙 IdP가 생기면 그때 그룹 기반 SSO로 바꾼다.

## 인증서 회전

Origin Certificate 만료 전에 새 인증서와 key를 Secrets Manager의 같은 JSON source에 새
version으로 넣고 ExternalSecret을 즉시 동기화한다.

```bash
kubectl annotate externalsecret grafana-origin-tls -n monitoring \
  external-secrets.io/force-sync="$(date +%s)" --overwrite
kubectl wait --for=condition=Ready externalsecret/grafana-origin-tls \
  -n monitoring --timeout=180s
```

Traefik은 TLS Secret 변경을 감시하므로 Grafana 재시작은 필요 없다. Full (strict) 상태에서
외부 HTTPS 요청이 성공하는지 확인한 다음 Secrets Manager의 이전 version을 폐기한다.

## 네트워크와 알림의 경계

`monitoring` namespace는 default-deny ingress다. 같은 namespace의 수집·조회 트래픽,
`app`·`dev-app`·`preview`에서 OTel Collector 4317/4318로 보내는 OTLP, 그리고
`kube-system`의 Traefik에서 Grafana 3000으로 오는 경로만 별도 허용한다. egress는 제한하지
않으며, 이 정책은 승인 계정이나 Cloudflare Access를 대신하지 않는다.

현재 availability alert는 실제 scrape target인 node-exporter, Tempo, OTel Collector, Loki,
Prometheus, Alertmanager, Grafana를 대상으로 한다. 여기에 노드 CPU·메모리·디스크, API
오류율·지연, Hikari pool, OTel export 실패 알림이 있다. scrape하지 않는 PostgreSQL·Redis,
외부 HTTP health나 인증서 만료는 이 Prometheus가 감시한다고 가정하지 않는다.

가장 중요한 한계는 **모니터와 대상이 같은 단일 노드에 있다는 것**이다. `NodeExporterDown`은
Prometheus가 살아 있을 때 exporter 또는 내부 scrape 경로 장애만 알려준다. 물리 노드·k3s·회선
전체가 죽으면 Prometheus와 Alertmanager도 같이 죽어 Discord를 보낼 수 없다. 운영 전 IDC 밖의
uptime monitor로 Cloudflare HTTPS와 별도 heartbeat를 확인해야 한다.

## 복구 시 예외 상태

사용자 목록은 Grafana sqlite가 있는 local-path PVC에 저장된다. 노드가 소실되면 대시보드와
데이터소스는 Git에서 돌아오지만 팀원 계정은 돌아오지 않는다. 현재 인원에서는 계정을 다시
만드는 편이 별도 사용자 DB 백업보다 단순하다. 복구 절차는
[재해 복구 런북](../runbooks/disaster-recovery.md)에 포함돼 있다.

Traefik의 `trustedIPs`에 Cloudflare 대역을 넣기 전에는 접속 로그와 rate limit에 실제 사용자
IP 대신 Cloudflare IP가 찍힌다는 운영 부채도 남아 있다.
