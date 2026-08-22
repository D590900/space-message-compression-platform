# Contributing

## Development rules

1. Branch from the default branch and keep commits scoped and descriptive.
2. Never commit `.env` files, credentials, signed URLs, private fixtures, generated user artifacts or model weights.
3. Add or update an ADR when changing a trust boundary, external authority, binary format or reproducibility contract.
4. A codec adapter must run a real implementation and report accurate capabilities. Test-only fakes remain under test paths.
5. Record code and weight licenses separately before enabling a model.
6. Generate benchmark reports from committed runners and fixtures; do not edit measured values manually.

Run the repository-wide `pnpm check` and the Compose E2E profile before requesting review. Rust checks run in the pinned toolchain container when no host toolchain is installed.

