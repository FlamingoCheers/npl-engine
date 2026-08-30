"""NPL 命令行入口。

子命令：
  validate <file> [--json]            语法 + 语义校验
  simulate <file> [--out DIR]          确定性模拟 → 状态快照 + Scene IR
  render <file> [--scene N] [--adapter A] [--config F] [--out DIR] [--stdout]
                                       场景渲染（默认 mock 适配器；真实 LLM 需配置）
  inspect <file> [--character X] [--scene N] [--reader] [--deep]
                                       查询任意时点的角色认知 / Reader Model 视图
                                       （--deep 对深层嵌套做逐层接地验证）
  actor <file> --character X [--scene N] [--adapter A]
                                       LLM Actor 模式：epistemic sandbox 内产出行动提议
                                       （M3；脚本模式仍是唯一真值源，提议需写回 .npl）
  check <file> [--prose F] [--scene N] [--adapter A]
                                       认知泄漏检查（抽取 + 规则引擎；缺省扫描全部已渲染幕）
  diff <file> [--scene N]              相邻快照 diff（这一幕改变了什么）
"""
import argparse
import json
import re
import sys
from pathlib import Path

from .ast_nodes import Program
from .parser import load_program
from .render.adapter import RenderError, create_adapter, load_config
from .render.renderer import render_scene
from .runtime.epistemics import deep_grounding
from .runtime.executor import simulate
from .runtime.state import RuntimeState, canonical_to_display
from .validator import validate


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except OSError as e:
        print(f"✗ 无法读取文件: {e}")
        return None


def _load_and_validate(path):
    """读入（含 import 展开）→ 解析 → 校验。失败返回 (None, exit_code)。"""
    try:
        program = load_program(path)
    except Exception as e:  # NPLSyntaxError（含 NAR-015/016）或 IO 错误
        line = getattr(e, "line", "?")
        code = getattr(e, "code", "NAR-001")
        print(f"✗ {code} [行 {line}] {e}")
        return None, 1
    diags = validate(program)
    errors = [d for d in diags if d.severity == "error"]
    warnings = [d for d in diags if d.severity == "warning"]
    for d in errors:
        print(f"✗ {d.code} [行 {d.line}] {d.message}")
    for d in warnings:
        print(f"⚠ {d.code} [行 {d.line}] {d.message}")
    if errors:
        return None, 1
    return program, warnings


def _dump_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _primary_style(program: Program) -> str:
    if program.render and program.render.style:
        return program.render.style
    return "default"


# ---------------------------------------------------------------- validate
def cmd_validate(args):
    try:
        program = load_program(args.file)
    except Exception as e:
        line = getattr(e, "line", "?")
        code = getattr(e, "code", "NAR-001")
        if args.json:
            print(json.dumps({"ok": False,
                              "errors": [{"code": code, "line": line,
                                          "message": str(e)}]},
                             ensure_ascii=False))
        else:
            print(f"✗ {code} [行 {line}] {e}")
        return 1
    diags = validate(program)
    errors = [d for d in diags if d.severity == "error"]
    warnings = [d for d in diags if d.severity == "warning"]
    if args.json:
        print(json.dumps({
            "ok": not errors,
            "errors": [d.as_dict() for d in errors],
            "warnings": [d.as_dict() for d in warnings],
        }, ensure_ascii=False))
        return 0 if not errors else 1
    for d in errors:
        print(f"✗ {d.code} [行 {d.line}] {d.message}")
    for d in warnings:
        print(f"⚠ {d.code} [行 {d.line}] {d.message}")
    if not errors:
        chars = len(program.characters)
        infos = len(program.informations)
        scenes = len(program.scenes)
        wf = len(program.world.facts) if program.world else 0
        print(f"✓ {args.file}: 校验通过（1 个 world（{wf} 项事实），"
              f"{chars} 个人物，{infos} 个信息对象，{scenes} 个场景）"
              + (f"，{len(warnings)} 个警告" if warnings else ""))
    return 0 if not errors else 1


# ---------------------------------------------------------------- simulate
def _check_process_order(program, state_dict):
    """v0.4：世界进程阶段单调性检查。阶段序 = 声明序；后阶段为真而前置未真 → 乱序。"""
    lines = []
    if program.world is None:
        return lines
    facts = state_dict.get("world", {}).get("facts", {})
    for proc in program.world.processes:
        seen_false = False
        for st in proc.stages:
            if bool(facts.get(st.fact)):
                if seen_false:
                    lines.append(f"⚠ 进程 '{proc.name}' 阶段乱序：'{st.name}'"
                                 f"（{st.fact}）已发生，但其前置阶段未全部为真")
                    break
            else:
                seen_false = True
    return lines


