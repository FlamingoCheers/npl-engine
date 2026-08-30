"""规则引擎：命题抽取结果 × 认知状态 → 带错误码的检查结论。

错误码（项目规划 附录 A，M2/M4 实现）：
  NAR-021 ERROR  Epistemic leakage：POV 叙述泄露权限外信息
                 （全知旁白 / 他人内心 / 断言 POV 不知道的世界事实）
  NAR-022 ERROR  角色全知：角色表现出其认知状态中不存在的信息
  NAR-031 ERROR  Conceal violation：违反 dramatic_goal 的 conceal 声明
  NAR-032 WARN   Reveal 未达成：reveal 目标未被读者可得地呈现
  NAR-051 WARN   风格违规：直接命名情绪（M4 扩展为完整 NAR-05x 家族）
  NAR-052 WARN   风格违规：超长句占比过高（style.sentence_max）
  NAR-061/2/3    母题结构错误（validator 前端检查）
  NAR-064 WARN   母题缺呈现：场景声明的母题未在散文中出现
  NAR-065 WARN   伏笔无回收：foreshadow 之后没有任何揭示承接
  NAR-066 WARN   Withhold 未按期释放：到期时读者仍不知道该事实
  NAR-067 WARN   Misdirect 缺陷：误导目标为真事实，或后续无反转揭示
"""
from dataclasses import dataclass, field
import re

from .lexicon import scan_emotions
from ..runtime.executor import CONFIRM_VERBS, REVEAL_VERBS


@dataclass
class CheckFinding:
    code: str
    severity: str          # "error" / "warning"
    message: str
    span: str = ""
    detail: dict = field(default_factory=dict)


def _fact_is_claimed_ground(claim):
    """claims_to_know 可能是 fact id，也可能是自由描述；只有能接地的才可判定。"""
    return claim if isinstance(claim, str) else None


