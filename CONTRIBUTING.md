# Contributing

## Before changing code

1. Branch from the default branch and keep commits scoped and descriptive.
2. Read the relevant ADR and threat-model section before changing a trust boundary, external authority, binary format or reproducibility contract.
3. Do not commit `.env` files, credentials, signed URLs, private fixtures, generated user artifacts or model weights.
4. Check [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md). Disabled or incomplete behavior must remain explicit in code, API responses and documentation.

## Local setup

Use Node.js 24+, pnpm 11.6, Python 3.12 with `uv`, Rust 1.98 and Docker Compose. Install locked dependencies:

```console
corepack enable
corepack prepare pnpm@11.6.0 --activate
pnpm install --frozen-lockfile
uv sync --project services/compression-worker --frozen
```

Copy `.env.example` to `.env` only when running Compose. A live protected-flow test requires a Clerk development instance; placeholders are sufficient only for dependency/health smoke tests and never prove authentication.

## Change rules

- Add or update an ADR for material architecture or format decisions.
- A codec adapter must execute a real implementation and report accurate capabilities. Test fakes remain under test paths.
- Record code and weight licenses separately before enabling a model. A known code license never implies permission to use or distribute weights.
- Do not add runtime downloads. Model acquisition is explicit, checksum-verified and operator initiated.
- Preserve deterministic ordering, canonical encoding and bounded parsing in capsule code. Rust production crates forbid unsafe code.
- Add migrations rather than editing an already released migration. The runner must apply each file once, atomically, under its advisory lock and reject later checksum changes.
- Generate benchmark reports from committed runners and fixtures; never edit measured values manually.
- Avoid high-cardinality or tenant-bearing metric labels and never attach payloads or secrets to traces.

## Required checks

Run the repository gate:

```console
pnpm check
pnpm openapi:lint
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --locked
uv --directory services/compression-worker run ruff check src tests
uv --directory services/compression-worker run mypy src
uv --directory services/compression-worker run pytest -q
uv --directory packages/sdk-python run ruff check src tests
uv --directory packages/sdk-python run mypy src
uv --directory packages/sdk-python run pytest -q
```

For infrastructure, codec or vertical-slice changes, also run:

```console
docker compose config --quiet
docker compose up --build --detach --wait
curl --fail http://127.0.0.1:3001/health/ready
docker compose run --rm migrate
docker compose down --volumes --remove-orphans
```

Run the relevant golden-vector, benchmark or fuzz workflow when changing serialization, codecs, metrics or planner behavior. Security-sensitive changes should include a focused regression test.

## Pull requests

Explain the problem, trust/security impact, migration implications, tests executed and any disabled or deferred behavior. Link an ADR when required. A reviewable change must leave generated files reproducible and documentation consistent with observable behavior.

Report vulnerabilities through the private process in [`SECURITY.md`](SECURITY.md), not a pull request or public issue.
