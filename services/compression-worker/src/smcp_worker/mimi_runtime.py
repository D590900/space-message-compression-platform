"""Pinned Mimi inference entry point and deterministic token container."""

from __future__ import annotations

import argparse
import io
import json
import os
import struct
import wave
from collections.abc import Sequence
from pathlib import Path

MAGIC = b"SMCPMIMI"
FORMAT_VERSION = 1
SAMPLE_RATE = 24_000
FRAME_SAMPLES = 1_920
CODEBOOK_SIZE = 2_048
CODEBOOK_BITS = 11
CODEBOOK_COUNT = 8
MAX_SAMPLES = SAMPLE_RATE * 30
HEADER = struct.Struct(">8sBBIII")


def pack_tokens(codebooks: Sequence[Sequence[int]], sample_count: int) -> bytes:
    """Serialize eight 11-bit Mimi codebooks without Python object formats."""
    if not 0 < sample_count <= MAX_SAMPLES:
        raise ValueError("sample count is outside the supported range")
    if len(codebooks) != CODEBOOK_COUNT:
        raise ValueError("Mimi 1.1 kbps requires exactly eight codebooks")
    frame_count = len(codebooks[0])
    if frame_count == 0 or any(len(codebook) != frame_count for codebook in codebooks):
        raise ValueError("Mimi codebooks must have equal non-zero lengths")
    maximum_frames = (sample_count + FRAME_SAMPLES - 1) // FRAME_SAMPLES + 1
    if frame_count > maximum_frames:
        raise ValueError("Mimi frame count exceeds the declared sample count")
    values = [value for codebook in codebooks for value in codebook]
    if any(not 0 <= value < CODEBOOK_SIZE for value in values):
        raise ValueError("Mimi token is outside the 11-bit codebook")

    output = bytearray(
        HEADER.pack(
            MAGIC,
            FORMAT_VERSION,
            CODEBOOK_COUNT,
            SAMPLE_RATE,
            sample_count,
            frame_count,
        )
    )
    accumulator = 0
    bits = 0
    for value in values:
        accumulator = (accumulator << CODEBOOK_BITS) | value
        bits += CODEBOOK_BITS
        while bits >= 8:
            bits -= 8
            output.append((accumulator >> bits) & 0xFF)
            accumulator &= (1 << bits) - 1
    if bits:
        output.append((accumulator << (8 - bits)) & 0xFF)
    return bytes(output)


def unpack_tokens(payload: bytes) -> tuple[int, list[list[int]]]:
    """Parse a bounded Mimi token container and reject non-canonical encodings."""
    if len(payload) < HEADER.size:
        raise ValueError("truncated Mimi container")
    magic, version, codebook_count, sample_rate, sample_count, frame_count = (
        HEADER.unpack_from(payload)
    )
    if magic != MAGIC or version != FORMAT_VERSION or sample_rate != SAMPLE_RATE:
        raise ValueError("unsupported Mimi container")
    maximum_frames = (sample_count + FRAME_SAMPLES - 1) // FRAME_SAMPLES + 1
    if (
        not 0 < sample_count <= MAX_SAMPLES
        or codebook_count != CODEBOOK_COUNT
        or not 0 < frame_count <= maximum_frames
    ):
        raise ValueError("invalid Mimi container dimensions")
    total = codebook_count * frame_count
    expected_bytes = (total * CODEBOOK_BITS + 7) // 8
    if len(payload) != HEADER.size + expected_bytes:
        raise ValueError("Mimi token payload length mismatch")

    values: list[int] = []
    accumulator = 0
    bits = 0
    for octet in payload[HEADER.size :]:
        accumulator = (accumulator << 8) | octet
        bits += 8
        while bits >= CODEBOOK_BITS and len(values) < total:
            bits -= CODEBOOK_BITS
            values.append((accumulator >> bits) & (CODEBOOK_SIZE - 1))
            accumulator &= (1 << bits) - 1
    if len(values) != total or accumulator:
        raise ValueError("non-canonical Mimi token padding")
    return sample_count, [
        values[index * frame_count : (index + 1) * frame_count]
        for index in range(codebook_count)
    ]


def _read_pcm(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as stream:
        if (
            stream.getnchannels() != 1
            or stream.getsampwidth() != 2
            or stream.getframerate() != SAMPLE_RATE
            or stream.getcomptype() != "NONE"
        ):
            raise ValueError("Mimi input must be mono 24 kHz signed 16-bit PCM WAV")
        sample_count = stream.getnframes()
        frames = stream.readframes(sample_count)
    if not 0 < sample_count <= MAX_SAMPLES or len(frames) != sample_count * 2:
        raise ValueError("invalid PCM sample count")
    samples = struct.unpack(f"<{sample_count}h", frames)
    return sample_count, [sample / 32768.0 for sample in samples]


def _write_pcm(path: Path, samples: Sequence[float]) -> None:
    pcm = [max(-32768, min(32767, round(sample * 32768.0))) for sample in samples]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))
    path.write_bytes(buffer.getvalue())


def _load_model(weights: Path, config: Path):  # type: ignore[no-untyped-def]
    from safetensors.torch import load_file  # type: ignore[import-not-found]
    from transformers import MimiConfig, MimiModel  # type: ignore[import-not-found]

    configuration = json.loads(config.read_text(encoding="utf-8"))
    if configuration.get("sampling_rate") != SAMPLE_RATE:
        raise ValueError("unsupported Mimi checkpoint sampling rate")
    model = MimiModel(MimiConfig.from_dict(configuration))
    model.load_state_dict(load_file(weights, device="cpu"), strict=True)
    return model.eval()


def encode(weights: Path, config: Path, input_path: Path, output_path: Path) -> None:
    import torch  # type: ignore[import-not-found]

    sample_count, samples = _read_pcm(input_path)
    model = _load_model(weights, config)
    audio = torch.tensor(samples, dtype=torch.float32).reshape(1, 1, -1)
    with torch.inference_mode():
        codes = model.encode(audio, num_quantizers=CODEBOOK_COUNT).audio_codes
    codebooks = [codes[0, index].detach().cpu().tolist() for index in range(CODEBOOK_COUNT)]
    output_path.write_bytes(pack_tokens(codebooks, sample_count))


def decode(weights: Path, config: Path, input_path: Path, output_path: Path) -> None:
    import torch

    sample_count, codebooks = unpack_tokens(input_path.read_bytes())
    model = _load_model(weights, config)
    codes = torch.tensor(codebooks, dtype=torch.int64).unsqueeze(0)
    padding_mask = torch.ones((1, 1, sample_count), dtype=torch.bool)
    with torch.inference_mode():
        reconstructed = model.decode(codes, padding_mask=padding_mask).audio_values
    samples = reconstructed.detach().cpu().reshape(-1)
    if samples.numel() < sample_count:
        raise ValueError("Mimi decoder returned fewer samples than declared")
    _write_pcm(output_path, samples[:sample_count].tolist())


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SMCP pinned Mimi 24 kHz runtime")
    parser.add_argument("mode", choices=("encode", "decode"))
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.weights.is_file() or not args.config.is_file():
        raise ValueError("pinned Mimi artifacts are missing")
    os.umask(0o077)
    if args.mode == "encode":
        encode(args.weights, args.config, args.input, args.output)
    else:
        decode(args.weights, args.config, args.input, args.output)


if __name__ == "__main__":
    main()
