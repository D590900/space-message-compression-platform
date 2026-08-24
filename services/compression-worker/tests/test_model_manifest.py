import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import pytest
import requests
from pydantic import ValidationError

from smcp_worker.model_manifest import ModelCatalog, ModelManifest, fetch_weights, load_catalog


def test_committed_model_catalog_records_audited_neural_artifacts() -> None:
    catalog = load_catalog(Path("model-manifests/catalog.json"))
    assert len(catalog.models) == 8
    by_id = {model.id: model for model in catalog.models}
    cod_lite = by_id["cod-lite"]
    assert cod_lite.enabled
    assert cod_lite.decoder_image_digest == (
        "sha256:791454206faacd38b9b4126f89a998a2d2ff9761f8cd1dcdc81e7030022035cf"
    )
    assert cod_lite.license_weights == "MIT"
    assert cod_lite.license_weights_evidence is not None
    assert cod_lite.weights_sha256 == (
        "af74235d4ec4485c425bb6de93354d0a3abfc6f060cac350c2a7ea3dbd65e0ca"
    )
    assert cod_lite.config_sha256 == (
        "af69be08f74378e3b3a9ef5d8b629a5e8acc49b0754282deba27d31adc3c70e4"
    )
    snac = by_id["snac"]
    assert snac.enabled
    assert snac.decoder_image_digest == (
        "sha256:1a21bda431cd81b45115819736b16f53bc12f35e7dc8e86b1c6470873292078c"
    )
    assert snac.license_weights == "MIT"
    assert snac.license_weights_evidence is not None
    assert snac.weights_sha256 == (
        "4b8164cc6606bfa627f1a784734c1e539891518f1191ed9194fe1e3b9b4bff40"
    )
    assert snac.config_sha256 == (
        "e119b9366d4f5e73c6ca5f31137c4ff361578bbb132953a5203afe037c4012be"
    )
    mimi = by_id["mimi"]
    assert mimi.enabled
    assert mimi.decoder_image_digest == (
        "sha256:e053c39c169accd02b775e46b6b1e344449b8207ff5c175741fc6dce69b7a8ff"
    )
    assert mimi.license_weights == "CC-BY-4.0"
    assert mimi.license_weights_evidence is not None
    assert mimi.weights_sha256 == (
        "bac7e85083dcded655d24eaadde7e6eea34c0da1b35fa2d284e641bd2b942a5e"
    )
    assert mimi.config_sha256 == (
        "aca6f44b04f7bc2e7466b71597d2d51e463ed1cf3cd7025d8848595580546c36"
    )
    encodec = by_id["encodec"]
    assert encodec.enabled
    assert encodec.decoder_image_digest == (
        "sha256:aee93174fab26f4890481db6fe9addbd1ad8c211bcdcf17cd26f1ebfc6dca653"
    )
    assert encodec.license_weights == "MIT"
    assert encodec.license_weights_evidence is not None
    assert encodec.weights_sha256 == (
        "47a15ffbaf7bb76176d0833e10590de0a8988a7848748608cefc36a1c88adfdc"
    )
    assert encodec.config_sha256 == (
        "4a914ed15ed5a69e19932d05b0c51f2d22c68ffac70e959a757594cb0cd6e2a7"
    )
    liveportrait = by_id["liveportrait"]
    assert liveportrait.enabled
    assert liveportrait.decoder_image_digest == (
        "sha256:b0805d6919914e3ed1a2190a48227aa5f56377e7d2735073a78718950d43c5c7"
    )
    assert liveportrait.license_weights == "MIT"
    assert liveportrait.license_weights_evidence is not None
    assert liveportrait.config_sha256 == (
        "da135e5d5104441675411caba2ededdf26606bfa8a511a2504018d2d149512c4"
    )
    assert [artifact.name for artifact in liveportrait.weight_artifacts] == [
        "appearance_feature_extractor.pth",
        "motion_extractor.pth",
        "spade_generator.pth",
        "warping_module.pth",
    ]
    coolchic = by_id["coolchic-image"]
    assert coolchic.enabled
    assert coolchic.decoder_image_digest == (
        "sha256:606962ae27366101361ccf555aa6664bd1a128719085a815eb398edd22e714dc"
    )
    assert coolchic.adapter_entrypoint == "smcp_worker.adapters.image:CoolChicImageAdapter"
    assert coolchic.weights_origin == "per_asset"
    assert coolchic.license_weights_evidence is not None
    assert not coolchic.license_weights.startswith("UNKNOWN")
    coolchic_video = by_id["coolchic-video"]
    assert coolchic_video.enabled
    assert coolchic_video.decoder_image_digest == coolchic.decoder_image_digest
    assert coolchic_video.adapter_entrypoint == (
        "smcp_worker.adapters.video:CoolChicVideoAdapter"
    )
    assert coolchic_video.weights_origin == "per_asset"
    assert coolchic_video.license_weights_evidence is not None
    assert not coolchic_video.license_weights.startswith("UNKNOWN")
    hinerv = by_id["hinerv-video"]
    assert hinerv.enabled
    assert hinerv.decoder_image_digest == (
        "sha256:f85cac0ea6fa2fa150ac1da882b18d64b91189a6ff4775750d7e5c61059f5bfa"
    )
    assert hinerv.adapter_entrypoint == "smcp_worker.adapters.video:HiNervVideoAdapter"
    assert hinerv.weights_origin == "per_asset"
    assert hinerv.license_weights_evidence is not None
    assert not hinerv.license_weights.startswith("UNKNOWN")
    assert not any(model.license_weights.startswith("UNKNOWN") for model in catalog.models)


