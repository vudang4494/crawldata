"""SFT formats (§7.1) — clean doc → ChatML / ShareGPT / Alpaca record.

P0 mapping (document corpus → single-turn): text thành 1 turn assistant, hoặc dùng
`messages` sẵn có nếu clean record đã có. Meta mang provenance + id + lang (§7.2).
"""

from __future__ import annotations

from typing import Any

from crawl_datasets_common.schema import Message, SFTRecord

_SHAREGPT_ROLE = {"system": "system", "user": "human", "assistant": "gpt"}


def to_messages(doc: dict[str, Any]) -> list[Message]:
    """Clean doc → messages. Có sẵn `messages` → dùng; ngược lại wrap text (1 turn)."""
    raw = doc.get("messages")
    if isinstance(raw, list) and raw:
        return [Message(role=m["role"], content=m["content"]) for m in raw]
    return [Message(role="assistant", content=str(doc.get("text", "")))]


def serialize(record: SFTRecord, fmt: str) -> dict[str, Any]:
    """SFTRecord → dict theo format (§7.1). Meta luôn kèm provenance + id + lang."""
    meta = {"id": record.id, "lang": record.lang, **record.prov.model_dump(mode="json")}
    if fmt == "sharegpt":
        conv = [
            {"from": _SHAREGPT_ROLE[m.role], "value": m.content}
            for m in record.messages
        ]
        return {"conversations": conv, "meta": meta}
    if fmt == "alpaca":
        instruction = next((m.content for m in record.messages if m.role == "user"), "")
        output = next(
            (m.content for m in record.messages if m.role == "assistant"),
            record.messages[-1].content,
        )
        return {"instruction": instruction, "input": "", "output": output, "meta": meta}
    return {"messages": [m.model_dump() for m in record.messages], "meta": meta}
