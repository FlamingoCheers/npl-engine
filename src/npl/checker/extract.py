"""LLM 命题抽取：把散文还原为可与认知状态对照的命题结构。

抽取与判定分离（项目规划 §9 风险对策）：抽取可换模型（extract 适配器），
规则引擎确定性判定。抽取 prompt 版本化：EXTRACT_PROMPT_VERSION。
"""
import hashlib
import json
import re
from pathlib import Path

EXTRACT_PROMPT_VERSION = "v8"

_SYSTEM = f"""你是一个叙事文本命题抽取器（{EXTRACT_PROMPT_VERSION}）。你的唯一任务：把给定的小说片段还原为结构化命题，供下游规则引擎与角色认知状态比对。你不评价文本好坏，只做忠实抽取。宁可多记待规则引擎甄别，不要漏记。

输出要求：只输出一个 JSON 对象，不要 markdown 代码块，不要解释。所有列表合计不超过 20 条，同一片段只记一次，严禁重复输出。字段全部必给（没有就给空数组/空对象）：
{{
  "fact_assertions": [{{"fact": "<事实id>", "asserted": "true|false|uncertain", "asserted_by": "<人物名或narration>", "span": "原文片段"}}],
  "omniscient_spans": [{{"span": "片段", "why": "为何属于全知旁白"}}],
  "inner_mind_spans": [{{"character": "<人物名>", "span": "片段"}}],
  "knowledge_claims": [{{"character": "<人物名>", "claims_to_know": "<事实id>", "span": "片段"}}],
  "concealed_evidence_spans": [{{"fact": "<事实id>", "span": "片段"}}],
  "reveal_achieved": {{"fact": "<reveal目标id>", "achieved": true, "span": "支撑片段"}},
  "emotions_named": [{{"subject": "<人物名>", "emotion": "<情绪词>", "span": "片段"}}],
  "motif_mentions": [{{"motif": "<母题id>", "span": "片段"}}]
}}

判定口径（逐条细读）：
- fact_assertions：叙述或对话把某事实当真/假陈述出来就记（含"她什么都不知道"= 断言 lin_knows_nothing 类）。asserted_by 填作出该断言的人物（台词归说话者；"他知道X"式归被陈述者；纯叙述归 narration）。把文中指称映射到事实清单 id：合同复印件→lin_has_seen_contract_copy 这类同义映射必须做，不能只做字面匹配。仅存疑猜测记 uncertain。
- omniscient_spans：仅限叙述者披露"POV 当时无法感知"的信息："X不知道的是……"、"而在他看不见的地方……"、直接交代 POV 之外的秘密内容、无感知来源的确凿背景陈述、**直接断言他人看见/注意到/察觉了什么**（"他看见桌上的纸""他注意到她的表情"——POV 无法确知他人的知觉内容，只能写"他的目光落在桌上"这类可观察的视线方向）。**以下都绝不算全知**：①POV 在场看到/听到的他人外部动作、神态、台词——台词内容本身（哪怕是谎言）是 POV 可感知的，不得因"台词是谎话"而记全知；②日期、时间、天气等 POV 理应知道的常识；③POV 自己的回忆与数日子（"她想起……"是 POV 的记忆，永远合法）；④可观察的视线方向（"他看着那张纸""目光落在""视线扫过"）；⑤POV 可见的他人生理细节（"眼睛里有血丝""眼睑浮肿""手上有茧"）；⑥"像是/仿佛/好像"式猜测性解读。只有叙述直接披露 POV 不在场的实况或他人未表露的内心，才记。
- inner_mind_spans：仅限**无推测标记的直接断言**非 POV 人物的想法/动机/情绪（"他心里涌起愧疚""他告诉自己……"）。**"像是/仿佛/好像/似乎"式猜测性解读不算**——那是 POV 自己的猜测（限制视角的合法笔法，甚至是其特征），不是叙述进入他人内心。"语气温和""动作很快""肩膀塌着"等纯外部观察也不算。
- knowledge_claims：仅当角色言语/行为中出现"只有知情者才会有的具体内容"——说出事实细节、出示实证、点破、对特定事实求证（"你是怎么拿到X的？"）——才记 claims_to_know=X。角色的普通在场动作（坐下、烧东西、收拾、沉默）**不算**对任何事实的认知宣称，严禁从纯动作反推"他知道某事"。claims_to_know 必须映射到事实清单 id。
- fact_assertions 的映射纪律：只把文中**对某事实内容的直接陈述**（台词或叙述断言）映射到事实 id，严禁把人物的行为泛化映射到无关事实（"她没有告诉任何人"≠"X 什么都不知道"这类人物行为陈述不得映射到认知类事实 id）。映射必须基于完整句的语义，禁止拿无关短语硬套事实 id；对应不上就别记。
- concealed_evidence_spans：文中呈现了 conceal 清单事实的实物实证（持有、出示、取出文件等），或叙述直接确认角色握有该实证。**映射纪律**：证据必须映射到它语义对应的事实（合同复印件/印字的纸页 → lin_has_seen_contract_copy 这类文件型事实），严禁因某事实在 conceal 清单里就把证据挂错——meta_knowledge 是"谁知道谁知道某事"的元认知事实，任何实物都不可能是它的实证；财务/抵押类事实的实证是账本、数字、印章、银行单据，不是合同复印件。
- reveal_achieved：读者能否从可观察细节感知 reveal 目标（POV 已知情这件事是否透出来）。fact 必须填 reveal 目标 id，绝不能为空。
- emotions_named：仅限**叙述**直接说出情绪名词的片段（"她很悲伤""涌起一股不安""他感到恐惧"式）。**角色台词引语内的情绪词不算**（"别担心""我很难过"是台词内容，不是叙述命名情绪）。**身体感受与生理反应（喉咙紧、手凉、胃里发沉、眼眶热、茶水苦涩、呼吸一滞）一律不算**，哪怕它们暗示情绪。内心情绪名词陈述同时记 inner_mind_spans（若主体非 POV）。
- motif_mentions：母题清单中列出的意象（及其近义形态）在文中出现的片段就记（"茶杯/茶具/茶水"→ 茶杯 这类近义映射必须做）。**身体化的情绪载体（"喉咙紧"）不算母题**，只算真实存在的意象物。"""


