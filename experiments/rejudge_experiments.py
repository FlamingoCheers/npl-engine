# -*- coding: utf-8 -*-
"""离线重判：用已保存的 extraction 重跑规则引擎（零 API 调用）。

规则引擎更新（如 021a 戏剧反讽豁免）后，无需重新渲染/抽取，
直接对本轮已落盘的抽取结果重新判定并重写报告。
"""
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from npl.checker.rules import run_checks  # noqa: E402
from npl.style.rules import get_style  # noqa: E402
from npl.runtime.state import RuntimeState  # noqa: E402

from leak_experiment import ERROR_CODES, RESULTS, load_station, summarize  # noqa: E402


def main():
    program, sim = load_station()
    scene = program.scenes[0]
    ir = sim.irs[0]
    style = get_style("restrained_literary")
    state = RuntimeState.from_dict(sim.snapshots[0]["state"])

    summaries = {}
    for tag in ("naive", "npl"):
        rows = []
        for i in range(100):
            p = RESULTS / f"{tag}_{i:02d}.json"
            if not p.exists():
                break
            row = json.loads(p.read_text(encoding="utf-8"))
            ex = row.get("extraction")
            if ex is None:
                rows.append(row)  # 抽取失败样本原样保留
                continue
            findings = run_checks(ex, state, scene, ir, style, "")
            errors = [f for f in findings
                      if f.code in ERROR_CODES and f.severity == "error"]
            warnings = [f for f in findings if f.severity == "warning"]
            row.update({
                "leaked": bool(errors),
                "codes": sorted({f.code for f in errors}),
                "warnings": sorted({f.code for f in warnings}),
                "spans": [f"{f.code}: {f.span[:40]}" for f in errors],
            })
            p.write_text(json.dumps(row, ensure_ascii=False, indent=1),
                         encoding="utf-8")
            rows.append(row)
        summaries[tag] = summarize(tag, rows)

    a_sum, b_sum = summaries["naive"], summaries["npl"]
    today = datetime.date.today().isoformat()
    report = ROOT / "experiments" / f"report_{today}.md"
    lines = [
        "# M2 对照实验报告：裸 LLM vs NPL 权限管线",
        "",
        f"- 日期：{today}（离线重判版：021a 增加戏剧反讽豁免后，"
        f"以已存抽取结果重跑规则引擎）",
        "- 判定：认知泄漏 = NAR-021/022/031 任一 ERROR（同一抽取器 + 规则引擎）",
        "",
        "| 组 | 样本 | 有效判定 | 抽取失败 | 泄漏 | 泄漏率 | 021 | 022 | 031 | 风格警告数 |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| A 裸 LLM | {a_sum['n']} | {a_sum['judged']} | {a_sum['failed']} "
        f"| {a_sum['leak_count']} | {a_sum['leak_rate']} "
        f"| {a_sum['code_hist'].get('NAR-021', 0)} "
        f"| {a_sum['code_hist'].get('NAR-022', 0)} "
        f"| {a_sum['code_hist'].get('NAR-031', 0)} | {a_sum['warn_count']} |",
        f"| B NPL | {b_sum['n']} | {b_sum['judged']} | {b_sum['failed']} "
        f"| {b_sum['leak_count']} | {b_sum['leak_rate']} "
        f"| {b_sum['code_hist'].get('NAR-021', 0)} "
        f"| {b_sum['code_hist'].get('NAR-022', 0)} "
        f"| {b_sum['code_hist'].get('NAR-031', 0)} | {b_sum['warn_count']} |",
        "",
        "## A 组泄漏片段摘录",
    ]
    for i in range(100):
        p = RESULTS / f"naive_{i:02d}.json"
        if not p.exists():
            break
        row = json.loads(p.read_text(encoding="utf-8"))
        for s in row["spans"][:2]:
            lines.append(f"- [{row['i']:02d}] {s}")
    lines += ["", "## B 组命中明细"]
    any_b = False
    for i in range(100):
        p = RESULTS / f"npl_{i:02d}.json"
        if not p.exists():
            break
        row = json.loads(p.read_text(encoding="utf-8"))
        for s in row["spans"][:2]:
            any_b = True
            lines.append(f"- [{row['i']:02d}] {s}")
    if not any_b:
        lines.append("-（无认知泄漏命中）")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告: {report}")
    print(f"A 组泄漏率 {a_sum['leak_rate']} | B 组泄漏率 {b_sum['leak_rate']}")


if __name__ == "__main__":
    main()
