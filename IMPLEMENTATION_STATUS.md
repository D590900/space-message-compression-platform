# Implementation status

Last updated: 2026-08-23

| Milestone                | State       | Evidence                                                                                                                                                                                                                                                          |
| ------------------------ | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M0 — audit and design    | Complete    | ADRs, STRIDE model, PostgreSQL schema, runtime-schema-generated/linted OpenAPI, license policy and test/milestone plans                                                                                                                                           |
| M1 — vertical slice      | Complete    | Real Clerk organization login and scoped key issuance; signed upload; asynchronous Brotli/Zstandard candidates; artifact download; bit-exact decompression; exact capsule plan; Rust build/download/hash verification; key revocation enforced with 401           |
| M2 — baseline media      | Complete    | Real AVIF/JPEG XL, Opus and AV1+Opus adapters; decode-and-measure gates; capability registry; production-image smoke on all four baselines                                                                                                                        |
| M3 — neural codecs       | In progress | CoD-Lite 0.0312-bpp and SNAC 24 kHz are enabled with immutable CUDA and CPU decoders; both use external hash-verified weights and scanned, attested runtimes; six other families remain fail-closed pending checkpoint-specific approval                          |
| M4 — capsule and planner | Complete    | Canonical Rust format, exact/greedy planner, API/worker wiring, Merkle/ECC, CLI, golden/properties and a 33.7M-input parser fuzz smoke                                                                                                                            |
| M5 — productization      | Complete    | Clerk-backed responsive dashboard, session-backed collections, configurable non-weakenable quality gates, original retention, TypeScript/Python SDKs, public CLI including Rust capsule extraction, signed durable webhooks, quotas/rate limits and operator docs |
| M6 — release             | Complete    | Release `v0.1.0` published from the exact audited commit with protected Clerk lifecycle validation, four scanned and attested GHCR images, SPDX SBOMs, source archive and independently re-verified checksums                                                     |

## Environment audit

- Host: macOS arm64
- Available: Node.js 26, pnpm 11, Python/uv, Docker/Compose, GitHub CLI
- Installed during development: pinned Rust 1.98 toolchain, FFmpeg, libavif and JPEG XL tools
- Live E2E used a Clerk development instance; both short-lived test keys were revoked after validation

Measured synthetic CPU results are under `benchmarks/reports/`. Target values in planning documents remain goals, not measurements.
