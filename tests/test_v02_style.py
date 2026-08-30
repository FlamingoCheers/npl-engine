"""v0.2 风格指纹 + 意象聚类测试。"""
import json
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from npl.analysis.imagery import extract_candidates  # noqa: E402
from npl.style import features  # noqa: E402
from npl.style.fingerprint import (  # noqa: E402
    corpus_fingerprint,
    diff,
    render_style_npl,
    to_style_decl,
)


RESTRAINED = (
    "茶凉了。林把账本合上，指腹压着封皮，压出一道浅浅的印子。\n\n"
    "三月三日。茶楼。她把那一行看了两遍，没有再多看。\n\n"
    "“账本？”包勇在门口问。\n\n"
    "“对账。”她说。声音平得像熨过的纸。"
)

LUSH = (
    "灯光只够到桌面，四壁都退进暗里去了，她坐在光里，像坐在一口深井的井底。"
    "那几个数字安安静静地卧在一串水电费中间，安静得近乎无辜，可她一眼就看见了它，"
    "仿佛人海之中你总能第一眼看见那个你不敢看见的人。酸楚便从那里漫上来，漫过喉咙。"
)


class TestFingerprint(unittest.TestCase):
    def test_deterministic(self):
        a = corpus_fingerprint([RESTRAINED, LUSH])
        b = corpus_fingerprint([RESTRAINED, LUSH])
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_builtin_features_present(self):
        fp = corpus_fingerprint([RESTRAINED])
        for name in ("avg_sentence_len", "dialogue_ratio", "emotion_naming_rate",
                     "metaphor_density", "sensory_density", "vocab_richness",
                     "paragraph_len_median", "punctuation_profile"):
            self.assertIn(name, fp["features"])
        self.assertIn("lexicon_digest", fp["meta"])
        self.assertEqual(fp["fingerprint_version"], "1")

    def test_lexicon_injection_changes_values(self):
        base = corpus_fingerprint([RESTRAINED])
        custom = corpus_fingerprint(
            [RESTRAINED], lexicons={"emotion_words": {"账本", "茶", "印子"}})
        self.assertGreater(custom["features"]["emotion_naming_rate"],
                           base["features"]["emotion_naming_rate"])
        self.assertNotEqual(base["meta"]["lexicon_digest"],
                            custom["meta"]["lexicon_digest"])

    def test_new_lexicon_category(self):
        # 第三方注入全新词表类别：类别本身影响词表摘要（digest），可被同名自定义特征消费
        base = corpus_fingerprint([RESTRAINED])
        custom = corpus_fingerprint([RESTRAINED],
                                    lexicons={"color_words": {"黄", "灰"}})
        self.assertNotEqual(base["meta"]["lexicon_digest"],
                            custom["meta"]["lexicon_digest"])

    def test_custom_feature_registration(self):
        @features.register_feature("color_word_rate", version="2")
        def color_word_rate(c):
            lex = c.lexicons.get("color_words", set())
            if not lex or c.n_tokens == 0:
                return 0.0
            return sum(1 for t in c.all_tokens if t in lex) / c.n_tokens * 1000

        fp = corpus_fingerprint([RESTRAINED], feature_names=["color_word_rate"],
                                lexicons={"color_words": {"黄", "灰"}})
        self.assertIn("color_word_rate", fp["features"])
        self.assertEqual(fp["features"]["color_word_rate"], 0.0)  # RESTRAINED 无颜色词

    def test_unknown_feature_rejected(self):
        with self.assertRaises(KeyError):
            corpus_fingerprint([RESTRAINED], feature_names=["no_such_feature"])

    def test_diff(self):
        fa = corpus_fingerprint([RESTRAINED])
        fb = corpus_fingerprint([LUSH])
        d = diff(fa, fb)
        self.assertLess(fa["features"]["metaphor_density"],
                        fb["features"]["metaphor_density"])
        self.assertEqual(d["metaphor_density"]["delta"],
                         round(fb["features"]["metaphor_density"]
                               - fa["features"]["metaphor_density"], 4))


class TestStyleMapping(unittest.TestCase):
    def test_to_style_decl_lush(self):
        fp = corpus_fingerprint([LUSH])
        decl = to_style_decl(fp)
        self.assertEqual(decl["emotion_naming"], "allow")   # LUSH 明确命名“酸楚”
        self.assertGreater(decl["sentence_max"], 12)
        self.assertTrue(decl["rules"])                      # 比喻密度高 → 出规则

    def test_sentence_max_clamped(self):
        tiny = corpus_fingerprint(["短。句。子。"])
        decl = to_style_decl(tiny)
        self.assertGreaterEqual(decl["sentence_max"], 12)

    def test_render_npl_roundtrip(self):
        from npl.parser import parse_source
        fp = corpus_fingerprint([LUSH])
        decl = to_style_decl(fp)
        block = render_style_npl("from_corpus", decl, "自动生成")
        src = ('npl@0.2\n'
               'world 小城 { location = home }\n'
               'character A { }\n'
               'information x {\n'
               '  truth = secret_x\n'
               '  public = false\n'
               '}\n'
               + block + '\n'
               'render {\n'
               '  style = from_corpus\n'
               '  language = zh\n'
               '}\n')
        program = parse_source(src)
        self.assertEqual(len(program.styles), 1)
        sd = program.styles[0]
        self.assertEqual(sd.key, "from_corpus")
        self.assertEqual(sd.sentence_max, decl["sentence_max"])
        self.assertEqual(sd.emotion_naming, decl["emotion_naming"])
        self.assertEqual(sd.sensory, decl["sensory"])
        self.assertEqual(sd.dialogue_gaps, decl["dialogue_gaps"])
        self.assertEqual(len(sd.rules), len(decl["rules"]))


class TestImagery(unittest.TestCase):
    def test_cluster_and_stopwords(self):
        scenes = {
            "[1] A": "茶杯放在桌上。茶水凉了。他忽然站起来走了。",
            "[2] B": "茶杯还在原地。她看着茶水出神。",
            "[3] C": "钥匙落进碗里。他走了以后没人动过茶杯。",
        }
        out = extract_candidates(scenes, min_scenes=2)
        labels = {c["label"] for c in out}
        # “茶杯”应聚出；“忽然/以后”等泛词与停用词不应出现
        self.assertIn("茶杯", labels)
        self.assertNotIn("忽然", labels)
        self.assertNotIn("以后", labels)

    def test_min_scenes_filter(self):
        scenes = {"[1] A": "茶杯放在桌上。", "[2] B": "完全不同的内容出现。"}
        out = extract_candidates(scenes, min_scenes=2, min_total=2)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
