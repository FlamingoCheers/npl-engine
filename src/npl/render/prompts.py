"""渲染提示词：把 Context 编译为 system / user 指令。

两层职责：
1. 语义翻译：ctx["descriptions"] 把裸 id 翻译成模型可理解的语义
   （编译器的"中转"职责——模型不是猜测 id 含义，而是收到作者的原始意图）。
2. 铁律约束：权限式渲染在提示层的第二道防线（第一道是 Context 物理隔离）。
"""


def _bool(v):
    return "true" if v else "false"


def _with_desc(text, descriptions, section, key=None):
    """查描述表，返回 `text（desc）` 或原 text。"""
    d = (descriptions or {}).get(section, {})
    desc = d.get(key or text)
    return f"{text}（{desc}）" if desc else text


def _paren(d):
    return f"（{d}）" if d else ""


def build_system_prompt(ctx, style):
    pov = ctx["pov"]["name"]
    others = "、".join(ctx["others"].keys()) or "无"
    desc = ctx.get("descriptions") or {}
    goals = desc.get("goals", {})
    infos = desc.get("informations", {})
    facts = desc.get("facts", {})

    def objective_line(kind, targets):
        if not targets:
            return None
        parts = []
        for t in targets:
            d = infos.get(t) or facts.get(t)
            g = goals.get(f"{kind}:{t}")
            if g and g != d:
                d = f"{d}（作者意图：{g}）" if d else g
            parts.append(f"「{t}」—— {d}" if d else f"「{t}」")
        return "；".join(parts)

    reveal_line = objective_line("reveal", ctx["narrative_objectives"]["reveal"])
    conceal_line = objective_line("conceal", ctx["narrative_objectives"]["conceal"])

    obj_parts = []
    if reveal_line:
        obj_parts.append(
            f"揭示（间接达成——通过可观察细节让读者隐约感知，禁止直说）：{reveal_line}")
    if conceal_line:
        obj_parts.append(
            f"隐藏（绝不打破——任何人物不得说破、承认、指涉其证据本身；"
            f"也不得通过暗示让读者推断出证据的存在，例如提到 POV 曾见过某个名字、"
            f"某份文件或某个物件；与该秘密相关的单据、文件、银行回执、字据、合同等"
            f"实物意象一律不得作为环境细节出现；宁可少写，不可说破，不可暗示）：{conceal_line}")
    objective_text = "\n   ".join(obj_parts) if obj_parts else "无"

    rules = "\n".join(f"   {i}. {r}" for i, r in enumerate(style["rules"], 1))
    flashback_note = ""
    if ctx["scene"].get("flashback"):
        flashback_note = """

本幕是倒叙闪回：以回忆的笔法呈现（时间、光线、记忆质感可作标记），
但信息边界不变——只能使用本上下文提供的信息（即使其中部分在故事当前
时间线早已是旧闻，也不得引入上下文之外的"后见之明"）。"""
    return f"""你是一位小说渲染器：把结构化叙事中间表示（Scene IR）渲染为中文小说散文。
你不是自由创作者，而是一台受严格约束的渲染机器。你只能使用下方提供的信息，不得虚构超出边界的设定。

铁律（违反任何一条即渲染失败）：
1. 视角与人称：本场景 POV 是「{pov}」。全部叙述只能来自 {pov} 的感知、记忆与推断；必须使用第三人称限制视角，禁止第一人称叙述（正文不得出现以"我"为叙述者的段落）。
2. 禁止全知旁白：不得以任何形式陈述 {pov} 不可能知道的信息；不得出现"TA不知道的是……"式句子。
3. 禁止进入他人内心：{others} 只能通过可观察的外部表现（动作、语气、微表情、停顿、视线、身体姿态）呈现；禁止直接陈述他们的想法、动机或情绪名称。
4. 信息边界：只能使用【POV 内部状态】中列出的事实与信念；世界其余真相对你不存在——你不知道，因此不能写，也不能让角色说出来。
5. 叙事目标：
   {objective_text}
6. 情绪呈现：POV 的情绪只能通过身体感受、动作与感官细节透出，禁止直接命名情绪。
7. 冲突裁决：任何两条要求冲突时，信息边界（铁律 2/3/4）优先于一切文学效果与节拍完整性；宁可省略某个节拍，不可越界。

风格（{style['name']}）：{style['description']}
{rules}

输出要求：800–1500 字中文散文；直接输出正文，不要标题、解释或任何元信息。{flashback_note}"""


