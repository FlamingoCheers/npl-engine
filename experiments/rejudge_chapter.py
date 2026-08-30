# -*- coding: utf-8 -*-
"""离线全章判定：人工抽取（build/extract_manual/）× 规则引擎。

与 `npl check` 走同一套 run_checks，只是命题抽取由人工/外部模型
预先写好 JSON（v7 判定口径），不调 API。零成本、可复跑。
用法: python experiments/rejudge_chapter.py examples/novel/chapter_one.npl
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from npl.parser import parse_source          # noqa: E402
from npl.runtime import simulate, RuntimeState  # noqa: E402
from npl.checker.rules import run_checks     # noqa: E402
from npl.style.rules import resolve_style    # noqa: E402
from npl.cli import _primary_style, _strip_prose_header  # noqa: E402


def main():
    src = Path(sys.argv[1])
    program = parse_source(src.read_text(encoding="utf-8-sig"))
    result = simulate(program)
    style = resolve_style(_primary_style(program), program.styles)
    manual = ROOT / "build" / "extract_manual"
    prose_dir = ROOT / "build" / "prose"

    total_e = total_w = 0
    for idx, scene in enumerate(program.scenes, 1):
        prose = _strip_prose_header(
            (prose_dir / f"scene_{idx:03d}.md").read_text(encoding="utf-8-sig"))
        extraction = json.loads(
            (manual / f"scene_{idx:03d}.json").read_text(encoding="utf-8"))
        state = RuntimeState.from_dict(result.snapshots[idx - 1]["state"])
        findings = run_checks(extraction, state, scene,
                              result.irs[idx - 1], style, prose,
                              scene_idx=idx - 1, program=program)
        errs = [f for f in findings if f.severity == "error"]
        warns = [f for f in findings if f.severity != "error"]
        total_e += len(errs)
        total_w += len(warns)
        mark = "✓" if not findings else "✗"
        print(f"{mark} 第 {idx} 幕「{scene.title}」: "
              f"{len(errs)} ERROR, {len(warns)} WARNING")
        for f in findings:
            print(f"  {mark} {f.code} [{f.severity}] {f.message}"
                  f"｜片段: “{f.span[:40]}”" if f.span else
                  f"  {mark} {f.code} [{f.severity}] {f.message}")
    print(f"---\n检查完成: {total_e} ERROR, {total_w} WARNING")
    return 1 if total_e else 0


if __name__ == "__main__":
    sys.exit(main())