def _emit_simulation(result, out, header=None):
    """模拟结果的统一落盘与摘要输出（cmd_simulate / cmd_continue 共用）。"""
    out = Path(out)
    if header:
        print(header)
    print(f"✓ 模拟完成：{len(result.snapshots)} 个场景")
    for snap, ir, chg in zip(result.snapshots, result.irs, result.changes):
        idx = snap["meta"]["scene_index"]
        _dump_json(snap, out / "state_snapshots" / f"scene_{idx:03d}.json")
        _dump_json(ir, out / "scene_ir" / f"scene_{idx:03d}.json")
        fb = "｜闪回" if snap["meta"].get("flashback") else ""
        parts = []
        for key, label in (("knows_added", "获知"), ("believes_added", "误信"),
                           ("suspects_added", "怀疑"), ("hides_added", "隐藏")):
            seg = "、".join(f"{c}(+{', '.join(ps)})" for c, ps in chg[key].items() if ps)
            if seg:
                parts.append(f"{label}: {seg}")
        who = "；".join(parts) or "无"
        print(f"  [{idx}] {snap['meta']['scene_title']}"
              f"｜POV: {ir['framing']['pov']}{fb}｜认知变更: {who}")
    print(f"  快照: {out / 'state_snapshots'}")
    print(f"  IR:   {out / 'scene_ir'}")


def cmd_simulate(args):
    program, _ = _load_and_validate(args.file)
    if program is None:
        return 1
    result = simulate(program)
    _emit_simulation(result, args.out)
    for line in _check_process_order(program, result.snapshots[-1]["state"]):
        print(line)
    return 0


# ---------------------------------------------------------------- continue
def _load_snapshot(path):
    """读取快照 JSON，返回 (snap, err_message)。"""
    p = Path(path)
    if not p.exists():
        return None, f"快照不存在: {p}"
    try:
        snap = json.loads(p.read_text(encoding="utf-8-sig"))
        if not isinstance(snap, dict) or "state" not in snap or "meta" not in snap:
            return None, f"不是有效的场景快照: {p}"
    except (json.JSONDecodeError, OSError) as e:
        return None, f"快照读取失败: {e}"
    return snap, None


def cmd_continue(args):
    snap, err = _load_snapshot(args.snapshot)
    if err:
        print(f"✗ {err}")
        return 2
    start = snap["meta"].get("scene_index")
    if not isinstance(start, int):
        print("✗ 快照缺少 meta.scene_index，无法续接编号")
        return 2
    program, _ = _load_and_validate(args.file)
    if program is None:
        return 1
    known = set(snap["state"].get("characters", {}))
    unknown = sorted({name for scene in program.scenes
                      for name in [scene.pov, *(p.name for p in scene.participants)]
                      if name not in known})
    if unknown:
        print(f"✗ 快照中没有这些人物: {', '.join(unknown)}"
              "（续跑程序必须复用基程序的世界与人物）")
        return 1
    from .runtime.executor import simulate_continue
    # 快照是第 start 幕执行后的状态：追加场景从 start+1 号开始
    result = simulate_continue(RuntimeState.from_dict(snap["state"]),
                               program.scenes, start + 1)
    _emit_simulation(result, args.out,
                     header=f"◆ 从快照 scene_{start:03d} 续跑")
    for line in _check_process_order(program, result.snapshots[-1]["state"]):
        print(line)
    return 0


def cmd_branch_diff(args):
    a, err = _load_snapshot(args.snapshot_a)
    if err:
        print(f"✗ {err}")
        return 2
    b, err = _load_snapshot(args.snapshot_b)
    if err:
        print(f"✗ {err}")
        return 2

    def _title(snap):
        m = snap.get("meta", {})
        return f"scene_{m.get('scene_index', '?'):0>3} {m.get('scene_title', '')}"

    print(f"◆ 分支 A: {_title(a)}")
    print(f"◆ 分支 B: {_title(b)}")
    diffs = _diff_states(a["state"], b["state"])
    if not diffs:
        print("  两分支状态一致")
        return 0
    for line in diffs:
        print(f"  {line}")
    return 0


# ---------------------------------------------------------------- render
def cmd_render(args):
    program, _ = _load_and_validate(args.file)
    if program is None:
        return 1
    try:
        config = load_config(args.config)
        adapter = create_adapter(config, "render", args.adapter)
    except RenderError as e:
        print(f"✗ {e}")
        return 2

    result = simulate(program)
    total = len(result.snapshots)
    indices = [args.scene] if args.scene else list(range(1, total + 1))
    for idx in indices:
        if not (1 <= idx <= total):
            print(f"✗ 场景编号越界: {idx}（共 {total} 幕）")
            return 2
    style = _primary_style(program)
    scene_decls = {i: s for i, s in enumerate(program.scenes, 1)}

    out = Path(args.out)
    prose_paths = []
    from .context.compiler import collect_descriptions
    descriptions = collect_descriptions(program)
    for idx in indices:
        scene = scene_decls[idx]
        ir = result.irs[idx - 1]
        state = RuntimeState.from_dict(result.snapshots[idx - 1]["state"])
        try:
            prose, _ctx = render_scene(state, scene, ir, style, adapter,
                                       descriptions,
                                       style_decls=program.styles)
        except RenderError as e:
            print(f"✗ 第 {idx} 幕渲染失败: {e}")
            return 2
        header = (f"<!-- npl render｜scene {idx}: {scene.title}"
                  f"｜adapter: {adapter.describe()}｜style: {style} -->\n\n")
        path = out / "prose" / f"scene_{idx:03d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header + prose.rstrip() + "\n", encoding="utf-8")
        prose_paths.append(path)
        print(f"✓ [{idx}] {scene.title} → {path}（{adapter.describe()}）")
        if args.stdout:
            print()
            print(header + prose)
    return 0


