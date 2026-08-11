"""CI/CD 배포 흐름 — 코드 push 부터 클러스터 반영까지.

KubeDiagrams 로는 그릴 수 없다. "Actions 가 ghcr 에 밀고 인프라 레포에 태그를 커밋하면
ArgoCD 가 감지한다"는 어떤 매니페스트에도 적혀 있지 않기 때문이다. 그래서 손으로 그린다.

이 그림이 반드시 전달해야 하는 두 가지:
  1) ArgoCD → GitHub 방향이 pull 이다 (push 아님)
  2) 앱 레포에서 클러스터로 가는 화살표가 없다 — 그게 이 설계의 핵심 성질

    python cicd_flow.py     →  out/cicd-flow.png, out/cicd-flow-dark.png
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.k8s.compute import Deployment
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import User
from diagrams.onprem.container import Docker
from diagrams.onprem.gitops import Argocd
from diagrams.onprem.vcs import Github

from theme import THEMES, cluster_attr, edge_attr, graph_attr, node_attr

PULL = "#E5534B"  # pull 방향 강조. 라이트·다크 양쪽에서 읽히는 채도


def build(theme: dict) -> None:
    ca = cluster_attr(theme)
    with Diagram(
        "tapple 배포 흐름 (GitOps)",
        filename=f"out/cicd-flow{theme['name']}",
        outformat="png",
        show=False,
        graph_attr=graph_attr(theme, rankdir="LR", ranksep="1.4"),
        node_attr=node_attr(theme),
        edge_attr=edge_attr(theme),
    ):
        dev = User("개발자")

        with Cluster("tapple-be  (private)", graph_attr=ca):
            repo_be = Github("main / dev")
            actions = GithubActions("cd-gitops.yml\n브랜치로 환경 판정")

        registry = Docker("ghcr.io/tapplee/tapple-be\n:<커밋 SHA 12자리>")

        with Cluster("tapple-infra-v2  (public)", graph_attr=ca):
            repo_infra = Github("values.yaml (prod)\nvalues-dev.yaml (dev)")

        argo = Argocd("ArgoCD")

        with Cluster("k3s  ·  VPS 1대", graph_attr=ca):
            with Cluster("ns app", graph_attr=ca):
                prod = Deployment("tapple-server\nprod,otel,k3s")
            with Cluster("ns dev-app", graph_attr=ca):
                dev_app = Deployment("tapple-server\ndev,otel,k3s")

        dev >> Edge(label="push") >> repo_be >> Edge(label="트리거") >> actions

        actions >> Edge(label="① 이미지 빌드 → push") >> registry
        actions >> Edge(label="② image.tag 한 줄 커밋", style="dashed") >> repo_infra

        # 이 화살표의 방향이 이 설계의 전부다 — 클러스터가 GitHub 을 읽는다
        argo >> Edge(label="③ 3분마다 읽음 (pull)", color=PULL, fontcolor=PULL) >> repo_infra

        argo >> Edge(label="main → Production") >> prod
        argo >> Edge(label="dev → Development") >> dev_app

        prod >> Edge(label="④ 이미지 pull\n(ghcr-pull)", style="dotted") >> registry
        dev_app >> Edge(style="dotted") >> registry


if __name__ == "__main__":
    for t in THEMES:
        build(t)
    print("out/cicd-flow{,-dark}.png 생성")