def test_enabled_model_requires_complete_weight_and_decoder_provenance() -> None:
    payload = {
        "schema_version": 1,
        "models": [
            {
                "id": "example",
                "codec_id": "audio.example",
                "version": "1",
                "source": "https://example.invalid/source",
                "code_commit": "a" * 40,
                "license_code": "Apache-2.0",
                "license_code_evidence": "https://example.invalid/license",
                "license_weights": "UNKNOWN",
                "input_contract": "mono PCM",
                "enabled": True,
                "install_hint": "install explicitly",
            }
        ],
    }
    with pytest.raises(ValidationError, match="enabled model is missing"):
        ModelCatalog.model_validate_json(json.dumps(payload))


def test_enabled_per_asset_model_needs_no_external_checkpoint() -> None:
    manifest = ModelManifest.model_validate(
        {
            "id": "per-asset-example",
            "codec_id": "image.per-asset-example",
            "version": "1",
            "source": "https://example.invalid/source",
            "code_commit": "a" * 40,
            "license_code": "BSD-3-Clause",
            "license_code_evidence": "https://example.invalid/license",
            "license_weights": "BSD-3-Clause; generated per asset",
            "weights_origin": "per_asset",
            "license_weights_evidence": "https://example.invalid/license",
            "input_contract": "one bounded RGB image",
            "decoder_image_digest": f"sha256:{'b' * 64}",
            "adapter_entrypoint": "example:Adapter",
            "enabled": True,
            "install_hint": "use the pinned runtime",
        }
    )

    assert manifest.weights_url is None
    assert manifest.config_url is None
    with pytest.raises(ValueError, match="do not download weights"):
        fetch_weights(manifest, Path("unused"))


def test_per_asset_model_rejects_external_checkpoint_fields() -> None:
    with pytest.raises(ValidationError, match="cannot declare external weights"):
        ModelManifest.model_validate(
            {
                "id": "per-asset-example",
                "codec_id": "image.per-asset-example",
                "version": "1",
                "source": "https://example.invalid/source",
                "code_commit": "a" * 40,
                "license_code": "BSD-3-Clause",
                "license_code_evidence": "https://example.invalid/license",
                "license_weights": "BSD-3-Clause; generated per asset",
                "weights_origin": "per_asset",
                "license_weights_evidence": "https://example.invalid/license",
                "weights_url": "https://example.invalid/checkpoint.bin",
                "weights_sha256": "a" * 64,
                "input_contract": "one bounded RGB image",
                "decoder_image_digest": f"sha256:{'b' * 64}",
                "adapter_entrypoint": "example:Adapter",
                "enabled": True,
                "install_hint": "use the pinned runtime",
            }
        )


def test_catalog_retains_multiple_versions_for_persisted_decoder_selection() -> None:
    payload = json.loads(Path("model-manifests/catalog.json").read_text(encoding="utf-8"))
    current = next(model for model in payload["models"] if model["id"] == "cod-lite")
    historical = {**current, "version": "historical-test-vector"}
    payload["models"].append(historical)

    catalog = ModelCatalog.model_validate(payload)

    assert [model.codec_id for model in catalog.models].count("image.cod-lite") == 2


