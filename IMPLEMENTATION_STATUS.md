# Implementation status

Last updated: 2026-08-22

| Milestone                | State       | Evidence                                                                                                                                                                                                         |
| ------------------------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M0 — audit and design    | Complete    | ADRs, STRIDE model, PostgreSQL schema, linted OpenAPI, license policy and test/milestone plans                                                                                                                   |
| M1 — vertical slice      | In progress | Clerk control plane, signed upload API, Valkey worker, verified decompression, capsule E2E and Compose services; live Clerk E2E and dashboard remain                                                             |
| M2 — baseline media      | Complete    | Real AVIF/JPEG XL, Opus and AV1+Opus adapters; decode-and-measure gates; capability registry; production-image smoke on all four baselines                                                                       |
| M3 — neural codecs       | In progress | Eight official implementations pinned with separately verified code-license evidence; strict enabled-manifest/hash/download gates; inference remains disabled until weight terms and real pipelines are approved |
| M4 — capsule and planner | Complete    | Canonical Rust format, exact/greedy planner, API/worker wiring, Merkle/ECC, CLI, golden/properties and a 33.7M-input parser fuzz smoke                                                                           |
| M5 — productization      | In progress | TypeScript/Python SDKs, public CLI, signed durable webhooks, atomic quotas, protected metrics, OTLP trace propagation, live worker health and operator docs; dashboard remains                                   |
| M6 — release             | In progress | Pinned CI/security/image/release workflows and reproducible JSON/CSV/Markdown CPU benchmarks; full release audit, public PR and tag remain                                                                       |

## Environment audit

- Host: macOS arm64
- Available: Node.js 26, pnpm 11, Python/uv, Docker/Compose, GitHub CLI
- Installed during development: pinned Rust 1.98 toolchain, FFmpeg, libavif and JPEG XL tools
- External configuration required for E2E: Clerk development instance

Measured synthetic CPU results are under `benchmarks/reports/`. Target values in planning documents remain goals, not measurements.
