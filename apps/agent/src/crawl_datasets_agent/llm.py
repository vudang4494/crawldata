"""LLM client cho agent (§14) — API OpenAI-compatible, httpx gated.

Một code path phủ Ollama (`/v1`), llama.cpp server và LM Studio — model GGUF
local (mặc định §9.3 `agent.model`: Gemma QAT). Thiếu httpx hoặc server không
chạy → RuntimeError tường minh (fail-closed); pipeline thường KHÔNG phụ thuộc
agent nên các stage vẫn chạy độc lập.
"""

from __future__ import annotations

from typing import Any

from crawl_datasets_common.settings import AgentSettings

_httpx: Any = None
try:
    import httpx as _httpx_mod

    _httpx = _httpx_mod
except ImportError:  # pragma: no cover
    _httpx = None

Message = dict[str, str]


class ChatLLM:
    """POST {base_url}/chat/completions → content của choice đầu tiên."""

    def __init__(self, cfg: AgentSettings) -> None:
        if _httpx is None:
            raise RuntimeError(
                "agent cần httpx để gọi LLM (extra crawl-datasets-agent[llm]) "
                "— §14 fail-closed"
            )
        self.cfg = cfg

    def __call__(self, messages: list[Message]) -> str:
        try:
            resp = _httpx.post(
                f"{self.cfg.base_url.rstrip('/')}/chat/completions",
                json={
                    "model": self.cfg.model,
                    "messages": messages,
                    "temperature": self.cfg.temperature,
                },
                timeout=self.cfg.timeout_s,
            )
            resp.raise_for_status()
        except Exception as exc:  # network boundary — báo rõ, không nuốt lỗi
            raise RuntimeError(
                f"agent LLM không phản hồi tại {self.cfg.base_url} "
                f"(model={self.cfg.model}): {exc}"
            ) from exc
        data = resp.json()
        return str(data["choices"][0]["message"]["content"])
