"""词法器测试。"""
import pytest

from npl.errors import NPLSyntaxError
from npl.lexer import tokenize


def test_version_and_timestamp():
    toks = tokenize('npl@0.1\ntime = 2047-03-17 23:40\n')
    assert toks[0].type == "VERSION"
    assert toks[0].value == "npl@0.1"
    ts = [t for t in toks if t.type == "TIMESTAMP"]
    assert ts[0].value == "2047-03-17 23:40"


def test_date_only_timestamp():
    toks = tokenize("2047-03-17\n")
    assert toks[0].type == "TIMESTAMP"


def test_chinese_ident():
    toks = tokenize("character 林黛玉 {\n}\n")
    idents = [t.value for t in toks if t.type == "IDENT"]
    assert "林黛玉" in idents


def test_boolean_values():
    toks = tokenize("fact a = true\nfact b = false\n")
    bools = [t.value for t in toks if t.type == "BOOLEAN"]
    assert bools == [True, False]


def test_comment_skipped():
    toks = tokenize("// 注释\nfact ok = true // 尾注\n")
    assert all(not (t.type == "IDENT" and t.value == "注释") for t in toks)
    assert [t.value for t in toks if t.type == "BOOLEAN"] == [True]


def test_arrow_and_punct():
    types = [t.type for t in tokenize("a: x -> y\n")]
    assert "->" in types


def test_newline_collapse():
    types = [t.type for t in tokenize("a\n\n\nb\n")]
    assert types.count("NEWLINE") == 2


def test_bad_char_semicolon():
    with pytest.raises(NPLSyntaxError):
        tokenize("fact a = true;\n")


def test_unclosed_string():
    with pytest.raises(NPLSyntaxError):
        tokenize('scene "夜车 {\n}\n')
