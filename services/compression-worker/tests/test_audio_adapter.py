import hashlib
import json
from pathlib import Path

import pytest

from smcp_worker.adapters.audio import OpusAudioAdapter, SnacAudioAdapter, snac_manifest_for_version
from smcp_worker.adapters.external import executable, run
from smcp_worker.model_manifest import load_catalog
from smcp_worker.models import EncodeParams, PreparedInput, Profile, SourceObject


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
    candidate_again = adapter.encode(prepared, EncodeParams(level=20))
    decoded = adapter.decode(candidate)
    report = adapter.measure(prepared, decoded)

    assert candidate.payload.startswith(b"OggS")
    assert candidate_again.payload == candidate.payload
    assert report.quality_gate_passed
    duration_delta = report.metrics["duration_delta_seconds"]
    assert isinstance(duration_delta, float)
    assert duration_delta <= 0.02
    assert report.metrics["intelligibility_status"] == "not_evaluated:no_versioned_asr_model"


def test_non_audio_is_rejected() -> None:
    source = SourceObject(b"not audio", "text/plain", "message.txt")
    assert not OpusAudioAdapter().probe(source).accepted


def test_snac_wraps_pinned_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    upstream = source_root / "snac" / "snac.py"
    upstream.parent.mkdir(parents=True)
    upstream.write_text("# pinned upstream implementation\n", encoding="utf-8")
    cache_root = tmp_path / "cache"
    catalog_manifest = next(
        model
        for model in load_catalog(Path("model-manifests/catalog.json")).models
        if model.id == "snac"
    )
    weights = b"verified weights"
    config = b'{"sampling_rate": 24000}\n'
    manifest = catalog_manifest.model_copy(
        update={
            "enabled": True,
            "disabled_reason": None,
            "weights_sha256": hashlib.sha256(weights).hexdigest(),
            "config_sha256": hashlib.sha256(config).hexdigest(),
            "decoder_image_digest": f"sha256:{'b' * 64}",
        }
    )
    model_directory = cache_root / manifest.id / manifest.version
    model_directory.mkdir(parents=True)
    (model_directory / "weights.bin").write_bytes(weights)
    (model_directory / "config.yaml").write_bytes(config)
    adapter = SnacAudioAdapter(manifest, source_root, cache_root)

    def fake_transform(
        payload: bytes,
        input_suffix: str,
        output_suffix: str,
        command: tuple[str, ...],
        *,
        timeout: int = 300,
    ) -> bytes:
        assert payload
        assert timeout == 600
        assert command[:4] == (
            adapter.python_executable,
            "-m",
            "smcp_worker.snac_runtime",
            "encode" if output_suffix == ".snac" else "decode",
        )
        return b"SMCPSNACtokens" if output_suffix == ".snac" else b"decoded-wav"

    monkeypatch.setattr("smcp_worker.adapters.audio.transform", fake_transform)
    assert adapter.capabilities().enabled
    candidate = adapter.encode(PreparedInput(b"wav", b"wav", "audio/wav"), EncodeParams(980))
    assert candidate.payload == b"SMCPSNACtokens"
    assert candidate.config["checkpoint_sha256"] == manifest.weights_sha256
    assert adapter.decode(candidate) == b"decoded-wav"


def test_snac_rejects_tampered_cached_artifact(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    upstream = source_root / "snac" / "snac.py"
    upstream.parent.mkdir(parents=True)
    upstream.write_text("# pinned upstream implementation\n", encoding="utf-8")
    cache_root = tmp_path / "cache"
    catalog_manifest = next(
        model
        for model in load_catalog(Path("model-manifests/catalog.json")).models
        if model.id == "snac"
    )
    manifest = catalog_manifest.model_copy(
        update={
            "enabled": True,
            "disabled_reason": None,
            "decoder_image_digest": f"sha256:{'b' * 64}",
        }
    )
    model_directory = cache_root / manifest.id / manifest.version
    model_directory.mkdir(parents=True)
    (model_directory / "weights.bin").write_bytes(b"tampered")
    (model_directory / "config.yaml").write_bytes(b"tampered")

    capability = SnacAudioAdapter(manifest, source_root, cache_root).capabilities()
    assert not capability.enabled
    assert "failed SHA-256 verification" in (capability.disabled_reason or "")


def test_snac_decoder_manifest_is_resolved_by_persisted_version(tmp_path: Path) -> None:
    payload = json.loads(Path("model-manifests/catalog.json").read_text(encoding="utf-8"))
    current = next(model for model in payload["models"] if model["id"] == "snac")
    payload["models"].append({**current, "version": "historical-snac-test-vector"})
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")

    resolved = snac_manifest_for_version("historical-snac-test-vector", catalog_path)

    assert resolved.version == "historical-snac-test-vector"
    with pytest.raises(LookupError, match="persisted version"):
        snac_manifest_for_version("missing-version", catalog_path)
