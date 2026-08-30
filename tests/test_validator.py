"""语义校验器测试：12 个故意错误样例全部命中 + 黄金样例零错误。"""
from pathlib import Path

import pytest

from npl.errors import NPLSyntaxError
from npl.parser import parse_source
from npl.validator import validate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
STATION = ROOT / "examples" / "station" / "station.npl"

EXPECTED = {
    "01_missing_header.npl": "NAR-010",
    "02_unknown_toplevel.npl": "NAR-001",
    "03_duplicate_character.npl": "NAR-011",
    "04_duplicate_info_field.npl": "NAR-012",
    "05_pov_undeclared.npl": "NAR-002",
    "06_participant_undeclared.npl": "NAR-002",
    "07_bad_capability.npl": "NAR-003",
    "08_pov_not_participant.npl": "NAR-004",
    "09_arc_not_participant.npl": "NAR-004",
    "10_missing_pov.npl": "NAR-013",
    "11_info_truth_ungrounded.npl": "NAR-002",
    "12_syntax_error.npl": "NAR-001",
}


def codes_of(source: str):
    try:
        program = parse_source(source)
    except NPLSyntaxError as e:
        return [e.code]
    return [d.code for d in validate(program)]


@pytest.mark.parametrize("name,expected", sorted(EXPECTED.items()))
def test_invalid_fixture_hits_expected_code(name, expected):
    src = (FIXTURES / "invalid" / name).read_text(encoding="utf-8-sig")
    assert expected in codes_of(src), f"{name} 应触发 {expected}，实得 {codes_of(src)}"


def test_station_validates_clean():
    program = parse_source(STATION.read_text(encoding="utf-8-sig"))
    diags = validate(program)
    errors = [d for d in diags if d.severity == "error"]
    warnings = [d for d in diags if d.severity == "warning"]
    assert errors == []
    # 一处设计意图内的自由命题：marriage_is_effectively_over
    # （lin_knows_nothing 已由世界事实 lin_knows_nothing = false 接地）
    assert [w.code for w in warnings] == ["NAR-041"]


def test_minimal_valid_zero_diagnostics():
    program = parse_source((FIXTURES / "valid" / "minimal.npl").read_text(encoding="utf-8-sig"))
    assert validate(program) == []


def test_ungrounded_knows_warns():
    src = ("npl@0.1\ncharacter A {\n    knows:\n        ghost_fact\n}\n")
    diags = validate(parse_source(src))
    assert len(diags) == 1
    assert diags[0].code == "NAR-041" and diags[0].severity == "warning"


def test_world_capability_on_character_errors():
    src = ("npl@0.1\n"
           "character Lin {\n}\n\n"
           "scene \"s\" {\n    pov = Lin\n    participants = [Lin]\n"
           "    access {\n        allow = Lin.truth\n    }\n}\n")
    diags = validate(parse_source(src))
    assert any(d.code == "NAR-003" for d in diags)
