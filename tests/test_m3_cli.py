"""M3 CLI 测试：inspect --reader / actor（mock，确定性）。"""
import json

from pathlib import Path

import pytest

from npl.cli import main

ROOT = Path(__file__).resolve().parent.parent
SRC = (
    "npl@0.1\n"
    "world w {\n"
    "    fact secret_deal = true  // 货款去向：一桩未公开的交易\n"
    "    fact receipt_found = false\n"
    "}\n"
    "character Lin {\n"
    "    knows: secret_deal\n"
    "    believes:\n"
    "        Bao.does_not_know(secret_deal)  // 林还以为对方蒙在鼓里\n"
    "    suspects:\n"
    "        receipt_found (0.4)\n"
    "}\n"
    "character Bao {\n"
    "}\n"
    "scene \"试探\" {\n"
    "    location = home\n"
    "    world_time = 2047-03-17 23:40\n"
    "    pov = Lin\n"
    "    participants = [Lin, Bao]\n"
    "    events {\n"
    "        Bao.hides(secret_deal)\n"
    "    }\n"
    "    information_changes {\n"
    "        Lin.misunderstands(Bao.does_not_know(secret_deal))\n"
    "    }\n"
    "}\n"
    "scene \"摊牌\" {\n"
    "    location = home\n"
    "    world_time = 2047-03-18 08:00\n"
    "    pov = Lin\n"
    "    participants = [Lin, Bao]\n"
    "    dramatic_goal {\n"
    "        reveal = secret_deal\n"
    "    }\n"
    "}\n"
)


@pytest.fixture()
def src_file(tmp_path):
    p = tmp_path / "mini.npl"
    p.write_text(SRC, encoding="utf-8")
    return p


def test_inspect_reader_view(src_file, capsys):
    code = main(["inspect", str(src_file), "--scene", "1", "--reader"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Reader Model" in out
    assert "secret_deal" in out          # 已知（读者）
    assert "置信度 0.4" in out           # 证据性怀疑带置信度
    assert "行为可疑" in out             # 观察到的隐藏行为
    assert "在隐瞒" in out               # Bao 在隐瞒 secret_deal 的什么？


def test_inspect_character_nested_and_suspects(src_file, capsys):
    code = main(["inspect", str(src_file), "--character", "Lin", "--scene", "1"])
    assert code == 0
    out = capsys.readouterr().out
    assert "believes_about[Bao]" in out
    assert "置信度 0.4" in out


def test_actor_mock_deterministic(src_file, tmp_path, capsys):
    code1 = main(["actor", str(src_file), "--character", "Lin",
                  "--scene", "1", "--adapter", "mock",
                  "--out", str(tmp_path / "a")])
    code2 = main(["actor", str(src_file), "--character", "Lin",
                  "--scene", "1", "--adapter", "mock",
                  "--out", str(tmp_path / "b")])
    assert code1 == 0 and code2 == 0
    f1 = tmp_path / "a" / "actor_proposals" / "scene_001_Lin.json"
    f2 = tmp_path / "b" / "actor_proposals" / "scene_001_Lin.json"
    assert f1.exists() and f2.exists()
    assert json.loads(f1.read_text(encoding="utf-8")) == \
        json.loads(f2.read_text(encoding="utf-8"))
    capsys.readouterr()