# ---------------------------------------------------------------- inspect
def _belief_marks(state, props):
    facts = state.world["facts"]
    out = []
    for p in props:
        if p in facts:
            if facts[p] is False:
                out.append(f"{p} ← 虚假信念（世界中该命题为 false）")
            else:
                out.append(f"{p}（与真相一致）")
        else:
            out.append(f"{p}（真值未知）")
    return out


def _print_character_view(state, name, scene_title, idx, total, added, deep=False):
    cs = state.characters[name]
    print(f"=== {name} @ scene \"{scene_title}\"（第 {idx}/{total} 幕）结束时 ===")
    knows = ", ".join(
        p + ("*" if added and p in added else "")
        for p in sorted(cs["knows"])) or "（无）"
    print(f"  knows: {knows}")
    if added:
        print(f"        （* 本幕新确认: {', '.join(sorted(added))}）")
    for b in _belief_marks(state, sorted(cs["believes"])):
        print(f"  believes: {b}")
    verb_cn = {"knows": "知道", "does_not_know": "不知道", "believes": "相信"}
    for holder, bucket in sorted(cs.get("believes_about", {}).items()):
        actual_knows = state.characters.get(holder, {}).get("knows", set())
        facts = state.world["facts"]
        for verb, props in sorted(bucket.items()):
            for p in sorted(props):
                if verb == "believes" or p not in facts:
                    mark = "（真值未知）"
                elif (p in actual_knows) == (verb == "knows"):
                    mark = "（与事实一致）"
                else:
                    mark = " ← 虚假嵌套信念（该人物实际认知相反）"
                print(f"  believes_about[{holder}]: 相信 {holder} "
                      f"{verb_cn.get(verb, verb)} {p}{mark}")
    if cs["suspects"]:
        sus = ", ".join(f"{k}（置信度 {v}）" for k, v in sorted(cs["suspects"].items()))
        print(f"  suspects: {sus}")
    nested = sorted(cs.get("nested_beliefs", []))
    if nested:
        print("  嵌套认知（深层建模，默认验证深度 1）:")
        for canon in nested:
            print(f"    {canonical_to_display(canon)}")
            if not deep:
                continue
            g = deep_grounding(state, canon)
            if g is None:
                print("      接地: 链格式异常")
                continue
            for lv in g["levels"]:
                mark = {"holds": "✓", "unknown": "？"}[lv["verdict"]] \
                    if lv["verdict"] in ("holds", "unknown") else "✗"
                print(f"      {mark} {lv['claim']} — {lv['evidence']}")
            if g["verdict"] == "holds":
                print("      判定: 接地成立（基础命题近似）")
            else:
                kind, holder = g["verdict"].split(":", 1)
                note = "无认知记录" if kind == "unknown" else "断裂"
                print(f"      判定: 在 {holder} 层{note}（基础命题近似，深度≥3 中间层未建模）")
    if cs.get("hides"):
        print(f"  hides: {', '.join(sorted(cs['hides']))}")
    if cs["intends"]:
        print(f"  intends: {', '.join(sorted(cs['intends']))}")
    if cs["personality"]:
        pers = ", ".join(f"{k}={v}" for k, v in sorted(cs["personality"].items()))
        print(f"  personality: {pers}")
    if cs["emotion"]:
        emo = ", ".join(f"{k}={v}" for k, v in sorted(cs["emotion"].items()))
        print(f"  emotion: {emo}")
    if cs["arc"]:
        print(f"  arc: {' -> '.join(cs['arc']['states'])}（当前: {cs['arc']['current']}）")
    # 信息对象视角
    lines = []
    for info_id, info in sorted(state.information.items()):
        suspects = ", ".join(f"{c}（置信度 {conf}）"
                             for c, conf in sorted(info["suspected_by"].items()))
        if name in info["holders"]:
            lines.append(f"    持有: {info_id}（真相锚点: {info['truth']}）")
        elif info["public"]:
            lines.append(f"    公开信息: {info_id}（真相锚点: {info['truth']}）")
        else:
            note = f"；被谁怀疑: {suspects}" if suspects else ""
            lines.append(f"    不知道: {info_id}（真相锚点: {info['truth']}）{note}")
    if lines:
        print("  信息视角:")
        for ln in lines:
            print(ln)


