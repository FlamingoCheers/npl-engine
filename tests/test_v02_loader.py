"""v0.2 多文件加载：import 递归合并、循环检测、跨文件唯一性、母题跨文件。"""
import pytest

from npl.errors import NPLSyntaxError
from npl.parser import load_program
from npl.validator import validate

COMMON = ("npl@0.2\n"
          "world w {\n"
          "    fact lin_has_seen_contract_copy = false\n"
          "    location = station\n"
          "}\n"
          "character Lin {\n"
          "    knows: lin_has_seen_contract_copy\n"
          "}\n"
          "render {\n"
          "    style = restrained_literary\n"
          "    language = zh\n"
          "}")

ENTRY = ('npl@0.2\n'
         'import "common.npl" // 公共世界\n'
         "character Bao {}\n"
         'scene "s" {\n'
         "    pov = Lin\n"
         "    participants = [Lin, Bao]\n"
         "}\n")


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_load_merges_two_files(tmp_path):
    _write(tmp_path, "common.npl", COMMON)
    entry = _write(tmp_path, "main.npl", ENTRY)
    p = load_program(entry)
    names = {c.name for c in p.characters}
    assert names == {"Lin", "Bao"}
    fact_names = {f.name for f in p.world.facts}
    assert "lin_has_seen_contract_copy" in fact_names
    assert len(p.source_files) == 2
    assert p.imports[0].desc == "公共世界"
    assert p.render.style == "restrained_literary"   # 入口无 render → 采纳导入文件
    assert validate(p) is not None


def test_render_from_entry_wins(tmp_path):
    _write(tmp_path, "common.npl", COMMON)
    entry = _write(tmp_path, "main.npl",
                   ENTRY.replace('import "common.npl" // 公共世界\n',
                                 'import "common.npl"\n')
                   + "render { style = default }")
    p = load_program(entry)
    assert p.render.style == "default"


def test_cycle_raises_nar016(tmp_path):
    _write(tmp_path, "a.npl", 'npl@0.2\nimport "b.npl"\nworld w { fact x = true }')
    _write(tmp_path, "b.npl", 'npl@0.2\nimport "a.npl"')
    with pytest.raises(NPLSyntaxError) as ei:
        load_program(tmp_path / "a.npl")
    assert ei.value.code == "NAR-016"


def test_missing_import_raises_nar015(tmp_path):
    _write(tmp_path, "main.npl", 'npl@0.2\nimport "ghost.npl"')
    with pytest.raises(NPLSyntaxError) as ei:
        load_program(tmp_path / "main.npl")
    assert ei.value.code == "NAR-015"


def test_cross_file_duplicate_character(tmp_path):
    _write(tmp_path, "common.npl", COMMON)
    entry = _write(tmp_path, "main.npl",
                   ENTRY.replace("character Bao {}", "character Lin {}"))
    with pytest.raises(NPLSyntaxError) as ei:
        load_program(entry)
    assert ei.value.code == "NAR-011"


def test_cross_file_duplicate_world(tmp_path):
    _write(tmp_path, "common.npl", COMMON)
    entry = _write(tmp_path, "main.npl",
                   'npl@0.2\nimport "common.npl"\nworld w2 { fact y = true }')
    with pytest.raises(NPLSyntaxError) as ei:
        load_program(entry)
    assert ei.value.code == "NAR-011"


def test_motif_across_files(tmp_path):
    common = ('npl@0.2\n'
              'import "base.npl"\n'
              'scene "s" {\n'
              "    pov = Lin\n"
              "    participants = [Lin]\n"
              "    motifs {\n"
              "        teacup = introduce //一只豁口的茶杯\n"
              "    }\n"
              "}\n")
    _write(tmp_path, "base.npl", COMMON)
    _write(tmp_path, "common.npl", common)
    entry = _write(tmp_path, "main.npl",
                   'npl@0.2\n'
                   'import "common.npl"\n'
                   "character Bao {}\n"
                   'scene "s2" {\n'
                   "    pov = Lin\n"
                   "    participants = [Lin]\n"
                   "    motifs {\n"
                   "        teacup = recurrence //茶已经凉透\n"
                   "    }\n"
                   "}\n")
    p = load_program(entry)
    assert [d.code for d in validate(p)].count("NAR-061") == 0


def test_motif_recurrence_without_introduce_across_files(tmp_path):
    _write(tmp_path, "common.npl", COMMON)
    entry = _write(tmp_path, "main.npl",
                   'npl@0.2\n'
                   'import "common.npl"\n'
                   "character Bao {}\n"
                   'scene "s2" {\n'
                   "    pov = Lin\n"
                   "    participants = [Lin]\n"
                   "    motifs {\n"
                   "        teacup = recurrence //凭空重现\n"
                   "    }\n"
                   "}\n")
    p = load_program(entry)
    assert "NAR-061" in [d.code for d in validate(p)]
