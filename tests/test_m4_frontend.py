"""M4 测试：文学原语（motif/foreshadow/withhold/misdirect）+ style 块。"""
import pytest

from npl.ast_nodes import StyleDecl
from npl.errors import NPLSyntaxError
from npl.parser import parse_source
from npl.runtime.executor import simulate
from npl.runtime.state import RuntimeState
from npl.style.rules import resolve_style, STYLE_PRESETS
from npl.validator import validate


def codes(diags):
    return [d.code for d in diags]


def _program(extra_scenes="", style_block=None):
    style = style_block if style_block is not None else (
        'style restrained_literary {\n'
        '    sentence_max = 22\n'
        '    emotion_naming = forbid\n'
        '    sensory = low\n'
        '    dialogue_gaps = true\n'
        '    rule = "厨房与机械意象优先"\n'
        '}\n')
    src = (
        "npl@0.1\n"
        "world w {\n"
        "    fact deal_secret = true\n"
        "    fact rumor_false = false\n"
        "}\n"
        "character Lin {}\n"
        "character Bao {}\n"
        'scene "一" {\n'
        "    location = room\n"
        "    world_time = 2047-03-10 09:00\n"
        "    pov = Lin\n"
        "    participants = [Lin]\n"
        "    motifs {\n"
        "        茶杯 = introduce // 缺口茶杯第一次出现\n"
        "    }\n"
        "    foreshadows {\n"
        "        deal_secret // 电话里冒出定金二字\n"
        "    }\n"
        "    withholds {\n"
        "        deal_secret until = 2 // 只埋不揭\n"
        "    }\n"
        "    misdirects {\n"
        "        rumor_false // 读者误以为流言为真\n"
        "    }\n"
        "}\n"
        'scene "二" {\n'
        "    location = room\n"
        "    world_time = 2047-03-11 09:00\n"
        "    pov = Lin\n"
        "    participants = [Lin]\n"
        "    information_changes {\n"
        "        Lin.confirms(deal_secret)\n"
        "    }\n"
        "}\n" + extra_scenes + style
    )
    return parse_source(src)


# ---------- 解析 ----------

def test_parse_m4_decls():
    p = _program()
    s1 = p.scenes[0]
    m = s1.motifs[0]
    assert m.motif == "茶杯" and m.role == "introduce"
    assert "缺口" in (m.desc or "")
    assert s1.foreshadows[0].target == "deal_secret"
    w = s1.withholds[0]
    assert w.target == "deal_secret" and w.until == 2
    assert s1.misdirects[0].target == "rumor_false"
    st = p.styles[0]
    assert st.key == "restrained_literary"
    assert st.sentence_max == 22
    assert st.emotion_naming == "forbid"
    assert st.sensory == "low"
    assert st.dialogue_gaps is True
    assert st.rules == ["厨房与机械意象优先"]


def test_style_dup_top_level_nar_011():
    dup = ('style restrained_literary { sentence_max = 10 }\n'
           'style restrained_literary { sentence_max = 20 }\n')
    with pytest.raises(NPLSyntaxError) as ei:
        _program(style_block=dup)
    assert ei.value.code == "NAR-011"


def test_style_dup_field_nar_012():
    dup = ('style restrained_literary {\n'
           '    sentence_max = 10\n'
           '    sentence_max = 20\n'
           '}\n')
    with pytest.raises(NPLSyntaxError) as ei:
        _program(style_block=dup)
    assert ei.value.code == "NAR-012"


def test_bad_motif_role_nar_001():
    with pytest.raises(NPLSyntaxError) as ei:
        parse_source(
            "npl@0.1\nworld w { fact x = true }\ncharacter A {}\n"
            'scene "s" {\n    pov = A\n    participants = [A]\n'
            "    motifs { x = final_first }\n}\n")
    assert ei.value.code == "NAR-001"


def test_bad_style_value_nar_001():
    with pytest.raises(NPLSyntaxError) as ei:
        _program(
            style_block='style restrained_literary { emotion_naming = maybe }\n')
    assert ei.value.code == "NAR-001"


