"""M2 检查器测试：规则引擎（离线）、词表兜底、diff、check CLI（mock）。"""
from npl.cli import main
from npl.parser import parse_source
from npl.runtime.executor import simulate
from npl.runtime.state import RuntimeState
from npl.checker.lexicon import scan_emotions
from npl.checker.rules import run_checks
from npl.style.rules import get_style

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATION = ROOT / "examples" / "station" / "station.npl"


def station_fixture():
    program = parse_source(STATION.read_text(encoding="utf-8-sig"))
    result = simulate(program)
    state = RuntimeState.from_dict(result.snapshots[0]["state"])
    scene = program.scenes[0]
    style = get_style("restrained_literary")
    return state, scene, result, style


def codes(findings):
    return sorted(f.code for f in findings)


# ---------------------------------------------------------------- 规则引擎
def test_clean_extraction_reports_nothing():
    state, scene, result, style = station_fixture()
    clean = {"fact_assertions": [], "omniscient_spans": [],
             "inner_mind_spans": [], "knowledge_claims": [],
             "concealed_evidence_spans": [],
             "reveal_achieved": {"fact": "meta_knowledge",
                                 "achieved": True, "span": ""},
             "emotions_named": []}
    assert run_checks(clean, state, scene, result.irs[0], style, "") == []


def test_unknown_fact_assertion_is_021():
    state, scene, result, style = station_fixture()
    ex = {"fact_assertions": [
        {"fact": "buyer_paid_deposit", "asserted": "true",
         "span": "定金早就付过了"}]}
    assert codes(run_checks(ex, state, scene, result.irs[0], style, "")) == \
        ["NAR-021"]


def test_belief_anchor_truth_assertion_is_exempt_from_021():
    """戏剧反讽豁免：叙述断言信念锚定事实的世界真值（她并非一无所知）
    是 reveal meta_knowledge 的合法机制，不判 021；conceal 由 031 管。"""
    state, scene, result, style = station_fixture()
    ex = {"fact_assertions": [
        {"fact": "lin_knows_nothing", "asserted": "false",
         "span": "她知道三号那天他不在城南。她不需要再问。"}]}
    assert run_checks(ex, state, scene, result.irs[0], style, "") == []
    # 反例：断言值与世界真值不符（或非信念锚定事实）仍要抓
    ex2 = {"fact_assertions": [
        {"fact": "lin_knows_nothing", "asserted": "true",
         "span": "她什么都不知道。"},
        {"fact": "buyer_paid_deposit", "asserted": "false",
         "span": "定金还没付。"}]}
    assert codes(run_checks(ex2, state, scene, result.irs[0], style, "")) == \
        ["NAR-021", "NAR-021"]


def test_omniscient_and_inner_mind_are_021():
    state, scene, result, style = station_fixture()
    ex = {"omniscient_spans": [{"span": "Bao 不知道的是…", "why": "旁白"}],
          "inner_mind_spans": [{"character": "Bao", "span": "他心里一阵恐慌"}]}
    fs = run_checks(ex, state, scene, result.irs[0], style, "")
    assert codes(fs) == ["NAR-021", "NAR-021"]


def test_character_omniscience_is_022():
    state, scene, result, style = station_fixture()
    ex = {"knowledge_claims": [
        {"character": "Bao", "claims_to_know": "meta_knowledge",
         "span": "你都知道了？他说"}]}
    # meta_knowledge 是信息对象 id 而非 fact id——rules 只接 fact id，
    # 其真相锚点 lin_has_seen_contract_copy 同样不在 Bao.knows 中
    ex["knowledge_claims"][0]["claims_to_know"] = "lin_has_seen_contract_copy"
    assert codes(run_checks(ex, state, scene, result.irs[0], style, "")) == \
        ["NAR-022"]


def test_dialogue_assertion_by_ignorant_char_is_022():
    """022b：非 POV 人物在对话中断言其认知外的事实（求证式点破）。
    该断言同时破了 conceal（031）——双重违规属正确行为。"""
    state, scene, result, style = station_fixture()
    ex = {"fact_assertions": [
        {"fact": "lin_has_seen_contract_copy", "asserted": "true",
         "asserted_by": "Bao", "span": "你是怎么拿到那份复印件的？"}]}
    cs = codes(run_checks(ex, state, scene, result.irs[0], style, ""))
    assert "NAR-022" in cs and "NAR-031" in cs


