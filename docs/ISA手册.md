# NPL 认知指令集手册（ISA）

**版本：ISA v0.4**（随语言版本演进；本文描述 `npl@0.2` + v0.3/v0.4 运行时）
**权威链**：本文是对 `src/npl/runtime/executor.py` 与 `src/npl/runtime/state.py`
中已实现语义的规范描述。实现与本文冲突时，以测试通过的实现为准并回改本文。

---

## 1. 定位

NPL 的事件动词是一套**认知指令集**：程序作者用它们声明"这一幕谁的心智发生了
什么变化"。世界机（executor）是唯一执行者；LLM 渲染层只是这些指令的认知投影，
**不是**权威。理解 ISA 就能不看代码地预测 `npl simulate` 的全部行为。

## 2. 指令的两条通道

| 通道 | 语法位置 | 语义强度 | 说明 |
|---|---|---|---|
| `information_changes` | scene 块内 | **正式状态转换** | 全部五族动词都生效 |
| `events` | scene 块内 | 叙事节拍 | 仅 HIDE、SUSPECT 族生效；其余动词执行为无操作的节拍（用于保持叙事节奏） |

**设计依据**：events 描述"读者看得见的行为"，information_changes 描述"世界
认知状态的跃迁"。举手投足是节拍，心事转变是转换。

## 3. 认知动词族（五族）

### 3.1 CONFIRM 族 —— 获知
- 动词：`confirms discovers learns realizes remembers infers notices finds`
- 语法：`A.discovers(x)`；嵌套形式见 §4
- 状态效应：`A.knows += x`（若 x 是世界事实，此后 A 的认知与真值一致）
- 读者效应：无直接效应（除非配合 dramatic_goal reveal）

### 3.2 REVEAL 族 —— 公开
- 动词：`reveals tells admits confesses discloses`
- 语法：`A.tells(x)`
- 状态效应：**广播**——`participants` 中每个人的 `knows += x`
  （REVEAL 是唯一改变他人认知的动词族）
- 语义要点：公开即"在场人人皆知"；不在场者不受影响

### 3.3 MISUNDERSTAND 族 —— 误信
- 动词：`misunderstands mistakes`
- 语法：`B.misunderstands(x)`
- 状态效应：`A.believes += x`（**不入 knows**——即使世界真值为假也采信；
  这是"错误信念"的唯一入口）
- 典型用法：配合 `fact x = false` 的接地事实，inspect 会标注"虚假信念"

### 3.4 SUSPECT 族 —— 怀疑
- 动词：`suspects doubts`
- 语法：`A.suspects(x)` 或 `A.suspects(x) (0.7)`（置信度 0~1，缺省 0.6）
- 状态效应：`A.suspects[x] = max(旧值, 新值)`（只升不降）
- 读者效应：POV 的怀疑并入 `narrative.suspicions`（读者随之起疑）

### 3.5 HIDE 族 —— 隐藏
- 动词：`hides conceals withholds`
- 语法：`A.hides(x)`
- 状态效应：`A.hides += x`
- 读者效应：**隐藏行为天然可观察**——读者看到 A 在藏，于是
  `narrative.suspicions += x` 且生成未答之问 `"{A} 在隐瞒 {x} 的什么？"`
  （注意：读者起疑 ≠ 读者知情；x 的内容仍在 conceal 边界内）

### 3.6 WORLD 族 —— 物理事实变更（v0.4）

- 动词：`sets`（置真）、`clears`（置假）
- 语法：`主体.sets(事实id)`；主体可为**已声明实体**（`灵脉.sets(裂痕)`）
  或人物（`老祭司.clears(外泄)`）——实体主体无需入 participants
- 状态效应：`world.facts[事实id] = true/false`（**物理层**，不触碰任何
  人物认知）
- 两通道均生效（世界变迁是正式状态转换，无论写在哪条通道）
- 参数必须是已声明世界事实（NAR-002）；不接受嵌套参数
- **观察传播是显式的**：世界变了不等于有人知道——谁看见、谁起疑，
  由作者用 CONFIRM/SUSPECT 显式声明（认知账目哲学：无隐式传播）

## 4. 嵌套参数（对他人心智的建模）

- 语法：`A.realizes(B.knows(x))`、`A.realizes(B.does_not_know(x))`、
  `A.realizes(B.believes(x))`；v0.2 起支持任意深度 `A.realizes(B.knows(C.believes(x)))`
- 生效范围：**仅 CONFIRM 族**（获知一个关于他人心智的命题，也是获知）
- 一层嵌套：入 `A.believes_about[B]`（knows/does_not_know 互斥更新）
- 深层嵌套：以规范化字符串入 `A.nested_beliefs`
  （canonical：`B|knows>C|believes>x`）
