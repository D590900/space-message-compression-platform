# Space Message Compression Platform

An API-first platform for producing reproducible, quality-gated compressed artifacts and deterministic binary capsules under a strict byte budget.

> **Status:** active development toward v0.1.0. The design is frozen in M0; implementation status is tracked in [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md). No benchmark target is presented as an achieved result.

## Principles

- A capsule build either verifies within its declared budget or fails atomically.
- Codec adapters execute real tools. Missing optional dependencies are reported as disabled capabilities, never simulated.
- Text lossless mode is byte-exact. Media output is admitted only after configured quality gates pass.
- Model code, configuration, weights and decoder images are identified by cryptographic hashes.
- Secrets, user payloads and model weights never belong in Git.

## Planned local stack

The current CPU Compose stack runs the Fastify API, Python worker, PostgreSQL, Valkey and MinIO. The Next.js dashboard is still in progress. Clerk is the identity and API-key authority and requires a configured development instance. Neural codecs are optional and never downloaded during build or import.

The API, worker, storage and capsule stack is executable with Compose; the dashboard remains in progress. Supported TypeScript, Python and CLI usage is documented in [`docs/operations/clients.md`](docs/operations/clients.md). For architecture and security decisions, start with [`docs/architecture/system.md`](docs/architecture/system.md) and [`docs/security/threat-model.md`](docs/security/threat-model.md).

## License

Apache-2.0. Third-party code and model licensing are tracked separately in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`MODEL_LICENSES.md`](MODEL_LICENSES.md).
