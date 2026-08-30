# 모니터링 보는 법

브랜치별로 무슨 일이 났는지는 Grafana에서 본다. 지표·로그·트레이스가 한곳에 있다.

```
https://grafana-k3s.tapple.co.kr
```

구글 계정으로 로그인한다. **운영자가 미리 등록한 계정만 들어온다** — 처음이면 운영자에게 구글 이메일을 알려주고 등록을 요청한다.

kubectl도 kubeconfig도 필요 없다. 브라우저만 있으면 된다.

> 아직 안 열렸다면 아래 **[운영자용](#운영자용)** 의 4단계가 남아 있는 상태다. 그동안은 볼 방법이 없다.

---

## 내 PR 환경만 골라 보기

대시보드는 `tapple` **폴더 안**에 있다. 최상위 목록만 보면 비어 보인다.

각 대시보드 상단의 `Service` 드롭다운에서 환경을 고른다.

| 고를 값 | 무엇 |
|---|---|
| `taple` | prod |
| `taple-dev` | dev |
| `taple-pr27` | PR #27 프리뷰 |

이 목록은 하드코딩이 아니라 실제로 데이터가 들어온 것만 뜬다. 내 PR이 안 보이면 아직 요청이 한 건도 안 갔거나 파드가 안 떴다는 뜻이다.

## 로그 찾기

Explore → 데이터소스 `Loki` → 쿼리:

```
{service_name="taple-pr27"}                   내 PR 로그 전부
{service_name="taple-pr27"} |= "ERROR"        에러만
{service_name="taple-pr27"} | json | taskId=`abc123`
```

`kubectl logs`를 쓸 필요가 없다. 앱이 OTLP로 직접 밀어넣으므로 파드가 재시작돼도 지난 로그가 남아 있다.

개인정보는 로그에 안 들어간다 — 식별자는 HMAC으로 해싱돼 찍힌다.

## 트레이스

Loki에서 로그 한 줄을 펼치면 `Tempo`로 넘어가는 링크가 있다. 요청 하나가 어디서 느렸는지 본다.

## 안 되는 것

| | |
|---|---|
| 대시보드 수정·삭제 | 권한이 `Viewer`다. 원본이 Git(v1 레포)이라 여기서 고치면 덮어써진다 |
| 알림 규칙 변경 | 같은 이유 |
| DB 조회 | [db-access.md](db-access.md) — 이건 kubeconfig가 필요하다 |
| ArgoCD UI | 운영자용이다. 내 PR이 떴는지는 URL을 찍어보면 된다 |

```bash
curl "https://pr-27-api.tapple.co.kr/actuator/health"
```

---

## 운영자용

### 지금 상태

레포에는 ExternalSecret 계약이 들어가 있고 **OAuth 스위치가 꺼져 있다.**
남은 것은 네 단계다.

```
① Cloudflare DNS  →  grafana-k3s   A   <IDC_PUBLIC_IP>   [Proxied 🟠]

② Google Cloud Console → 사용자 인증 정보 → OAuth 클라이언트(웹)
     승인된 리다이렉트 URI:  https://grafana-k3s.tapple.co.kr/login/google
     ※ 앱(tapple-be)이 쓰는 클라이언트와 별개로 만든다

③ AWS Secrets Manager에 JSON Secret 하나를 등록
     이름: /tapple/platform/monitoring/grafana-google-oauth
     properties: client-id, client-secret
     값은 비밀 관리 도구에서 복사해 AWS Console의 JSON editor에서 입력

④ apps/platform/monitoring/grafana.yaml 의 auth.google.enabled 를 true 로
```

③의 JSON 구조는 아래처럼 두 property만 갖는다. 예시의 자리표는 실제
값으로 교체하되 Git이나 공유 문서에 저장하지 않는다.

```json
{
  "client-id": "<Google OAuth client ID>",
  "client-secret": "<Google OAuth client secret>"
}
```

등록 후 값을 출력하지 말고 ExternalSecret의 상태와 최종 Secret의
키 이름만 확인한다.

```bash
kubectl annotate externalsecret grafana-google-oauth -n monitoring \
  external-secrets.io/force-sync="$(date +%s)" --overwrite
kubectl wait --for=condition=Ready externalsecret/grafana-google-oauth \
  -n monitoring --timeout=180s
kubectl get externalsecret grafana-google-oauth -n monitoring \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[0].status,REFRESHED:.status.refreshTime'
kubectl get secret grafana-google-oauth -n monitoring \
  -o go-template='{{range $key, $_ := .data}}{{println $key}}{{end}}'
```

`client-id`와 `client-secret` 키가 둘 다 있고 refresh 시간이 갱신된 것을 본 뒤
④를 커밋한다. ArgoCD가 반영하면 롤아웃까지 확인한다.

```bash
kubectl rollout status deployment/grafana -n monitoring --timeout=300s
```

시크릿이 없어도 Grafana는 뜬다 — `envValueFrom`에 `optional: true`를 줬다.
다만 `grafana-google-oauth` ExternalSecret은 Ready=False라 운영 준비가 완료된 상태가
아니다. Ready 확인 전에 OAuth를 켜지 않는다.

### OAuth 클라이언트 시크릿 회전

이후 Google client secret을 바꿀 때는 AWS Console에서 위 JSON Secret의
`client-secret` property만 갱신하고 `client-id`는 유지한 뒤
위 `force-sync` → Ready/refresh 확인 → Grafana 재시작 순서로 한다. Kubernetes
Secret이 바뀌어도 실행 중인 Grafana 프로세스의 환경변수는 바뀌지 않는다.

```bash
kubectl rollout restart deployment/grafana -n monitoring
kubectl rollout status deployment/grafana -n monitoring --timeout=300s
```

자동화가 필요하면 JSON을 명령행 인자에 넣지 말고 보안 임시 파일로 읽힌다.

```bash
umask 077
SECRET_INPUT="$(mktemp)"
trap 'rm -f "$SECRET_INPUT"' EXIT
${EDITOR:-vi} "$SECRET_INPUT"    # JSON 전체를 입력하고 저장
aws secretsmanager put-secret-value \
  --secret-id /tapple/platform/monitoring/grafana-google-oauth \
  --secret-string "file://$SECRET_INPUT"
rm -f "$SECRET_INPUT"
trap - EXIT
```

실제 값은 위 명령의 argv에 들어가지 않지만 임시 파일에는 있으므로 로컬
백업대상이 아닌 안전한 파일시스템에서만 실행하고 즉시 삭제한다. GitHub
Actions/Git에 복사하지 않는다. Secrets Manager가 version을 보관하므로 회전 실패 시에는
직전 version으로 롤백한다.

### 팀원 등록

```
Administration → Users and access → Users → New user
  Email:  팀원의 구글 계정 이메일    ← 정확히 일치해야 매칭된다
  Role:   Viewer
  Password: 비밀 관리 도구로 무작위 생성하고 팀원에게 공유하지 않음
```

운영자는 비밀 관리 도구의 Grafana admin 자격증명으로 UI에 로그인해 명단을
관리한다. `grafana-admin` Kubernetes Secret을 터미널에 출력하지 않는다.

**이메일이 구글 계정과 다르면 `signup is not allowed`가 뜬다.** 이게 유일한 실무 함정이다.

빼는 것도 UI에서 삭제하면 즉시 막힌다.

### 왜 allowed_domains 를 안 쓰나

`allowed_domains`는 도메인으로 거른다. 팀원이 `gmail.com`이면 **구글 계정 있는 전원이 통과**한다. 제한이 아니다.

그래서 `allow_sign_up: false` + 명단 방식을 쓴다. 구글은 "누구인지"만 증명하고 "들어와도 되는지"는 Grafana 사용자 목록이 판정한다. 한 명씩 정확히 통제된다.

`@tapple.co.kr` Google Workspace가 생기면 `allowed_domains`를 추가해 이중으로 걸 수 있다.

### 이 설계가 감수하는 것

**사용자 목록이 Git에 없다.** Grafana의 sqlite(PVC `grafana`, 1Gi, local-path)에 있다. 이 레포 원칙이 "클러스터 정의 전체가 Git 하나로 복원"인데 여기에 예외가 생긴다.

노드가 죽으면 팀원 계정이 사라진다. 명단이 몇 명이라 재등록이 1분이고, [runbooks/disaster-recovery.md](../runbooks/disaster-recovery.md)에 단계로 넣어뒀다. 대시보드는 Git에서 복원되니 사람만 다시 넣으면 된다.

**오리진 IP로 우회가 가능하다.** Cloudflare를 거치게 해도 IP를 아는 사람은 이렇게 들어온다.

```bash
curl -H 'Host: grafana-k3s.tapple.co.kr' \
  "http://${IDC_PUBLIC_IP:?IDC_PUBLIC_IP를 설정하세요}/"
```

인증은 그대로 살아 있으므로(구글 로그인 화면이 뜬다) 얻는 건 "TLS 없이 로그인 화면을 본다"뿐이다. 모든 공개 endpoint를 Cloudflare 실도메인으로 전환한 뒤 ufw에서 80/443을 Cloudflare 대역으로 제한하면 오리진 우회를 막을 수 있다.

**클라이언트 IP가 Cloudflare IP로 찍힌다.** traefik `trustedIPs`에 Cloudflare 대역을 넣기 전까지는 접속 로그와 레이트리밋이 실사용자 IP를 못 본다.

### TLS 를 왜 안 만들었나

`tapple.co.kr`이 Cloudflare DNS이고 Universal SSL이 `*.tapple.co.kr`을 이미 커버한다. Cloudflare가 인증서를 발급·종료하므로 cert-manager도 Let's Encrypt도 필요 없다. 오리진(traefik)은 http로 받는다.

**단 Universal SSL 은 1단 서브도메인까지만 커버한다.**

```
grafana-k3s.tapple.co.kr        ✅
pr-27.api.tapple.co.kr          ❌ 인증서 불일치
```

앱·프리뷰를 실도메인으로 옮길 때 `pr-27-api.tapple.co.kr`처럼 평평하게 잡아야 한다. 2단을 쓰려면 Cloudflare Advanced Certificate Manager(유료)나 오리진 인증서가 필요하다.

### 대안이었던 것

| | 왜 안 골랐나 |
|---|---|
| port-forward + anonymous viewer | 도메인이 이미 있어서 기다릴 이유가 없었다. `anonymous`를 켰다가 Ingress를 열 때 끄는 걸 잊으면 그대로 공개된다 |
| Cloudflare Access | 명단 관리 지점이 하나 늘어난다. `allow_sign_up: false`가 같은 일을 한다 |
| nip.io + cert-manager | Application을 신설해야 하고 도메인 붙으면 버릴 작업 |
| 생 IP + Grafana 자체 계정 | Google OAuth가 IP를 리다이렉트 URI로 받지 않는다. http라 비밀번호가 평문으로 흐른다 |
