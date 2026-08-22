from pathlib import Path

import pytest

from smcp_worker.adapters.external import executable, run
from smcp_worker.adapters.image import AvifImageAdapter, JpegXlImageAdapter
from smcp_worker.models import EncodeParams, Profile, SourceObject


@pytest.fixture
def test_image(tmp_path: Path) -> SourceObject:
    ffmpeg = executable("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is not installed")
    output = tmp_path / "source.png"
    run(
        (
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x128:rate=1",
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-y",
            str(output),
        )
    )
    return SourceObject(output.read_bytes(), "image/png", "source.png")


@pytest.mark.parametrize(
    ("adapter", "level"), [(AvifImageAdapter(), 28), (JpegXlImageAdapter(), 10)]
)
def test_image_codec_decode_and_quality_gate(
    adapter: AvifImageAdapter | JpegXlImageAdapter,
    level: int,
    test_image: SourceObject,
) -> None:
    capability = adapter.capabilities()
    if not capability.enabled:
        pytest.skip(capability.disabled_reason or "codec is disabled")
    prepared = adapter.preprocess(test_image, Profile.FAITHFUL)
    candidate = adapter.encode(prepared, EncodeParams(level=level))
    decoded = adapter.decode(candidate)
    report = adapter.measure(prepared, decoded)

    assert candidate.payload
    assert report.quality_gate_passed
    assert isinstance(report.metrics["ms_ssim"], float)
    assert report.metrics["lpips_status"] == "disabled:no_versioned_weights"


def test_missing_binary_is_an_explicit_disabled_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("smcp_worker.adapters.image.executable", lambda _name: None)
    capability = AvifImageAdapter().capabilities()
    assert not capability.enabled
    assert capability.disabled_reason
    assert capability.install_hint
