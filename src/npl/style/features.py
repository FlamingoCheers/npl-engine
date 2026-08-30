"""语料风格特征——可扩展注册表。

扩展方式（第三方只需 import 本模块）::

    from npl.style import features

    @features.register_feature("rhyme_tail_rate", version="1")
    def rhyme_tail_rate(corpus):
        # corpus: 预计算的语料统计对象，见 CorpusStats
        ...

    fp = corpus_fingerprint(texts, features=["avg_sentence_len", "rhyme_tail_rate"])

词表（LEXICONS）同样可注入替换：不同团队可以带自己的情绪词表、
比喻标记表、感官词表，指纹口径随之改变。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from ..analysis.imagery import tokenize

# --------------------------------------------------------------- 注册表

FEATURES: Dict[str, Callable[["CorpusStats"], float]] = {}
FEATURE_VERSIONS: Dict[str, str] = {}


def register_feature(name: str, version: str = "1"):
    """把函数注册为风格特征。函数签名 fn(corpus: CorpusStats) -> float。"""

    def deco(fn):
        if name in FEATURES:
            raise ValueError(f"特征重复注册: {name}")
        FEATURES[name] = fn
        FEATURE_VERSIONS[name] = version
        return fn

    return deco


# 可注入词表：键固定，值可整体替换或 update。
LEXICONS: Dict[str, set] = {
    "emotion_words": {
        "悲", "痛", "恨", "爱", "怒", "怕", "惧", "喜", "愁", "怨", "悔",
        "委屈", "心酸", "酸楚", "绝望", "温柔", "冷漠", "愧疚", "嫉妒",
        "幸福", "孤独", "寂寞", "愤怒", "恐惧", "欢喜", "焦虑", "不安",
    },
    "metaphor_markers": {
        "像", "好像", "仿佛", "似乎", "如同", "宛如", "好似",
        "似的", "般", "犹如", "恍若",
    },
    "sensory_words": {
        "烫", "凉", "冷", "热", "涩", "腥", "咸", "苦", "甜", "腻",
        "嗡", "吱", "咔", "嘶", "哗", "砰", "滴答",
        "刺眼", "晃眼", "昏暗", "灰白", "猩红", "油亮", "潮湿", "干燥",
        "烟味", "焦味", "霉味", "汗味", "腥气", "水声", "哗啦", "吱呀",
        "咔哒", "嗡嗡", "闷响", "冰凉", "滚烫", "温热", "发凉", "发烫",
        "凉透", "发硬", "发潮", "沉甸甸", "轻飘飘", "黏", "刺痒",
    },
    "punctuations": {"；", "——", "…", "！", "？", "……"},
}

RE_SENT_SPLIT = re.compile(r"[。！？!?…]+")
RE_PUNCTspa = None  # 占位：标点统计直接按子串计数


# --------------------------------------------------------------- 语料统计

@dataclass
class CorpusStats:
    """指纹计算前的语料预统计。特征函数只读这里，保证一次分词全表共享。"""

    texts: List[str]
    tokens: List[List[str]] = field(default_factory=list)
    sentences: List[str] = field(default_factory=list)
    paragraphs: List[str] = field(default_factory=list)
    n_chars: int = 0
    lexicons: Dict[str, set] = field(default_factory=dict)

    @property
    def all_tokens(self) -> List[str]:
        return [t for toks in self.tokens for t in toks]

    @property
    def n_tokens(self) -> int:
        return sum(len(t) for t in self.tokens)


def build_corpus_stats(texts: List[str], lexicons: Dict[str, set] | None = None) -> CorpusStats:
    merged = {k: set(v) for k, v in LEXICONS.items()}
    if lexicons:
        for k, v in lexicons.items():
            if k not in merged:
                merged[k] = set(v)          # 新词表类别（第三方扩展点）
            else:
                merged[k] = set(v)          # 整体替换，保证口径确定
    stats = CorpusStats(texts=list(texts), lexicons=merged)
    for text in texts:
        stats.tokens.append(tokenize(text))
        stats.sentences.extend(s for s in RE_SENT_SPLIT.split(text) if s.strip())
        paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
        stats.paragraphs.extend(paras)
        stats.n_chars += len(re.sub(r"\s", "", text))
    return stats


# --------------------------------------------------------------- 内置 8 特征

@register_feature("avg_sentence_len")
def avg_sentence_len(c: CorpusStats) -> float:
    if not c.sentences:
        return 0.0
    lens = [len(s.strip()) for s in c.sentences]
    return sum(lens) / len(lens)


@register_feature("paragraph_len_median")
def paragraph_len_median(c: CorpusStats) -> float:
    if not c.paragraphs:
        return 0.0
    lens = sorted(len(p) for p in c.paragraphs)
    n = len(lens)
    mid = lens[n // 2] if n % 2 else (lens[n // 2 - 1] + lens[n // 2]) / 2
    return float(mid)


@register_feature("dialogue_ratio")
def dialogue_ratio(c: CorpusStats) -> float:
    """含引号（“”「」''""）的段占比。"""
    if not c.paragraphs:
        return 0.0
    marks = ("“", "”", "「", "」", "‘", "’", "\"", "'")
    hits = sum(1 for p in c.paragraphs if any(m in p for m in marks))
    return hits / len(c.paragraphs)


def _lex_rate(c: CorpusStats, key: str) -> float:
    lex = c.lexicons.get(key, set())
    if not lex or c.n_tokens == 0:
        return 0.0
    hits = sum(1 for t in c.all_tokens if t in lex)
    return hits / c.n_tokens


@register_feature("emotion_naming_rate")
def emotion_naming_rate(c: CorpusStats) -> float:
    """情绪名词密度（每千词）。直陈情绪的程度。"""
    return _lex_rate(c, "emotion_words") * 1000


@register_feature("metaphor_density")
def metaphor_density(c: CorpusStats) -> float:
    """比喻标记密度（每千词）。"""
    return _lex_rate(c, "metaphor_markers") * 1000


@register_feature("sensory_density")
def sensory_density(c: CorpusStats) -> float:
    """感官词密度（每千词）。"""
    return _lex_rate(c, "sensory_words") * 1000


@register_feature("vocab_richness")
def vocab_richness(c: CorpusStats) -> float:
    toks = c.all_tokens
    if not toks:
        return 0.0
    return len(set(toks)) / len(toks)


@register_feature("punctuation_profile")
def punctuation_profile(c: CorpusStats) -> float:
    """特征标点（；——…！？……）每千字频次。"""
    if c.n_chars == 0:
        return 0.0
    hits = sum(text.count(p) for text in c.texts for p in c.lexicons["punctuations"])
    return hits / c.n_chars * 1000
