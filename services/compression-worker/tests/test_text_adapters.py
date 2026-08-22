import hashlib
from itertools import count

import pytest

from smcp_worker.adapters.text import (
    BrotliTextAdapter,
    ZstandardTextAdapter,
    generate_text_candidates,
)
from smcp_worker.models import EncodeParams, Profile, SourceObject


@pytest.fixture
def multilingual_source() -> SourceObject:
    text = "Signals from Earth — Segnali dalla Terra — إشارات من الأرض — 地球からの信号\n" * 20
    return SourceObject(text.encode(), "text/plain", "message.txt")


@pytest.mark.parametrize(
    ("adapter", "level"), [(BrotliTextAdapter(), 11), (ZstandardTextAdapter(), 19)]
)
def test_exact_round_trip(
    adapter: BrotliTextAdapter | ZstandardTextAdapter,
    level: int,
    multilingual_source: SourceObject,
) -> None:
    prepared = adapter.preprocess(multilingual_source, Profile.FAITHFUL)
    candidate = adapter.encode(prepared, EncodeParams(level=level))
    decoded = adapter.decode(candidate)
    report = adapter.measure(prepared, decoded)
    assert decoded == multilingual_source.data
    assert report.exact_round_trip
    assert report.quality_gate_passed
    assert report.original_sha256 == hashlib.sha256(multilingual_source.data).hexdigest()


def test_candidate_selection_is_real_and_stable(
    multilingual_source: SourceObject, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = count(start=0, step=2_000_000)
    monkeypatch.setattr(
        "smcp_worker.adapters.text.time.perf_counter_ns", lambda: next(clock)
    )
    candidates = generate_text_candidates(multilingual_source, Profile.ULTRA)
    assert {candidate.codec_id for candidate, _ in candidates} == {
        "text.brotli",
        "text.zstandard",
    }
    assert candidates == sorted(
        candidates, key=lambda item: (len(item[0].payload), item[0].codec_id)
    )
    assert all(report.quality_gate_passed for _, report in candidates)
    assert all(candidate.encode_duration_ms == 2 for candidate, _ in candidates)
    assert all(candidate.decode_duration_ms == 2 for candidate, _ in candidates)


@pytest.mark.parametrize("data", [b"\xff\xfe", b"valid prefix\x00hidden suffix"])
def test_rejects_non_text_payloads(data: bytes) -> None:
    source = SourceObject(data, "text/plain", "malicious.txt")
    assert not BrotliTextAdapter().probe(source).accepted
