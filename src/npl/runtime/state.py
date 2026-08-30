"""NPL Runtime：六层叙事状态（M3 版）。

实现程度（见《项目规划.md》§2.2/§2.3/§2.4）：
  World / Character / Epistemic / Narrative 完整；Temporal 简化（每幕记录 world_time + flashback，
  状态演进按叙事顺序累积——倒叙只是呈现顺序，认知与读者模型仍按阅读顺序演化）；
  Presentation 不作为全局状态，由 executor 按场景 access 规则即时解析。

M3 新增：
  - 嵌套认知 beliefs_about：A 关于 B 心智的建模（B.knows(x) / B.does_not_know(x) / B.believes(x)）
  - suspects 升级为 置信度字典（默认 0.5）
  - hides：角色主动隐藏行为的认知记录
  - Reader Model：narrative.suspicions / narrative.unanswered_questions（§2.3 读者世界）

确定性约定：to_dict() 输出全部排序（set → sorted list），同输入 → 逐字节一致的快照。
"""
from .. import ast_nodes as ast


class RuntimeState:
    def __init__(self):
        self.world = {"facts": {}, "locations": [], "time": None, "entities": {}}
        self.characters = {}   # name -> 状态 dict
        self.information = {}  # id -> {truth, holders:set, suspected_by:dict, public}
        self.narrative = {
            "reader_knows": set(),
            "conceal_active": set(),
            "revealed": set(),
            "suspicions": set(),             # Reader Model：读者怀疑的 info/fact id
            "unanswered_questions": set(),   # Reader Model：未回答的问题（确定性字符串）
            "motifs": {},                    # M4：母题 id -> [{role, scene}]（按幕序追加）
            "misdirects_active": set(),      # M4：尚在误导中的命题（读者被引向的错误方向）
        }

    # ---------- 构建 ----------
    @classmethod
    def from_program(cls, program):
        st = cls()
        if program.world is not None:
            for f in program.world.facts:
                st.world["facts"][f.name] = f.value
            st.world["locations"] = [p.name for p in program.world.locations]
            st.world["time"] = program.world.time
            for e in program.world.entities:
                st.world["entities"][e.name] = e.attrs
        for c in program.characters:
            suspects = {}
            for s in c.suspects:
                suspects[s.name] = float(getattr(s, "confidence", 0.5))
            relations = {}
            relation_reasons = {}
            for rel in getattr(c, "relations", []):   # v0.5 有向态度（值+理由）
                relations.setdefault(rel.target, {})[rel.attitude] = rel.value
                if rel.reason:
                    relation_reasons.setdefault(rel.target, {})[rel.attitude] = rel.reason
            believes = set()
            believes_about = {}
            nested_beliefs = set()
            for e in c.believes:
                if isinstance(e, ast.NestedBelief):
                    if len(e.path) == 1:
                        bucket = believes_about.setdefault(
                            e.holder, {"knows": set(), "does_not_know": set(), "believes": set()})
                        bucket[e.verb].add(e.prop)
                    else:   # v0.2 深层嵌套：规范化字符串存储（运行时验证深度见计算模型）
                        nested_beliefs.add(e.canonical())
                else:
                    believes.add(e.name)
            st.characters[c.name] = {
                "knows": {p.name for p in c.knows},
                "believes": believes,
                "believes_about": believes_about,
                "nested_beliefs": nested_beliefs,
                "suspects": suspects,
                "does_not_know": {p.name for p in c.does_not_know},
                "intends": {p.name for p in c.intends},
                "goals": {p.name for p in c.goal},
                "personality": {t.name: t.value for t in c.personality},
                "emotion": {t.name: t.value for t in c.emotion},
                "relations": relations,
                "relation_reasons": relation_reasons,
                "hides": set(),
                "arc": None,
            }
        for i in program.informations:
            st.information[i.name] = {
                "truth": i.truth,
                "holders": {p.name for p in i.known_by},
                "suspected_by": {s.name: s.confidence for s in i.suspected_by},
                "public": i.public,
            }
        return st

    @classmethod
    def from_dict(cls, d):
        """快照 JSON → RuntimeState（round-trip，用于渲染指定场景/离线 inspect）。"""
        st = cls()
        st.world = {
            "facts": dict(d["world"]["facts"]),
            "locations": list(d["world"]["locations"]),
            "time": d["world"]["time"],
            "entities": {k: dict(v) for k, v in d["world"]["entities"].items()},
        }
        for name, cs in d["characters"].items():
            st.characters[name] = {
                "knows": set(cs["knows"]),
                "believes": set(cs["believes"]),
                "believes_about": {
                    holder: {verb: set(props) for verb, props in sorted(bucket.items())}
                    for holder, bucket in cs.get("believes_about", {}).items()
                },
                "nested_beliefs": set(cs.get("nested_beliefs", [])),
                "suspects": dict(cs["suspects"]),
                "does_not_know": set(cs["does_not_know"]),
                "intends": set(cs["intends"]),
                "goals": set(cs["goals"]),
                "personality": dict(cs["personality"]),
                "emotion": dict(cs["emotion"]),
                "relations": {
                    target: dict(atts)
                    for target, atts in cs.get("relations", {}).items()
                },
                "relation_reasons": {
                    target: dict(atts)
                    for target, atts in cs.get("relation_reasons", {}).items()
                },
                "hides": set(cs.get("hides", [])),
                "arc": ({"states": list(cs["arc"]["states"]),
                         "current": cs["arc"]["current"]} if cs["arc"] else None),
            }
        for k, v in d["information"].items():
            st.information[k] = {
                "truth": v["truth"],
                "holders": set(v["holders"]),
                "suspected_by": dict(v["suspected_by"]),
                "public": v["public"],
            }
        n = d.get("narrative", {})
        st.narrative = {k: set(v) for k, v in n.items() if k != "motifs"}
        st.narrative["motifs"] = {k: [dict(x) for x in v]
                                  for k, v in n.get("motifs", {}).items()}
        st.narrative.setdefault("misdirects_active", set())
        return st

    # ---------- 事件语义 ----------
    def confirm(self, actor, prop):
        """CONFIRM 族动词：actor 获知 prop。"""
        if actor in self.characters:
            self.characters[actor]["knows"].add(prop)

    def nested_realize(self, actor, path, prop):
        """CONFIRM 族动词的嵌套形式：actor 更新对他人心智的建模。

        path = [(holder, verb), ...] 由外向内。一层入 believes_about；
        更深层以规范化字符串入 nested_beliefs（v0.2）。
        """
        if actor not in self.characters:
            return
        cs = self.characters[actor]
        if len(path) == 1:
            holder, verb = path[0]
            bucket = cs["believes_about"].setdefault(
                holder, {"knows": set(), "does_not_know": set(), "believes": set()})
            if verb == "knows":
                bucket["knows"].add(prop)
                bucket["does_not_know"].discard(prop)
            elif verb == "does_not_know":
                bucket["does_not_know"].add(prop)
                bucket["knows"].discard(prop)
            else:
                bucket["believes"].add(prop)
            return
        head = ">".join(f"{h}|{v}" for h, v in path)
        cs["nested_beliefs"].add(f"{head}>{prop}")

    def misunderstand(self, actor, prop):
        """MISUNDERSTAND 族动词：actor 采信 prop（即使世界真值为假）；不入 knows。"""
        if actor in self.characters:
            self.characters[actor]["believes"].add(prop)

    def suspect(self, actor, prop, confidence=0.6):
        """SUSPECT 族动词：actor 怀疑 prop（置信度取更高值）。"""
        if actor in self.characters:
            cur = self.characters[actor]["suspects"].get(prop, 0.0)
            self.characters[actor]["suspects"][prop] = max(cur, float(confidence))

    def hide(self, actor, prop):
        """HIDE 族动词：actor 主动隐藏 prop。"""
        if actor in self.characters:
            self.characters[actor]["hides"].add(prop)

    def reveal_to_all(self, participants, prop):
        """REVEAL 族动词：对全部在场人物公开 prop。"""
        for name in participants:
            if name in self.characters:
                self.characters[name]["knows"].add(prop)

    def apply_arc(self, character, states):
        if character in self.characters:
            self.characters[character]["arc"] = {
                "states": list(states),
                "current": states[-1] if states else None,
            }

    def apply_goals(self, reveals, conceals):
        for t in reveals:
            self.narrative["reader_knows"].add(t)
            self.narrative["revealed"].add(t)
            self.narrative["conceal_active"].discard(t)  # 揭示即解除隐藏
            self.narrative["misdirects_active"].discard(t)
            self.narrative["unanswered_questions"] = {
                q for q in self.narrative["unanswered_questions"] if t not in q}
        for t in conceals:
            if t in self.narrative["revealed"]:
                continue  # 已揭示的目标不再回退为隐藏
            self.narrative["conceal_active"].add(t)
            self.narrative["unanswered_questions"].add(f"{t} 的真相尚未揭示")

    # ---------- 序列化 ----------
    def to_dict(self):        return {
            "world": {
                "facts": dict(sorted(self.world["facts"].items())),
                "locations": sorted(self.world["locations"]),
                "time": self.world["time"],
                "entities": {k: dict(sorted(v.items()))
                             for k, v in sorted(self.world["entities"].items())},
            },
            "characters": {
                name: {
                    "knows": sorted(cs["knows"]),
                    "believes": sorted(cs["believes"]),
                    "believes_about": {
                        holder: {verb: sorted(props) for verb, props in sorted(bucket.items())}
                        for holder, bucket in sorted(cs["believes_about"].items())
                    },
                    "nested_beliefs": sorted(cs["nested_beliefs"]),
                    "suspects": dict(sorted(cs["suspects"].items())),
                    "does_not_know": sorted(cs["does_not_know"]),
                    "intends": sorted(cs["intends"]),
                    "goals": sorted(cs["goals"]),
                    "personality": dict(sorted(cs["personality"].items())),
                    "emotion": dict(sorted(cs["emotion"].items())),
                    "relations": {
                        target: dict(sorted(atts.items()))
                        for target, atts in sorted(cs.get("relations", {}).items())
                    },
                    "relation_reasons": {
                        target: dict(sorted(atts.items()))
                        for target, atts in sorted(cs.get("relation_reasons", {}).items())
                    },
                    "hides": sorted(cs["hides"]),
                    "arc": ({"states": cs["arc"]["states"],
                             "current": cs["arc"]["current"]} if cs["arc"] else None),
                }
                for name, cs in sorted(self.characters.items())
            },
            "information": {
                k: {"truth": v["truth"], "holders": sorted(v["holders"]),
                    "suspected_by": dict(sorted(v["suspected_by"].items())),
                    "public": v["public"]}
                for k, v in sorted(self.information.items())
            },
            "narrative": {
                k: (sorted(v) if k != "motifs"
                    else {mid: [dict(sorted(m.items())) for m in ms]
                          for mid, ms in sorted(v.items())})
                for k, v in self.narrative.items()
            },
        }


def canonical_to_display(canon: str) -> str:
    "'A|believes>B|knows>x' -> 'A.believes(B.knows(x))'（供 IR/prompt 展示深层嵌套）。"
    parts = canon.split(">")
    inner = parts[-1]
    for seg in reversed(parts[:-1]):
        holder, verb = seg.split("|", 1)
        inner = f"{holder}.{verb}({inner})"
    return inner
