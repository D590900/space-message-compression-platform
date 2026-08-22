from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from smcp_worker.observability import READINESS

app = FastAPI(title="SMCP compression worker health", docs_url=None, redoc_url=None)


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def ready(response: Response) -> dict[str, str]:
    if not READINESS.is_set():
        response.status_code = 503
        return {"status": "not_ready"}
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    # The worker endpoint is internal-only in Compose. A deployment that exposes
    # it must enforce network policy or an authenticated collector proxy.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
