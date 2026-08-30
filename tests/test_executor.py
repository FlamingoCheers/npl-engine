"""执行器测试：状态转换、确定性、快照。"""
import json

from npl.parser import parse_source
from npl.runtime.executor import simulate
from npl.runtime.state import RuntimeState

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATION = ROOT / "examples" / "station" / "station.npl"


def station_program():
    return parse_source(STATION.read_text(encoding="utf-8-sig"))


def test_simulate_produces_one_snapshot_per_scene():
    result = simulate(station_program())
    assert len(result.snapshots) == 1
    assert result.snapshots[0]["meta"]["scene_index"] == 1
    assert result.snapshots[0]["meta"]["scene_title"] == "夜车"


def test_information_change_confirms_fact_for_actor():
    result = simulate(station_program())
    state = RuntimeState.from_dict(result.snapshots[0]["state"])
    assert "bao_met_buyer_march_3rd" in state.characters["Lin"]["knows"]
    assert result.changes[0]["knows_added"]["Lin"] == ["bao_met_buyer_march_3rd"]


# ---------------- M3：新动词族 / 嵌套认知 / Reader Model / 闪回 ----------------

M3_SRC = (
    "npl@0.1\n"
    "world w {\n"
    "    fact secret_deal = true   // 秘密交易\n"
    "    fact false_rumor = false  // 假传闻\n"
    "}\n"
    "character Lin {\n"
    "    believes:\n"
    "        Bao.does_not_know(secret_deal)\n"
    "}\n"
    "character Bao {\n"
    "}\n"
    "scene \"试探\" {\n"
    "    location = room\n"
    "    world_time = 2047-03-17 23:40\n"
    "    pov = Lin\n"
    "    participants = [Lin, Bao]\n"
    "    information_changes {\n"
    "        Lin.realizes(Bao.knows(secret_deal))   // 嵌套更新\n"
    "        Lin.misunderstands(false_rumor)         // 误信假传闻\n"
    "        Lin.suspects(secret_deal)               // 怀疑\n"
    "        Bao.hides(secret_deal)                  // 隐藏\n"
    "    }\n"
    "    dramatic_goal {\n"
    "        conceal = secret_deal\n"
    "    }\n"
    "}\n"
)


def test_m3_new_verbs_change_state():
    result = simulate(parse_source(M3_SRC))
    state = RuntimeState.from_dict(result.snapshots[0]["state"])
    # 嵌套更新：Lin 现在相信 Bao 知道 secret_deal
    assert state.characters["Lin"]["believes_about"]["Bao"]["knows"] == {"secret_deal"}
    assert state.characters["Lin"]["believes_about"]["Bao"]["does_not_know"] == set()
    # 误信：假传闻进入 believes 而非 knows
    assert "false_rumor" in state.characters["Lin"]["believes"]
    assert "false_rumor" not in state.characters["Lin"]["knows"]
    # 怀疑：置信度取缺省 0.6
    assert state.characters["Lin"]["suspects"]["secret_deal"] == 0.6
    # 隐藏：Bao.hides 生效
    assert state.characters["Bao"]["hides"] == {"secret_deal"}


def test_m3_reader_model_accumulates():
    result = simulate(parse_source(M3_SRC))
    nar = result.snapshots[0]["state"]["narrative"]
    # 读者采用 POV 的怀疑 + 观察到隐藏行为
    assert "secret_deal" in nar["suspicions"]
    assert "Bao 在隐瞒 secret_deal 的什么？" in nar["unanswered_questions"]
    # conceal 目标生成未回答问题
    assert "secret_deal 的真相尚未揭示" in nar["unanswered_questions"]


def test_m3_reveal_goal_recycles_question():
    src = M3_SRC.replace("        conceal = secret_deal\n",
                         "        reveal = secret_deal\n")
    result = simulate(parse_source(src))
    nar = result.snapshots[0]["state"]["narrative"]
    assert "secret_deal 的真相尚未揭示" not in nar["unanswered_questions"]
    assert "secret_deal" in nar["reader_knows"]


def test_m3_flashback_meta_recorded():
    src = M3_SRC.replace('    world_time = 2047-03-17 23:40\n',
                         '    world_time = 2047-03-10 09:00\n    flashback = true\n')
    result = simulate(parse_source(src))
    meta = result.snapshots[0]["meta"]
    assert meta["flashback"] is True
    assert meta["world_time"] == "2047-03-10 09:00"
    assert result.irs[0]["framing"]["flashback"] is True


def test_non_participant_knowledge_unchanged():
    result = simulate(station_program())
    state = RuntimeState.from_dict(result.snapshots[0]["state"])
    # Bao 不在场感知范围内：confirms 只作用于 Lin
    assert sorted(state.characters["Bao"]["knows"]) == [
        "bao_met_buyer_march_3rd", "bao_signed_the_transfer"]


def test_dramatic_goal_updates_narrative_state():
    result = simulate(station_program())
    nar = result.snapshots[0]["state"]["narrative"]
    assert nar["reader_knows"] == ["meta_knowledge"]
    assert nar["conceal_active"] == ["lin_has_seen_contract_copy"]


def test_simulate_is_deterministic():
    a = simulate(station_program())
    b = simulate(station_program())
    assert (json.dumps(a.snapshots, ensure_ascii=False, sort_keys=True)
            == json.dumps(b.snapshots, ensure_ascii=False, sort_keys=True))
    assert (json.dumps(a.irs, ensure_ascii=False, sort_keys=True)
            == json.dumps(b.irs, ensure_ascii=False, sort_keys=True))


def test_reveal_verb_shares_knowledge_with_all_present():
    src = ("npl@0.1\n"
           "world w {\n"
           "    fact hidden_truth = true\n"
           "}\n"
           "character A {\n"
           "    knows:\n"
           "        hidden_truth\n"
           "}\n"
           "character B {\n"
           "}\n"
           "scene \"摊牌\" {\n"
           "    location = room\n"
           "    world_time = 2047-03-17 23:40\n"
           "    pov = A\n"
           "    participants = [A, B]\n"
           "    information_changes {\n"
           "        A.reveals(hidden_truth)\n"
           "    }\n"
           "}\n")
    result = simulate(parse_source(src))
    state = RuntimeState.from_dict(result.snapshots[0]["state"])
    assert "hidden_truth" in state.characters["A"]["knows"]
    assert "hidden_truth" in state.characters["B"]["knows"]


def test_runtime_state_roundtrip():
    result = simulate(station_program())
    d = result.snapshots[0]["state"]
    state = RuntimeState.from_dict(RuntimeState.from_dict(d).to_dict())
    assert state.to_dict() == d