- **运行时验证深度 = 1**（深层只存储、展示；可选的 `inspect --deep` 提供
  基础命题近似的逐层接地，见计算模型.md）
- events 通道中嵌套参数一律跳过（嵌套是纯心智事件，不是可观察行为）

## 5. access 权限（渲染边界，非状态语义）

无 access 块时的缺省策略（语言规范 §4.4）：

- 允许：POV 的 `perception / memory / inference`
- 拒绝：其他在场者的 `private_thought`、`world.truth`

access 只约束**渲染投影**（LLM 能看到什么），不改变 simulate 的状态演化。
显式 `access` 块可覆盖（如戏剧反讽场景允许叙述者知道 POV 不知道的事）。

## 6. 叙事指令（scene 块的文学原语状态效应）

| 指令 | 状态效应 |
|---|---|
| `dramatic_goal reveal = x` | `reader_knows/revealed += x`；解除 x 的 conceal 与 misdirect；回收含 x 的未答之问 |
| `dramatic_goal conceal = x` | `conceal_active += x`；生成未答之问；**已揭示的目标不回退** |
| `motifs`（introduce/recurrence/final） | `narrative.motifs[id] += {role, scene}`（仅记录，不改认知） |
| `withholds { x until = N }` | 立即入 `conceal_active`；**第 N 幕开头自动解除**（跨幕 pending 队列） |
| `misdirects { x }` | `misdirects_active += x`；`suspicions += x`（读者被引向该方向）；reveal x 时反转解除 |

## 7. Reader Model 逐幕更新（确定性）

每幕末尾按序执行：
1. POV 的全部怀疑 → `narrative.suspicions`
2. 本幕观察到的隐藏行为 → `suspicions += prop` + 未答之问
3. dramatic_goal 的 reveal/conceal（§6）

读者模型的三个字段（`reader_knows / suspicions / unanswered_questions`）
是 conceal/reveal 节奏检查（NAR-031/032/066）的数据基础。

## 8. 确定性协议

- 事件应用顺序 = 声明顺序（information_changes 先于 events）
- 无随机数、无时钟、无外部输入；快照序列化排序（sorted）
- 同一程序 → 逐字节一致的时间线；`simulate_continue(state, scenes, n)`
  同样确定（快照读档 = 确定性分叉）

## 9. 静默行为表（作者易踩的坑）

| 写法 | 实际行为 |
|---|---|
| events 里写 `A.realizes(x)` 等非 HIDE/SUSPECT 动词 | 静默节拍（无状态变化）——**这是特性不是 bug**，节拍用于叙事节奏 |
| 拼错的动词（如 `reveals_to_all`） | 静默节拍（validator 不查动词拼写） |
| 动词作用在快照中不存在的人物（continue 场景） | CLI 层拒绝（exit 1）；executor 层 no-op |
| conceal 一个已 reveal 的目标 | 忽略（不回退） |
| suspect 同一命题两次 | 取更高置信度 |

## 10. WORLD 族与题材包（v0.4 已实现）

世界动力学由 WORLD 族动词（§3.6）承担：物理事实与认知状态彻底分层——
`灵脉.sets(裂痕已现)` 只改世界；`阿岩.notices(裂痕已现)` 才改认知。
两者在 .npl 中成对显式出现，世界机不做任何隐式推断。

**多阶段世界进程（process 声明）**：世界块内可声明进程（如灵脉坍塌的
四个阶段），每个阶段绑定一个标志事实。运行时事实仍由 WORLD 族显式驱动；
`npl simulate` 末尾按声明序做**单调性检查**——后阶段为真而前置未真
（阶段乱序）打印告警。进程是声明式知识：给检查器、题材包复用与
ISA 手册一个可读的世界动力学骨架。

**题材包（genre pack）模式**：把世界事实/实体/进程装进一个可 import 的
.npl（不装人物、场景、文风），故事程序首行 `import "包.npl"` 即获得
整个世界的物理与历史。示例：`examples/packs/northern_veins/`。

## 11. 演进规则（如何新增动词族）

1. `executor.py`：定义 `XXX_VERBS` 集合 + `_apply_change` 分支
2. `state.py`：对应状态方法（保持"只升不降/互斥"等单调性约定）
3. `validator.py`：如需静态校验则加 NAR-0xx 码
4. 测试：状态效应 + 读者效应 + 静默行为三面
5. 本手册升版（ISA v0.x → v0.x+1），语言规范 §5/附录 A 同步
6. **兼容性承诺**：既有动词族语义永不改动，只增不改——旧程序在新版
   运行时上必须产生逐字节一致的快照

### 规则层（远期预留）

`when fact X becomes true → fact Y becomes true` 的声明式因果引擎。
当前不做：所有因果关系由作者以 WORLD 族动词显式声明，保持"无隐式
状态转换"的世界机哲学。

