# Third-party notices

This file tracks distributed **code and system-library** dependencies. Model weights are tracked separately in [`MODEL_LICENSES.md`](MODEL_LICENSES.md).

The lockfiles generated during implementation are the authoritative dependency inventory. Release CI must generate an SPDX SBOM and fail when a dependency lacks license metadata or conflicts with Apache-2.0 distribution.

| Component                       | Purpose                               | License                         | Distribution status                                                                                                                                |
| ------------------------------- | ------------------------------------- | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Next.js / React                 | Web dashboard and docs                | MIT                             | Planned                                                                                                                                            |
| Fastify                         | Public API                            | MIT                             | Planned                                                                                                                                            |
| Clerk SDKs                      | Identity and API-key integration      | MIT                             | Planned                                                                                                                                            |
| PostgreSQL                      | Relational database                   | PostgreSQL                      | Runtime service                                                                                                                                    |
| Valkey                          | Queue and rate-limit store            | BSD-3-Clause                    | Runtime service                                                                                                                                    |
| MinIO                           | Local S3-compatible storage           | AGPL-3.0                        | Separate runtime service; not linked or redistributed in application images                                                                        |
| FFmpeg 9.0.1                    | Media probing/encoding                | LGPL-2.1-or-later               | Source-built in the worker image with the official release signature verified and `--disable-gpl`; exact flags are visible via `ffmpeg -buildconf` |
| dav1d                           | AV1 software decoding                 | BSD-2-Clause                    | Linked into the worker's FFmpeg build                                                                                                              |
| SVT-AV1                         | AV1 software encoding                 | BSD-3-Clause                    | Linked into the worker's FFmpeg build                                                                                                              |
| Brotli                          | Text compression                      | MIT                             | Python worker dependency                                                                                                                           |
| Zstandard                       | Text compression                      | BSD-3-Clause                    | Python worker dependency                                                                                                                           |
| libavif / AOM                   | Image baseline                        | BSD-2-Clause / BSD-3-Clause     | Worker runtime tools                                                                                                                               |
| libjxl                          | Image baseline                        | BSD-3-Clause                    | Worker runtime tools                                                                                                                               |
| Opus                            | Audio baseline                        | BSD-3-Clause                    | Linked into the worker's FFmpeg build                                                                                                              |
| OpenTelemetry SDKs              | Cross-service tracing and OTLP export | Apache-2.0                      | API and worker dependencies; no exporter is enabled without configuration                                                                          |
| prom-client / prometheus-client | Prometheus metrics exposition         | Apache-2.0                      | API and worker dependencies                                                                                                                        |
| Rust crates                     | Capsule format/planner                | Per lockfile and generated SBOM | Implemented; release SBOM pending                                                                                                                  |

Do not infer a model-weight license from its implementation repository.