def test_explicit_weight_fetch_is_hash_checked_and_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"synthetic model weights"
    config_payload = b"model: synthetic\n"
    manifest = ModelManifest.model_validate(
        {
            "id": "example",
            "codec_id": "audio.example",
            "version": "1",
            "source": "https://example.invalid/source",
            "code_commit": "a" * 40,
            "license_code": "Apache-2.0",
            "license_code_evidence": "https://example.invalid/license",
            "license_weights": "Apache-2.0",
            "license_weights_evidence": "https://example.invalid/weights-license",
            "weights_url": "https://example.invalid/weights.bin",
            "weights_sha256": hashlib.sha256(payload).hexdigest(),
            "config_url": "https://example.invalid/config.yaml",
            "config_sha256": hashlib.sha256(config_payload).hexdigest(),
            "input_contract": "mono PCM",
            "decoder_image_digest": f"sha256:{'c' * 64}",
            "adapter_entrypoint": "example:Adapter",
            "enabled": True,
            "install_hint": "install explicitly",
        }
    )

    class FakeResponse:
        def __init__(self, url: str, body: bytes) -> None:
            self.url = url
            self.body = body
            self.headers: dict[str, str] = {"content-length": str(len(body))}

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_arguments: Any) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int) -> list[bytes]:
            assert chunk_size == 1024 * 1024
            return [self.body]

    def fake_get(url: str, **_kwargs: Any) -> FakeResponse:
        body = config_payload if url.endswith("config.yaml") else payload
        return FakeResponse(url, body)

    monkeypatch.setattr(requests, "get", fake_get)
    destination = fetch_weights(manifest, tmp_path, max_bytes=1024)

    assert destination.read_bytes() == payload
    assert stat.S_IMODE(destination.stat().st_mode) == 0o400
    config_destination = destination.with_name("config.yaml")
    assert config_destination.read_bytes() == config_payload
    assert stat.S_IMODE(config_destination.stat().st_mode) == 0o400


def test_multi_artifact_fetch_verifies_each_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bodies = {
        "https://example.invalid/config.yaml": b"model: synthetic\n",
        "https://example.invalid/feature.pth": b"feature weights",
        "https://example.invalid/motion.pth": b"motion weights",
    }
    manifest = ModelManifest.model_validate(
        {
            "id": "example",
            "codec_id": "video.example",
            "version": "1",
            "source": "https://example.invalid/source",
            "code_commit": "a" * 40,
            "license_code": "MIT",
            "license_code_evidence": "https://example.invalid/license",
            "license_weights": "MIT",
            "license_weights_evidence": "https://example.invalid/weights-license",
            "weight_artifacts": [
                {
                    "name": "feature.pth",
                    "url": "https://example.invalid/feature.pth",
                    "sha256": hashlib.sha256(
                        bodies["https://example.invalid/feature.pth"]
                    ).hexdigest(),
                },
                {
                    "name": "motion.pth",
                    "url": "https://example.invalid/motion.pth",
                    "sha256": hashlib.sha256(
                        bodies["https://example.invalid/motion.pth"]
                    ).hexdigest(),
                },
            ],
            "config_url": "https://example.invalid/config.yaml",
            "config_sha256": hashlib.sha256(
                bodies["https://example.invalid/config.yaml"]
            ).hexdigest(),
            "input_contract": "pre-aligned video",
            "decoder_image_digest": f"sha256:{'d' * 64}",
            "adapter_entrypoint": "example:Adapter",
            "enabled": True,
            "install_hint": "install explicitly",
        }
    )

    class FakeResponse:
        def __init__(self, url: str) -> None:
            self.url = url
            self.body = bodies[url]
            self.headers = {"content-length": str(len(self.body))}

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_arguments: Any) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int) -> list[bytes]:
            assert chunk_size == 1024 * 1024
            return [self.body]

    monkeypatch.setattr(requests, "get", lambda url, **_kwargs: FakeResponse(url))
    destination = fetch_weights(manifest, tmp_path, max_bytes=1024)

    assert destination.is_dir()
    for name, expected in (
        ("config.yaml", bodies["https://example.invalid/config.yaml"]),
        ("feature.pth", bodies["https://example.invalid/feature.pth"]),
        ("motion.pth", bodies["https://example.invalid/motion.pth"]),
    ):
        path = destination / name
        assert path.read_bytes() == expected
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
