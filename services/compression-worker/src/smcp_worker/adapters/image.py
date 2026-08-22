from __future__ import annotations

import math
import re
import subprocess
import tempfile
import time
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

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/avif"}


def _capability(
    *,
    codec_id: str,
    command: str,
    decoder: str,
    version_args: tuple[str, ...],
    install_hint: str,
) -> CodecCapabilities:
    required = (command, decoder, "ffmpeg", "ffprobe")
    missing = [name for name in required if executable(name) is None]
    if missing:
        return CodecCapabilities(
            codec_id=codec_id,
            codec_version="unavailable",
            content_types=("IMAGE",),
            profiles=(Profile.FAITHFUL, Profile.ULTRA),
            enabled=False,
            deterministic=True,
            disabled_reason=f"required executables are not installed: {', '.join(missing)}",
            install_hint=install_hint,
        )
    path = executable(command)
    if path is None:  # Narrowed defensively for static type checking.
        raise RuntimeError(f"required executable disappeared: {command}")
    return CodecCapabilities(
        codec_id=codec_id,
        codec_version=version_line((path, *version_args)),
        content_types=("IMAGE",),
        profiles=(Profile.FAITHFUL, Profile.ULTRA),
        enabled=True,
        deterministic=True,
    )


class ImageAdapterMixin:
    def probe(self, source: SourceObject) -> ProbeResult:
        if source.declared_mime not in IMAGE_MIME_TYPES:
            return ProbeResult("application/octet-stream", False, "declared MIME is not an image")
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
                        "stream=codec_name,width,height",
                        "-of",
                        "csv=p=0",
                        str(path),
                    ),
                    timeout=30,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                return ProbeResult(
                    "application/octet-stream", False, "FFmpeg could not decode the image"
                )
        accepted = bool(result.stdout.strip())
        return ProbeResult(
            source.declared_mime,
            accepted,
            "supported decoded image" if accepted else "image stream is missing",
        )

    def preprocess(self, source: SourceObject, profile: Profile) -> PreparedInput:
        if not self.probe(source).accepted:
            raise ValueError("source did not pass image probing")
        canonical = transform(
            source.data,
            Path(source.filename).suffix or ".bin",
            ".png",
            (
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                "{input}",
                "-map_metadata",
                "-1",
                "-frames:v",
                "1",
                "-pix_fmt",
                "rgb24",
                "-y",
                "{output}",
            ),
        )
        return PreparedInput(source.data, canonical, "image/png")

    def measure(self, original: PreparedInput, decoded: bytes) -> QualityReport:
        if original.canonical_bytes is None:
            raise ValueError("canonical image is missing")
        scale_scores = _multiscale_ssim(original.canonical_bytes, decoded)
        weights = (0.1, 0.2, 0.3, 0.4)[: len(scale_scores)]
        weight_sum = sum(weights)
        ms_ssim = math.exp(
            sum(
                weight * math.log(max(score, 1e-12))
                for weight, score in zip(weights, scale_scores, strict=True)
            )
            / weight_sum
        )
        psnr = _psnr(original.canonical_bytes, decoded)
        failures = () if ms_ssim >= 0.90 else ("ms_ssim_below_0.90",)
        return QualityReport(
            exact_round_trip=original.canonical_bytes == decoded,
            original_sha256=digest(original.canonical_bytes),
            decoded_sha256=digest(decoded),
            quality_gate_passed=not failures,
            metrics={
                "bytes": len(decoded),
                "ms_ssim": ms_ssim,
                "psnr_db": psnr,
                "lpips": None,
                "lpips_status": "disabled:no_versioned_weights",
                "identity_status": "not_evaluated:no_versioned_face_model",
            },
            gate_failures=failures,
        )


class AvifImageAdapter(ImageAdapterMixin):
    def capabilities(self) -> CodecCapabilities:
        return _capability(
            codec_id="image.avif",
            command="avifenc",
            decoder="avifdec",
            version_args=("--version",),
            install_hint="Install libavif tools (for example: brew install libavif).",
        )

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate:
        capability = self.capabilities()
        if not capability.enabled or prepared.canonical_bytes is None:
            raise RuntimeError(capability.disabled_reason or "canonical image is missing")
        payload = transform(
            prepared.canonical_bytes,
            ".png",
            ".avif",
            (
                "avifenc",
                "--jobs",
                "1",
                "--speed",
                "6",
                "--min",
                str(params.level),
                "--max",
                str(params.level),
                "{input}",
                "{output}",
            ),
        )
        return EncodedCandidate(
            "image.avif",
            capability.codec_version,
            {"quantizer": params.level, "speed": 6, "jobs": 1},
            payload,
        )

    def decode(self, candidate: EncodedCandidate) -> bytes:
        return transform(
            candidate.payload,
            ".avif",
            ".png",
            ("avifdec", "--jobs", "1", "{input}", "{output}"),
        )


