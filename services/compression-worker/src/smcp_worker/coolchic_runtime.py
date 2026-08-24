"""Bounded deterministic wrapper for the pinned per-asset Cool-Chic codec."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import random
import runpy
import struct
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

MAGIC = b"SMCPCCIC"
VERSION = 1
KIND_IMAGE = 1
HEADER = struct.Struct(">8sBBQ32s")
VIDEO_MAGIC = b"SMCPCCVC"
VIDEO_VERSION = 1
VIDEO_HEADER = struct.Struct(">8sBHHIIHQQ32s32s")
MAX_BITSTREAM_BYTES = 128 * 1024 * 1024
MAX_AUDIO_BYTES = 64 * 1024 * 1024
MAX_VIDEO_FRAMES = 32


def pack_container(raw: bytes, kind: int) -> bytes:
    """Authenticate one bounded upstream bitstream and identify its media kind."""
    if kind not in {KIND_IMAGE}:
        raise ValueError("unsupported Cool-Chic media kind")
    if not raw or len(raw) > MAX_BITSTREAM_BYTES:
        raise ValueError("Cool-Chic bitstream is empty or exceeds the bounded contract")
    return HEADER.pack(MAGIC, VERSION, kind, len(raw), hashlib.sha256(raw).digest()) + raw


def unpack_container(payload: bytes, expected_kind: int) -> bytes:
    """Validate lengths and digest before the upstream decoder sees any bytes."""
    if len(payload) < HEADER.size:
        raise ValueError("truncated Cool-Chic container")
    magic, version, kind, raw_length, expected_digest = HEADER.unpack_from(payload)
    if magic != MAGIC or version != VERSION or kind != expected_kind:
        raise ValueError("unsupported Cool-Chic container")
    if raw_length == 0 or raw_length > MAX_BITSTREAM_BYTES:
        raise ValueError("invalid Cool-Chic bitstream length")
    raw = payload[HEADER.size :]
    if len(raw) != raw_length:
        raise ValueError("Cool-Chic payload length mismatch")
    if not hmac.compare_digest(hashlib.sha256(raw).digest(), expected_digest):
        raise ValueError("Cool-Chic payload digest mismatch")
    return raw


def pack_video_container(
    video: bytes,
    audio: bytes,
    *,
    width: int,
    height: int,
    fps_numerator: int,
    fps_denominator: int,
    frames: int,
) -> bytes:
    """Pack one Cool-Chic video bitstream and optional deterministic Opus stream."""
    if not 32 <= width <= 640 or not 32 <= height <= 640 or width % 2 or height % 2:
        raise ValueError("video dimensions are outside the bounded contract")
    if not 1 <= frames <= MAX_VIDEO_FRAMES:
        raise ValueError("video frame count is outside the bounded contract")
    if not 1 <= fps_numerator <= 1_000_000 or not 1 <= fps_denominator <= 1_000_000:
        raise ValueError("video frame rate is outside the bounded contract")
    if Fraction(fps_numerator, fps_denominator) > 60:
        raise ValueError("video frame rate exceeds 60 fps")
    if not video or len(video) > MAX_BITSTREAM_BYTES:
        raise ValueError("Cool-Chic video bitstream is empty or too large")
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("audio stream exceeds the bounded contract")
    return (
        VIDEO_HEADER.pack(
            VIDEO_MAGIC,
            VIDEO_VERSION,
            width,
            height,
            fps_numerator,
            fps_denominator,
            frames,
            len(video),
            len(audio),
            hashlib.sha256(video).digest(),
            hashlib.sha256(audio).digest(),
        )
        + video
        + audio
    )


def unpack_video_container(payload: bytes) -> tuple[bytes, bytes, int, int, int, int, int]:
    """Authenticate all bounded video sections before decoding either stream."""
    if len(payload) < VIDEO_HEADER.size:
        raise ValueError("truncated Cool-Chic video container")
    (
        magic,
        version,
        width,
        height,
        fps_numerator,
        fps_denominator,
        frames,
        video_length,
        audio_length,
        video_digest,
        audio_digest,
    ) = VIDEO_HEADER.unpack_from(payload)
    if magic != VIDEO_MAGIC or version != VIDEO_VERSION:
        raise ValueError("unsupported Cool-Chic video container")
    if not 32 <= width <= 640 or not 32 <= height <= 640 or width % 2 or height % 2:
        raise ValueError("invalid Cool-Chic video dimensions")
    if not 1 <= frames <= MAX_VIDEO_FRAMES:
        raise ValueError("invalid Cool-Chic video frame count")
    if not 1 <= fps_numerator <= 1_000_000 or not 1 <= fps_denominator <= 1_000_000:
        raise ValueError("invalid Cool-Chic video frame rate")
    if Fraction(fps_numerator, fps_denominator) > 60:
        raise ValueError("Cool-Chic video frame rate exceeds 60 fps")
    if video_length == 0 or video_length > MAX_BITSTREAM_BYTES:
        raise ValueError("invalid Cool-Chic video bitstream length")
    if audio_length > MAX_AUDIO_BYTES:
        raise ValueError("invalid Cool-Chic audio stream length")
    if VIDEO_HEADER.size + video_length + audio_length != len(payload):
        raise ValueError("Cool-Chic video section length mismatch")
    video_start = VIDEO_HEADER.size
    video = payload[video_start : video_start + video_length]
    audio = payload[video_start + video_length :]
    if not hmac.compare_digest(hashlib.sha256(video).digest(), video_digest):
        raise ValueError("Cool-Chic video digest mismatch")
    if not hmac.compare_digest(hashlib.sha256(audio).digest(), audio_digest):
        raise ValueError("Cool-Chic audio digest mismatch")
    return video, audio, width, height, fps_numerator, fps_denominator, frames


def _seed() -> None:
    os.environ["PYTHONHASHSEED"] = "0"
    random.seed(0)
    import numpy as np  # type: ignore[import-not-found]
    import torch  # type: ignore[import-not-found]

    np.random.seed(0)
    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)


def _run_script(script: Path, arguments: list[str]) -> None:
    previous_argv = sys.argv
    previous_cwd = Path.cwd()
    try:
        sys.argv = [str(script), *arguments]
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as error:
            if error.code not in (None, 0):
                raise
    finally:
        sys.argv = previous_argv
        os.chdir(previous_cwd)


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- argv-only calls to fixed ffmpeg executables
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _probe_video(input_path: Path) -> tuple[int, int, int, int, int, bool]:
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
    has_audio = bool(audio_report.get("streams"))
    pack_video_container(
        b"probe",
        b"",
        width=width,
        height=height,
        fps_numerator=rate.numerator,
        fps_denominator=rate.denominator,
        frames=frames,
    )
    return width, height, rate.numerator, rate.denominator, frames, has_audio


def encode_image(
    source_root: Path,
    input_path: Path,
    output_path: Path,
    *,
    iterations: int,
    lmbda: float,
) -> None:
    if not 1 <= iterations <= 100_000:
        raise ValueError("Cool-Chic iteration count is outside the bounded contract")
    if not 1e-6 <= lmbda <= 0.1:
        raise ValueError("Cool-Chic lambda is outside the bounded contract")
    _seed()
    with tempfile.TemporaryDirectory(prefix="smcp-coolchic-") as directory:
        root = Path(directory)
        raw_path = root / "output.cool"
        work = root / "work"
        work.mkdir(mode=0o700)
        arguments = [
            f"--input={input_path}",
            f"--output={raw_path}",
            f"--workdir={work}",
            f"--n_itr={iterations}",
            f"--lmbda={lmbda}",
        ]
        if iterations < 2_000:
            arguments.append("--debug")
        _run_script(source_root / "cc_encode.py", arguments)
        output_path.write_bytes(pack_container(raw_path.read_bytes(), KIND_IMAGE))


def decode_image(source_root: Path, input_path: Path, output_path: Path) -> None:
    raw = unpack_container(input_path.read_bytes(), KIND_IMAGE)
    _seed()
    with tempfile.TemporaryDirectory(prefix="smcp-coolchic-") as directory:
        raw_path = Path(directory) / "input.cool"
        raw_path.write_bytes(raw)
        _run_script(
            source_root / "cc_decode.py",
            [f"--input={raw_path}", f"--output={output_path}", "--verbosity=0"],
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ValueError("Cool-Chic produced an empty reconstruction")


def encode_video(
    source_root: Path,
    input_path: Path,
    output_path: Path,
    *,
    iterations: int,
    lmbda: float,
) -> None:
    if not 1 <= iterations <= 20_000:
        raise ValueError("Cool-Chic video iteration count is outside the bounded contract")
    if not 1e-6 <= lmbda <= 0.1:
        raise ValueError("Cool-Chic video lambda is outside the bounded contract")
    width, height, fps_numerator, fps_denominator, frames, has_audio = _probe_video(input_path)
    _seed()
    with tempfile.TemporaryDirectory(prefix="smcp-coolchic-video-") as directory:
        root = Path(directory)
        raw_path = root / f"input_{width}x{height}_yuv420_8b.yuv"
        bitstream_path = root / "video.cool"
        audio_path = root / "audio.opus"
        work = root / "work"
        work.mkdir(mode=0o700)
        _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(input_path),
                "-map",
                "0:v:0",
                "-frames:v",
                str(frames),
                "-pix_fmt",
                "yuv420p",
                "-f",
                "rawvideo",
                "-y",
                str(raw_path),
            ],
            timeout=600,
        )
        if has_audio:
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
        intra_positions = ",".join(str(index) for index in range(frames))
        for coding_index in range(frames):
            arguments = [
                f"--input={raw_path}",
                f"--output={bitstream_path}",
                f"--workdir={work}",
                f"--intra_pos={intra_positions}",
                "--p_pos=",
                f"--n_frames={frames}",
                f"--coding_idx={coding_index}",
                f"--lmbda={lmbda}",
                f"--n_itr={iterations}",
                f"--dec_cfg_residue={source_root / 'cfg' / 'dec' / 'intra' / 'lop.cfg'}",
                f"--dec_cfg_motion={source_root / 'cfg' / 'dec' / 'motion' / 'lop.cfg'}",
            ]
            if iterations < 2_000:
                arguments.append("--debug")
            _run_script(source_root / "cc_encode.py", arguments)
        video = bitstream_path.read_bytes()
        audio = audio_path.read_bytes() if has_audio else b""
        output_path.write_bytes(
            pack_video_container(
                video,
                audio,
                width=width,
                height=height,
                fps_numerator=fps_numerator,
                fps_denominator=fps_denominator,
                frames=frames,
            )
        )


def decode_video(source_root: Path, input_path: Path, output_path: Path) -> None:
    video, audio, width, height, fps_numerator, fps_denominator, frames = unpack_video_container(
        input_path.read_bytes()
    )
    _seed()
    with tempfile.TemporaryDirectory(prefix="smcp-coolchic-video-") as directory:
        root = Path(directory)
        bitstream_path = root / "video.cool"
        raw_path = root / f"decoded_{width}x{height}_yuv420_8b.yuv"
        audio_path = root / "audio.opus"
        bitstream_path.write_bytes(video)
        _run_script(
            source_root / "cc_decode.py",
            [f"--input={bitstream_path}", f"--output={raw_path}", "--verbosity=0"],
        )
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            f"{fps_numerator}/{fps_denominator}",
            "-i",
            str(raw_path),
        ]
        if audio:
            audio_path.write_bytes(audio)
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
        raise ValueError("Cool-Chic produced an empty video reconstruction")


def main() -> None:
    parser = argparse.ArgumentParser(description="SMCP pinned Cool-Chic runtime")
    parser.add_argument(
        "mode", choices=("encode-image", "decode-image", "encode-video", "decode-video")
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=2_000)
    parser.add_argument("--lambda", dest="lmbda", type=float, default=0.001)
    arguments = parser.parse_args()
    if arguments.mode == "encode-image":
        encode_image(
            arguments.source_root,
            arguments.input,
            arguments.output,
            iterations=arguments.iterations,
            lmbda=arguments.lmbda,
        )
    elif arguments.mode == "decode-image":
        decode_image(arguments.source_root, arguments.input, arguments.output)
    elif arguments.mode == "encode-video":
        encode_video(
            arguments.source_root,
            arguments.input,
            arguments.output,
            iterations=arguments.iterations,
            lmbda=arguments.lmbda,
        )
    else:
        decode_video(arguments.source_root, arguments.input, arguments.output)


if __name__ == "__main__":
    main()