def _print_reader_view(state, scene_title, idx, total):
    """Reader Model 视图（M3 §2.3 读者世界）。"""
    nar = state.narrative
    conf = {}
    for ch in state.characters.values():
        for name, v in (ch.get("suspects") or {}).items():
            if name not in conf or v > conf[name]:
                conf[name] = v
    sus = []
    for name in sorted(nar["suspicions"]):
        sus.append(f"{name}（置信度 {conf[name]}）" if name in conf
                   else f"{name}（行为可疑）")
    print(f"=== Reader Model @ scene \"{scene_title}\"（第 {idx}/{total} 幕）结束时 ===")
    print(f"  known_facts: {', '.join(sorted(nar['reader_knows'])) or '（无）'}")
    print(f"  suspicions: {', '.join(sus) or '（无）'}")
    qs = sorted(nar["unanswered_questions"])
    print("  unanswered_questions:")
    for q in qs:
        print(f"    - {q}")
    if not qs:
        print("    （无）")


def cmd_inspect(args):
    program, _ = _load_and_validate(args.file)
    if program is None:
        return 1
    result = simulate(program)
    total = len(result.snapshots)
    idx = args.scene if args.scene else total
    if not (1 <= idx <= total):
        print(f"✗ 场景编号越界: {idx}（共 {total} 幕）")
        return 2
    snap = result.snapshots[idx - 1]
    state = RuntimeState.from_dict(snap["state"])
    scene_title = snap["meta"]["scene_title"]
    if args.reader:
        _print_reader_view(state, scene_title, idx, total)
        return 0
    names = [args.character] if args.character else list(state.characters)
    for name in names:
        if name not in state.characters:
            print(f"✗ 未声明的人物: {name}")
            return 2
    for name in names:
        add = result.changes[idx - 1]["knows_added"].get(name, [])
        _print_character_view(state, name, scene_title, idx, total, add,
                              deep=getattr(args, "deep", False))
    nar = state.narrative
    print("---")
    print(f"叙事状态: reader_knows = [{', '.join(sorted(nar['reader_knows']))}]"
          f" | conceal_active = [{', '.join(sorted(nar['conceal_active']))}]"
          f" | suspicions = [{', '.join(sorted(nar['suspicions']))}]")
    return 0


# ---------------------------------------------------------------- check
def cmd_check(args):
    from .checker.extract import extract_propositions
    from .checker.rules import run_checks
    from .style.rules import resolve_style

    program, _ = _load_and_validate(args.file)
    if program is None:
        return 1
    try:
        config = load_config(args.config)
        adapter = create_adapter(config, "extract", args.adapter)
    except RenderError as e:
        print(f"✗ {e}")
        return 2

    result = simulate(program)
    total = len(result.snapshots)
    style = resolve_style(_primary_style(program), program.styles)
    scene_decls = {i: s for i, s in enumerate(program.scenes, 1)}

    # 待检场景：--prose 指定单文件（须配 --scene，缺省第 1 幕），
    # 否则扫描 build/prose/ 下每幕产物
    jobs = []
    if args.prose:
        idx = args.scene or 1
        jobs.append((idx, Path(args.prose)))
    else:
        base = Path(args.out) / "prose"
        for idx in range(1, total + 1):
            p = base / f"scene_{idx:03d}.md"
            if p.exists():
                jobs.append((idx, p))
    if not jobs:
        print(f"✗ 未找到可检查的散文（先运行 render，或用 --prose 指定文件）")
        return 2

    error_total = 0
    warn_total = 0
    for idx, path in jobs:
        prose = _strip_prose_header(path.read_text(encoding="utf-8-sig"))
        scene = scene_decls[idx]
        state = RuntimeState.from_dict(result.snapshots[idx - 1]["state"])
        try:
            extraction = extract_propositions(
                adapter, prose, state, scene,
                cache_dir=Path(args.out) / "extract_cache")
        except ValueError as e:
            print(f"✗ 第 {idx} 幕命题抽取失败: {e}")
            return 2
        findings = run_checks(extraction, state, scene,
                              result.irs[idx - 1], style, prose,
                              scene_idx=idx - 1, program=program)
        errors = [f for f in findings if f.severity == "error"]
        warnings = [f for f in findings if f.severity == "warning"]
        error_total += len(errors)
        warn_total += len(warnings)
        status = "✓" if not errors else "✗"
        print(f"{status} 第 {idx} 幕「{scene.title}」: "
              f"{len(errors)} ERROR, {len(warnings)} WARNING"
              f"（{path}）")
        for f in findings:
            mark = "✗" if f.severity == "error" else "⚠"
            span = f" ｜片段: “{f.span}”" if f.span else ""
            print(f"  {mark} {f.code} {f.message}{span}")
    print(f"---")
    print(f"检查完成: {error_total} ERROR, {warn_total} WARNING")
    return 1 if error_total else 0


