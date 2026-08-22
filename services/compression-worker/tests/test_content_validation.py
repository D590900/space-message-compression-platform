import pytest

from smcp_worker.content_validation import validate_content


@pytest.mark.parametrize(
    ("input_type", "declared_mime", "filename", "payload", "detected"),
    [
        ("TEXT", "text/plain", "message.txt", "Segnale — 地球".encode(), "text/plain"),
        ("IMAGE", "image/png", "image.png", b"\x89PNG\r\n\x1a\nbody", "image/png"),
        ("IMAGE", "image/jpeg", "image.jpg", b"\xff\xd8\xffbody", "image/jpeg"),
        ("AUDIO", "audio/wav", "audio.wav", b"RIFF0000WAVEbody", "audio/wav"),
        ("AUDIO", "audio/ogg", "audio.opus", b"OggSbody", "audio/ogg"),
        ("VIDEO", "video/webm", "video.webm", b"\x1aE\xdf\xa3body", "video/webm"),
        ("VIDEO", "video/mp4", "video.mp4", b"0000ftypisom0000", "video/mp4"),
        ("IMAGE", "image/avif", "image.avif", b"0000ftypavif0000", "image/avif"),
    ],
)
def test_accepts_matching_allowlisted_content(
    input_type: str,
    declared_mime: str,
    filename: str,
    payload: bytes,
    detected: str,
) -> None:
    result = validate_content(input_type, declared_mime, filename, payload)
    assert result.detected_mime == detected
    assert result.error_code is None


def test_rejects_declared_mime_mismatch() -> None:
    result = validate_content("IMAGE", "image/jpeg", "image.jpg", b"\x89PNG\r\n\x1a\n")
    assert result.detected_mime == "image/png"
    assert result.error_code == "MIME_MISMATCH"


def test_rejects_requested_content_class_mismatch() -> None:
    result = validate_content("VIDEO", "image/png", "image.png", b"\x89PNG\r\n\x1a\n")
    assert result.error_code == "CONTENT_TYPE_MISMATCH"


def test_rejects_extension_mismatch_and_unknown_binary() -> None:
    assert (
        validate_content("IMAGE", "image/png", "image.jpg", b"\x89PNG\r\n\x1a\n").error_code
        == "EXTENSION_MISMATCH"
    )
    assert (
        validate_content("TEXT", "text/plain", "message.txt", b"valid\x00hidden").error_code
        == "UNSUPPORTED_CONTENT"
    )
