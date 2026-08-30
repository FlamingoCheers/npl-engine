"""v0.3 跨章长程母题追踪：轨迹合并、全文回扫计数、gap 预警、CLI 跨章模式。"""
import json

from npl.analysis.tracking import (DROPPED, INTERMITTENT, TAILING,
                                   render_track_report, report_to_json,
                                   track_motifs)
from npl.cli import main


def _ch(*texts):
    return [("s%d" % (i + 1), t) for i, t in enumerate(texts)]


# ---------------- 轨迹与全文回扫计数 ----------------

def test_series_counts_full_text_not_cluster_only():
    # 卷二只出现一次（聚不出局部簇），但全文回扫必须计数
    chapters = {
        "卷一": _ch("茶杯放在案头，茶杯映着灯花。", "他没喝，茶杯凉透了。"),
        "卷二": _ch("桌上只剩一只茶杯。"),
    }
    r = track_motifs(chapters, declared={"卷一": {"茶杯"}})
    assert r["chapters"] == ["卷一", "卷二"]
    m = [x for x in r["motifs"] if x["label"] == "茶杯"]
    assert m and m[0]["series"]["卷一"] == 3 and m[0]["series"]["卷二"] == 1
    assert m[0]["declared_in"] == ["卷一"]
    assert m[0]["status"] == "活跃"


def test_gap_intermittent_alert():
    chapters = {
        "一": _ch("茶杯放在案头，茶杯映着灯花。", "茶杯里的水凉了。"),
        "二": _ch("他翻着账册，一夜没睡。"),
        "三": _ch("账册的数字对不上。"),
        "四": _ch("茶杯终于凉透了。", "茶杯边压着字条。"),
    }
    r = track_motifs(chapters, declared={"一": {"茶杯"}, "四": {"茶杯"}},
                     gap_alert=2)
    m = [x for x in r["motifs"] if x["label"] == "茶杯"][0]
    assert m["max_gap"] == 2
    assert m["status"] == INTERMITTENT
    assert any("最长间隔 2 章" in a for a in m["alerts"])


def test_dropped_alert():
    chapters = {
        "一": _ch("茶杯放在案头，茶杯映着灯花。", "茶杯里的水凉了。"),
        "二": _ch("他翻着账册。"),
        "三": _ch("账册对不上。"),
    }
    r = track_motifs(chapters, declared={"一": {"茶杯"}}, gap_alert=2)
    m = [x for x in r["motifs"] if x["label"] == "茶杯"][0]
    assert m["status"] == DROPPED
    assert any("连续 2 章未出现" in a for a in m["alerts"])


def test_tailing_declared():
    chapters = {
        "一": _ch("茶杯放在案头，茶杯映着灯花。", "茶杯里的水凉了。"),
        "二": _ch("他翻着账册。"),
    }
    r = track_motifs(chapters, declared={"一": {"茶杯"}}, gap_alert=2)
    m = [x for x in r["motifs"] if x["label"] == "茶杯"][0]
    assert m["status"] == TAILING and not m["alerts"]


def test_undeclared_track_no_tag():
    chapters = {
        "一": _ch("钥匙在抽屉里。", "钥匙生了锈，钥匙很旧。"),
        "二": _ch("钥匙不见了。"),
    }
    r = track_motifs(chapters)
    m = [x for x in r["motifs"] if x["label"] == "钥匙"]
    assert m and m[0]["declared_in"] == []
    assert m[0]["status"] == "活跃"


# ---------------- 频率与序列化 ----------------

def test_freq_per_kchar():
    t1, t2 = "茶杯放在案头。", "茶杯映着灯花。茶杯凉了。"
    chapters = {"卷一": _ch(t1, t2)}
    r = track_motifs(chapters, declared={"卷一": {"茶杯"}})
    m = [x for x in r["motifs"] if x["label"] == "茶杯"][0]
    chars = len(t1) + len(t2)
    assert m["freq"]["卷一"] == round(m["series"]["卷一"] / chars * 1000, 2)


def test_json_roundtrip_and_render():
    chapters = {
        "一": _ch("茶杯放在案头，茶杯映着灯花。", "茶杯里的水凉了。"),
        "二": _ch("茶杯凉透了。"),
    }
    r = track_motifs(chapters, declared={"一": {"茶杯"}, "二": {"茶杯"}})
    r2 = json.loads(report_to_json(r))
    assert any(m["label"] == "茶杯" for m in r2["motifs"])
    text = "\n".join(render_track_report(r))
    assert "跨章母题追踪" in text and "茶杯" in text and "★已声明" in text


def test_empty_input():
    r = track_motifs({"卷一": _ch("无事发生。")})
    assert r["motifs"] == []


# ---------------- CLI 跨章模式 ----------------

_NPL = ("npl@0.2\n"
        "world w {\n"
        "    fact x_done = false\n"
        "    location = station\n"
        "}\n"
        "character Lin {\n"
        "    knows: x_done\n"
        "}\n"
        'scene "一" {\n'
        "    pov = Lin\n"
        "    participants = [Lin]\n"
        "    motifs {\n"
        "        茶杯 = introduce // 案头常物\n"
        "    }\n"
        "}\n"
        'scene "二" {\n'
        "    pov = Lin\n"
        "    participants = [Lin]\n"
        "}\n"
        "render {\n"
        "    style = restrained_literary\n"
        "    language = zh\n"
        "}\n")


def _make_chapter(root, name, mentions):
    d = root / name
    (d / "build" / "prose").mkdir(parents=True)
    (d / "book.npl").write_text(_NPL, encoding="utf-8")
    for i, text in enumerate(mentions, 1):
        (d / "build" / "prose" / f"scene_{i:03d}.md").write_text(
            f"<!-- header -->\n{text}", encoding="utf-8")
    return d


def test_cli_track_mode(tmp_path, capsys):
    a = _make_chapter(tmp_path, "卷一",
                      ["茶杯放在案头，他没碰茶杯。", "茶杯里的水凉透了。"])
    b = _make_chapter(tmp_path, "卷二",
                      ["茶杯还在老地方。", "他扫了账册一眼。"])
    rc = main(["motifs", str(a), str(b), "--min-scenes", "1", "--json"])
    assert rc == 0
    r = json.loads(capsys.readouterr().out)
    m = [x for x in r["motifs"] if x["label"] == "茶杯"]
    assert m and m[0]["declared_in"] == ["卷一", "卷二"]
    assert m[0]["series"]["卷二"] >= 1


def test_cli_track_needs_two_dirs(tmp_path, capsys):
    a = _make_chapter(tmp_path, "卷一",
                      ["茶杯放在案头，他没碰茶杯。", "茶杯里的水凉透了。"])
    assert main(["motifs", str(a)]) == 2
    out = capsys.readouterr().out
    assert "至少需要 2 个章节目录" in out


def test_cli_track_missing_prose(tmp_path, capsys):
    a = _make_chapter(tmp_path, "卷一",
                      ["茶杯放在案头，他没碰茶杯。", "茶杯里的水凉透了。"])
    b = tmp_path / "卷二"
    b.mkdir()
    (b / "book.npl").write_text(_NPL, encoding="utf-8")
    assert main(["motifs", str(a), str(b)]) == 2
    assert "缺少散文文件" in capsys.readouterr().out