def run_checks(extraction, state, scene, ir, style, prose="", scene_idx=None,
               program=None):
    """对单个场景的抽取结果执行规则检查。

    extraction: checker.extract 产出的 dict（或手工构造，供测试）
    state:      该幕结束时的 RuntimeState
    style:      ctx["style"]（其 rules 声明是否禁止命名情绪、句长上限等）
    scene_idx:  本幕序号（0-based）——NAR-065/066/067 需要
    program:    完整程序 AST——NAR-065/066/067 需要
    """
    pov = scene.pov
    facts = state.world["facts"]
    pov_knows = state.characters[pov]["knows"]
    conceal_active = set(state.narrative["conceal_active"])
    findings = []
    conceal_spans_seen = set()

    # NAR-021a：叙述断言 POV 不知道的世界事实（断言者是 narration 或 POV 本人）。
    # 放行 POV 的 believes/suspects——限制性第三人称允许 POV 把自身信念
    # 叙述为事实（"他知道婚姻已经完了"是信念，不是全知）。
    pov_believes = state.characters[pov]["believes"] | \
        set(state.characters[pov]["suspects"])
    for fa in extraction.get("fact_assertions", []):
        fid = fa.get("fact", "")
        if fid not in facts or fa.get("asserted") not in ("true", "false"):
            continue
        by = fa.get("asserted_by", "narration") or "narration"
        if by in (pov, "narration", "POV") and fid not in pov_knows \
                and fid not in pov_believes:
            # 戏剧反讽锚定事实豁免：叙述/POV 断言某信念锚定事实的世界真值
            # （如 lin_knows_nothing = false，即"她并非一无所知"），是 reveal
            # meta_knowledge 的合法机制——读者得知"相信者错了"。若该断言
            # 破坏 conceal，由 NAR-031 单独判定，不在此重复计漏。
            asserted_val = fa.get("asserted") == "true"
            is_belief_anchor = any(
                fid in state.characters[c]["believes"]
                for c in state.characters if c != pov)
            if is_belief_anchor and asserted_val == facts[fid]:
                continue
            findings.append(CheckFinding(
                "NAR-021", "error",
                f"POV 叙述断言了权限外事实 '{fid}'（POV {pov} 不知道该事实）",
                span=fa.get("span", "")))

    # NAR-021b：全知旁白
    for om in extraction.get("omniscient_spans", []):
        findings.append(CheckFinding(
            "NAR-021", "error", "全知旁白：叙述披露了 POV 视角外的信息",
            span=om.get("span", ""), detail={"why": om.get("why", "")}))

    # NAR-021c：进入他人内心
    for im in extraction.get("inner_mind_spans", []):
        if im.get("character") != pov:
            findings.append(CheckFinding(
                "NAR-021", "error",
                f"叙述进入了 {im.get('character', '?')} 的内心（deny = "
                f"{im.get('character', '?')}.private_thought）",
                span=im.get("span", "")))

    # NAR-022a：角色全知——knowledge_claims 路径（claims 可接地的才判定）
    for kc in extraction.get("knowledge_claims", []):
        char = kc.get("character", "")
        if char not in state.characters or char == pov:
            continue
        claim = _fact_is_claimed_ground(kc.get("claims_to_know"))
        cs = state.characters[char]
        # hides 豁免：隐藏者本人必然知道所隐藏之事
        if claim and claim in facts and \
                claim not in cs["knows"] | cs["believes"] | cs["hides"]:
            findings.append(CheckFinding(
                "NAR-022", "error",
                f"角色全知：{char} 表现出知道 '{claim}'，"
                f"但其认知状态中不存在该信息",
                span=kc.get("span", "")))

    # NAR-022b：角色全知——对话断言路径（非 POV 人物断言其认知外事实）
    for fa in extraction.get("fact_assertions", []):
        fid = fa.get("fact", "")
        by = fa.get("asserted_by", "")
        if not by or by in (pov, "narration", "POV"):
            continue
        if by not in state.characters or fid not in facts:
            continue
        if fa.get("asserted") != "true":
            continue
        cs = state.characters[by]
        if fid not in cs["knows"] | cs["believes"] | cs["hides"]:
            findings.append(CheckFinding(
                "NAR-022", "error",
                f"角色全知：{by} 在言行中表现出知道 '{fid}'，"
                f"但其认知状态中不存在该信息",
                span=fa.get("span", "")))

    # NAR-031：conceal 违规（双路：显式实证呈现 + 对隐藏事实的真断言）。
    # 严格语义：conceal 事实一旦在 prose 中被断言为真（含持有实证），
    # 读者即确定，conceal 即破——无论断言者是谁。
    for ce in extraction.get("concealed_evidence_spans", []):
        fid = ce.get("fact", "")
        if fid in conceal_active and ce.get("span") not in conceal_spans_seen:
            conceal_spans_seen.add(ce.get("span"))
            findings.append(CheckFinding(
                "NAR-031", "error",
                f"Conceal violation：prose 直接呈现了应隐藏的事实 '{fid}' "
                f"的实证", span=ce.get("span", "")))
    for fa in extraction.get("fact_assertions", []):
        fid = fa.get("fact", "")
        if fid in conceal_active and fa.get("asserted") == "true" and \
                fa.get("span") not in conceal_spans_seen:
            conceal_spans_seen.add(fa.get("span"))
            findings.append(CheckFinding(
                "NAR-031", "error",
                f"Conceal violation：prose 断言了应向读者隐藏的事实 '{fid}'，"
                f"读者对其的实证有无不再不确定",
                span=fa.get("span", "")))

    # NAR-032：reveal 未达成（fact 为空的抽取噪声不判）
    ra = extraction.get("reveal_achieved")
    if ra and ra.get("achieved") is False and ra.get("fact"):
        findings.append(CheckFinding(
            "NAR-032", "warning",
            f"Reveal 未达成：reveal 目标 '{ra.get('fact', '?')}' "
            f"未被读者可得地呈现", span=ra.get("span", "")))

    # NAR-051：直接命名情绪（风格声明禁止时）—— LLM 抽取 ∪ 词表兜底
    forbids_naming = any("命名情绪" in r or "情绪" in r and "禁止" in r
                         for r in style.get("rules", []))
    if forbids_naming:
        emotions = list(extraction.get("emotions_named", []))
        seen_spans = {(e.get("emotion"), e.get("span")) for e in emotions}
        for hit in scan_emotions(prose):
            if (hit["emotion"], hit["span"]) not in seen_spans:
                emotions.append(hit)
        span_seen = set()
        for e in emotions:
            if e.get("span") in span_seen:
                continue  # 同一片段多个情绪词只报一次
            span_seen.add(e.get("span"))
            findings.append(CheckFinding(
                "NAR-051", "warning",
                f"风格违规：直接命名情绪'{e.get('emotion', '?')}'"
                f"（应通过动作与感官细节呈现）",
                span=e.get("span", "")))

    # NAR-052：超长句占比（style.sentence_max 声明时才判）
    smax = (style.get("constraints") or {}).get("sentence_max")
    if smax and prose:
        sentences = [s for s in re.split(r"[。！？]+", prose) if s.strip()]
        long_ones = [s for s in sentences if len(s.strip()) > smax]
        if sentences and len(long_ones) / len(sentences) > 0.3:
            worst = max(long_ones, key=len)
            findings.append(CheckFinding(
                "NAR-052", "warning",
                f"风格违规：超长句（>{smax} 字）占比 "
                f"{len(long_ones)}/{len(sentences)} 超过 30%",
                span=worst.strip()))

    # NAR-064：母题缺呈现——场景声明的母题在散文中无对应提及。
    # v0.2 离线回退：人工抽取无 motif_mentions 时，母题 id 字面出现也算呈现。
    mentioned = {m.get("motif") for m in extraction.get("motif_mentions", [])}
    for m in scene.motifs:
        if m.motif not in mentioned and m.motif not in prose:
            findings.append(CheckFinding(
                "NAR-064", "warning",
                f"母题缺呈现：场景声明的母题 '{m.motif}'（{m.role}）"
                f"未在散文中出现",
                span="", detail={"motif": m.motif, "role": m.role}))

    # NAR-065/066/067：需要 program 与 scene_idx 的结构化检查
    if program is not None and scene_idx is not None:
        findings.extend(_structural_checks(extraction, state, scene,
                                           program, scene_idx))

    # Span 原文验证：抽取器给出的片段必须是散文原文（防幻觉片段）。
    # 归一化后比对；短于 6 字的片段无法可靠验证，保留。
    if prose:
        norm = _norm_text(prose)
        verified = []
        for f in findings:
            s = _norm_text(f.span)
            if len(s) < 6 or s in norm:
                verified.append(f)
        findings = verified

    # 双次抽取取并集后按 (code, span) 去重——同一违规只报一次
    deduped, seen = [], set()
    for f in findings:
        key = (f.code, f.span)
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


