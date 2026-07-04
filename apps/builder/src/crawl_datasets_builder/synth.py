"""Synthetic QA (§7.1 Phase B) — clean text → cặp instruction-QA bằng LLM local.

LLM chỉ SINH nội dung từ text đã qua đủ gate ở S3 (license/PII/decontam);
provenance giữ `source_url` gốc + đánh dấu `synthetic=true`, `synth_model` (§7.2).

Fail modes:
- `enabled=true` mà thiếu httpx → RuntimeError ngay khi init (fail-closed).
- LLM trả JSON hỏng per-doc → retry kèm phản hồi lỗi → `SynthError` (caller
  drop `synth_failed`, fail-visible — không chặn cả run).
`llm` inject được (callable) → test không cần server.
"""

from __future__ import annotations

from collections.abc import Callable

from crawl_datasets_common.llm import ChatLLM, extract_json_object
from crawl_datasets_common.settings import AgentSettings, SynthConfig

LLM = Callable[[list[dict[str, str]]], str]

_SYSTEM = (
    "Bạn là người tạo dữ liệu fine-tuning chất lượng cao. Từ ĐOẠN VĂN cho trước, "
    "sinh đúng {n} cặp hỏi-đáp CÙNG NGÔN NGỮ với đoạn văn. Câu hỏi tự nhiên như "
    "người dùng thật; câu trả lời đầy đủ, chính xác và chỉ dựa trên thông tin "
    "TRONG đoạn văn (tuyệt đối không bịa thêm). Chỉ trả về MỘT JSON object, "
    'không markdown: {{"pairs": [{{"question": "...", "answer": "..."}}]}}'
)


class SynthError(RuntimeError):
    """LLM không sinh được cặp QA hợp lệ cho doc này (sau retry)."""


class QASynthesizer:
    """generate(text) → [(question, answer), ...] — tối đa `questions_per_doc`."""

    def __init__(
        self, cfg: SynthConfig, agent_cfg: AgentSettings, llm: LLM | None = None
    ) -> None:
        self.cfg = cfg
        self.model = agent_cfg.model
        self._llm: LLM = llm if llm is not None else ChatLLM(agent_cfg)

    def generate(self, text: str, *, max_retries: int = 2) -> list[tuple[str, str]]:
        snippet = text[: self.cfg.max_chars]
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYSTEM.format(n=self.cfg.questions_per_doc)},
            {"role": "user", "content": f"ĐOẠN VĂN:\n{snippet}"},
        ]
        last_err = "?"
        for _attempt in range(max_retries):
            raw = self._llm(messages)
            try:
                obj = extract_json_object(raw)
                pairs = [
                    (str(p["question"]).strip(), str(p["answer"]).strip())
                    for p in obj["pairs"]
                ]
                pairs = [(q, a) for q, a in pairs if q and a]
                if not pairs:
                    raise ValueError("pairs rỗng")
                return pairs[: self.cfg.questions_per_doc]
            except (ValueError, KeyError, TypeError) as exc:
                last_err = str(exc)
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": f"JSON không hợp lệ ({exc}) — trả lại đúng "
                        "MỘT JSON object theo định dạng đã nêu.",
                    }
                )
        raise SynthError(f"không sinh được QA hợp lệ sau {max_retries} lần: {last_err}")


def build_synthesizer(
    cfg: SynthConfig, agent_cfg: AgentSettings
) -> QASynthesizer | None:
    """None khi tắt; RuntimeError khi bật mà thiếu httpx backend (fail-closed)."""
    if not cfg.enabled:
        return None
    return QASynthesizer(cfg, agent_cfg)
