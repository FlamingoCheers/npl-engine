"""v0.3-3.2 深层嵌套接地验证：epistemics 逐层判定 + inspect --deep CLI。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "src"))

from npl.cli import main as cli_main
from npl.parser import parse_source
from npl.runtime.epistemics import deep_grounding, parse_canonical
from npl.runtime.executor import simulate
from npl.runtime.state import RuntimeState

# 最小合法程序：world + character + 两幕 + render
_NPL = """npl@0.2
world 小镇 {
    fact 密信存在 = true
}
character 阿岩 {
    knows: 密信存在
}
scene \"第一幕\" {
    pov = 阿岩
    participants = [阿岩]
    events {
        阿岩.arrives
    }
}
render {
    style = restrained_literary
    language = zh
}
"""


def _state_with(nested_canon, extra_chars=None):
    prog = parse_source(_NPL)
    result = simulate(prog)
    state = RuntimeState.from_dict(result.snapshots[-1]["state"])
    if extra_chars:
        for name, knows, believes in extra_chars:
            state.characters[name] = {
                "knows": set(knows), "believes": set(believes),
                "suspects": {}, "hides": set(), "intends": set(),
                "personality": {}, "emotion": {}, "arc": None,
                "believes_about": {}, "nested_beliefs": set(),
            }
    state.characters["阿岩"]["nested_beliefs"].add(nested_canon)
    return state


# ---------------- parse_canonical ----------------

def test_parse_canonical_shapes():
    assert parse_canonical("A|believes>B|knows>x") == (
        [("A", "believes"), ("B", "knows")], "x")
    assert parse_canonical("A|knows>x") is None           # 路径至少两层才入此格式
    assert parse_canonical("A|wants>B|knows>x") is None    # 非法动词
    assert parse_canonical("junk") is None


# ---------------- deep_grounding ----------------
# 注意：canonical 不含 owner 段——链上全部都是被建模的他人。

def test_depth2_holds_when_holders_actually_know():
    # owner 建模“老祭司知道阿芽知道x”；两人真知 → 成立
    st = _state_with("老祭司|knows>阿芽|knows>密信存在",
                     [("老祭司", {"密信存在"}, set()),
                      ("阿芽", {"密信存在"}, set())])
    g = deep_grounding(st, "老祭司|knows>阿芽|knows>密信存在")
    assert g["verdict"] == "holds"
    assert [lv["holder"] for lv in g["levels"]] == ["阿芽", "老祭司"]


def test_depth2_breaks_at_inner_holder():
    # 阿芽实际不知道 → 内层断裂
    st = _state_with("老祭司|knows>阿芽|knows>密信存在",
                     [("老祭司", {"密信存在"}, set()),
                      ("阿芽", set(), set())])
    g = deep_grounding(st, "老祭司|knows>阿芽|knows>密信存在")
    assert g["verdict"] == "broken:阿芽"
    assert g["levels"][0]["verdict"] == "violated"


def test_depth3_inner_break_wins_but_all_levels_reported():
    canon = "老祭司|believes>阿芽|knows>守烛人|knows>密信存在"
    # 三层全不成立 → 内层（守烛人）先断，但三层都报告
    st = _state_with(canon,
                     [("老祭司", set(), set()),
                      ("阿芽", set(), set()),
                      ("守烛人", set(), set())])
    g = deep_grounding(st, canon)
    assert g["verdict"] == "broken:守烛人"
    assert [lv["verdict"] for lv in g["levels"]] == ["violated"] * 3


def test_depth3_all_hold():
    canon = "老祭司|believes>阿芽|knows>守烛人|knows>密信存在"
    st = _state_with(canon,
                     [("老祭司", set(), {"密信存在"}),
                      ("阿芽", {"密信存在"}, set()),
                      ("守烛人", {"密信存在"}, set())])
    g = deep_grounding(st, canon)
    assert g["verdict"] == "holds"


def test_unknown_when_holder_missing():
    # 阿芽成立，路人无记录 → unknown:路人
    st = _state_with("路人|knows>阿芽|knows>密信存在",
                     [("阿芽", {"密信存在"}, set())])
    g = deep_grounding(st, "路人|knows>阿芽|knows>密信存在")
    assert g["verdict"] == "unknown:路人"
    assert g["levels"][-1]["holder"] == "路人"


def test_does_not_know_verb_semantics():
    # 建模“老祭司不知道阿芽知道x”；阿芽真知，老祭司实际不知 → 成立
    canon = "老祭司|does_not_know>阿芽|knows>密信存在"
    st = _state_with(canon,
                     [("老祭司", set(), set()),
                      ("阿芽", {"密信存在"}, set())])
    g = deep_grounding(st, canon)
    assert g["verdict"] == "holds"
    # 老祭司实际知道 → 外层断裂
    st2 = _state_with(canon,
                      [("老祭司", {"密信存在"}, set()),
                       ("阿芽", {"密信存在"}, set())])
    g2 = deep_grounding(st2, canon)
    assert g2["verdict"] == "broken:老祭司"


# ---------------- CLI inspect --deep ----------------

def _write_min(tmp_path):
    p = tmp_path / "mini.npl"
    p.write_text(_NPL, encoding="utf-8")
    return p


def test_inspect_deep_flag_output(tmp_path, capsys):
    p = _write_min(tmp_path)
    rc = cli_main(["inspect", str(p), "--deep"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "嵌套认知" not in out  # 该程序无深层嵌套，不输出该节


def test_inspect_deep_flag_accepted_with_character(tmp_path, capsys):
    p = _write_min(tmp_path)
    rc = cli_main(["inspect", str(p), "--character", "阿岩", "--deep"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "阿岩" in out


_DEEP_NPL = """npl@0.2
world 小镇 {
    fact 密信存在 = true
}
character 阿岩 {
    knows: 密信存在
    believes: 老祭司.knows(阿芽.knows(密信存在))
}
character 老祭司 {
    knows: 密信存在
}
character 阿芽 { }
scene \"第一幕\" {
    pov = 阿岩
    participants = [阿岩]
    events {
        阿岩.arrives
    }
}
render {
    style = restrained_literary
    language = zh
}
"""


def test_inspect_deep_renders_grounding(tmp_path, capsys):
    # 阿岩 建模“老祭司知道阿芽知道密信”；老祭司真知 ✓，阿芽不知 ✗ → 在阿芽层断裂
    p = tmp_path / "deep.npl"
    p.write_text(_DEEP_NPL, encoding="utf-8")
    rc = cli_main(["inspect", str(p), "--character", "阿岩", "--deep"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "嵌套认知" in out
    assert "老祭司.knows(阿芽.knows(密信存在))" in out
    assert "在 阿芽 层断裂" in out
    assert "老祭司.knows(密信存在)（基础命题近似）" in out
    assert "密信存在 ∈ 老祭司.knows" in out