def _strip_prose_header(text):
    """剥掉 render 产物头部的 <!-- npl render ... --> 注释行。"""
    lines = [ln for ln in text.splitlines()
             if not ln.strip().startswith("<!--")]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- actor
def _mock_actor_proposals(ctx, actor):
    """mock 适配器下的确定性提议（不调用 LLM，供管线离线测试）。"""
    pov = ctx["pov"]
    out = []
    for p in list(pov["known_facts"])[:2]:
        out.append({"action": "observes", "args": [p],
                    "reason": "（mock 提议 — 未调用真实 LLM）"})
    if pov["intents"]:
        out.append({"action": "acts_on", "args": [pov["intents"][0]],
                    "reason": "（mock 提议 — 依据意图）"})
    return out or [{"action": "observes", "args": [],
                    "reason": "（mock 提议 — 无可用信息）"}]


def _parse_actor_json(raw):
    """从模型输出中提取 JSON 数组；失败返回 None。"""
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def cmd_actor(args):
    """LLM Actor 模式（M3 §2.6）：epistemic sandbox 内的角色行动提议。

    脚本模式仍是唯一真值源：LLM 只提议，作者确认后把行动写回 .npl 的 events，
    经确定性执行器生效。
    """
    from .context.compiler import collect_descriptions, compile_actor_context
    from .ir.scene_ir import build_ir
    from .render.prompts import build_actor_prompt
    from .runtime.executor import resolve_access

    program, _ = _load_and_validate(args.file)
    if program is None:
        return 1
    if args.character not in {c.name for c in program.characters}:
        print(f"✗ 未声明的人物: {args.character}")
        return 2
    try:
        config = load_config(args.config)
        adapter = create_adapter(config, "render", args.adapter)
    except RenderError as e:
        print(f"✗ {e}")
        return 2

    result = simulate(program)
    total = len(result.snapshots)
    idx = args.scene or 1
    if not (1 <= idx <= total):
        print(f"✗ 场景编号越界: {idx}（共 {total} 幕）")
        return 2
    scene = program.scenes[idx - 1]
    # sandbox 用本幕开始前的状态（角色决策发生在场景内）
    state = (RuntimeState.from_dict(result.snapshots[idx - 2]["state"])
             if idx >= 2 else RuntimeState.from_program(program))
    reveals = [g.target for g in scene.dramatic_goal if g.kind == "reveal"]
    conceals = [g.target for g in scene.dramatic_goal if g.kind == "conceal"]
    ir = build_ir(state, scene, idx, resolve_access(scene), reveals, conceals)
    descriptions = collect_descriptions(program)
    ctx = compile_actor_context(state, scene, ir, _primary_style(program),
                                args.character, descriptions,
                                style_decls=program.styles)
    system, user = build_actor_prompt(ctx)

    if adapter.name == "mock":
        proposals = _mock_actor_proposals(ctx, args.character)
    else:
        raw = adapter.chat(system, user)
        proposals = _parse_actor_json(raw)
        if proposals is None:
            print("✗ 行动提议解析失败（模型未返回 JSON 数组）")
            print(raw[:2000])
            return 2

    out = Path(args.out) / "actor_proposals" / f"scene_{idx:03d}_{args.character}.json"
    _dump_json({
        "meta": {"scene_index": idx, "scene_title": scene.title,
                 "character": args.character, "adapter": adapter.describe()},
        "proposals": proposals,
    }, out)
    print(f"✓ 角色行动提议 → {out}"
          f"（{adapter.describe()}｜epistemic sandbox: {args.character}）")
    for p in proposals:
        a = "、".join(p.get("args", []))
        print(f"  - {p.get('action')}({a})｜{p.get('reason', '')}")
    print("  （脚本模式仍是唯一真值源：确认后将行动写回 .npl 的 events）")
    return 0


# ---------------------------------------------------------------- diff
def _set_diff(prefix, prev_list, cur_list):
    prev, cur = set(prev_list), set(cur_list)
    out = []
    for x in sorted(cur - prev):
        out.append(f"{prefix}: + {x}")
    for x in sorted(prev - cur):
        out.append(f"{prefix}: - {x}")
    return out


