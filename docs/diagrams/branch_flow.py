"""브랜치 하나가 올라가는 경로 — 기능 브랜치부터 prod 까지, 그리고 되돌리기.

cicd_flow.py 는 "push 하면 어떻게 배포되나"를 그린다. 이 그림은 그 앞단이다:
기능 브랜치를 따서 dev 를 거쳐 prod 까지 올리는 순서와, 잘못됐을 때 되돌리는 두 경로.

앱 승격은 사람이 결정하고, 각 환경의 infra tag+digest 변경은 PR·필수 CI·
squash auto-merge를 거친다. 조직 2FA와 branch protection은 순서가 있는 컷오버 작업이다.

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


def dark_icon_panel(theme: dict, width: str = "1.75") -> dict:
    """Back black GitHub/user icons with a light panel in dark renders only."""
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
    with Diagram(
        "브랜치 하나가 올라가는 길  (주황 = 사람이 누름 · 파랑 = 자동 · 빨강 = 되돌리기)",
        filename=f"out/branch-flow{theme['name']}",
        outformat="png",
        show=False,
        graph_attr=graph_attr(theme, rankdir="LR", ranksep="0.8", nodesep="0.5"),
        node_attr=node_attr(theme),
        edge_attr=edge_attr(theme),
    ):
        me = User("maintainer", **dark_icon_panel(theme, width="1.25"))

        with Cluster("tapple-be", graph_attr=ca):
            feat = Git("feat/xxx\n기능 브랜치")
            dev_br = Github("dev", **dark_panel)
            main_br = Github("main", **dark_panel)

        cd_dev = GithubActions("cd-gitops.yml\ndev run")
        cd_prod = GithubActions("cd-gitops.yml\nprod run")

        with Cluster("tapple-infra-v2", graph_attr=ca):
            pr_dev = Github("deploy/dev/<tag>-<digest>\nvalues-dev image PR", **dark_panel)
            pr_prod = Github("deploy/prod/<tag>-<digest>\nvalues image PR", **dark_panel)
            checks = GithubActions("Static validation\nrequired · strict")
            infra_main = Github(
                "origin/main\nstaged: 2FA 수동 → protection\nPR only · approval 0",
                **dark_icon_panel(theme, width="2.1"),
            )
            revert_pr = Git("known-good tag + digest\nrevert PR")

        argo = Argocd("ArgoCD\nself-heal")

        with Cluster("k3s", graph_attr=ca):
            with Cluster("dev-app  검증", graph_attr=ca):
                dev_pod = Deployment("tapple-server\ndev")
            with Cluster("app  운영", graph_attr=ca):
                prod_pod = Deployment("tapple-server\nprod")

        # 올리는 길 — 앱 승격은 사람, infra tag PR부터는 자동이다.
        me >> Edge(label="① 브랜치 따서 작업", color=MANUAL, fontcolor=MANUAL) >> feat
        feat >> Edge(label="② PR → Squash 머지", color=MANUAL, fontcolor=MANUAL) >> dev_br

        dev_br >> Edge(label="자동 트리거", color=AUTO, fontcolor=AUTO) >> cd_dev
        cd_dev >> Edge(label="SHA image + digest PR", color=AUTO, fontcolor=AUTO) >> pr_dev
        pr_dev >> Edge(label="필수 CI", color=AUTO, fontcolor=AUTO) >> checks

        dev_pod >> Edge(label="③ dev 에서 확인", color=MANUAL, fontcolor=MANUAL, style="dotted") >> me
        dev_br >> Edge(label="④ PR → Merge commit\n(장수 브랜치라 squash 금지)",
                       color=MANUAL, fontcolor=MANUAL) >> main_br

        main_br >> Edge(label="자동 트리거", color=AUTO, fontcolor=AUTO) >> cd_prod
        cd_prod >> Edge(label="SHA image + digest PR", color=AUTO, fontcolor=AUTO) >> pr_prod
        pr_prod >> Edge(label="필수 CI", color=AUTO, fontcolor=AUTO) >> checks
        checks >> Edge(label="squash auto-merge", color=AUTO, fontcolor=AUTO) >> infra_main
        argo >> Edge(label="protected main pull", color=AUTO, fontcolor=AUTO,
                     style="dashed") >> infra_main
        argo >> Edge(label="values-dev", color=AUTO, fontcolor=AUTO) >> dev_pod
        argo >> Edge(label="values prod", color=AUTO, fontcolor=AUTO) >> prod_pod

        # 되돌리는 길 — 두 가지
        prod_pod >> Edge(label="문제 발견", color=BACK, fontcolor=BACK, style="dotted") >> me
        me >> Edge(label="ⓐ ArgoCD UI 에서 이전 버전 선택\n(빠름 · Git 은 그대로)",
                   color=BACK, fontcolor=BACK) >> argo
        me >> Edge(label="ⓑ known-good tag+digest revert PR\n(Git 이 정답지로 남음)",
                   color=BACK, fontcolor=BACK) >> revert_pr
        revert_pr >> Edge(label="필수 CI", color=BACK, fontcolor=BACK) >> checks


if __name__ == "__main__":
    for t in THEMES:
        build(t)
    print("out/branch-flow{,-dark}.png 생성")
