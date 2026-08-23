# Space Message Compression Platform

An API-first platform for producing reproducible, quality-gated compressed artifacts and deterministic binary capsules under a strict byte budget.

> **Status:** v0.1.0 is released. The API, Clerk-backed operator dashboard, CPU worker, storage plane, SDKs, CLI and Rust capsule tool are executable. A real Clerk development instance passed both the vertical slice and the automated API-key lifecycle test. See [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md); benchmark targets are never presented as measured results.

## What is implemented

- Fastify REST API with Clerk organization sessions and Clerk-managed scoped API keys.
- PostgreSQL tenancy, audit events, idempotency, hard quotas and durable key-rotation/webhook state.
- Valkey Streams jobs, an S3-compatible object plane and short-lived encrypted signed URLs.
- Real CPU codecs: Brotli/Zstandard, AVIF/JPEG XL, Opus and AV1+Opus, with decode-and-measure gates.
- A deterministic, bounded Rust capsule format with Merkle integrity, Reed–Solomon ECC and an exact/greedy budget planner.
- TypeScript and Python SDKs, a JSON-output CLI, versioned OpenAPI, synthetic benchmarks and golden vectors.
- Non-root, read-only runtime containers; full-history secret scanning, dependency scanning, image scanning, SBOMs and release provenance in CI.

CoD-Lite and SNAC 24 kHz are available through optional digest-pinned CUDA and CPU workers. Their weights are fetched explicitly into an external verified cache and are never bundled or downloaded implicitly. Other neural codecs remain disabled until their checkpoint-specific terms and runtime artifacts are approved.

## Repository map

| Path                          | Purpose                                       |
| ----------------------------- | --------------------------------------------- |
| `apps/api`                    | TypeScript control-plane REST API             |
| `apps/cli`                    | Public command-line client                    |
| `services/compression-worker` | Python job worker and codec adapters          |
| `crates/capsule-*`            | Rust binary format, planner and CLI           |
| `packages/sdk-*`              | TypeScript and Python clients                 |
| `packages/schemas`            | Shared request/response validation            |
| `infra`                       | Migrations, production Dockerfiles, Compose   |
| `docs`                        | Architecture, security, format and operations |
| `benchmarks`                  | Synthetic fixtures, runner and measured data  |

## Prerequisites

- Docker Desktop or Docker Engine with Compose v2.
- A Clerk development instance with Organizations and API Keys enabled.
- For host-side development: Node.js 24+, pnpm 11.6, Python 3.12 with `uv`, and Rust 1.98.

The production images pin their base-image digests. Do not reuse the public Compose credentials outside a local machine.

## Quickstart

1. Create local configuration:

   ```console
   cp .env.example .env
   ```

2. Set real development values for `CLERK_SECRET_KEY` and `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` in `.env`. Never commit the file.

3. Start the CPU stack:

   ```console
   docker compose up --build --detach --wait
   curl --fail http://127.0.0.1:3000/health
   curl --fail http://127.0.0.1:3001/health/ready
   docker compose ps
   ```

   This starts the dashboard at `http://127.0.0.1:3000`, PostgreSQL, migrations, Valkey, MinIO, API and worker. MinIO's S3 endpoint is bound to `127.0.0.1:19000` so browser-facing signed URLs remain reachable; its console is at `127.0.0.1:19001`. Override `WEB_PORT`, `S3_PUBLIC_PORT`, `WEB_ORIGIN`, and `S3_PUBLIC_ENDPOINT` together when those ports are occupied. The worker health/metrics port is internal only.

4. Open `http://127.0.0.1:3000`, sign in, and select a Clerk organization. Create a project under **Settings**, then issue a scoped credential under **API keys**. Project and API-key administration intentionally reject standalone API keys. The API-key secret is returned once; store it in a secret manager.

5. Use the SDK or CLI with the issued key:

   ```console
   export SMCP_API_URL=http://127.0.0.1:3001
   export SMCP_API_KEY='the-one-time-secret'
   pnpm --filter @smcp/cli build
   node apps/cli/dist/index.js codecs
   ```

The exact request contracts and required scopes are in the generated [`docs/api/openapi.yaml`](docs/api/openapi.yaml). Its Zod request schemas and Fastify route inventory are checked against the code; change the template or schemas and run `pnpm openapi:generate`. Client examples are in [`docs/operations/clients.md`](docs/operations/clients.md).

Stop and remove local state with:

```console
docker compose down --volumes --remove-orphans
```

## Development and verification

Install and run the TypeScript quality gate:

```console
corepack enable
corepack prepare pnpm@11.6.0 --activate
pnpm install --frozen-lockfile
pnpm check
pnpm openapi:lint
```

Run the worker and Rust suites:

```console
cd services/compression-worker
uv sync --frozen
uv run ruff check .
uv run mypy src
uv run pytest
cd ../..
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --locked
```

Generate a smoke benchmark without editing results by hand:

```console
python3 benchmarks/datasets/generate.py
python3 benchmarks/runners/run_baselines.py --smoke --output-dir /tmp/smcp-benchmark
```

Committed measurements and full provenance are under [`benchmarks/reports`](benchmarks/reports). Parser fuzzing is documented in [`docs/operations/fuzzing.md`](docs/operations/fuzzing.md).

## Invariants and boundaries

- A capsule either verifies within its declared budget or is not published.
- Text lossless mode is byte-exact. Media candidates are admitted only after their configured gates pass.
- Missing dependencies and unevaluated learned metrics are reported explicitly; they are never simulated as successful.
- Tenant identity derives only from a verified Clerk session or service-issued Clerk API key.
- Secrets, payloads, signed URLs and model weights do not belong in Git or logs.
- Local Compose is a development topology, not a production high-availability deployment.

Read [`docs/architecture/system.md`](docs/architecture/system.md), [`docs/security/threat-model.md`](docs/security/threat-model.md), [`docs/operations/configuration.md`](docs/operations/configuration.md) and [`docs/operations/deployment.md`](docs/operations/deployment.md) before operating the service.

## License

Apache-2.0. Third-party code and model licensing are tracked separately in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`MODEL_LICENSES.md`](MODEL_LICENSES.md).
