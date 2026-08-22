# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or include user content, credentials, API keys, signed URLs or model-distribution links in a report. Use GitHub's private vulnerability reporting for this repository. Maintainers will acknowledge a complete report within three business days and coordinate remediation and disclosure.

## Supported versions

Until v0.1.0, only the current default branch is supported. After the first release, the latest minor release receives security fixes.

## Security invariants

- No secret, user payload or model weight is committed or logged.
- Tenant identity comes exclusively from a verified Clerk credential.
- Missing codec/model dependencies disable a capability; integrity checks are never bypassed.
- A capsule is not published unless its hash, section checksums, Merkle root and strict budget all verify.
- Untrusted media runs in bounded, non-root, network-disabled subprocesses.

See [`docs/security/threat-model.md`](docs/security/threat-model.md) for the full threat model.

