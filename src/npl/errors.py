"""NPL 错误类型与诊断结构。"""


class NPLSyntaxError(Exception):
    """语法/结构错误（NAR-001/010/011/012）。解析阶段抛出。"""

    def __init__(self, line: int, message: str, code: str = "NAR-001"):
        self.line = line
        self.message = message
        self.code = code
        super().__init__(f"{code} [line {line}] {message}")


class Diagnostic:
    """语义校验诊断（validator 产出）。"""

    def __init__(self, code: str, severity: str, line: int, message: str):
        self.code = code
        self.severity = severity  # "error" | "warning"
        self.line = line
        self.message = message

    def __repr__(self):
        return f"Diagnostic({self.code},{self.severity},L{self.line},{self.message!r})"

    def as_dict(self):
        return {"code": self.code, "severity": self.severity,
                "line": self.line, "message": self.message}
