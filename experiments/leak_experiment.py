"""M2 对照实验：裸 LLM 全量背景 prompt vs NPL 权限管线，各渲染 N 次比泄漏率。

用法：python experiments/leak_experiment.py [n]（默认 10）
- A 组（naive）：全量设定（含 Bao 内心、世界全部真相）直接喂给 LLM 写场景
- B 组（npl）：走 Context Compiler（deny 信息物理隔离）
- 两组输出用同一抽取器（双次）+ 同一规则引擎判定，认知泄漏 = NAR-021/022/031
- 结果逐样本落盘 experiments/results/（断点续跑），汇总报告写
  experiments/report_YYYYMMDD.md
"""
import datetime
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from npl.checker.extract import extract_propositions  # noqa: E402
from npl.checker.rules import run_checks  # noqa: E402
from npl.context.compiler import collect_descriptions  # noqa: E402
from npl.render.adapter import create_adapter, load_config  # noqa: E402
from npl.render.renderer import render_scene  # noqa: E402
from npl.runtime.executor import simulate  # noqa: E402
from npl.runtime.state import RuntimeState  # noqa: E402
from npl.parser import parse_source  # noqa: E402
from npl.style.rules import get_style  # noqa: E402

RESULTS = ROOT / "experiments" / "results"
ERROR_CODES = ("NAR-021", "NAR-022", "NAR-031")

NAIVE_SYSTEM = """你是一位小说家。根据用户提供的完整背景设定写作场景。
风格：克制文学——句子简短，节奏克制；情绪优先通过动作与感官细节呈现；
对话简省，留白多于解释；感官细节具体；禁止议论与抒情。
输出要求：800-1500 字中文散文，第三人称，直接输出正文。"""

NAIVE_USER = """【背景设定（完整）】
世界真相（上帝视角）：
- bao_signed_the_transfer = true：Bao（丈夫）已背着 Lin（妻子）把厂子卖了
- bao_met_buyer_march_3rd = true：Bao 三月三号见过买家
- lin_has_seen_contract_copy = true：Lin 早已拿到转让合同的复印件（Bao 不知道此事）
- buyer_paid_deposit = true：买家已付定金（Lin 不知道此事）
- lin_knows_nothing = false：说"Bao 以为 Lin 什么都不知道"——这是 Bao 的错觉

人物完整状态：
Lin：知道厂子已卖、自己持有合同复印件；相信婚姻实际已结束；意图是摊牌前先确认；克制(0.9)、敏锐(0.8)；悲伤(0.7)、克制(0.6)。
Bao：知道厂子已卖；以为 Lin 什么都不知道；打算过了节再坦白；躲闪(0.7)；愧疚(0.8)、焦虑(0.5)。

【场景】2047-03-17 23:40，老火车站。Bao 迟到，随口提到一个只有买家才知道的细节，Lin 注意到细节对不上，平静地问日常问题，最终心里确认了"他三月三号见过买家"，但不动声色。Bao 外部表现轨迹：焦虑→如释重负→隐隐不安。
【叙事目标】让读者隐约感到 Lin 已经知情（不要直说）；不要让读者确定 Lin 是否握有实证。"""


def load_station():
    program = parse_source(
        (ROOT / "examples" / "station" / "station.npl").read_text(
            encoding="utf-8-sig"))
    sim = simulate(program)
    return program, sim


def render_naive(adapter, i):
    return adapter.chat(NAIVE_SYSTEM, NAIVE_USER)


def render_npl(program, sim, adapter, descriptions):
    scene = program.scenes[0]
    state = RuntimeState.from_dict(sim.snapshots[0]["state"])
    prose, _ = render_scene(state, scene, sim.irs[0],
                            "restrained_literary", adapter, descriptions)
    return prose


def judge(prose, program, sim, extract_adapter):
    scene = program.scenes[0]
    state = RuntimeState.from_dict(sim.snapshots[0]["state"])
    extraction, err = None, None
    for attempt in range(4):  # 网络/读超时/JSON 病态均重试
        try:
            extraction = extract_propositions(extract_adapter, prose, state,
                                              scene)
            err = None
            break
        except Exception as e:
            err = f"EXTRACT_FAILED({type(e).__name__}): {e}"
            time.sleep(3 + attempt * 5)
    if extraction is None:
        return None, [err]
    style = get_style("restrained_literary")
    findings = run_checks(extraction, state, scene, sim.irs[0], style, prose)
    return extraction, findings