def _paren_desc(d):
    return f"（{d}）" if d else ""


def build_facts_brief(state, scene):
    """给抽取器的 grounding 简报：事实 × POV 认知状态 + conceal/reveal。"""
    pov = scene.pov
    facts = state.world["facts"]
    pov_knows = state.characters[pov]["knows"]
    pov_believes = state.characters[pov]["believes"]
    brief = {"pov": pov,
             "participants": [p.name for p in scene.participants],
             "facts": {}, "conceal": sorted(state.narrative["conceal_active"]),
             "reveal": scene_reveals(scene),
             "motifs": [{"motif": m.motif, "role": m.role, "desc": m.desc}
                        for m in scene.motifs]}
    for fid, val in facts.items():
        if fid in pov_knows:
            brief["facts"][fid] = f"known_to_pov={str(val).lower()}"
        elif fid in pov_believes:
            brief["facts"][fid] = "believed_by_pov"
        else:
            brief["facts"][fid] = "unknown_to_pov"
    return brief


def scene_reveals(scene):
    return [g.target for g in scene.dramatic_goal if g.kind == "reveal"]


def extract_propositions(adapter, prose, state, scene, passes=2, cache_dir=None):
    """调用 extract 适配器（默认双次取并集，对冲单次抽取的不稳定）；返回 dict。

    cache_dir 给定时按 (prompt 版本 + facts_brief + prose) 哈希缓存结果，
    迭代判定口径时只有变化的幕需要重抽。
    """
    brief = build_facts_brief(state, scene)
    user = (f"【POV】{brief['pov']}\n"
            f"【在场人物】{'、'.join(brief['participants'])}\n"
            f"【事实清单（id: POV认知状态）】\n"
            + "\n".join(f"  {k}: {v}" for k, v in sorted(brief["facts"].items()))
            + f"\n【conceal 清单（不应呈现其实证）】{'、'.join(brief['conceal']) or '无'}"
            f"\n【reveal 清单（读者应可感知）】{'、'.join(brief['reveal']) or '无'}"
            + (f"\n【母题清单】\n" + "\n".join(
                f"  {m['motif']}（{m['role']}）{_paren_desc(m['desc'])}"
                for m in brief["motifs"]) if brief["motifs"] else "")
            + f"\n\n【待抽取文本】\n{prose}")
    cache_path = None
    if cache_dir:
        key = hashlib.sha1(
            f"{EXTRACT_PROMPT_VERSION}\0{_SYSTEM}\0{user}".encode("utf-8")).hexdigest()
        cache_path = Path(cache_dir) / f"{key}.json"
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    merged = None
    last_err = None
    for _ in range(max(1, passes)):
        raw = adapter.chat(_SYSTEM, user, temperature=0.0) \
            if hasattr(adapter, "chat") else None
        try:
            data = parse_extraction(raw)
        except ValueError as e:
            last_err = e
            _dump_debug(raw)  # 病态输出落盘，便于诊断
            continue
        merged = data if merged is None else _merge(merged, data)
    if merged is None:
        raise last_err
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(merged, ensure_ascii=False,
                                             indent=1), encoding="utf-8")
        except OSError:
            pass
    return merged


