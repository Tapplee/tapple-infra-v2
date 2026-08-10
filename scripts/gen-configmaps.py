#!/usr/bin/env python3
"""대시보드 JSON·알림 규칙 원본을 k8s ConfigMap yaml로 변환.

원본은 이 레포가 아니라 tapple-infra(v1)의 monitoring/grafana/config가 소유한다 —
부하 리그(tapple-loadtest)의 monitoring EC2가 같은 경로를 clone해 쓰기 때문.
여기 manifests/monitoring/*은 전부 이 스크립트의 산출물이므로 직접 고치지 말 것.

    python3 scripts/gen-configmaps.py [원본_config_경로]

TODO: 원본이 딴 레포라 크로스 레포 의존이다. v1을 정리할 때 원본 소유를 다시 결정할 것.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(
    sys.argv[1] if len(sys.argv) > 1 else HERE / "../../tapple-infra/monitoring/grafana/config"
).resolve()
OUT = HERE / ".." / "manifests/monitoring"


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


def main() -> None:
    dash_out = OUT / "dashboards"
    dash_out.mkdir(parents=True, exist_ok=True)

    for f in sorted((SRC / "grafana/dashboards").glob("*.json")):
        name = f"dashboard-{f.stem.replace('_', '-')}"
        (dash_out / f"{f.stem}.yaml").write_text(
            configmap(name, f.name, f.read_text(), {"grafana_dashboard": "1"})
        )
        print(f"dashboards/{f.stem}.yaml")

    prom_rules = SRC / "prometheus/rules/default-alerts.yml"
    (OUT / "prometheus-alert-rules.yaml").write_text(
        configmap("prometheus-alert-rules", prom_rules.name, prom_rules.read_text(), {})
    )
    print("prometheus-alert-rules.yaml")

    loki_rules = SRC / "loki/rules/fake/default-log-alerts.yml"
    (OUT / "loki-alert-rules.yaml").write_text(
        configmap("loki-alert-rules", loki_rules.name, loki_rules.read_text(), {})
    )
    print("loki-alert-rules.yaml")


if __name__ == "__main__":
    sys.exit(main())
