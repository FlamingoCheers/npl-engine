"""NPL 词法器：.npl 源码 → token 流。UTF-8（兼容 BOM）。"""
import re
from .errors import NPLSyntaxError


class TokenType:
    VERSION = "VERSION"
    IDENT = "IDENT"
    STRING = "STRING"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    TIMESTAMP = "TIMESTAMP"
    NEWLINE = "NEWLINE"
    LBRACE = "{"
    RBRACE = "}"
    LBRACKET = "["
    RBRACKET = "]"
    LPAREN = "("
    RPAREN = ")"
    COLON = ":"
    COMMA = ","
    EQUALS = "="
    DOT = "."
    ARROW = "->"
    EOF = "EOF"


class Token:
    __slots__ = ("type", "value", "line", "col", "trailing")

    def __init__(self, type_, value, line, col):
        self.type = type_
        self.value = value
        self.line = line
        self.col = col
        self.trailing = None  # 行尾注释文本（语义描述，编译器会读取）

    def __repr__(self):
        return f"Token({self.type},{self.value!r},L{self.line})"


RE_VERSION = re.compile(r"npl@\d+\.\d+")
RE_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?")
RE_NUMBER = re.compile(r"\d+(?:\.\d+)?")
RE_IDENT = re.compile(r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*")
RE_STRING = re.compile(r'"[^"\n]*"')

SINGLE_PUNCT = set("{}[]():,=.")


class Lexer:
    def __init__(self, source: str):
        self.src = source
        self.pos = 0
        self.line = 1
        self.col = 1

    def _error(self, msg):
        raise NPLSyntaxError(self.line, msg)

    def _peek(self, k=0):
        p = self.pos + k
        return self.src[p] if p < len(self.src) else ""

    def _make(self, type_, value, length):
        tok = Token(type_, value, self.line, self.col)
        for _ in range(length):
            if self.src[self.pos] == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.pos += 1
        return tok

    def tokenize(self):
        tokens = []
        src = self.src
        while True:
            ch = self._peek()
            if ch == "":
                break
            if ch in " \t\r":
                self.pos += 1
                self.col += 1
                continue
            if ch == "\n":
                if not (tokens and tokens[-1].type == TokenType.NEWLINE):
                    tokens.append(self._make(TokenType.NEWLINE, "\n", 1))
                else:
                    self.pos += 1
                    self.line += 1
                    self.col = 1
                continue
            if ch == "/" and self._peek(1) == "/":
                start = self.pos + 2
                while self._peek() and self._peek() != "\n":
                    self.pos += 1
                    self.col += 1
                text = src[start:self.pos].strip()
                # 行尾注释 = 语义描述：若同一行已有 token，附着到最近的 token；
                # 独立成行的注释才是纯注释（丢弃）。
                if text and tokens and tokens[-1].type not in (
                        TokenType.NEWLINE, TokenType.EOF):
                    tokens[-1].trailing = text
                continue
            rest = src[self.pos:]
            if rest.startswith("npl@"):
                m = RE_VERSION.match(rest)
                if not m:
                    self._error("非法版本声明（应为 npl@0.1 形式）")
                tokens.append(self._make(TokenType.VERSION, m.group(0), m.end()))
                continue
            if ch == '"':
                m = RE_STRING.match(rest)
                if not m:
                    self._error("未终止的字符串")
                tokens.append(self._make(TokenType.STRING, m.group(0)[1:-1], m.end()))
                continue
            if ch.isdigit() or (ch == "-" and rest[1:2].isdigit()):
                # v0.2：'-' 后跟数字 → 负数（'->' 箭头不受影响）
                m = RE_TIMESTAMP.match(rest)
                if m and ch.isdigit():
                    tokens.append(self._make(TokenType.TIMESTAMP, m.group(0).replace("T", " "), m.end()))
                    continue
                m = RE_NUMBER.match(rest[1:] if ch == "-" else rest)
                text = ("-" if ch == "-" else "") + m.group(0)
                value = float(text) if "." in text else int(text)
                # m.end() 相对 rest[1:]，负号需补回 1 位偏移
                end = m.end() + (1 if ch == "-" else 0)
                tokens.append(self._make(TokenType.NUMBER, value, end))
                continue
            if RE_IDENT.match(ch):
                m = RE_IDENT.match(rest)
                word = m.group(0)
                if word in ("true", "false"):
                    tokens.append(self._make(TokenType.BOOLEAN, word == "true", m.end()))
                else:
                    tokens.append(self._make(TokenType.IDENT, word, m.end()))
                continue
            if ch == "-" and self._peek(1) == ">":
                tokens.append(self._make(TokenType.ARROW, "->", 2))
                continue
            if ch in SINGLE_PUNCT:
                tokens.append(self._make(ch, ch, 1))
                continue
            self._error(f"无法识别的字符 {ch!r}")
        if not (tokens and tokens[-1].type == TokenType.NEWLINE):
            tokens.append(Token(TokenType.NEWLINE, "\n", self.line, self.col))
        tokens.append(Token(TokenType.EOF, None, self.line, self.col))
        return tokens


def tokenize(source: str):
    return Lexer(source).tokenize()
