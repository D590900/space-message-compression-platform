# Implementation status

Last updated: 2026-08-22

| Milestone | State | Evidence |
| --- | --- | --- |
| M0 — audit and design | Complete | ADRs, STRIDE model, PostgreSQL schema, linted OpenAPI, license policy and test/milestone plans |
| M1 — vertical slice | In progress | Clerk control plane, signed upload API, Valkey text worker, verified decompression and Compose services; Clerk-backed E2E and dashboard remain |
| M2 — baseline media | Complete | Real AVIF/JPEG XL, Opus and AV1+Opus adapters; decode-and-measure gates; capability registry; production-image smoke on all four baselines |
| M3 — neural codecs | Not started | — |
| M4 — capsule and planner | In progress | Canonical Rust format, CLI, exact planner, Merkle/ECC, properties and committed golden vector; API wiring and fuzz smoke remain |
| M5 — productization | Not started | — |
| M6 — release | Not started | — |

## Environment audit

- Host: macOS arm64
- Available: Node.js 26, pnpm 11, Python/uv, Docker/Compose, GitHub CLI
- Installed during development: pinned Rust 1.98 toolchain, FFmpeg, libavif and JPEG XL tools
- External configuration required for E2E: Clerk development instance

No benchmark results exist yet. Target values in planning documents are goals, not measurements.
