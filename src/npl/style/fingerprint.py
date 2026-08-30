"""语料风格指纹——统计、序列化与到 NPL style 块的确定性映射。

指纹是版本化的纯数据 JSON：特征集 + 每特征版本 + 词表指纹，
相同语料 + 相同特征集 ⇒ 逐字节相同的指纹（可 diff、可入库）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional

from . import features
from .features import CorpusStats, build_corpus_stats, FEATURES, FEATURE_VERSIONS

FINGERPRINT_VERSION = "1"


# --------------------------------------------------------------- 计算

def corpus_fingerprint(
    texts: List[str],
    feature_names: Optional[List[str]] = None,
    lexicons: Optional[Dict[str, set]] = None,
) -> dict:
    """对语料计算风格指纹。

    feature_names: 缺省用全部已注册特征（含第三方注册的）。
    lexicons:      词表注入（整体替换同名类别，可新增类别）。
    """
    names = list(feature_names) if feature_names else sorted(FEATURES)
    unknown = [n for n in names if n not in FEATURES]
    if unknown:
        raise KeyError(f"未注册的特征: {', '.join(unknown)}")

    stats: CorpusStats = build_corpus_stats(texts, lexicons=lexicons)
    values = {name: round(float(FEATURES[name](stats)), 4) for name in names}

    lex_digest = hashlib.sha1(
        json.dumps({k: sorted(v) for k, v in sorted(stats.lexicons.items())},
                   ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:10]

    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "feature_set_version": _feature_set_version(names),
        "meta": {
            "n_texts": len(texts),
            "n_chars": stats.n_chars,
            "n_sentences": len(stats.sentences),
            "n_paragraphs": len(stats.paragraphs),
            "lexicon_digest": lex_digest,
        },
        "features": values,
    }


def _feature_set_version(names: List[str]) -> str:
    payload = json.dumps(
        [[n, FEATURE_VERSIONS.get(n, "?")] for n in sorted(names)],
        ensure_ascii=False,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def load_fingerprint(path) -> dict:
    fp = json.loads(open(path, encoding="utf-8-sig").read())
    if "features" not in fp:
        raise ValueError(f"不是有效的指纹文件: {path}")
    return fp


# --------------------------------------------------------------- 映射

def to_style_decl(fp: dict) -> dict:
    """指纹 → StyleDecl 形状的 dict（与 parser 的 style 块字段一一对应）。"""
    f = fp["features"]
    p90 = f.get("avg_sentence_len", 20.0) * 1.5
    sentence_max = int(min(60, max(12, round(p90 / 2) * 2)))

    emo = f.get("emotion_naming_rate", 0.0)
    emotion_naming = "allow" if emo >= 2.0 else "forbid"

    sen = f.get("sensory_density", 0.0)
    sensory = "high" if sen >= 6.0 else ("mid" if sen >= 2.0 else "low")

    dialogue_gaps = f.get("dialogue_ratio", 0.0) < 0.35

    rules = []
    meta = f.get("metaphor_density", 0.0)
    if meta >= 4.0:
        rules.append("比喻密度高：允许每段一处比喻")
    elif meta < 1.0:
        rules.append("比喻密度低：避免明喻修辞")
    if f.get("punctuation_profile", 0.0) >= 8.0:
        rules.append("特征标点密度高：保留顿挫与留白标点")
    if f.get("vocab_richness", 0.0) >= 0.55:
        rules.append("词汇丰富度高：避免重复用词")

    return {
        "sentence_max": sentence_max,
        "emotion_naming": emotion_naming,
        "sensory": sensory,
        "dialogue_gaps": dialogue_gaps,
        "rules": rules,
    }


def render_style_npl(key: str, decl: dict, desc: str = "") -> str:
    """把 StyleDecl 形状 dict 渲染成可直接粘进 .npl 的 style 块文本。"""
    lines = [f"style {key} {{"]
    if desc:
        lines.append(f'  desc = "{desc}"')
    lines.append(f"  sentence_max = {decl['sentence_max']}")
    lines.append(f"  emotion_naming = {decl['emotion_naming']}")
    lines.append(f"  sensory = {decl['sensory']}")
    lines.append(f"  dialogue_gaps = {'true' if decl['dialogue_gaps'] else 'false'}")
    for rule in decl.get("rules", []):
        lines.append(f'  rule = "{rule}"')
    lines.append("}")
    return "\n".join(lines)


# --------------------------------------------------------------- 对比

def diff(fp_a: dict, fp_b: dict) -> dict:
    """逐特征对比两个指纹：返回 {feature: {a, b, delta}}。"""
    fa, fb = fp_a["features"], fp_b["features"]
    out = {}
    for name in sorted(set(fa) | set(fb)):
        va, vb = fa.get(name), fb.get(name)
        delta = None
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            delta = round(vb - va, 4)
        out[name] = {"a": va, "b": vb, "delta": delta}
    return out