def _diff_states(prev, cur):
    lines = []
    # world facts
    for k in sorted(set(prev["world"]["facts"]) | set(cur["world"]["facts"])):
        a = prev["world"]["facts"].get(k)
        b = cur["world"]["facts"].get(k)
        if a != b:
            lines.append(f"world.fact {k}: {a} -> {b}")
    # characters
    for name in sorted(cur["characters"]):
        pc = prev["characters"].get(name, {})
        cc = cur["characters"][name]
        for field in ("knows", "believes", "intends", "goals", "hides"):
            lines += _set_diff(f"{name}.{field}", pc.get(field, []), cc[field])
        lines += _set_diff(
            f"{name}.suspects",
            [f"{k}({v})" for k, v in sorted(pc.get("suspects", {}).items())],
            [f"{k}({v})" for k, v in sorted(cc["suspects"].items())])
        pa = (pc.get("arc") or {}).get("current")
        ca = (cc.get("arc") or {}).get("current")
        if pa != ca and ca:
            lines.append(f"{name}.arc.current: {pa if pa else '∅'} -> {ca}")
        for dim in sorted(set(pc.get("emotion", {})) | set(cc.get("emotion", {}))):
            a = pc.get("emotion", {}).get(dim)
            b = cc.get("emotion", {}).get(dim)
            if a != b:
                lines.append(f"{name}.emotion.{dim}: {a} -> {b}")
    # narrative
    for field in ("reader_knows", "conceal_active", "revealed",
                  "suspicions", "unanswered_questions"):
        lines += _set_diff(f"narrative.{field}",
                           prev["narrative"].get(field, []),
                           cur["narrative"][field])
    return lines


def cmd_diff(args):
    program, _ = _load_and_validate(args.file)
    if program is None:
        return 1
    result = simulate(program)
    total = len(result.snapshots)
    idx = args.scene if args.scene else total
    if not (1 <= idx <= total):
        print(f"✗ 场景编号越界: {idx}（共 {total} 幕）")
        return 2
    prev = (result.snapshots[idx - 2]["state"] if idx >= 2
            else RuntimeState.from_program(program).to_dict())
    cur = result.snapshots[idx - 1]["state"]
    title = result.snapshots[idx - 1]["meta"]["scene_title"]
    base = "初始状态" if idx == 1 else f"第 {idx - 1} 幕后"
    print(f"第 {idx} 幕「{title}」状态变更（相对{base}）:")
    changes = _diff_states(prev, cur)
    if not changes:
        print("  （无状态变化）")
    for ln in changes:
        print(f"  {ln}")
    return 0


# ---------------------------------------------------------------- motifs
def _motifs_single(file: str, args):
    """单章模式（v0.2 兼容）：一个 .npl + 一个 prose 目录。"""
    program, _ = _load_and_validate(file)
    if program is None:
        return 1
    from .analysis.imagery import extract_candidates

    prose_dir = Path(args.prose_dir) if args.prose_dir else Path("build/prose")
    scene_texts = {}
    for idx, scene in enumerate(program.scenes, 1):
        path = prose_dir / f"scene_{idx:03d}.md"
        if not path.is_file():
            print(f"✗ 缺少散文文件: {path}（先运行 npl render，或用 --prose-dir 指定）")
            return 2
        text = path.read_text(encoding="utf-8")
        # 去掉 render 写入的 <!-- ... --> 头注释，避免污染统计
        text = re.sub(r"<!--.*?-->\s*", "", text, flags=re.S)
        scene_texts[f"[{idx}] {scene.title}"] = text

    candidates = extract_candidates(scene_texts, min_scenes=args.min_scenes)
    declared = {m.motif for scene in program.scenes for m in scene.motifs}

    print(f"意象聚类（{len(scene_texts)} 幕，阈值：出现 ≥{args.min_scenes} 幕）:")
    if not candidates:
        print("  （未发现跨幕重复意象）")
    for c in candidates:
        dist = "、".join(f"{name}×{n}" for name, n in c["scenes"].items())
        members = "/".join(c["members"][:6]) + ("…" if len(c["members"]) > 6 else "")
        hit = "★已声明" if c["label"] in declared else ""
        print(f"  {c['label']}  {hit}")
        print(f"    词族: {members}")
        print(f"    分布: {dist}（共 {c['total']} 次）")

    uncovered = declared - {c["label"] for c in candidates}
    if uncovered:
        print(f"⚠ 已声明但未在散文中聚出的母题: {'、'.join(sorted(uncovered))}"
              f"（抽取口径不同或词频不足；check 的 NAR-064 为准）")
    return 0