# ---------- 结构校验 ----------

def test_motif_no_introduce_nar_061():
    src_extra = ('scene "二点五" {\n'
                 "    location = room\n"
                 "    world_time = 2047-03-12 09:00\n"
                 "    pov = Lin\n    participants = [Lin]\n"
                 "    motifs { 茶杯 = recurrence }\n"
                 "}\n")
    # 幕一 introduce 仍在 -> 合法；把幕一的 introduce 删掉则 061
    p = _program(extra_scenes=src_extra)
    assert "NAR-061" not in codes(validate(p))
    src_no_intro = src_extra.replace(
        'scene "二点五"', 'scene "零"')  # 仅保证位置无关
    p2 = parse_source(
        "npl@0.1\nworld w { fact x = true }\ncharacter A {}\n"
        'scene "s" {\n    pov = A\n    participants = [A]\n'
        "    motifs { 茶杯 = recurrence }\n}\n")
    assert "NAR-061" in codes(validate(p2))


def test_motif_final_without_recurrence_nar_062():
    p = parse_source(
        "npl@0.1\nworld w { fact x = true }\ncharacter A {}\n"
        'scene "s" {\n    pov = A\n    participants = [A]\n'
        "    motifs { 茶杯 = introduce }\n}\n"
        'scene "t" {\n    pov = A\n    participants = [A]\n'
        "    motifs { 茶杯 = final }\n}\n")
    assert "NAR-062" in codes(validate(p))


def test_motif_double_introduce_nar_063():
    p = parse_source(
        "npl@0.1\nworld w { fact x = true }\ncharacter A {}\n"
        'scene "s" {\n    pov = A\n    participants = [A]\n'
        "    motifs { 茶杯 = introduce }\n}\n"
        'scene "t" {\n    pov = A\n    participants = [A]\n'
        "    motifs { 茶杯 = introduce }\n}\n")
    assert "NAR-063" in codes(validate(p))


def test_withhold_until_out_of_range_nar_004():
    p = _program()
    p.scenes[0].withholds[0].until = 5
    assert "NAR-004" in codes(validate(p))
    p2 = parse_source(
        "npl@0.1\nworld w { fact x = true }\ncharacter A {}\n"
        'scene "s" {\n    pov = A\n    participants = [A]\n'
        "    withholds { x until = 1 }\n}\n")
    assert "NAR-004" in codes(validate(p2))


def test_m4_undeclared_refs_nar_002():
    p = _program()
    p.scenes[0].foreshadows[0].target = "ghost"
    p.scenes[0].withholds[0].target = "ghost"
    p.scenes[0].misdirects[0].target = "ghost"
    got = codes(validate(p))
    assert got.count("NAR-002") == 3


def test_m4_valid_program_clean():
    diags = validate(_program())
    assert [d for d in diags if d.severity == "error"] == []


# ---------- 运行时 ----------

def test_executor_withhold_release_motif_misdirect():
    p = _program()
    result = simulate(p)
    s1 = result.snapshots[0]["state"]["narrative"]
    assert "deal_secret" in s1["conceal_active"]          # 声明即隐藏
    assert s1["motifs"]["茶杯"] == [{"role": "introduce", "scene": 1}]
    assert "rumor_false" in s1["misdirects_active"]
    assert "rumor_false" in s1["suspicions"]
    s2 = result.snapshots[1]["state"]
    assert "deal_secret" not in s2["narrative"]["conceal_active"]  # until=2 幕首释放
    assert "deal_secret" in s2["characters"]["Lin"]["knows"]       # confirm 生效


# ---------- 风格合并 ----------

def test_resolve_style_merges_decls():
    p = _program()
    st = resolve_style("restrained_literary", p.styles)
    assert st["constraints"]["sentence_max"] == 22
    assert any("22" in r for r in st["rules"])
    assert "lush_emotion" in STYLE_PRESETS


# ---------- 规则引擎 052/064-067 ----------

