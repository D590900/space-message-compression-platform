"""Bounded deterministic wrapper for the pinned per-video HiNeRV codec."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import struct
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

MAGIC = b"SMCPHNRV"
VERSION = 1
HEADER = struct.Struct(">8sBHHIIHBBQQ32s32s")
MAX_MODEL_BYTES = 128 * 1024 * 1024
MAX_AUDIO_BYTES = 64 * 1024 * 1024
MAX_FRAMES = 32
ALLOWED_CHANNELS = {8, 16, 32, 64, 96, 128}
QUANT_LEVEL = 6


def pack_container(
    model: bytes,
    audio: bytes,
    *,
    width: int,
    height: int,
    fps_numerator: int,
    fps_denominator: int,
    frames: int,
    channels: int,
) -> bytes:
    """Pack authenticated per-video weights, media metadata and optional audio."""
    _validate_contract(width, height, fps_numerator, fps_denominator, frames, channels)
    if not model or len(model) > MAX_MODEL_BYTES:
        raise ValueError("HiNeRV model bitstream is empty or too large")
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("HiNeRV audio stream exceeds the bounded contract")
    return (
        HEADER.pack(
            MAGIC,
            VERSION,
            width,
            height,
            fps_numerator,
            fps_denominator,
            frames,
            channels,
            QUANT_LEVEL,
            len(model),
            len(audio),
            hashlib.sha256(model).digest(),
            hashlib.sha256(audio).digest(),
        )
        + model
        + audio
    )


def unpack_container(payload: bytes) -> tuple[bytes, bytes, int, int, int, int, int, int]:
    """Authenticate every bounded section before HiNeRV or FFmpeg sees it."""
    if len(payload) < HEADER.size:
        raise ValueError("truncated HiNeRV container")
    (
        magic,
        version,
        width,
        height,
        fps_numerator,
        fps_denominator,
        frames,
        channels,
        quant_level,
        model_length,
        audio_length,
        model_digest,
        audio_digest,
    ) = HEADER.unpack_from(payload)
    if magic != MAGIC or version != VERSION or quant_level != QUANT_LEVEL:
        raise ValueError("unsupported HiNeRV container")
    _validate_contract(width, height, fps_numerator, fps_denominator, frames, channels)
    if model_length == 0 or model_length > MAX_MODEL_BYTES:
        raise ValueError("invalid HiNeRV model length")
    if audio_length > MAX_AUDIO_BYTES:
        raise ValueError("invalid HiNeRV audio length")
    if HEADER.size + model_length + audio_length != len(payload):
        raise ValueError("HiNeRV section length mismatch")
    model_start = HEADER.size
    model = payload[model_start : model_start + model_length]
    audio = payload[model_start + model_length :]
    if not hmac.compare_digest(hashlib.sha256(model).digest(), model_digest):
        raise ValueError("HiNeRV model digest mismatch")
    if not hmac.compare_digest(hashlib.sha256(audio).digest(), audio_digest):
        raise ValueError("HiNeRV audio digest mismatch")
    return model, audio, width, height, fps_numerator, fps_denominator, frames, channels


def _validate_contract(
    width: int,
    height: int,
    fps_numerator: int,
    fps_denominator: int,
    frames: int,
    channels: int,
) -> None:
    if not 32 <= width <= 640 or not 32 <= height <= 640:
        raise ValueError("HiNeRV dimensions are outside the bounded contract")
    if width % 16 or height % 16:
        raise ValueError("HiNeRV dimensions must be divisible by 16")
    if not 1 <= frames <= MAX_FRAMES:
        raise ValueError("HiNeRV frame count is outside the bounded contract")
    if not 1 <= fps_numerator <= 1_000_000 or not 1 <= fps_denominator <= 1_000_000:
        raise ValueError("HiNeRV frame rate is outside the bounded contract")
    if Fraction(fps_numerator, fps_denominator) > 60:
        raise ValueError("HiNeRV frame rate exceeds 60 fps")
    if channels not in ALLOWED_CHANNELS:
        raise ValueError("unsupported HiNeRV channel count")


def _run(
    command: list[str], *, timeout: int, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    return subprocess.run(  # noqa: S603 -- argv-only calls to fixed executables
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        env=environment,
    )


def _probe(input_path: Path) -> tuple[int, int, int, int, int, bool]:
    report = json.loads(
        _run(
            [
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
                str(input_path),
            ],
            timeout=60,
        ).stdout
    )
    stream = report["streams"][0]
    width, height = int(stream["width"]), int(stream["height"])
    rate = Fraction(stream["avg_frame_rate"])
    frames = int(stream["nb_read_frames"])
    audio_report = json.loads(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "json",
                str(input_path),
            ],
            timeout=60,
        ).stdout
    )
    return (
        width,
        height,
        rate.numerator,
        rate.denominator,
        frames,
        bool(audio_report.get("streams")),
    )


def _hinerv_arguments(
    *,
    source_root: Path,
    dataset_root: Path,
    output_root: Path,
    experiment: str,
    width: int,
    height: int,
    channels: int,
    epochs: int,
    bitstream_root: Path | None = None,
) -> list[str]:
    arguments = [
        str(source_root / "hinerv_main.py"),
        "--dataset",
        str(dataset_root),
        "--dataset-name",
        "video",
        "--output",
        str(output_root),
        "--exp-name",
        experiment,
        "--input-size",
        str(height),
        str(width),
        "--crop-size",
        "-1",
        "-1",
        "--patch-size",
        "1",
        str(height),
        str(width),
        "--cached",
        "patch",
        "--epochs",
        str(epochs),
        "--eval-epochs",
        str(epochs),
        "--log-epochs",
        "-1",
        "--prune-epochs",
        "0",
        "--quant-epochs",
        "1",
        "--quant-warmup-epochs",
        "0",
        "--quant-level",
        str(QUANT_LEVEL),
        "--batch-size",
        "1",
        "--eval-batch-size",
        "1",
        "--workers",
        "1",
        "--pin-mem",
        "false",
        "--log-eval",
        "true",
        "--loss",
        "mse",
        "--train-metric",
        "psnr",
        "--eval-metric",
        "psnr",
        "--opt",
        "adam",
        "--lr",
        "0.001",
        "--warmup-epochs",
        "0",
        "--warmup-lr",
        "0.001",
        "--min-lr",
        "0.001",
        "--channels",
        str(channels),
        "--channels-reduce",
        "2",
        "--depths",
        "1",
        "1",
        "--exps",
        "1",
        "1",
        "--stem-kernels",
        "1",
        "--kernels",
        "1",
        "1",
        "--scales-t",
        "1",
        "1",
        "--scales-hw",
        "4",
        "4",
        "--stem-paddings",
        "-1",
        "-1",
        "-1",
        "--paddings",
        "-1",
        "-1",
        "-1",
        "--base-size",
        "-1",
        "-1",
        "-1",
        "--base-grid-size",
        "-1",
        "-1",
        "-1",
        "4",
        "--base-grid-level",
        "1",
        "--base-grid-level-scale",
        "1",
        "1",
        "1",
        "1",
        "--enc-type",
        "none",
        "--upsample-type",
        "trilinear",
        "--upsample-config",
        "matmul-th-w",
        "--quant-noise",
        "0.9",
        "--quant-ste",
        "false",
        "--seed",
        "0",
    ]
    if bitstream_root is not None:
        arguments.extend(
            [
                "--bitstream",
                str(bitstream_root),
                "--bitstream-q",
                str(QUANT_LEVEL),
                "--eval-only",
            ]
        )
    return arguments


def _extract_audio(input_path: Path, audio_path: Path) -> None:
    _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(input_path),
            "-map",
            "0:a:0",
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-c:a",
            "libopus",
            "-b:a",
            "48k",
            "-flags:a",
            "+bitexact",
            "-y",
            str(audio_path),
        ],
        timeout=600,
    )


def encode(
    source_root: Path,
    python_executable: Path,
    input_path: Path,
    output_path: Path,
    *,
    epochs: int,
    channels: int,
) -> None:
    if not 1 <= epochs <= 300:
        raise ValueError("HiNeRV epoch count is outside the bounded contract")
    width, height, fps_numerator, fps_denominator, frames, has_audio = _probe(input_path)
    _validate_contract(width, height, fps_numerator, fps_denominator, frames, channels)
    with tempfile.TemporaryDirectory(prefix="smcp-hinerv-") as directory:
        root = Path(directory)
        dataset_root = root / "dataset"
        frame_root = dataset_root / "video"
        output_root = root / "output"
        frame_root.mkdir(parents=True)
        output_root.mkdir()
        _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(input_path),
                "-frames:v",
                str(frames),
                "-fps_mode",
                "passthrough",
                str(frame_root / "%04d.png"),
            ],
            timeout=600,
        )
        _run(
            [
                str(python_executable),
                *_hinerv_arguments(
                    source_root=source_root,
                    dataset_root=dataset_root,
                    output_root=output_root,
                    experiment="encode",
                    width=width,
                    height=height,
                    channels=channels,
                    epochs=epochs,
                ),
            ],
            timeout=86_400,
            cwd=source_root,
        )
        model_path = output_root / "encode" / "bitstreams" / f"Q{QUANT_LEVEL}.zip"
        audio_path = root / "audio.opus"
        if has_audio:
            _extract_audio(input_path, audio_path)
        output_path.write_bytes(
            pack_container(
                model_path.read_bytes(),
                audio_path.read_bytes() if has_audio else b"",
                width=width,
                height=height,
                fps_numerator=fps_numerator,
                fps_denominator=fps_denominator,
                frames=frames,
                channels=channels,
            )
        )


def decode(
    source_root: Path,
    python_executable: Path,
    input_path: Path,
    output_path: Path,
) -> None:
    model, audio, width, height, fps_numerator, fps_denominator, frames, channels = (
        unpack_container(input_path.read_bytes())
    )
    with tempfile.TemporaryDirectory(prefix="smcp-hinerv-") as directory:
        root = Path(directory)
        dataset_root = root / "dataset"
        frame_root = dataset_root / "video"
        output_root = root / "output"
        bitstream_root = root / "bitstream"
        bitstream_dir = bitstream_root / "bitstreams"
        frame_root.mkdir(parents=True)
        output_root.mkdir()
        bitstream_dir.mkdir(parents=True)
        (bitstream_dir / f"Q{QUANT_LEVEL}.zip").write_bytes(model)
        _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=black:size={width}x{height}:rate={fps_numerator}/{fps_denominator}",
                "-frames:v",
                str(frames),
                str(frame_root / "%04d.png"),
            ],
            timeout=600,
        )
        _run(
            [
                str(python_executable),
                *_hinerv_arguments(
                    source_root=source_root,
                    dataset_root=dataset_root,
                    output_root=output_root,
                    experiment="decode",
                    width=width,
                    height=height,
                    channels=channels,
                    epochs=1,
                    bitstream_root=bitstream_root,
                ),
            ],
            timeout=3_600,
            cwd=source_root,
        )
        reconstructed = output_root / "decode" / "eval_output" / "0"
        images = sorted(reconstructed.glob("*.png"))
        if len(images) != frames:
            raise ValueError("HiNeRV reconstructed an unexpected number of frames")
        audio_path = root / "audio.opus"
        if audio:
            audio_path.write_bytes(audio)
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-framerate",
            f"{fps_numerator}/{fps_denominator}",
            "-pattern_type",
            "glob",
            "-i",
            str(reconstructed / "*.png"),
        ]
        if audio:
            command.extend(["-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0"])
        else:
            command.extend(["-map", "0:v:0"])
        command.extend(
            [
                "-frames:v",
                str(frames),
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
            ]
        )
        if audio:
            command.extend(["-c:a", "pcm_s16le", "-ar", "48000"])
        command.extend(["-y", str(output_path)])
        _run(command, timeout=600)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ValueError("HiNeRV produced an empty reconstruction")


def main() -> None:
    parser = argparse.ArgumentParser(description="SMCP pinned HiNeRV runtime")
    parser.add_argument("mode", choices=("encode", "decode"))
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--channels", type=int, default=32)
    arguments = parser.parse_args()
    if arguments.mode == "encode":
        encode(
            arguments.source_root,
            arguments.python,
            arguments.input,
            arguments.output,
            epochs=arguments.epochs,
            channels=arguments.channels,
        )
    else:
        decode(
            arguments.source_root,
            arguments.python,
            arguments.input,
            arguments.output,
        )


if __name__ == "__main__":
    main()
