"""inspect 测试：认知状态查询与虚假信念标注。"""
from npl.cli import main

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATION = ROOT / "examples" / "station" / "station.npl"


def test_inspect_bao_marks_false_belief(capsys):
    rc = main(["inspect", str(STATION), "--character", "Bao"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "虚假信念" in out
    assert "lin_knows_nothing" in out
    # Bao 不知道元认知信息（inspect 为上帝视角工具，可看 Bao 的意图）
    assert "不知道: meta_knowledge" in out
    assert "delay_telling_until_after_festival" in out


def test_inspect_lin_shows_scene_confirmation(capsys):
    rc = main(["inspect", str(STATION), "--character", "Lin"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "bao_met_buyer_march_3rd*" in out
    assert "本幕新确认" in out
    assert "marriage_is_effectively_over" in out
    assert "真值未知" in out


def test_inspect_all_characters_and_narrative_state(capsys):
    rc = main(["inspect", str(STATION)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "=== Lin" in out and "=== Bao" in out
    assert "reader_knows = [meta_knowledge]" in out
    assert "conceal_active = [lin_has_seen_contract_copy]" in out


def test_inspect_unknown_character_fails(capsys):
    rc = main(["inspect", str(STATION), "--character", "Wang"])
    assert rc == 2
