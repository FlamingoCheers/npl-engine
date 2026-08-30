"""深层嵌套认知接地验证（v0.3）。

canonical 链 'h1|v1>h2|v2>...>hn|vn>prop' 是某人物（owner 隐式，
不出现在链中）的一条建模：
    owner 认为 [h1 v1 [h2 v2 [...[hn vn prop]...]]]

运行时只保存这条链；各中间人物对"复合命题本身"的态度并未建模
（believes_about 只存对基础命题的一层态度）。因此接地验证采用
**基础命题近似**，对链上全部 h1..hn 逐层检查：
    hi 是否真的对【基础命题 prop】持有 vi 态度——
    knows → prop ∈ hi.knows；does_not_know → prop ∉ hi.knows；
    believes → prop ∈ hi.believes。

深度 2 的表达（两层建模）没有近似损失；深度 ≥3 的中间层为近似——
文档与输出均明示。纯函数，确定性，只在 inspect --deep 时启用。
"""

_VERBS = ("knows", "does_not_know", "believes")


def parse_canonical(canon):
    """'h1|v1>h2|v2>prop' -> ([(h1,v1),(h2,v2)], prop)；不合法返回 None。"""
    parts = canon.split(">")
    if len(parts) < 3:
        return None
    path = []
    for seg in parts[:-1]:
        if "|" not in seg:
            return None
        holder, verb = seg.split("|", 1)
        if verb not in _VERBS:
            return None
        path.append((holder, verb))
    return path, parts[-1]


def _holds(state, holder, verb, prop):
    """hi 对基础命题是否真的持有 vi 态度。None = 该人物无记录。"""
    cs = state.characters.get(holder)
    if cs is None:
        return None
    knows = prop in cs["knows"]
    if verb == "knows":
        return knows
    if verb == "does_not_know":
        return not knows
    return prop in cs["believes"]


def deep_grounding(state, canon):
    """对一条嵌套链逐层接地。

    返回 dict：
      prop      基础命题
      levels    [{holder, verb, claim, verdict, evidence}]（由内层向外层）
      verdict   "holds" | "broken:<holder>" | "unknown:<holder>"
    判定顺序：从最内层向外，第一个 violated/unknown 即为结论锚点，
    但 levels 始终完整给出每一层结果。
    """
    parsed = parse_canonical(canon)
    if parsed is None:
        return None
    path, prop = parsed
    levels = []
    verdict = "holds"
    # 从内层（路径末段）向外层（第 1 段）逐层检查（owner 隐式不在链中）
    for idx in range(len(path) - 1, -1, -1):
        holder, verb = path[idx]
        r = _holds(state, holder, verb, prop)
        if r is None:
            lv_verdict = "unknown"
            evidence = f"{holder} 无认知记录"
        else:
            lv_verdict = "holds" if r else "violated"
            cs = state.characters[holder]
            if verb == "knows":
                evidence = f"{prop} {'∈' if r else '∉'} {holder}.knows"
            elif verb == "does_not_know":
                evidence = f"{prop} {'∉' if r else '∈'} {holder}.knows"
            else:
                evidence = f"{prop} {'∈' if r else '∉'} {holder}.believes"
        levels.append({
            "holder": holder,
            "verb": verb,
            "claim": f"{holder}.{verb}({prop})（基础命题近似）",
            "verdict": lv_verdict,
            "evidence": evidence,
        })
        if lv_verdict != "holds" and verdict == "holds":
            verdict = ("unknown" if lv_verdict == "unknown" else "broken") \
                + f":{holder}"
    return {"prop": prop, "levels": levels, "verdict": verdict}
