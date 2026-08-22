# Test plan

## Fast gates on every change

- TypeScript format, lint, strict typecheck, unit tests and OpenAPI validation.
- Python ruff, mypy, pytest and adapter capability tests.
- Rust fmt, clippy with warnings denied, unit/property/golden tests.
- Migration apply/rollback smoke and Compose configuration validation.

## Integration and E2E

Integration covers Clerk test keys (valid, expired, revoked, missing claim, wrong scope), presigned storage, duplicate stream delivery, worker restart, webhook retries and tenant isolation. The E2E path is sign-in → project → scoped key → direct upload → compression → download → decompression/compare → capsule plan/build/verify/extract.

Tests that require Clerk are marked and fail with a clear configuration error when explicitly selected without credentials; they are not silently replaced by mocks. Pull requests from untrusted forks run non-secret gates, while protected CI runs the real integration suite.

## Robustness

Golden vectors pin deterministic hashes. Property tests exercise varints, packing and planner invariants. Fuzz smoke covers truncated/corrupt headers, non-canonical encodings, offset overflow, excessive counts and insufficient ECC. Concurrency tests double-submit every transition and require one observable outcome.

## Benchmark integrity

Synthetic redistributable fixtures are generated from committed seeds. Runners emit machine-readable JSON and CSV; Markdown is derived only from those outputs. Hardware, versions, commit and hashes are mandatory. Aspirational targets are never copied into results.

