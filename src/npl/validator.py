"""NPL 语义校验器：AST → Diagnostic 列表。

错误码（ERROR 阻断 simulate/render）：
  NAR-002 引用未声明标识
  NAR-003 非法 access 引用（未知能力 / world 非 truth）
  NAR-004 场景约束违例（pov/事件主体/情绪轨迹人物不在 participants；withhold 释放幕次非法）
  NAR-013 必填字段缺失（scene.pov / scene.participants / information.truth）
  NAR-014 嵌套认知引用非法（v0.2：任意深度的心智人物未声明 / 嵌套命题未接地）
  NAR-015 import 目标文件不存在（v0.2）
  NAR-016 import 循环引用（v0.2）
  NAR-043 置信度越界（必须 0~1）
  NAR-044 世界事实值非法（v0.2：仅 true/false、数值或标识符枚举）
警告码（WARNING 不阻断）：
  NAR-041 自由命题（knows/believes/suspects/does_not_know 或 dramatic_goal 引用未接地 id）
  NAR-042 闪回场景包含改变世界真值的变更（时间线一致性提醒）
  NAR-061 母题未 introduce 即 recurrence/final（M4）
  NAR-062 母题 final 之前无 recurrence，或 final 之后仍有出现（M4）
  NAR-063 母题重复 introduce / 同幕重复声明（M4）
"""
import re

from . import ast_nodes as ast
from .ast_nodes import parse_nested_arg
from .errors import Diagnostic

CAPABILITIES = {"perception", "memory", "inference", "private_thought", "emotion", "intention"}
EPISTEMIC_SECTIONS = ("knows", "believes", "suspects", "does_not_know")
REVEAL_ACTIONS = {"reveals", "tells", "admits", "confesses", "discloses"}

from .runtime.executor import WORLD_SET_VERBS   # v0.4：与 executor 共用动词族
NESTED_ARG_RE = re.compile(r"^(\S+)\.(knows|does_not_know|believes)\((\S+)\)$")


