"""Detector-free LivePortrait keyframe, motion and neural-audio runtime."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import struct
import subprocess
import tempfile
import zlib
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

MAGIC = b"SMCPLPRT"
FORMAT_VERSION = 1
WIDTH = 512
HEIGHT = 512
MODEL_INPUT_SIZE = 256
CHANNELS = 3
KEYPOINTS = 21
KEYPOINT_DIMENSIONS = 3
MOTION_VALUES_PER_FRAME = KEYPOINTS * KEYPOINT_DIMENSIONS
MOTION_QUANTIZATION = 16_384
MIN_FRAMES = 2
MAX_FRAMES = 30
MAX_FPS = 30
MAX_KEYFRAME_BYTES = 8 * 1024 * 1024
MAX_MOTION_BYTES = MAX_FRAMES * MOTION_VALUES_PER_FRAME * 2 + 1_024
MAX_AUDIO_BYTES = 2 * 1024 * 1024
FLAG_AUDIO = 1
HEADER = struct.Struct(">8sBHHIIHHIII")
DIGEST_BYTES = 32 * 3
EXPECTED_CONFIG = {
    "appearance_feature_extractor_params": {
        "image_channel": 3,
        "block_expansion": 64,
        "num_down_blocks": 2,
        "max_features": 512,
        "reshape_channel": 32,
        "reshape_depth": 16,
        "num_resblocks": 6,
    },
    "motion_extractor_params": {"num_kp": 21, "backbone": "convnextv2_tiny"},
    "warping_module_params": {
        "num_kp": 21,
        "block_expansion": 64,
        "max_features": 512,
        "num_down_blocks": 2,
        "reshape_channel": 32,
        "estimate_occlusion_map": True,
        "dense_motion_params": {
            "block_expansion": 32,
            "max_features": 1024,
            "num_blocks": 5,
            "reshape_depth": 16,
            "compress": 4,
        },
    },
    "spade_generator_params": {
        "upscale": 2,
        "block_expansion": 64,
        "max_features": 512,
        "num_down_blocks": 2,
    },
}
WEIGHT_FILES = {
    "appearance": "appearance_feature_extractor.pth",
    "motion": "motion_extractor.pth",
    "generator": "spade_generator.pth",
    "warping": "warping_module.pth",
}


def pack_container(
    keyframe: bytes,
    motion_values: Sequence[int],
    audio: bytes,
    *,
    frame_count: int,
    fps_numerator: int,
    fps_denominator: int,
) -> bytes:
    """Serialize bounded keyframe, motion and optional EnCodec sections."""
    if not MIN_FRAMES <= frame_count <= MAX_FRAMES:
        raise ValueError("frame count is outside the LivePortrait contract")
    fps = Fraction(fps_numerator, fps_denominator)
    if fps <= 0 or fps > MAX_FPS:
        raise ValueError("frame rate is outside the LivePortrait contract")
    expected_motion_values = (frame_count - 1) * MOTION_VALUES_PER_FRAME
    if len(motion_values) != expected_motion_values:
        raise ValueError("motion stream dimensions do not match frame count")
    if any(not -32_768 <= value <= 32_767 for value in motion_values):
        raise ValueError("motion value is outside signed 16-bit range")
    if not keyframe or len(keyframe) > MAX_KEYFRAME_BYTES:
        raise ValueError("keyframe section is outside the supported range")
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("audio section is outside the supported range")
    raw_motion = struct.pack(f">{len(motion_values)}h", *motion_values)
    compressed_motion = zlib.compress(raw_motion, level=9)
    if len(compressed_motion) > MAX_MOTION_BYTES:
        raise ValueError("compressed motion section is outside the supported range")
    flags = FLAG_AUDIO if audio else 0
    header = HEADER.pack(
        MAGIC,
        FORMAT_VERSION,
        WIDTH,
        HEIGHT,
        fps.numerator,
        fps.denominator,
        frame_count,
        flags,
        len(keyframe),
        len(compressed_motion),
        len(audio),
    )
    digests = b"".join(
        hashlib.sha256(section).digest() for section in (keyframe, compressed_motion, audio)
    )
    return header + digests + keyframe + compressed_motion + audio


def unpack_container(
    payload: bytes,
) -> tuple[int, int, int, bytes, list[int], bytes]:
    """Parse and authenticate a bounded LivePortrait container."""
    if len(payload) < HEADER.size + DIGEST_BYTES:
        raise ValueError("truncated LivePortrait container")
    (
        magic,
        version,
        width,
        height,
        fps_numerator,
        fps_denominator,
        frame_count,
        flags,
        keyframe_length,
        motion_length,
        audio_length,
    ) = HEADER.unpack_from(payload)
    if (
        magic != MAGIC
        or version != FORMAT_VERSION
        or width != WIDTH
        or height != HEIGHT
        or flags & ~FLAG_AUDIO
    ):
        raise ValueError("unsupported LivePortrait container")
    if not MIN_FRAMES <= frame_count <= MAX_FRAMES:
        raise ValueError("invalid LivePortrait frame count")
    fps = Fraction(fps_numerator, fps_denominator)
    if fps <= 0 or fps > MAX_FPS:
        raise ValueError("invalid LivePortrait frame rate")
    if (
        not 0 < keyframe_length <= MAX_KEYFRAME_BYTES
        or not 0 < motion_length <= MAX_MOTION_BYTES
        or not 0 <= audio_length <= MAX_AUDIO_BYTES
        or bool(flags & FLAG_AUDIO) != bool(audio_length)
    ):
        raise ValueError("invalid LivePortrait section dimensions")
    expected_length = HEADER.size + DIGEST_BYTES + keyframe_length + motion_length + audio_length
    if len(payload) != expected_length:
        raise ValueError("LivePortrait payload length mismatch")
    digest_offset = HEADER.size
    expected_digests = (
        payload[digest_offset : digest_offset + 32],
        payload[digest_offset + 32 : digest_offset + 64],
        payload[digest_offset + 64 : digest_offset + 96],
    )
    section_offset = HEADER.size + DIGEST_BYTES
    keyframe = payload[section_offset : section_offset + keyframe_length]
    section_offset += keyframe_length
    compressed_motion = payload[section_offset : section_offset + motion_length]
    section_offset += motion_length
    audio = payload[section_offset:]
    for expected, section in zip(
        expected_digests, (keyframe, compressed_motion, audio), strict=True
    ):
        if not hmac.compare_digest(expected, hashlib.sha256(section).digest()):
            raise ValueError("LivePortrait section digest mismatch")
    expected_raw_length = (frame_count - 1) * MOTION_VALUES_PER_FRAME * 2
    decompressor = zlib.decompressobj()
    raw_motion = decompressor.decompress(compressed_motion, expected_raw_length + 1)
    if (
        len(raw_motion) != expected_raw_length
        or not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
    ):
        raise ValueError("invalid or non-bounded LivePortrait motion stream")
    value_count = expected_raw_length // 2
    motion_values = list(struct.unpack(f">{value_count}h", raw_motion))
    return fps.numerator, fps.denominator, frame_count, keyframe, motion_values, audio


def _run(
    command: Sequence[str], *, input_bytes: bytes | None = None, timeout: int = 600
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - argv-only trusted media commands
        command,
        input=input_bytes,
        capture_output=True,
        check=True,
        timeout=timeout,
    )


def _probe(path: Path) -> tuple[int, int, int, bool]:
    completed = _run(
        (
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,width,height,avg_frame_rate,nb_read_frames",
            "-of",
            "json",
            str(path),
        ),
        timeout=60,
    )
    report = json.loads(completed.stdout)
    streams = report.get("streams")
    if not isinstance(streams, list):
        raise ValueError("FFprobe did not return video streams")
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        raise ValueError("input has no video stream")
    if video.get("width") != WIDTH or video.get("height") != HEIGHT:
        raise ValueError("LivePortrait input must be pre-aligned 512x512 video")
    rate = Fraction(str(video.get("avg_frame_rate", "0/1")))
    frame_count = int(video.get("nb_read_frames", 0))
    if rate <= 0 or rate > MAX_FPS or not MIN_FRAMES <= frame_count <= MAX_FRAMES:
        raise ValueError("video frame count or frame rate is outside the contract")
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    return rate.numerator, rate.denominator, frame_count, has_audio


def _extract_frames(path: Path, frame_count: int) -> list[bytes]:
    completed = _run(
        (
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-frames:v",
            str(frame_count),
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        )
    )
    frame_bytes = WIDTH * HEIGHT * CHANNELS
    expected = frame_count * frame_bytes
    if len(completed.stdout) != expected:
        raise ValueError("FFmpeg returned unexpected decoded frame dimensions")
    return [
        completed.stdout[offset : offset + frame_bytes]
        for offset in range(0, expected, frame_bytes)
    ]


def _frame_tensor(frame: bytes):  # type: ignore[no-untyped-def]
    import torch  # type: ignore[import-not-found]
    import torch.nn.functional as functional  # type: ignore[import-not-found]

    expected = WIDTH * HEIGHT * CHANNELS
    if len(frame) != expected:
        raise ValueError("invalid RGB frame length")
    tensor = torch.frombuffer(bytearray(frame), dtype=torch.uint8)
    tensor = tensor.reshape(HEIGHT, WIDTH, CHANNELS).permute(2, 0, 1).unsqueeze(0)
    tensor = functional.interpolate(
        tensor.float(),
        size=(MODEL_INPUT_SIZE, MODEL_INPUT_SIZE),
        mode="bilinear",
        align_corners=False,
        antialias=True,
    )
    return tensor.div_(255.0)


def _load_config(config_path: Path) -> dict[str, dict[str, Any]]:
    import yaml  # type: ignore[import-untyped]

    document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("model_params") is None:
        raise ValueError("invalid LivePortrait model configuration")
    params = document["model_params"]
    if not isinstance(params, dict):
        raise ValueError("invalid LivePortrait model parameters")
    for name, expected in EXPECTED_CONFIG.items():
        if params.get(name) != expected:
            raise ValueError(f"unsupported LivePortrait configuration for {name}")
    return params


def _load_state(model: Any, path: Path) -> Any:
    import torch

    state = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(state, dict) or not state:
        raise ValueError("LivePortrait checkpoint is not a state dictionary")
    model.load_state_dict(state, strict=True)
    return model.eval()


def _load_motion_model(source_root: Path, weights_root: Path, config_path: Path):  # type: ignore[no-untyped-def]
    import sys

    source = str(source_root)
    if source not in sys.path:
        sys.path.insert(0, source)
    from src.modules.motion_extractor import MotionExtractor  # type: ignore[import-not-found]

    params = _load_config(config_path)
    return _load_state(
        MotionExtractor(**params["motion_extractor_params"]),
        weights_root / WEIGHT_FILES["motion"],
    )


def _load_decoder_models(
    source_root: Path, weights_root: Path, config_path: Path
) -> tuple[Any, Any, Any, Any]:
    import sys

    source = str(source_root)
    if source not in sys.path:
        sys.path.insert(0, source)
    from src.modules.appearance_feature_extractor import (  # type: ignore[import-not-found]
        AppearanceFeatureExtractor,
    )
    from src.modules.motion_extractor import MotionExtractor
    from src.modules.spade_generator import SPADEDecoder  # type: ignore[import-not-found]
    from src.modules.warping_network import WarpingNetwork  # type: ignore[import-not-found]

    params = _load_config(config_path)
    return (
        _load_state(
            AppearanceFeatureExtractor(**params["appearance_feature_extractor_params"]),
            weights_root / WEIGHT_FILES["appearance"],
        ),
        _load_state(
            MotionExtractor(**params["motion_extractor_params"]),
            weights_root / WEIGHT_FILES["motion"],
        ),
        _load_state(
            WarpingNetwork(**params["warping_module_params"]),
            weights_root / WEIGHT_FILES["warping"],
        ),
        _load_state(
            SPADEDecoder(**params["spade_generator_params"]),
            weights_root / WEIGHT_FILES["generator"],
        ),
    )


def _transformed_keypoints(info: dict[str, Any], source_root: Path):  # type: ignore[no-untyped-def]
    import sys

    source = str(source_root)
    if source not in sys.path:
        sys.path.insert(0, source)
    from src.utils.camera import (  # type: ignore[import-not-found]
        get_rotation_matrix,
        headpose_pred_to_degree,
    )

    keypoints = info["kp"].reshape(1, KEYPOINTS, KEYPOINT_DIMENSIONS)
    expression = info["exp"].reshape(1, KEYPOINTS, KEYPOINT_DIMENSIONS)
    rotation = get_rotation_matrix(
        headpose_pred_to_degree(info["pitch"]),
        headpose_pred_to_degree(info["yaw"]),
        headpose_pred_to_degree(info["roll"]),
    )
    transformed = info["scale"][..., None] * (keypoints @ rotation + expression)
    transformed[:, :, :2] += info["t"][:, None, :2]
    return transformed


def _encode_keyframe(frame: bytes, root: Path, quantizer: int) -> bytes:
    png = root / "keyframe.png"
    avif = root / "keyframe.avif"
    _run(
        (
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-i",
            "pipe:0",
            "-frames:v",
            "1",
            "-compression_level",
            "9",
            "-y",
            str(png),
        ),
        input_bytes=frame,
        timeout=60,
    )
    _run(
        (
            "avifenc",
            "--jobs",
            "1",
            "--speed",
            "6",
            "--min",
            str(quantizer),
            "--max",
            str(quantizer),
            str(png),
            str(avif),
        ),
        timeout=120,
    )
    return avif.read_bytes()


def _decode_keyframe(keyframe: bytes, root: Path) -> bytes:
    avif = root / "keyframe.avif"
    png = root / "keyframe.png"
    avif.write_bytes(keyframe)
    _run(("avifdec", "--jobs", "1", str(avif), str(png)), timeout=60)
    decoded = _run(
        (
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(png),
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ),
        timeout=60,
    ).stdout
    if len(decoded) != WIDTH * HEIGHT * CHANNELS:
        raise ValueError("decoded keyframe has unexpected dimensions")
    return decoded


def _encode_audio(
    input_path: Path,
    root: Path,
    encodec_weights: Path,
    encodec_config: Path,
) -> bytes:
    from smcp_worker.encodec_runtime import encode as encode_audio

    wav = root / "audio.wav"
    encoded = root / "audio.encd"
    _run(
        (
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(input_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(wav),
        ),
        timeout=120,
    )
    encode_audio(encodec_weights, encodec_config, wav, encoded, 3.0)
    return encoded.read_bytes()


def encode(
    source_root: Path,
    weights_root: Path,
    config_path: Path,
    encodec_weights: Path,
    encodec_config: Path,
    input_path: Path,
    output_path: Path,
    quantizer: int,
) -> None:
    import torch

    fps_numerator, fps_denominator, frame_count, has_audio = _probe(input_path)
    frames = _extract_frames(input_path, frame_count)
    model = _load_motion_model(source_root, weights_root, config_path)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    quantized: list[int] = []
    with torch.inference_mode():
        source_keypoints = _transformed_keypoints(model(_frame_tensor(frames[0])), source_root)
        for frame in frames[1:]:
            keypoints = _transformed_keypoints(model(_frame_tensor(frame)), source_root)
            delta = (keypoints - source_keypoints).detach().cpu().reshape(-1)
            values = torch.round(delta * MOTION_QUANTIZATION).to(torch.int64).tolist()
            if any(not -32_768 <= value <= 32_767 for value in values):
                raise ValueError("LivePortrait motion exceeds the quantized range")
            quantized.extend(values)
    with tempfile.TemporaryDirectory(prefix="smcp-liveportrait-encode-") as directory:
        root = Path(directory)
        keyframe = _encode_keyframe(frames[0], root, quantizer)
        audio = (
            _encode_audio(input_path, root, encodec_weights, encodec_config) if has_audio else b""
        )
    output_path.write_bytes(
        pack_container(
            keyframe,
            quantized,
            audio,
            frame_count=frame_count,
            fps_numerator=fps_numerator,
            fps_denominator=fps_denominator,
        )
    )


def _tensor_to_rgb(tensor: Any) -> bytes:
    import torch
    import torch.nn.functional as functional

    resized = functional.interpolate(
        tensor,
        size=(HEIGHT, WIDTH),
        mode="bilinear",
        align_corners=False,
        antialias=True,
    )
    pixels = resized.detach().cpu().clamp(0, 1).mul(255).round().to(torch.uint8)
    return bytes(pixels[0].permute(1, 2, 0).contiguous().numpy().tobytes())


def _write_video(
    frames: Sequence[bytes],
    fps_numerator: int,
    fps_denominator: int,
    audio_path: Path | None,
    output_path: Path,
) -> None:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-framerate",
        f"{fps_numerator}/{fps_denominator}",
        "-i",
        "pipe:0",
    ]
    if audio_path is not None:
        command.extend(("-i", str(audio_path)))
    command.extend(
        (
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?" if audio_path is not None else "0:a:0?",
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
            "-bitexact",
        )
    )
    if audio_path is not None:
        command.append("-shortest")
    command.extend(("-y", str(output_path)))
    _run(command, input_bytes=b"".join(frames), timeout=600)


def decode(
    source_root: Path,
    weights_root: Path,
    config_path: Path,
    encodec_weights: Path,
    encodec_config: Path,
    input_path: Path,
    output_path: Path,
) -> None:
    import torch

    (
        fps_numerator,
        fps_denominator,
        frame_count,
        keyframe,
        motion_values,
        audio,
    ) = unpack_container(input_path.read_bytes())
    appearance, motion, warping, generator = _load_decoder_models(
        source_root, weights_root, config_path
    )
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    with tempfile.TemporaryDirectory(prefix="smcp-liveportrait-decode-") as directory:
        root = Path(directory)
        first_frame = _decode_keyframe(keyframe, root)
        source = _frame_tensor(first_frame)
        decoded_frames = [first_frame]
        with torch.inference_mode():
            feature = appearance(source)
            source_keypoints = _transformed_keypoints(motion(source), source_root)
            for index in range(frame_count - 1):
                offset = index * MOTION_VALUES_PER_FRAME
                values = motion_values[offset : offset + MOTION_VALUES_PER_FRAME]
                delta = torch.tensor(values, dtype=torch.float32).reshape(
                    1, KEYPOINTS, KEYPOINT_DIMENSIONS
                )
                driving_keypoints = source_keypoints + delta / MOTION_QUANTIZATION
                warped = warping(
                    feature,
                    kp_source=source_keypoints,
                    kp_driving=driving_keypoints,
                )["out"]
                decoded_frames.append(_tensor_to_rgb(generator(feature=warped)))
        audio_path: Path | None = None
        if audio:
            from smcp_worker.encodec_runtime import decode as decode_audio

            encoded_audio = root / "audio.encd"
            audio_path = root / "audio.wav"
            encoded_audio.write_bytes(audio)
            decode_audio(
                encodec_weights,
                encodec_config,
                encoded_audio,
                audio_path,
            )
        _write_video(
            decoded_frames,
            fps_numerator,
            fps_denominator,
            audio_path,
            output_path,
        )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SMCP pinned detector-free LivePortrait runtime")
    parser.add_argument("mode", choices=("encode", "decode"))
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--weights-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--encodec-weights", type=Path, required=True)
    parser.add_argument("--encodec-config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quantizer", type=int, choices=range(20, 52), default=35)
    args = parser.parse_args(argv)
    required = [
        args.source_root / "src" / "modules" / "motion_extractor.py",
        args.config,
        args.encodec_weights,
        args.encodec_config,
        *(args.weights_root / name for name in WEIGHT_FILES.values()),
    ]
    if any(not path.is_file() for path in required):
        raise ValueError("pinned LivePortrait or EnCodec artifacts are missing")
    os.umask(0o077)
    if args.mode == "encode":
        encode(
            args.source_root,
            args.weights_root,
            args.config,
            args.encodec_weights,
            args.encodec_config,
            args.input,
            args.output,
            args.quantizer,
        )
    else:
        decode(
            args.source_root,
            args.weights_root,
            args.config,
            args.encodec_weights,
            args.encodec_config,
            args.input,
            args.output,
        )


if __name__ == "__main__":
    main()
