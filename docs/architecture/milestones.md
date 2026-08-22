# Delivery milestones

## M0 — audit and design

Freeze trust boundaries, ADRs, schema, preliminary OpenAPI, license policy and test strategy before application code. Exit: design documents cross-reference executable contracts and unresolved external configuration is explicit.

## M1 — vertical slice

Deliver Clerk sign-in and organization project management, real scoped Clerk API keys, direct upload, lossless text job through Valkey, download/decompression, audit and capsule build. Exit: E2E passes with configured Clerk test instance and Compose.

## M2–M3 — media and optional neural codecs

Ship AVIF, Opus and AV1 CPU baselines plus JPEG XL when installed. Add capability-gated neural adapters and immutable model manifests. Exit: at least one real CPU codec per content type and all absent features accurately disabled.

## M4 — capsule and planner

Ship canonical Rust format, CLI, Merkle/ECC, exact planner, golden vectors, properties and fuzz smoke. Exit: all successful builds satisfy budget and corrupted/truncated inputs fail safely.

## M5 — productization

Complete dashboard/docs, SDKs/CLI, webhooks, quotas, rate limits, telemetry and hardening. Exit: full user flow is available without undocumented manual steps.

## M6 — release

Run generated synthetic benchmarks, publish raw JSON/CSV and derived Markdown, create SBOM/images/checksums, pass security review and release v0.1.0. Exit: public repository CI is green and final PR documents rollout and residual risk.

