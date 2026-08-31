#!/usr/bin/env python3
"""대시보드 JSON·알림 규칙 원본을 k8s ConfigMap yaml로 변환.

원본은 이 레포가 아니라 tapple-infra(v1)의 monitoring/grafana/config가 소유한다 —
부하 리그(tapple-loadtest)의 monitoring EC2가 같은 경로를 clone해 쓰기 때문.
여기 manifests/monitoring/*은 전부 이 스크립트의 산출물이므로 직접 고치지 말 것.

    python3 scripts/gen-configmaps.py [원본_config_경로]

TODO: 원본이 딴 레포라 크로스 레포 의존이다. v1을 정리할 때 원본 소유를 다시 결정할 것.
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(
    sys.argv[1] if len(sys.argv) > 1 else HERE / "../../tapple-infra/monitoring/grafana/config"
).resolve()
OUT = HERE / ".." / "manifests/monitoring"

# v1 원본에 남아 있지만 v2 k3s에는 대응 scrape target이 없거나 전용 alert와 중복되는
# rule을 원본 변경 없이 v2 산출물에서만 제거한다. 이름이 사라지면 생성 단계가 실패하도록
# 해 upstream 변경을 조용히 삼키지 않는다.
K3S_DROPPED_ALERTS = frozenset(
    {
        "ApiServerDown",
        "PrometheusTargetDown",
        "PostgreSQLDown",
        "RedisDown",
        "RedisMemoryHighUsage",
        "RedisRejectedConnections",
        "SSLCertificateExpiresSoon",
        "ExternalHttpHealthCheckFailed",
        "ApiHealthCheckFailed",
    }
)
ALERT_START = re.compile(r"^(?P<indent> *)- alert: (?P<name>[^ ]+)\s*$")
AVAILABILITY_MARKER = "  - name: taple.availability\n    rules:\n"
OBSERVABILITY_MARKER = "  - name: taple.observability\n    rules:\n"
COMMENTED_NODE_EXPORTER_ALERT = """\
      # - alert: NodeExporterDown
      #   expr: up{job="node-exporter"} == 0
      #   for: 3m
      #   labels:
      #     severity: warning
      #   annotations:
      #     summary: "Node exporter is down"
      #     description: "Host metrics are not being scraped from {{ $labels.instance }}."

"""
K3S_STATIC_ALERTS = """\
      # k3s에서는 아래 세 Service/port가 실제 Helm render에 존재한다.
      - alert: NodeExporterDown
        expr: up{job="node-exporter"} == 0
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Node exporter scrape를 확인해주세요"
          description: "instance={{ $labels.instance }} 의 exporter 또는 cluster 내부 scrape 경로가 3분 이상 응답하지 않아요. 전체 node/cluster 장애 탐지는 외부 모니터가 별도로 필요해요."

      - alert: TempoDown
        expr: up{job="tempo"} == 0
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Tempo metrics endpoint를 확인해주세요"
          description: "instance={{ $labels.instance }} 의 Tempo metrics endpoint를 3분 이상 scrape하지 못했어요. Tempo pod, Service와 storage 상태를 확인해주세요."

      - alert: KubeStateMetricsDown
        expr: up{job="kube-state-metrics"} == 0
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "kube-state-metrics scrape를 확인해주세요"
          description: "instance={{ $labels.instance }} 에서 backup Job/CronJob 상태 지표를 3분 이상 받지 못했어요. kube-state-metrics pod와 Service를 확인해주세요."

