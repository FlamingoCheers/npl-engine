# NPL — 叙事编程系统

**叙事即程序**：把小说写成"认知状态机"，正文只是状态机的投影。

NPL 是一门面向叙事的领域语言与其世界机引擎。作者用 `.npl` 声明世界事实、
人物认知与每幕的信息目标（reveal / conceal），引擎确定性推演出认知状态快照，
渲染层把"某一人物视角下的世界"交给 LLM 投影成散文，检查器再对照快照
审计散文是否泄漏了人物不该知道的事。

```
.npl 程序 ──validate──▶ AST + 诊断（NAR-0xx）
        └─simulate──▶ 确定性认知快照序列（MD5 可复现）
                      │
                      ├─render──▶ LLM 投影散文（限视角，信息边界编译进 prompt）
                      ├─inspect──▶ 任意人物/任意时点/Reader Model 认知查询
                      └─check───▶ 泄漏审计（NAR-021/022/031/032/051…）
```

## ⚠️ 重要声明

**本系统所有渲染产出的结果只是初级的渲染结果，并不是小说成文，成文需要后期的创作。**
本系统只是**协助 AI 进行文学创作的中间件**，目的在于解决一般用大纲、世界观、
人设文档作为背景提示时的**注意力偏移**与**超长上下文**问题——把"谁知道了什么、
要向读者揭示/隐瞒什么"编译成可校验的状态，而不是生成终稿。

## 快速开始

```bash
pip install -e .            # 或 pip install jieba 后 python -m pip install -e .
npl validate examples/station/station.npl
npl simulate examples/novel/chapter_one.npl --out build
npl inspect  examples/novel/chapter_one.npl --character Bao --scene 5
npl check    examples/novel/chapter_one.npl --adapter mock   # 离线
npl motifs   第1章 第2章                                     # 跨章母题追踪
npl style fingerprint 语料/*.md --out my_style.json          # 语料风格指纹
```

## 命令一览

| 命令 | 作用 |
| --- | --- |
| `validate` | 语法/语义校验（NAR-0xx 诊断码） |
| `simulate` | 确定性模拟 → 认知快照 + 场景 IR |
| `continue` | 从任一快照续跑追加场景（分支时间线） |
| `branch-diff` | 两条时间线快照的全量状态对比 |
| `render` | 幕 → LLM 散文（mock 适配器离线可跑） |
| `inspect` | 人物/读者认知视图，`--deep` 深层嵌套接地 |
| `check` | 散文泄漏审计（对照快照） |
| `diff` | 相邻两幕状态差异 |
| `motifs` | 意象聚类 / 跨章母题追踪（断线告警） |
| `actor` | Actor 模式：角色在认知沙箱内提议行动 |
| `style` | 语料风格指纹：fingerprint / show / to-npl / diff |

## 文档

- `docs/语言规范.md` — 语法（EBNF）、错误码、保留字
- `docs/计算模型.md` — 世界机语义：认知状态、信息流转、Reader Model、
  快照续跑、风格指纹、世界动力学
- `docs/ISA手册.md` — 指令集规范（ISA v0.4）：动词族语义、确定性协议、
  兼容性承诺（外围系统按此对接）
- `项目规划.md` — 路线图与各版本验收记录

## 设计原则

1. **运行时是唯一事实源**——散文是投影，不是权威；一切可审计。
2. **认知账目无隐式状态转换**——信息只通过显式动词流转，世界机零隐藏行为。
3. **确定性优先**——同一程序 + 同一状态 = 逐字节一致的快照。
4. **LLM 是打印机，不是世界**——信息边界在编译期定死，不由模型自觉。

## 依赖

内核零必需依赖（纯标准库）。`jieba` 为可选增强（`pip install npl-engine[nlp]`），
缺失时意象/母题分析自动回退 CJK bigram。

## License

MIT
