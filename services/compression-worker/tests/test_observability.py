from smcp_worker.worker import CompressionWorker


def test_queue_backlog_combines_unclaimed_lag_and_pending_work() -> None:
    groups = [
        {"name": "other", "pending": 100, "lag": 100},
        {"name": "compression-workers", "pending": 2, "lag": 3},
    ]
    assert CompressionWorker._group_backlog(groups, "compression-workers") == 5
    assert CompressionWorker._group_backlog(groups, "missing") == 0