def _state(p, idx=-1):
    result = simulate(p)
    return RuntimeState.from_dict(result.snapshots[idx]["state"])


def test_nar_052_long_sentence_ratio():
    p = _program()
    scene = p.scenes[0]
    st = resolve_style("restrained_literary", p.styles)
    state = _state(p, 0)
    prose = "短句一。短句二。" + "。".join(["这一句远远超出了限制的长度" * 2] * 4) + "。"
    findings = _checks({}, state, scene, st, prose, scene_idx=0, program=p)
    assert any(f.code == "NAR-052" for f in findings)


def test_nar_064_missing_motif():
    p = _program()
    state = _state(p, 0)
    findings = _checks({}, state, p.scenes[0], resolve_style(
        "restrained_literary", p.styles), "", scene_idx=0, program=p)
    assert any(f.code == "NAR-064" for f in findings)
    findings2 = _checks({"motif_mentions": [{"motif": "茶杯", "span": "缺口茶杯"}]},
                        state, p.scenes[0], resolve_style(
                            "restrained_literary", p.styles),
                        "", scene_idx=0, program=p)
    assert not any(f.code == "NAR-064" for f in findings2)


def test_nar_065_foreshadow_payoff():
    p = _program()  # 幕二 confirms(deal_secret) -> 有回收
    state = _state(p, 0)
    style = resolve_style("restrained_literary", p.styles)
    assert not any(f.code == "NAR-065" for f in _checks(
        {}, state, p.scenes[0], style, "", scene_idx=0, program=p))
    p2 = parse_source(
        "npl@0.1\nworld w { fact x = true }\ncharacter A {}\n"
        'scene "s" {\n    pov = A\n    participants = [A]\n'
        "    foreshadows { x }\n}\n"
        'scene "t" {\n    pov = A\n    participants = [A]\n}\n')
    state2 = _state(p2, 0)
    assert any(f.code == "NAR-065" for f in _checks(
        {}, state2, p2.scenes[0], style, "", scene_idx=0, program=p2))


def test_nar_066_withhold_due_unknown():
    p = _program()  # until=2 且幕二 confirm -> 读者已知，不报
    state = _state(p, 1)
    style = resolve_style("restrained_literary", p.styles)
    assert not any(f.code == "NAR-066" for f in _checks(
        {}, state, p.scenes[1], style, "", scene_idx=1, program=p))
    # 去掉幕二的 confirm -> 到期读者仍不知道
    src = ("npl@0.1\nworld w { fact x = true }\ncharacter A {}\n"
           'scene "s" {\n    pov = A\n    participants = [A]\n'
           "    withholds { x until = 2 }\n}\n"
           'scene "t" {\n    pov = A\n    participants = [A]\n}\n')
    p2 = parse_source(src)
    state2 = _state(p2, 1)
    assert any(f.code == "NAR-066" for f in _checks(
        {}, state2, p2.scenes[1], style, "", scene_idx=1, program=p2))


def test_nar_067_misdirect_defects():
    p = _program()
    state = _state(p, 0)
    style = resolve_style("restrained_literary", p.styles)
    # rumor_false 为假 -> 无"目标为真"告警；但后续无 reveal -> 无反转告警
    f1 = _checks({}, state, p.scenes[0], style, "", scene_idx=0, program=p)
    codes1 = [f.code for f in f1]
    assert "NAR-067" in codes1
    assert not any(f.code == "NAR-067" and "为真" in f.message for f in f1)
    # 目标改为真事实 deal_secret -> 目标为真告警
    p.scenes[0].misdirects[0].target = "deal_secret"
    f2 = _checks({}, _state(p, 0), p.scenes[0], style, "", scene_idx=0,
                 program=p)
    assert any(f.code == "NAR-067" and "为真" in f.message for f in f2)


def _checks(extraction, state, scene, style, prose, scene_idx, program):
    from npl.checker.rules import run_checks
    return run_checks(extraction, state, scene, {}, style, prose,
                      scene_idx=scene_idx, program=program)