def cmd_motifs(args):
    """npl motifs：单章传 .npl 文件（v0.2）；跨章追踪传各章目录（v0.3）。"""
    paths = [Path(p) for p in args.paths]
    if len(paths) == 1 and paths[0].is_file():
        return _motifs_single(str(paths[0]), args)
    from .analysis.tracking import render_track_report, report_to_json, track_motifs

    chapters, declared = {}, {}
    for d in paths:
        if not d.is_dir():
            print(f"✗ 不是目录：{d}（跨章追踪传各章目录；单章分析传 .npl 文件）")
            return 2
        npl_files = sorted(d.glob("*.npl"))
        if len(npl_files) != 1:
            print(f"✗ {d} 顶层应有且仅有一个 .npl 文件（找到 {len(npl_files)} 个）")
            return 2
        program, _ = _load_and_validate(str(npl_files[0]))
        if program is None:
            return 1
        prose_dir = d / "build" / "prose"
        scenes = []
        for idx, scene in enumerate(program.scenes, 1):
            p = prose_dir / f"scene_{idx:03d}.md"
            if not p.is_file():
                print(f"✗ 缺少散文文件: {p}（先对该章运行 npl render）")
                return 2
            text = re.sub(r"<!--.*?-->\s*", "", p.read_text(encoding="utf-8"),
                          flags=re.S)
            scenes.append((f"[{idx}] {scene.title}", text))
        chapters[d.name] = scenes
        declared[d.name] = {m.motif for s in program.scenes for m in s.motifs}

    if len(chapters) < 2:
        print("⚠ 跨章追踪至少需要 2 个章节目录（单章分析请传 .npl 文件）")
        return 2

    report = track_motifs(chapters, declared=declared,
                          min_scenes=args.min_scenes, gap_alert=args.gap_alert)
    if args.json:
        print(report_to_json(report))
    else:
        print("\n".join(render_track_report(report)))
        covered = set()
        for m in report["motifs"]:
            covered |= set(m["members"]) | {m["label"]}
        all_declared = set().union(*declared.values()) if declared else set()
        uncovered = all_declared - covered
        if uncovered:
            print(f"⚠ 已声明但未被轨迹聚出的母题: {'、'.join(sorted(uncovered))}"
                  f"（单章 check 的 NAR-064 为准）")
    return 0


# ---------------------------------------------------------------- style
def _collect_corpus(paths):
    files = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(
                x for x in p.rglob("*")
                if x.suffix.lower() in (".txt", ".md") and not x.name.startswith(".")
            ))
        elif p.is_file():
            files.append(p)
        else:
            print(f"✗ 语料路径不存在: {raw}")
            return None
    if not files:
        print("✗ 未收集到语料文件（.txt/.md）")
        return None
    return [f.read_text(encoding="utf-8-sig") for f in files]


