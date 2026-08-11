"""GitOps 제어 흐름 — root-app 하나가 클러스터 전체를 세우는 구조.

이 관계는 ArgoCD Application 의 `directory.recurse: true` 한 줄에 숨어 있어서
YAML 구조상 드러나지 않는다. KubeDiagrams 는 Application 을 일반 커스텀 리소스로만
그리고 root → 자식 관계를 추론하지 못한다. 그래서 손으로 그린다.

sync-wave 가 순서를 정한다. 낮은 수가 먼저다 — 네임스페이스가 없으면 그 안에 뭘 만들 수 없고,
시크릿 컨트롤러가 없으면 시크릿을 풀 수 없고, DB 가 없으면 앱이 뜰 수 없다.

    python gitops_tree.py   →  out/gitops-tree.png, out/gitops-tree-dark.png
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.k8s.ecosystem import Helm
from diagrams.k8s.group import Namespace
from diagrams.k8s.podconfig import Secret
from diagrams.onprem.gitops import Argocd
from diagrams.onprem.monitoring import Grafana
from diagrams.onprem.vcs import Github

from theme import THEMES, cluster_attr, edge_attr, graph_attr, node_attr

WAVE = "#4C8FD0"
DEP = "#E5534B"


def build(theme: dict) -> None:
    ca = cluster_attr(theme)

    with Diagram(
        "GitOps 제어 흐름 — 수동 apply 는 root-app 하나뿐",
        filename=f"out/gitops-tree{theme['name']}",
        outformat="png",
        show=False,
        graph_attr=graph_attr(theme, rankdir="LR", splines="ortho", ranksep="1.5"),
        node_attr=node_attr(theme),
        edge_attr=edge_attr(theme),
    ):
        repo = Github("tapple-infra-v2\nmain")
        root = Argocd("root\nbootstrap/root-app.yaml")

        with Cluster("wave -3  클러스터 기반", graph_attr=ca):
            cluster_app = Namespace("cluster\n네임스페이스 5 + PriorityClass 3")

        with Cluster("wave -2  컨트롤러", graph_attr=ca):
            sealed = Helm("sealed-secrets\nupstream 차트")

        with Cluster("wave -1  시크릿", graph_attr=ca):
            secrets = Secret("secrets\nSealedSecret 9")

        with Cluster("wave 0  데이터베이스", graph_attr=ca):
            pg = Helm("postgres        [db]")
            pg_dev = Helm("dev-postgres  [dev-db]")

        with Cluster("wave 1  앱", graph_attr=ca):
            app = Helm("tapple-server        [app]")
            app_dev = Helm("dev-tapple-server  [dev-app]")

        with Cluster("wave 2  관측", graph_attr=ca):
            mon = Grafana("grafana · prometheus\nloki · tempo · otel-collector\nmonitoring-config")

        root >> Edge(label="apps/ 재귀 sync", color=WAVE) >> cluster_app
        root >> Edge(color=WAVE) >> sealed
        root >> Edge(color=WAVE) >> secrets
        root >> Edge(color=WAVE) >> pg
        root >> Edge(color=WAVE) >> pg_dev
        root >> Edge(color=WAVE) >> app
        root >> Edge(color=WAVE) >> app_dev
        root >> Edge(color=WAVE) >> mon

        root >> Edge(label="3분마다 읽음 (pull)", style="dashed", color=DEP, fontcolor=DEP) >> repo

        # 순서 의존 — 앞이 없으면 뒤가 성립하지 않는다
        cluster_app >> Edge(label="네임스페이스가 있어야", style="dotted") >> secrets
        sealed >> Edge(label="컨트롤러가 있어야 복호화", style="dotted") >> secrets
        secrets >> Edge(label="자격증명이 있어야 기동", style="dotted") >> pg
        pg >> Edge(label="DB 가 있어야 Flyway", style="dotted") >> app


if __name__ == "__main__":
    for t in THEMES:
        build(t)
    print("out/gitops-tree{,-dark}.png 생성")
