"""S3 cleaner (§5) — normalize, filters, dedup, PII, decontam, pipeline end-to-end."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from crawl_datasets_cleaner.decontam import Decontaminator
from crawl_datasets_cleaner.dedup import LSHIndex, MinHasher, content_hash, scope_key
from crawl_datasets_cleaner.filters import c4_filter, fineweb_custom, gopher_quality
from crawl_datasets_cleaner.normalize import normalize_text
from crawl_datasets_cleaner.pii import redact_pii
from crawl_datasets_cleaner.pipeline import run
from crawl_datasets_common.provenance import verify_provenance
from crawl_datasets_common.settings import GopherQuality, Settings, VIOverrides

# ~60-word coherent docs that pass every §5.3 filter.
GOOD_EN = (
    "The quick brown fox jumps over a lazy dog beside the calm river every "
    "morning. Researchers have shown that consistent reading improves memory "
    "and vocabulary across many age groups. Students who practise writing "
    "regularly tend to express complex ideas with greater clarity and "
    "confidence, and teachers report steady progress throughout the school year."
)
GOOD_VI = (
    "Trong những năm gần đây, việc học tiếng Việt trực tuyến đã trở nên phổ "
    "biến hơn với rất nhiều người ở khắp nơi. Các khóa học được thiết kế để "
    "giúp người học nắm vững ngữ pháp và mở rộng vốn từ vựng một cách hiệu "
    "quả nhất. Nhiều học viên cho biết rằng họ đã tiến bộ rõ rệt sau một thời "
    "gian ngắn luyện tập đều đặn mỗi ngày."
)


def test_normalize_forces_nfc() -> None:
    decomposed = unicodedata.normalize("NFD", "tiếng Việt")
    out = normalize_text(decomposed)
    assert out == unicodedata.normalize("NFC", out)
    # cùng nội dung ở dạng Unicode khác nhau → cùng hash sau normalize (§5.1)
    assert content_hash(normalize_text(decomposed)) == content_hash(
        normalize_text(unicodedata.normalize("NFC", "tiếng Việt"))
    )


def test_gopher_word_count_floor() -> None:
    assert gopher_quality("Hello world.", GopherQuality(), "en", VIOverrides()) == (
        "gopher_word_count:2"
    )


def test_gopher_vn_uses_vn_stopwords_not_english() -> None:
    cfg, vi = GopherQuality(), VIOverrides()
    # lang=vi + override → dùng stop-word VN → pass
    assert gopher_quality(GOOD_VI, cfg, "vi", vi) is None
    # cùng text nhưng coi là 'en' → EN stop-words không khớp → drop (§5.3)
    assert gopher_quality(GOOD_VI, cfg, "en", vi) == "gopher_stopwords"


def test_c4_drops_lorem_ipsum_and_untermined_lines() -> None:
    _, reason = c4_filter("Lorem ipsum dolor sit amet.")
    assert reason == "c4_lorem_ipsum"
    _, reason2 = c4_filter("no terminal punctuation here\nanother dangling line")
    assert reason2 == "c4_all_lines_dropped"
    kept, reason3 = c4_filter("This sentence ends properly.\nSo does this one.")
    assert reason3 is None and "properly" in kept


def test_fineweb_flags_list_like() -> None:
    assert fineweb_custom("- a\n- b\n- c\n- d") == "fineweb_list_like"
    assert fineweb_custom(GOOD_EN) is None


def test_minhash_is_deterministic_by_seed() -> None:
    a = MinHasher(112, 5, seed=42).signature(GOOD_EN)
    b = MinHasher(112, 5, seed=42).signature(GOOD_EN)
    assert a is not None and a == b
    assert MinHasher(112, 5, seed=7).signature(GOOD_EN) != a  # seed khác → khác


def test_lsh_catches_near_duplicate() -> None:
    lsh = LSHIndex(bands=14, rows=8)
    hasher = MinHasher(112, 5, seed=42)
    near = GOOD_EN.replace("confidence", "assurance")  # đổi 1 từ
    sig_a = hasher.signature(GOOD_EN)
    sig_b = hasher.signature(near)
    assert sig_a is not None and sig_b is not None
    scope = scope_key("https://example.com/a", "per_source")
    assert lsh.add_or_is_dup(scope, "a", sig_a) is False
    assert lsh.add_or_is_dup(scope, "b", sig_b) is True  # near-dup


def test_pii_vn_regex_redacts_and_respects_flag() -> None:
    text = "Liên hệ an@example.com hoặc +84912345678, CCCD 012345678901."
    redacted, types = redact_pii(text, vi_regex=True)
    assert "an@example.com" not in redacted and "+84912345678" not in redacted
    assert "012345678901" not in redacted
    assert set(types) >= {"email", "phone_vn", "cccd_cmnd"}
    # vi_regex=False → chỉ email/IP (FineWeb tối thiểu §5.5)
    _, types2 = redact_pii(text, vi_regex=False)
    assert "phone_vn" not in types2 and "cccd_cmnd" not in types2


def test_decontam_13gram_match() -> None:
    bench = "the capital of france is paris and it has been for many centuries indeed"
    dec = Decontaminator.from_texts(13, [bench])
    assert dec.active
    assert dec.is_contaminated("Note: " + bench + " today.") is True
    assert (
        dec.is_contaminated("A completely unrelated sentence about something else.")
        is False
    )


def _write_jsonl(path: Path, docs: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(d) for d in docs), encoding="utf-8")


def test_pipeline_end_to_end(tmp_path: Path) -> None:
    in_dir = tmp_path / "extracted"
    out_dir = tmp_path / "out"
    _write_jsonl(
        in_dir / "part-0.jsonl",
        [
            {"text": GOOD_EN, "source_url": "https://a.com/1", "license": "cc-by"},
            {
                "text": GOOD_VI,
                "source_url": "https://b.vn/1",
                "extractor": "trafilatura",
            },
            {"text": GOOD_EN, "source_url": "https://a.com/2"},  # exact dup → drop
            {"text": "Too short.", "source_url": "https://a.com/3"},  # gopher drop
            {"text": GOOD_EN},  # thiếu source_url → fail-closed drop
        ],
    )

    stats = run(in_dir, out_dir, Settings())

    assert stats.seen == 5
    assert stats.kept == 2  # GOOD_EN + GOOD_VI
    assert "exact_dup" in stats.dropped
    assert "no_source_url" in stats.dropped
    assert any(r.startswith("gopher_word_count") for r in stats.dropped)

    clean = out_dir / "clean" / "part-00000.jsonl"
    records = [json.loads(ln) for ln in clean.read_text().splitlines()]
    assert len(records) == 2
    for rec in records:
        assert rec["id"] and rec["prov"]["pipeline_version"] == "1.3.0"
        verify_provenance(rec["prov"])  # §0 — provenance đầy đủ, không raise
    assert (out_dir / "clean" / "_SUCCESS").exists()
    langs = {r["lang"] for r in records}
    assert langs == {"en", "vi"}
