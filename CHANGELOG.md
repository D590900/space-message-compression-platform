# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Updated the `tsx` toolchain dependency so the transitive `esbuild` version is
  outside the affected advisory range.

### Changed

- Updated pinned GitHub Actions to their Node.js 24-based releases and aligned
  the implementation audit with the published and verified `v0.1.0` release.

## [0.1.0] - 2026-08-23

### Added

- Clerk organization sessions and service-issued, scoped API keys with durable
  creation, rotation, revocation and audit records.
- Tenant-isolated upload, compression, decompression and capsule APIs backed by
  PostgreSQL, Valkey Streams and S3-compatible object storage.
- CPU codec baselines for text, images, audio and video with measured quality
  gates and explicit fail-closed handling for unavailable learned metrics.
- Canonical Rust capsule format, exact and greedy budget planners, Merkle/ECC
  verification, CLI inspection and extraction.
- TypeScript and Python SDKs, JSON CLI and Clerk-backed operator dashboard.
- Signed durable webhooks, hard quotas, cost-weighted rate limits, metrics,
  tracing, retention and recovery controls.
- Pinned CI, source and image security scans, SPDX SBOMs, provenance
  attestations, release-candidate auditing and protected real-Clerk tests.

### Security

- API-key authentication confirms current Clerk metadata after secret
  verification, so a revoked or expired key is rejected even if Clerk's verify
  endpoint briefly returns a pre-revocation snapshot.
- PostgreSQL reconstructs missing job outbox events for safely replayable
  pending or retryable work only when an atomic Valkey delivery marker proves
  that the transport record was lost.

[0.1.0]: https://github.com/D590900/space-message-compression-platform/releases/tag/v0.1.0
[Unreleased]: https://github.com/D590900/space-message-compression-platform/compare/v0.1.0...HEAD
