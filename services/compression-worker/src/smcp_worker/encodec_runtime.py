"""Pinned EnCodec inference entry point and deterministic token container."""

from __future__ import annotations

import argparse
import io
import json
import os
import struct
import wave
from collections.abc import Sequence
from pathlib import Path

MAGIC = b"SMCPENCD"
FORMAT_VERSION = 1
SAMPLE_RATE = 48_000
CHANNELS = 2
CODEBOOK_SIZE = 1_024
CODEBOOK_BITS = 10
TARGET_BANDWIDTHS = (3.0, 6.0, 12.0, 24.0)
CODEBOOKS_PER_BANDWIDTH = (2, 4, 8, 16)
CHUNK_STRIDE_SAMPLES = 47_520
MAX_SAMPLES = SAMPLE_RATE * 30
MAX_CHUNKS = 32
MAX_CODEBOOKS = 16
MAX_FRAMES = 150
HEADER = struct.Struct(">8sBBIIBBHHH")


def pack_tokens(
    chunks: Sequence[Sequence[Sequence[int]]],
    scales: Sequence[float],
    *,
    sample_count: int,
    bandwidth: float,
    last_frame_pad_length: int,
) -> bytes:
    """Serialize EnCodec chunks, normalization scales and 10-bit tokens."""
    if not 0 < sample_count <= MAX_SAMPLES:
        raise ValueError("sample count is outside the supported range")
    if bandwidth not in TARGET_BANDWIDTHS:
        raise ValueError("unsupported EnCodec bandwidth")
    chunk_count = len(chunks)
    if (
        not 0 < chunk_count <= MAX_CHUNKS
        or chunk_count != (sample_count + CHUNK_STRIDE_SAMPLES - 1) // CHUNK_STRIDE_SAMPLES
        or len(scales) != chunk_count
    ):
        raise ValueError("invalid EnCodec chunk dimensions")
    codebook_count = len(chunks[0])
    frame_count = len(chunks[0][0])
    if (
        codebook_count != CODEBOOKS_PER_BANDWIDTH[TARGET_BANDWIDTHS.index(bandwidth)]
        or not 0 < frame_count <= MAX_FRAMES
        or not 0 <= last_frame_pad_length < frame_count
    ):
        raise ValueError("invalid EnCodec token dimensions")
    if any(
        len(chunk) != codebook_count
        or any(len(codebook) != frame_count for codebook in chunk)
        for chunk in chunks
    ):
        raise ValueError("EnCodec chunks must have rectangular token dimensions")
    values = [value for chunk in chunks for codebook in chunk for value in codebook]
    if any(not 0 <= value < CODEBOOK_SIZE for value in values):
        raise ValueError("EnCodec token is outside the 10-bit codebook")
    if any(not 0.0 < scale < 1_000.0 for scale in scales):
        raise ValueError("invalid EnCodec normalization scale")

    bandwidth_id = TARGET_BANDWIDTHS.index(bandwidth)
    output = bytearray(
        HEADER.pack(
            MAGIC,
            FORMAT_VERSION,
            CHANNELS,
            SAMPLE_RATE,
            sample_count,
            bandwidth_id,
            codebook_count,
            chunk_count,
            frame_count,
            last_frame_pad_length,
        )
    )
    output.extend(struct.pack(f">{chunk_count}f", *scales))
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


def unpack_tokens(
    payload: bytes,
) -> tuple[int, float, int, list[float], list[list[list[int]]]]:
    """Parse a bounded EnCodec container and reject non-canonical encodings."""
    if len(payload) < HEADER.size:
        raise ValueError("truncated EnCodec container")
    (
        magic,
        version,
        channels,
        sample_rate,
        sample_count,
        bandwidth_id,
        codebook_count,
        chunk_count,
        frame_count,
        last_frame_pad_length,
    ) = HEADER.unpack_from(payload)
    if (
        magic != MAGIC
        or version != FORMAT_VERSION
        or channels != CHANNELS
        or sample_rate != SAMPLE_RATE
        or bandwidth_id >= len(TARGET_BANDWIDTHS)
    ):
        raise ValueError("unsupported EnCodec container")
    if (
        not 0 < sample_count <= MAX_SAMPLES
        or chunk_count != (sample_count + CHUNK_STRIDE_SAMPLES - 1) // CHUNK_STRIDE_SAMPLES
        or not 0 < chunk_count <= MAX_CHUNKS
        or codebook_count != CODEBOOKS_PER_BANDWIDTH[bandwidth_id]
        or not 0 < frame_count <= MAX_FRAMES
        or not 0 <= last_frame_pad_length < frame_count
    ):
        raise ValueError("invalid EnCodec container dimensions")
    scale_bytes = chunk_count * 4
    total = chunk_count * codebook_count * frame_count
    token_bytes = (total * CODEBOOK_BITS + 7) // 8
    if len(payload) != HEADER.size + scale_bytes + token_bytes:
        raise ValueError("EnCodec token payload length mismatch")
    scales = list(struct.unpack_from(f">{chunk_count}f", payload, HEADER.size))
    if any(not 0.0 < scale < 1_000.0 for scale in scales):
        raise ValueError("invalid EnCodec normalization scale")

    values: list[int] = []
    accumulator = 0
    bits = 0
    for octet in payload[HEADER.size + scale_bytes :]:
        accumulator = (accumulator << 8) | octet
        bits += 8
        while bits >= CODEBOOK_BITS and len(values) < total:
            bits -= CODEBOOK_BITS
            values.append((accumulator >> bits) & (CODEBOOK_SIZE - 1))
            accumulator &= (1 << bits) - 1
    if len(values) != total or accumulator:
        raise ValueError("non-canonical EnCodec token padding")
    chunks: list[list[list[int]]] = []
    offset = 0
    for _ in range(chunk_count):
        chunk: list[list[int]] = []
        for _ in range(codebook_count):
            chunk.append(values[offset : offset + frame_count])
            offset += frame_count
        chunks.append(chunk)
    return (
        sample_count,
        TARGET_BANDWIDTHS[bandwidth_id],
        last_frame_pad_length,
        scales,
        chunks,
    )


