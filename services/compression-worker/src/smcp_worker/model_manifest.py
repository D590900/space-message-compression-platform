"""Strict provenance gates and explicit model-weight retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Self

import requests
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
ARTIFACT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")


class WeightArtifact(BaseModel):
    """One independently hash-verified file in a multi-file checkpoint."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    url: HttpUrl
    sha256: str

    @model_validator(mode="after")
    def validate_artifact(self) -> Self:
        if not ARTIFACT_NAME_PATTERN.fullmatch(self.name):
            raise ValueError("weight artifact name must be a safe lowercase filename")
        if self.name in {"config.yaml", "weights.bin"}:
            raise ValueError("weight artifact name is reserved")
        if self.url.scheme != "https":
            raise ValueError("weight artifact URL must use HTTPS")
        if not SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("weight artifact sha256 must be lowercase SHA-256")
        return self


class ModelManifest(BaseModel):
    """Immutable code, weight, configuration and decoder provenance."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=120)
    codec_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=120)
    source: HttpUrl
    code_commit: str
    license_code: str = Field(min_length=1, max_length=120)
    license_code_evidence: HttpUrl
    license_weights: str = Field(min_length=1, max_length=200)
    license_weights_evidence: HttpUrl | None = None
    weights_url: HttpUrl | None = None
    weights_sha256: str | None = None
    weight_artifacts: tuple[WeightArtifact, ...] = ()
    config_url: HttpUrl | None = None
    config_sha256: str | None = None
    input_contract: str = Field(min_length=1, max_length=500)
    decoder_image_digest: str | None = None
    adapter_entrypoint: str | None = None
    enabled: bool
    disabled_reason: str | None = None
    install_hint: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if self.source.scheme != "https" or self.license_code_evidence.scheme != "https":
            raise ValueError("source and code-license evidence must use HTTPS")
        if not COMMIT_PATTERN.fullmatch(self.code_commit):
            raise ValueError("code_commit must be a lowercase 40-character Git SHA")
        evidence_urls = {
            "weights-license evidence": self.license_weights_evidence,
            "weights URL": self.weights_url,
            "configuration URL": self.config_url,
        }
        for label, url in evidence_urls.items():
            if url is not None and url.scheme != "https":
                raise ValueError(f"{label} must use HTTPS")
        hashes = {
            "weights_sha256": self.weights_sha256,
            "config_sha256": self.config_sha256,
        }
        for label, value in hashes.items():
            if value is not None and not SHA256_PATTERN.fullmatch(value):
                raise ValueError(f"{label} must be lowercase SHA-256")
        if (self.weights_url is None) != (self.weights_sha256 is None):
            raise ValueError("weights_url and weights_sha256 must be recorded together")
        if self.weight_artifacts and self.weights_url is not None:
            raise ValueError("use either a single weights URL or weight_artifacts, not both")
        artifact_names = [artifact.name for artifact in self.weight_artifacts]
        if len(set(artifact_names)) != len(artifact_names):
            raise ValueError("weight artifact names must be unique")
        if (self.config_url is None) != (self.config_sha256 is None):
            raise ValueError("config_url and config_sha256 must be recorded together")
        if self.enabled:
            required = {
                "license_weights_evidence": self.license_weights_evidence,
                "config_url": self.config_url,
                "config_sha256": self.config_sha256,
                "decoder_image_digest": self.decoder_image_digest,
                "adapter_entrypoint": self.adapter_entrypoint,
            }
            missing = sorted(name for name, value in required.items() if value is None)
            if missing:
                raise ValueError(f"enabled model is missing: {', '.join(missing)}")
            if self.weights_url is None and not self.weight_artifacts:
                raise ValueError("enabled model is missing weights provenance")
            if self.license_weights.upper().startswith("UNKNOWN"):
                raise ValueError("enabled model weights must have verified license terms")
            if self.disabled_reason is not None:
                raise ValueError("enabled model cannot have a disabled_reason")
            if self.decoder_image_digest is not None and not DIGEST_PATTERN.fullmatch(
                self.decoder_image_digest
            ):
                raise ValueError("decoder_image_digest must be an immutable SHA-256 digest")
        elif not self.disabled_reason:
            raise ValueError("disabled model must explain why it is disabled")
        return self


class ModelCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1, le=1)
    models: list[ModelManifest]

    @model_validator(mode="after")
    def unique_models(self) -> Self:
        identities = [(model.id, model.version) for model in self.models]
        if len(set(identities)) != len(identities):
            raise ValueError("model id/version pairs must be unique")
        return self


def load_catalog(path: Path) -> ModelCatalog:
    return ModelCatalog.model_validate_json(path.read_text(encoding="utf-8"))


def fetch_weights(
    manifest: ModelManifest, cache_root: Path, max_bytes: int = 10_737_418_240
) -> Path:
    """Explicitly download one enabled model's weights and configuration."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if (
        not manifest.enabled
        or manifest.config_url is None
        or manifest.config_sha256 is None
        or (
            (manifest.weights_url is None or manifest.weights_sha256 is None)
            and not manifest.weight_artifacts
        )
    ):
        raise ValueError("only a fully validated enabled manifest may download weights")
    destination_directory = cache_root / manifest.id / manifest.version
    destination_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    downloads: list[tuple[Path, Path]] = []
    try:
        config_temporary = _download_verified(
            str(manifest.config_url),
            manifest.config_sha256,
            destination_directory,
            max_bytes,
        )
        downloads.append((config_temporary, destination_directory / "config.yaml"))
        if manifest.weight_artifacts:
            for artifact in manifest.weight_artifacts:
                temporary = _download_verified(
                    str(artifact.url), artifact.sha256, destination_directory, max_bytes
                )
                downloads.append((temporary, destination_directory / artifact.name))
        else:
            if manifest.weights_url is None or manifest.weights_sha256 is None:
                raise AssertionError("validated single-file weights are missing")
            temporary = _download_verified(
                str(manifest.weights_url),
                manifest.weights_sha256,
                destination_directory,
                max_bytes,
            )
            downloads.append((temporary, destination_directory / "weights.bin"))
    except BaseException:
        for temporary, _ in downloads:
            temporary.unlink(missing_ok=True)
        raise
    for temporary, destination in downloads:
        os.chmod(temporary, 0o400)
        os.replace(temporary, destination)
    if manifest.weight_artifacts:
        return destination_directory
    return destination_directory / "weights.bin"


