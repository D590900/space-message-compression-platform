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
    assert not encodec.enabled
    assert encodec.license_weights == "MIT"
    assert encodec.license_weights_evidence is not None
    assert encodec.weights_sha256 == (
        "47a15ffbaf7bb76176d0833e10590de0a8988a7848748608cefc36a1c88adfdc"
    )
    assert encodec.config_sha256 == (
        "4a914ed15ed5a69e19932d05b0c51f2d22c68ffac70e959a757594cb0cd6e2a7"
    )
    assert all(
        not model.enabled and model.license_weights.startswith("UNKNOWN")
        for model in catalog.models
        if model.id not in {"cod-lite", "snac", "mimi", "encodec"}
    )


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
