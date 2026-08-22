from fastapi import Response

from smcp_worker.health import metrics, ready
from smcp_worker.observability import READINESS


def test_readiness_reflects_worker_state() -> None:
    READINESS.clear()
    unavailable = Response()
    assert ready(unavailable) == {"status": "not_ready"}
    assert unavailable.status_code == 503

    READINESS.set()
    available = Response()
    assert ready(available) == {"status": "ready"}
    assert available.status_code == 200
    READINESS.clear()


def test_metrics_are_prometheus_text_without_payload_labels() -> None:
    response = metrics()
    body = bytes(response.body).decode()
    assert response.media_type.startswith("text/plain; version=")
    assert 'gpu_utilization{device="cpu"} 0.0' in body
    assert "tenant_subject" not in body
