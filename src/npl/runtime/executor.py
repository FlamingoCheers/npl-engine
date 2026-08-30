"""场景执行器：确定性事件流 → 状态转换 + Scene IR + 快照。

simulate 路径零 LLM 调用、完全确定性 —— 这是"Runtime is the source of truth"的可测试表达。

事件语义（v0.1 最小动词表 + M3 扩展 + v0.4 世界动词族）：
规范见 docs/ISA手册.md；权威实现见本文件。
  information_changes（改认知状态）：
    CONFIRM 族（confirms/discovers/learns/realizes/remembers/infers/notices/finds）
        Actor.arg → Actor.knows += arg
        嵌套参数 B.knows(x) / B.does_not_know(x) / B.believes(x)
            → Actor.believes_about[B] 更新（A 对他人心智的建模）
    REVEAL 族（reveals/tells/admits/confesses/discloses）
        arg → 全部在场人物 knows += arg
    MISUNDERSTAND 族（misunderstands/mistakes）
        Actor.arg → Actor.believes += arg（即使世界真值为假；不入 knows）
    SUSPECT 族（suspects/doubts）
        Actor.arg → Actor.suspects[arg] = max(现有, 0.6)
    HIDE 族（hides/conceals/withholds）
        Actor.arg → Actor.hides += arg
  events（叙事节拍，只处理读者可见的行为动词）：
    HIDE / SUSPECT 族照常生效（隐藏与怀疑行为本身是读者可观察的）；
    其余动词不改状态。
  Reader Model（每幕末尾确定性更新，§2.3 读者世界）：
    读者采用 POV 的怀疑（suspicions += POV.suspects）；
    观察到隐藏行为 → suspicions += prop，unanswered_questions += "X 在隐瞒 Y 的什么？"；
    conceal 目标 → unanswered_questions += "Y 的真相尚未揭示"（reveal 达成时回收）。
"""
import re

from ..ir.scene_ir import build_ir
from .state import RuntimeState

CONFIRM_VERBS = {"confirms", "discovers", "learns", "realizes",
                 "remembers", "infers", "notices", "finds"}
REVEAL_VERBS = {"reveals", "tells", "admits", "confesses", "discloses"}
MISUNDERSTAND_VERBS = {"misunderstands", "mistakes"}
SUSPECT_VERBS = {"suspects", "doubts"}
HIDE_VERBS = {"hides", "conceals", "withholds"}
WORLD_SET_VERBS = {"sets", "clears"}   # v0.4：世界事实变更（物理层）
DEFAULT_SUSPECT_CONFIDENCE = 0.6

from ..ast_nodes import parse_nested_arg   # v0.2：与 validator 共用，避免循环依赖

class SimulationResult:
    def __init__(self, program):
        self.program = program
        self.snapshots = []   # list[dict]：每幕后完整状态快照
        self.irs = []         # list[dict]：每幕 Scene IR
        self.changes = []     # list[dict]：每幕认知变更


def resolve_access(scene):
    """Presentation 层：解析 POV 权限。无 access 块时使用缺省策略（语言规范 §4.4）。"""
    if scene.access:
        allows = [f"{r.subject}.{r.capability}" for r in scene.access if r.kind == "allow"]
        denies = [f"{r.subject}.{r.capability}" for r in scene.access if r.kind == "deny"]
    else:
        allows = [f"{scene.pov}.{cap}" for cap in ("perception", "memory", "inference")]
        denies = [f"{p.name}.private_thought" for p in scene.participants
                  if p.name != scene.pov]
        denies.append("world.truth")
    return {"allows": allows, "denies": denies}


def _apply_change(state, actor, action, arg, participants):
    """单条变更/事件语义分发。

    WORLD 族（sets/clears）最先分发：物理事实变更，两通道均生效；
    嵌套参数仅在 CONFIRM 族下生效。
    """
    if action in WORLD_SET_VERBS:
        state.world["facts"][arg] = (action == "sets")
        return
    nested = parse_nested_arg(arg)
    if nested is not None:
        if action in CONFIRM_VERBS:
            state.nested_realize(actor, nested[0], nested[1])
        return
    if action in REVEAL_VERBS:
        state.reveal_to_all(participants, arg)
    elif action in CONFIRM_VERBS:
        state.confirm(actor, arg)
    elif action in MISUNDERSTAND_VERBS:
        state.misunderstand(actor, arg)
    elif action in SUSPECT_VERBS:
        state.suspect(actor, arg, DEFAULT_SUSPECT_CONFIDENCE)
    elif action in HIDE_VERBS:
        state.hide(actor, arg)


