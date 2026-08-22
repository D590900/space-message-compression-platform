from pathlib import Path

import pytest

from smcp_worker.adapters.external import executable, run
from smcp_worker.adapters.video import Av1VideoAdapter
from smcp_worker.models import EncodeParams, Profile, SourceObject


@pytest.fixture
def test_video(tmp_path: Path) -> SourceObject:
    ffmpeg = executable("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is not installed")
    output = tmp_path / "source.mkv"
    run(
        (
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x96:rate=5:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            "-y",
            str(output),
        ),
        timeout=60,
    )
    return SourceObject(output.read_bytes(), "video/x-matroska", "source.mkv")


def test_av1_decode_and_quality_gate(test_video: SourceObject) -> None:
    adapter = Av1VideoAdapter()
    capability = adapter.capabilities()
    if not capability.enabled:
        pytest.skip(capability.disabled_reason or "codec is disabled")
    prepared = adapter.preprocess(test_video, Profile.FAITHFUL)
    candidate = adapter.encode(prepared, EncodeParams(level=32))
    decoded = adapter.decode(candidate)
    decoded_again = adapter.decode(candidate)
    report = adapter.measure(prepared, decoded)

    assert candidate.payload
    assert decoded_again == decoded
    assert report.quality_gate_passed
    assert report.metrics["classification"] == "GENERIC"
    duration_delta = report.metrics["duration_delta_seconds"]
    assert isinstance(duration_delta, float)
    assert duration_delta <= 0.05


def test_non_video_is_rejected() -> None:
    source = SourceObject(b"not video", "text/plain", "message.txt")
    assert not Av1VideoAdapter().probe(source).accepted
