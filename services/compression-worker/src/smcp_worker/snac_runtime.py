"""Pinned SNAC inference entry point and deterministic token container."""

from __future__ import annotations

import argparse
import io
import os
import struct
import wave
from collections.abc import Sequence
from pathlib import Path

MAGIC = b"SMCPSNAC"
FORMAT_VERSION = 1
SAMPLE_RATE = 24_000
CODEBOOK_SIZE = 4_096
CODEBOOK_BITS = 12
CODEBOOK_COUNT = 3
MAX_SAMPLES = SAMPLE_RATE * 60
PADDING_SAMPLES = 2_048
HEADER = struct.Struct(">8sBIQB")
COUNT = struct.Struct(">I")


def pack_tokens(codebooks: Sequence[Sequence[int]], sample_count: int) -> bytes:
    """Serialize the three hierarchical 12-bit codebooks without pickle."""
    if not 0 < sample_count <= MAX_SAMPLES:
        raise ValueError("sample count is outside the supported range")
    if len(codebooks) != CODEBOOK_COUNT:
        raise ValueError("SNAC 24 kHz requires exactly three codebooks")
    counts = [len(codebook) for codebook in codebooks]
    coarse_count = (sample_count + PADDING_SAMPLES - 1) // PADDING_SAMPLES
    if counts != [coarse_count, coarse_count * 2, coarse_count * 4]:
        raise ValueError("invalid SNAC hierarchy lengths")
    values = [value for codebook in codebooks for value in codebook]
    if any(not 0 <= value < CODEBOOK_SIZE for value in values):
        raise ValueError("SNAC token is outside the 12-bit codebook")

    output = bytearray(HEADER.pack(MAGIC, FORMAT_VERSION, SAMPLE_RATE, sample_count, len(counts)))
    for count in counts:
        output.extend(COUNT.pack(count))
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
    """Parse a bounded SNAC token container and reject non-canonical encodings."""
    minimum = HEADER.size + CODEBOOK_COUNT * COUNT.size
    if len(payload) < minimum:
        raise ValueError("truncated SNAC container")
    magic, version, sample_rate, sample_count, codebook_count = HEADER.unpack_from(payload)
    if magic != MAGIC or version != FORMAT_VERSION or sample_rate != SAMPLE_RATE:
        raise ValueError("unsupported SNAC container")
    if not 0 < sample_count <= MAX_SAMPLES or codebook_count != CODEBOOK_COUNT:
        raise ValueError("invalid SNAC container dimensions")
    offset = HEADER.size
    counts: list[int] = []
    for _ in range(codebook_count):
        (count,) = COUNT.unpack_from(payload, offset)
        counts.append(count)
        offset += COUNT.size
    coarse_count = (sample_count + PADDING_SAMPLES - 1) // PADDING_SAMPLES
    if counts != [coarse_count, coarse_count * 2, coarse_count * 4]:
        raise ValueError("invalid SNAC hierarchy lengths")
    total = sum(counts)
    expected_bytes = (total * CODEBOOK_BITS + 7) // 8
    if len(payload) != offset + expected_bytes:
        raise ValueError("SNAC token payload length mismatch")

    values: list[int] = []
    accumulator = 0
    bits = 0
    for octet in payload[offset:]:
        accumulator = (accumulator << 8) | octet
        bits += 8
        while bits >= CODEBOOK_BITS and len(values) < total:
            bits -= CODEBOOK_BITS
            values.append((accumulator >> bits) & (CODEBOOK_SIZE - 1))
            accumulator &= (1 << bits) - 1
    if len(values) != total or accumulator:
        raise ValueError("non-canonical SNAC token padding")
    codebooks: list[list[int]] = []
    cursor = 0
    for count in counts:
        codebooks.append(values[cursor : cursor + count])
        cursor += count
    return sample_count, codebooks


def _read_pcm(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as stream:
        if (
            stream.getnchannels() != 1
            or stream.getsampwidth() != 2
            or stream.getframerate() != SAMPLE_RATE
            or stream.getcomptype() != "NONE"
        ):
            raise ValueError("SNAC input must be mono 24 kHz signed 16-bit PCM WAV")
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
    import torch  # type: ignore[import-not-found]
    from snac import SNAC  # type: ignore[import-not-found]

    model = SNAC.from_config(config)
    state_dict = torch.load(weights, map_location="cpu", weights_only=True)
    model.load_state_dict(state_dict)
    return model.eval()


def encode(weights: Path, config: Path, input_path: Path, output_path: Path) -> None:
    import torch

    sample_count, samples = _read_pcm(input_path)
    model = _load_model(weights, config)
    audio = torch.tensor(samples, dtype=torch.float32).reshape(1, 1, -1)
    with torch.inference_mode():
        tensors = model.encode(audio)
    codebooks = [tensor.detach().cpu().reshape(-1).tolist() for tensor in tensors]
    output_path.write_bytes(pack_tokens(codebooks, sample_count))


def decode(weights: Path, config: Path, input_path: Path, output_path: Path) -> None:
    import torch

    sample_count, codebooks = unpack_tokens(input_path.read_bytes())
    model = _load_model(weights, config)
    tensors = [torch.tensor(values, dtype=torch.int64).reshape(1, -1) for values in codebooks]
    with torch.inference_mode():
        reconstructed = model.decode(tensors).detach().cpu().reshape(-1)
    if reconstructed.numel() < sample_count:
        raise ValueError("SNAC decoder returned fewer samples than declared")
    _write_pcm(output_path, reconstructed[:sample_count].tolist())


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SMCP pinned SNAC 24 kHz runtime")
    parser.add_argument("mode", choices=("encode", "decode"))
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.weights.is_file() or not args.config.is_file():
        raise ValueError("pinned SNAC artifacts are missing")
    os.umask(0o077)
    if args.mode == "encode":
        encode(args.weights, args.config, args.input, args.output)
    else:
        decode(args.weights, args.config, args.input, args.output)


if __name__ == "__main__":
    main()
