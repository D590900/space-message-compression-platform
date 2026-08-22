# Security policy

## Reporting a vulnerability

Use GitHub private vulnerability reporting for this repository. Do not open a public issue or include user content, credentials, API keys, signed URLs, webhook secrets, object keys or model-distribution links in a report.

Include the affected version or commit, impact, a minimal reproduction and any suggested mitigation. Maintainers will acknowledge a complete report within three business days, provide a triage decision as investigation permits, and coordinate remediation and disclosure. Do not access data that is not yours or degrade a running service while testing.

## Supported versions

Until v0.1.0, only the current default branch is supported. After the first release, the latest minor release receives security fixes. Pre-release artifacts are not covered by a stability guarantee.

## Security invariants

- No secret, user payload, signed URL or model weight is committed or logged.
- Tenant identity comes exclusively from a verified Clerk credential; client-provided tenant headers are not trusted.
- API-key secrets are returned once by Clerk and never stored by SMCP.
- Missing codec/model dependencies disable a capability; integrity and quality checks are never bypassed.
- A capsule is not published unless its hash, section checksums, Merkle root and strict byte budget verify.
- Uploads are size-limited, MIME-sniffed and stored privately with server-side encryption.
- Webhook targets must be public HTTPS endpoints and are DNS-resolved, address-pinned, redirect-blocked, signed and retried durably.
- Production processes run non-root with restricted filesystems; worker media subprocesses use bounded inputs, timeouts and private temporary files.

## Release security gate

Pull requests run lint/typecheck/tests, CodeQL, dependency review, Gitleaks over full Git history and the working tree, Trivy filesystem/image scans, Docker builds and Compose smoke tests. Release images are scanned for fixed HIGH/CRITICAL findings before publication and are emitted with SBOM and provenance attestations.

The narrow Gitleaks allowlist permits one deterministic AES unit-test fixture only when both its exact source line and one of three named test paths match. New findings must not be hidden by directory-wide or rule-wide exclusions.

See [`docs/security/threat-model.md`](docs/security/threat-model.md) for the STRIDE analysis and [`docs/operations/configuration.md`](docs/operations/configuration.md) for secret, retention and observability controls.
