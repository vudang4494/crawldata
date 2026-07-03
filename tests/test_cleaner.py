"""S3 cleaner (§5) — normalize, filters, dedup, PII, decontam, pipeline end-to-end."""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

import pytest
from crawl_datasets_cleaner.decontam import Decontaminator
from crawl_datasets_cleaner.dedup import LSHIndex, MinHasher, content_hash, scope_key
from crawl_datasets_cleaner.filters import (
    c4_filter,
    fineweb_custom,
    gopher_quality,
    gopher_repetition,
)
from crawl_datasets_cleaner.normalize import normalize_text
from crawl_datasets_cleaner.pii import build_presidio, redact_pii
from crawl_datasets_cleaner.pipeline import run
from crawl_datasets_common.provenance import verify_provenance
from crawl_datasets_common.settings import (
    GopherQuality,
    QualityConfig,
    Settings,
    VIOverrides,
)

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


def test_gopher_repetition_flags_dupes() -> None:
    assert gopher_repetition(GOOD_EN) is None  # doc tốt không bị cờ
    assert gopher_repetition("copy this line.\n" * 20) == "rep_dup_lines"
    # 5-gram lặp nhiều → cờ top/dup n-gram (§5.3 mở rộng)
    assert (gopher_repetition("alpha beta gamma delta epsilon " * 15) or "").startswith(
        "rep_"
    )


def test_build_presidio_none_without_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ép thiếu backend (env có thể đã cài presidio — gated backend):
    # gate phải trả None → fallback regex-only (§5.5), deterministic bất kể env.
    monkeypatch.setitem(sys.modules, "presidio_analyzer", None)
    assert build_presidio() is None


# --- §5.3 quality classifier (P1) ---------------------------------------------


class _FakeFastTextModel:
    """fastText giả — predict trả (labels, probs) như model thật."""

    def __init__(self, hq_prob: float) -> None:
        self._hq = hq_prob

    def predict(self, text: str, k: int = 1) -> tuple[list[str], list[float]]:
        return ["__label__hq", "__label__lq"], [self._hq, 1.0 - self._hq]


def _quality_settings(
    monkeypatch: pytest.MonkeyPatch, *, hq_prob: float, min_score: float
) -> Settings:
    from crawl_datasets_cleaner import quality

    class _FakeFastTextModule:
        @staticmethod
        def load_model(path: str) -> _FakeFastTextModel:
            return _FakeFastTextModel(hq_prob)

    monkeypatch.setattr(quality, "_fasttext", _FakeFastTextModule)
    s = Settings()
    s.clean.quality.enabled = True
    s.clean.quality.model_path = "fake-edu-classifier.bin"
    s.clean.quality.min_score = min_score
    return s


def test_quality_scorer_disabled_returns_none() -> None:
    from crawl_datasets_cleaner.quality import build_scorer

    assert build_scorer(QualityConfig()) is None  # enabled=false mặc định


def test_quality_enabled_without_backend_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crawl_datasets_cleaner import quality

    monkeypatch.setattr(quality, "_fasttext", None)
    with pytest.raises(RuntimeError):
        quality.build_scorer(QualityConfig(enabled=True, model_path="m.bin"))


def test_quality_enabled_without_model_path_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crawl_datasets_cleaner import quality

    monkeypatch.setattr(quality, "_fasttext", object())  # backend có, thiếu model
    with pytest.raises(RuntimeError):
        quality.build_scorer(QualityConfig(enabled=True))


def test_transformer_scorer_picks_head_by_lang() -> None:
    # §5.3 backend transformer — head per-lang; lang không có head → fail-closed.
    from crawl_datasets_cleaner.quality import TransformerQualityScorer

    cfg = QualityConfig(enabled=True, backend="transformer", model_path="epfml/x")
    scorer = TransformerQualityScorer(
        cfg,
        embed=lambda text: len(text),
        heads={"vi": lambda emb: 0.9, "en": lambda emb: 0.2},
    )
    assert scorer.score("xin chào", "vi") == pytest.approx(0.9)
    assert scorer.score("hello", "en") == pytest.approx(0.2)
    with pytest.raises(RuntimeError, match="fail-closed"):
        scorer.score("hola", "es")


def test_transformer_backend_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from crawl_datasets_cleaner import quality

    cfg = QualityConfig(enabled=True, backend="transformer", model_path="epfml/x")
    # lang_allow có lang không được lang_heads cover → raise TRƯỚC khi cần torch.
    with pytest.raises(RuntimeError, match="lang_heads"):
        quality.build_scorer(cfg, ["vi", "en", "ja"])
    # thiếu torch/transformers → raise (extra cleaner[quality]).
    monkeypatch.setattr(quality, "_torch", None)
    monkeypatch.setattr(quality, "_transformers", None)
    with pytest.raises(RuntimeError, match="torch"):
        quality.build_scorer(cfg, ["vi", "en"])


