# monitoring — 기존 compose 스택(ADR-014)의 k8s 이식

[tapple-infra의 monitoring/grafana](https://github.com/Tapplee/tapple-infra/tree/main/monitoring/grafana)에서 docker-compose로 운영하던 스택을 기반으로 옮겼다. **알림 규칙·대시보드**를 고정하고 retention과 보안 패치는 현재 k3s 운영 정책에 맞췄다. 차트는 upstream + `valuesObject` 인라인 (D16).

| Application | upstream 차트 | 고정 이미지 | 비고 |
|---|---|---|---|
| `otel-collector` | open-telemetry/opentelemetry-collector | otel/opentelemetry-collector-contrib:0.152.0 | OTLP 게이트웨이. 클러스터 내부 통신이라 bearer token 제거, 트레이스 10% 샘플링과 memory limiter 적용(§6) |
| `prometheus` | prometheus-community/prometheus | prom/prometheus:v3.11.3 · alertmanager:v0.32.1 · node-exporter:v1.11.1 | retention 14d, OTLP receiver, Discord 알림 라우팅, 실제 scrape target 기준 규칙 ConfigMap 마운트 |
| `tempo` | grafana/tempo | grafana/tempo:2.10.5 | retention 168h(7d), PVC 5Gi, 256Mi memory ballast |
| `loki` | grafana/loki | grafana/loki:3.7.2 | SingleBinary 모드, retention 90d, 로그 알림 ruler 포함 |
| `grafana` | grafana-community/grafana | grafana/grafana:13.2.0-distroless | 13.0.x 이후 공개 CVE 수정 + read-only root filesystem. datasource uid(prometheus/loki/tempo/alertmanager)는 로컬과 동일, cloudwatch만 제외 |
| `monitoring-config` | (raw manifests) | — | 대시보드 7개·알림 규칙 ConfigMap·NetworkPolicy ([manifests/monitoring](../../../manifests/monitoring)) |

## compose 대비 달라진 점

- 앱→collector 인증 토큰 제거 — 인터넷 경유가 아니라 ClusterIP 내부 통신만 존재
- collector에 트레이스 head sampling 10% 추가 (계획 §6 — Tempo PVC 5Gi 절약)
- collector의 metrics·traces·logs pipeline 첫 processor에 memory limiter(512Mi limit의 80%, spike 25%) 적용
- OTLP는 `app`·`dev-app`·`preview` namespace에서 collector의 4317/4318로만 허용. monitoring은 default-deny ingress이고, Grafana 3000은 Traefik에서만 허용
- cloudwatch datasource 제거 (AWS 이탈)
- 서비스 주소가 컨테이너명 → k8s DNS (`*.monitoring.svc.cluster.local`)
- Grafana는 기존 13.0.1 대신 13.2.0 distroless 보안 이미지 사용
- dashboard sidecar는 `monitoring` namespace의 ConfigMap만 읽고 Secret은 읽지 못함
- sidecar에 admin Secret을 넘기지 않고 Grafana provider가 파일 변경을 polling
- 단일 replica + SQLite PVC라 upgrade는 `Recreate`로 직렬화
- read-only distroless에서 bundled plugin 자동 쓰기 갱신은 끄고 image/chart upgrade로 갱신

## 실제 알림과 단일 노드 한계

Prometheus availability 알림은 render에 존재하는 target만 가리킨다. 현재
`NodeExporterDown`, `TempoDown`, `OTelCollectorDown`, `LokiDown`, `PrometheusDown`,
`AlertmanagerDown`, `GrafanaDown`과 노드 CPU·메모리·디스크, API 오류율·지연,
Hikari pool, OTel export 실패를 감시한다. scrape하지 않는 kube-apiserver·PostgreSQL·Redis와
외부 HTTP/인증서 target을 전제로 한 규칙은 제거했다.

`NodeExporterDown`은 **Prometheus가 살아 있을 때 exporter 또는 내부 scrape 경로가 끊긴 것**만
알 수 있다. Prometheus와 Alertmanager도 같은 물리 노드에 있으므로 노드·클러스터·회선 전체가
죽으면 여기서는 알림을 보낼 수 없다. 그 장애는 IDC 밖의 uptime monitor가 Cloudflare HTTPS와
별도 heartbeat를 확인해야 한다. 단일 노드에서 내부 모니터링만으로 자기 소실을 감지하지
못하는 tradeoff는 의도적으로 남겨 둔다.

## 리소스 경계

| workload | requests | memory limit |
|---|---|---|
| OTel Collector | 100m / 256Mi | 512Mi |
| Tempo | 100m / 512Mi | 768Mi |
| Loki + rules sidecar | 125m / 576Mi | 896Mi |
| Prometheus + reload + Alertmanager + node-exporter | 150m / 896Mi | 1280Mi |
| Grafana + dashboard sidecar + PVC init | 160m / 464Mi | 1184Mi |

manifest에 선언된 app/sidecar/init container를 보수적으로 단순 합하면
**635m / 2704Mi(약 2.64Gi) requests**, memory limit **4640Mi(약 4.53Gi)**다.
위 Grafana 행에는 일회성 PVC ownership init container의 10m/16Mi request와 32Mi limit도
보수적으로 더했다.
prod·dev·preview가 이 스택 하나를 공유하며 `service_name`(`taple` / `taple-dev` /
`taple-pr<번호>`)으로 구분한다. 이 값은 운영 전 예산이며 실제 IDC에서 `kubectl top`과 PVC
증가율을 보고 샘플링·보존·limit을 다시 조정한다.

## 원본 갱신 시

infra/monitoring 쪽 대시보드·규칙을 고치면 `python3 scripts/gen-configmaps.py`로 ConfigMap 재생성 후 커밋.
