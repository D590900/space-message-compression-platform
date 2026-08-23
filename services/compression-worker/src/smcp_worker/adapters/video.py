from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from fractions import Fraction
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
from smcp_worker.coolchic_runtime import VIDEO_MAGIC as COOLCHIC_VIDEO_MAGIC
from smcp_worker.hinerv_runtime import MAGIC as HINERV_MAGIC
from smcp_worker.liveportrait_runtime import MAGIC as LIVEPORTRAIT_MAGIC
from smcp_worker.liveportrait_runtime import video_contract_supported
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

MODEL_CATALOG = Path(__file__).resolve().parents[3] / "model-manifests" / "catalog.json"


def liveportrait_manifest_for_version(
    version: str, catalog_path: Path = MODEL_CATALOG
) -> ModelManifest:
    """Resolve the immutable manifest belonging to a persisted LivePortrait stream."""
    matches = [
        model
        for model in load_catalog(catalog_path).models
        if model.codec_id == "video.liveportrait" and model.version == version
    ]
    if len(matches) != 1:
        raise LookupError(f"no unique LivePortrait manifest for persisted version {version!r}")
    return matches[0]


def coolchic_video_manifest_for_version(
    version: str, catalog_path: Path = MODEL_CATALOG
) -> ModelManifest:
    """Resolve the immutable manifest belonging to a persisted Cool-Chic video."""
    matches = [
        model
        for model in load_catalog(catalog_path).models
        if model.codec_id == "video.coolchic" and model.version == version
    ]
    if len(matches) != 1:
        raise LookupError(f"no unique Cool-Chic video manifest for persisted version {version!r}")
    return matches[0]


def hinerv_manifest_for_version(version: str, catalog_path: Path = MODEL_CATALOG) -> ModelManifest:
    """Resolve the immutable manifest belonging to a persisted HiNeRV video."""
    matches = [
        model
        for model in load_catalog(catalog_path).models
        if model.codec_id == "video.hinerv" and model.version == version
    ]
    if len(matches) != 1:
        raise LookupError(f"no unique HiNeRV manifest for persisted version {version!r}")
    return matches[0]


def _ffmpeg_capability() -> CodecCapabilities:
    ffmpeg = executable("ffmpeg")
    ffprobe = executable("ffprobe")
    if ffmpeg is None or ffprobe is None:
        missing = [
            name for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if path is None
        ]
        return CodecCapabilities(
            codec_id="video.av1",
            codec_version="unavailable",
            content_types=("VIDEO",),
            profiles=(Profile.FAITHFUL, Profile.ULTRA),
            enabled=False,
            deterministic=True,
            disabled_reason=f"required executables are not installed: {', '.join(missing)}",
            install_hint="Install FFmpeg with libsvtav1 and libopus enabled.",
        )
    encoders = run((ffmpeg, "-hide_banner", "-encoders"), timeout=30).stdout
    missing = [encoder for encoder in ("libsvtav1", "libopus") if encoder not in encoders]
    if missing:
        return CodecCapabilities(
            codec_id="video.av1",
            codec_version=version_line((ffmpeg, "-version")),
            content_types=("VIDEO",),
            profiles=(Profile.FAITHFUL, Profile.ULTRA),
            enabled=False,
            deterministic=True,
            disabled_reason=f"FFmpeg is missing required encoders: {', '.join(missing)}",
            install_hint="Install an FFmpeg build configured with SVT-AV1 and libopus.",
        )
    return CodecCapabilities(
        codec_id="video.av1",
        codec_version=version_line((ffmpeg, "-version")),
        content_types=("VIDEO",),
        profiles=(Profile.FAITHFUL, Profile.ULTRA),
        enabled=True,
        deterministic=True,
    )


