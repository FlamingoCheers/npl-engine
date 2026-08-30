"""渲染器：Context → prompts → adapter → 散文。"""
from ..context.compiler import compile_render_context
from . import prompts


def render_scene(state, scene, ir, style_name, adapter, descriptions=None,
                 style_decls=()):
    """渲染单个场景，返回 (prose, context)。

    descriptions: collect_descriptions(program) 的产物（可选）。
    传入后 prompt 层获得语义描述，模型不再面对裸 id。
    style_decls: 程序内 style 块（覆盖预设参数）。
    """
    ctx = compile_render_context(state, scene, ir, style_name, descriptions,
                                 style_decls)
    system = prompts.build_system_prompt(ctx, ctx["style"])
    user = prompts.build_user_prompt(ctx)
    prose = adapter.chat(system, user)
    return prose, ctx
