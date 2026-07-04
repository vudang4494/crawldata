"""Re-export — `ChatLLM` chuyển về `crawl_datasets_common.llm` (Phase B: dùng
chung giữa agent intake §14 và builder synth §7.1). Giữ module này để import
path cũ không vỡ."""

from crawl_datasets_common.llm import ChatLLM, Message

__all__ = ["ChatLLM", "Message"]
