"""v0.5 关系系统 + 章节意图：语法、校验、运行时、上下文、CLI。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from npl.errors import NPLSyntaxError
from npl.parser import parse_source
from npl.validator import validate
from npl.runtime.state import RuntimeState
from npl.runtime.executor import simulate, evaluate_intents, SimulationResult
from npl.context.compiler import compile_render_context

BASE = """npl@0.2

world 测试世界 {
  location = living_room
  time = 2047-03-21
  fact 密信存在 = true
  fact 合同复印件 = true
}

character Lin { // 林，妻子
  knows:
    密信存在
  relations:
    Bao : trust = -0.9 // 三月三日的电话
    Bao : guilt = 0.4
}

character Bao { // 包，丈夫
  knows:
    密信存在
}

information 密信情报 {
  truth = 密信存在
  known_by = [Lin]
  unknown_to = [Bao]
  public = false
}

scene "对峙" {
  pov = Lin
  location = living_room
  world_time = 2047-03-21
  participants = [Lin, Bao]
  events {
    Lin.tells(密信存在)
  }
  information_changes {
    Bao.suspects(密信存在)
  }
  relation_changes {
    Lin -> Bao : trust = -0.95 // 看见账本的瞬间
  }
  dramatic_goal {
    reveal = 密信存在
  }
}