def _dump_debug(raw):
    try:
        from pathlib import Path
        p = Path(__file__).resolve().parents[3] / "build" \
            / "extract_debug.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(raw or "", encoding="utf-8")
    except OSError:
        pass


def _merge(a, b):
    """并集合并：列表字段拼接去重；reveal_achieved 任一次未达成即视为未达成。"""
    out = {}
    for k in ("fact_assertions", "omniscient_spans", "inner_mind_spans",
              "knowledge_claims", "concealed_evidence_spans", "emotions_named"):
        seen, items = set(), []
        for item in a.get(k, []) + b.get(k, []):
            key = (str(item.get("span", ""))[:60], str(item.get("fact",
                      item.get("claims_to_know", item.get("emotion", "")))))
            if key not in seen:
                seen.add(key)
                items.append(item)
        out[k] = items
    ra, rb = a.get("reveal_achieved") or {}, b.get("reveal_achieved") or {}
    out["reveal_achieved"] = {
        "fact": ra.get("fact") or rb.get("fact") or "",
        "achieved": bool(ra.get("achieved", True)) and bool(rb.get("achieved", True)),
        "span": ra.get("span") or rb.get("span") or "",
    }
    return out


def parse_extraction(raw):
    if raw is None:
        raise ValueError("适配器无 chat 接口")
    text = raw.strip()
    m = re.search(r"\{.*\}", text, re.S)  # 剥离可能的 markdown 围栏/杂讯
    if not m:
        raise ValueError(f"抽取输出中无 JSON 对象: {text[:120]!r}")
    try:
        return _normalize(json.loads(m.group(0)))
    except json.JSONDecodeError:
        pass
    salvaged = _salvage_json(m.group(0))
    if salvaged is not None:
        return _normalize(salvaged)
    try:
        json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"抽取输出 JSON 解析失败: {e}: {text[:120]!r}") from e


_LIST_KEYS = ("fact_assertions", "omniscient_spans", "inner_mind_spans",
              "knowledge_claims", "concealed_evidence_spans", "emotions_named",
              "motif_mentions")


def _normalize(data):
    """LLM 输出形状防御：reveal_achieved 可能是数组，列表项可能是字符串。"""
    if not isinstance(data, dict):
        raise ValueError(f"抽取输出顶层不是对象: {str(data)[:120]!r}")
    out = {}
    for k in _LIST_KEYS:
        items = data.get(k) or []
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            items = []
        out[k] = [it for it in items if isinstance(it, dict)]
    ra = data.get("reveal_achieved") or {}
    if isinstance(ra, list):
        ra = next((it for it in ra if isinstance(it, dict)), {})
    if not isinstance(ra, dict):
        ra = {}
    out["reveal_achieved"] = {
        "fact": ra.get("fact") if isinstance(ra.get("fact"), str) else "",
        "achieved": bool(ra.get("achieved", True)),
        "span": ra.get("span") if isinstance(ra.get("span"), str) else "",
    }
    return out


def _salvage_json(text):
    """截断/复读退化的 JSON 尽力抢救：截到最后一个完整值边界并补齐闭合。

    glm-4-flash 长文本抽取会进入复读循环，输出被 max_tokens 掐断，
    顶层对象永不闭合。此函数保留已完整生成的条目（重复条目由
    _merge 去重），其余丢弃；无法抢救返回 None。
    """
    stack = []
    in_str = esc = False
    candidates = []  # (cut_end, closers) —— 每个完整值边界
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            if not stack:
                return None  # 多余闭合 → 非截断，放弃
            top = stack.pop()
            if (ch == "]") != (top == "["):
                return None  # 括号类型错乱 → 非单纯截断
            closers = [("]" if o == "[" else "}") for o in reversed(stack)]
            candidates.append((i + 1, closers))
            if not stack:
                break  # 顶层已完整闭合，其后皆垃圾
    if not stack or not candidates:
        return None
    cut_end, closers = candidates[-1]
    cut = text[:cut_end] + "".join(closers)
    try:
        return json.loads(cut)
    except json.JSONDecodeError:
        return None
    return out
