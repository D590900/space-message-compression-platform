# ADR 0001: Separate control, data, capsule and model planes

- Status: Accepted
- Date: 2026-08-22

## Context

Identity, tenant state and job orchestration have different trust and scaling boundaries from untrusted media processing. Capsule parsing must remain small, deterministic and independently verifiable. Optional model assets introduce a separate provenance lifecycle.

## Decision

Use a pnpm/Turborepo monorepo with four explicit planes:

1. The TypeScript control plane (`apps/web`, `apps/api`) owns Clerk identity, projects, requests, audit, quotas and public contracts.
2. The Python data plane (`services/compression-worker`) consumes Valkey Streams, handles untrusted media in constrained subprocesses, creates real candidates and quality reports, and persists artifacts through S3 APIs.
3. The Rust capsule plane (`crates/*`) owns canonical serialization, bit packing, indexing, Merkle verification, ECC and deterministic planning.
4. Model manifests identify external immutable code/config/weights/decoders; production never downloads weights on demand.

PostgreSQL is authoritative for state. Valkey is transport and ephemeral coordination, never the sole record of a transition. Object storage holds original, candidate, artifact and capsule bytes under tenant-prefixed keys.

## Consequences

Cross-language contracts are versioned schemas. Job transitions use compare-and-set database updates and an outbox/consumer pattern. A codec can fail without corrupting control-plane state. Capsule verification can be distributed without the web stack.

