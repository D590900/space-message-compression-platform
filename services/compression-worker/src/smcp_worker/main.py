import logging
from threading import Thread

import uvicorn

from smcp_worker.health import app
from smcp_worker.observability import READINESS, configure_tracing
from smcp_worker.settings import Settings
from smcp_worker.worker import CompressionWorker


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings()  # type: ignore[call-arg]
    shutdown_tracing = configure_tracing(settings)
    health_thread = Thread(
        target=uvicorn.run,
        kwargs={
            "app": app,
            "host": settings.worker_health_host,
            "port": settings.worker_health_port,
            "access_log": False,
            "log_level": "warning",
        },
        name="smcp-worker-health",
        daemon=True,
    )
    health_thread.start()
    try:
        CompressionWorker(settings).run_forever(on_ready=READINESS.set)
    finally:
        READINESS.clear()
        shutdown_tracing()


if __name__ == "__main__":
    run()
