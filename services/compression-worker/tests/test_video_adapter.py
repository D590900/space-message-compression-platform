import hashlib
from pathlib import Path

import pytest

from smcp_worker.adapters.external import executable, run
from smcp_worker.adapters.video import (
    Av1VideoAdapter,
    CoolChicVideoAdapter,
    HiNervVideoAdapter,
    LivePortraitVideoAdapter,
)
from smcp_worker.coolchic_runtime import pack_video_container, unpack_video_container
from smcp_worker.hinerv_runtime import pack_container as pack_hinerv_container
from smcp_worker.hinerv_runtime import unpack_container as unpack_hinerv_container
from smcp_worker.model_manifest import ModelManifest, load_catalog
from smcp_worker.models import EncodedCandidate, EncodeParams, PreparedInput, Profile, SourceObject


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


def test_coolchic_video_wraps_pinned_per_asset_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "cc_encode.py").write_text("# pinned encoder\n", encoding="utf-8")
    (source_root / "cc_decode.py").write_text("# pinned decoder\n", encoding="utf-8")
    catalog_manifest = next(
        model
        for model in load_catalog(Path("model-manifests/catalog.json")).models
        if model.id == "coolchic-video"
    )
    manifest = catalog_manifest.model_copy(
        update={
            "enabled": True,
            "disabled_reason": None,
            "decoder_image_digest": f"sha256:{'a' * 64}",
            "adapter_entrypoint": "smcp_worker.adapters.video:CoolChicVideoAdapter",
        }
    )
    adapter = CoolChicVideoAdapter(manifest, source_root)
    monkeypatch.setattr(
        "smcp_worker.adapters.video.coolchic_video_manifest_for_version",
        lambda _version: manifest,
    )
    payload = pack_video_container(
        b"coolchic-video",
        b"opus",
        width=64,
        height=64,
        fps_numerator=5,
        fps_denominator=1,
        frames=2,
    )
    monkeypatch.setattr(adapter, "supports_prepared", lambda _prepared: True)

    def fake_transform(
        source: bytes,
        _input_suffix: str,
        _output_suffix: str,
        command: tuple[str, ...],
        *,
        timeout: int = 300,
        cwd: Path | None = None,
    ) -> bytes:
        assert source
        assert cwd is None
        if "encode-video" in command:
            assert timeout == 86_400
            return payload
        assert timeout == 3_600
        return b"decoded-avi"

    monkeypatch.setattr("smcp_worker.adapters.video.transform", fake_transform)
    candidate = adapter.encode(
        PreparedInput(b"avi", b"avi", "video/x-msvideo"), EncodeParams(level=1)
    )

    assert candidate.payload == payload
    assert candidate.config["weights_origin"] == "per_asset_embedded"
    assert adapter.decode(candidate) == b"decoded-avi"


def test_coolchic_video_container_authenticates_all_sections() -> None:
    payload = pack_video_container(
        b"video",
        b"audio",
        width=64,
        height=48,
        fps_numerator=25,
        fps_denominator=1,
        frames=3,
    )

    assert unpack_video_container(payload) == (b"video", b"audio", 64, 48, 25, 1, 3)
    with pytest.raises(ValueError, match="audio digest mismatch"):
        unpack_video_container(payload[:-1] + bytes([payload[-1] ^ 1]))
    with pytest.raises(ValueError, match="section length mismatch"):
        unpack_video_container(payload + b"trailing")


