#!/usr/bin/env python3
"""Generate the redistributable SMCP synthetic benchmark corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import tempfile
import wave
import zlib
from pathlib import Path

SEED = 590900
ROOT = Path(__file__).resolve().parent
GENERATED = ROOT / "generated"
SAMPLE_RATE = 24_000

TEXTS = {
    "text-en.txt": (
        "Telemetry packet 590900 reports nominal thermal control, stable power, "
        "and a verified capsule index. Repeatable compression preserves every byte.\n"
    ),
    "text-it.txt": (
        "Il pacchetto telemetrico 590900 segnala controllo termico nominale, "
        "alimentazione stabile e indice della capsula verificato.\n"
    ),
    "text-multilingual.txt": (
        "Earth · Terra · Земля · الأرض · पृथ्वी · 地球 · 지구\n"
        "Sequence: 0001 0001 0010 0011 0101 1000 1101\n"
        "Symbols: ΔT=-12.5 °C; integrity=sha256; status=✓\n"
    ),
}


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind + payload) & 0xFFFF_FFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    """Write deterministic RGB8 PNG bytes with no ancillary metadata."""
    if len(pixels) != width * height * 3:
        raise ValueError("RGB payload length does not match dimensions")
    rows = b"".join(
        b"\x00" + pixels[offset : offset + width * 3] for offset in range(0, len(pixels), width * 3)
    )
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(rows, level=9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def _pattern(width: int, height: int) -> bytes:
    output = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            offset = (y * width + x) * 3
            checker = 34 if ((x // 32) + (y // 32)) % 2 else 0
            output[offset] = (x * 255 // (width - 1) + checker) % 256
            output[offset + 1] = (y * 255 // (height - 1) + SEED % 67) % 256
            output[offset + 2] = ((x ^ y) + checker) % 256
    return bytes(output)


def _face(width: int, height: int, frame: int) -> bytes:
    output = bytearray(width * height * 3)
    mouth_open = 3 + abs((frame % 12) - 6)
    for y in range(height):
        for x in range(width):
            dx = x - width // 2
            dy = y - height // 2
            color = (18, 32, 54)
            if (dx * dx) / (76 * 76) + (dy * dy) / (98 * 98) <= 1:
                color = (212, 164, 126)
            if (dx - 27) ** 2 + (dy + 24) ** 2 < 7**2:
                color = (22, 24, 29)
            if (dx + 27) ** 2 + (dy + 24) ** 2 < 7**2:
                color = (22, 24, 29)
            if abs(dx) < 28 and abs(dy - 42) < mouth_open:
                color = (86, 22, 33)
            offset = (y * width + x) * 3
            output[offset : offset + 3] = bytes(color)
    return bytes(output)


def _write_audio(path: Path, duration_seconds: float = 2.0) -> None:
    frame_count = int(SAMPLE_RATE * duration_seconds)
    frames = bytearray()
    for index in range(frame_count):
        time = index / SAMPLE_RATE
        envelope = min(1.0, time * 8, (duration_seconds - time) * 8)
        carrier = math.sin(2 * math.pi * (165 + 35 * math.sin(2 * math.pi * 2.3 * time)) * time)
        formant = 0.35 * math.sin(2 * math.pi * 660 * time)
        sample = int(12_000 * envelope * (carrier + formant) / 1.35)
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(frames)


def _write_video(path: Path, audio_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to generate the video fixture")
    with tempfile.TemporaryDirectory(prefix="smcp-dataset-") as directory:
        frame_root = Path(directory)
        for frame in range(24):
            write_png(frame_root / f"frame-{frame:03d}.png", 256, 256, _face(256, 256, frame))
        subprocess.run(  # noqa: S603
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-framerate",
                "12",
                "-i",
                str(frame_root / "frame-%03d.png"),
                "-i",
                str(audio_path),
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
                "24000",
                "-shortest",
                "-y",
                str(path),
            ],
            check=True,
            timeout=120,
        )


def generate() -> dict[str, object]:
    GENERATED.mkdir(parents=True, exist_ok=True)
    for filename, content in TEXTS.items():
        (GENERATED / filename).write_text(content, encoding="utf-8", newline="")
    write_png(GENERATED / "image-pattern-512.png", 512, 512, _pattern(512, 512))
    audio_path = GENERATED / "audio-synthetic-2s.wav"
    _write_audio(audio_path)
    _write_video(GENERATED / "video-talking-head-2s.mkv", audio_path)

    files = []
    for path in sorted(GENERATED.iterdir()):
        payload = path.read_bytes()
        files.append(
            {
                "path": str(path.relative_to(ROOT)),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest: dict[str, object] = {
        "schema_version": 1,
        "seed": SEED,
        "license": "Apache-2.0",
        "files": files,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def verify() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        path = ROOT / item["path"]
        payload = path.read_bytes()
        if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise RuntimeError(f"dataset fixture does not match manifest: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    arguments = parser.parse_args()
    if arguments.verify:
        verify()
    else:
        print(json.dumps(generate(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
