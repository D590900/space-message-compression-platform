import pytest

from smcp_worker.mimi_runtime import pack_tokens, unpack_tokens


def test_mimi_token_container_round_trip() -> None:
    codebooks = [[(index * 17 + codebook) % 2048 for index in range(4)] for codebook in range(8)]
    payload = pack_tokens(codebooks, 6_000)

    sample_count, decoded = unpack_tokens(payload)

    assert payload.startswith(b"SMCPMIMI")
    assert sample_count == 6_000
    assert decoded == codebooks


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload[:-1],
        lambda payload: payload + b"\x00",
        lambda payload: b"NOTMIMI!" + payload[8:],
    ],
)
def test_mimi_token_container_rejects_malformed_payload(mutator) -> None:  # type: ignore[no-untyped-def]
    payload = pack_tokens([[index] * 4 for index in range(8)], 6_000)

    with pytest.raises(ValueError):
        unpack_tokens(mutator(payload))
