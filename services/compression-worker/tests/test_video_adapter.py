import hashlib
from pathlib import Path

import pytest

from smcp_worker.adapters.external import executable, run
from smcp_worker.adapters.video import Av1VideoAdapter, LivePortraitVideoAdapter
from smcp_worker.model_manifest import ModelManifest
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
    candidate_again = adapter.encode(prepared, EncodeParams(level=32))
    decoded = adapter.decode(candidate)
    decoded_again = adapter.decode(candidate)
    report = adapter.measure(prepared, decoded)

    assert candidate.payload
    assert candidate_again.payload == candidate.payload
    assert decoded_again == decoded
    assert report.quality_gate_passed
    assert report.metrics["classification"] == "GENERIC"
    duration_delta = report.metrics["duration_delta_seconds"]
    assert isinstance(duration_delta, float)
    assert duration_delta <= 0.05


def test_non_video_is_rejected() -> None:
    source = SourceObject(b"not video", "text/plain", "message.txt")
    assert not Av1VideoAdapter().probe(source).accepted


def test_liveportrait_capability_verifies_every_external_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = b"model_params: synthetic\n"
    feature = b"feature"
    motion = b"motion"
    encodec_weights = b"encodec weights"
    encodec_config = b"encodec config"
    liveportrait = ModelManifest.model_validate(
        {
            "id": "liveportrait",
            "codec_id": "video.liveportrait",
            "version": "test",
            "source": "https://example.invalid/liveportrait",
            "code_commit": "a" * 40,
            "license_code": "MIT",
            "license_code_evidence": "https://example.invalid/code-license",
            "license_weights": "MIT",
            "license_weights_evidence": "https://example.invalid/weights-license",
            "weight_artifacts": [
                {
                    "name": "feature.pth",
                    "url": "https://example.invalid/feature.pth",
                    "sha256": hashlib.sha256(feature).hexdigest(),
                },
                {
                    "name": "motion.pth",
                    "url": "https://example.invalid/motion.pth",
                    "sha256": hashlib.sha256(motion).hexdigest(),
                },
            ],
            "config_url": "https://example.invalid/config.yaml",
            "config_sha256": hashlib.sha256(config).hexdigest(),
            "input_contract": "pre-aligned video",
            "decoder_image_digest": f"sha256:{'d' * 64}",
            "adapter_entrypoint": "example:Adapter",
            "enabled": True,
            "install_hint": "install explicitly",
        }
    )
    encodec = ModelManifest.model_validate(
        {
            "id": "encodec",
            "codec_id": "audio.encodec",
            "version": "test",
            "source": "https://example.invalid/encodec",
            "code_commit": "b" * 40,
            "license_code": "Apache-2.0",
            "license_code_evidence": "https://example.invalid/code-license",
            "license_weights": "MIT",
            "license_weights_evidence": "https://example.invalid/weights-license",
            "weights_url": "https://example.invalid/weights.bin",
            "weights_sha256": hashlib.sha256(encodec_weights).hexdigest(),
            "config_url": "https://example.invalid/config.yaml",
            "config_sha256": hashlib.sha256(encodec_config).hexdigest(),
            "input_contract": "stereo PCM",
            "decoder_image_digest": f"sha256:{'e' * 64}",
            "adapter_entrypoint": "example:Adapter",
            "enabled": True,
            "install_hint": "install explicitly",
        }
    )
    source_root = tmp_path / "source"
    (source_root / "src/modules").mkdir(parents=True)
    (source_root / "src/modules/motion_extractor.py").write_text("# pinned source\n")
    cache = tmp_path / "cache"
    model_directory = cache / liveportrait.id / liveportrait.version
    model_directory.mkdir(parents=True)
    (model_directory / "config.yaml").write_bytes(config)
    (model_directory / "feature.pth").write_bytes(feature)
    (model_directory / "motion.pth").write_bytes(motion)
    encodec_directory = cache / encodec.id / encodec.version
    encodec_directory.mkdir(parents=True)
    (encodec_directory / "weights.bin").write_bytes(encodec_weights)
    (encodec_directory / "config.yaml").write_bytes(encodec_config)
    monkeypatch.setattr(
        LivePortraitVideoAdapter,
        "encodec_manifest",
        property(lambda _self: encodec),
    )
    adapter = LivePortraitVideoAdapter(
        manifest=liveportrait, source_root=source_root, cache_root=cache
    )

    assert adapter.capabilities().enabled
    (model_directory / "motion.pth").write_bytes(b"corrupted")
    capability = adapter.capabilities()
    assert not capability.enabled
    assert "failed SHA-256 verification" in (capability.disabled_reason or "")
