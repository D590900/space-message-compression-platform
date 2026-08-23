from __future__ import annotations

import hashlib
import io
import os
import struct
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import replace
from pathlib import Path

from smcp_worker.adapters.external import (
    digest,
    executable,
    numeric_metric,
    pareto_frontier_per_codec,
    run,
    transform,
    version_line,
)
from smcp_worker.model_manifest import ModelManifest, load_catalog
from smcp_worker.models import (
    CodecCapabilities,
    EncodedCandidate,
    EncodeParams,
    PreparedInput,
    ProbeResult,
    Profile,
    QualityReport,
    SourceObject,
)
from smcp_worker.snac_runtime import MAX_SAMPLES as SNAC_MAX_SAMPLES

AUDIO_MIME_PREFIXES = ("audio/",)
MODEL_CATALOG = Path(__file__).resolve().parents[3] / "model-manifests" / "catalog.json"


def snac_manifest_for_version(version: str, catalog_path: Path = MODEL_CATALOG) -> ModelManifest:
    """Resolve the immutable manifest belonging to a persisted SNAC bitstream."""
    matches = [
        model
        for model in load_catalog(catalog_path).models
        if model.codec_id == "audio.snac" and model.version == version
    ]
    if len(matches) != 1:
        raise LookupError(f"no unique SNAC manifest for persisted version {version!r}")
    return matches[0]


def _ffmpeg_capability() -> CodecCapabilities:
    ffmpeg = executable("ffmpeg")
    ffprobe = executable("ffprobe")
    if ffmpeg is None or ffprobe is None:
        missing = [
            name for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if path is None
        ]
        return CodecCapabilities(
            codec_id="audio.opus",
            codec_version="unavailable",
            content_types=("AUDIO",),
            profiles=(Profile.FAITHFUL, Profile.ULTRA),
            enabled=False,
            deterministic=True,
            disabled_reason=f"required executables are not installed: {', '.join(missing)}",
            install_hint="Install FFmpeg with libopus enabled.",
        )
    encoders = run((ffmpeg, "-hide_banner", "-encoders"), timeout=30)
    if "libopus" not in encoders.stdout:
        return CodecCapabilities(
            codec_id="audio.opus",
            codec_version=version_line((ffmpeg, "-version")),
            content_types=("AUDIO",),
            profiles=(Profile.FAITHFUL, Profile.ULTRA),
            enabled=False,
            deterministic=True,
            disabled_reason="FFmpeg was built without the libopus encoder",
            install_hint="Install an FFmpeg build configured with libopus.",
        )
    return CodecCapabilities(
        codec_id="audio.opus",
        codec_version=version_line((ffmpeg, "-version")),
        content_types=("AUDIO",),
        profiles=(Profile.FAITHFUL, Profile.ULTRA),
        enabled=True,
        deterministic=True,
    )


