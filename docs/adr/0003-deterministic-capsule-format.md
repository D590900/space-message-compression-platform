# ADR 0003: Canonical binary capsule with reconstruction verification

- Status: Accepted
- Date: 2026-08-22

## Context

The final artifact must include all overhead and ECC within a hard byte budget, remain stream-parseable, and provide stable verification without JSON or Base64 payload inflation.

## Decision

SMCP Capsule Format v1 is little-endian and canonical. It uses a fixed header, bounded section table, unsigned LEB128 integers where compact, contiguous typed streams, delta-coded record indices, CRC32C per section, SHA-256 leaves and Merkle root, plus optional Reed–Solomon parity. Registry entries contain codec/model/config hashes once and records reference compact integer IDs.

The planner uses actual serialized candidate sizes and an exact overhead function. It solves multiple-choice knapsack deterministically, falls back to a stable greedy method, builds the real container, and re-plans if size differs. The final invariant is `serialized_length <= declared_budget`; failure produces no output file.

Parsers reject unknown required flags, non-canonical varints, duplicate sections, integer overflow, overlapping offsets, out-of-bounds reads, excessive counts, checksum failure and trailing data outside declared padding.

## Consequences

Encoding changes require versioning and golden vectors. Timestamps are omitted by default to preserve reproducibility. Optional parity reduces payload capacity and is included in planning.

