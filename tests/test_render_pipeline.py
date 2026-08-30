"""渲染管线端到端测试（mock 适配器，离线可跑）。"""
from pathlib import Path

from npl.cli import main
from npl.render.adapter import MockAdapter
from npl.render.renderer import render_scene
from npl.runtime.executor import simulate
from npl.runtime.state import RuntimeState
from npl.parser import parse_source

ROOT = Path(__file__).resolve().parent.parent
STATION = ROOT / "examples" / "station" / "station.npl"


def test_render_scene_with_mock_adapter():
    program = parse_source(STATION.read_text(encoding="utf-8-sig"))
    result = simulate(program)
    state = RuntimeState.from_dict(result.snapshots[0]["state"])
    prose, ctx = render_scene(state, program.scenes[0], result.irs[0],
                              "restrained_literary", MockAdapter())
    assert "mock 渲染输出" in prose
    assert ctx["pov"]["name"] == "Lin"


def test_cli_render_writes_prose(tmp_path, capsys):
    rc = main(["render", str(STATION), "--out", str(tmp_path),
               "--adapter", "mock"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "scene_001.md" in out
    prose = (tmp_path / "prose" / "scene_001.md").read_text(encoding="utf-8")
    assert prose.startswith("<!-- npl render")
    assert "mock" in prose


def test_cli_simulate_writes_snapshots_and_ir(tmp_path, capsys):
    rc = main(["simulate", str(STATION), "--out", str(tmp_path)])
    assert rc == 0
    snap = tmp_path / "state_snapshots" / "scene_001.json"
    ir = tmp_path / "scene_ir" / "scene_001.json"
    assert snap.exists() and ir.exists()
    assert "夜车" in snap.read_text(encoding="utf-8")


def test_cli_render_scene_out_of_range(tmp_path, capsys):
    rc = main(["render", str(STATION), "--scene", "9", "--out", str(tmp_path),
               "--adapter", "mock"])
    assert rc == 2
    assert "越界" in capsys.readouterr().out