class Av1VideoAdapter:
    def capabilities(self) -> CodecCapabilities:
        return _ffmpeg_capability()

    def probe(self, source: SourceObject) -> ProbeResult:
        if not source.declared_mime.startswith("video/"):
            return ProbeResult("application/octet-stream", False, "declared MIME is not video")
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
                        "v:0",
                        "-show_entries",
                        "stream=codec_name,width,height,avg_frame_rate",
                        "-of",
                        "csv=p=0",
                        str(path),
                    ),
                    timeout=30,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                return ProbeResult(
                    "application/octet-stream", False, "FFmpeg could not decode the video"
                )
        accepted = bool(result.stdout.strip())
        return ProbeResult(
            source.declared_mime,
            accepted,
            "supported decoded video" if accepted else "video stream is missing",
        )

    def preprocess(self, source: SourceObject, profile: Profile) -> PreparedInput:
        if not self.probe(source).accepted:
            raise ValueError("source did not pass video probing")
        canonical = transform(
            source.data,
            Path(source.filename).suffix or ".bin",
            ".avi",
            (
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                "{input}",
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-map_metadata",
                "-1",
                "-c:v",
                "ffv1",
                "-level",
                "3",
                "-g",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "pcm_s16le",
                "-ar",
                "48000",
                "-y",
                "{output}",
            ),
        )
        return PreparedInput(source.data, canonical, "video/x-msvideo; codecs=ffv1,pcm_s16le")

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate:
        capability = self.capabilities()
        if not capability.enabled or prepared.canonical_bytes is None:
            raise RuntimeError(capability.disabled_reason or "canonical video is missing")
        payload = transform(
            prepared.canonical_bytes,
            ".avi",
            ".mkv",
            (
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                "{input}",
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-map_metadata",
                "-1",
                "-c:v",
                "libsvtav1",
                "-preset",
                "8",
                "-crf",
                str(params.level),
                "-svtav1-params",
                "lp=1",
                "-c:a",
                "libopus",
                "-b:a",
                "48k",
                "-bitexact",
                "-y",
                "{output}",
            ),
        )
        return EncodedCandidate(
            "video.av1",
            capability.codec_version,
            {
                "crf": params.level,
                "preset": 8,
                "logical_processors": 1,
                "audio_codec": "libopus",
                "audio_bitrate_kbps": 48,
                "classification": "GENERIC",
            },
            payload,
        )

    def decode(self, candidate: EncodedCandidate) -> bytes:
        return transform(
            candidate.payload,
            ".mkv",
            ".avi",
            (
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                "{input}",
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-map_metadata",
                "-1",
                "-c:v",
                "ffv1",
                "-level",
                "3",
                "-g",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "pcm_s16le",
                "-ar",
                "48000",
                "-y",
                "{output}",
            ),
        )

    def measure(self, original: PreparedInput, decoded: bytes) -> QualityReport:
        if original.canonical_bytes is None:
            raise ValueError("canonical video is missing")
        metrics = _video_metrics(original.canonical_bytes, decoded)
        original_duration = metrics["original_duration_seconds"]
        decoded_duration = metrics["duration_seconds"]
        ssim = metrics["ssim"]
        if original_duration is None or decoded_duration is None or ssim is None:
            raise RuntimeError("required video quality metrics are missing")
        duration_delta = abs(original_duration - decoded_duration)
        failures: list[str] = []
        vmaf = metrics.get("vmaf")
        if isinstance(vmaf, float) and vmaf < 70:
            failures.append("vmaf_below_70")
        elif vmaf is None and ssim < 0.85:
            failures.append("ssim_below_0.85")
        if duration_delta > 0.05:
            failures.append("duration_delta_above_50ms")
        return QualityReport(
            exact_round_trip=original.canonical_bytes == decoded,
            original_sha256=digest(original.canonical_bytes),
            decoded_sha256=digest(decoded),
            quality_gate_passed=not failures,
            metrics={
                **metrics,
                "duration_delta_seconds": duration_delta,
                "classification": "GENERIC",
                "temporal_stability_proxy": ssim,
                "lip_sync_status": "not_applicable:generic_video",
                "pose_error_status": "not_evaluated:no_versioned_pose_model",
            },
            gate_failures=tuple(failures),
        )


