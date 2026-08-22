from pathlib import Path

import pytest

from smcp_worker.adapters.audio import OpusAudioAdapter
from smcp_worker.adapters.external import executable, run
from smcp_worker.models import EncodeParams, Profile, SourceObject


@pytest.fixture
def test_audio(tmp_path: Path) -> SourceObject:
    ffmpeg = executable("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is not installed")
    output = tmp_path / "source.wav"
    run(
        (
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(output),
        )
    )
    return SourceObject(output.read_bytes(), "audio/wav", "source.wav")


def test_opus_decode_and_quality_gate(test_audio: SourceObject) -> None:
    adapter = OpusAudioAdapter()
    capability = adapter.capabilities()
    if not capability.enabled:
        pytest.skip(capability.disabled_reason or "codec is disabled")
    prepared = adapter.preprocess(test_audio, Profile.FAITHFUL)
    candidate = adapter.encode(prepared, EncodeParams(level=20))
    decoded = adapter.decode(candidate)
    report = adapter.measure(prepared, decoded)

    assert candidate.payload.startswith(b"OggS")
    assert report.quality_gate_passed
    duration_delta = report.metrics["duration_delta_seconds"]
    assert isinstance(duration_delta, float)
    assert duration_delta <= 0.02
    assert report.metrics["intelligibility_status"] == "not_evaluated:no_versioned_asr_model"


def test_non_audio_is_rejected() -> None:
    source = SourceObject(b"not audio", "text/plain", "message.txt")
    assert not OpusAudioAdapter().probe(source).accepted