def _structural_checks(extraction, state, scene, program, scene_idx):
    """需要整章结构信息的检查：伏笔回收 / withhold 到期 / misdirect 反转。"""
    findings = []

    # NAR-065：伏笔无回收——声明后无任何揭示（dramatic_goal 或
    # information_changes 的确认/揭示）承接该目标
    def later_payoff(target, from_idx):
        for gidx in range(from_idx + 1, len(program.scenes)):
            g = program.scenes[gidx]
            if any(gi.kind == "reveal" and gi.target == target
                   for gi in g.dramatic_goal):
                return True
            for ref in g.information_changes:
                if ref.action in CONFIRM_VERBS | REVEAL_VERBS and \
                        any(a == target or a.endswith(f"({target})")
                            for a in ref.args):
                    return True
        return False

    for f in scene.foreshadows:
        if not later_payoff(f.target, scene_idx):
            findings.append(CheckFinding(
                "NAR-065", "warning",
                f"伏笔无回收：第 {scene_idx + 1} 幕埋设的伏笔 '{f.target}' "
                f"在后续场景中没有任何揭示承接",
                span="", detail={"target": f.target}))

    # NAR-066：withhold 到期未释放——until 幕结束时读者仍不知道该事实。
    # withhold 语义 = 声明幕即对读者隐藏（进 conceal_active），
    # until 幕开始时释放（executor），之后应有揭示让读者得知。
    reader_knows = set(state.narrative["reader_knows"])
    pov_knows = state.characters[scene.pov]["knows"]
    for s in program.scenes:
        for w in s.withholds:
            if w.until == scene_idx + 1 and \
                    w.target not in reader_knows and \
                    w.target not in pov_knows:
                findings.append(CheckFinding(
                    "NAR-066", "warning",
                    f"Withhold 未按期释放：'{w.target}' 声明于第 "
                    f"{w.until + 1} 幕释放，但该幕结束时读者仍不知道它",
                    span="", detail={"target": w.target, "until": w.until}))

    # NAR-067：misdirect 缺陷——目标为真事实（误导即真话，无意义）
    # 或后续没有任何 reveal 反转
    facts = state.world["facts"]
    for m in scene.misdirects:
        if m.target in facts and facts[m.target] is True:
            findings.append(CheckFinding(
                "NAR-067", "warning",
                f"误导缺陷：misdirect 目标 '{m.target}' 在世界中为真，"
                f"误导读者相信真相不构成误导",
                span="", detail={"target": m.target}))
        has_reversal = any(
            gi.kind == "reveal"
            for gidx in range(scene_idx + 1, len(program.scenes))
            for gi in program.scenes[gidx].dramatic_goal)
        if not has_reversal:
            findings.append(CheckFinding(
                "NAR-067", "warning",
                f"误导缺陷：第 {scene_idx + 1} 幕的误导 '{m.target}' "
                f"之后没有任何 reveal 场景承载反转",
                span="", detail={"target": m.target}))
    return findings


def _norm_text(t):
    return "".join(ch for ch in (t or "")
                   if not ch.isspace() and ch not in "\"'「」『』“”‘’“”")