class CoolChicVideoAdapter(Av1VideoAdapter):
    """Per-video overfit codec with neural decoder parameters embedded in-band."""

    def __init__(
        self, manifest: ModelManifest | None = None, source_root: Path | None = None
    ) -> None:
        self.manifest = manifest or next(
            model for model in load_catalog(MODEL_CATALOG).models if model.id == "coolchic-video"
        )
        self.source_root = source_root or Path(
            os.environ.get("SMCP_COOLCHIC_ROOT", "/opt/coolchic")
        )
        self.python_executable = os.environ.get("SMCP_COOLCHIC_PYTHON", sys.executable)

    def capabilities(self) -> CodecCapabilities:
        if not self.manifest.enabled:
            return CodecCapabilities(
                self.manifest.codec_id,
                self.manifest.version,
                ("VIDEO",),
                (Profile.ULTRA,),
                False,
                True,
                self.manifest.disabled_reason,
                self.manifest.install_hint,
            )
        required = (self.source_root / "cc_encode.py", self.source_root / "cc_decode.py")
        missing = [str(path) for path in required if not path.is_file()]
        return CodecCapabilities(
            self.manifest.codec_id,
            self.manifest.version,
            ("VIDEO",),
            (Profile.ULTRA,),
            not missing,
            True,
            f"required pinned Cool-Chic source is missing: {', '.join(missing)}"
            if missing
            else None,
            self.manifest.install_hint if missing else None,
        )

    @staticmethod
    def supports_prepared(prepared: PreparedInput) -> bool:
        if prepared.canonical_bytes is None:
            return False
        with tempfile.TemporaryDirectory(prefix="smcp-coolchic-video-support-") as directory:
            path = Path(directory) / "input.avi"
            path.write_bytes(prepared.canonical_bytes)
            try:
                report = json.loads(
                    run(
                        (
                            "ffprobe",
                            "-v",
                            "error",
                            "-count_frames",
                            "-select_streams",
                            "v:0",
                            "-show_entries",
                            "stream=width,height,avg_frame_rate,nb_read_frames",
                            "-of",
                            "json",
                            str(path),
                        ),
                        timeout=60,
                    ).stdout
                )
                stream = report["streams"][0]
                width, height = int(stream["width"]), int(stream["height"])
                rate = Fraction(stream["avg_frame_rate"])
                frames = int(stream["nb_read_frames"])
            except (KeyError, IndexError, ValueError, subprocess.SubprocessError):
                return False
        return (
            32 <= width <= 640
            and 32 <= height <= 640
            and width % 2 == 0
            and height % 2 == 0
            and 0 < rate <= 60
            and 1 <= frames <= 32
        )

    def _command(
        self, mode: str, input_path: Path, output_path: Path, *, level: int = 1
    ) -> tuple[str, ...]:
        command = (
            self.python_executable,
            "-m",
            "smcp_worker.coolchic_runtime",
            mode,
            "--source-root",
            str(self.source_root),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        )
        if mode == "encode-video":
            lmbda = {1: "0.003", 2: "0.001", 3: "0.0003"}.get(level)
            if lmbda is None:
                raise ValueError("Cool-Chic video level must be 1, 2 or 3")
            return (*command, "--iterations", "2000", "--lambda", lmbda)
        return command

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate:
        capability = self.capabilities()
        if not capability.enabled or prepared.canonical_bytes is None:
            raise RuntimeError(capability.disabled_reason or "canonical video is missing")
        if not self.supports_prepared(prepared):
            raise ValueError("video is outside the bounded Cool-Chic input contract")
        payload = transform(
            prepared.canonical_bytes,
            ".avi",
            ".smcpccv",
            self._command("encode-video", Path("{input}"), Path("{output}"), level=params.level),
            timeout=86_400,
        )
        if not payload.startswith(COOLCHIC_VIDEO_MAGIC):
            raise ValueError("Cool-Chic produced an invalid SMCP video container")
        return EncodedCandidate(
            self.manifest.codec_id,
            self.manifest.version,
            {
                "level": params.level,
                "iterations_per_frame": 2_000,
                "weights_origin": "per_asset_embedded",
                "audio_codec": "libopus",
                "audio_bitrate_kbps": 48,
                "classification": "GENERIC",
                "coding_structure": "ALL_INTRA_NO_PRETRAINED_MOTION_MODEL",
                "source_commit": self.manifest.code_commit,
            },
            payload,
        )

    def decode(self, candidate: EncodedCandidate) -> bytes:
        persisted_manifest = coolchic_video_manifest_for_version(candidate.codec_version)
        if persisted_manifest.version != self.manifest.version:
            return CoolChicVideoAdapter(
                manifest=persisted_manifest, source_root=self.source_root
            ).decode(candidate)
        capability = self.capabilities()
        if not capability.enabled:
            raise RuntimeError(capability.disabled_reason)
        return transform(
            candidate.payload,
            ".smcpccv",
            ".avi",
            self._command("decode-video", Path("{input}"), Path("{output}")),
            timeout=3_600,
        )


