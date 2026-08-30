"""NPL AST 节点定义。所有节点携带行号（line）用于诊断定位。"""
from dataclasses import dataclass, field


@dataclass
class Prop:
    """通用命名项（认知小节条目 / 列表成员）"""
    name: str
    line: int
    desc: str = None


@dataclass
class FactItem:
    """world 内的 fact 声明（STATE 原语）。desc 来自行尾注释（语义描述）。

    v0.2：value 支持 布尔 / 数字 / 枚举标识符，vkind 标记类型（bool/num/enum）。
    """
    name: str
    value: object
    line: int
    desc: str = None
    vkind: str = "bool"            # "bool" | "num" | "enum"


@dataclass
class EntityDecl:
    """ENTITY 原语：world 内实体。"""
    name: str
    line: int
    attrs: dict = field(default_factory=dict)


@dataclass
class ProcessStage:
    """v0.4：进程阶段 —— 阶段名 + 标志性事实（该阶段为真的标志）。"""
    name: str
    fact: str
    line: int
    desc: str = None


@dataclass
class ProcessDecl:
    """v0.4：多阶段世界进程（灵脉坍塌 / 战争升级 / 季节轮转）。

    声明式知识：按序列出各阶段的标志事实。运行时事实仍由 WORLD 族动词
    （sets/clears）显式驱动；simulate 末尾按阶段序校验真值单调性（乱序告警）。
    """
    name: str
    line: int
    stages: list = field(default_factory=list)      # list[ProcessStage]
    desc: str = None


@dataclass
class WorldDecl:
    """WORLD 原语：世界声明块。"""
    name: str
    line: int
    locations: list = field(default_factory=list)   # list[Prop]
    time: str = None                                # 世界基准时间戳
    facts: list = field(default_factory=list)       # list[FactItem]
    entities: list = field(default_factory=list)    # list[EntityDecl]
    processes: list = field(default_factory=list)   # v0.4 list[ProcessDecl]


@dataclass
class Trait:
    """慢/快变量条目：personality / emotion。"""
    name: str
    value: float
    line: int


@dataclass
class CharacterDecl:
    """CHARACTER 原语：人物声明块。desc 来自块首行尾注释（身份/角色）。"""
    name: str
    line: int
    desc: str = None
    knows: list = field(default_factory=list)          # list[Prop | NestedBelief]
    believes: list = field(default_factory=list)       # list[Prop | NestedBelief]
    suspects: list = field(default_factory=list)       # list[Suspect]（默认置信度 0.5）
    does_not_know: list = field(default_factory=list)  # list[Prop]
    intends: list = field(default_factory=list)        # list[Prop]
    goal: list = field(default_factory=list)           # list[Prop]
    personality: list = field(default_factory=list)    # list[Trait] 慢变量
    emotion: list = field(default_factory=list)        # list[Trait] 快变量


@dataclass
class Suspect:
    name: str
    confidence: float
    line: int


@dataclass
class NestedBelief:
    """嵌套认知条目（M3 一层，v0.2 递归多层）。

    `believes: Bao.knows(x)`            → path=[("Bao","knows")], prop="x"
    `believes: A.believes(B.knows(x))`  → path=[("A","believes"),("B","knows")], prop="x"
    """
    path: list                    # list[tuple[str, str]]  (holder, verb) 由外向内
    prop: str                     # 最内层命题 id
    line: int
    desc: str = None

    @property
    def holder(self) -> str:
        """最外层被建模心智的人物 id（向后兼容一层形式）。"""
        return self.path[0][0]

    @property
    def verb(self) -> str:
        return self.path[0][1]

    def canonical(self) -> str:
        """确定性序列化：holder|verb>holder|verb>prop。"""
        head = ">".join(f"{h}|{v}" for h, v in self.path)
        return f"{head}>{self.prop}"

    def display(self) -> str:
        """人类可读形式：A.believes(B.knows(x))。"""
        inner = self.prop
        for holder, verb in reversed(self.path):
            inner = f"{holder}.{verb}({inner})"
        return inner


@dataclass
class InformationDecl:
    """Information Object：信息一等公民。desc 来自块首行尾注释。"""
    name: str
    line: int
    desc: str = None
    truth: str = None            # 必填：指向 world.fact 的 id
    truth_line: int = 0
    known_by: list = field(default_factory=list)      # list[Prop]
    unknown_to: list = field(default_factory=list)    # list[Prop]
    suspected_by: list = field(default_factory=list)  # list[Suspect]
    public: bool = False


@dataclass
class AccessRule:
    """POV 权限规则：allow/deny = 主体.能力。desc 来自行尾注释。"""
    kind: str          # "allow" | "deny"
    subject: str       # 人物 id 或 "world"
    capability: str    # perception/memory/inference/private_thought/emotion/intention 或 truth
    line: int
    desc: str = None