def test_belief_consistent_claim_is_not_022():
    """断言内容在其 believes 中 → 与认知状态一致，不算角色全知。"""
    state, scene, result, style = station_fixture()
    ex = {"fact_assertions": [
        {"fact": "lin_knows_nothing", "asserted": "true",
         "asserted_by": "Bao", "span": "她什么都不知道"}]}
    assert run_checks(ex, state, scene, result.irs[0], style, "") == []


def test_concealed_fact_assertion_is_031_even_for_pov():
    """031 严格语义：conceal 事实被断言为真即破（不论断言者）。"""
    state, scene, result, style = station_fixture()
    ex = {"fact_assertions": [
        {"fact": "lin_has_seen_contract_copy", "asserted": "true",
         "asserted_by": "Lin", "span": "她从包里取出复印件"}]}
    assert codes(run_checks(ex, state, scene, result.irs[0], style, "")) == \
        ["NAR-031"]


def test_conceal_violation_is_031():
    state, scene, result, style = station_fixture()
    ex = {"concealed_evidence_spans": [
        {"fact": "lin_has_seen_contract_copy",
         "span": "她把复印件推到桌对面"}]}
    assert codes(run_checks(ex, state, scene, result.irs[0], style, "")) == \
        ["NAR-031"]


def test_reveal_not_achieved_is_032_warning():
    state, scene, result, style = station_fixture()
    ex = {"reveal_achieved": {"fact": "meta_knowledge",
                              "achieved": False, "span": ""}}
    fs = run_checks(ex, state, scene, result.irs[0], style, "")
    assert codes(fs) == ["NAR-032"]
    assert fs[0].severity == "warning"


def test_known_fact_assertion_is_fine():
    """POV 断言自己已知的事实不属于泄漏。"""
    state, scene, result, style = station_fixture()
    ex = {"fact_assertions": [
        {"fact": "bao_signed_the_transfer", "asserted": "true",
         "span": "厂子已经卖了"}]}
    assert run_checks(ex, state, scene, result.irs[0], style, "") == []


# ---------------------------------------------------------------- 词表兜底
def test_lexicon_catches_emotion_naming():
    hits = scan_emotions("她的心中涌起一股不安。他看起来很平静。")
    assert any(h["emotion"] == "不安" for h in hits)
    assert all(h["emotion"] != "平静" for h in hits)  # 平静不在词表


def test_emotion_naming_is_051_warning():
    state, scene, result, style = station_fixture()
    ex = {"emotions_named": [{"subject": "Lin", "emotion": "不安",
                              "span": "心中涌起一股不安"}]}
    fs = run_checks(ex, state, scene, result.irs[0], style,
                    "心中涌起一股不安")
    assert "NAR-051" in codes(fs)
    assert all(f.severity == "warning" for f in fs
               if f.code == "NAR-051")


# ---------------------------------------------------------------- diff
def test_diff_shows_scene_changes(capsys):
    rc = main(["diff", str(STATION)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Lin.knows: + bao_met_buyer_march_3rd" in out
    assert "narrative.reader_knows: + meta_knowledge" in out
    assert "Lin.arc.current: ∅ -> cold_clarity" in out


# ---------------------------------------------------------------- check CLI
def test_check_with_mock_adapter_clean(tmp_path, capsys):
    # mock 抽取器返回全干净结果 → 0 ERROR
    prose = tmp_path / "scene_001.md"
    prose.write_text("（mock 渲染输出）", encoding="utf-8")
    rc = main(["check", str(STATION), "--prose", str(prose),
               "--adapter", "mock"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0 ERROR" in out


def test_salvage_truncated_array():
    from npl.checker.extract import _salvage_json
    raw = ('{"fact_assertions": [{"fact": "a", "span": "完整"},'
           ' {"fact": "b", "span": "被截')
    d = _salvage_json(raw)
    assert d and [x["fact"] for x in d["fact_assertions"]] == ["a"]


def test_salvage_no_boundary_returns_none():
    from npl.checker.extract import _salvage_json
    raw = '{"fact_assertions": [{"fact": "a", "span": "引号未闭合就断'
    assert _salvage_json(raw) is None


def test_salvage_bracket_mismatch_returns_none():
    from npl.checker.extract import _salvage_json
    assert _salvage_json('{"a": [1,2} 垃圾') is None
