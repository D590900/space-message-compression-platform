from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from smcp_worker.worker import CompressionWorker

CAPSULE_ID = "00000000-0000-0000-0000-000000000001"
JOB_ID = "00000000-0000-0000-0000-000000000002"
CANDIDATE_ID = "00000000-0000-0000-0000-000000000003"
ARTIFACT_ID = "00000000-0000-0000-0000-000000000004"


def test_varint_uses_canonical_unsigned_encoding() -> None:
    assert CompressionWorker._varint(0) == b"\x00"
    assert CompressionWorker._varint(127) == b"\x7f"
    assert CompressionWorker._varint(128) == b"\x80\x01"


def test_capsule_sections_are_binary_and_deterministic(tmp_path: Path) -> None:
    selection = {"utility": 99}
    artifact = {
        "artifact_id": ARTIFACT_ID,
        "candidate_id": CANDIDATE_ID,
        "job_id": JOB_ID,
        "input_type": "TEXT",
        "codec_id": "text.brotli",
        "codec_version": "1.1.0",
    }
    payload = b"compressed payload"
    first = CompressionWorker._write_capsule_sections(
        tmp_path / "first", CAPSULE_ID, 2_000_000, [(selection, artifact, payload)]
    )
    second = CompressionWorker._write_capsule_sections(
        tmp_path / "second", CAPSULE_ID, 2_000_000, [(selection, artifact, payload)]
    )

    assert [kind for kind, _ in first] == [
        "codec-registry",
        "text",
        "index",
        "manifest-digest",
    ]
    assert [path.read_bytes() for _, path in first] == [
        path.read_bytes() for _, path in second
    ]
    text = dict(first)["text"].read_bytes()
    assert text == bytes([len(payload)]) + payload
    index = dict(first)["index"].read_bytes()
    assert UUID(JOB_ID).bytes in index
    assert UUID(CANDIDATE_ID).bytes in index
    assert hashlib.sha256(payload).digest() in index