@dataclass
class EventRef:
    """事件引用：Actor.action(args)。desc 来自行尾注释。"""
    actor: str
    action: str
    args: list = field(default_factory=list)
    line: int = 0
    desc: str = None


@dataclass
class GoalItem:
    """叙事意图：reveal/conceal = 目标。desc 来自行尾注释。"""
    kind: str      # "reveal" | "conceal"
    target: str    # information id 或 fact id
    line: int
    desc: str = None


@dataclass
class ArcEntry:
    """情绪轨迹：人物: 状态 -> 状态 -> ...。desc 来自行尾注释。"""
    character: str
    states: list = field(default_factory=list)
    line: int = 0
    desc: str = None


@dataclass
class SceneDecl:
    """SCENE 原语：场景块。"""
    title: str
    line: int
    pov: str = None
    pov_line: int = 0
    location: str = None
    world_time: str = None
    flashback: bool = False   # M3：倒叙场景（narrative_order ≠ world_time）
    participants: list = field(default_factory=list)       # list[Prop]
    access: list = field(default_factory=list)             # list[AccessRule]
    events: list = field(default_factory=list)             # list[EventRef]
    information_changes: list = field(default_factory=list)  # list[EventRef]
    dramatic_goal: list = field(default_factory=list)      # list[GoalItem]
    emotional_arc: list = field(default_factory=list)      # list[ArcEntry]
    motifs: list = field(default_factory=list)             # M4 list[MotifRef]
    foreshadows: list = field(default_factory=list)        # M4 list[LiteraryRef]
    withholds: list = field(default_factory=list)          # M4 list[WithholdRef]
    misdirects: list = field(default_factory=list)         # M4 list[LiteraryRef]


@dataclass
class MotifRef:
    """M4 母题引用：motifs { id = introduce|recurrence|final }。"""
    motif: str
    role: str      # introduce | recurrence | final
    line: int
    desc: str = None


@dataclass
class LiteraryRef:
    """M4 foreshadow / misdirect 引用：目标 fact/information id，desc 来自行尾注释。"""
    target: str
    line: int
    desc: str = None


@dataclass
class WithholdRef:
    """M4 withhold：限时隐藏，until = 第 N 幕释放。"""
    target: str
    until: int
    line: int
    desc: str = None


@dataclass
class StyleDecl:
    """M4 STYLE 原语：文件内风格定义，字段并入同名命名预设。

    数值/开关字段编译为文本规则追加进渲染 prompt；
    rule = "..." 提供自由文本规则（可重复）。
    """
    key: str
    line: int
    desc: str = None
    sentence_max: float = None     # 平均句长上限（字）
    emotion_naming: str = None     # forbid | allow
    sensory: str = None            # low | mid | high
    dialogue_gaps: bool = None     # 对话留白
    rules: list = field(default_factory=list)   # list[str] 自由规则


@dataclass
class RenderDecl:
    """RENDER 原语：渲染配置块。"""
    line: int
    style: str = "default"
    language: str = "zh"


@dataclass
class ImportDecl:
    """v0.2：import "相对路径.npl" —— 多文件程序。行尾注释可作用途说明。"""
    path: str
    line: int
    desc: str = None


@dataclass
class Program:
    """叙事程序顶层节点。"""
    version: str
    world: WorldDecl = None
    characters: list = field(default_factory=list)      # list[CharacterDecl]
    informations: list = field(default_factory=list)    # list[InformationDecl]
    scenes: list = field(default_factory=list)          # list[SceneDecl]
    render: RenderDecl = None
    styles: list = field(default_factory=list)          # M4 list[StyleDecl]
    imports: list = field(default_factory=list)         # v0.2 list[ImportDecl]（仅入口文件填充）
    source_files: list = field(default_factory=list)    # v0.2 参与合并的文件路径（有序）


import re as _re
NESTED_HEAD_RE = _re.compile(r"^([^\s.]+)\.(knows|does_not_know|believes)\((.*)\)$")


def parse_nested_arg(arg):
    """'B.knows(x)' / 'A.believes(B.knows(x))' → (path, prop)；非嵌套返回 None。

    path = [(holder, verb), ...] 由外向内（v0.2 递归多层）。
    """
    path = []
    cur = arg.strip()
    while True:
        m = NESTED_HEAD_RE.match(cur)
        if not m:
            break
        path.append((m.group(1), m.group(2)))
        cur = m.group(3)
    if not path:
        return None
    if "(" in cur or ")" in cur:
        return None   # 括号不平衡等畸形输入：按不透明字符串处理
    return path, cur
