"""v0.4 题材包（genre pack）：import 复用世界设定 + 世界动词 + 进程检查。"""
import json

from npl.cli import main
from npl.parser import load_program
from npl.runtime.executor import simulate
from npl.validator import validate

PACK = """npl@0.2
// 测试题材包

world 北境 {
    fact 灵脉不稳 = false
    fact 灵脉裂痕已现 = false
    fact 灵脉坍塌 = false

    entity 灵脉 {
        desc = "城下地脉"
    }

    process 灵脉坍塌 { // 灵脉之死
        stage 不稳 {
            fact = 灵脉不稳
        }
        stage 裂痕 {
            fact = 灵脉裂痕已现
        }
        stage 坍塌 {
            fact = 灵脉坍塌
        }
    }
}
"""

STORY = """npl@0.2
import "pack.npl" // 复用题材包

character 阿岩 {
}

scene "集市日" {
    pov = 阿岩
    participants = [阿岩]
    events {
        灵脉.sets(灵脉不稳)
    }
    information_changes {
        阿岩.notices(灵脉不稳)
    }
}

render {
    style = restrained_literary
    language = zh
}
"""


def _make(tmp_path, story=STORY):
    (tmp_path / "pack.npl").write_text(PACK, encoding="utf-8")
    story_path = tmp_path / "story.npl"
    story_path.write_text(story, encoding="utf-8")
    return story_path


def test_example_pack_validates_and_simulates():
    """仓库内置示例：import 题材包 → 校验 → 模拟。"""
    from pathlib import Path
    story = Path("examples/packs/northern_veins/veins_story.npl")
    program = load_program(story)
    assert [d for d in validate(program) if d.level == "ERROR"] == []
    assert program.world is not None and program.world.name == "北境"
    result = simulate(program)
    s2 = result.snapshots[1]["state"]["world"]["facts"]
    assert s2["灵脉不稳"] is True and s2["灵脉裂痕已现"] is True
    assert s2["灵脉坍塌"] is False


def test_pack_merge_world_from_import(tmp_path):
    p = _make(tmp_path)
    program = load_program(p)
    assert program.world.name == "北境"
    assert [d for d in validate(program) if d.level == "ERROR"] == []


def test_pack_process_order_check_clean(tmp_path):
    from npl.cli import _check_process_order
    p = _make(tmp_path)
    program = load_program(p)
    result = simulate(program)
    assert _check_process_order(program, result.snapshots[-1]["state"]) == []


def test_pack_process_order_violation_warns(tmp_path):
    from npl.cli import _check_process_order
    # 跳过前两个阶段直接坍塌 → 乱序
    bad_story = STORY.replace("灵脉.sets(灵脉不稳)", "灵脉.sets(灵脉坍塌)")
    p = _make(tmp_path, bad_story)
    program = load_program(p)
    result = simulate(program)
    lines = _check_process_order(program, result.snapshots[-1]["state"])
    assert len(lines) == 1 and "乱序" in lines[0] and "灵脉坍塌" in lines[0]


def test_pack_story_deterministic(tmp_path):
    p = _make(tmp_path)
    r1 = simulate(load_program(p))
    r2 = simulate(load_program(p))
    assert json.dumps(r1.snapshots, sort_keys=True) == \
        json.dumps(r2.snapshots, sort_keys=True)
