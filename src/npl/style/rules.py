"""风格系统（M4）：命名预设 + 文件内 style 声明 → 渲染约束。

M4 扩展：语料库 → 文学特征提取 → Style Model（预留接口，见 extract接口 note）。
"""


STYLE_PRESETS = {
    "default": {
        "key": "default",
        "name": "默认文学",
        "description": "自然、克制的现代中文小说叙述",
        "rules": [
            "第三人称限制视角",
            "情绪优先通过动作与感官细节呈现",
            "避免堆砌形容词，避免议论",
        ],
    },
    "restrained_literary": {
        "key": "restrained_literary",
        "name": "克制文学",
        "description": "冰山笔法：短句为主，情绪全部藏进动作与感官细节，杜绝抒情议论",
        "rules": [
            "句子简短，节奏克制，多用句号",
            "禁止直接命名情绪（不写\"她很悲伤\"，写她做了什么、碰到什么）",
            "对话简省，留白多于解释",
            "感官细节具体（声音、气味、触感、光线、温度）",
            "禁止议论、抒情与心理概括",
        ],
    },
    "lush_emotion": {
        "key": "lush_emotion",
        "name": "浓郁抒情",
        "description": "情感浓烈、句子绵长、比喻繁密的抒情笔法，与克制文学形成对照",
        "rules": [
            "句子绵长舒展，允许从句与排比，节奏流动",
            "鼓励比喻与意象叠加，每段至少一处明确的比喻",
            "可以直接命名与描写情绪（\"她感到一阵酸楚\"式），内心独白充分展开",
            "感官描写浓烈：色彩、气味、声音的渲染要饱满",
            "允许适度的抒情议论，但须附着在具体意象上",
        ],
    },
}

# 语料风格特征提取预留接口（对接文风指纹工具链）：
# corpus_fingerprint(texts) -> {sentence_max, emotion_naming, sensory, rules[...]}
# 产出可直接喂给 StyleDecl 字段。v0.1 未实现，仅约定形状。


def get_style(name):
    return STYLE_PRESETS.get(name, STYLE_PRESETS["default"])


def resolve_style(name, style_decls=()):
    """命名预设与文件内 style 声明合并（M4）。

    数值/开关字段编译为文本规则追加；rule = "..." 逐条附加；
    多个同 key 声明按声明顺序依次并入。
    """
    base = get_style(name)
    merged = {"key": base["key"], "name": base["name"],
              "description": base["description"],
              "rules": list(base["rules"]),
              "constraints": {}}
    for d in style_decls:
        if d.key != name:
            continue
        if d.desc:
            merged["description"] = d.desc
        if d.sentence_max is not None:
            merged["constraints"]["sentence_max"] = d.sentence_max
            merged["rules"].append(f"平均句长不超过 {d.sentence_max:g} 字，以短句节奏为主")
        if d.emotion_naming == "forbid":
            merged["rules"].append("禁止直接命名情绪（写动作、感官与生理反应）")
        elif d.emotion_naming == "allow":
            merged["rules"].append("可直接命名情绪，但须克制、少用")
        if d.sensory:
            level = {"low": "低（点到为止）", "mid": "中（适度呈现）",
                     "high": "高（声音、气味、触感、光线、温度密集呈现）"}[d.sensory]
            merged["constraints"]["sensory"] = d.sensory
            merged["rules"].append(f"感官细节密度：{level}")
        if d.dialogue_gaps is True:
            merged["constraints"]["dialogue_gaps"] = True
            merged["rules"].append("对话简省，留白多于解释")
        merged["rules"].extend(d.rules)
    return merged