def _download_verified(url: str, expected_sha256: str, directory: Path, max_bytes: int) -> Path:
    """Download one immutable artifact to a private temporary file and verify it."""
    digest = hashlib.sha256()
    with requests.get(url, stream=True, timeout=(10, 300)) as response:
        response.raise_for_status()
        if response.url.startswith("https://") is False:
            raise ValueError("model download redirected away from HTTPS")
        content_length = response.headers.get("content-length")
        if content_length is not None and int(content_length) > max_bytes:
            raise ValueError("model weights exceed the configured download limit")
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            received = 0
            try:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        received += len(chunk)
                        if received > max_bytes:
                            raise ValueError("model weights exceed the configured download limit")
                        digest.update(chunk)
                        temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise
    if digest.hexdigest() != expected_sha256:
        temporary_path.unlink(missing_ok=True)
        raise ValueError("downloaded model artifact failed SHA-256 verification")
    return temporary_path


def main() -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate")
    validate.add_argument("catalog", type=Path)
    fetch = subcommands.add_parser("fetch")
    fetch.add_argument("catalog", type=Path)
    fetch.add_argument("model_id")
    fetch.add_argument("version")
    fetch.add_argument("--cache", required=True, type=Path)
    fetch.add_argument("--max-bytes", type=int, default=10_737_418_240)
    arguments = parser.parse_args()
    catalog = load_catalog(arguments.catalog)
    if arguments.command == "validate":
        print(json.dumps({"models": len(catalog.models), "valid": True}, sort_keys=True))
        return
    manifest = next(
        (
            item
            for item in catalog.models
            if item.id == arguments.model_id and item.version == arguments.version
        ),
        None,
    )
    if manifest is None:
        raise SystemExit("model id/version not found")
    print(fetch_weights(manifest, arguments.cache, arguments.max_bytes))


if __name__ == "__main__":
    main()