def build_user_prompt(ctx):
    s = ctx["scene"]
    pov = ctx["pov"]
    desc = ctx.get("descriptions") or {}
    lines = []
    lines.append(f"【场景】{s['title']}")
    loc_desc = desc.get("locations", {}).get(s["location"])
    flashback_mark = "（倒叙闪回：以回忆笔法呈现）" if s.get("flashback") else ""
    lines.append(f"【地点】{s['location']}{_paren(loc_desc)}　【时间】{s['time']}{flashback_mark}")
    lines.append(f"【在场人物】{'、'.join(s['participants'])}")
    # 人物身份语义（作者在 .npl 中以行尾注释声明）
    char_descs = desc.get("characters", {})
    if char_descs:
        who = "；".join(f"{k}：{v}" for k, v in char_descs.items())
        lines.append(f"【人物身份】{who}")
    lines.append(f"【POV 内部状态｜{pov['name']}】")
    fact_descs = desc.get("facts", {})
    for k, v in pov["known_facts"].items():
        lines.append(f"  已知事实: {k} = {_bool(v)}{_paren(fact_descs.get(k))}")
    for p in pov["known_free_propositions"]:
        lines.append(f"  已知(自由命题): {p}")
    for k, v in pov["beliefs"]["grounded"].items():
        lines.append(f"  信念: {k} = {_bool(v)}{_paren(fact_descs.get(k))}")
    for p in pov["beliefs"]["free"]:
        lines.append(f"  信念(自由命题): {p}")
    verb_cn = {"knows": "知道", "does_not_know": "不知道", "believes": "相信"}
    for holder, bucket in pov.get("believes_about", {}).items():
        for verb, props in bucket.items():
            for p in props:
                lines.append(f"  对他人认知的建模: 你相信 {holder} {verb_cn.get(verb, verb)} {p}")
    for k, v in pov.get("suspects", {}).items():
        lines.append(f"  怀疑: {k}（置信度 {v}，只是怀疑，未证实——不得当作事实书写）")
    for p in pov.get("hides", []):
        lines.append(f"  正在隐藏: {p}（行为上掩饰，不得让其他人物察觉实情）")
    for p in pov["intents"]:
        lines.append(f"  意图: {p}")
    att_cn = {"trust": "信任", "distrust": "不信任", "affection": "亲近",
              "resentment": "怨怼", "wariness": "戒备", "guilt": "愧疚",
              "attachment": "依恋"}
    for target, atts in pov.get("relations", {}).items():
        for att, v in atts.items():
            reason = pov.get("relation_reasons", {}).get(target, {}).get(att)
            lines.append(f"  对 {target} 的态度: {att_cn.get(att, att)}={v}"
                         f"（影响语气与行为细节；严禁在叙述中直接出现数值或'态度'字样）"
                         + (f"（缘由：{reason}）" if reason else ""))
    pers = "，".join(f"{k}={v}" for k, v in pov["personality"].items())
    emo = "，".join(f"{k}={v}" for k, v in pov["emotion"].items())
    arc = " -> ".join(pov["emotional_arc"] or [])
    if pers:
        lines.append(f"  性格: {pers}")
    if emo:
        lines.append(f"  情绪(起点): {emo}")
    if arc:
        lines.append(f"  情绪轨迹: {arc}")
    lines.append("【叙事节拍（按顺序发生）】")
    event_descs = desc.get("events", {})
    for e in ctx["scene_events"]:
        args = f"({'、'.join(e['args'])})" if e["args"] else ""
        key = f"{e['actor']}.{e['action']}"
        lines.append(f"  {key}{args}{_paren(event_descs.get(key))}")
    for name, o in ctx["others"].items():
        acts = "、".join(o["scene_actions"]) or "无"
        arc2 = " -> ".join(o["observable_arc"])
        hint = f"；外部表现轨迹: {arc2}" if arc2 else ""
        lines.append(f"【非POV人物｜{name}】场景内行为: {acts}{hint}（只能通过可观察行为呈现）")
    if ctx.get("motif_directives"):
        lines.append("【母题指令】（写作时自然融入，禁止点破含义）")
        for m in ctx["motif_directives"]:
            d = _paren(m.get("desc"))
            lines.append(f"  {m['motif']}（{m['role']}）: {m['instruction']}{d}")
    if ctx.get("misdirect_notes"):
        lines.append("【误导提示】（可微妙引导读者怀疑；实为假象，不得明写）")
        for m in ctx["misdirect_notes"]:
            lines.append(f"  可引导读者怀疑: {m['target']}{_paren(m.get('desc'))}")
    if ctx["forbidden"]:
        forb = "、".join(_with_desc(f, desc, "access") for f in ctx["forbidden"])
        lines.append(f"【明确禁止】{forb}")
    return "\n".join(lines)


def build_actor_prompt(ctx):
    """LLM Actor 模式（M3 §2.6）：epistemic sandbox 内的角色行动提议。

    返回 (system, user)。脚本模式仍是唯一真值源：提议仅供作者挑选写回 .npl。
    """
    actor = ctx["actor_mode"]["character"]
    goals = ctx["narrative_objectives"]
    system = f"""你是小说角色「{actor}」的行动决策器。角色身处 epistemic sandbox 中：
你只能使用【POV 内部状态】里列出的信息（那就是 {actor} 知道的一切），
其余世界真相对 {actor}（也对你）不存在——不知道的信息不能出现在任何提议里。

输出一个 JSON 数组（直接输出，不要任何解释或代码块标记），每项形如：
{{"action": "动词", "args": ["命题id"], "reason": "一句话动机"}}
提出 3-5 条 {actor} 在本场景中可能采取的行动提议，要求：
1. 只能引用上下文中列出的已知事实/信念/怀疑/意图的 id；
2. 叙事意图（软约束）：reveal 目标 {goals.get('reveal') or '无'} —— 设计能让读者可感知的行动；
   conceal 目标 {goals.get('conceal') or '无'} —— 设计掩饰性行动，绝不主动提及该信息；
3. 行动须符合性格与情绪轨迹，并贴合当前场景的时间/地点/在场人物。
动词建议：asks/tells/hides/observes/leaves/confronts/avoids/realizes 等自然动作。"""
    return system, build_user_prompt(ctx)
