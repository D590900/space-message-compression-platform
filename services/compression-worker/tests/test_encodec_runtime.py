import pytest

from smcp_worker.encodec_runtime import pack_tokens, unpack_tokens


def test_encodec_token_container_round_trip() -> None:
    chunks = [
        [[0, 1, 1023], [12, 34, 56]],
        [[78, 90, 101], [202, 303, 404]],
    ]
    payload = pack_tokens(
        chunks,
        [0.25, 0.5],
        sample_count=48_001,
        bandwidth=3.0,
        last_frame_pad_length=1,
    )

    sample_count, bandwidth, pad_length, scales, unpacked = unpack_tokens(payload)

    assert payload.startswith(b"SMCPENCD")
    assert sample_count == 48_001
    assert bandwidth == 3.0
    assert pad_length == 1
    assert scales == [0.25, 0.5]
    assert unpacked == chunks


@pytest.mark.parametrize(
    "mutator",
    (
        lambda payload: payload[:-1],
        lambda payload: b"NOTENCD!" + payload[8:],
        lambda payload: payload + b"\x00",
        lambda payload: payload[:-1] + bytes([payload[-1] | 1]),
    ),
)
def test_encodec_token_container_rejects_malformed_payload(mutator) -> None:  # type: ignore[no-untyped-def]
    payload = pack_tokens(
        [[[1, 2, 3], [4, 5, 6]]],
        [0.25],
        sample_count=4_800,
        bandwidth=3.0,
        last_frame_pad_length=0,
    )

    with pytest.raises(ValueError):
        unpack_tokens(mutator(payload))
