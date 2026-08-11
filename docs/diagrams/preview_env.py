"""PR 프리뷰 환경 — feat 브랜치마다 임시 환경을 띄운다. (제안, 미구현)

목표: PR 을 올리면 그 브랜치만의 URL 이 생기고, PR 을 닫으면 사라진다.
      dev 환경 하나를 여러 작업이 번갈아 쓰면서 서로 덮어쓰는 문제를 없앤다.

장치는 ArgoCD ApplicationSet 의 Pull Request 생성기다. PR 목록을 폴링해
PR 하나당 Application 을 자동으로 만들고, PR 이 닫히면 그 Application 을 지운다.

설계 판단 세 개 (각각 대안이 있었다):

1) 네임스페이스를 PR 마다 만들지 않고 preview 하나로 모은다
   SealedSecret 은 (네임스페이스, 이름)에 묶여 암호화되므로 PR 마다 네임스페이스를 만들면
   시크릿을 재사용할 수 없다. PR 이 열릴 때마다 사람이 씰링해야 하면 자동화가 성립하지 않는다.
   cluster-wide 스코프로 씰링하는 방법도 있지만 그건 그 시크릿을 아무 네임스페이스에서나
   풀 수 있게 만드는 것이라 프리뷰 편의로 감수할 트레이드오프가 아니다.

2) DB 는 프리뷰 전용 postgres 한 대를 공유하고, PR 마다 database 를 따로 만든다
   database 를 나누지 않으면 여러 PR 의 Flyway 가 같은 스키마를 동시에 고쳐 서로를 깬다.
   postgres 를 PR 마다 띄우면 메모리가 남지 않는다(아래 예산).

3) 우선순위를 dev 보다 더 낮게 둔다
   메모리 압박 시 프리뷰가 가장 먼저 죽어야 한다. dev-low 아래 preview-lowest 를 새로 만든다.

    python preview_env.py   →  out/preview-env.png, out/preview-env-dark.png
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.k8s.compute import Deployment, Job, StatefulSet
from diagrams.k8s.network import Ingress
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import User
from diagrams.onprem.container import Docker
from diagrams.onprem.gitops import Argocd
from diagrams.onprem.vcs import Github

from theme import THEMES, cluster_attr, edge_attr, graph_attr, node_attr

NEW = "#D68910"    # 새로 만들어야 하는 것
AUTO = "#4C8FD0"   # 자동
GONE = "#8B95A1"   # PR 닫힐 때 사라지는 것


def build(theme: dict) -> None:
    ca = cluster_attr(theme)
    with Diagram(
        "PR 프리뷰 환경 (제안 · 미구현) — 주황이 새로 만들어야 하는 부분",
        filename=f"out/preview-env{theme['name']}",
        outformat="png",
        show=False,
        graph_attr=graph_attr(theme, rankdir="LR", ranksep="1.3", nodesep="0.6"),
        node_attr=node_attr(theme),
        edge_attr=edge_attr(theme),
    ):
        me = User("개발자")

        with Cluster("tapple-be", graph_attr=ca):
            pr = Github("PR #42\nfeat/new-func")
            cd = GithubActions("cd-gitops.yml\n★ 브랜치 무관 빌드로 확장")

        registry = Docker("ghcr.io/tapplee/tapple-be\n:<PR head SHA>")

        with Cluster("tapple-infra-v2", graph_attr=ca):
            appset = Github("★ applicationset-preview.yaml\nPR 생성기")

        argo = Argocd("ArgoCD\n★ ApplicationSet CRD 필요")

        with Cluster("k3s  ·  ns preview", graph_attr=ca):
            with Cluster("PR 하나당 자동 생성 · 닫으면 삭제", graph_attr=ca):
                ing = Ingress("pr-42.api.<ip>\n.nip.io")
                app = Deployment("tapple-server-pr-42\n1Gi · preview-lowest")
                dbjob = Job("★ createdb Job\ntapple_pr42")
            pg = StatefulSet("★ postgres-preview\n공유 1대 · 1Gi")

        me >> Edge(label="① PR 올린다", color=NEW, fontcolor=NEW) >> pr
        pr >> Edge(label="자동 빌드", color=AUTO) >> cd >> Edge(color=AUTO) >> registry

        argo >> Edge(label="② PR 목록 폴링\n(GitHub 토큰 필요)", color=NEW,
                     fontcolor=NEW, style="dashed") >> appset
        appset >> Edge(label="PR 당 Application 1개", color=NEW, fontcolor=NEW) >> argo

        argo >> Edge(label="③ 생성", color=AUTO) >> ing
        argo >> Edge(color=AUTO) >> app
        argo >> Edge(color=AUTO) >> dbjob

        app >> Edge(label="이미지 pull", color=AUTO, style="dotted") >> registry
        dbjob >> Edge(label="database 생성\n(멱등)", color=NEW, fontcolor=NEW) >> pg
        app >> Edge(label="jdbc .../tapple_pr42\nFlyway 가 스키마 생성", color=AUTO) >> pg

        ing >> Edge(label="④ 이 URL 로 검증", color=NEW, fontcolor=NEW, style="dotted") >> me
        me >> Edge(label="⑤ PR 닫음 → Application 삭제\n→ Deployment·Svc·Ingress 사라짐",
                   color=GONE, fontcolor=GONE, style="dashed") >> pr


if __name__ == "__main__":
    for t in THEMES:
        build(t)
    print("out/preview-env{,-dark}.png 생성")
