import logging

from smcp_worker.settings import Settings
from smcp_worker.worker import CompressionWorker


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    worker = CompressionWorker(Settings())  # type: ignore[call-arg]
    worker.run_forever()


if __name__ == "__main__":
    run()
