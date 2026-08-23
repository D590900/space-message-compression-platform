from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from smcp_worker.settings import Settings
from smcp_worker.worker import (
    ACK_AND_DELETE_SCRIPT,
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
    assert all(call.kwargs == {"count": 7} for call in worker.redis.xautoclaim.call_args_list)


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

    assert worker.redis.eval.call_count == expected_ack_count
    if terminal:
        worker.redis.eval.assert_called_once_with(
            ACK_AND_DELETE_SCRIPT, 1, COMPRESSION_STREAM, "workers", "1-0"
        )
    worker._fail_job.assert_called_once_with(COMPRESSION_STREAM, job_id, "tenant", "WORKER_FAILURE")


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
    worker.redis.eval.assert_called_once_with(
        ACK_AND_DELETE_SCRIPT, 1, COMPRESSION_STREAM, "workers", "1-0"
    )


def test_acknowledgement_deletes_only_after_the_consumer_group_acknowledges() -> None:
    worker = bare_worker()

    worker._acknowledge(COMPRESSION_STREAM, "9-0")

    worker.redis.eval.assert_called_once_with(
        ACK_AND_DELETE_SCRIPT, 1, COMPRESSION_STREAM, "workers", "9-0"
    )
    assert "if acknowledged == 1" in ACK_AND_DELETE_SCRIPT
    assert "XDEL" in ACK_AND_DELETE_SCRIPT


def test_worker_failure_audit_contains_only_content_free_state() -> None:
    connection = MagicMock()

    CompressionWorker._audit_worker_failure(
        connection,
        "org_test",
        "00000000-0000-0000-0000-000000000001",
        "compression",
        "00000000-0000-0000-0000-000000000002",
        "MEDIA_PROBE_FAILED",
        "FAILED_TERMINAL",
        2,
    )

    parameters = connection.execute.call_args.args[1]
    assert parameters[:6] == (
        "org_test",
        "00000000-0000-0000-0000-000000000001",
        "compression.failed",
        "compression_job",
        "00000000-0000-0000-0000-000000000002",
        "worker:00000000-0000-0000-0000-000000000002",
    )
    assert parameters[6] == (
        '{"attempt": 2, "error_code": "MEDIA_PROBE_FAILED", "status": "FAILED_TERMINAL"}'
    )


def test_candidate_selection_enforces_target_bytes_with_a_stable_tie_break() -> None:
    candidates = [
        ("candidate-b", 90, "object-b"),
        ("candidate-a", 90, "object-a"),
        ("candidate-small", 80, "object-small"),
    ]

    assert CompressionWorker._select_candidate(candidates, 85) == (
        "candidate-small",
        80,
        "object-small",
    )
    assert CompressionWorker._select_candidate(candidates[0:2], 85) is None
    assert CompressionWorker._select_candidate(candidates[0:2], None) == (
        "candidate-a",
        90,
        "object-a",
    )


def test_retention_retry_backoff_is_bounded() -> None:
    assert CompressionWorker._retention_retry_seconds(1) == 30
    assert CompressionWorker._retention_retry_seconds(4) == 240
    assert CompressionWorker._retention_retry_seconds(100) == 3_600


def test_due_original_is_deleted_and_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = bare_worker()
    worker.settings.database_url = "postgresql://unused"
    worker.settings.deletion_batch_size = 20
    worker.settings.s3_bucket = "private"
    worker.s3 = MagicMock()
    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "tenant_subject": "org_test",
        "project_id": "00000000-0000-0000-0000-000000000002",
        "object_key": "private/source",
        "deletion_attempt": 0,
    }
    claim_cursor = MagicMock()
    claim_cursor.fetchall.return_value = [row]
    delete_cursor = MagicMock()
    delete_cursor.fetchone.return_value = {"id": row["id"]}
    connection = MagicMock()
    connection.execute.side_effect = [claim_cursor, delete_cursor, MagicMock()]
    manager = MagicMock()
    manager.__enter__.return_value = connection
    monkeypatch.setattr("smcp_worker.worker.psycopg.connect", lambda *args, **kwargs: manager)

    worker._delete_due_originals()

    worker.s3.delete_object.assert_called_once_with(Bucket="private", Key="private/source")
    audit_parameters = connection.execute.call_args_list[2].args[1]
    assert audit_parameters[0:3] == (
        "org_test",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    )
    assert audit_parameters[4] == '{"deletion_attempt": 1}'


def test_original_deletion_failure_is_redacted_and_rescheduled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = bare_worker()
    worker.settings.database_url = "postgresql://unused"
    worker.settings.deletion_batch_size = 20
    worker.settings.s3_bucket = "private"
    worker.s3 = MagicMock()
    worker.s3.delete_object.side_effect = TimeoutError("sensitive upstream detail")
    claim_cursor = MagicMock()
    claim_cursor.fetchall.return_value = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "tenant_subject": "org_test",
            "project_id": "00000000-0000-0000-0000-000000000002",
            "object_key": "private/source",
            "deletion_attempt": 1,
        }
    ]
    connection = MagicMock()
    connection.execute.side_effect = [claim_cursor, MagicMock()]
    manager = MagicMock()
    manager.__enter__.return_value = connection
    monkeypatch.setattr("smcp_worker.worker.psycopg.connect", lambda *args, **kwargs: manager)

    worker._delete_due_originals()

    retry_parameters = connection.execute.call_args_list[1].args[1]
    assert retry_parameters[0:3] == (2, "TimeoutError", 60)
    assert "sensitive upstream detail" not in repr(retry_parameters)
    connection.rollback.assert_called_once()
