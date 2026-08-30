# -*- coding: utf-8 -*-
"""把每幕权限过滤后的渲染上下文与完整 prompt 落盘（build/render_context/）。

用途：离线/人工渲染工作流——渲染 LLM（人或模型）只读这些文件，
与 `npl render` 走 zen API 时看到的上下文完全一致。
用法: python experiments/dump_ctx.py examples/novel/chapter_one.npl
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from npl.parser import parse_source          # noqa: E402
from npl.runtime import simulate, RuntimeState  # noqa: E402
from npl.context.compiler import (           # noqa: E402
    collect_descriptions, compile_render_context)
from npl.render import prompts               # noqa: E402
from npl.cli import _primary_style           # noqa: E402


def main():
    src = Path(sys.argv[1])
    program = parse_source(src.read_text(encoding="utf-8-sig"))
    result = simulate(program)
    descriptions = collect_descriptions(program)
    style = _primary_style(program)
    outdir = ROOT / "build" / "render_context"
    outdir.mkdir(parents=True, exist_ok=True)
    for idx, scene in enumerate(program.scenes, 1):
        state = RuntimeState.from_dict(result.snapshots[idx - 1]["state"])
        ir = result.irs[idx - 1]
        ctx = compile_render_context(state, scene, ir, style, descriptions)
        system = prompts.build_system_prompt(ctx, ctx["style"])
        user = prompts.build_user_prompt(ctx)
        p = outdir / f"scene_{idx:03d}.md"
        p.write_text(
            f"<!-- scene {idx}: {scene.title}｜style: {style} -->\n\n"
            f"## SYSTEM\n\n{system}\n\n## USER\n\n{user}\n",
            encoding="utf-8")
        print(f"scene {idx}: {scene.title} -> {p}")


if __name__ == "__main__":
    main()
