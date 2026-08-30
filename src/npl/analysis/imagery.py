"""NPL 文本分析工具（v0.2）：母题/意象聚类。可选依赖 jieba，缺失时自动回退。"""

from __future__ import annotations

import re
from collections import Counter

# 停用词：虚词/代词/常用单字（聚类的噪声源）
STOPWORDS = {
    "的", "了", "是", "在", "我", "你", "他", "她", "它", "们", "和", "与", "就",
    "连", "着", "不", "被", "有", "没", "无", "可", "这", "那", "都", "也", "又",
    "一", "个", "上", "下", "来", "去", "说", "要", "会", "能", "到", "对", "把",
    "让", "给", "从", "而", "但", "却", "还", "很", "再", "只", "已经", "着",
    "自己", "什么", "没有", "不是", "一下", "一样", "起来", "过来", "出去",
    "知道", "觉得", "看见", "听到", "然后", "所以", "因为", "但是", "如果",
    "一种", "一起", "一声", "一眼", "一点", "一块", "半天", "声音", "时候",
    "地方", "东西", "样子", "好像", "似乎", "几乎", "突然", "终于", "慢慢",
    "轻轻", "静静", "只是", "就是", "还是", "这个", "那个", "这么", "那么",
}

RE_CJK = re.compile(r"[\u4e00-\u9fff]+")
RE_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def tokenize(text: str) -> list:
    """中文分词：优先 jieba；否则 CJK 串切 bigram + 拉丁词。"""
    try:
        import jieba  # noqa: F401
        return [w for w in jieba.lcut(text) if w.strip()]
    except ImportError:
        words = []
        for chunk in RE_CJK.findall(text):
            if len(chunk) == 1:
                words.append(chunk)
            else:
                words.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
        words.extend(RE_WORD.findall(text))
        return words


def _char_bigrams(term: str) -> set:
    if len(term) < 2:
        return {term}
    return {term[i:i + 2] for i in range(len(term) - 1)}


def extract_candidates(scene_texts: dict, min_scenes: int = 2,
                      min_total: int = 3) -> list:
    """从各场景正文中聚类候选母题。

    scene_texts: {场景名: 正文}。返回
    [{"label": 代表词, "members": [近义词], "scenes": {场景名: 次数}, "total": n}, ...]
    按出现场景数与总频次降序。
    """
    per_scene = {}
    for name, text in scene_texts.items():
        words = [w for w in tokenize(text) if len(w) >= 2 and w not in STOPWORDS
                 and not re.fullmatch(r"[A-Za-z0-9_]+", w)]
        per_scene[name] = Counter(words)

    df = Counter()          # 词 → 出现场景数
    total = Counter()       # 词 → 总频次
    for counter in per_scene.values():
        for w, n in counter.items():
            df[w] += 1
            total[w] += n

    seeds = [w for w, n in df.items() if n >= min_scenes and total[w] >= min_total]

    # 聚类：字符 bigram 重叠 → 视为同一意象族（茶杯/茶水/茶壶）
    clusters = []           # [{terms:set, scenes:{name:count}, total:int}]
    for w in sorted(seeds, key=lambda x: -total[x]):
        grams = _char_bigrams(w)
        for cluster in clusters:
            rep = min(cluster["terms"], key=lambda t: -total[t])
            if grams & _char_bigrams(rep):
                cluster["terms"].add(w)
                break
        else:
            clusters.append({"terms": {w}})

    out = []
    for cluster in clusters:
        scenes = {}
        t = 0
        for name, counter in per_scene.items():
            n = sum(counter[w] for w in cluster["terms"])
            if n:
                scenes[name] = n
                t += n
        if len(scenes) >= min_scenes:
            label = max(cluster["terms"], key=lambda x: total[x])
            out.append({"label": label, "members": sorted(cluster["terms"]),
                        "scenes": scenes, "total": t})
    out.sort(key=lambda c: (-len(c["scenes"]), -c["total"]))
    return out
