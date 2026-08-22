# Third-party notices

This file tracks distributed **code and system-library** dependencies. Model weights are tracked separately in [`MODEL_LICENSES.md`](MODEL_LICENSES.md).

The lockfiles generated during implementation are the authoritative dependency inventory. Release CI must generate an SPDX SBOM and fail when a dependency lacks license metadata or conflicts with Apache-2.0 distribution.

| Component | Purpose | License | Distribution status |
| --- | --- | --- | --- |
| Next.js / React | Web dashboard and docs | MIT | Planned |
| Fastify | Public API | MIT | Planned |
| Clerk SDKs | Identity and API-key integration | MIT | Planned |
| PostgreSQL | Relational database | PostgreSQL | Runtime service |
| Valkey | Queue and rate-limit store | BSD-3-Clause | Runtime service |
| MinIO | Local S3-compatible storage | AGPL-3.0 | Separate runtime service; not linked or redistributed in application images |
| FFmpeg | Media probing/encoding | LGPL-2.1-or-later or GPL build-dependent | CPU image must use an LGPL-compatible build; exact configure flags recorded in SBOM |
| Brotli | Text compression | MIT | Planned |
| Zstandard | Text compression | BSD-3-Clause | Planned |
| libavif / AOM | Image baseline | BSD-2-Clause / BSD-3-Clause | Planned |
| libjxl | Image baseline | BSD-3-Clause | Optional |
| Opus | Audio baseline | BSD-3-Clause | Planned |
| Rust crates | Capsule format/planner | Per lockfile and generated SBOM | Planned |

Do not infer a model-weight license from its implementation repository.

