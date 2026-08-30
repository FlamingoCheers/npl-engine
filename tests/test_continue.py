"""快照续跑与分支对比（v0.3-3.3）：continue / branch-diff 端到端。"""
import json

from npl.cli import main
from npl.parser import load_program
from npl.runtime.executor import simulate_continue
from npl.runtime.state import RuntimeState

_BASE = """npl@0.2  // 基程序：两幕

world 客栈 {
    fact 密信存在 = true
}

character 林秋 {
    knows:
        密信存在
}

character 沈砚 {
}

information 密信存在 {
    truth = 密信存在
    known_by = [林秋]
    unknown_to = [沈砚]
    public = false
}

scene "茶摊" {
    pov = 林秋
    participants = [林秋]
}

scene "夜谈" {
    pov = 沈砚
    participants = [林秋, 沈砚]
    information_changes {
        沈砚.suspects(密信存在)
    }
}

render {
    style = restrained_literary
    language = zh
}
"""

_EXTRA_A = """npl@0.2  // 分支 A：沈砚确证

world 客栈 {
    fact 密信存在 = true
}

character 林秋 {
    knows:
        密信存在
}

character 沈砚 {
}

information 密信存在 {
    truth = 密信存在
    known_by = [林秋]
    unknown_to = [沈砚]
    public = false
}

scene "摊牌" {
    pov = 林秋
    participants = [林秋, 沈砚]
    information_changes {
        林秋.reveals(密信存在)
    }
}

render {
    style = restrained_literary
    language = zh
}
"""

_EXTRA_B = """npl@0.2  // 分支 B：沈砚始终不知

world 客栈 {
    fact 密信存在 = true
}

character 林秋 {
    knows:
        密信存在
}

character 沈砚 {
}

information 密信存在 {
    truth = 密信存在
    known_by = [林秋]
    unknown_to = [沈砚]
    public = false
}

scene "错过" {
    pov = 沈砚
    participants = [沈砚]
}

render {
    style = restrained_literary
    language = zh
}
"""

_EXTRA_GHOST = """npl@0.2  // 分支 C：引入快照中不存在的人物（应拒绝）

world 客栈 {
    fact 密信存在 = true
}

character 林秋 {
    knows:
        密信存在
}

character 沈砚 {
}

character 过客 {
}

information 密信存在 {
    truth = 密信存在
    known_by = [林秋]
    unknown_to = [沈砚]
    public = false
}

scene "岔路" {
    pov = 过客
    participants = [过客]
}

render {
    style = restrained_literary
    language = zh
}
"""


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _base_last_snapshot(tmp_path):
    base = _write(tmp_path, "base.npl", _BASE)
    out = tmp_path / "base_build"
    assert main(["simulate", str(base), "--out", str(out)]) == 0
    snap = json.loads(
        (out / "state_snapshots" / "scene_002.json").read_text(encoding="utf-8")
    )
    return snap


# ------------------------------------------------------------- 执行核心

def test_simulate_continue_deterministic_and_carryover(tmp_path):
    snap = _base_last_snapshot(tmp_path)
    extra = _write(tmp_path, "extra_a.npl", _EXTRA_A)
    program = load_program(extra)
    state = RuntimeState.from_dict(snap["state"])

    r1 = simulate_continue(state, program.scenes, snap["meta"]["scene_index"] + 1)
    r2 = simulate_continue(RuntimeState.from_dict(snap["state"]),
                           program.scenes, snap["meta"]["scene_index"] + 1)
    assert json.dumps(r1.snapshots, sort_keys=True) == json.dumps(
        r2.snapshots, sort_keys=True)
    # 编号续接：scene_index 3 起
    assert r1.snapshots[0]["meta"]["scene_index"] == 3
    # 基程序状态延续：林秋仍知密信
    assert "密信存在" in r1.snapshots[0]["state"]["characters"]["林秋"]["knows"]


# ------------------------------------------------------------- CLI: continue

def test_cli_continue_end_to_end(tmp_path, capsys):
    snap = _base_last_snapshot(tmp_path)
    snap_path = tmp_path / "snap002.json"
    snap_path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    extra = _write(tmp_path, "extra_a.npl", _EXTRA_A)
    out = tmp_path / "cont"

    assert main(["continue", str(extra), "--from", str(snap_path),
                 "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "续跑" in text
    assert "[3]" in text
    assert (out / "state_snapshots" / "scene_003.json").exists()
    # reveal 已传播：沈砚知道密信
    snap3 = json.loads(
        (out / "state_snapshots" / "scene_003.json").read_text(encoding="utf-8"))
    assert "密信存在" in snap3["state"]["characters"]["沈砚"]["knows"]


def test_cli_continue_rejects_unknown_character(tmp_path, capsys):
    snap = _base_last_snapshot(tmp_path)
    snap_path = tmp_path / "snap002.json"
    snap_path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    extra = _write(tmp_path, "extra_ghost.npl", _EXTRA_GHOST)
    assert main(["continue", str(extra), "--from", str(snap_path),
                 "--out", str(tmp_path / "c2")]) == 1
    assert "过客" in capsys.readouterr().out


def test_cli_continue_missing_snapshot(tmp_path, capsys):
    extra = _write(tmp_path, "extra_a.npl", _EXTRA_A)
    assert main(["continue", str(extra), "--from",
                 str(tmp_path / "nope.json")]) == 2
    assert "快照不存在" in capsys.readouterr().out


# ------------------------------------------------------------- CLI: branch-diff

def test_cli_branch_diff_shows_divergence(tmp_path, capsys):
    snap = _base_last_snapshot(tmp_path)
    snap_path = tmp_path / "snap002.json"
    snap_path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")

    out_a, out_b = tmp_path / "a", tmp_path / "b"
    assert main(["continue", str(_write(tmp_path, "extra_a.npl", _EXTRA_A)),
                 "--from", str(snap_path), "--out", str(out_a)]) == 0
    assert main(["continue", str(_write(tmp_path, "extra_b.npl", _EXTRA_B)),
                 "--from", str(snap_path), "--out", str(out_b)]) == 0
    capsys.readouterr()

    assert main(["branch-diff",
                 str(out_a / "state_snapshots" / "scene_003.json"),
                 str(out_b / "state_snapshots" / "scene_003.json")]) == 0
    text = capsys.readouterr().out
    assert "分支 A" in text and "分支 B" in text
    # A 分支沈砚已知，B 分支不知 → 差异必须体现
    assert "沈砚.knows" in text


def test_cli_branch_diff_identical(tmp_path, capsys):
    snap = _base_last_snapshot(tmp_path)
    snap_path = tmp_path / "snap002.json"
    snap_path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    assert main(["branch-diff", str(snap_path), str(snap_path)]) == 0
    assert "一致" in capsys.readouterr().out
