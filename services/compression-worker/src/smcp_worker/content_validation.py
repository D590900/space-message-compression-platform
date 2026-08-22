from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ContentValidation:
    detected_mime: str
    error_code: str | None


MIME_CONTENT_TYPES = {
    "text/plain": "TEXT",
    "image/avif": "IMAGE",
    "image/jpeg": "IMAGE",
    "image/png": "IMAGE",
    "audio/ogg": "AUDIO",
    "audio/wav": "AUDIO",
    "video/mp4": "VIDEO",
    "video/webm": "VIDEO",
}

MIME_EXTENSIONS = {
    "text/plain": {".csv", ".json", ".log", ".md", ".text", ".txt"},
    "image/avif": {".avif"},
    "image/jpeg": {".jpeg", ".jpg"},
    "image/png": {".png"},
    "audio/ogg": {".oga", ".ogg", ".opus"},
    "audio/wav": {".wav", ".wave"},
    "video/mp4": {".m4v", ".mov", ".mp4"},
    "video/webm": {".webm"},
}


def _sniff_binary_mime(payload: bytes) -> str:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WAVE":
        return "audio/wav"
    if payload.startswith(b"OggS"):
        return "audio/ogg"
    if payload.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    if len(payload) >= 16 and payload[4:8] == b"ftyp":
        brands = payload[8:32]
        if b"avif" in brands or b"avis" in brands:
            return "image/avif"
        return "video/mp4"
    return "application/octet-stream"


def validate_content(
    input_type: str,
    declared_mime: str,
    filename: str,
    payload: bytes,
) -> ContentValidation:
    if input_type == "TEXT":
        try:
            payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            detected_mime = "application/octet-stream"
        else:
            detected_mime = "application/octet-stream" if b"\x00" in payload else "text/plain"
    else:
        detected_mime = _sniff_binary_mime(payload)

    if detected_mime == "application/octet-stream":
        return ContentValidation(detected_mime, "UNSUPPORTED_CONTENT")
    if declared_mime != detected_mime:
        return ContentValidation(detected_mime, "MIME_MISMATCH")
    if MIME_CONTENT_TYPES.get(detected_mime) != input_type:
        return ContentValidation(detected_mime, "CONTENT_TYPE_MISMATCH")
    suffix = Path(filename).suffix.lower()
    if suffix and suffix not in MIME_EXTENSIONS[detected_mime]:
        return ContentValidation(detected_mime, "EXTENSION_MISMATCH")
    return ContentValidation(detected_mime, None)
