from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Profile(StrEnum):
    FAITHFUL = "faithful"
    ULTRA = "ultra"
    SEMANTIC = "semantic"


@dataclass(frozen=True, slots=True)
class CodecCapabilities:
    codec_id: str
    codec_version: str
    content_types: tuple[str, ...]
    profiles: tuple[Profile, ...]
    enabled: bool
    deterministic: bool
    disabled_reason: str | None = None
    install_hint: str | None = None

    def __post_init__(self) -> None:
        if not self.enabled and not self.disabled_reason:
            raise ValueError("a disabled codec must explain why it is disabled")


@dataclass(frozen=True, slots=True)
class SourceObject:
    data: bytes
    declared_mime: str
    filename: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    detected_mime: str
    accepted: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PreparedInput:
    original_bytes: bytes


@dataclass(frozen=True, slots=True)
class EncodeParams:
    level: int
    shared_dictionary: bytes | None = None


@dataclass(frozen=True, slots=True)
class EncodedCandidate:
    codec_id: str
    codec_version: str
    config: dict[str, Any]
    payload: bytes


@dataclass(frozen=True, slots=True)
class QualityReport:
    exact_round_trip: bool
    original_sha256: str
    decoded_sha256: str
    quality_gate_passed: bool
