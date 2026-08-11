"""브랜치 하나가 올라가는 경로 — 기능 브랜치부터 prod 까지, 그리고 되돌리기.

cicd_flow.py 는 "push 하면 어떻게 배포되나"를 그린다. 이 그림은 그 앞단이다:
기능 브랜치를 따서 dev 를 거쳐 prod 까지 올리는 순서와, 잘못됐을 때 되돌리는 두 경로.

혼자 운영하는 전제다. 각 단계에서 사람이 눌러야 하는 것과 자동으로 굴러가는 것을 구분한다.

    python branch_flow.py   →  out/branch-flow.png, out/branch-flow-dark.png
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.k8s.compute import Deployment
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import User
from diagrams.onprem.gitops import Argocd
from diagrams.onprem.vcs import Git, Github

from theme import THEMES, cluster_attr, edge_attr, graph_attr, node_attr

MANUAL = "#D68910"   # 사람이 눌러야 하는 것
AUTO = "#4C8FD0"     # 자동
BACK = "#E5534B"     # 되돌리기


def build(theme: dict) -> None:
    ca = cluster_attr(theme)
    with Diagram(
        "브랜치 하나가 올라가는 길  (주황 = 사람이 누름 · 파랑 = 자동 · 빨강 = 되돌리기)",
        filename=f"out/branch-flow{theme['name']}",
        outformat="png",
        show=False,
        graph_attr=graph_attr(theme, rankdir="LR", ranksep="1.2", nodesep="0.7"),
        node_attr=node_attr(theme),
        edge_attr=edge_attr(theme),
    ):
        me = User("개발자\n(혼자)")

        with Cluster("tapple-be", graph_attr=ca):
            feat = Git("feat/xxx\n기능 브랜치")
            dev_br = Github("dev")
            main_br = Github("main")

        cd = GithubActions("cd-gitops.yml")

        with Cluster("tapple-infra-v2", graph_attr=ca):
            vals_dev = Git("values-dev.yaml\ntag")
            vals = Git("values.yaml\ntag")

        argo = Argocd("ArgoCD\nself-heal")

        with Cluster("k3s", graph_attr=ca):
            with Cluster("dev-app  검증", graph_attr=ca):
                dev_pod = Deployment("tapple-server\ndev")
            with Cluster("app  운영", graph_attr=ca):
                prod_pod = Deployment("tapple-server\nprod")

        # 올리는 길 — 사람이 누르는 지점은 두 곳뿐이다
        me >> Edge(label="① 브랜치 따서 작업", color=MANUAL, fontcolor=MANUAL) >> feat
        feat >> Edge(label="② PR → Squash 머지", color=MANUAL, fontcolor=MANUAL) >> dev_br

        dev_br >> Edge(label="자동 트리거", color=AUTO) >> cd
        cd >> Edge(label="dev 태그 커밋", color=AUTO) >> vals_dev
        argo >> Edge(label="pull", color=AUTO, style="dashed") >> vals_dev
        argo >> Edge(color=AUTO) >> dev_pod

        dev_pod >> Edge(label="③ dev 에서 확인", color=MANUAL, fontcolor=MANUAL, style="dotted") >> me
        dev_br >> Edge(label="④ PR → Merge commit\n(장수 브랜치라 squash 금지)",
                       color=MANUAL, fontcolor=MANUAL) >> main_br

        main_br >> Edge(label="자동 트리거", color=AUTO) >> cd
        cd >> Edge(label="prod 태그 커밋", color=AUTO) >> vals
        argo >> Edge(label="pull", color=AUTO, style="dashed") >> vals
        argo >> Edge(color=AUTO) >> prod_pod

        # 되돌리는 길 — 두 가지
        prod_pod >> Edge(label="문제 발견", color=BACK, fontcolor=BACK, style="dotted") >> me
        me >> Edge(label="ⓐ ArgoCD UI 에서 이전 버전 선택\n(빠름 · Git 은 그대로)",
                   color=BACK, fontcolor=BACK) >> argo
        me >> Edge(label="ⓑ git revert → push\n(느림 · Git 이 정답지로 남음)",
                   color=BACK, fontcolor=BACK) >> main_br


if __name__ == "__main__":
    for t in THEMES:
        build(t)
    print("out/branch-flow{,-dark}.png 생성")