class HiNervVideoAdapter(Av1VideoAdapter):
    """Per-video implicit neural representation with in-band quantized weights."""

    def __init__(
        self, manifest: ModelManifest | None = None, source_root: Path | None = None
    ) -> None:
        self.manifest = manifest or next(
            model for model in load_catalog(MODEL_CATALOG).models if model.id == "hinerv-video"
        )
        self.source_root = source_root or Path(os.environ.get("SMCP_HINERV_ROOT", "/opt/hinerv"))
        self.python_executable = os.environ.get("SMCP_HINERV_PYTHON", sys.executable)

    def capabilities(self) -> CodecCapabilities:
        if not self.manifest.enabled:
            return CodecCapabilities(
                self.manifest.codec_id,
                self.manifest.version,
                ("VIDEO",),
                (Profile.ULTRA,),
                False,
                True,
                self.manifest.disabled_reason,
                self.manifest.install_hint,
            )
        required = (self.source_root / "hinerv_main.py", self.source_root / "LICENSE")
        missing = [str(path) for path in required if not path.is_file()]
        return CodecCapabilities(
            self.manifest.codec_id,
            self.manifest.version,
            ("VIDEO",),
            (Profile.ULTRA,),
            not missing,
            True,
            f"required pinned HiNeRV source is missing: {', '.join(missing)}" if missing else None,
            self.manifest.install_hint if missing else None,
        )

    @staticmethod
    def supports_prepared(prepared: PreparedInput) -> bool:
        if prepared.canonical_bytes is None:
            return False
        with tempfile.TemporaryDirectory(prefix="smcp-hinerv-support-") as directory:
            path = Path(directory) / "input.avi"
            path.write_bytes(prepared.canonical_bytes)
            try:
                report = json.loads(
                    run(
                        (
                            "ffprobe",
                            "-v",
                            "error",
                            "-count_frames",
                            "-select_streams",
                            "v:0",
                            "-show_entries",
                            "stream=width,height,avg_frame_rate,nb_read_frames",
                            "-of",
                            "json",
                            str(path),
                        ),
                        timeout=60,
                    ).stdout
                )
                stream = report["streams"][0]
                width, height = int(stream["width"]), int(stream["height"])
                rate = Fraction(stream["avg_frame_rate"])
                frames = int(stream["nb_read_frames"])
            except (KeyError, IndexError, ValueError, subprocess.SubprocessError):
                return False
        return (
            32 <= width <= 640
            and 32 <= height <= 640
            and width % 16 == 0
            and height % 16 == 0
            and 0 < rate <= 60
            and 1 <= frames <= 32
        )

    def _command(
        self, mode: str, input_path: Path, output_path: Path, *, level: int = 1
    ) -> tuple[str, ...]:
        command = (
            self.python_executable,
            "-m",
            "smcp_worker.hinerv_runtime",
            mode,
            "--source-root",
            str(self.source_root),
            "--python",
            self.python_executable,
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        )
        if mode == "encode":
            configuration = {1: (30, 32), 2: (100, 64), 3: (300, 96)}.get(level)
            if configuration is None:
                raise ValueError("HiNeRV level must be 1, 2 or 3")
            epochs, channels = configuration
            return (
                *command,
                "--epochs",
                str(epochs),
                "--channels",
                str(channels),
            )
        return command

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate:
        capability = self.capabilities()
        if not capability.enabled or prepared.canonical_bytes is None:
            raise RuntimeError(capability.disabled_reason or "canonical video is missing")
        if not self.supports_prepared(prepared):
            raise ValueError("video is outside the bounded HiNeRV input contract")
        configuration = {1: (30, 32), 2: (100, 64), 3: (300, 96)}.get(params.level)
        if configuration is None:
            raise ValueError("HiNeRV level must be 1, 2 or 3")
        epochs, channels = configuration
        payload = transform(
            prepared.canonical_bytes,
            ".avi",
            ".hnrv",
            self._command("encode", Path("{input}"), Path("{output}"), level=params.level),
            timeout=86_400,
        )
        if not payload.startswith(HINERV_MAGIC):
            raise ValueError("HiNeRV produced an invalid SMCP container")
        return EncodedCandidate(
            self.manifest.codec_id,
            self.manifest.version,
            {
                "level": params.level,
                "epochs": epochs,
                "channels": channels,
                "quantization_bits": 6,
                "weights_origin": "per_asset_embedded",
                "audio_codec": "libopus",
                "audio_bitrate_kbps": 48,
                "classification": "GENERIC",
                "source_commit": self.manifest.code_commit,
            },
            payload,
        )

    def decode(self, candidate: EncodedCandidate) -> bytes:
        persisted_manifest = hinerv_manifest_for_version(candidate.codec_version)
        if persisted_manifest.version != self.manifest.version:
            return HiNervVideoAdapter(
                manifest=persisted_manifest, source_root=self.source_root
            ).decode(candidate)
        capability = self.capabilities()
        if not capability.enabled:
            raise RuntimeError(capability.disabled_reason)
        return transform(
            candidate.payload,
            ".hnrv",
            ".avi",
            self._command("decode", Path("{input}"), Path("{output}")),
            timeout=3_600,
        )


