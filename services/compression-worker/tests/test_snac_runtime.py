import pytest

from smcp_worker.snac_runtime import pack_tokens, unpack_tokens


def test_snac_token_container_round_trip() -> None:
    codebooks = [[0, 4095], [1, 2, 3, 4], list(range(8))]

    payload = pack_tokens(codebooks, sample_count=3_777)

    sample_count, decoded = unpack_tokens(payload)
    assert payload.startswith(b"SMCPSNAC")
    assert len(payload) == 34 + 21
    assert sample_count == 3_777
    assert decoded == codebooks


@pytest.mark.parametrize(
    "mutator",
    (
        lambda payload: payload[:-1],
        lambda payload: payload + b"\x00",
        lambda payload: b"NOTSNAC!" + payload[8:],
        lambda payload: payload[:-1] + bytes([payload[-1] | 1]),
    ),
)
def test_snac_token_container_rejects_malformed_payload(mutator) -> None:  # type: ignore[no-untyped-def]
    payload = pack_tokens([[0], [1, 2], [3, 4, 5, 6]], sample_count=512)

    with pytest.raises(ValueError):
        unpack_tokens(mutator(payload))
