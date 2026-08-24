import hashlib
import zlib
from fractions import Fraction

import pytest

from smcp_worker.liveportrait_runtime import (
    DIGEST_BYTES,
    HEADER,
    MAGIC,
    MOTION_VALUES_PER_FRAME,
    pack_container,
    unpack_container,
    video_contract_supported,
)


def test_liveportrait_container_is_deterministic_and_round_trips() -> None:
    frame_count = 4
    motion = [
        ((index * 37) % 4_001) - 2_000
        for index in range((frame_count - 1) * MOTION_VALUES_PER_FRAME)
    ]
    arguments = {
        "frame_count": frame_count,
        "fps_numerator": 30_000,
        "fps_denominator": 1_001,
    }

    first = pack_container(b"synthetic-avif", motion, b"SMCPENCD-audio", **arguments)
    second = pack_container(b"synthetic-avif", motion, b"SMCPENCD-audio", **arguments)

    assert first == second
    assert unpack_container(first) == (
        30_000,
        1_001,
        frame_count,
        b"synthetic-avif",
        motion,
        b"SMCPENCD-audio",
    )


def test_liveportrait_container_supports_silent_video() -> None:
    motion = [0] * MOTION_VALUES_PER_FRAME
    payload = pack_container(
        b"keyframe",
        motion,
        b"",
        frame_count=2,
        fps_numerator=25,
        fps_denominator=1,
    )

    assert unpack_container(payload)[-1] == b""


@pytest.mark.parametrize(
    ("rate", "frame_count", "expected"),
    (
        (Fraction(1, 1), 30, True),
        (Fraction(1, 2), 30, False),
        (Fraction(30, 1), 30, True),
        (Fraction(31, 1), 30, False),
    ),
)
def test_liveportrait_video_contract_bounds_duration(
    rate: Fraction, frame_count: int, expected: bool
) -> None:
    assert video_contract_supported(512, 512, rate, frame_count) is expected


def test_liveportrait_container_rejects_corruption_and_trailing_data() -> None:
    payload = pack_container(
        b"keyframe",
        [0] * MOTION_VALUES_PER_FRAME,
        b"audio",
        frame_count=2,
        fps_numerator=24,
        fps_denominator=1,
    )
    corrupted = bytearray(payload)
    corrupted[-1] ^= 1

    with pytest.raises(ValueError, match="digest mismatch"):
        unpack_container(bytes(corrupted))
    with pytest.raises(ValueError, match="length mismatch"):
        unpack_container(payload + b"trailing")


def test_liveportrait_container_rejects_motion_decompression_bomb() -> None:
    keyframe = b"keyframe"
    compressed_motion = zlib.compress(b"\0" * 100_000, level=9)
    audio = b""
    header = HEADER.pack(
        MAGIC,
        1,
        512,
        512,
        25,
        1,
        2,
        0,
        len(keyframe),
        len(compressed_motion),
        0,
    )
    digests = b"".join(
        hashlib.sha256(section).digest() for section in (keyframe, compressed_motion, audio)
    )
    assert len(digests) == DIGEST_BYTES

    with pytest.raises(ValueError, match="non-bounded"):
        unpack_container(header + digests + keyframe + compressed_motion)


@pytest.mark.parametrize(
    ("motion", "frame_count", "fps_numerator", "expected"),
    (
        ([], 2, 25, "motion stream dimensions"),
        ([0] * MOTION_VALUES_PER_FRAME, 1, 25, "frame count"),
        ([0] * MOTION_VALUES_PER_FRAME, 2, 31, "frame rate"),
        ([32_768] * MOTION_VALUES_PER_FRAME, 2, 25, "signed 16-bit"),
    ),
)
def test_liveportrait_container_rejects_invalid_dimensions(
    motion: list[int], frame_count: int, fps_numerator: int, expected: str
) -> None:
    with pytest.raises(ValueError, match=expected):
        pack_container(
            b"keyframe",
            motion,
            b"",
            frame_count=frame_count,
            fps_numerator=fps_numerator,
            fps_denominator=1,
        )