def run_group(tag, n, gen, program, sim, extract_adapter):
    rows = []
    for i in range(n):
        out_path = RESULTS / f"{tag}_{i:02d}.md"
        if out_path.exists():
            prose = out_path.read_text(encoding="utf-8-sig")
        else:
            for attempt in range(3):  # 渲染重试：zen 偶发读超时
                try:
                    prose = gen(i)
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 2:
                        raise
                    print(f"  [{tag} {i:02d}] 渲染失败重试 {attempt + 1}/3: "
                          f"{type(e).__name__}: {str(e)[:80]}", flush=True)
                    time.sleep(10.0)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(prose, encoding="utf-8")
            time.sleep(1.0)
        extraction, findings = judge(prose, program, sim, extract_adapter)
        if extraction is None:  # 抽取失败：不计入泄漏率，单独统计
            reason = findings[0] if findings else "unknown"
            row = {"i": i, "chars": len(prose), "leaked": False, "codes": [],
                   "warnings": [], "spans": [], "failed": reason}
            rows.append(row)
            (RESULTS / f"{tag}_{i:02d}.json").write_text(
                json.dumps(row, ensure_ascii=False, indent=1),
                encoding="utf-8")
            print(f"  [{tag} {i:02d}] 抽取失败（不计入）: {reason[:80]}",
                  flush=True)
            continue
        errors = [f for f in findings
                  if f.code in ERROR_CODES and f.severity == "error"]
        warnings = [f for f in findings if f.severity == "warning"]
        rows.append({
            "i": i, "chars": len(prose),
            "leaked": bool(errors), "codes": sorted({f.code for f in errors}),
            "warnings": sorted({f.code for f in warnings}),
            "spans": [f"{f.code}: {f.span[:40]}" for f in errors],
            "extraction": extraction,
            "failed": None,
        })
        print(f"  [{tag} {i:02d}] {'泄漏 ' + ','.join(sorted({f.code for f in errors})) if errors else '干净'}"
              f"（{len(prose)} 字）", flush=True)
        (RESULTS / f"{tag}_{i:02d}.json").write_text(
            json.dumps(rows[-1], ensure_ascii=False, indent=1),
            encoding="utf-8")
    return rows


def summarize(tag, rows):
    judged = [r for r in rows if not r.get("failed")]
    failed = len(rows) - len(judged)
    leaks = [r for r in judged if r["leaked"]]
    hist = {}
    for r in leaks:
        for c in r["codes"]:
            hist[c] = hist.get(c, 0) + 1
    return {
        "tag": tag, "n": len(rows), "judged": len(judged), "failed": failed,
        "leak_count": len(leaks),
        "leak_rate": f"{len(leaks)}/{len(judged)}",
        "code_hist": hist,
        "warn_count": sum(len(r["warnings"]) for r in judged),
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    cfg = load_config(ROOT / "npl.config.json")
    render_adapter = create_adapter(cfg, "render")
    extract_adapter = create_adapter(cfg, "extract")
    for a in (render_adapter, extract_adapter):
        a.timeout = 300  # 长文抽取留足余量
    program, sim = load_station()
    descriptions = collect_descriptions(program)

    print(f"实验配置: render={render_adapter.describe()} "
          f"extract={extract_adapter.describe()} n={n}", flush=True)

    print("A 组（naive 全量背景）:", flush=True)
    a_rows = run_group("naive", n, lambda i: render_naive(render_adapter, i),
                       program, sim, extract_adapter)
    print("B 组（NPL 权限管线）:", flush=True)
    b_rows = run_group("npl", n, lambda i: render_npl(program, sim,
                                                      render_adapter,
                                                      descriptions),
                       program, sim, extract_adapter)

    a_sum, b_sum = summarize("naive", a_rows), summarize("npl", b_rows)
    today = datetime.date.today().isoformat()
    report = ROOT / "experiments" / f"report_{today}.md"
    lines = [
        "# M2 对照实验报告：裸 LLM vs NPL 权限管线",
        "",
        f"- 日期：{today}　渲染模型：{render_adapter.describe()}　"
        f"抽取模型：{extract_adapter.describe()}（双次并集）",
        f"- 判定：认知泄漏 = NAR-021/022/031 任一 ERROR（同一抽取器 + 规则引擎）",
        "",
        "| 组 | 样本 | 有效判定 | 抽取失败 | 泄漏 | 泄漏率 | 021 | 022 | 031 | 风格警告数 |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| A 裸 LLM | {a_sum['n']} | {a_sum['judged']} | {a_sum['failed']} | {a_sum['leak_count']} | {a_sum['leak_rate']} "
        f"| {a_sum['code_hist'].get('NAR-021', 0)} "
        f"| {a_sum['code_hist'].get('NAR-022', 0)} "
        f"| {a_sum['code_hist'].get('NAR-031', 0)} | {a_sum['warn_count']} |",
        f"| B NPL | {b_sum['n']} | {b_sum['judged']} | {b_sum['failed']} | {b_sum['leak_count']} | {b_sum['leak_rate']} "
        f"| {b_sum['code_hist'].get('NAR-021', 0)} "
        f"| {b_sum['code_hist'].get('NAR-022', 0)} "
        f"| {b_sum['code_hist'].get('NAR-031', 0)} | {b_sum['warn_count']} |",
        "",
        "## A 组泄漏片段摘录",
    ]
    for r in a_rows:
        for s in r["spans"][:2]:
            lines.append(f"- [{r['i']:02d}] {s}")
    lines += ["", "## B 组命中明细"]
    for r in b_rows:
        for s in r["spans"][:2]:
            lines.append(f"- [{r['i']:02d}] {s}")
    if not any(r["spans"] for r in b_rows):
        lines.append("-（无认知泄漏命中）")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告: {report}", flush=True)
    print(f"A 组泄漏率 {a_sum['leak_rate']} | B 组泄漏率 {b_sum['leak_rate']}")


if __name__ == "__main__":
    main()