class OpusAudioAdapter:
    def capabilities(self) -> CodecCapabilities:
        return _ffmpeg_capability()

    def probe(self, source: SourceObject) -> ProbeResult:
        if not source.declared_mime.startswith(AUDIO_MIME_PREFIXES):
            return ProbeResult("application/octet-stream", False, "declared MIME is not audio")
        with tempfile.TemporaryDirectory(prefix="smcp-probe-") as directory:
            path = Path(directory) / f"input{Path(source.filename).suffix or '.bin'}"
            path.write_bytes(source.data)
            try:
                result = run(
                    (
                        "ffprobe",
                        "-v",
                        "error",
                        "-select_streams",
                        "a:0",
                        "-show_entries",
                        "stream=codec_name,sample_rate,channels",
                        "-of",
                        "csv=p=0",
                        str(path),
                    ),
                    timeout=30,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                return ProbeResult(
                    "application/octet-stream", False, "FFmpeg could not decode the audio"
                )
        accepted = bool(result.stdout.strip())
        return ProbeResult(
            source.declared_mime,
            accepted,
            "supported decoded audio" if accepted else "audio stream is missing",
        )

    def preprocess(self, source: SourceObject, profile: Profile) -> PreparedInput:
        if not self.probe(source).accepted:
            raise ValueError("source did not pass audio probing")
        filters = ["aresample=24000", "alimiter=limit=0.95"]
        if profile == Profile.ULTRA:
            filters.insert(
                0,
                "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB:"
                "stop_periods=-1:stop_duration=0.2:stop_threshold=-50dB",
            )
        canonical = transform(
            source.data,
            Path(source.filename).suffix or ".bin",
            ".wav",
            (
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                "{input}",
                "-vn",
                "-map_metadata",
                "-1",
                "-af",
                ",".join(filters),
                "-ac",
                "1",
                "-ar",
                "24000",
                "-c:a",
                "pcm_s16le",
                "-y",
                "{output}",
            ),
        )
        return PreparedInput(source.data, canonical, "audio/wav; rate=24000; channels=1")

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate:
        capability = self.capabilities()
        if not capability.enabled or prepared.canonical_bytes is None:
            raise RuntimeError(capability.disabled_reason or "canonical audio is missing")
        payload = transform(
            prepared.canonical_bytes,
            ".wav",
            ".ogg",
            (
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                "{input}",
                "-map_metadata",
                "-1",
                "-c:a",
                "libopus",
                "-b:a",
                f"{params.level}k",
                "-vbr",
                "on",
                "-compression_level",
                "10",
                "-application",
                "audio",
                "-frame_duration",
                "60",
                "-bitexact",
                "-y",
                "{output}",
            ),
        )
        return EncodedCandidate(
            "audio.opus",
            capability.codec_version,
            {
                "bitrate_kbps": params.level,
                "sample_rate": 24000,
                "channels": 1,
                "vbr": True,
                "frame_duration_ms": 60,
            },
            payload,
        )

    def decode(self, candidate: EncodedCandidate) -> bytes:
        return transform(
            candidate.payload,
            ".ogg",
            ".wav",
            (
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                "{input}",
                "-ac",
                "1",
                "-ar",
                "24000",
                "-c:a",
                "pcm_s16le",
                "-y",
                "{output}",
            ),
        )

    def measure(self, original: PreparedInput, decoded: bytes) -> QualityReport:
        if original.canonical_bytes is None:
            raise ValueError("canonical audio is missing")
        original_stats = _pcm_stats(original.canonical_bytes)
        decoded_stats = _pcm_stats(decoded)
        duration_delta = abs(original_stats["duration_seconds"] - decoded_stats["duration_seconds"])
        clipping_ratio = decoded_stats["clipped_samples"] / max(decoded_stats["samples"], 1)
        failures: list[str] = []
        if duration_delta > 0.02:
            failures.append("duration_delta_above_20ms")
        if clipping_ratio > 0.001:
            failures.append("clipping_ratio_above_0.001")
        return QualityReport(
            exact_round_trip=original.canonical_bytes == decoded,
            original_sha256=digest(original.canonical_bytes),
            decoded_sha256=digest(decoded),
            quality_gate_passed=not failures,
            metrics={
                "duration_seconds": decoded_stats["duration_seconds"],
                "duration_delta_seconds": duration_delta,
                "peak_amplitude": decoded_stats["peak_amplitude"],
                "clipping_ratio": clipping_ratio,
                "intelligibility_status": "not_evaluated:no_versioned_asr_model",
                "speaker_similarity_status": "not_evaluated:no_versioned_speaker_model",
                "perceptual_quality_status": "not_evaluated:no_versioned_metric_model",
            },
            gate_failures=tuple(failures),
        )


class SnacAudioAdapter(OpusAudioAdapter):
    """Wrapper for the pinned official SNAC 24 kHz speech checkpoint."""

    def __init__(
        self,
        manifest: ModelManifest | None = None,
        source_root: Path | None = None,
        cache_root: Path | None = None,
    ) -> None:
        self.manifest = manifest or next(
            model for model in load_catalog(MODEL_CATALOG).models if model.id == "snac"
        )
        self.source_root = source_root or Path(os.environ.get("SMCP_SNAC_ROOT", "/opt/snac"))
        self.cache_root = cache_root or Path(
            os.environ.get("SMCP_MODEL_CACHE", "/var/lib/smcp/models")
        )
        self.python_executable = os.environ.get("SMCP_SNAC_PYTHON", sys.executable)
        self._verified_artifact_signature: tuple[tuple[int, int], tuple[int, int]] | None = None

    @property
    def model_directory(self) -> Path:
        return self.cache_root / self.manifest.id / self.manifest.version

    def _capability(
        self,
        *,
        enabled: bool,
        disabled_reason: str | None = None,
        install_hint: str | None = None,
    ) -> CodecCapabilities:
        return CodecCapabilities(
            codec_id=self.manifest.codec_id,
            codec_version=self.manifest.version,
            content_types=("AUDIO",),
            profiles=(Profile.ULTRA, Profile.SEMANTIC),
            enabled=enabled,
            deterministic=True,
            disabled_reason=disabled_reason,
            install_hint=install_hint,
        )

    def capabilities(self) -> CodecCapabilities:
        if not self.manifest.enabled:
            return self._capability(
                enabled=False,
                disabled_reason=self.manifest.disabled_reason,
                install_hint=self.manifest.install_hint,
            )
        required = (
            self.source_root / "snac" / "snac.py",
            self.model_directory / "weights.bin",
            self.model_directory / "config.yaml",
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            return self._capability(
                enabled=False,
                disabled_reason=f"required pinned artifacts are missing: {', '.join(missing)}",
                install_hint=self.manifest.install_hint,
            )
        weights_path, config_path = required[1:]
        signature = (
            (weights_path.stat().st_size, weights_path.stat().st_mtime_ns),
            (config_path.stat().st_size, config_path.stat().st_mtime_ns),
        )
        if signature != self._verified_artifact_signature:
            for path, expected_sha256 in (
                (weights_path, self.manifest.weights_sha256),
                (config_path, self.manifest.config_sha256),
            ):
                with path.open("rb") as artifact:
                    actual_sha256 = hashlib.file_digest(artifact, "sha256").hexdigest()
                if actual_sha256 != expected_sha256:
                    return self._capability(
                        enabled=False,
                        disabled_reason=f"pinned artifact failed SHA-256 verification: {path}",
                        install_hint="Refetch the approved artifacts into the immutable cache.",
                    )
            self._verified_artifact_signature = signature
        return self._capability(enabled=True)

    def _command(self, mode: str, input_path: Path, output_path: Path) -> tuple[str, ...]:
        return (
            self.python_executable,
            "-m",
            "smcp_worker.snac_runtime",
            mode,
            "--weights",
            str(self.model_directory / "weights.bin"),
            "--config",
            str(self.model_directory / "config.yaml"),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        )

    @staticmethod
    def supports_prepared(prepared: PreparedInput) -> bool:
        if prepared.canonical_bytes is None:
            return False
        with wave.open(io.BytesIO(prepared.canonical_bytes), "rb") as stream:
            return (
                stream.getnchannels() == 1
                and stream.getsampwidth() == 2
                and stream.getframerate() == 24_000
                and 0 < stream.getnframes() <= SNAC_MAX_SAMPLES
            )

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate:
        capability = self.capabilities()
        if not capability.enabled or prepared.canonical_bytes is None:
            raise RuntimeError(capability.disabled_reason or "canonical audio is missing")
        payload = transform(
            prepared.canonical_bytes,
            ".wav",
            ".snac",
            self._command("encode", Path("{input}"), Path("{output}")),
            timeout=600,
        )
        if not payload.startswith(b"SMCPSNAC"):
            raise ValueError("SNAC produced an invalid token container")
        return EncodedCandidate(
            self.manifest.codec_id,
            self.manifest.version,
            {
                "bitrate_kbps": 0.98,
                "sample_rate": 24_000,
                "channels": 1,
                "checkpoint_sha256": self.manifest.weights_sha256,
                "config_sha256": self.manifest.config_sha256,
                "level": params.level,
            },
            payload,
        )

    def decode(self, candidate: EncodedCandidate) -> bytes:
        capability = self.capabilities()
        if not capability.enabled:
            raise RuntimeError(capability.disabled_reason)
        return transform(
            candidate.payload,
            ".snac",
            ".wav",
            self._command("decode", Path("{input}"), Path("{output}")),
            timeout=600,
        )


def _pcm_stats(payload: bytes) -> dict[str, float | int]:
    with wave.open(io.BytesIO(payload), "rb") as stream:
        if stream.getsampwidth() != 2 or stream.getnchannels() != 1:
            raise ValueError("quality measurement requires mono signed 16-bit PCM")
        frames = stream.readframes(stream.getnframes())
        sample_rate = stream.getframerate()
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    peak = max((abs(sample) for sample in samples), default=0)
    clipped = sum(abs(sample) >= 32767 for sample in samples)
    return {
        "samples": len(samples),
        "duration_seconds": len(samples) / sample_rate,
        "peak_amplitude": peak / 32768,
        "clipped_samples": clipped,
    }


def generate_audio_candidates(
    source: SourceObject, profile: Profile
) -> list[tuple[EncodedCandidate, QualityReport]]:
    adapters_and_levels = (
        (OpusAudioAdapter(), (12, 20, 32)),
        (SnacAudioAdapter(), (980,)),
    )
    candidates: list[tuple[EncodedCandidate, QualityReport]] = []
    for adapter, levels in adapters_and_levels:
        capability = adapter.capabilities()
        if not capability.enabled or profile not in capability.profiles:
            continue
        prepared = adapter.preprocess(source, profile)
        if isinstance(adapter, SnacAudioAdapter) and not adapter.supports_prepared(prepared):
            continue
        for level in levels:
            encode_started = time.perf_counter_ns()
            candidate = adapter.encode(prepared, EncodeParams(level=level))
            encode_duration_ms = max(
                0, (time.perf_counter_ns() - encode_started) // 1_000_000
            )
            decode_started = time.perf_counter_ns()
            decoded = adapter.decode(candidate)
            decode_duration_ms = max(
                0, (time.perf_counter_ns() - decode_started) // 1_000_000
            )
            candidate = replace(
                candidate,
                encode_duration_ms=encode_duration_ms,
                decode_duration_ms=decode_duration_ms,
            )
            report = adapter.measure(prepared, decoded)
            if report.quality_gate_passed:
                candidates.append((candidate, report))
    return pareto_frontier_per_codec(
        candidates,
        codec_id=lambda candidate: candidate.codec_id,
        payload_size=lambda candidate: len(candidate.payload),
        quality=lambda report: (
            -numeric_metric(report.metrics, "duration_delta_seconds"),
            -numeric_metric(report.metrics, "clipping_ratio"),
        ),
        stable_config=lambda candidate: repr(sorted(candidate.config.items())),
    )
