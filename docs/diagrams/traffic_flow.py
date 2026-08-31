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
from diagrams.generic.storage import Storage
from diagrams.onprem.client import Users
from diagrams.onprem.logging import Loki
from diagrams.onprem.monitoring import Grafana, Prometheus
from diagrams.onprem.network import Internet, Traefik
from diagrams.onprem.tracing import Tempo

from theme import THEMES, cluster_attr, edge_attr, graph_attr, node_attr

DATA = "#4C8FD0"   # 사용자 요청 경로
TELEM = "#A175D8"  # 관측 데이터 (push)
OPS = "#E5534B"    # 운영자·팀원 접근


def build(theme: dict) -> None:
    ca = cluster_attr(theme)

    with Diagram(
        "tapple 트래픽 흐름  (파랑 요청 · 보라 관측 · 빨강 운영 접근)",
        filename=f"out/traffic-flow{theme['name']}",
        outformat="png",
        show=False,
        graph_attr=graph_attr(theme, rankdir="LR"),
        node_attr=node_attr(theme),
        edge_attr=edge_attr(theme),
    ):
        public = Users("사용자")
        edge = Internet("Cloudflare edge\nTLS proxy")
        team = Users("팀원")

        with Cluster("ns kube-system", graph_attr=ca):
            traefik = Traefik("traefik\n80 / 443")
            api = API("kube-apiserver\n:6443 CIDR allowlist")

        with Cluster("ns app  ·  prod", graph_attr=ca):
            ing = Ingress("api.<domain>")
            svc = Service("tapple-server\n:80")
            app = Deployment("tapple-server\n8080")

        with Cluster("ns db  ·  prod", graph_attr=ca):
            pg = StatefulSet("postgres:16\nDB tapple")
            backup = Cronjob("pg-backup")

        with Cluster("ns dev-app  ·  dev", graph_attr=ca):
            ing_d = Ingress("dev-api.<domain>")
            app_d = Deployment("tapple-server")

        with Cluster("ns dev-db  ·  dev", graph_attr=ca):
            pg_d = StatefulSet("postgres:16\nDB tapple_dev")

        with Cluster("ns monitoring  ·  prod·dev 공용", graph_attr=ca):
            graf_ing = Ingress("grafana-k3s.<domain>")
            collector = Prometheus("otel-collector\n:4318")
            tempo = Tempo("tempo")
            loki = Loki("loki")
            prom = Prometheus("prometheus")
            graf = Grafana("grafana")

        s3 = Storage("오브젝트 스토리지\n(백업 대상)")

        # 사용자 요청 경로
        public >> Edge(color=DATA, label="HTTPS") >> edge
        edge >> Edge(color=DATA, label="HTTPS · origin TLS") >> traefik
        traefik >> Edge(color=DATA, label="Host 매칭") >> ing >> Edge(color=DATA) >> svc
        svc >> Edge(color=DATA) >> app
        app >> Edge(color=DATA, label="jdbc  postgres.db.svc") >> pg

        traefik >> Edge(color=DATA, style="dashed") >> ing_d >> Edge(color=DATA, style="dashed") >> app_d
        app_d >> Edge(color=DATA, style="dashed", label="jdbc  postgres.dev-db.svc") >> pg_d

        # 관측 — 앱이 밀어 넣는다 (scrape 아님)
        app >> Edge(color=TELEM, label="OTLP push") >> collector
        app_d >> Edge(color=TELEM, style="dashed") >> collector
        collector >> Edge(color=TELEM, label="traces") >> tempo
        collector >> Edge(color=TELEM, label="logs") >> loki
        collector >> Edge(color=TELEM, label="metrics") >> prom
        graf << Edge(color=TELEM, style="dotted", label="데이터소스") << tempo
        graf << Edge(color=TELEM, style="dotted") << loki
        graf << Edge(color=TELEM, style="dotted") << prom

        # DB는 CIDR allowlist + 최소권한 RBAC로 API port-forward. Grafana는 승인 로컬 계정.
        team >> Edge(color=OPS, style="dotted", label="제한 kubeconfig") >> api
        api >> Edge(color=OPS, style="dotted", label="RBAC port-forward") >> pg
        api >> Edge(color=OPS, style="dotted") >> pg_d
        team >> Edge(color=OPS, style="dotted", label="HTTPS · 승인 계정") >> edge
        traefik >> Edge(color=OPS, style="dotted") >> graf_ing >> Edge(color=OPS, style="dotted") >> graf

        backup >> Edge(color=OPS, label="컷오버 후 매일\n현재 suspend") >> s3


if __name__ == "__main__":
    for t in THEMES:
        build(t)
    print("out/traffic-flow{,-dark}.png 생성")
