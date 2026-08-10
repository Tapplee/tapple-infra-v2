# secrets — SealedSecret만 커밋

이 디렉터리에는 **kubeseal로 암호화된 SealedSecret yaml만** 둔다.
평문 `kind: Secret` yaml은 절대 커밋 금지.

예외로 `sealed-secrets-pub.pem`(컨트롤러 **공개키**)이 함께 있다. 암호화 전용 키라 공개돼도 무해하고 — 그게 공개키의 존재 이유다 — 복호화는 클러스터 안 개인키만 할 수 있다. 이걸 커밋해둔 덕분에 GitHub Actions가 **클러스터 접속 없이** 씰링할 수 있다(아래 "레포에서 씰링하기"). ArgoCD 는 디렉터리에서 yaml 만 읽으므로 이 파일은 무시된다.

> SealedSecret 은 기본적으로 **(네임스페이스, 이름)에 묶여** 암호화된다. 파일의 `namespace:` 를 손으로 바꿔 다른 네임스페이스로 옮기면 컨트롤러가 복호화를 거부한다. 그래서 `app`·`dev-app` 처럼 네임스페이스가 다르면 각각 따로 씰링해야 한다(실측 확인됨).

암호화는 클러스터의 공개키로 한다. 공개키를 이 디렉터리에 커밋해뒀으므로 **클러스터 접속 없이도** 씰링할 수 있다(아래 워크플로). 새 클러스터를 만들었다면 그 클러스터의 공개키로 `sealed-secrets-pub.pem` 을 갱신해야 한다.

## 만들어야 할 시크릿 목록

| 파일 | Secret 이름 | namespace | 키 |
|---|---|---|---|
| `postgres-secrets.yaml` | postgres-secrets | db | POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB(=tapple) |
| `app-secrets.yaml` | app-secrets | app | 아래 "app-secrets 키 목록" 전부 |
| `ghcr-pull.yaml` | ghcr-pull | app | dockerconfigjson (ghcr.io PAT, read:packages) |
| `backup-s3.yaml` | backup-s3 | db | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_ENDPOINT, S3_BUCKET |
| `grafana-admin.yaml` | grafana-admin | monitoring | admin-user, admin-password |
| `alertmanager-discord.yaml` | alertmanager-discord | monitoring | discord-webhook (Discord webhook URL 전문) |
| `dev-postgres-secrets.yaml` | postgres-secrets | **dev-db** | POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB |
| `dev-app-secrets.yaml` | app-secrets | **dev-app** | prod와 같은 키, 값은 dev용 (외부 API는 샌드박스 키 권장) |
| `dev-ghcr-pull.yaml` | ghcr-pull | **dev-app** | dockerconfigjson (prod와 같은 PAT 재사용 가능) |

> 이름이 같아도 네임스페이스가 다르면 별개 Secret이다. dev 파일은 `-n dev-db` / `-n dev-app`으로 만들면 된다.

### app-secrets 키 목록

차트가 `envFrom: secretRef: app-secrets`로 **통째 주입**한다. 평문으로 둘 값(`POSTGRES_URL`·`OTEL_URL`·`SPRING_*`·`DEPLOY_ENV`)은 `charts/tapple-server/values.yaml`의 `env`에 있고, 나머지는 전부 여기 들어간다. 원본 계약은 taple-be `infrastructure/src/main/resources/application.yml`.

**기본값이 없어서 빠지면 앱이 아예 안 뜨는 키** (`${VAR}` 형태, fallback 없음):

```
GOOGLE_CLIENT_ID  GOOGLE_CLIENT_SECRET  GOOGLE_REDIRECT_URI
JWT_SECRET_KEY  JWT_ACCESS_EXPIRATION  JWT_REFRESH_EXPIRATION
S3_BUCKET_NAME  S3_REGION  S3_ACCESS_KEY  S3_SECRET_KEY
SWAGGER_REDIRECT_URI
DISCORD_NOTIFY_ID  DISCORD_NOTIFY_TOKEN  DISCORD_ERRORS_ID  DISCORD_ERRORS_TOKEN
```

**기본값이 있어서 생략 가능하지만 운영값을 넣어야 하는 키**:

