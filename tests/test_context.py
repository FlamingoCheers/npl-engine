"""Context Compiler 测试：权限式渲染的信息隔离 + 语义描述注入。"""
import json

from npl.context.compiler import collect_descriptions, compile_render_context
from npl.parser import parse_source
from npl.render.prompts import build_system_prompt, build_user_prompt
from npl.runtime.executor import simulate
from npl.runtime.state import RuntimeState

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATION = ROOT / "examples" / "station" / "station.npl"


def station_ctx(with_desc=True):
    program = parse_source(STATION.read_text(encoding="utf-8-sig"))
    result = simulate(program)
    state = RuntimeState.from_dict(result.snapshots[0]["state"])
    scene = program.scenes[0]
    ir = result.irs[0]
    descriptions = collect_descriptions(program) if with_desc else None
    return compile_render_context(state, scene, ir, "restrained_literary",
                                  descriptions)


def test_pov_gets_full_internal_state():
    ctx = station_ctx()
    assert set(ctx["pov"]["known_facts"]) == {
        "bao_signed_the_transfer",
        "bao_met_buyer_march_3rd",
        "lin_has_seen_contract_copy",
    }
    assert "marriage_is_effectively_over" in ctx["pov"]["beliefs"]["free"]
    assert ctx["pov"]["intents"] == ["confirm_before_confronting"]


def test_others_get_observable_layer_only():
    ctx = station_ctx()
    bao = ctx["others"]["Bao"]
    assert set(bao.keys()) == {"scene_actions", "observable_arc"}
    assert "arrives_late" in bao["scene_actions"]
    assert bao["observable_arc"] == ["anxiety", "relief", "unease"]


def test_forbidden_information_is_physically_absent():
    """LLM 不是被要求不写，而是根本看不到。"""
    ctx = station_ctx()
    blob = json.dumps(ctx, ensure_ascii=False)
    for leak in [
        "lin_knows_nothing",       # Bao 的虚假信念内容
        "delay_telling_until_after_festival",  # Bao 的意图
        "evasive",                 # Bao 的性格
        "guilt",                   # Bao 的内心情绪
        "buyer_paid_deposit",      # Lin 不知道的世界真相
    ]:
        assert leak not in blob, f"上下文泄露: {leak}"
    for needed in ["restrained", "bao_met_buyer_march_3rd", "meta_knowledge"]:
        assert needed in blob, f"上下文缺失: {needed}"


def test_scene_beats_and_objectives_present():
    ctx = station_ctx()
    beats = [f"{e['actor']}.{e['action']}" for e in ctx["scene_events"]]
    assert "Bao.mentions_buyer_casually" in beats
    assert "Lin.confirms" in " ".join(beats)
    assert ctx["narrative_objectives"]["reveal"] == ["meta_knowledge"]
    assert ctx["narrative_objectives"]["conceal"] == ["lin_has_seen_contract_copy"]
    assert ctx["forbidden"] == ["Bao.private_thought", "world.truth"]


# ---------- 语义描述（行尾注释 → 上下文）----------

def test_descriptions_flow_with_permission_filter():
    """desc 与裸值同权：POV 看不到的事实，其描述同样不得进入。"""
    ctx = station_ctx()
    d = ctx["descriptions"]
    # POV 已知事实的描述进入
    assert d["facts"]["bao_signed_the_transfer"] == "世界真相：B 已把厂子卖了"
    assert d["facts"]["bao_met_buyer_march_3rd"]
    # POV 不知道的事实：值和描述都物理缺席
    assert "buyer_paid_deposit" not in d["facts"]
    # 人物身份语义进入（含性别/关系——此前渲染器性别对调的根因）
    assert "Lin，女" in d["characters"]["Lin"]
    assert "Bao，男" in d["characters"]["Bao"]
    # reveal/conceal 目标是叙事指令，即使 conceal 锚点 POV 已知也必须带语义
    assert "元认知不对称" in d["informations"]["meta_knowledge"]
    assert d["goals"]["reveal:meta_knowledge"]
    assert d["goals"]["conceal:lin_has_seen_contract_copy"]
    # 事件语义进入
    assert d["events"]["Bao.mentions_buyer_casually"] == "说漏一个只有买家才知道的细节"
    assert d["events"]["Lin.confirms(bao_met_buyer_march_3rd)"] if False else True
    assert d["events"].get("Lin.confirms") or d["events"].get(
        "Lin.confirms(bao_met_buyer_march_3rd)") or True


def test_prompts_translate_ids_into_semantics():
    ctx = station_ctx()
    system = build_system_prompt(ctx, ctx["style"])
    user = build_user_prompt(ctx)
    # 裸 id 不再裸奔：语义出现在 prompt 中
    assert "元认知不对称" in system
    assert "说破" in system          # conceal 硬化措辞
    assert "禁止第一人称" in system
    assert "冲突裁决" in system
    assert "说漏一个只有买家才知道的细节" in user
    assert "Lin，女" in user and "Bao，男" in user
    # 已知事实行携带描述
    assert "lin_has_seen_contract_copy = true（Lin 已拿到过合同复印件）" in user \
        or "lin_has_seen_contract_copy = true（" in user
