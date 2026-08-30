"""v0.4 多阶段世界进程（process）：解析、校验、运行时乱序检查。"""
import json

import pytest

from npl.cli import main
from npl.parser import load_program
from npl.runtime.executor import simulate
from npl.validator import validate

_BASE = """npl@0.2
// 进程测试

world 北境 {
    fact 灵脉不稳 = false
    fact 灵脉裂痕已现 = false
    fact 灵脉坍塌 = false

    entity 灵脉 {
        desc = "城下地脉"
    }

    process 灵脉坍塌 { // 城基之下的缓慢灾变
        stage 不稳 {
            fact = 灵脉不稳 // 老树无风自摇
        }
        stage 裂痕 {
            fact = 灵脉裂痕已现 // 集市石板开裂
        }
        stage 坍塌 {
            fact = 灵脉坍塌 // 城门楼下沉
        }
    }
}

character 阿岩 {
}

information 灵脉不稳 {
    truth = 灵脉不稳
    known_by = []
    unknown_to = [阿岩]
    public = false
}

information 灵脉裂痕已现 {
    truth = 灵脉裂痕已现
    known_by = []
    unknown_to = [阿岩]
    public = false
}

information 灵脉坍塌 {
    truth = 灵脉坍塌
    known_by = []
    unknown_to = [阿岩]
    public = false
}

scene "征兆" {
    pov = 阿岩
    participants = [阿岩]
    events {
        灵脉.sets(灵脉不稳)
        灵脉.sets(灵脉裂痕已现)
    }
}

scene "灾变" {
    pov = 阿岩
    participants = [阿岩]
    events {
        灵脉.sets(灵脉坍塌)
    }
}

render {
    style = restrained_literary
    language = zh
}
"""


def _write(tmp_path, text, name="process.npl"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_process_parse_structure(tmp_path):
    p = _write(tmp_path, _BASE)
    program = load_program(p)
    proc = program.world.processes[0]
    assert proc.name == "灵脉坍塌"
    assert proc.desc == "城基之下的缓慢灾变"
    assert [(s.name, s.fact) for s in proc.stages] == [
        ("不稳", "灵脉不稳"), ("裂痕", "灵脉裂痕已现"), ("坍塌", "灵脉坍塌")]
    assert proc.stages[0].desc == "老树无风自摇"


def test_process_validate_clean(tmp_path):
    p = _write(tmp_path, _BASE)
    assert [d for d in validate(load_program(p)) if d.level == "ERROR"] == []


def test_process_stage_fact_undeclared(tmp_path):
    bad = _BASE.replace("fact = 灵脉坍塌 // 城门楼下沉", "fact = 未声明事实")
    p = _write(tmp_path, bad, "bad_fact.npl")
    diags = validate(load_program(p))
    assert any(d.code == "NAR-002" and "未声明事实" in d.message for d in diags)


def test_process_duplicate_name_and_stage(tmp_path):
    dup_proc = _BASE.replace("    process 灵脉坍塌 { // 城基之下的缓慢灾变",
                             "    process 灵脉坍塌 {\n        stage 早 { fact = 灵脉不稳 }\n    }\n\n    process 灵脉坍塌 { // 第二个同名进程")
    p = _write(tmp_path, dup_proc, "dup_proc.npl")
    diags = validate(load_program(p))
    assert any(d.code == "NAR-012" and "重复的进程" in d.message for d in diags)

    dup_stage = _BASE.replace("        stage 坍塌 {", "        stage 裂痕 {")
    p2 = _write(tmp_path, dup_stage, "dup_stage.npl")
    with pytest.raises(Exception) as e:
        load_program(p2)
    assert "重复阶段" in str(e.value)


def test_process_stage_missing_fact_field(tmp_path):
    bad = _BASE.replace("            fact = 灵脉不稳 // 老树无风自摇\n", "")
    p = _write(tmp_path, bad, "no_fact.npl")
    with pytest.raises(Exception):
        load_program(p)


def test_simulate_in_order_no_warning(tmp_path, capsys):
    p = _write(tmp_path, _BASE)
    assert main(["simulate", str(p), "--out", str(tmp_path / "b")]) == 0
    assert "乱序" not in capsys.readouterr().out


def test_simulate_out_of_order_warns(tmp_path, capsys):
    bad = _BASE.replace("        灵脉.sets(灵脉不稳)\n        灵脉.sets(灵脉裂痕已现)\n",
                        "")
    p = _write(tmp_path, bad, "ooo.npl")
    assert main(["simulate", str(p), "--out", str(tmp_path / "b2")]) == 0
    out = capsys.readouterr().out
    assert "乱序" in out and "灵脉坍塌" in out


def test_process_deterministic_snapshot(tmp_path):
    p = _write(tmp_path, _BASE)
    r1 = simulate(load_program(p))
    r2 = simulate(load_program(p))
    assert json.dumps(r1.snapshots, sort_keys=True) == \
        json.dumps(r2.snapshots, sort_keys=True)
    assert r1.snapshots[1]["state"]["world"]["facts"]["灵脉坍塌"] is True