"""
K3S_OBSERVABILITY_ALERTS = """\
      # 100% sampling 정책과 실제 전달 성공은 다르다. Collector가 span을 거부하거나
      # exporter queue가 포화되면 유실 가능성이 있으므로 별도 경보로 드러낸다.
      - alert: OTelCollectorTraceReceiveRefusals
        expr: sum by (receiver, transport, instance) (rate(otelcol_receiver_refused_spans[5m]) or rate(otelcol_receiver_refused_spans_total[5m])) > 0
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "OTel Collector가 trace 수신을 거부하고 있어요"
          description: "receiver={{ $labels.receiver }}, instance={{ $labels.instance }} 에서 span이 3분 이상 거부되고 있어요. memory limiter, Collector RSS와 client retry를 확인해주세요."

      - alert: OTelCollectorTraceEnqueueFailures
        expr: sum by (exporter, instance) (rate(otelcol_exporter_enqueue_failed_spans[5m]) or rate(otelcol_exporter_enqueue_failed_spans_total[5m])) > 0
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "OTel Collector trace queue 유실을 확인해주세요"
          description: "exporter={{ $labels.exporter }}, instance={{ $labels.instance }} 의 queue에 span을 넣지 못하고 있어요. Tempo 처리량과 exporter queue를 확인해주세요."

      - alert: OTelCollectorExporterQueueHigh
        expr: max by (exporter, data_type, instance) (otelcol_exporter_queue_size{data_type="traces"} / clamp_min(otelcol_exporter_queue_capacity{data_type="traces"}, 1)) > 0.7
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "OTel Collector exporter queue가 70%를 넘었어요"
          description: "exporter={{ $labels.exporter }}, data_type={{ $labels.data_type }}, instance={{ $labels.instance }} 의 queue가 5분 이상 70%를 넘었어요. downstream 지연과 trace 유입량을 확인해주세요."

      - alert: PostgresBackupFailed
        expr: max by (namespace, job_name) (kube_job_failed{namespace="db",job_name=~"pg-backup-.+",condition="true"}) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "PostgreSQL S3 backup Job이 실패했어요"
          description: "job={{ $labels.job_name }} 의 dump, checksum, S3 권한과 bucket 상태를 확인해주세요."

      - alert: PostgresBackupNeverSucceeded
        expr: kube_cronjob_spec_suspend{namespace="db",cronjob="pg-backup"} == 0 unless on (namespace, cronjob) kube_cronjob_status_last_successful_time{namespace="db",cronjob="pg-backup"}
        for: 27h
        labels:
          severity: critical
        annotations:
          summary: "활성화된 PostgreSQL S3 backup의 정규 성공 기록이 없어요"
          description: "pg-backup을 활성화한 뒤 27시간 동안 CronJob status에 성공 기록이 없어요. 첫 schedule, controller, Job과 S3 writer 권한을 확인해주세요. 수동 create job은 이 status를 채우지 않아요."

      - alert: PostgresBackupStale
        expr: kube_cronjob_spec_suspend{namespace="db",cronjob="pg-backup"} == 0 and on (namespace, cronjob) time() - kube_cronjob_status_last_successful_time{namespace="db",cronjob="pg-backup"} > 108000
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "최근 PostgreSQL S3 backup 성공 기록이 없어요"
          description: "활성화된 pg-backup의 마지막 정규 성공이 30시간을 넘었어요. CronJob, ExternalSecret과 S3 writer 권한을 확인해주세요."

