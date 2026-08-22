from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from smcp_worker.settings import Settings
from smcp_worker.worker import (
    CAPSULE_STREAM,
    COMPRESSION_STREAM,
    DECOMPRESSION_STREAM,
    CompressionWorker,
)


def bare_worker() -> CompressionWorker:
    worker = object.__new__(CompressionWorker)
    worker.settings = SimpleNamespace(  # type: ignore[assignment]
        worker_group="workers",
        worker_consumer_name="worker-2",
        worker_claim_idle_ms=30_000,
        worker_claim_batch=7,
    )
    worker.redis = MagicMock()
    return worker


def test_empty_optional_otlp_endpoint_disables_export() -> None:
    settings = Settings(
        database_url="postgresql://unused",
        valkey_url="redis://unused",
        s3_endpoint="http://unused",
        s3_access_key_id="unused",
        s3_secret_access_key="test-placeholder",  # noqa: S106
        otel_exporter_otlp_traces_endpoint="",
    )

    assert settings.otel_exporter_otlp_traces_endpoint is None


def test_claims_stale_pending_messages_from_every_stream() -> None:
    worker = bare_worker()
    worker.redis.xautoclaim.side_effect = [
        ["0-0", [("1-0", {"job_id": "job"})], []],
        ["0-0", [], []],
        ["0-0", [("3-0", {"capsule_id": "capsule"})], []],
    ]

    claimed = worker._claim_stale_messages()

    assert claimed == [
        (COMPRESSION_STREAM, [("1-0", {"job_id": "job"})]),
        (CAPSULE_STREAM, [("3-0", {"capsule_id": "capsule"})]),
    ]
    assert [call.args[0] for call in worker.redis.xautoclaim.call_args_list] == [
        COMPRESSION_STREAM,
        DECOMPRESSION_STREAM,
        CAPSULE_STREAM,
    ]
    assert all(
        call.kwargs == {"count": 7} for call in worker.redis.xautoclaim.call_args_list
    )


@pytest.mark.parametrize("terminal,expected_ack_count", [(False, 0), (True, 1)])
def test_retryable_message_stays_pending_until_attempts_are_exhausted(
    terminal: bool, expected_ack_count: int
) -> None:
    worker = bare_worker()
    job_id = "00000000-0000-0000-0000-000000000001"
    worker.process_job = MagicMock(side_effect=RuntimeError("transient"))  # type: ignore[method-assign]
    worker._fail_job = MagicMock(return_value=terminal)  # type: ignore[method-assign]

    worker.process_message(
        COMPRESSION_STREAM,
        "1-0",
        {"job_id": job_id, "tenant_subject": "tenant"},
    )

    assert worker.redis.xack.call_count == expected_ack_count
    worker._fail_job.assert_called_once_with(
        COMPRESSION_STREAM, job_id, "tenant", "WORKER_FAILURE"
    )


def test_candidate_cleanup_uses_bounded_s3_batches() -> None:
    worker = bare_worker()
    worker.settings.s3_bucket = "private"
    worker.s3 = MagicMock()

    worker._delete_objects([f"object-{index}" for index in range(1_001)])

    assert worker.s3.delete_objects.call_count == 2
    assert len(worker.s3.delete_objects.call_args_list[0].kwargs["Delete"]["Objects"]) == 1_000
    assert len(worker.s3.delete_objects.call_args_list[1].kwargs["Delete"]["Objects"]) == 1


def test_invalid_internal_job_id_is_acknowledged_without_database_work() -> None:
    worker = bare_worker()
    worker.process_job = MagicMock()  # type: ignore[method-assign]

    worker.process_message(
        COMPRESSION_STREAM,
        "1-0",
        {"job_id": "not-a-uuid", "tenant_subject": "tenant"},
    )

    worker.process_job.assert_not_called()
    worker.redis.xack.assert_called_once_with(COMPRESSION_STREAM, "workers", "1-0")