```
POSTGRES_USERNAME  POSTGRES_PASSWORD
CORS_ALLOWED_ORIGINS  FRONTEND_GOOGLE_COMPLETE_URI
PUBLIC_SITE_ORIGIN  PUBLIC_API_ORIGIN  PUBLIC_ASSET_ORIGIN  PUBLIC_MEDIA_ORIGIN
PUBLIC_SPA_SCRIPT_PATH  PUBLIC_SPA_STYLESHEET_PATH
SHARE_PREVIEW_SERVICE_TOKEN  SHARE_PREVIEW_PREVIOUS_SERVICE_TOKEN  SHARE_PREVIEW_LOG_HMAC_KEY
SLUG_RESERVATION_HMAC_KEY  SLUG_RESERVATION_HMAC_KEY_VERSION
HIKARI_MAX_POOL_SIZE  HIKARI_MIN_IDLE
REFRESH_COOKIE_SECURE  REFRESH_COOKIE_SAME_SITE
HIBERNATE_SHOW_SQL  OTEL_TRACE_SAMPLE  OTEL_AUTH_HEADER
```

- `HIKARI_MAX_POOL_SIZE`는 **10**을 넘기지 말 것 — postgres `max_connections=60`과 맞춰둔 값이다.
- `OTEL_AUTH_HEADER`는 클러스터 내부 collector에 인증이 없지만 `application-otel.yml`이 참조하므로 키 자체는 있어야 한다.
- `DISCORD_*` 4개는 앱의 알림 웹훅이고, alertmanager가 쓰는 `alertmanager-discord`(웹훅 URL 전문)와 **별개**다. 둘 다 필요하다.

### 테스트 클러스터의 더미 값

임시 VPS 검증 단계에서는 부팅에 필요한 것만 실값이고 나머지는 더미다 — 삭제 예정 서버에 실운영 키를 올려두지 않는다.

| 키 | 테스트 | 이유 |
|---|---|---|
| `POSTGRES_*`, `JWT_*`, `SHARE_PREVIEW_*`, `SLUG_RESERVATION_*` | **실값** | 없으면 부팅·기능 검증 불가 |
| `S3_*`, `AWS_*`, `GOOGLE_CLIENT_SECRET`, `OTEL_AUTH_HEADER` | 더미 | 업로드·로그인은 테스트 범위 밖 (도메인이 nip.io라 OAuth 콜백도 어차피 불일치) |
| `DISCORD_*` | 더미 | 홈서버 `.env`도 `CHANGEME` 상태 |

컷오버 전에 AWS 키·Google 시크릿·JWT 키를 로테이션하고, 그때 실값으로 다시 씰링한다.

## 레포에서 씰링하기 (권장 — SSH 불필요)

`.github/workflows/seal-secret.yml` 이 커밋된 공개키로 씰링해 이 디렉터리에 커밋한다.

1. 이 레포 `Settings → Secrets and variables → Actions` 에 평문을 등록
2. `Actions → Seal secrets → Run workflow` → 대상 선택
3. 봇이 `secrets/*.yaml` 을 갱신 커밋 → ArgoCD 가 반영

| 대상 | 필요한 Actions 시크릿 |
|---|---|
| `ghcr-pull` | `GHCR_USERNAME`, `GHCR_PAT` (classic PAT, `read:packages`) |

`workflow_dispatch` 입력값은 실행 기록에 평문으로 남으므로 **평문을 입력창으로 넘기지 않는다** — 반드시 Actions 시크릿에 넣는다.

## 생성 방법 — 노드에서 직접 (대안)

```bash
# 1) 평문 Secret을 파일로 생성 (클러스터에 apply 하지 않는다. --dry-run 주의)
kubectl create secret generic postgres-secrets -n db \
  --from-literal=POSTGRES_USER=... \
  --from-literal=POSTGRES_PASSWORD=... \
  --from-literal=POSTGRES_DB=tapple \
  --dry-run=client -o yaml > /tmp/plain.yaml

# 2) 암호화 → 이 디렉터리에 저장 → 커밋
kubeseal --format yaml < /tmp/plain.yaml > secrets/postgres-secrets.yaml
rm /tmp/plain.yaml

# ghcr pull secret은 docker-registry 타입으로
kubectl create secret docker-registry ghcr-pull -n app \
  --docker-server=ghcr.io --docker-username=<github-id> --docker-password=<PAT> \
  --dry-run=client -o yaml | kubeseal --format yaml > secrets/ghcr-pull.yaml
```

## 컨트롤러 개인키 백업 (필수 — 안 하면 재구축 시 전부 재발급)

```bash
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o yaml > sealed-secrets-key.yaml
# → 오브젝트 스토리지에 업로드 후 로컬 파일 삭제. 복원 절차는 runbooks/disaster-recovery.md
```
