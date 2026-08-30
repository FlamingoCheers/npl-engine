"""Scene IR 构造：场景执行后的中间表示（Context Compiler 的输入）。"""


def epistemic_view(state, pov_name):
    """某人物的认知视图（IR 的 pov_epistemic_view）。"""
    cs = state.characters[pov_name]
    facts = state.world["facts"]
    return {
        "knows_grounded": {p: facts[p] for p in sorted(cs["knows"]) if p in facts},
        "knows_free": sorted(p for p in cs["knows"] if p not in facts),
        "believes_grounded": {p: facts[p] for p in sorted(cs["believes"]) if p in facts},
        "believes_free": sorted(p for p in cs["believes"] if p not in facts),
        "believes_about": {
            holder: {verb: sorted(props) for verb, props in sorted(bucket.items())}
            for holder, bucket in sorted(cs["believes_about"].items())
        },
        "nested_beliefs": sorted(cs.get("nested_beliefs", [])),   # v0.2 深层嵌套（canonical 形式）
        "suspects": dict(sorted(cs["suspects"].items())),
        "hides": sorted(cs["hides"]),
        "intends": sorted(cs["intends"]),
        "personality": dict(sorted(cs["personality"].items())),
        "emotion": dict(sorted(cs["emotion"].items())),
        "arc": cs["arc"],
    }


def reader_model(state):
    """Reader Model 视图（§2.3 读者世界，确定性派生）。"""
    return {
        "known_facts": sorted(state.narrative["reader_knows"]),
        "suspicions": sorted(state.narrative["suspicions"]),
        "unanswered_questions": sorted(state.narrative["unanswered_questions"]),
    }


def build_ir(state, scene, scene_index, presentation, reveals, conceals):
    participants = [p.name for p in scene.participants]
    return {
        "scene_index": scene_index,
        "title": scene.title,
        "framing": {
            "location": scene.location,
            "world_time": scene.world_time,
            "flashback": scene.flashback,
            "pov": scene.pov,
            "participants": participants,
        },
        "presentation": presentation,
        "events": [{"actor": r.actor, "action": r.action, "args": list(r.args)}
                   for r in scene.events],
        "information_changes": [{"actor": r.actor, "action": r.action, "args": list(r.args)}
                                for r in scene.information_changes],
        "pov_epistemic_view": epistemic_view(state, scene.pov),
        "others_observable": {
            name: {
                "scene_actions": [r.action for r in scene.events if r.actor == name],
                "observable_arc": [s for a in scene.emotional_arc
                                   if a.character == name for s in a.states],
            }
            for name in participants if name != scene.pov
        },
        "emotional_trajectory": {a.character: list(a.states) for a in scene.emotional_arc},
        "narrative_objectives": {"reveal": reveals, "conceal": conceals},
        "motifs": [{"motif": m.motif, "role": m.role, "desc": m.desc}
                   for m in scene.motifs],
        "foreshadows": [{"target": f.target, "desc": f.desc}
                        for f in scene.foreshadows],
        "misdirects": [{"target": d.target, "desc": d.desc}
                       for d in scene.misdirects],
        "withholds": [{"target": w.target, "until": w.until, "desc": w.desc}
                      for w in scene.withholds],
        "reader_model": reader_model(state),
    }
