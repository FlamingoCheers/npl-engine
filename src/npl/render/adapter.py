"""LLM 适配器层。

设计（用户决策）：同时支持线上 API 与本地大模型——凡 openai-compatible
协议（DeepSeek / Qwen / 智谱 / Ollama / LM Studio …）统一走
OpenAICompatibleAdapter；mock 适配器提供离线确定性输出用于管线测试。

API key 一律从环境变量读取（api_key_env 指定变量名），绝不写进配置文件。
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class RenderError(Exception):
    pass


class MockAdapter:
    """离线确定性适配器：渲染任务回显指令结构；抽取任务返回干净 JSON。"""

    name = "mock"

    def describe(self):
        return "mock"

    def chat(self, system, user, temperature=None):
        if "命题抽取器" in system:
            return json.dumps({
                "fact_assertions": [], "omniscient_spans": [],
                "inner_mind_spans": [], "knowledge_claims": [],
                "concealed_evidence_spans": [],
                "reveal_achieved": {"fact": "", "achieved": True, "span": ""},
                "emotions_named": [],
            }, ensure_ascii=False)
        head = system.split("\n", 1)[0]
        return "\n".join([
            "（mock 渲染输出 — 未调用真实 LLM；用于管线测试）",
            "",
            head,
            "",
            "—— 以下为编译出的渲染指令 ——",
            "",
            user,
        ])


class OpenAICompatibleAdapter:
    def __init__(self, name, base_url, model, api_key=None,
                 timeout=180, temperature=0.8, max_tokens=8192):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    def describe(self):
        return f"{self.name}:{self.model}"

    def chat(self, system, user, temperature=None):
        url = self.base_url + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,  # 思考型模型需余量给 reasoning
        }
        headers = {"Content-Type": "application/json",
                   "User-Agent": "npl-engine/0.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            raise RenderError(f"LLM 调用失败 HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RenderError(
                f"LLM 调用失败（网络不可达）: {e.reason}；"
                f"请检查 base_url={self.base_url!r} 与网络/代理设置") from e
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RenderError(
                f"LLM 返回格式异常: {json.dumps(data, ensure_ascii=False)[:500]}") from None


DEFAULT_CONFIG = {
    "adapters": {"mock": {"type": "mock"}},
    "render": {"adapter": "mock"},
    "extract": {"adapter": "mock"},
}


def load_config(path=None):
    """加载 npl.config.json；未指定时找当前目录；仍无则用内置默认。"""
    if path is None:
        cwd_config = Path("npl.config.json")
        if cwd_config.exists():
            path = cwd_config
    if path is None:
        return json.loads(json.dumps(DEFAULT_CONFIG))
    cfg = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return {
        "adapters": {**DEFAULT_CONFIG["adapters"], **cfg.get("adapters", {})},
        "render": cfg.get("render", DEFAULT_CONFIG["render"]),
        "extract": cfg.get("extract", DEFAULT_CONFIG["extract"]),
    }


def create_adapter(config, task="render", override=None):
    name = override or config.get(task, {}).get("adapter") or "mock"
    spec = config["adapters"].get(name)
    if spec is None:
        raise RenderError(
            f"未配置的适配器 '{name}'（可用: {', '.join(sorted(config['adapters']))}）")
    kind = spec.get("type")
    if kind == "mock":
        return MockAdapter()
    if kind == "openai-compatible":
        base_url = spec.get("base_url", "")
        if not base_url:
            raise RenderError(f"适配器 '{name}' 缺少 base_url")
        env_var = spec.get("api_key_env", "")
        api_key = os.environ.get(env_var, "") if env_var else None
        return OpenAICompatibleAdapter(
            name=name,
            base_url=base_url,
            model=spec.get("model", ""),
            api_key=api_key,
            timeout=spec.get("timeout", 180),
            temperature=spec.get("temperature", 0.8),
            max_tokens=spec.get("max_tokens", 8192),
        )
    raise RenderError(f"适配器 '{name}' 类型未知: {kind!r}（可用: mock / openai-compatible）")