def _read_pcm(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as stream:
        if (
            stream.getnchannels() != CHANNELS
            or stream.getsampwidth() != 2
            or stream.getframerate() != SAMPLE_RATE
            or stream.getcomptype() != "NONE"
        ):
            raise ValueError("EnCodec input must be stereo 48 kHz signed 16-bit PCM WAV")
        sample_count = stream.getnframes()
        frames = stream.readframes(sample_count)
    value_count = sample_count * CHANNELS
    if not 0 < sample_count <= MAX_SAMPLES or len(frames) != value_count * 2:
        raise ValueError("invalid PCM sample count")
    samples = struct.unpack(f"<{value_count}h", frames)
    return sample_count, [sample / 32768.0 for sample in samples]


def _write_pcm(path: Path, channels: Sequence[Sequence[float]]) -> None:
    if len(channels) != CHANNELS or len(channels[0]) != len(channels[1]):
        raise ValueError("EnCodec decoder returned invalid channel dimensions")
    interleaved = [sample for frame in zip(*channels, strict=True) for sample in frame]
    pcm = [max(-32768, min(32767, round(sample * 32768.0))) for sample in interleaved]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(CHANNELS)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))
    path.write_bytes(buffer.getvalue())


def _load_model(weights: Path, config: Path):  # type: ignore[no-untyped-def]
    from safetensors.torch import load_file  # type: ignore[import-not-found]
    from transformers import EncodecConfig, EncodecModel  # type: ignore[import-not-found]

    configuration = json.loads(config.read_text(encoding="utf-8"))
    if (
        configuration.get("sampling_rate") != SAMPLE_RATE
        or configuration.get("audio_channels") != CHANNELS
        or tuple(configuration.get("target_bandwidths", ())) != TARGET_BANDWIDTHS
    ):
        raise ValueError("unsupported EnCodec checkpoint configuration")
    model = EncodecModel(EncodecConfig.from_dict(configuration))
    model.load_state_dict(load_file(weights, device="cpu"), strict=True)
    return model.eval()


def encode(
    weights: Path,
    config: Path,
    input_path: Path,
    output_path: Path,
    bandwidth: float,
) -> None:
    import torch  # type: ignore[import-not-found]

    sample_count, samples = _read_pcm(input_path)
    model = _load_model(weights, config)
    audio = torch.tensor(samples, dtype=torch.float32).reshape(1, sample_count, CHANNELS)
    audio = audio.transpose(1, 2).contiguous()
    with torch.inference_mode():
        encoded = model.encode(audio, bandwidth=bandwidth)
    codes = encoded.audio_codes.detach().cpu()
    chunks = [
        [codes[chunk, 0, codebook].tolist() for codebook in range(codes.shape[2])]
        for chunk in range(codes.shape[0])
    ]
    scales = [float(scale.detach().cpu().reshape(-1)[0]) for scale in encoded.audio_scales]
    output_path.write_bytes(
        pack_tokens(
            chunks,
            scales,
            sample_count=sample_count,
            bandwidth=bandwidth,
            last_frame_pad_length=encoded.last_frame_pad_length,
        )
    )


def decode(weights: Path, config: Path, input_path: Path, output_path: Path) -> None:
    import torch

    sample_count, _, last_frame_pad_length, scales, chunks = unpack_tokens(
        input_path.read_bytes()
    )
    model = _load_model(weights, config)
    codes = torch.tensor(chunks, dtype=torch.int64).unsqueeze(1)
    audio_scales = [torch.tensor([[scale]], dtype=torch.float32) for scale in scales]
    padding_mask = torch.ones((1, CHANNELS, sample_count), dtype=torch.bool)
    with torch.inference_mode():
        reconstructed = model.decode(
            codes,
            audio_scales,
            padding_mask=padding_mask,
            last_frame_pad_length=last_frame_pad_length,
        ).audio_values
    samples = reconstructed.detach().cpu()[0]
    if samples.shape[0] != CHANNELS or samples.shape[1] < sample_count:
        raise ValueError("EnCodec decoder returned fewer samples than declared")
    _write_pcm(output_path, [samples[index, :sample_count].tolist() for index in range(CHANNELS)])


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SMCP pinned EnCodec 48 kHz runtime")
    parser.add_argument("mode", choices=("encode", "decode"))
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bandwidth", type=float, choices=TARGET_BANDWIDTHS, default=3.0)
    args = parser.parse_args(argv)
    if not args.weights.is_file() or not args.config.is_file():
        raise ValueError("pinned EnCodec artifacts are missing")
    os.umask(0o077)
    if args.mode == "encode":
        encode(args.weights, args.config, args.input, args.output, args.bandwidth)
    else:
        decode(args.weights, args.config, args.input, args.output)


if __name__ == "__main__":
    main()
