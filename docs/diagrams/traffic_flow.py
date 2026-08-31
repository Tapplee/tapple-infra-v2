"""트래픽 흐름 — 누가 누구를 부르는가.

KubeDiagrams 의 아키텍처 그림은 "무엇이 있는가"(인벤토리)를 매니페스트에서 파생시킨다.
하지만 아래 연결들은 k8s 참조가 아니라 값 안의 문자열이라 도구가 추론할 수 없다.

  app → postgres      POSTGRES_URL 환경변수의 접속 문자열
  app → collector     OTEL_URL 환경변수
  collector → 백엔드  Application 안 valuesObject 의 exporter 설정

그래서 이 그림은 손으로 그린다. 두 그림은 대체 관계가 아니라 축이 다르다.

    python traffic_flow.py   →  out/traffic-flow.png, out/traffic-flow-dark.png
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.k8s.compute import Cronjob, Deployment, StatefulSet
from diagrams.k8s.controlplane import API
from diagrams.k8s.network import Ingress, Service
from diagrams.onprem.client import Users
from diagrams.onprem.logging import Loki
from diagrams.onprem.monitoring import Grafana, Prometheus
from diagrams.onprem.network import Internet, Traefik
from diagrams.onprem.tracing import Tempo

from theme import THEMES, cluster_attr, edge_attr, graph_attr, node_attr

DATA = "#4C8FD0"   # 사용자 요청 경로
TELEM = "#A175D8"  # 관측 데이터 (push)
OPS = "#E5534B"    # 운영자·팀원 접근


def dark_icon_panel(theme: dict, width: str = "1.25") -> dict:
    """Give dark-only black line-art icons a light, readable backing panel."""
    if theme["name"] != "-dark":
        return {}
    return {
        "shape": "box",
        "style": "rounded,filled",
        "fillcolor": "#F8FAFC",
        "color": "#94A3B8",
        "fontcolor": "#111827",
        "penwidth": "1.5",
        "margin": "0.12,0.08",
        "width": width,
    }


def build(theme: dict) -> None:
    ca = cluster_attr(theme)
    dark_panel = dark_icon_panel(theme)
    dark_wide_panel = dark_icon_panel(theme, width="1.85")

    with Diagram(
        "tapple 트래픽 흐름  (파랑 요청 · 보라 관측 · 빨강 운영 접근)",
        filename=f"out/traffic-flow{theme['name']}",
        outformat="png",
        show=False,
        graph_attr=graph_attr(theme, rankdir="LR"),
        node_attr=node_attr(theme),
        edge_attr=edge_attr(theme),
    ):
        public = Users("사용자", **dark_panel)
        edge = Internet("Cloudflare edge\nproxied DNS · TLS", **dark_wide_panel)
        outside = Internet("외부 uptime monitor\nHTTPS + heartbeat", **dark_wide_panel)
        team = Users("팀원", **dark_panel)

        with Cluster("ns kube-system", graph_attr=ca):
            traefik = Traefik("traefik websecure\n443 only · public 80 닫힘\nUFW: Cloudflare CIDR만")
            api = API("kube-apiserver\n:6443 CIDR allowlist")

        with Cluster("ns app  ·  prod", graph_attr=ca):
            ing = Ingress("기본 비활성 Ingress\n실제 host + TLS 후 enable")
            svc = Service("tapple-server\n:80")
            app = Deployment("tapple-server\n8080")

        with Cluster("ns db  ·  prod", graph_attr=ca):
            pg = StatefulSet("postgres 16.15 digest\nDB tapple")
            backup = Cronjob("pg-backup\n03:00 Asia/Seoul\ndeadline 1h · suspend:true")

        with Cluster("ns dev-app  ·  dev", graph_attr=ca):
            ing_d = Ingress("기본 비활성 Ingress\n실제 host + TLS 후 enable")
            app_d = Deployment("tapple-server")

        with Cluster("ns dev-db  ·  dev", graph_attr=ca):
            pg_d = StatefulSet("postgres 16.15 digest\nDB tapple_dev")

        with Cluster("ns monitoring  ·  default-deny ingress", graph_attr=ca):
            graf_ing = Ingress("grafana-k3s.<domain>")
            collector = Prometheus("otel-collector :4317/4318\n512Mi cap · limiter\ntraces 10%")
            tempo = Tempo("tempo\n7d · PVC 5Gi · 768Mi cap")
            loki = Loki("loki")
            prom = Prometheus("prometheus + alertmanager\n실제 scrape target만\n같은-node 소실은 감지 못함")
            graf = Grafana("grafana")

        # 사용자 요청 경로
        public >> Edge(color=DATA, fontcolor=DATA, label="HTTPS") >> edge
        edge >> Edge(color=DATA, fontcolor=DATA,
                     label="HTTPS · origin TLS\nCloudflare source only") >> traefik
        traefik >> Edge(color=DATA, fontcolor=DATA, style="dashed",
                        label="컷오버 후\nHost 매칭") >> ing >> Edge(color=DATA, style="dashed") >> svc
        svc >> Edge(color=DATA) >> app
        app >> Edge(color=DATA, fontcolor=DATA, label="jdbc  postgres.db.svc") >> pg

        traefik >> Edge(color=DATA, style="dashed") >> ing_d >> Edge(color=DATA, style="dashed") >> app_d
        app_d >> Edge(color=DATA, fontcolor=DATA, style="dashed",
                      label="jdbc  postgres.dev-db.svc") >> pg_d

        # 관측 — 앱이 밀어 넣는다 (scrape 아님)
        app >> Edge(color=TELEM, fontcolor=TELEM,
                    label="NetworkPolicy 허용\nOTLP push") >> collector
        app_d >> Edge(color=TELEM, fontcolor=TELEM, style="dashed",
                      label="NetworkPolicy 허용") >> collector
        collector >> Edge(color=TELEM, fontcolor=TELEM, label="traces") >> tempo
        collector >> Edge(color=TELEM, fontcolor=TELEM, label="logs") >> loki
        collector >> Edge(color=TELEM, fontcolor=TELEM, label="metrics") >> prom
        graf << Edge(color=TELEM, fontcolor=TELEM, style="dotted",
                     label="데이터소스") << tempo
        graf << Edge(color=TELEM, style="dotted") << loki
        graf << Edge(color=TELEM, style="dotted") << prom

        # DB는 CIDR allowlist + 최소권한 RBAC로 API port-forward. Grafana는 승인 로컬 계정.
        team >> Edge(color=OPS, fontcolor=OPS, style="dotted",
                     label="제한 kubeconfig") >> api
        api >> Edge(color=OPS, fontcolor=OPS, style="dotted",
                    label="RBAC port-forward") >> pg
        api >> Edge(color=OPS, style="dotted") >> pg_d
        team >> Edge(color=OPS, fontcolor=OPS, style="dotted",
                     label="HTTPS · 승인 계정") >> edge
        traefik >> Edge(color=OPS, style="dotted") >> graf_ing >> Edge(color=OPS, style="dotted") >> graf

        outside >> Edge(color=OPS, fontcolor=OPS, style="dotted",
                        label="노드 밖에서 감시") >> edge


if __name__ == "__main__":
    for t in THEMES:
        build(t)
    print("out/traffic-flow{,-dark}.png 생성")
