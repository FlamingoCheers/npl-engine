"""Context Compiler：组装 LLM 渲染上下文。

权限式渲染的核心：deny 的信息【物理上不进入】上下文——
LLM 不是"被要求不写"，而是根本看不到。

- POV：完整内部状态（known_facts = 世界事实 ∩ pov.knows）
- 非 POV 人物：只有场景内行为节拍 + 外部表现轨迹（可观察层）
- 世界真相：只有 POV 已知的部分进入；其余对渲染器不存在

语义层：.npl 源码的行尾注释是作者写给编译器的语义描述（lexer/parser 捕获，
存于 AST desc 字段）。collect_descriptions 汇总后按权限过滤注入 ctx，
prompt 层据此把裸 id 翻译为模型可理解的语义（编译器的"中转/翻译"职责）。
"""
from ..style.rules import resolve_style

MOTIF_ROLE_GUIDE = {
    "introduce": "首次登场：让该意象自然出现一次，建立印象，不解释含义",
    "recurrence": "重现：让该意象再次出现，与之前的印象呼应，仍不点破",
    "final": "收束：最后一次出现，承载情感落点，可稍明亮或沉重，仍禁止直接说破主题",
}


def motif_directives(ir):
    """本幕母题指令（M4）：motifs 声明 → 渲染指导行。"""
    return [{"motif": m["motif"], "role": m["role"],
             "instruction": MOTIF_ROLE_GUIDE.get(m["role"], ""),
             "desc": m.get("desc")}
            for m in ir.get("motifs", [])]


def collect_descriptions(program):
    """从 AST 汇总行尾注释语义。返回 dict：
    facts{id: desc} / informations{id: desc} / info_truth{id: truth_fact}
    / characters{name: desc} / events{"Actor.action": desc}
    / goals{"reveal:id"/"conceal:id": desc} / access{"subject.capability": desc}
    """
    d = {"facts": {}, "informations": {}, "info_truth": {}, "characters": {},
         "events": {}, "goals": {}, "access": {}, "locations": {}}
    if program.world:
        for f in program.world.facts:
            if f.desc:
                d["facts"][f.name] = f.desc
        for loc in program.world.locations:
            if loc.desc:
                d["locations"][loc.name] = loc.desc
    for c in program.characters:
        if c.desc:
            d["characters"][c.name] = c.desc
    for i in program.informations:
        if i.desc:
            d["informations"][i.name] = i.desc
        d["info_truth"][i.name] = i.truth
    for s in program.scenes:
        for r in s.events + s.information_changes:
            key = f"{r.actor}.{r.action}"
            if r.desc and key not in d["events"]:
                d["events"][key] = r.desc
        for g in s.dramatic_goal:
            key = f"{g.kind}:{g.target}"
            if g.desc and key not in d["goals"]:
                d["goals"][key] = g.desc
        for a in s.access:
            key = f"{a.subject}.{a.capability}"
            if a.desc and key not in d["access"]:
                d["access"][key] = a.desc
    return d


def _filter_descriptions(descriptions, scene, pov_knows):
    """权限过滤：描述与裸值同权——POV 看不到的事实，其描述同样不得进入上下文。"""
    if not descriptions:
        return {}
    known = set(pov_knows)
    out = {
        "facts": {k: v for k, v in descriptions.get("facts", {}).items()
                  if k in known},
        "informations": {},
        "characters": {k: v for k, v in descriptions.get("characters", {}).items()
                       if k in {p.name for p in scene.participants}},
        "events": dict(descriptions.get("events", {})),
        "goals": dict(descriptions.get("goals", {})),
        "access": dict(descriptions.get("access", {})),
        "locations": dict(descriptions.get("locations", {})),
    }
    info_truth = descriptions.get("info_truth", {})
    for info_id, desc in descriptions.get("informations", {}).items():
        truth = info_truth.get(info_id)
        # 信息对象描述仅当其真相锚点为 POV 已知事实，或该信息是本幕
        # reveal/conceal 目标（叙事指令必须携带语义）时才进入
        if truth is None or truth in known or _is_objective(scene, info_id):
            out["informations"][info_id] = desc
    return out


def _is_objective(scene, info_id):
    return any(g.target == info_id for g in scene.dramatic_goal)


def compile_render_context(state, scene, ir, style_name, descriptions=None,
                           style_decls=()):
    pov = scene.pov
    view = ir["pov_epistemic_view"]
    facts = state.world["facts"]

    known_facts = {p: facts[p] for p in view["knows_grounded"]}
    known_free = view["knows_free"]

    ctx = {
        "scene": {
            "title": ir["title"],
            "location": ir["framing"]["location"],
            "time": ir["framing"]["world_time"],
            "flashback": ir["framing"].get("flashback", False),
            "participants": ir["framing"]["participants"],
        },
        "pov": {
            "name": pov,
            "known_facts": known_facts,
            "known_free_propositions": known_free,
            "beliefs": {
                "grounded": view["believes_grounded"],
                "free": view["believes_free"],
            },
            "believes_about": view.get("believes_about", {}),
            "suspects": view.get("suspects", {}),
            "hides": view.get("hides", []),
            "intents": view["intends"],
            "personality": view["personality"],
            "emotion": view["emotion"],
            "emotional_arc": (view["arc"] or {}).get("states") if view["arc"] else None,
        },
        "others": {
            name: {
                "scene_actions": v["scene_actions"],
                "observable_arc": v["observable_arc"],
            }
            for name, v in ir["others_observable"].items()
        },
        "scene_events": ir["events"] + ir["information_changes"],
        "narrative_objectives": ir["narrative_objectives"],
        "forbidden": ir["presentation"]["denies"],
        "style": resolve_style(style_name, style_decls),
        "motif_directives": motif_directives(ir),
        "misdirect_notes": [{"target": d["target"], "desc": d["desc"]}
                            for d in ir.get("misdirects", [])],
    }
    # 语义描述（已按权限过滤；beliefs 中接地命题的真值 POV 已知，可带描述）
    if descriptions is not None:
        pov_knows = set(known_facts) | set(view["believes_grounded"])
        ctx["descriptions"] = _filter_descriptions(descriptions, scene, pov_knows)
    return ctx


def compile_actor_context(state, scene, ir, style_name, actor, descriptions=None,
                          style_decls=()):
    """LLM Actor 模式（M3 §2.6）：把某人物放进自己的 epistemic sandbox。

    该人物以自己的认知视图代替 POV 视图，其余权限过滤规则不变。
    脚本模式仍是唯一真值源：LLM 只产出行动提议（软约束 = dramatic_goal），
    提议经作者确认写回 .npl 后才进入确定性执行。
    """
    from ..ir.scene_ir import epistemic_view
    ir2 = dict(ir)
    ir2["pov_epistemic_view"] = epistemic_view(state, actor)
    ir2["framing"] = dict(ir["framing"], pov=actor)
    ir2["others_observable"] = {
        name: v for name, v in ir["others_observable"].items() if name != actor
    }
    ctx = compile_render_context(state, scene, ir2, style_name, descriptions,
                                 style_decls)
    ctx["actor_mode"] = {"character": actor, "sandbox": True}
    return ctx
