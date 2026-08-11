"""라이트·다크 두 벌을 만들기 위한 공용 테마.

배경을 transparent 로 두면 안 된다. diagrams 의 Cluster 는 자체 밝은 배경색을 갖고 있어서,
글자만 밝게 바꾸면 밝은 박스 위 밝은 글자가 되어 읽을 수 없다.
그래서 페이지 배경·클러스터 배경·글자색을 한 세트로 묶어 명시한다.

GitHub 은 다크 모드에서 이미지 색을 바꿔주지 않으므로 README 에서 <picture> 로 두 벌을 준다.
"""

LIGHT = {
    "name": "",  # 파일명 접미사 없음
    "bg": "#FFFFFF",
    "fg": "#1F2328",
    "cluster_bg": "#EEF3F8",
    "cluster_fg": "#48525C",
}

DARK = {
    "name": "-dark",
    "bg": "#0D1117",  # GitHub 다크 캔버스
    "fg": "#E6EDF3",
    "cluster_bg": "#18222D",
    "cluster_fg": "#AEB9C4",
}

THEMES = (LIGHT, DARK)


def graph_attr(theme: dict, **extra) -> dict:
    """Diagram 전체 속성."""
    base = {
        "fontname": "Helvetica",
        "bgcolor": theme["bg"],
        "fontcolor": theme["fg"],
        "pad": "0.5",
        "splines": "spline",
        "nodesep": "0.5",
        "ranksep": "1.1",
    }
    base.update(extra)
    return base


def node_attr(theme: dict) -> dict:
    return {"fontname": "Helvetica", "fontcolor": theme["fg"], "fontsize": "12"}


def edge_attr(theme: dict) -> dict:
    return {"fontname": "Helvetica", "fontcolor": theme["fg"], "fontsize": "11"}


def cluster_attr(theme: dict) -> dict:
    """Cluster 박스 속성 — 배경과 제목 글자색을 함께 지정해야 한다."""
    return {
        "bgcolor": theme["cluster_bg"],
        "fontcolor": theme["cluster_fg"],
        "fontname": "Helvetica",
        "fontsize": "13",
        "penwidth": "1",
        "pencolor": theme["cluster_fg"],
        "style": "rounded",
    }
