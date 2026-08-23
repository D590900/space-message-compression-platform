# Implementation status

Last updated: 2026-08-23

| Milestone                | State       | Evidence                                                                                                                                                                                                                                                                  |
| ------------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M0 — audit and design    | Complete    | ADRs, STRIDE model, PostgreSQL schema, runtime-schema-generated/linted OpenAPI, license policy and test/milestone plans                                                                                                                                                   |
| M1 — vertical slice      | Complete    | Real Clerk organization login and scoped key issuance; signed upload; asynchronous Brotli/Zstandard candidates; artifact download; bit-exact decompression; exact capsule plan; Rust build/download/hash verification; key revocation enforced with 401                  |
| M2 — baseline media      | Complete    | Real AVIF/JPEG XL, Opus and AV1+Opus adapters; decode-and-measure gates; capability registry; production-image smoke on all four baselines                                                                                                                                |
| M3 — neural codecs       | In progress | Eight official implementations pinned with separately verified code-license evidence; strict enabled-manifest/hash/download gates; inference remains disabled until weight terms and real pipelines are approved                                                          |
| M4 — capsule and planner | Complete    | Canonical Rust format, exact/greedy planner, API/worker wiring, Merkle/ECC, CLI, golden/properties and a 33.7M-input parser fuzz smoke                                                                                                                                    |
| M5 — productization      | Complete    | Clerk-backed responsive dashboard, session-backed collections, configurable non-weakenable quality gates, original retention, TypeScript/Python SDKs, public CLI including Rust capsule extraction, signed durable webhooks, quotas/rate limits and operator docs       |
| M6 — release             | In progress | Pinned CI/security/image/release workflows, reproducible JSON/CSV/Markdown CPU benchmarks, clean source/image secret+CVE audit and dependency-license inventory; public draft PR exists, final CI/review and tag remain                                                   |

## Environment audit

- Host: macOS arm64
- Available: Node.js 26, pnpm 11, Python/uv, Docker/Compose, GitHub CLI
- Installed during development: pinned Rust 1.98 toolchain, FFmpeg, libavif and JPEG XL tools
- Live E2E used a Clerk development instance; both short-lived test keys were revoked after validation

Measured synthetic CPU results are under `benchmarks/reports/`. Target values in planning documents remain goals, not measurements.
