from __future__ import annotations

from typing import Protocol

from smcp_worker.models import (
    CodecCapabilities,
    EncodedCandidate,
    EncodeParams,
    PreparedInput,
    ProbeResult,
    Profile,
    QualityReport,
    SourceObject,
)


class CodecAdapter(Protocol):
    def capabilities(self) -> CodecCapabilities: ...

    def probe(self, source: SourceObject) -> ProbeResult: ...

    def preprocess(self, source: SourceObject, profile: Profile) -> PreparedInput: ...

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate: ...

    def decode(self, candidate: EncodedCandidate) -> bytes: ...

    def measure(self, original: PreparedInput, decoded: bytes) -> QualityReport: ...
