from types import SimpleNamespace

import smcp_worker.worker as worker_module
from smcp_worker.worker import CompressionWorker


def worker_with_limits() -> CompressionWorker:
    worker = object.__new__(CompressionWorker)
    worker.settings = SimpleNamespace(  # type: ignore[assignment]
        max_image_pixels=9_999,
        max_audio_seconds=60,
        max_video_seconds=10,
        max_video_pixels=2_100_000,
        max_video_frames=300,
    )
    return worker


def probe(monkeypatch, report: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        worker_module,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=report),
    )


def test_rejects_image_over_decoded_pixel_limit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    probe(monkeypatch, '{"streams":[{"width":100,"height":100}]}')
    assert worker_with_limits()._media_limit_error("IMAGE", b"image") == (
        "PIXEL_LIMIT_EXCEEDED"
    )


def test_rejects_audio_over_duration_limit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    probe(
        monkeypatch,
        '{"streams":[{"codec_type":"audio"}],"format":{"duration":"60.001"}}',
    )
    assert worker_with_limits()._media_limit_error("AUDIO", b"audio") == (
        "DURATION_LIMIT_EXCEEDED"
    )


def test_rejects_video_over_actual_frame_limit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    probe(
        monkeypatch,
        '{"streams":[{"width":1920,"height":1080,"avg_frame_rate":"30/1",'
        '"nb_read_frames":"301"}],"format":{"duration":"10"}}',
    )
    assert worker_with_limits()._media_limit_error("VIDEO", b"video") == (
        "FRAME_LIMIT_EXCEEDED"
    )


def test_accepts_video_at_all_boundaries(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    probe(
        monkeypatch,
        '{"streams":[{"width":1920,"height":1080,"avg_frame_rate":"30/1",'
        '"nb_read_frames":"300"}],"format":{"duration":"10"}}',
    )
    assert worker_with_limits()._media_limit_error("VIDEO", b"video") is None
