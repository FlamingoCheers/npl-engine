"""M3 前端与 CLI 测试：嵌套认知 / 置信度 / 闪回 / Reader Model / actor。"""
import json

from npl.errors import NPLSyntaxError
from npl.parser import parse_source
from npl.validator import validate

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATION = ROOT / "examples" / "station" / "station.npl"


def _program(extra=""):
    src = (
        "npl@0.1\n"
        "world w {\n"
        "    fact deal_secret = true\n"
        "    fact rumor_false = false\n"
        "}\n"
        "character Lin {\n"
        "    believes:\n"
        "        Bao.does_not_know(deal_secret)\n"
        "    suspects:\n"
        "        deal_secret (0.35)\n"
        "}\n"
        "character Bao {\n"
        "}\n"
        "scene \"试\" {\n"
        "    location = room\n"
        "    world_time = 2047-03-10 09:00\n"
        "    flashback = true\n"
        "    pov = Lin\n"
        "    participants = [Lin, Bao]\n"
        "    information_changes {\n"
        "        Lin.realizes(Bao.knows(deal_secret))\n"
        "    }\n"
        "}\n" + extra
    )
    return parse_source(src)


def test_parse_nested_belief_and_confidence():
    p = _program()
    lin = p.characters[0]
    nested = lin.believes[0]
    assert nested.holder == "Bao"
    assert nested.verb == "does_not_know"
    assert nested.prop == "deal_secret"
    sus = lin.suspects[0]
    assert sus.name == "deal_secret"
    assert sus.confidence == pytest.approx(0.35)
    assert p.scenes[0].flashback is True


def test_default_suspect_confidence_is_half():
    src = ("npl@0.1\n"
           "world w { fact x = true }\n"
           "character A { suspects: x }\n"
           "character B {}\n"
           "scene \"s\" {\n    pov = A\n    participants = [A]\n}\n")
    a = parse_source(src).characters[0]
    assert a.suspects[0].confidence == pytest.approx(0.5)


def test_nar_014_unknown_holder():
    p = _program()
    p.characters[0].believes[0].path[0] = ("Ghost", "knows")   # v0.2: path 结构
    codes = [d.code for d in validate(p)]
    assert "NAR-014" in codes


def test_nar_014_ungrounded_nested_prop():
    p = _program()
    p.characters[0].believes[0].prop = "no_such_fact"
    codes = [d.code for d in validate(p)]
    assert "NAR-014" in codes


def test_nar_042_flashback_reveal_warning():
    src = ("npl@0.1\n"
           "world w { fact x = true }\n"
           "character A {}\n"
           "character B {}\n"
           "scene \"s\" {\n"
           "    location = room\n"
           "    world_time = 2047-03-10 09:00\n"
           "    flashback = true\n"
           "    pov = A\n"
           "    participants = [A, B]\n"
           "    information_changes {\n"
           "        A.reveals(x)\n"
           "    }\n"
           "}\n")
    codes = [d.code for d in validate(parse_source(src))]
    assert "NAR-042" in codes


def test_nar_043_confidence_out_of_range():
    p = _program()
    p.characters[0].suspects[0].confidence = 1.7
    codes = [d.code for d in validate(p)]
    assert "NAR-043" in codes


def test_event_nested_arg_validates():
    src = ("npl@0.1\n"
           "world w { fact x = true }\n"
           "character A {}\n"
           "character B {}\n"
           "scene \"s\" {\n"
           "    pov = A\n"
           "    participants = [A, B]\n"
           "    information_changes {\n"
           "        A.realizes(Ghost.knows(x))\n"
           "    }\n"
           "}\n")
    codes = [d.code for d in validate(parse_source(src))]
    assert "NAR-014" in codes
