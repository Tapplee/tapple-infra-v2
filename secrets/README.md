# secrets — SealedSecret만 커밋

이 디렉터리에는 **kubeseal로 암호화된 SealedSecret yaml만** 둔다.
평문 `kind: Secret` yaml은 절대 커밋 금지.

암호화는 클러스터의 공개키로 하므로 **클러스터 + sealed-secrets 컨트롤러가 뜬 뒤**(Phase 3~4)에야 생성 가능. 그래서 지금은 비어 있다.

## 만들어야 할 시크릿 목록

| 파일 | Secret 이름 | namespace | 키 |
|---|---|---|---|
| `postgres-secrets.yaml` | postgres-secrets | db | POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB(=taple_prod) |
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

차트가 `envFrom: secretRef: app-secrets`로 **통째 주입**한다. 평문으로 둘 값(`POSTGRES_URL`·`OTEL_URL` 등)은 `charts/tapple-server/values.yaml`의 `env`에 있고, 나머지는 전부 여기 들어간다. 원본 계약은 taple-be `infrastructure/src/main/resources/application.yml`.

```
POSTGRES_USERNAME  POSTGRES_PASSWORD
JWT_SECRET_KEY  JWT_ACCESS_EXPIRATION  JWT_REFRESH_EXPIRATION
GOOGLE_CLIENT_ID  GOOGLE_CLIENT_SECRET  GOOGLE_REDIRECT_URI  FRONTEND_GOOGLE_COMPLETE_URI
SWAGGER_REDIRECT_URI  CORS_ALLOWED_ORIGINS
PUBLIC_API_ORIGIN  PUBLIC_SITE_ORIGIN  PUBLIC_ASSET_ORIGIN  PUBLIC_MEDIA_ORIGIN
PUBLIC_SPA_SCRIPT_PATH  PUBLIC_SPA_STYLESHEET_PATH
SHARE_PREVIEW_SERVICE_TOKEN  SHARE_PREVIEW_PREVIOUS_SERVICE_TOKEN  SHARE_PREVIEW_LOG_HMAC_KEY
SLUG_RESERVATION_HMAC_KEY  SLUG_RESERVATION_HMAC_KEY_VERSION
DISCORD_NOTIFY_ID  DISCORD_NOTIFY_TOKEN  DISCORD_ERRORS_ID  DISCORD_ERRORS_TOKEN
HIKARI_MAX_POOL_SIZE  HIKARI_MIN_IDLE
REFRESH_COOKIE_SECURE  REFRESH_COOKIE_SAME_SITE
OTEL_AUTH_HEADER
```

- `HIKARI_MAX_POOL_SIZE`는 **10**을 넘기지 말 것 — postgres `max_connections=60`과 맞춰둔 값이다(계획 §8-4).
- `OTEL_AUTH_HEADER`는 클러스터 내부 collector엔 인증이 없지만 `application-otel.yml`이 필수로 참조한다. 빈 값이라도 키는 있어야 한다.

## 생성 방법 (Phase 3~4)

```bash
# 1) 평문 Secret을 파일로 생성 (클러스터에 apply 하지 않는다. --dry-run 주의)
kubectl create secret generic postgres-secrets -n db \
  --from-literal=POSTGRES_USER=... \
  --from-literal=POSTGRES_PASSWORD=... \
  --from-literal=POSTGRES_DB=taple_prod \
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
