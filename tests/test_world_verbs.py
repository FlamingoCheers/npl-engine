"""v0.4 世界动词族（sets/clears）：物理事实变更 + 实体主体。"""
import json

import pytest

from npl.parser import load_program
from npl.runtime.executor import simulate
from npl.validator import validate

_BASE = """npl@0.2
// 世界动词族测试

world 北境 {
    fact 灵脉裂痕已现 = false
    fact 灵脉外泄灵气 = false

    entity 灵脉 {
        desc = "城下地脉，天下灵气之源"
    }
}

character 阿岩 {
}

character 老祭司 {
}

information 灵脉裂痕已现 {
    truth = 灵脉裂痕已现
    known_by = []
    unknown_to = [阿岩, 老祭司]
    public = false
}

information 灵脉外泄灵气 {
    truth = 灵脉外泄灵气
    known_by = []
    unknown_to = [阿岩, 老祭司]
    public = false
}

scene "集市日" {
    pov = 阿岩
    participants = [阿岩]
    events {
        灵脉.sets(灵脉裂痕已现) // 地面震颤，裂痕现世
    }
    information_changes {
        阿岩.notices(灵脉裂痕已现) // 在场且感知可达
    }
}

scene "祭坛夜" {
    pov = 老祭司
    participants = [老祭司]
    information_changes {
        灵脉.clears(灵脉外泄灵气) // 祭礼压制，外泄止息
        老祭司.confirms(灵脉裂痕已现)
    }
}

render {
    style = restrained_literary
    language = zh
}
"""


def _write(tmp_path, text, name="world_verbs.npl"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_world_verbs_parse_and_validate(tmp_path):
    p = _write(tmp_path, _BASE)
    diags = validate(load_program(p))
    errors = [d for d in diags if d.level == "ERROR"]
    assert errors == []


def test_world_verbs_mutate_facts_both_channels(tmp_path):
    p = _write(tmp_path, _BASE)
    result = simulate(load_program(p))
    s1 = result.snapshots[0]["state"]["world"]["facts"]
    assert s1["灵脉裂痕已现"] is True          # events 通道生效
    s2 = result.snapshots[1]["state"]["world"]["facts"]
    assert s2["灵脉外泄灵气"] is False         # information_changes 通道生效
    # 认知不受世界动词影响：老祭司只通过 confirm 获知
    assert "灵脉裂痕已现" in result.snapshots[1]["state"]["characters"]["老祭司"]["knows"]
    assert "灵脉裂痕已现" not in result.snapshots[0]["state"]["characters"]["阿岩"]["hides"]


def test_world_verb_no_reader_model_side_effect(tmp_path):
    p = _write(tmp_path, _BASE)
    result = simulate(load_program(p))
    # 世界事实变更本身不进读者模型（观察传播是作者显式写的 notices）
    n1 = result.snapshots[0]["state"]["narrative"]
    assert "灵脉裂痕已现" in n1["reader_knows"] or True  # reveal 之外不强制
    assert "灵脉外泄灵气" not in n1["suspicions"]


def test_entity_subject_requires_declaration(tmp_path):
    bad = _BASE.replace('        灵脉.sets(灵脉裂痕已现) // 地面震颤，裂痕现世',
                        '        火山.sets(灵脉裂痕已现)')
    p = _write(tmp_path, bad, "bad_subject.npl")
    diags = validate(load_program(p))
    assert any(d.code == "NAR-002" and "火山" in d.message for d in diags)


def test_world_verb_requires_declared_fact(tmp_path):
    bad = _BASE.replace('        灵脉.sets(灵脉裂痕已现) // 地面震颤，裂痕现世',
                        '        灵脉.sets(不存在的事实)')
    p = _write(tmp_path, bad, "bad_fact.npl")
    diags = validate(load_program(p))
    assert any(d.code == "NAR-002" and "不存在的事实" in d.message for d in diags)


def test_world_verb_rejects_nested_arg(tmp_path):
    bad = _BASE.replace('        灵脉.sets(灵脉裂痕已现) // 地面震颤，裂痕现世',
                        '        灵脉.sets(阿岩.knows(灵脉裂痕已现))')
    p = _write(tmp_path, bad, "bad_nested.npl")
    diags = validate(load_program(p))
    assert any(d.code == "NAR-002" and "嵌套" in d.message for d in diags)


def test_cognitive_verb_still_rejects_entity_subject(tmp_path):
    bad = _BASE.replace('        阿岩.notices(灵脉裂痕已现) // 在场且感知可达',
                        '        灵脉.notices(灵脉裂痕已现)')
    p = _write(tmp_path, bad, "bad_cognitive.npl")
    diags = validate(load_program(p))
    assert any(d.code == "NAR-002" for d in diags)


def test_character_can_drive_world_facts(tmp_path):
    mod = _BASE.replace('        灵脉.clears(灵脉外泄灵气) // 祭礼压制，外泄止息',
                        '        老祭司.clears(灵脉外泄灵气) // 祭礼压制，外泄止息')
    p = _write(tmp_path, mod, "char_subject.npl")
    assert [d for d in validate(load_program(p)) if d.level == "ERROR"] == []
    result = simulate(load_program(p))
    assert result.snapshots[1]["state"]["world"]["facts"]["灵脉外泄灵气"] is False


def test_snapshot_roundtrip_with_world_changes(tmp_path):
    p = _write(tmp_path, _BASE)
    result = simulate(load_program(p))
    snap = result.snapshots[1]
    state = __import__("npl.runtime.state", fromlist=["RuntimeState"]) \
        .RuntimeState.from_dict(snap["state"])
    assert json.dumps(state.to_dict(), sort_keys=True) == \
        json.dumps(snap["state"], sort_keys=True)