"""
K3S_DASHBOARD_REPLACEMENTS = {
    "api-flow.json": (
        "> trace 샘플링이 1.0 미만이면 HTTP 요청 일부가 누락될 수 있으니, "
        "시연 시 같은 API 를 여러 번 호출하세요.",
        "> k3s prod/dev/preview는 trace sampling을 1.0으로 고정합니다. "
        "요청이 보이지 않으면 Collector의 refused/enqueue/export 경보와 Tempo 상태를 확인하세요.",
    )
}
K3S_PROMETHEUS_COUNTER_REPLACEMENTS = {
    "rate(otelcol_exporter_send_failed_log_records[5m])": (
        "(rate(otelcol_exporter_send_failed_log_records[5m]) or "
        "rate(otelcol_exporter_send_failed_log_records_total[5m]))"
    ),
    "rate(otelcol_exporter_send_failed_metric_points[5m])": (
        "(rate(otelcol_exporter_send_failed_metric_points[5m]) or "
        "rate(otelcol_exporter_send_failed_metric_points_total[5m]))"
    ),
    "rate(otelcol_exporter_send_failed_spans[5m])": (
        "(rate(otelcol_exporter_send_failed_spans[5m]) or "
        "rate(otelcol_exporter_send_failed_spans_total[5m]))"
    ),
}


def block_scalar(text: str, indent: int) -> str:
    pad = " " * indent
    lines = [(pad + ln).rstrip() for ln in text.splitlines()]
    return "\n".join(lines)


def configmap(name: str, filename: str, content: str, labels: dict[str, str]) -> str:
    label_lines = "".join(f"    {k}: \"{v}\"\n" for k, v in labels.items())
    labels_block = f"  labels:\n{label_lines}" if labels else ""
    return (
        "# 자동 생성 — 원본: tapple-infra(v1) monitoring/grafana/config — scripts/gen-configmaps.py 재실행으로 갱신\n"
        "apiVersion: v1\n"
        "kind: ConfigMap\n"
        "metadata:\n"
        f"  name: {name}\n"
        "  namespace: monitoring\n"
        f"{labels_block}"
        "data:\n"
        f"  {filename}: |\n"
        f"{block_scalar(content, 4)}\n"
    )


def drop_alert_rules(content: str, names: frozenset[str]) -> str:
    """Prometheus rule list에서 이름이 일치하는 alert block만 제거한다."""
    lines = content.splitlines(keepends=True)
    output: list[str] = []
    found: set[str] = set()
    index = 0

    while index < len(lines):
        match = ALERT_START.match(lines[index].rstrip("\n"))
        if match is None or match.group("name") not in names:
            output.append(lines[index])
            index += 1
            continue

        found.add(match.group("name"))
        rule_indent = len(match.group("indent"))
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.strip() and len(line) - len(line.lstrip(" ")) <= rule_indent:
                break
            index += 1

    missing = names - found
    if missing:
        raise ValueError(f"v2에서 제거할 alert가 v1 원본에 없습니다: {sorted(missing)}")
    return "".join(output)


def k3s_dashboard(filename: str, content: str) -> str:
    """v1 dashboard의 sampling 안내만 k3s의 100% 정책에 맞춘다."""
    replacement = K3S_DASHBOARD_REPLACEMENTS.get(filename)
    if replacement is None:
        return content
    old, new = replacement
    if content.count(old) != 1:
        raise ValueError(f"{filename}에서 교체할 sampling 안내를 정확히 하나 찾지 못했습니다")
    return content.replace(old, new, 1)


def k3s_prometheus_rules(content: str) -> str:
    """v1 compose rule을 실제 k3s scrape topology에 맞춘다."""
    content = drop_alert_rules(content, K3S_DROPPED_ALERTS)
    content = content.replace(COMMENTED_NODE_EXPORTER_ALERT, "", 1)
    if content.count(AVAILABILITY_MARKER) != 1:
        raise ValueError("taple.availability rule group을 정확히 하나 찾지 못했습니다")
    content = content.replace(
        AVAILABILITY_MARKER,
        AVAILABILITY_MARKER + K3S_STATIC_ALERTS,
        1,
    )
    if content.count(OBSERVABILITY_MARKER) != 1:
        raise ValueError("taple.observability rule group을 정확히 하나 찾지 못했습니다")
    content = content.replace(
        OBSERVABILITY_MARKER,
        OBSERVABILITY_MARKER + K3S_OBSERVABILITY_ALERTS,
        1,
    )
    for old, new in K3S_PROMETHEUS_COUNTER_REPLACEMENTS.items():
        if content.count(old) != 1:
            raise ValueError(f"교체할 OTel counter expression을 정확히 하나 찾지 못했습니다: {old}")
        content = content.replace(old, new, 1)
    return (
        "# tapple-infra-v2 k3s topology 적용: target 없는 alert 제거, static target과 "
        "100% trace 전달 무결성 alert 추가\n"
        + content.rstrip()
        + "\n"
    )


def main() -> None:
    dash_out = OUT / "dashboards"
    dash_out.mkdir(parents=True, exist_ok=True)

    for f in sorted((SRC / "grafana/dashboards").glob("*.json")):
        name = f"dashboard-{f.stem.replace('_', '-')}"
        (dash_out / f"{f.stem}.yaml").write_text(
            configmap(
                name,
                f.name,
                k3s_dashboard(f.name, f.read_text()),
                {"grafana_dashboard": "1"},
            )
        )
        print(f"dashboards/{f.stem}.yaml")

    prom_rules = SRC / "prometheus/rules/default-alerts.yml"
    (OUT / "prometheus-alert-rules.yaml").write_text(
        configmap(
            "prometheus-alert-rules",
            prom_rules.name,
            k3s_prometheus_rules(prom_rules.read_text()),
            {},
        )
    )
    print("prometheus-alert-rules.yaml")

    loki_rules = SRC / "loki/rules/fake/default-log-alerts.yml"
    (OUT / "loki-alert-rules.yaml").write_text(
        configmap("loki-alert-rules", loki_rules.name, loki_rules.read_text(), {})
    )
    print("loki-alert-rules.yaml")


if __name__ == "__main__":
    sys.exit(main())