def update_reader_model(state, scene, observed_hides):
    """Reader Model 逐幕确定性更新（§2.3 读者世界）。"""
    pov = scene.pov
    if pov in state.characters:
        state.narrative["suspicions"] |= set(state.characters[pov]["suspects"])
    for actor, prop in observed_hides:
        state.narrative["suspicions"].add(prop)
        state.narrative["unanswered_questions"].add(f"{actor} 在隐瞒 {prop} 的什么？")


def execute_scene(state: RuntimeState, scene, scene_index: int,
                  pending_withholds=None):
    """执行一幕。pending_withholds 携带跨幕的 withhold 声明（M4），返回更新后的列表。"""
    pending_withholds = list(pending_withholds or [])

    # 到期 withhold 释放：隐藏解除（先于本幕一切处理）
    for w in [w for w in pending_withholds if w.until == scene_index]:
        state.narrative["conceal_active"].discard(w.target)
    pending_withholds = [w for w in pending_withholds if w.until != scene_index]

    participants = [p.name for p in scene.participants]
    before = {name: {
        "knows": set(state.characters[name]["knows"]) if name in state.characters else set(),
        "believes": set(state.characters[name]["believes"]) if name in state.characters else set(),
        "suspects": set(state.characters[name]["suspects"]) if name in state.characters else set(),
        "hides": set(state.characters[name]["hides"]) if name in state.characters else set(),
    } for name in participants}

    presentation = resolve_access(scene)

    # information_changes 才是正式的状态转换；隐藏行为天然可观察，纳入 Reader Model
    observed_hides = []
    for ref in scene.information_changes:
        for arg in ref.args:
            _apply_change(state, ref.actor, ref.action, arg, participants)
            if ref.action in HIDE_VERBS and parse_nested_arg(arg) is None:
                observed_hides.append((ref.actor, arg))

    # events 是叙事节拍；世界动词（物理事实）、隐藏/怀疑行为读者可见，纳入处理
    for ref in scene.events:
        for arg in ref.args:
            if parse_nested_arg(arg) is not None:
                continue
            if ref.action in WORLD_SET_VERBS:
                _apply_change(state, ref.actor, ref.action, arg, participants)
            elif ref.action in HIDE_VERBS:
                state.hide(ref.actor, arg)
                observed_hides.append((ref.actor, arg))
            elif ref.action in SUSPECT_VERBS:
                state.suspect(ref.actor, arg, DEFAULT_SUSPECT_CONFIDENCE)

    for arc in scene.emotional_arc:
        state.apply_arc(arc.character, arc.states)

    reveals = [g.target for g in scene.dramatic_goal if g.kind == "reveal"]
    conceals = [g.target for g in scene.dramatic_goal if g.kind == "conceal"]
    state.apply_goals(reveals, conceals)

    # M4 文学原语状态
    for m in scene.motifs:
        state.narrative["motifs"].setdefault(m.motif, []).append(
            {"role": m.role, "scene": scene_index})
    for w in scene.withholds:
        state.narrative["conceal_active"].add(w.target)  # 限时隐藏，入 conceal 管
        pending_withholds.append(w)
    for d in scene.misdirects:
        state.narrative["misdirects_active"].add(d.target)
        state.narrative["suspicions"].add(d.target)  # 读者被引向怀疑该方向

    update_reader_model(state, scene, observed_hides)

    def delta(key):
        out = {}
        for name in before:
            if name not in state.characters:
                out[name] = []
                continue
            cur = state.characters[name][key]
            added = (set(cur) - before[name][key]) if isinstance(cur, dict) \
                else (cur - before[name][key])
            out[name] = sorted(added)
        return out

    changes = {
        "knows_added": delta("knows"),
        "believes_added": delta("believes"),
        "suspects_added": delta("suspects"),
        "hides_added": delta("hides"),
    }
    ir = build_ir(state, scene, scene_index, presentation, reveals, conceals)
    return ir, changes, pending_withholds


def simulate_continue(state, scenes, start_index=1):
    """从既有状态续跑追加场景（快照续跑 / 分支的执行核心）。

    state 通常来自 RuntimeState.from_dict(snapshot["state"])；start_index
    为续接的场景编号（基程序快照的 scene_index）。确定性：同一 state 与
    scenes 产生逐字节一致的快照序列。
    """
    result = SimulationResult(None)
    pending = []
    for offset, scene in enumerate(scenes):
        idx = start_index + offset
        ir, changes, pending = execute_scene(state, scene, idx, pending)
        result.irs.append(ir)
        result.changes.append(changes)
        result.snapshots.append({
            "meta": {"scene_index": idx, "scene_title": scene.title,
                     "world_time": scene.world_time, "flashback": scene.flashback},
            "state": state.to_dict(),
        })
    return result


def simulate(program):
    """全程序确定性模拟：返回每幕的快照、IR 与认知变更。"""
    return simulate_continue(RuntimeState.from_program(program), program.scenes, 1)
