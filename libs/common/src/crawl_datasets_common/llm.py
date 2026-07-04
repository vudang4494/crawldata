"""LLM local client — API OpenAI-compatible, httpx gated. Dùng chung 2 nơi:
agent intake (§14) và builder synth QA (§7.1 Phase B).

Một code path phủ Ollama (`/v1`), llama.cpp server, LM Studio — model GGUF local
(mặc định §9.3 `agent.model`). Thiếu httpx hoặc server không chạy → RuntimeError
tường minh (fail-closed); pipeline thường KHÔNG phụ thuộc LLM — các stage chạy
độc lập khi backend vắng, chỉ tính năng bật LLM mới đòi backend.
"""

from __future__ import annotations

import json
from typing import Any

from .settings import AgentSettings

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
                "LLM client cần httpx (extra [llm]/[synth]) — fail-closed"
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
                f"LLM không phản hồi tại {self.cfg.base_url} "
                f"(model={self.cfg.model}): {exc}"
            ) from exc
        data = resp.json()
        return str(data["choices"][0]["message"]["content"])


def extract_json_object(raw: str) -> dict[str, Any]:
    """Chịu được code-fence / lời dẫn thừa — lấy JSON object đầu tiên trong text."""
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("không tìm thấy JSON object trong phản hồi")
    obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("JSON không phải object")
    return obj
