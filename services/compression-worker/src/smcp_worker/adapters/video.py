from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

from smcp_worker.adapters.external import (
    digest,
    executable,
    pareto_smallest_per_codec,
    run,
    transform,
    version_line,
)
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
    adapter = Av1VideoAdapter()
    if not adapter.capabilities().enabled:
        return []
    prepared = adapter.preprocess(source, profile)
    candidates: list[tuple[EncodedCandidate, QualityReport]] = []
    for crf in (28, 36, 44):
        candidate = adapter.encode(prepared, EncodeParams(level=crf))
        report = adapter.measure(prepared, adapter.decode(candidate))
        if report.quality_gate_passed:
            candidates.append((candidate, report))
    return pareto_smallest_per_codec(
        candidates,
        codec_id=lambda candidate: candidate.codec_id,
        payload_size=lambda candidate: len(candidate.payload),
        stable_config=lambda candidate: repr(sorted(candidate.config.items())),
    )
