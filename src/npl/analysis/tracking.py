"""NPL 跨章长程母题追踪（v0.3）。

单章聚类沿用 imagery.extract_candidates；本模块把多章的局部聚类合并为
长程母题轨迹（track），输出频率曲线（千字归一）、间隔（gap）统计与
断线/间歇预警。纯离线统计，零 LLM。
"""

from __future__ import annotations

import json
from collections import Counter

from .imagery import _char_bigrams, extract_candidates, tokenize

# 轨迹状态
ACTIVE = "活跃"        # 最后一章仍出现
TAILING = "收尾"       # 末章未出现，但离末章不足 gap_alert 章
INTERMITTENT = "间歇"  # 中间出现过 ≥gap_alert 章的空洞
DROPPED = "断线"       # 已声明母题，距末次出现 ≥gap_alert 章且未到末章收束


def _mergeable(a: dict, b: dict) -> bool:
    """跨章合并规则：label 相同 / 词族相交 / 字符 bigram 相交。"""
    if a["label"] == b["label"]:
        return True
    if set(a["members"]) & set(b["members"]):
        return True
    return bool(_char_bigrams(a["label"]) & _char_bigrams(b["label"]))


def track_motifs(chapters: dict, declared: dict = None,
                 min_scenes: int = 2, min_total: int = 3,
                 gap_alert: int = 2) -> dict:
    """跨章母题追踪。

    chapters: {章节名: [(场景名, 正文), ...]}，按叙述顺序排列。
    declared: {章节名: {已声明母题 id, ...}}，可省略。
    返回可 JSON 序列化的报告 dict：
    {"chapters": [...], "gap_alert": n,
     "motifs": [{label, members, declared_in, series, freq, total,
                 first, last, max_gap, status, alerts, trend}, ...]}
    """
    declared = declared or {}
    chapter_names = list(chapters.keys())
    n_ch = len(chapter_names)
    chapter_chars = {ch: sum(len(t) for _, t in chapters[ch]) for ch in chapter_names}

    # 1) 逐章局部聚类（复用 v0.2）
    local = {ch: extract_candidates({s: t for s, t in scenes},
                                    min_scenes=min_scenes, min_total=min_total)
             for ch, scenes in chapters.items()}

    # 2) 跨章合并为轨迹（种子来自逐章聚类；词族可跨章生长）
    tracks = []  # [{label, members:set, declared_in:set}]
    for ch in chapter_names:
        for c in local[ch]:
            for t in tracks:
                if _mergeable(t, c):
                    t["members"].update(c["members"])
                    break
            else:
                tracks.append({"label": c["label"],
                               "members": set(c["members"]) | {c["label"]},
                               "declared_in": set()})

    # 3) 声明匹配：母题 id 等于 label 或属于词族
    for ch in chapter_names:
        ids = declared.get(ch) or set()
        if not ids:
            continue
        for t in tracks:
            hit = (t["label"] in ids) or (set(t["members"]) & ids)
            if hit:
                t["declared_in"].add(ch)
                t["members"].update(ids & (set(t["members"]) | {t["label"]}))

    # 4) 逐轨迹统计：series 直接回扫各章全文计数——
    #    不依赖"该章是否聚出"（单次出现的章不该被误判为断线）
    chapter_counters = {ch: Counter(tokenize("\n".join(t for _, t in scenes)))
                        for ch, scenes in chapters.items()}

    # 5) 逐轨迹统计
    out = []
    for t in tracks:
        series = {ch: sum(chapter_counters[ch][w] for w in t["members"])
                  for ch in chapter_names}
        present = [i for i, ch in enumerate(chapter_names) if series[ch] > 0]
        if not present:
            continue
        first, last = present[0], present[-1]
        # 最大空洞（首末出现之间的连续零章数）
        max_gap, run = 0, 0
        for i in range(first, last + 1):
            if series[chapter_names[i]] == 0:
                run += 1
                max_gap = max(max_gap, run)
            else:
                run = 0
        freq = {}
        for ch, n in series.items():
            chars = chapter_chars[ch]
            freq[ch] = round(n / chars * 1000, 2) if chars else 0.0

        dec = sorted(t["declared_in"])
        alerts = []
        if dec:
            tail = (n_ch - 1) - last
            if max_gap >= gap_alert:
                status = INTERMITTENT
                alerts.append(f"最长间隔 {max_gap} 章（第 {first + 1}~{last + 1} 章间）")
            elif last == n_ch - 1:
                status = ACTIVE
            elif tail >= gap_alert:
                status = DROPPED
                alerts.append(f"第 {last + 1} 章后已连续 {tail} 章未出现")
            else:
                status = TAILING
        else:
            status = INTERMITTENT if max_gap >= gap_alert else (
                ACTIVE if last == n_ch - 1 else TAILING)
            if status == INTERMITTENT:
                alerts.append(f"最长间隔 {max_gap} 章（第 {first + 1}~{last + 1} 章间）")

        # 趋势：前半 vs 后半 平均千字频率
        half = max(1, n_ch // 2)
        front = [freq[c] for c in chapter_names[:half] if freq[c] is not None]
        back = [freq[c] for c in chapter_names[half:] if freq[c] is not None]
        f_mean = sum(front) / len(front) if front else 0.0
        b_mean = sum(back) / len(back) if back else 0.0
        if f_mean == 0 and b_mean == 0:
            trend = "平稳"
        elif b_mean > f_mean * 1.3:
            trend = "上升"
        elif f_mean > b_mean * 1.3:
            trend = "回落"
        else:
            trend = "平稳"

        out.append({"label": t["label"], "members": sorted(t["members"]),
                    "declared_in": dec, "series": series, "freq": freq,
                    "total": sum(series.values()), "first": chapter_names[first],
                    "last": chapter_names[last], "max_gap": max_gap,
                    "status": status, "alerts": alerts, "trend": trend})

    # 已声明在前，其余按总频次
    out.sort(key=lambda m: (not m["declared_in"], -m["total"], m["label"]))
    return {"chapters": chapter_names, "gap_alert": gap_alert, "motifs": out}


def render_track_report(report: dict) -> list:
    """报告 → 人类可读行列表（CLI 用）。"""
    lines = []
    chs = report["chapters"]
    lines.append(f"跨章母题追踪（{len(chs)} 章：{'、'.join(chs)}；"
                 f"断线阈值 {report['gap_alert']} 章）")
    if not report["motifs"]:
        lines.append("  （未发现跨章重复意象）")
        return lines
    for m in report["motifs"]:
        tag = f"★已声明({','.join(m['declared_in'])})" if m["declared_in"] else ""
        arrow = " → ".join(f"{m['series'][ch]}×" for ch in chs)
        lines.append(f"  {m['label']}  {m['status']}（{m['trend']}）  {tag}")
        members = "/".join(m["members"][:6]) + ("…" if len(m["members"]) > 6 else "")
        lines.append(f"    词族: {members}")
        lines.append(f"    出现: {arrow}（共 {m['total']} 次；首现 {m['first']}，"
                     f"末现 {m['last']}）")
        freqs = " → ".join(f"{m['freq'][ch]}/千字" for ch in chs)
        lines.append(f"    频率: {freqs}")
        for a in m["alerts"]:
            lines.append(f"    ⚠ {a}")
    return lines


def report_to_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
