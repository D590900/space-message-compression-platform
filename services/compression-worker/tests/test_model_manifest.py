import hashlib
import json
import stat
from pathlib import Path
from typing import Any, ClassVar

import pytest
import requests
from pydantic import ValidationError

from smcp_worker.model_manifest import ModelCatalog, ModelManifest, fetch_weights, load_catalog


def test_committed_model_catalog_is_valid_and_truthfully_disabled() -> None:
    catalog = load_catalog(Path("model-manifests/catalog.json"))
    assert len(catalog.models) == 8
    assert all(not model.enabled for model in catalog.models)
    assert all(model.license_weights.startswith("UNKNOWN") for model in catalog.models)


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


def test_explicit_weight_fetch_is_hash_checked_and_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"synthetic model weights"
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
            "config_sha256": "b" * 64,
            "input_contract": "mono PCM",
            "decoder_image_digest": f"sha256:{'c' * 64}",
            "adapter_entrypoint": "example:Adapter",
            "enabled": True,
            "install_hint": "install explicitly",
        }
    )

    class FakeResponse:
        url = "https://example.invalid/weights.bin"
        headers: ClassVar[dict[str, str]] = {"content-length": str(len(payload))}

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_arguments: Any) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int) -> list[bytes]:
            assert chunk_size == 1024 * 1024
            return [payload]

    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: FakeResponse())
    destination = fetch_weights(manifest, tmp_path, max_bytes=1024)

    assert destination.read_bytes() == payload
    assert stat.S_IMODE(destination.stat().st_mode) == 0o400