class JpegXlImageAdapter(ImageAdapterMixin):
    def capabilities(self) -> CodecCapabilities:
        return _capability(
            codec_id="image.jpeg-xl",
            command="cjxl",
            decoder="djxl",
            version_args=("--version",),
            install_hint="Install JPEG XL tools (for example: brew install jpeg-xl).",
        )

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate:
        capability = self.capabilities()
        if not capability.enabled or prepared.canonical_bytes is None:
            raise RuntimeError(capability.disabled_reason or "canonical image is missing")
        distance = params.level / 10
        payload = transform(
            prepared.canonical_bytes,
            ".png",
            ".jxl",
            (
                "cjxl",
                "{input}",
                "{output}",
                "--distance",
                str(distance),
                "--effort",
                "7",
                "--num_threads",
                "1",
            ),
        )
        return EncodedCandidate(
            "image.jpeg-xl",
            capability.codec_version,
            {"distance": distance, "effort": 7, "threads": 1},
            payload,
        )

    def decode(self, candidate: EncodedCandidate) -> bytes:
        return transform(
            candidate.payload,
            ".jxl",
            ".png",
            ("djxl", "{input}", "{output}", "--num_threads", "1"),
        )


def _metric(original: bytes, decoded: bytes, filter_name: str, pattern: str) -> float:
    with tempfile.TemporaryDirectory(prefix="smcp-metric-") as directory:
        root = Path(directory)
        original_path = root / "original.png"
        decoded_path = root / "decoded.png"
        original_path.write_bytes(original)
        decoded_path.write_bytes(decoded)
        completed = run(
            (
                "ffmpeg",
                "-v",
                "info",
                "-nostdin",
                "-i",
                str(original_path),
                "-i",
                str(decoded_path),
                "-lavfi",
                filter_name,
                "-f",
                "null",
                "-",
            )
        )
    match = re.search(pattern, completed.stderr)
    if not match:
        raise RuntimeError(f"FFmpeg did not report {filter_name}")
    value = match.group(1)
    return math.inf if value == "inf" else float(value)


def _multiscale_ssim(original: bytes, decoded: bytes) -> list[float]:
    # FFmpeg's SSIM implementation is evaluated at four reconstruction scales.
    # The weighted geometric aggregation is recorded as ms_ssim in the report.
    scores = [_metric(original, decoded, "ssim", r"All:([0-9.]+)")]
    for divisor in (2, 4, 8):
        expression = (
            f"[0:v]scale=trunc(iw/{divisor}/2)*2:trunc(ih/{divisor}/2)*2[a];"
            f"[1:v]scale=trunc(iw/{divisor}/2)*2:trunc(ih/{divisor}/2)*2[b];[a][b]ssim"
        )
        try:
            scores.append(_metric(original, decoded, expression, r"All:([0-9.]+)"))
        except subprocess.CalledProcessError:
            break
    return scores


def _psnr(original: bytes, decoded: bytes) -> float:
    return _metric(original, decoded, "psnr", r"average:([0-9.]+|inf)")


def generate_image_candidates(
    source: SourceObject, profile: Profile
) -> list[tuple[EncodedCandidate, QualityReport]]:
    adapters_and_levels = (
        (AvifImageAdapter(), (20, 32, 44)),
        (JpegXlImageAdapter(), (5, 10, 20)),
    )
    candidates: list[tuple[EncodedCandidate, QualityReport]] = []
    for adapter, levels in adapters_and_levels:
        if not adapter.capabilities().enabled:
            continue
        prepared = adapter.preprocess(source, profile)
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
            numeric_metric(report.metrics, "ms_ssim"),
            numeric_metric(report.metrics, "psnr_db"),
        ),
        stable_config=lambda candidate: repr(sorted(candidate.config.items())),
    )