def cmd_style_fingerprint(args):
    from .style.fingerprint import corpus_fingerprint

    texts = _collect_corpus(args.corpus)
    if texts is None:
        return 2
    names = ([s.strip() for s in args.features.split(",") if s.strip()]
             if args.features else None)
    try:
        fp = corpus_fingerprint(texts, feature_names=names)
    except KeyError as e:
        print(f"✗ {e}")
        return 2
    payload = json.dumps(fp, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
        print(f"✓ 指纹已写入 {out}")
        for k, v in fp["features"].items():
            print(f"  {k} = {v}")
    else:
        print(payload)
    return 0


def cmd_style_show(args):
    from .style.fingerprint import load_fingerprint

    fp = load_fingerprint(args.fingerprint)
    meta = fp.get("meta", {})
    print(f"指纹 {args.fingerprint}")
    print(f"  版本: fingerprint={fp.get('fingerprint_version')} "
          f"feature_set={fp.get('feature_set_version')} "
          f"lexicon={meta.get('lexicon_digest')}")
    print(f"  语料: {meta.get('n_texts')} 篇 / {meta.get('n_chars')} 字 / "
          f"{meta.get('n_sentences')} 句")
    for k, v in fp["features"].items():
        print(f"  {k} = {v}")
    return 0


def cmd_style_to_npl(args):
    from .style.fingerprint import load_fingerprint, to_style_decl, render_style_npl

    fp = load_fingerprint(args.fingerprint)
    decl = to_style_decl(fp)
    print(render_style_npl(args.key, decl, args.desc))
    return 0


def cmd_style_diff(args):
    from .style.fingerprint import load_fingerprint, diff

    da = load_fingerprint(args.fingerprint_a)
    db = load_fingerprint(args.fingerprint_b)
    print(f"风格指纹对比  A={args.fingerprint_a}")
    print(f"              B={args.fingerprint_b}")
    for name, r in diff(da, db).items():
        if r["delta"] is None:
            print(f"  {name}: A={r['a']}  B={r['b']}")
            continue
        arrow = "↑" if r["delta"] > 0 else ("↓" if r["delta"] < 0 else "→")
        print(f"  {name}: A={r['a']}  B={r['b']}  {arrow} {r['delta']:+}")
    return 0


# ---------------------------------------------------------------- main
def main(argv=None):
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="npl", description="NPL 叙事编程系统")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="语法 + 语义校验")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("simulate", help="确定性模拟 → 快照 + IR")
    p.add_argument("file")
    p.add_argument("--out", default="build", help="构建输出目录（默认 build）")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("continue", help="从快照续跑追加场景（快照续跑/分支，v0.3）")
    p.add_argument("file", help="追加场景的 .npl 程序（须复用基程序的世界与人物）")
    p.add_argument("--from", dest="snapshot", required=True,
                   help="基程序的场景快照 JSON（build/state_snapshots/scene_XXX.json）")
    p.add_argument("--out", default="build/continue", help="续跑输出目录")
    p.set_defaults(func=cmd_continue)

    p = sub.add_parser("branch-diff", help="对比两个快照的完整状态差异（分支对比，v0.3）")
    p.add_argument("snapshot_a")
    p.add_argument("snapshot_b")
    p.set_defaults(func=cmd_branch_diff)

    p = sub.add_parser("render", help="场景渲染（默认 mock；真实 LLM 需 npl.config.json）")
    p.add_argument("file")
    p.add_argument("--scene", type=int, default=None, help="渲染指定幕（1 起）；缺省全部")
    p.add_argument("--adapter", default=None, help="覆盖配置中的适配器（如 mock/deepseek）")
    p.add_argument("--config", default=None, help="配置文件路径（默认 ./npl.config.json）")
    p.add_argument("--out", default="build")
    p.add_argument("--stdout", action="store_true", help="同时打印正文")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("inspect", help="查询角色认知状态 / Reader Model")
    p.add_argument("file")
    p.add_argument("--character", default=None)
    p.add_argument("--scene", type=int, default=None, help="查看第 N 幕后（默认末幕）")
    p.add_argument("--reader", action="store_true", help="输出 Reader Model 视图（M3）")
    p.add_argument("--deep", action="store_true",
                   help="对深层嵌套认知做逐层接地验证（v0.3，基础命题近似）")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("actor", help="LLM Actor 模式：epistemic sandbox 行动提议（M3）")
    p.add_argument("file")
    p.add_argument("--character", required=True, help="决策角色")
    p.add_argument("--scene", type=int, default=None, help="第 N 幕（默认第 1 幕）")
    p.add_argument("--adapter", default=None)
    p.add_argument("--config", default=None)
    p.add_argument("--out", default="build")
    p.set_defaults(func=cmd_actor)

    p = sub.add_parser("check", help="认知泄漏检查（LLM 命题抽取 + 规则引擎）")
    p.add_argument("file")
    p.add_argument("--scene", type=int, default=None, help="指定 --prose 对应的幕号")
    p.add_argument("--prose", default=None, help="检查指定散文文件（默认 build/prose/ 各幕）")
    p.add_argument("--adapter", default=None, help="覆盖 extract 适配器")
    p.add_argument("--config", default=None)
    p.add_argument("--out", default="build")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("diff", help="相邻状态快照 diff（这一幕改变了什么）")
    p.add_argument("file")
    p.add_argument("--scene", type=int, default=None, help="第 N 幕（默认末幕）")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("motifs",
                       help="母题分析：单章传 .npl（聚类）；跨章传目录列表（长程追踪）")
    p.add_argument("paths", nargs="+", help=".npl 文件（单章）或章节目录（跨章追踪）")
    p.add_argument("--prose-dir", default=None,
                   help="散文目录（仅单章模式，默认 build/prose/）")
    p.add_argument("--min-scenes", type=int, default=2,
                   help="候选母题最少出现的场景数（默认 2）")
    p.add_argument("--gap-alert", type=int, default=2,
                   help="断线/间歇预警的间隔章数（默认 2，仅跨章模式）")
    p.add_argument("--json", action="store_true",
                   help="跨章模式输出 JSON 报告")
    p.set_defaults(func=cmd_motifs)

    p = sub.add_parser("style", help="语料风格指纹（v0.2）")
    style_sub = p.add_subparsers(dest="style_command", required=True)

    sp = style_sub.add_parser("fingerprint", help="对语料计算风格指纹 JSON")
    sp.add_argument("corpus", nargs="+",
                    help="语料文件（.txt/.md，可多个；目录则递归收集）")
    sp.add_argument("--out", default=None, help="指纹输出路径（缺省打印）")
    sp.add_argument("--features", default=None,
                    help="逗号分隔的特征名（缺省全部已注册特征）")
    sp.set_defaults(func=cmd_style_fingerprint)

    sp = style_sub.add_parser("show", help="查看指纹文件")
    sp.add_argument("fingerprint")
    sp.set_defaults(func=cmd_style_show)

    sp = style_sub.add_parser("to-npl", help="指纹 → .npl style 块文本")
    sp.add_argument("fingerprint")
    sp.add_argument("--key", required=True, help="style 名（标识符）")
    sp.add_argument("--desc", default="", help="style desc 描述")
    sp.set_defaults(func=cmd_style_to_npl)

    sp = style_sub.add_parser("diff", help="对比两个风格指纹")
    sp.add_argument("fingerprint_a")
    sp.add_argument("fingerprint_b")
    sp.set_defaults(func=cmd_style_diff)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
