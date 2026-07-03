"""Agent intake (§14) — {URL, nhu cầu} + source_profile → clarify → DatasetPlan.

Giao thức với LLM: trả về DUY NHẤT một JSON object:
  {"type": "questions", "questions": ["..."]}   — cần hỏi thêm user
  {"type": "plan", "plan": {...DatasetPlan...}} — đủ thông tin, chốt plan
LLM trả sai định dạng → gửi lỗi lại cho LLM tự sửa (tối đa `max_retries`),
hết lượt → RuntimeError (fail-closed, không đoán mò plan). Quá `max_rounds`
vòng hỏi → ép LLM chốt plan với thông tin hiện có.

`IntakeSession` là state machine dùng chung cho CLI, API và test (LLM inject
được — test không cần server LLM).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from .plan import DatasetPlan

LLM = Callable[[list[dict[str, str]]], str]

_SYSTEM = """Bạn là planner cho pipeline crawl→clean→build dataset SFT.
Nhiệm vụ: từ NHU CẦU của user và SOURCE PROFILE (kết quả thăm dò URL: robots,
sitemap, license, render), phân tích tiêu chí chi tiết rồi lập DatasetPlan.

Chỉ trả về MỘT JSON object, không markdown, không văn xuôi ngoài JSON:
- Thiếu thông tin quan trọng → {"type":"questions","questions":["...", tối đa 3 câu]}
- Đủ thông tin → {"type":"plan","plan":{
    "goal": "mục tiêu dataset", "criteria": ["tiêu chí chi tiết", ...],
    "seeds": ["url bắt đầu — URL gốc + seed tốt từ sitemap trong profile"],
    "max_depth": 0-6, "max_pages": <=20000, "render": "auto|http|browser",
    "lang_allow": ["vi","en"], "build_format": "chatml|sharegpt|alpaca",
    "quality_min_score": số 0-1 hoặc null, "notes": "lưu ý"}}

Quy tắc: KHÔNG có cách nào bỏ qua robots/license/PII — pipeline tự enforce;
license unknown sẽ bị loại khỏi dataset publish; chọn render theo profile."""


def _parse_json(raw: str) -> dict[str, Any]:
    """Chịu được code-fence / lời dẫn thừa — lấy JSON object đầu tiên."""
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("không tìm thấy JSON object trong phản hồi")
    obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("JSON không phải object")
    return obj


@dataclass
class Step:
    """Một bước tương tác: questions (chờ user trả lời) hoặc plan (xong)."""

    questions: list[str] = field(default_factory=list)
    plan: DatasetPlan | None = None

    @property
    def done(self) -> bool:
        return self.plan is not None


class IntakeSession:
    """State machine hỏi-đáp — `start()` rồi `answer()` tới khi `step.done`."""

    def __init__(
        self,
        url: str,
        need: str,
        profile: Any,
        llm: LLM,
        *,
        max_rounds: int = 3,
        max_retries: int = 3,
    ) -> None:
        prof: dict[str, Any] = (
            asdict(profile)
            if is_dataclass(profile) and not isinstance(profile, type)
            else dict(profile)
        )
        self.llm = llm
        self.max_rounds = max_rounds
        self.max_retries = max_retries
        self.rounds = 0
        self.final_plan: DatasetPlan | None = None  # set khi LLM chốt plan hợp lệ
        self.messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    f"NHU CẦU: {need}\nURL: {url}\n"
                    f"SOURCE PROFILE: {json.dumps(prof, ensure_ascii=False)}"
                ),
            },
        ]

    def start(self) -> Step:
        return self._advance()

    def answer(self, answers: list[str]) -> Step:
        self.messages.append(
            {"role": "user", "content": "TRẢ LỜI CỦA USER:\n" + "\n".join(answers)}
        )
        return self._advance()

    def _advance(self) -> Step:
        for _attempt in range(self.max_retries):
            raw = self.llm(self.messages)
            self.messages.append({"role": "assistant", "content": raw})
            try:
                obj = _parse_json(raw)
                kind = obj.get("type")
                if kind == "plan":
                    self.final_plan = DatasetPlan(**obj["plan"])
                    return Step(plan=self.final_plan)
                if kind == "questions":
                    qs = [str(q) for q in obj.get("questions", []) if str(q).strip()]
                    if not qs:
                        raise ValueError("questions rỗng")
                    if self.rounds >= self.max_rounds:
                        # Hết quota hỏi — ép chốt plan (dùng attempt tiếp theo).
                        self.messages.append(
                            {
                                "role": "user",
                                "content": "Không hỏi thêm nữa — chốt plan ngay "
                                "với thông tin hiện có.",
                            }
                        )
                        continue
                    self.rounds += 1
                    return Step(questions=qs[:3])
                raise ValueError(f"type không hợp lệ: {kind!r}")
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                # Pydantic ValidationError là ValueError — gửi lỗi cho LLM tự sửa.
                self.messages.append(
                    {
                        "role": "user",
                        "content": f"Phản hồi không hợp lệ ({exc}). "
                        "Trả lại đúng MỘT JSON object theo định dạng đã nêu.",
                    }
                )
        raise RuntimeError(
            f"agent không tạo được plan hợp lệ sau {self.max_retries} lần "
            "(§14 fail-closed)"
        )