class LivePortraitVideoAdapter(Av1VideoAdapter):
    """Detector-free wrapper for the pinned LivePortrait human-model core."""

    def __init__(
        self,
        manifest: ModelManifest | None = None,
        source_root: Path | None = None,
        cache_root: Path | None = None,
    ) -> None:
        self.manifest = manifest or next(
            model for model in load_catalog(MODEL_CATALOG).models if model.id == "liveportrait"
        )
        self.source_root = source_root or Path(
            os.environ.get("SMCP_LIVEPORTRAIT_ROOT", "/opt/liveportrait")
        )
        self.cache_root = cache_root or Path(
            os.environ.get("SMCP_MODEL_CACHE", "/var/lib/smcp/models")
        )
        self.python_executable = os.environ.get("SMCP_LIVEPORTRAIT_PYTHON", sys.executable)
        self._verified_artifact_signature: tuple[tuple[str, int, int], ...] | None = None

    @property
    def model_directory(self) -> Path:
        return self.cache_root / self.manifest.id / self.manifest.version

    @property
    def encodec_manifest(self) -> ModelManifest:
        return next(model for model in load_catalog(MODEL_CATALOG).models if model.id == "encodec")

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
            content_types=("VIDEO",),
            profiles=(Profile.ULTRA,),
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
        encodec = self.encodec_manifest
        encodec_directory = self.cache_root / encodec.id / encodec.version
        required = [
            self.source_root / "src" / "modules" / "motion_extractor.py",
            self.model_directory / "config.yaml",
            *(self.model_directory / artifact.name for artifact in self.manifest.weight_artifacts),
            encodec_directory / "weights.bin",
            encodec_directory / "config.yaml",
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            return self._capability(
                enabled=False,
                disabled_reason=f"required pinned artifacts are missing: {', '.join(missing)}",
                install_hint=self.manifest.install_hint,
            )
        signature = tuple(
            (str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in required[1:]
        )
        if signature != self._verified_artifact_signature:
            expected = {
                self.model_directory / "config.yaml": self.manifest.config_sha256,
                **{
                    self.model_directory / artifact.name: artifact.sha256
                    for artifact in self.manifest.weight_artifacts
                },
                encodec_directory / "weights.bin": encodec.weights_sha256,
                encodec_directory / "config.yaml": encodec.config_sha256,
            }
            for path, expected_sha256 in expected.items():
                with path.open("rb") as artifact_file:
                    actual_sha256 = hashlib.file_digest(artifact_file, "sha256").hexdigest()
                if actual_sha256 != expected_sha256:
                    return self._capability(
                        enabled=False,
                        disabled_reason=f"pinned artifact failed SHA-256 verification: {path}",
                        install_hint="Refetch the approved artifacts into the immutable cache.",
                    )
            self._verified_artifact_signature = signature
        return self._capability(enabled=True)

    def _command(
        self, mode: str, input_path: Path, output_path: Path, quantizer: int = 35
    ) -> tuple[str, ...]:
        encodec = self.encodec_manifest
        encodec_directory = self.cache_root / encodec.id / encodec.version
        command = (
            self.python_executable,
            "-m",
            "smcp_worker.liveportrait_runtime",
            mode,
            "--source-root",
            str(self.source_root),
            "--weights-root",
            str(self.model_directory),
            "--config",
            str(self.model_directory / "config.yaml"),
            "--encodec-weights",
            str(encodec_directory / "weights.bin"),
            "--encodec-config",
            str(encodec_directory / "config.yaml"),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        )
        return command + (("--quantizer", str(quantizer)) if mode == "encode" else ())

    @staticmethod
    def supports_prepared(prepared: PreparedInput) -> bool:
        if prepared.canonical_bytes is None:
            return False
        with tempfile.TemporaryDirectory(prefix="smcp-liveportrait-support-") as directory:
            path = Path(directory) / "input.avi"
            path.write_bytes(prepared.canonical_bytes)
            try:
                report = json.loads(
                    run(
                        (
                            "ffprobe",
                            "-v",
                            "error",
                            "-count_frames",
                            "-select_streams",
                            "v:0",
                            "-show_entries",
                            "stream=width,height,avg_frame_rate,nb_read_frames",
                            "-of",
                            "json",
                            str(path),
                        ),
                        timeout=60,
                    ).stdout
                )
                stream = report["streams"][0]
                rate = Fraction(stream["avg_frame_rate"])
                frames = int(stream["nb_read_frames"])
            except (KeyError, IndexError, ValueError, subprocess.SubprocessError):
                return False
        return video_contract_supported(
            int(stream.get("width", 0)),
            int(stream.get("height", 0)),
            rate,
            frames,
        )

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate:
        capability = self.capabilities()
        if not capability.enabled or prepared.canonical_bytes is None:
            raise RuntimeError(capability.disabled_reason or "canonical video is missing")
        if not self.supports_prepared(prepared):
            raise ValueError("video is outside the pre-aligned LivePortrait input contract")
        quantizer = params.level
        if not 20 <= quantizer <= 51:
            raise ValueError("LivePortrait AVIF quantizer must be between 20 and 51")
        payload = transform(
            prepared.canonical_bytes,
            ".avi",
            ".lprt",
            self._command("encode", Path("{input}"), Path("{output}"), quantizer),
            timeout=3_600,
        )
        if not payload.startswith(LIVEPORTRAIT_MAGIC):
            raise ValueError("LivePortrait produced an invalid motion container")
        return EncodedCandidate(
            self.manifest.codec_id,
            self.manifest.version,
            {
                "classification": "TALKING_HEAD_PREALIGNED",
                "keyframe_codec": "AVIF",
                "keyframe_quantizer": quantizer,
                "motion_keypoints": 21,
                "motion_dimensions": 3,
                "audio_codec": "EnCodec",
                "audio_bitrate_kbps": 3,
                "checkpoint_sha256": [
                    artifact.sha256 for artifact in self.manifest.weight_artifacts
                ],
                "config_sha256": self.manifest.config_sha256,
            },
            payload,
        )

    def decode(self, candidate: EncodedCandidate) -> bytes:
        persisted_manifest = liveportrait_manifest_for_version(candidate.codec_version)
        if persisted_manifest.version != self.manifest.version:
            adapter = LivePortraitVideoAdapter(
                manifest=persisted_manifest,
                source_root=self.source_root,
                cache_root=self.cache_root,
            )
            return adapter.decode(candidate)
        capability = self.capabilities()
        if not capability.enabled:
            raise RuntimeError(capability.disabled_reason)
        return transform(
            candidate.payload,
            ".lprt",
            ".avi",
            self._command("decode", Path("{input}"), Path("{output}")),
            timeout=3_600,
        )

    def measure(self, original: PreparedInput, decoded: bytes) -> QualityReport:
        if original.canonical_bytes is None:
            raise ValueError("canonical video is missing")
        metrics = _video_metrics(original.canonical_bytes, decoded)
        original_duration = metrics["original_duration_seconds"]
        decoded_duration = metrics["duration_seconds"]
        ssim = metrics["ssim"]
        if original_duration is None or decoded_duration is None or ssim is None:
            raise RuntimeError("required LivePortrait quality metrics are missing")
        duration_delta = abs(original_duration - decoded_duration)
        failures: list[str] = []
        vmaf = metrics.get("vmaf")
        if isinstance(vmaf, float) and vmaf < 70:
            failures.append("vmaf_below_70")
        elif vmaf is None and ssim < 0.85:
            failures.append("ssim_below_0.85")
        if duration_delta > 0.05:
            failures.append("duration_delta_above_50ms")
        return QualityReport(
            exact_round_trip=original.canonical_bytes == decoded,
            original_sha256=digest(original.canonical_bytes),
            decoded_sha256=digest(decoded),
            quality_gate_passed=not failures,
            metrics={
                **metrics,
                "duration_delta_seconds": duration_delta,
                "classification": "TALKING_HEAD_PREALIGNED",
                "identity_proxy_ssim": ssim,
                "temporal_stability_proxy": ssim,
                "lip_sync_duration_delta_seconds": duration_delta,
                "face_detector": "none:prealigned-contract",
            },
            gate_failures=tuple(failures),
        )


def _duration(path: Path) -> float:
    completed = run(
        (
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ),
        timeout=30,
    )
    return float(completed.stdout.strip())


def _video_metrics(original: bytes, decoded: bytes) -> dict[str, float | None]:
    with tempfile.TemporaryDirectory(prefix="smcp-video-metric-") as directory:
        root = Path(directory)
        original_path = root / "original.mkv"
        decoded_path = root / "decoded.mkv"
        vmaf_path = root / "vmaf.json"
        original_path.write_bytes(original)
        decoded_path.write_bytes(decoded)
        ssim_run = run(
            (
                "ffmpeg",
                "-v",
                "info",
                "-nostdin",
                "-i",
                str(decoded_path),
                "-i",
                str(original_path),
                "-lavfi",
                "[0:v][1:v]ssim",
                "-f",
                "null",
                "-",
            )
        )
        match = re.search(r"All:([0-9.]+)", ssim_run.stderr)
        if not match:
            raise RuntimeError("FFmpeg did not report video SSIM")
        ssim = float(match.group(1))
        vmaf: float | None = None
        filters = run(("ffmpeg", "-hide_banner", "-filters"), timeout=30).stdout
        if "libvmaf" in filters:
            run(
                (
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-i",
                    str(decoded_path),
                    "-i",
                    str(original_path),
                    "-lavfi",
                    f"[0:v][1:v]libvmaf=n_threads=1:log_fmt=json:log_path={vmaf_path}",
                    "-f",
                    "null",
                    "-",
                )
            )
            report = json.loads(vmaf_path.read_text())
            vmaf_value = report["pooled_metrics"]["vmaf"]["mean"]
            if isinstance(vmaf_value, int | float) and math.isfinite(vmaf_value):
                vmaf = float(vmaf_value)
        return {
            "ssim": ssim,
            "vmaf": vmaf,
            "duration_seconds": _duration(decoded_path),
            "original_duration_seconds": _duration(original_path),
        }


def generate_video_candidates(
    source: SourceObject, profile: Profile
) -> list[tuple[EncodedCandidate, QualityReport]]:
    adapters_and_levels = (
        (Av1VideoAdapter(), (28, 36, 44)),
        (CoolChicVideoAdapter(), (1,)),
        (HiNervVideoAdapter(), (1,)),
        (LivePortraitVideoAdapter(), (35,)),
    )
    candidates: list[tuple[EncodedCandidate, QualityReport]] = []
    for adapter, levels in adapters_and_levels:
        capability = adapter.capabilities()
        if not capability.enabled or profile not in capability.profiles:
            continue
        prepared = adapter.preprocess(source, profile)
        if isinstance(
            adapter, CoolChicVideoAdapter | HiNervVideoAdapter | LivePortraitVideoAdapter
        ) and not adapter.supports_prepared(prepared):
            continue
        for level in levels:
            encode_started = time.perf_counter_ns()
            candidate = adapter.encode(prepared, EncodeParams(level=level))
            encode_duration_ms = max(0, (time.perf_counter_ns() - encode_started) // 1_000_000)
            decode_started = time.perf_counter_ns()
            decoded = adapter.decode(candidate)
            decode_duration_ms = max(0, (time.perf_counter_ns() - decode_started) // 1_000_000)
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
            numeric_metric(report.metrics, "vmaf")
            if report.metrics["vmaf"] is not None
            else numeric_metric(report.metrics, "ssim") * 100,
            numeric_metric(report.metrics, "temporal_stability_proxy"),
            -numeric_metric(report.metrics, "duration_delta_seconds"),
        ),
        stable_config=lambda candidate: repr(sorted(candidate.config.items())),
    )