render {
  style = restrained_literary
  language = zh
}
"""


def _src(extra=""):
    """BASE 去掉 render 后追加 extra，再补回 render（保证 extra 在 render 前）。"""
    head, _, _ = BASE.rpartition("render {")
    return head + extra + "\nrender {\n  style = restrained_literary\n  language = zh\n}\n"


# ---------------- 解析 ----------------
def test_parse_relations_and_changes():
    program = parse_source(BASE)
    lin = program.characters[0]
    assert [(r.target, r.attitude, r.value) for r in lin.relations] == \
        [("Bao", "trust", -0.9), ("Bao", "guilt", 0.4)]
    assert lin.relations[0].reason == "三月三日的电话"
    rc = program.scenes[0].relation_changes
    assert len(rc) == 1
    assert (rc[0].subject, rc[0].target, rc[0].attitude, rc[0].value) == \
        ("Lin", "Bao", "trust", -0.95)
    assert rc[0].reason == "看见账本的瞬间"


def test_parse_intent_block():
    program = parse_source(_src(
        "intent {\n"
        "  goal = 密信存在 // 章末读者必须知道\n"
        "  forbid = 合同复印件\n"
        "  pacing = suspicion_up (密信情报)\n"
        "}\n"))
    kinds = [(i.kind, i.arg, i.pacing_kind) for i in program.intents]
    assert kinds == [("goal", "密信存在", None),
                     ("forbid", "合同复印件", None),
                     ("pacing", "密信情报", "suspicion_up")]


def test_intent_unknown_pacing_kind_rejected():
    with pytest.raises(NPLSyntaxError) as e:
        parse_source(_src("intent {\n  pacing = hasty_up (密信情报)\n}\n"))
    assert e.value.code == "NAR-001"


def test_intent_duplicate_rejected():
    dup = "intent {\n  goal = 密信存在\n  goal = 密信存在\n}\n"
    with pytest.raises(NPLSyntaxError) as e:
        parse_source(_src(dup))
    assert e.value.code == "NAR-012"


def test_duplicate_relations_section_rejected():
    dup = BASE.replace("  relations:\n    Bao : trust = -0.9 // 三月三日的电话\n    Bao : guilt = 0.4",
                       "  relations:\n    Bao : trust = -0.9\n  relations:\n    Bao : guilt = 0.4")
    assert dup != BASE
    with pytest.raises(NPLSyntaxError) as e:
        parse_source(dup)
    assert e.value.code == "NAR-012"


# ---------------- 校验 ----------------
def _codes(src):
    return [d.code for d in validate(parse_source(src))]


def test_relation_target_undeclared():
    src = BASE.replace("    Bao : trust = -0.9 // 三月三日的电话",
                       "    某某 : trust = -0.9")
    assert "NAR-002" in _codes(src)


def test_relation_value_out_of_range():
    src = BASE.replace("    Bao : trust = -0.9 // 三月三日的电话",
                       "    Bao : trust = -1.5")
    assert "NAR-045" in _codes(src)


def test_relation_change_subject_undeclared_and_range():
    src = BASE.replace("    Lin -> Bao : trust = -0.95 // 看见账本的瞬间",
                       "    某某 -> Bao : trust = 2.0")
    codes = _codes(src)
    assert "NAR-002" in codes and "NAR-045" in codes


def test_intent_arg_must_be_grounded():
    src = _src("intent {\n  goal = 凭空的事\n}\n")
    assert "NAR-002" in _codes(src)


def test_valid_base_has_no_errors():
    assert [d.code for d in validate(parse_source(BASE)) if d.severity == "error"] == []


# ---------------- 状态 ----------------
def test_state_seeds_and_roundtrip():
    program = parse_source(BASE)
    state = RuntimeState.from_program(program)
    rel = state.characters["Lin"]["relations"]
    assert rel["Bao"]["trust"] == -0.9 and rel["Bao"]["guilt"] == 0.4
    assert state.characters["Lin"]["relation_reasons"]["Bao"]["trust"] == "三月三日的电话"
    result = simulate(program)
    restored = RuntimeState.from_dict(result.snapshots[-1]["state"])
    assert restored.characters["Lin"]["relations"]["Bao"]["trust"] == -0.95
    assert restored.to_dict()["characters"]["Lin"]["relations"] == \
        result.snapshots[-1]["state"]["characters"]["Lin"]["relations"]


# ---------------- 运行时 ----------------
def test_executor_relation_changes_absolute():
    program = parse_source(BASE)
    result = simulate(program)
    assert result.changes[0]["relations_set"] == {"Lin->Bao.trust": -0.95}
    rel = result.snapshots[-1]["state"]["characters"]["Lin"]["relations"]
    assert rel["Bao"]["trust"] == -0.95 and rel["Bao"]["guilt"] == 0.4


def _snap(idx, reader_knows=(), suspects=None):
    return {"meta": {"scene_index": idx, "scene_title": f"s{idx}"},
            "state": {"narrative": {"reader_knows": list(reader_knows)},
                      "characters": {"A": {"suspects": suspects or {}}}}}


def test_intent_goal_missed_and_met():
    program = parse_source(_src("intent {\n  goal = 合同复印件\n}\n"))
    result = simulate(program)
    assert [w["code"] for w in result.intent_warnings] == ["NAR-071"]
    program2 = parse_source(_src("intent {\n  goal = 密信存在\n}\n"))
    result2 = simulate(program2)
    assert result2.intent_warnings == []


def test_intent_forbid_broken():
    program = parse_source(_src("intent {\n  forbid = 密信存在\n}\n"))
    result = simulate(program)
    assert [w["code"] for w in result.intent_warnings] == ["NAR-072"]


def test_evaluate_intents_pacing_drop():
    program = parse_source(_src("intent {\n  pacing = suspicion_up (密信情报)\n}\n"))
    result = SimulationResult(None)
    result.snapshots = [
        _snap(1),
        _snap(2, suspects={"密信情报": 0.6}),
        _snap(3, suspects={"密信情报": 0.8}),
        _snap(4, suspects={"密信情报": 0.2}),
    ]
    warnings = evaluate_intents(program, result)
    assert [w["code"] for w in warnings] == ["NAR-073"]
    assert "第 4 幕" in warnings[0]["message"]


def test_evaluate_intents_pacing_monotonic_ok():
    program = parse_source(_src("intent {\n  pacing = suspicion_up (密信情报)\n}\n"))
    result = SimulationResult(None)
    result.snapshots = [
        _snap(1, suspects={"密信情报": 0.6}),
        _snap(2, suspects={"密信情报": 0.6}),
        _snap(3, suspects={"密信情报": 0.8}),
    ]
    assert evaluate_intents(program, result) == []


# ---------------- 渲染上下文 ----------------
def test_compiler_includes_relations():
    program = parse_source(BASE)
    result = simulate(program)
    scene = program.scenes[0]
    ir = result.irs[0]
    state = RuntimeState.from_dict(result.snapshots[-1]["state"])
    ctx = compile_render_context(state, scene, ir, "restrained_literary")
    assert ctx["pov"]["relations"]["Bao"]["trust"] == -0.95
    assert ctx["pov"]["relation_reasons"]["Bao"]["trust"] == "看见账本的瞬间"


# ---------------- CLI ----------------
def test_cli_simulate_reports_intent_warning(tmp_path, capsys):
    from npl.cli import main
    f = tmp_path / "v05.npl"
    f.write_text(_src("intent {\n  goal = 合同复印件\n}\n"), encoding="utf-8")
    rc = main(["simulate", str(f), "--out", str(tmp_path / "build")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NAR-071" in out and "章节意图" in out


def test_cli_inspect_shows_relations(tmp_path, capsys):
    from npl.cli import main
    f = tmp_path / "v05.npl"
    f.write_text(BASE, encoding="utf-8")
    rc = main(["simulate", str(f), "--out", str(tmp_path / "build")])
    assert rc == 0
    capsys.readouterr()
    rc = main(["inspect", str(f), "--character", "Lin", "--scene", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "relations:" in out
    assert "Bao.trust = -0.95（看见账本的瞬间）" in out
    assert "Bao.guilt = 0.4" in out


def test_cli_diff_shows_relation_change(tmp_path, capsys):
    from npl.cli import main
    f = tmp_path / "v05.npl"
    f.write_text(BASE, encoding="utf-8")
    rc = main(["simulate", str(f), "--out", str(tmp_path / "build")])
    assert rc == 0
    capsys.readouterr()
    rc = main(["diff", str(f), "--scene", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Lin->Bao.trust: -0.9 -> -0.95" in out
