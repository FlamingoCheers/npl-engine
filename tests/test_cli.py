"""CLI 基础行为：validate 退出码 / --json 形状 / 缺失文件（v0.2: NAR-015）。"""
import json

from npl.cli import main


def test_validate_ok_exit0(capsys):
    assert main(["validate", "examples/station/station.npl"]) == 0
    assert "✗" not in capsys.readouterr().out


def test_validate_json_ok(capsys):
    assert main(["validate", "examples/station/station.npl", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True


def test_missing_file_is_nar015(capsys):
    # v0.2：文件缺失由 load_program 统一报 NAR-015（exit 1，不再是裸 IO exit 2）
    assert main(["validate", "no_such_file.npl"]) == 1
    assert "NAR-015" in capsys.readouterr().out


def test_syntax_error_exit1(capsys, tmp_path):
    bad = tmp_path / "bad.npl"
    bad.write_text("garbage\n", encoding="utf-8")
    assert main(["validate", str(bad)]) == 1
    assert "NAR-010" in capsys.readouterr().out