def test_pipeline_scores_vi_with_injected_transformer() -> None:
    # DocCleaner chấm doc VN bằng head vi (score truyền lang — §5.3).
    from crawl_datasets_cleaner.pipeline import DocCleaner
    from crawl_datasets_cleaner.quality import TransformerQualityScorer

    s = Settings()
    cleaner = DocCleaner(s)
    cleaner.quality = TransformerQualityScorer(
        s.clean.quality,
        embed=lambda text: text,
        heads={"vi": lambda emb: 0.8, "en": lambda emb: 0.3},
    )
    rec, reason = cleaner.clean_one(
        {"text": GOOD_VI, "source_url": "https://vi.example/1", "license": "cc-by"}
    )
    assert reason is None and rec is not None
    assert rec["quality"] == pytest.approx(0.8)  # head vi, không phải en
    assert "quality" in rec["prov"]["filters_passed"]


def test_quality_classifier_scores_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5.3 — score ghi vào record + filter theo min_score, chạy cuối chuỗi."""
    from crawl_datasets_cleaner.pipeline import DocCleaner

    doc = {"text": GOOD_EN, "source_url": "https://a.com/q", "license": "cc-by"}

    keep = DocCleaner(_quality_settings(monkeypatch, hq_prob=0.9, min_score=0.5))
    rec, reason = keep.clean_one(doc)
    assert reason is None and rec is not None
    assert rec["quality"] == pytest.approx(0.9)
    assert "quality" in rec["prov"]["filters_passed"]

    strict = DocCleaner(_quality_settings(monkeypatch, hq_prob=0.9, min_score=0.95))
    rec2, reason2 = strict.clean_one(doc)
    assert rec2 is None and reason2 == "quality_score_low"


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


def test_presidio_gated_by_lang() -> None:
    # §5.5 — NER English chỉ áp cho doc thuộc pii.presidio_langs (mặc định [en]);
    # doc VN chỉ chạy VN regex — EN NER trên VN false-positive phá text.
    from crawl_datasets_cleaner.pipeline import DocCleaner

    class _OverRedactingNER:
        """Giả lập NER EN over-redact: mọi lời gọi đều thay toàn bộ text."""

        def redact(self, text: str) -> tuple[str, list[str]]:
            return "<PERSON>", ["PERSON"]

    cleaner = DocCleaner(Settings())
    cleaner.presidio = _OverRedactingNER()

    rec_vi, reason_vi = cleaner.clean_one(
        {"text": GOOD_VI, "source_url": "https://vi.example/1", "license": "cc-by"}
    )
    assert reason_vi is None and rec_vi is not None
    assert "PERSON" not in rec_vi["pii_found"]
    assert "tiếng Việt" in rec_vi["text"]  # text VN nguyên vẹn, không qua NER EN

    rec_en, reason_en = cleaner.clean_one(
        {"text": GOOD_EN, "source_url": "https://en.example/1", "license": "cc-by"}
    )
    assert reason_en is None and rec_en is not None
    assert rec_en["text"] == "<PERSON>" and "PERSON" in rec_en["pii_found"]


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


def test_c4_shrunk_doc_dropped() -> None:
    # Pilot finding: doc dài qua Gopher nhưng C4 gọt (dòng không kết câu) còn
    # rất ngắn → phải drop, không được lọt vào clean tier.
    from crawl_datasets_cleaner.pipeline import DocCleaner

    lines = [  # 12 dòng nav đa dạng (~96 từ, qua Gopher) — không dòng nào kết câu
        "Home page and latest news from the region",
        "Contact the editorial team with your questions",
        "About the mission of this small newsroom",
        "Archive of older stories to browse today",
        "Weather updates and traffic notes for drivers",
        "Sports coverage with scores from local teams",
        "Culture section on books music and film",
        "Business news with markets and company reports",
        "Opinion pieces that challenge the usual thinking",
        "Health advice from doctors and trusted experts",
        "Science stories about space oceans and climate",
        "Travel guides to cities villages and mountains",
    ]
    text = "\n".join(lines) + "\nOnly this short sentence survives the filter."
    doc = {"text": text, "source_url": "https://a.com/nav", "license": "cc-by"}
    rec, reason = DocCleaner(Settings()).clean_one(doc)
    assert rec is None and reason is not None
    assert reason.startswith("c4_shrunk_words:")