def test_hinerv_wraps_pinned_per_asset_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "hinerv_main.py").write_text("# pinned runtime\n", encoding="utf-8")
    (source_root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    catalog_manifest = next(
        model
        for model in load_catalog(Path("model-manifests/catalog.json")).models
        if model.id == "hinerv-video"
    )
    manifest = catalog_manifest.model_copy(
        update={
            "enabled": True,
            "disabled_reason": None,
            "decoder_image_digest": f"sha256:{'a' * 64}",
            "adapter_entrypoint": "smcp_worker.adapters.video:HiNervVideoAdapter",
        }
    )
    adapter = HiNervVideoAdapter(manifest, source_root)
    monkeypatch.setattr(
        "smcp_worker.adapters.video.hinerv_manifest_for_version", lambda _version: manifest
    )
    payload = pack_hinerv_container(
        b"hinerv-model",
        b"opus",
        width=64,
        height=64,
        fps_numerator=5,
        fps_denominator=1,
        frames=2,
        channels=32,
    )
    monkeypatch.setattr(adapter, "supports_prepared", lambda _prepared: True)

    def fake_transform(
        source: bytes,
        _input_suffix: str,
        _output_suffix: str,
        command: tuple[str, ...],
        *,
        timeout: int = 300,
        cwd: Path | None = None,
    ) -> bytes:
        assert source
        assert cwd is None
        if "encode" in command:
            assert timeout == 86_400
            return payload
        assert timeout == 3_600
        return b"decoded-avi"

    monkeypatch.setattr("smcp_worker.adapters.video.transform", fake_transform)
    candidate = adapter.encode(
        PreparedInput(b"avi", b"avi", "video/x-msvideo"), EncodeParams(level=1)
    )

    assert candidate.payload == payload
    assert candidate.config["epochs"] == 30
    assert candidate.config["weights_origin"] == "per_asset_embedded"
    assert adapter.decode(candidate) == b"decoded-avi"


def test_hinerv_container_authenticates_model_and_audio() -> None:
    payload = pack_hinerv_container(
        b"model",
        b"audio",
        width=64,
        height=48,
        fps_numerator=25,
        fps_denominator=1,
        frames=3,
        channels=32,
    )

    assert unpack_hinerv_container(payload) == (
        b"model",
        b"audio",
        64,
        48,
        25,
        1,
        3,
        32,
    )
    with pytest.raises(ValueError, match="audio digest mismatch"):
        unpack_hinerv_container(payload[:-1] + bytes([payload[-1] ^ 1]))
    with pytest.raises(ValueError, match="section length mismatch"):
        unpack_hinerv_container(payload + b"trailing")


@pytest.mark.parametrize(
    ("model_id", "adapter_type", "resolver_name", "payload"),
    [
        (
            "coolchic-video",
            CoolChicVideoAdapter,
            "coolchic_video_manifest_for_version",
            pack_video_container(
                b"historical",
                b"",
                width=64,
                height=64,
                fps_numerator=1,
                fps_denominator=1,
                frames=1,
            ),
        ),
        (
            "hinerv-video",
            HiNervVideoAdapter,
            "hinerv_manifest_for_version",
            pack_hinerv_container(
                b"historical",
                b"",
                width=64,
                height=64,
                fps_numerator=1,
                fps_denominator=1,
                frames=1,
                channels=32,
            ),
        ),
    ],
)
def test_per_asset_video_decode_rejects_a_different_historical_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    model_id: str,
    adapter_type: type[CoolChicVideoAdapter] | type[HiNervVideoAdapter],
    resolver_name: str,
    payload: bytes,
) -> None:
    current = next(
        model
        for model in load_catalog(Path("model-manifests/catalog.json")).models
        if model.id == model_id
    ).model_copy(
        update={
            "enabled": True,
            "disabled_reason": None,
            "decoder_image_digest": f"sha256:{'a' * 64}",
            "adapter_entrypoint": f"smcp_worker.adapters.video:{adapter_type.__name__}",
        }
    )
    historical = current.model_copy(
        update={
            "version": "historical-test-vector",
            "decoder_image_digest": f"sha256:{'b' * 64}",
        }
    )
    source_root = tmp_path / "source"
    source_root.mkdir()
    adapter = adapter_type(current, source_root)
    monkeypatch.setattr(f"smcp_worker.adapters.video.{resolver_name}", lambda _version: historical)

    with pytest.raises(RuntimeError, match="digest-pinned historical worker"):
        adapter.decode(EncodedCandidate(current.codec_id, historical.version, {}, payload))


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