def validate(program: ast.Program) -> list:
    diags = []

    def err(code, line, msg):
        diags.append(Diagnostic(code, "error", line, msg))

    def warn(code, line, msg):
        diags.append(Diagnostic(code, "warning", line, msg))

    # ---- 符号表 ----
    facts = {}
    if program.world is not None:
        for f in program.world.facts:
            if f.name in facts:
                err("NAR-012", f.line, f"重复的事实声明 '{f.name}'")
            facts[f.name] = f
        entity_names = set()
        for e in program.world.entities:
            if e.name in entity_names:
                err("NAR-012", e.line, f"重复的实体声明 '{e.name}'")
            entity_names.add(e.name)
        process_names = set()
        for proc in program.world.processes:   # v0.4：多阶段世界进程
            if proc.name in process_names:
                err("NAR-012", proc.line, f"重复的进程声明 '{proc.name}'")
            process_names.add(proc.name)
            if not proc.stages:
                warn("NAR-041", proc.line, f"进程 '{proc.name}' 没有任何阶段")
            for st in proc.stages:
                if st.fact not in facts:
                    err("NAR-002", st.line,
                        f"进程 '{proc.name}' 阶段 '{st.name}' 的标志事实 '{st.fact}' 未声明")

    characters = {c.name: c for c in program.characters}
    informations = {i.name: i for i in program.informations}

    # ---- 人物认知小节：接地检查 + 嵌套认知 + 置信度 ----
    for c in program.characters:
        for section in EPISTEMIC_SECTIONS:
            for entry in getattr(c, section):
                if isinstance(entry, ast.NestedBelief):
                    for holder, verb in entry.path:   # v0.2：校验每一层 holder
                        if holder not in characters:
                            err("NAR-014", entry.line,
                                f"嵌套认知引用了未声明的人物 '{holder}'（{c.name}.believes: {entry.display()}）")
                    if entry.prop not in facts:
                        err("NAR-014", entry.line,
                            f"嵌套认知的命题 '{entry.prop}' 必须是已声明的事实（{c.name} 关于 {entry.display()}）")
                    continue
                if entry.name not in facts:
                    warn("NAR-041", entry.line,
                         f"自由命题（无对应世界事实）'{entry.name}'（{c.name}.{section}）")
                if section == "suspects" and not (0.0 <= entry.confidence <= 1.0):
                    err("NAR-043", entry.line,
                        f"置信度必须在 0~1 之间，得到 {entry.confidence}（{c.name}.suspects: {entry.name}）")

        # v0.5 有向态度（CK2 式：值+理由）
        for rel in c.relations:
            if rel.target not in characters:
                err("NAR-002", rel.line,
                    f"relations 引用了未声明的人物 '{rel.target}'（{c.name} 对 {rel.target}）")
            elif rel.target == c.name:
                warn("NAR-041", rel.line, f"人物 '{c.name}' 对自身的态度声明（通常无意义）")
            if not (-1.0 <= rel.value <= 1.0):
                err("NAR-045", rel.line,
                    f"态度值必须在 -1.0~1.0 之间，得到 {rel.value}"
                    f"（{c.name} 对 {rel.target}.{rel.attitude}）")

    # ---- 信息对象 ----
    for info in program.informations:
        if info.truth is None:
            err("NAR-013", info.line, f"信息对象 '{info.name}' 缺少必填字段 truth")
        elif info.truth not in facts:
            err("NAR-002", info.truth_line,
                f"信息对象 '{info.name}' 的 truth 引用了未声明的事实 '{info.truth}'")
        for prop in info.known_by:
            if prop.name not in characters:
                err("NAR-002", prop.line, f"known_by 引用了未声明的人物 '{prop.name}'（{info.name}）")
        for prop in info.unknown_to:
            if prop.name not in characters:
                err("NAR-002", prop.line, f"unknown_to 引用了未声明的人物 '{prop.name}'（{info.name}）")
        for s in info.suspected_by:
            if s.name not in characters:
                err("NAR-002", s.line, f"suspected_by 引用了未声明的人物 '{s.name}'（{info.name}）")
            elif not (0.0 <= s.confidence <= 1.0):
                err("NAR-043", s.line,
                    f"置信度必须在 0~1 之间，得到 {s.confidence}（{info.name}.suspected_by: {s.name}）")

    # ---- 场景 ----
    for scene_idx, scene in enumerate(program.scenes, 1):
        if scene.pov is None:
            err("NAR-013", scene.line, f"场景 '{scene.title}' 缺少必填字段 pov")
        elif scene.pov not in characters:
            err("NAR-002", scene.pov_line, f"pov 引用了未声明的人物 '{scene.pov}'（{scene.title}）")

        names = set()
        if not scene.participants:
            err("NAR-013", scene.line, f"场景 '{scene.title}' 缺少必填字段 participants")
        for p in scene.participants:
            if p.name not in characters:
                err("NAR-002", p.line, f"participants 引用了未声明的人物 '{p.name}'（{scene.title}）")
            names.add(p.name)

        if scene.participants and scene.pov in characters and scene.pov not in names:
            err("NAR-004", scene.pov_line,
                f"pov 人物 '{scene.pov}' 必须出现在 participants 中（{scene.title}）")

        for rule in scene.access:
            if rule.subject == "world":
                if rule.capability != "truth":
                    err("NAR-003", rule.line,
                        f"非法 access 引用：world 仅有 truth 能力，得到 'world.{rule.capability}'")
            elif rule.subject in characters:
                if rule.capability not in CAPABILITIES:
                    err("NAR-003", rule.line,
                        f"非法 access 引用：未知能力 '{rule.capability}'（可用：{'/'.join(sorted(CAPABILITIES))}）")
            else:
                err("NAR-002", rule.line, f"access 主体 '{rule.subject}' 未声明（人物或 world）")

        for which in ("events", "information_changes"):
            for ref in getattr(scene, which):
                if ref.action in WORLD_SET_VERBS:
                    # v0.4 世界动词族：主体可为人物或实体；参数必须是已声明世界事实
                    if ref.actor not in characters and ref.actor not in entity_names:
                        err("NAR-002", ref.line,
                            f"{which} 的世界事件主体 '{ref.actor}' 未声明"
                            f"（人物或 entity，{scene.title}）")
                    for arg in ref.args:
                        if parse_nested_arg(arg) is not None:
                            err("NAR-002", ref.line,
                                f"世界动词不接受嵌套参数（{arg}，{scene.title}）")
                        elif arg not in facts:
                            err("NAR-002", ref.line,
                                f"世界动词的目标事实 '{arg}' 未在 world 块声明"
                                f"（{scene.title}）")
                    continue
                if ref.actor not in characters:
                    err("NAR-002", ref.line,
                        f"{which} 的事件主体 '{ref.actor}' 未声明（{scene.title}）")
                elif ref.actor not in names:
                    err("NAR-004", ref.line,
                        f"事件主体 '{ref.actor}' 不在场景 participants 中（{scene.title}）")
                for arg in ref.args:
                    nested = parse_nested_arg(arg)   # v0.2：递归多层嵌套参数
                    if nested is not None:
                        path, prop = nested
                        for holder, verb in path:
                            if holder not in characters:
                                err("NAR-014", ref.line,
                                    f"嵌套事件参数引用了未声明的人物 '{holder}'（{arg}，{scene.title}）")
                        if prop not in facts:
                            warn("NAR-041", ref.line,
                                 f"自由命题（无对应世界事实）'{prop}'（嵌套事件参数 {arg}）")

        if scene.flashback:
            for ref in scene.information_changes:
                if ref.action in REVEAL_ACTIONS:
                    warn("NAR-042", ref.line,
                         f"闪回场景 '{scene.title}' 包含改变世界真值的变更（{ref.actor}.{ref.action}）；请确认倒叙时间线一致性")

        for g in scene.dramatic_goal:
            if g.target not in facts and g.target not in informations:
                warn("NAR-041", g.line,
                     f"dramatic_goal 引用了未声明的信息/事实 '{g.target}'（按自由命题处理）")

        for arc in scene.emotional_arc:
            if arc.character not in characters:
                err("NAR-002", arc.line,
                    f"emotional_arc 引用了未声明的人物 '{arc.character}'（{scene.title}）")
            elif arc.character not in names:
                err("NAR-004", arc.line,
                    f"emotional_arc 人物 '{arc.character}' 不在场景 participants 中（{scene.title}）")

        # ---- M4 文学原语引用 ----
        for kind in ("foreshadows", "misdirects"):
            for ref in getattr(scene, kind):
                if ref.target not in facts and ref.target not in informations:
                    err("NAR-002", ref.line,
                        f"{kind} 引用了未声明的事实/信息对象 '{ref.target}'（{scene.title}）")
        for w in scene.withholds:
            if w.target not in facts and w.target not in informations:
                err("NAR-002", w.line,
                    f"withholds 引用了未声明的事实/信息对象 '{w.target}'（{scene.title}）")
            if not (1 <= w.until <= len(program.scenes)):
                err("NAR-004", w.line,
                    f"withhold 释放幕次 {w.until} 超出范围（1~{len(program.scenes)}）（{scene.title}）")
            elif w.until <= scene_idx:
                err("NAR-004", w.line,
                    f"withhold 释放幕次 {w.until} 必须晚于声明幕（场景 {scene_idx}，{scene.title}）")

        # v0.5 关系变更（绝对置值）
        for rc in scene.relation_changes:
            if rc.subject not in characters:
                err("NAR-002", rc.line,
                    f"relation_changes 主体 '{rc.subject}' 未声明（{scene.title}）")
            elif rc.subject not in names:
                err("NAR-004", rc.line,
                    f"relation_changes 主体 '{rc.subject}' 不在场景 participants 中（{scene.title}）")
            if rc.target not in characters:
                err("NAR-002", rc.line,
                    f"relation_changes 目标 '{rc.target}' 未声明（{scene.title}）")
            elif rc.target not in names:
                warn("NAR-004", rc.line,
                     f"relation_changes 目标 '{rc.target}' 不在本幕 participants 中"
                     f"（对不在场者的态度变化，{scene.title}）")
            if not (-1.0 <= rc.value <= 1.0):
                err("NAR-045", rc.line,
                    f"态度值必须在 -1.0~1.0 之间，得到 {rc.value}"
                    f"（{rc.subject}->{rc.target}.{rc.attitude}，{scene.title}）")

    # ---- v0.5 章节意图（goal/forbid/pacing 的目标必须接地） ----
    for it in program.intents:
        if it.arg not in facts and it.arg not in informations:
            err("NAR-002", it.line,
                f"intent '{it.kind}' 的目标 '{it.arg}' 未声明（必须是事实或信息对象）")

    # ---- M4 母题结构（跨幕顺序）----
    motif_history = {}
    for idx, scene in enumerate(program.scenes, 1):
        seen_in_scene = set()
        for m in scene.motifs:
            if m.motif in seen_in_scene:
                warn("NAR-063", m.line,
                     f"母题 '{m.motif}' 在同一幕 '{scene.title}' 内重复声明")
            seen_in_scene.add(m.motif)
            motif_history.setdefault(m.motif, []).append((m.role, m.line, idx))
    for mid, entries in motif_history.items():
        roles = [e[0] for e in entries]
        if "introduce" not in roles:
            warn("NAR-061", entries[0][1],
                 f"母题 '{mid}' 从未 introduce（首次出现是 '{roles[0]}'，场景 {entries[0][2]}）")
        else:
            first_intro = roles.index("introduce")
            for role, line, idx in entries[:first_intro]:
                warn("NAR-061", line,
                     f"母题 '{mid}' 在 introduce 之前出现 '{role}'（场景 {idx}）")
            if "introduce" in roles[first_intro + 1:]:
                j = first_intro + 1 + roles[first_intro + 1:].index("introduce")
                warn("NAR-063", entries[j][1],
                     f"母题 '{mid}' 重复 introduce（场景 {entries[j][2]}）")
        if "final" in roles:
            fi = roles.index("final")
            if "recurrence" not in roles[:fi]:
                warn("NAR-062", entries[fi][1],
                     f"母题 '{mid}' 的 final（场景 {entries[fi][2]}）之前没有 recurrence")
            if fi != len(roles) - 1:
                warn("NAR-062", entries[fi + 1][1],
                     f"母题 '{mid}' 在 final（场景 {entries[fi][2]}）之后仍有出现（场景 {entries[fi + 1][2]}）")

    return diags
