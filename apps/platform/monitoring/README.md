# monitoring — 기존 compose 스택(ADR-014)의 k8s 이식

[infra/monitoring/grafana](../../../infra/monitoring/grafana)에서 docker-compose로 운영하던 스택을 그대로 옮긴 것. **이미지 버전·retention·알림 규칙·대시보드 전부 compose 값과 동일**하게 고정했다. 차트는 upstream + `valuesObject` 인라인 (D16).

| Application | upstream 차트 | 이미지 (compose와 동일) | 비고 |
|---|---|---|---|
| `otel-collector` | open-telemetry/opentelemetry-collector | otel/opentelemetry-collector-contrib:0.152.0 | OTLP 게이트웨이. 클러스터 내부 통신이라 bearer token 제거, 트레이스 10% 샘플링 추가(§6) |
| `prometheus` | prometheus-community/prometheus | prom/prometheus:v3.11.3 · alertmanager:v0.32.1 · node-exporter:v1.11.1 | retention 14d, OTLP receiver, Discord 알림 라우팅, 규칙 468줄은 ConfigMap 마운트 |
| `tempo` | grafana/tempo | grafana/tempo:2.10.5 | retention 168h(7d) |
| `loki` | grafana/loki | grafana/loki:3.7.2 | SingleBinary 모드, retention 30d, 로그 알림 ruler 포함 |
| `grafana` | grafana/grafana | grafana/grafana:13.0.1 | datasource uid(prometheus/loki/tempo/alertmanager) 로컬과 동일 — 대시보드가 참조. cloudwatch만 제외(AWS 떠남) |
| `monitoring-config` | (raw manifests) | — | 대시보드 8개 + 알림 규칙 ConfigMap ([manifests/monitoring](../../manifests/monitoring)) |

## compose 대비 달라진 점

- 앱→collector 인증 토큰 제거 — 인터넷 경유가 아니라 ClusterIP 내부 통신만 존재
- collector에 트레이스 head sampling 10% 추가 (계획 §6 — Tempo PVC 5Gi 절약)
- cloudwatch datasource 제거 (AWS 이탈)
- 서비스 주소가 컨테이너명 → k8s DNS (`*.monitoring.svc.cluster.local`)

## 리소스 합계

requests ~0.44 vCPU / 2.2Gi, limits ~3.3Gi — 계획 §4-2 예산 안. prod·dev 두 환경이 이 스택 하나를 공유하며, 라벨(`prod-tapple` / `dev-tapple`)로 구분해서 본다.

## 원본 갱신 시

infra/monitoring 쪽 대시보드·규칙을 고치면 `python3 scripts/gen-configmaps.py`로 ConfigMap 재생성 후 커밋.
