"""解析器测试：以火车站样例为黄金用例。"""
from pathlib import Path

import pytest

from npl.errors import NPLSyntaxError
from npl.parser import parse_source

ROOT = Path(__file__).resolve().parents[1]
STATION = ROOT / "examples" / "station" / "station.npl"


def test_station_parses():
    program = parse_source(STATION.read_text(encoding="utf-8-sig"))
    assert program.version == "npl@0.1"
    assert program.world.name == "station_world"
    assert program.world.time == "2047-03-17 23:40"
    assert {f.name: f.value for f in program.world.facts} == {
        "bao_signed_the_transfer": True,
        "bao_met_buyer_march_3rd": True,
        "lin_has_seen_contract_copy": True,
        "buyer_paid_deposit": True,
        "lin_knows_nothing": False,
    }
    assert [l.name for l in program.world.locations] == ["old_station"]

    assert len(program.characters) == 2
    lin = [c for c in program.characters if c.name == "Lin"][0]
    bao = [c for c in program.characters if c.name == "Bao"][0]
    assert [p.name for p in lin.knows] == [
        "bao_signed_the_transfer", "lin_has_seen_contract_copy"]
    assert [p.name for p in bao.believes] == ["lin_knows_nothing"]
    assert [(t.name, t.value) for t in lin.personality] == [("restrained", 0.9), ("observant", 0.8)]
    assert [(t.name, t.value) for t in bao.emotion] == [("guilt", 0.8), ("anxiety", 0.5)]

    assert len(program.informations) == 2
    meta = [i for i in program.informations if i.name == "meta_knowledge"][0]
    assert meta.truth == "lin_has_seen_contract_copy"
    assert [p.name for p in meta.known_by] == ["Lin"]
    assert [p.name for p in meta.unknown_to] == ["Bao"]

    assert len(program.scenes) == 1
    scene = program.scenes[0]
    assert scene.title == "夜车"
    assert scene.pov == "Lin"
    assert [p.name for p in scene.participants] == ["Lin", "Bao"]
    assert len(scene.access) == 5
    deny_bao = [r for r in scene.access if r.subject == "Bao"][0]
    assert deny_bao.kind == "deny" and deny_bao.capability == "private_thought"
    assert len(scene.events) == 4
    ic = scene.information_changes[0]
    assert (ic.actor, ic.action, ic.args) == ("Lin", "confirms", ["bao_met_buyer_march_3rd"])
    goals = {g.kind: g.target for g in scene.dramatic_goal}
    assert goals == {"reveal": "meta_knowledge", "conceal": "lin_has_seen_contract_copy"}
    bao_arc = [a for a in scene.emotional_arc if a.character == "Bao"][0]
    assert bao_arc.states == ["anxiety", "relief", "unease"]

    assert program.render.style == "restrained_literary"
    assert program.render.language == "zh"


def test_missing_header():
    with pytest.raises(NPLSyntaxError) as e:
        parse_source("character Lin {\n}\n")
    assert e.value.code == "NAR-010"


def test_unknown_toplevel():
    with pytest.raises(NPLSyntaxError) as e:
        parse_source('npl@0.1\nchapter "一" {\n}\n')
    assert e.value.code == "NAR-001"


def test_duplicate_character():
    with pytest.raises(NPLSyntaxError) as e:
        parse_source("npl@0.1\ncharacter Lin {\n}\n\ncharacter Lin {\n}\n")
    assert e.value.code == "NAR-011"


def test_same_line_items():
    program = parse_source(
        "npl@0.1\nworld w {\n    fact f = true\n}\n\n"
        "character A {\n    knows: f, f\n}\n")
    assert [p.name for p in program.characters[0].knows] == ["f", "f"]


def test_unclosed_brace_reports_eof():
    with pytest.raises(NPLSyntaxError) as e:
        parse_source("npl@0.1\nworld w {\n    fact f = true\n")
    assert "文件结尾" in e.value.message or "}" in e.value.message
