from __future__ import annotations

import hashlib
from importlib.metadata import version

import brotli
import zstandard

from smcp_worker.adapters.external import pareto_frontier_per_codec
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


def _measure(original: PreparedInput, decoded: bytes) -> QualityReport:
    original_hash = hashlib.sha256(original.original_bytes).hexdigest()
    decoded_hash = hashlib.sha256(decoded).hexdigest()
    exact = original.original_bytes == decoded
    return QualityReport(
        exact_round_trip=exact,
        original_sha256=original_hash,
        decoded_sha256=decoded_hash,
        quality_gate_passed=exact,
    )


class TextProbeMixin:
    def probe(self, source: SourceObject) -> ProbeResult:
        if source.declared_mime != "text/plain":
            return ProbeResult("application/octet-stream", False, "declared MIME is not text/plain")
        try:
            source.data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return ProbeResult("application/octet-stream", False, "input is not valid UTF-8")
        if b"\x00" in source.data:
            return ProbeResult(
                "application/octet-stream", False, "NUL byte is not accepted as text"
            )
        return ProbeResult("text/plain", True, "valid UTF-8 text")

    def preprocess(self, source: SourceObject, profile: Profile) -> PreparedInput:
        if not self.probe(source).accepted:
            raise ValueError("source did not pass text probing")
        # Lossless profiles preserve the exact original byte sequence.
        return PreparedInput(original_bytes=source.data)

    def measure(self, original: PreparedInput, decoded: bytes) -> QualityReport:
        return _measure(original, decoded)


class BrotliTextAdapter(TextProbeMixin):
    def capabilities(self) -> CodecCapabilities:
        return CodecCapabilities(
            codec_id="text.brotli",
            codec_version=version("brotli"),
            content_types=("TEXT",),
            profiles=(Profile.FAITHFUL, Profile.ULTRA),
            enabled=True,
            deterministic=True,
        )

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate:
        if params.shared_dictionary is not None:
            raise ValueError("the Brotli Python binding does not support shared dictionaries")
        payload = brotli.compress(
            prepared.original_bytes, quality=params.level, mode=brotli.MODE_TEXT
        )
        return EncodedCandidate(
            codec_id="text.brotli",
            codec_version=version("brotli"),
            config={"quality": params.level, "mode": "text"},
            payload=payload,
        )

    def decode(self, candidate: EncodedCandidate) -> bytes:
        return bytes(brotli.decompress(candidate.payload))


class ZstandardTextAdapter(TextProbeMixin):
    def capabilities(self) -> CodecCapabilities:
        return CodecCapabilities(
            codec_id="text.zstandard",
            codec_version=version("zstandard"),
            content_types=("TEXT",),
            profiles=(Profile.FAITHFUL, Profile.ULTRA),
            enabled=True,
            deterministic=True,
        )

    def encode(self, prepared: PreparedInput, params: EncodeParams) -> EncodedCandidate:
        dictionary = (
            zstandard.ZstdCompressionDict(params.shared_dictionary)
            if params.shared_dictionary
            else None
        )
        compressor = zstandard.ZstdCompressor(
            level=params.level,
            dict_data=dictionary,
            write_checksum=True,
            write_content_size=True,
            threads=0,
        )
        payload = compressor.compress(prepared.original_bytes)
        return EncodedCandidate(
            codec_id="text.zstandard",
            codec_version=version("zstandard"),
            config={
                "level": params.level,
                "checksum": True,
                "dictionary_sha256": (
                    hashlib.sha256(params.shared_dictionary).hexdigest()
                    if params.shared_dictionary
                    else None
                ),
            },
            payload=payload,
        )

    def decode(self, candidate: EncodedCandidate) -> bytes:
        # Dictionary-backed candidates are decoded by the pipeline with the registered dictionary.
        if candidate.config.get("dictionary_sha256") is not None:
            raise ValueError("registered shared dictionary is required for decoding")
        return zstandard.ZstdDecompressor().decompress(candidate.payload)


def generate_text_candidates(
    source: SourceObject, profile: Profile
) -> list[tuple[EncodedCandidate, QualityReport]]:
    adapters_and_levels = (
        (BrotliTextAdapter(), (5, 9, 11)),
        (ZstandardTextAdapter(), (9, 19, 22)),
    )
    candidates: list[tuple[EncodedCandidate, QualityReport]] = []
    for adapter, levels in adapters_and_levels:
        prepared = adapter.preprocess(source, profile)
        for level in levels:
            candidate = adapter.encode(prepared, EncodeParams(level=level))
            report = adapter.measure(prepared, adapter.decode(candidate))
            if not report.quality_gate_passed:
                raise RuntimeError(f"{candidate.codec_id} failed exact round-trip")
            candidates.append((candidate, report))

    return pareto_frontier_per_codec(
        candidates,
        codec_id=lambda candidate: candidate.codec_id,
        payload_size=lambda candidate: len(candidate.payload),
        quality=lambda _report: (1.0,),
        stable_config=lambda candidate: repr(sorted(candidate.config.items())),
    )
