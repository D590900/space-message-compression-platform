import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from smcp_worker.adapters.external import executable, run
from smcp_worker.adapters.image import (
    AvifImageAdapter,
    CodLiteImageAdapter,
    JpegXlImageAdapter,
    cod_lite_manifest_for_version,
    generate_image_candidates,
)
from smcp_worker.model_manifest import load_catalog
from smcp_worker.models import CodecCapabilities, EncodeParams, PreparedInput, Profile, SourceObject


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


def test_cod_lite_wraps_pinned_upstream_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    inference = source_root / "finetuned_one_step_codec" / "inference.py"
    inference.parent.mkdir(parents=True)
    inference.write_text("# pinned upstream entrypoint\n", encoding="utf-8")
    cache_root = tmp_path / "cache"
    catalog_manifest = next(
        model
        for model in load_catalog(Path("model-manifests/catalog.json")).models
        if model.id == "cod-lite"
    )
    weights = b"verified weights"
    config = b"model: verified\n"
    manifest = catalog_manifest.model_copy(
        update={
            "enabled": True,
            "disabled_reason": None,
            "weights_sha256": hashlib.sha256(weights).hexdigest(),
            "config_sha256": hashlib.sha256(config).hexdigest(),
            "decoder_image_digest": f"sha256:{'a' * 64}",
        }
    )
    model_directory = cache_root / manifest.id / manifest.version
    model_directory.mkdir(parents=True)
    (model_directory / "weights.bin").write_bytes(weights)
    (model_directory / "config.yaml").write_bytes(config)
    adapter = CodLiteImageAdapter(manifest, source_root, cache_root)

    def fake_run(
        command: tuple[str, ...], *, timeout: int = 300, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        assert timeout == 300
        assert cwd == source_root
        mode = command[3]
        output_directory = Path(command[command.index("--output") + 1])
        if mode == "compress":
            (output_directory / "input.png.cod").write_bytes(b"cod-bitstream")
        else:
            (output_directory / "input.png").write_bytes(b"decoded-png")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("smcp_worker.adapters.image.run", fake_run)
    assert adapter.capabilities().enabled
    candidate = adapter.encode(PreparedInput(b"png", b"png", "image/png"), EncodeParams(312))
    assert candidate.payload == b"cod-bitstream"
    assert candidate.config["checkpoint_sha256"] == manifest.weights_sha256
    assert adapter.decode(candidate) == b"decoded-png"


def test_cod_lite_rejects_tampered_cached_artifact(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    inference = source_root / "finetuned_one_step_codec" / "inference.py"
    inference.parent.mkdir(parents=True)
    inference.write_text("# pinned upstream entrypoint\n", encoding="utf-8")
    cache_root = tmp_path / "cache"
    catalog_manifest = next(
        model
        for model in load_catalog(Path("model-manifests/catalog.json")).models
        if model.id == "cod-lite"
    )
    manifest = catalog_manifest.model_copy(
        update={
            "enabled": True,
            "disabled_reason": None,
            "decoder_image_digest": f"sha256:{'a' * 64}",
        }
    )
    model_directory = cache_root / manifest.id / manifest.version
    model_directory.mkdir(parents=True)
    (model_directory / "weights.bin").write_bytes(b"tampered")
    (model_directory / "config.yaml").write_bytes(b"tampered")

    capability = CodLiteImageAdapter(manifest, source_root, cache_root).capabilities()
    assert not capability.enabled
    assert "failed SHA-256 verification" in (capability.disabled_reason or "")


def test_cod_lite_decoder_manifest_is_resolved_by_persisted_version(tmp_path: Path) -> None:
    payload = json.loads(Path("model-manifests/catalog.json").read_text(encoding="utf-8"))
    current = next(model for model in payload["models"] if model["id"] == "cod-lite")
    historical = {**current, "version": "historical-test-vector"}
    payload["models"].append(historical)
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")

    resolved = cod_lite_manifest_for_version("historical-test-vector", catalog_path)

    assert resolved.version == "historical-test-vector"
    with pytest.raises(LookupError, match="persisted version"):
        cod_lite_manifest_for_version("missing-version", catalog_path)


def test_cod_lite_is_not_generated_for_faithful_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DisabledAdapter:
        def capabilities(self) -> CodecCapabilities:
            return CodecCapabilities(
                "image.disabled",
                "test",
                ("IMAGE",),
                (Profile.FAITHFUL, Profile.ULTRA),
                False,
                True,
                "disabled for test",
            )

    class SemanticOnlyAdapter:
        def capabilities(self) -> CodecCapabilities:
            return CodecCapabilities(
                "image.cod-lite",
                "test",
                ("IMAGE",),
                (Profile.ULTRA, Profile.SEMANTIC),
                True,
                False,
            )

        def preprocess(self, _source: SourceObject, _profile: Profile) -> PreparedInput:
            raise AssertionError("unsupported profile reached CoD-Lite preprocessing")

    monkeypatch.setattr("smcp_worker.adapters.image.AvifImageAdapter", DisabledAdapter)
    monkeypatch.setattr("smcp_worker.adapters.image.JpegXlImageAdapter", DisabledAdapter)
    monkeypatch.setattr("smcp_worker.adapters.image.CodLiteImageAdapter", SemanticOnlyAdapter)

    assert (
        generate_image_candidates(
            SourceObject(b"not-decoded", "image/png", "source.png"), Profile.FAITHFUL
        )
        == []
    )
