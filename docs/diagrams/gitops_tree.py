"""GitOps 동기화 순서 — root Application의 app-of-apps health gate.

이 그림은 AWS 시크릿 공급망이나 실제 워크로드 토폴로지를 다루지 않는다.
root가 만드는 child Application/ApplicationSet과 wave별 진행 조건만 보여준다.

Application health customization이 child Application의 상태를 root에 전파하고,
SecretStore/ExternalSecret health customization이 secrets Application의 상태에 반영돼야
"Healthy 이후 다음 wave"가 실제 준비 순서가 된다.

    python gitops_tree.py   →  out/gitops-tree.png, out/gitops-tree-dark.png
"""

from diagrams import Diagram, Edge
from diagrams.k8s.others import CRD
from diagrams.onprem.gitops import Argocd
from diagrams.onprem.vcs import Github

from theme import THEMES, edge_attr, graph_attr, node_attr

SYNC = "#4C8FD0"
GATE = "#2E8B57"
NOTE = "#D68910"


def build(theme: dict) -> None:
    fg = theme["fg"]

    with Diagram(
        "GitOps 동기화 순서 — 각 wave가 Healthy여야 다음 단계로 진행",
        filename=f"out/gitops-tree{theme['name']}",
        outformat="png",
        show=False,
        graph_attr=graph_attr(
            theme,
            rankdir="LR",
            splines="ortho",
            ranksep="1.0",
            nodesep="0.5",
        ),
        node_attr=node_attr(theme),
        edge_attr=edge_attr(theme),
    ):
        repo = Github("tapple-infra-v2\nmain", fontcolor=fg)
        root = Argocd("root Application\napps/ 재귀 sync", fontcolor=fg)

        wave_cluster = Argocd(
            "wave -3\ncluster\nApplication 1",
            fontcolor=fg,
        )
        wave_eso = Argocd(
            "wave -2\nexternal-secrets\nApplication 1",
            fontcolor=fg,
        )
        wave_secrets = Argocd(
            "wave -1\nsecrets\nApplication 1",
            fontcolor=fg,
        )
        wave_db = Argocd(
            "wave 0\nprod · dev · preview PostgreSQL\nApplication 3",
            fontcolor=fg,
        )
        wave_app = Argocd(
            "wave 1\nprod · dev app: Application 2\npreview: ApplicationSet 1",
            fontcolor=fg,
        )
        wave_monitoring = Argocd(
            "wave 2\nmonitoring stack\nApplication 6",
            fontcolor=fg,
        )

        health = CRD(
            "Health gate\nApplication · ESO CRs\nroot 전에 pre-apply",
            fontcolor=fg,
        )

        repo >> Edge(
            label="3분마다 pull",
            color=SYNC,
            fontcolor=SYNC,
            style="dashed",
        ) >> root

        root >> Edge(label="child CR 생성", color=SYNC, fontcolor=SYNC) >> wave_cluster
        wave_cluster >> Edge(label="Healthy gate", color=GATE, fontcolor=GATE) >> wave_eso
        wave_eso >> Edge(label="Healthy gate", color=GATE, fontcolor=GATE) >> wave_secrets
        wave_secrets >> Edge(label="Secret Ready", color=GATE, fontcolor=GATE) >> wave_db
        wave_db >> Edge(label="DB Ready", color=GATE, fontcolor=GATE) >> wave_app
        wave_app >> Edge(label="App Ready", color=GATE, fontcolor=GATE) >> wave_monitoring

        health >> Edge(
            label="상태를 root에 전파",
            color=NOTE,
            fontcolor=NOTE,
            style="dotted",
        ) >> root


if __name__ == "__main__":
    for t in THEMES:
        build(t)
    print("out/gitops-tree{,-dark}.png 생성")
