"""v0.2 运行时：深层嵌套存储、数值/枚举事实、round-trip、多文件程序 simulate。"""
import pytest

from npl.parser import load_program, parse_source
from npl.runtime.executor import simulate
from npl.runtime.state import RuntimeState, canonical_to_display

V02 = "npl@0.2\n"

DEEP = (V02 +
        "world w {\n"
        "    fact x = true\n"
        "    fact days = 9\n"
        "    fact mood = calm\n"
        "}\n"
        "character A {\n"
        "    knows: x\n"
        "    believes: B.knows(C.does_not_know(x))\n"
        "}\n"
        "character B {}\n"
        "character C {}\n"
        'scene "s" {\n'
        "    pov = A\n"
        "    participants = [A]\n"
        "    information_changes {\n"
        "        A.realizes(days)\n"
        "    }\n"
        "}\n"
        "render { style = default }")


def _prog():
    return parse_source(DEEP)


def test_deep_nested_stored_canonical():
    result = simulate(_prog())
    snap = result.snapshots[-1]["state"]
    nbs = snap["characters"]["A"]["nested_beliefs"]
    assert nbs == ["B|knows>C|does_not_know>x"]


def test_numeric_and_enum_fact_values():
    result = simulate(_prog())
    facts = result.snapshots[-1]["state"]["world"]["facts"]
    assert facts["days"] == 9
    assert facts["mood"] == "calm"
    assert facts["x"] is True


def test_confirm_numeric_fact():
    result = simulate(_prog())
    chg = result.changes[0]
    assert "days" in chg["knows_added"]["A"]


def test_round_trip_preserves_nested_and_values():
    result = simulate(_prog())
    snap = result.snapshots[-1]["state"]
    state = RuntimeState.from_dict(snap)
    again = state.to_dict()
    assert again["characters"]["A"]["nested_beliefs"] == snap["characters"]["A"]["nested_beliefs"]
    assert again["world"]["facts"]["mood"] == "calm"
    assert again["world"]["facts"]["days"] == 9


def test_canonical_to_display():
    assert canonical_to_display("A|believes>B|knows>C|does_not_know>x") == \
        "A.believes(B.knows(C.does_not_know(x)))"


def test_deep_nested_ir_view():
    from npl.ir.scene_ir import build_ir
    p = _prog()
    result = simulate(p)
    ir = result.irs[0]
    assert ir["pov_epistemic_view"]["nested_beliefs"] == \
        ["B|knows>C|does_not_know>x"]


def test_imported_program_simulates(tmp_path):
    common = (V02 +
              "world w {\n    fact seen = false\n}\n"
              "character Lin {\n    knows: seen\n}\n")
    (tmp_path / "common.npl").write_text(common, encoding="utf-8")
    entry = (V02 +
             'import "common.npl"\n'
             "character Bao {\n    does_not_know: seen\n}\n"
             'scene "s" {\n'
             "    pov = Lin\n"
             "    participants = [Lin, Bao]\n"
             "    information_changes {\n"
             "        Lin.reveals(seen)\n"
             "    }\n"
             "}\n")
    e = tmp_path / "main.npl"
    e.write_text(entry, encoding="utf-8")
    p = load_program(e)
    result = simulate(p)
    chg = result.changes[0]
    assert "seen" in chg["knows_added"]["Bao"]
