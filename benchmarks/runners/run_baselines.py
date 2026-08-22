#!/usr/bin/env python3
"""Run SMCP CPU baselines and derive JSON, CSV and Markdown reports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import resource
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Protocol

from smcp_worker.adapters.audio import OpusAudioAdapter
from smcp_worker.adapters.image import AvifImageAdapter, JpegXlImageAdapter
from smcp_worker.adapters.text import BrotliTextAdapter, ZstandardTextAdapter
from smcp_worker.adapters.video import Av1VideoAdapter
from smcp_worker.models import EncodeParams, Profile, QualityReport, SourceObject

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "benchmarks" / "datasets" / "generated"


class Adapter(Protocol):
    def capabilities(self) -> Any: ...

    def preprocess(self, source: SourceObject, profile: Profile) -> Any: ...

    def encode(self, prepared: Any, params: EncodeParams) -> Any: ...

    def decode(self, candidate: Any) -> bytes: ...

    def measure(self, original: Any, decoded: bytes) -> QualityReport: ...


def _command_version(command: str, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603
            [command, *arguments], capture_output=True, check=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return (completed.stdout or completed.stderr).splitlines()[0]


def _git_commit() -> str:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to identify benchmark source revision")
    completed = subprocess.run(  # noqa: S603
        [git, "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()


def _attempt(
    fixture: Path,
    content_type: str,
    mime: str,
    adapter: Adapter,
    level: int,
) -> dict[str, Any]:
    source_bytes = fixture.read_bytes()
    capability = adapter.capabilities()
    base: dict[str, Any] = {
        "fixture": fixture.name,
        "fixture_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "content_type": content_type,
        "profile": "ultra",
        "codec_id": capability.codec_id,
        "codec_version": capability.codec_version,
        "level": level,
        "input_bytes": len(source_bytes),
        "container_overhead_bytes": 0,
        "enabled": capability.enabled,
        "success": False,
    }
    if not capability.enabled:
        return {
            **base,
            "failure": capability.disabled_reason,
            "install_hint": capability.install_hint,
        }
    started = time.perf_counter_ns()
    try:
        prepared = adapter.preprocess(SourceObject(source_bytes, mime, fixture.name), Profile.ULTRA)
        encode_started = time.perf_counter_ns()
        candidate = adapter.encode(prepared, EncodeParams(level=level))
        encode_ns = time.perf_counter_ns() - encode_started
        decode_started = time.perf_counter_ns()
        decoded = adapter.decode(candidate)
        decode_ns = time.perf_counter_ns() - decode_started
        report = adapter.measure(prepared, decoded)
    except Exception as error:  # Benchmark output must retain individual codec failures.
        return {
            **base,
            "elapsed_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
            "failure": f"{type(error).__name__}: {error}",
        }
    return {
        **base,
        "success": True,
        "output_payload_bytes": len(candidate.payload),
        "payload_sha256": hashlib.sha256(candidate.payload).hexdigest(),
        "ratio": round(len(source_bytes) / max(len(candidate.payload), 1), 6),
        "encode_ms": round(encode_ns / 1_000_000, 3),
        "decode_ms": round(decode_ns / 1_000_000, 3),
        "elapsed_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
        "config": candidate.config,
        "config_sha256": hashlib.sha256(
            json.dumps(candidate.config, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "model_id": None,
        "model_hash": None,
        "quality_gate_passed": report.quality_gate_passed,
        "quality_metrics": report.metrics,
        "gate_failures": list(report.gate_failures),
        "decoded_sha256": report.decoded_sha256,
        "determinism_status": "BIT_EXACT" if capability.deterministic else "NON_BIT_EXACT",
    }


def _cases(selected: set[str]) -> list[tuple[Path, str, str, Adapter, tuple[int, ...]]]:
    cases: list[tuple[Path, str, str, Adapter, tuple[int, ...]]] = []
    if "text" in selected:
        for fixture in sorted(DATASET.glob("text-*.txt")):
            cases.extend(
                [
                    (fixture, "TEXT", "text/plain", BrotliTextAdapter(), (5, 9, 11)),
                    (fixture, "TEXT", "text/plain", ZstandardTextAdapter(), (9, 19, 22)),
                ]
            )
    if "image" in selected:
        fixture = DATASET / "image-pattern-512.png"
        cases.extend(
            [
                (fixture, "IMAGE", "image/png", AvifImageAdapter(), (20, 32, 44)),
                (fixture, "IMAGE", "image/png", JpegXlImageAdapter(), (5, 10, 20)),
            ]
        )
    if "audio" in selected:
        cases.append(
            (
                DATASET / "audio-synthetic-2s.wav",
                "AUDIO",
                "audio/wav",
                OpusAudioAdapter(),
                (12, 20, 32),
            )
        )
    if "video" in selected:
        cases.append(
            (
                DATASET / "video-talking-head-2s.mkv",
                "VIDEO",
                "video/x-matroska",
                Av1VideoAdapter(),
                (28, 36, 44),
            )
        )
    return cases


def _environment() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "commit": _git_commit(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "not_reported",
        "python": platform.python_version(),
        "logical_cpu_count": os.cpu_count(),
        "peak_rss_kib": usage.ru_maxrss,
        "ffmpeg": _command_version("ffmpeg", "-version"),
        "avifenc": _command_version("avifenc", "--version"),
        "cjxl": _command_version("cjxl", "--version"),
    }


def _write_csv(path: Path, attempts: list[dict[str, Any]]) -> None:
    fields = [
        "fixture",
        "content_type",
        "codec_id",
        "codec_version",
        "level",
        "input_bytes",
        "output_payload_bytes",
        "payload_sha256",
        "container_overhead_bytes",
        "ratio",
        "encode_ms",
        "decode_ms",
        "quality_gate_passed",
        "success",
        "determinism_status",
        "config_sha256",
        "model_id",
        "model_hash",
        "quality_metrics",
        "failure",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for attempt in attempts:
            row = {**attempt}
            row["quality_metrics"] = json.dumps(
                attempt.get("quality_metrics", {}), sort_keys=True, separators=(",", ":")
            )
            writer.writerow(row)


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    attempts = report["attempts"]
    lines = [
        "# Generated CPU baseline report",
        "",
        "> This file is derived from `results.json`; target values are not copied into results.",
        "",
        f"Commit: `{report['environment']['commit']}`  ",
        f"Platform: `{report['environment']['platform']}`  ",
        f"Generated (UTC): `{report['generated_at_utc']}`",
        "",
        "| Fixture | Codec | Level | Input | Payload | Ratio | Encode ms | Decode ms | Gate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in attempts:
        if item["success"]:
            lines.append(
                f"| {item['fixture']} | {item['codec_id']} | {item['level']} | "
                f"{item['input_bytes']} | {item['output_payload_bytes']} | {item['ratio']:.3f} | "
                f"{item['encode_ms']:.3f} | {item['decode_ms']:.3f} | "
                f"{'pass' if item['quality_gate_passed'] else 'fail'} |"
            )
        else:
            lines.append(
                f"| {item['fixture']} | {item['codec_id']} | {item['level']} | "
                f"{item['input_bytes']} | — | — | — | — | unavailable/failure |"
            )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "This synthetic corpus is a reproducibility smoke set, not a representative "
            "human media corpus. Neural quality metrics and identity, speaker, ASR, pose, "
            "and lip-sync models remain explicitly "
            "unavailable until separately licensed, hashed manifests are installed.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--types",
        nargs="+",
        choices=("text", "image", "audio", "video"),
        default=["text", "image", "audio", "video"],
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    selected = set(arguments.types)
    attempts = [
        _attempt(fixture, content_type, mime, adapter, level)
        for fixture, content_type, mime, adapter, levels in _cases(selected)
        for level in levels
    ]
    report = {
        "schema_version": 1,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset_manifest_sha256": hashlib.sha256(
            (ROOT / "benchmarks" / "datasets" / "manifest.json").read_bytes()
        ).hexdigest(),
        "environment": _environment(),
        "attempts": attempts,
    }
    arguments.output.mkdir(parents=True, exist_ok=True)
    (arguments.output / "results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(arguments.output / "results.csv", attempts)
    _write_markdown(arguments.output / "README.md", report)
    print(json.dumps({"attempts": len(attempts), "output": str(arguments.output)}))


if __name__ == "__main__":
    main()
