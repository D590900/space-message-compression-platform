# Release security audit

Audit date: 2026-08-23. Scope: v0.1.0 release candidate derived from the merged `main` implementation. This is reproducible engineering evidence; the protected exact-commit workflow run and its retained SBOMs establish the final candidate SHA before tagging.

## Tools and commands

- Gitleaks 8.30.1: full Git history and working-tree scans.
- Trivy 0.72.0 with the current vulnerability/check databases: source, lockfile, Dockerfile and runtime-image scans for vulnerabilities, secrets and misconfiguration.
- Runtime smoke: process identity, required codec/capsule binaries and model-manifest validation inside each candidate image.

Representative commands:

```console
gitleaks git . --redact --no-banner
gitleaks dir . --redact --no-banner
trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --ignore-unfixed .
trivy image --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --ignore-unfixed IMAGE
```

Local virtual environments, package installation trees and `.git` are excluded from the source scan because they are not release inputs. Lockfiles and all four built runtime images are scanned separately.

## Results

- Gitleaks: full history scanned; no unallowlisted finding. The single allowlist entry is an exact deterministic AES test fixture constrained by rule, line regex and three named test files.
- Source: zero HIGH/CRITICAL fixed vulnerabilities, secret findings or repository Dockerfile misconfigurations.
- API image: zero HIGH/CRITICAL fixed findings after Debian security updates and removal of runtime npm/Corepack tooling.
- Worker image: zero HIGH/CRITICAL fixed findings after moving `uv` and its cache into a build-only stage.
- Capsule image: zero HIGH/CRITICAL fixed findings.
- The web image is part of candidate and release image scanning; its exact release-candidate result remains a pre-tag gate.
- API, worker and capsule images run as the `smcp` system user (UID/GID 999 in the audited builds).
- Worker smoke validated Python, FFmpeg, the capsule CLI and all eight disabled model manifests. API smoke validated Node and the capsule CLI.
- Application dependency licenses were inventoried separately from model weights and base operating-system packages; results and the two weak-copyleft runtime dependencies are recorded in [`license-audit.md`](license-audit.md).

The pre-merge candidate images were rebuilt with their exact revision in every OCI label. Trivy reported zero fixed HIGH/CRITICAL vulnerability, secret or misconfiguration findings for the audited API, worker and capsule images. Their generated SPDX 2.3 documents contain the expected Apache-2.0 first-party packages. Every reviewed `NOASSERTION` entry was limited to the OCI document root, Debian/root packages, or the already documented `benchmarks` and `transport` npm test-fixture manifests. The four-image release-candidate workflow repeats this evidence on the exact merged commit.

The initial scan findings were fixed rather than suppressed: outdated Debian runtime packages in the API, vulnerable npm tooling unused at runtime, and a vulnerable transitive Rust dependency embedded in the `uv` installer binary. The final application images do not contain those tools.

## Automated enforcement

CI installs a checksum-pinned Gitleaks binary and scans full history plus the checkout. Source and image Trivy jobs fail on fixed HIGH/CRITICAL findings. Release preflight rejects a tag whose commit is not contained in `main` or whose SemVer disagrees with any distributable manifest. Each release image is then built exactly once, loaded locally, scanned, and used to generate an SPDX JSON SBOM before that same local image is pushed. The registry digest is bound to separate provenance and SBOM attestations. All four SPDX files are retained as workflow artifacts, attached to the GitHub release, and covered by `SHA256SUMS` alongside the source archive.

## Open release gates

- Merge release hardening and confirm all required remote checks on `main`.
- Pass the protected real-Clerk lifecycle workflow on the merged commit.
- Pass the four-image release-candidate workflow and review its exact SPDX output.

Until those gates pass, this audit does not authorize a v0.1.0 tag.
