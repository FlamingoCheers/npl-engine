"""v0.2 前端：数值/枚举事实、深层嵌套认知、import 语法、版本头。"""
import pytest

from npl.ast_nodes import parse_nested_arg
from npl.errors import NPLSyntaxError
from npl.parser import parse_source
from npl.validator import validate

V02 = "npl@0.2\n"


def _fact_src(body):
    return V02 + f"world w {{\n{body}\n}}\nrender {{ style = default }}"


# ---------------- N1 数值 / 枚举事实 ----------------

def test_fact_bool_number_enum():
    p = parse_source(_fact_src(
        "fact seen = true\nfact days = 9\nfact mood = calm"))
    facts = {f.name: f for f in p.world.facts}
    assert facts["seen"].vkind == "bool" and facts["seen"].value is True
    assert facts["days"].vkind == "num" and facts["days"].value == 9.0
    assert facts["mood"].vkind == "enum" and facts["mood"].value == "calm"


def test_nar_044_string_value_rejected():
    with pytest.raises(NPLSyntaxError) as ei:
        parse_source(_fact_src("fact bad = \"hello\""))
    assert ei.value.code == "NAR-044"


def test_nar_044_negative_number_allowed():
    p = parse_source(_fact_src("fact debt = -12.5"))
    f = p.world.facts[0]
    assert f.vkind == "num" and f.value == -12.5


# ---------------- N2 深层嵌套认知 ----------------

def test_deep_nested_parse_and_canonical():
    src = (V02 +
           "world w { fact x = true }\n"
           "character A { believes: X.believes(B.knows(C.does_not_know(x))) }\n"
           "character B {}\n"
           "character C {}\n"
           "character X {}\n"
           'scene "t" {\n    pov = A\n    participants = [A]\n}\n'
           "render { style = default }")
    nb = parse_source(src).characters[0].believes[0]
    assert len(nb.path) == 3
    assert nb.path[0] == ("X", "believes") and nb.path[2] == ("C", "does_not_know")
    assert nb.prop == "x"
    assert nb.display() == "X.believes(B.knows(C.does_not_know(x)))"
    assert nb.canonical() == "X|believes>B|knows>C|does_not_know>x"


def test_section_believer_not_in_path():
    # 小节主体不入 path：A { knows: B.knows(x) } = A 知道"B 知道 x"，入口从 B 起
    src = (V02 +
           "world w { fact x = true }\n"
           "character A { knows: B.knows(x) }\n"
           "character B {}\n"
           'scene "t" {\n    pov = A\n    participants = [A]\n}\n'
           "render { style = default }")
    nb = parse_source(src).characters[0].knows[0]
    assert nb.path == [("B", "knows")] and nb.display() == "B.knows(x)"


def test_nar_014_deep_holder_undeclared():
    src = (V02 +
           "world w { fact x = true }\n"
           "character A { believes: B.knows(Ghost.believes(x)) }\n"
           "character B {}\n"
           'scene "t" {\n    pov = A\n    participants = [A]\n}\n'
           "render { style = default }")
    codes = [d.code for d in validate(parse_source(src))]
    assert codes.count("NAR-014") == 1


def test_event_deep_nested_arg_validation():
    src = (V02 +
           "world w { fact x = true }\n"
           "character A {}\n"
           "character B {}\n"
           'scene "t" {\n'
           "    pov = A\n"
           "    participants = [A, B]\n"
           "    events {\n"
           "        A.realizes(B.knows(x))\n"
           "    }\n"
           "}\n"
           "render { style = default }")
    codes = [d.code for d in validate(parse_source(src))]
    assert "NAR-014" not in codes
    assert "NAR-041" not in codes


def test_parse_nested_arg_malformed():
    assert parse_nested_arg("plain_id") is None
    assert parse_nested_arg("A.knows(B.believes(x") is None  # 括号不平衡


# ---------------- N3 import 语法 ----------------

def test_import_decl_parsed():
    src = V02 + 'import "common.npl" // 公共世界\nworld w { fact x = true }'
    p = parse_source(src)
    assert len(p.imports) == 1
    assert p.imports[0].path == "common.npl"
    assert p.imports[0].desc == "公共世界"


def test_import_after_top_level_decl_rejected():
    src = V02 + 'world w { fact x = true }\nimport "common.npl"'
    with pytest.raises(NPLSyntaxError) as ei:
        parse_source(src)
    assert ei.value.code == "NAR-001"


def test_version_02_header_accepted_03_rejected():
    parse_source(V02 + "world w { fact x = true }")
    with pytest.raises(NPLSyntaxError) as ei:
        parse_source("npl@0.3\nworld w { fact x = true }")
    assert ei.value.code == "NAR-010"
