# Threat model (STRIDE)

## Assets and adversaries

Assets include user identity, organization boundaries, API keys, private content, model supply chain, artifacts, capsule integrity, quotas and audit history. Adversaries include unauthenticated clients, malicious tenants, compromised dependencies/models, forged webhooks and malformed media/capsules.

| Category | Threat | Required controls | Verification |
| --- | --- | --- | --- |
| Spoofing | Forged session/API key or tenant subject | Server-side Clerk verification; `smcp_issued` claim; scope/expiry checks; derive tenant from credential | Real Clerk integration tests for valid, expired, revoked and wrong-scope keys |
| Tampering | Modified uploads, artifacts, manifests or capsules | SHA-256 object identity; immutable keys; CRC32C sections; Merkle root; signed URLs | Integration, golden and corruption tests |
| Repudiation | Denied key usage, job transitions or webhook sends | Append-only audit events with actor, request ID, key ID, timestamp and outcome; never secret/content | State-machine and audit tests |
| Information disclosure | Cross-tenant reads, secrets in logs, public buckets | Tenant predicate on every query; private storage; short TTL; structured redaction; no payload spans | Authorization matrix and log scans |
| Denial of service | Oversized files, bombs, parser allocations, expensive codecs | Byte/pixel/frame/duration/count limits; MIME sniffing; time/memory/process limits; rate/cost limits; bounded parser | Malicious corpus, property tests, fuzzing and load tests |
| Elevation of privilege | Scope bypass, worker breakout, unsafe decoder | Central policy; least-privilege IAM; non-root/read-only/no-network media subprocess; no Rust `unsafe` by default | Policy unit tests and container hardening checks |

## Supply-chain controls

- Pin package and container dependencies; generate SPDX SBOM and scan on every release.
- Never build from moving model branches. Verify code revision, weight/config SHA-256 and separate licenses before enablement.
- Do not download weights at build, import or request time.
- Secret scanning and dependency review block merge.
- FFmpeg runs against an allowlist with protocol/network access disabled, bounded probe/analyze sizes and isolated temporary directories.

## Retention and incident response

Projects configure original retention; deletion jobs remove originals and tombstone the event while preserving content-free audit data. Key compromise response revokes through Clerk, invalidates verification cache and reviews key-ID audit history. Integrity failure quarantines the object/capsule and never falls back to unverified output.

