# Deployment guide

Compose is the reference single-host CPU topology and a local integration environment. A production deployment should schedule the API and worker independently and use managed PostgreSQL, Valkey and S3-compatible storage.

## Artifacts

Release CI publishes four non-root images:

- `smcp-web`: Next.js Clerk-backed operator dashboard;
- `smcp-api`: Node.js API plus the capsule planner CLI;
- `smcp-worker`: Python codecs, verified FFmpeg build and capsule CLI;
- `smcp-capsule`: standalone Rust inspection/build/verification CLI.

Base images are pinned by digest. Candidate images must pass Trivy HIGH/CRITICAL vulnerability, secret and misconfiguration scans before publishing. Release images carry BuildKit SBOM/provenance attestations; the source release includes an archive and SHA-256 checksum.

Set the GitHub Actions repository variable `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` to the production Clerk publishable key before creating a release tag. It is compiled into the public web bundle by design; the Clerk secret key remains runtime-only secret material.

## Required external services

- Clerk instance with Organizations and API Keys enabled.
- PostgreSQL 17-compatible primary with TLS, backups and point-in-time recovery.
- Valkey 8-compatible service on a private network with `noeviction` for durable job signaling.
- Private S3-compatible bucket with TLS, server-side encryption, blocked public access and lifecycle controls.
- Optional OTLP/Prometheus collectors on private or authenticated endpoints.

Valkey is transport, not the system of record. PostgreSQL remains authoritative for accepted jobs, idempotency, quotas, plans, audit events and delivery state.

## Secrets and configuration

Inject configuration through the platform secret manager; never bake it into an image or manifest. At minimum set real values for Clerk, database, Valkey, S3, identifier HMAC, webhook encryption and metrics authentication. Generate `WEBHOOK_SECRET_ENCRYPTION_KEY` as exactly 32 random bytes encoded with Base64 and rotate it through a decrypt/re-encrypt migration, not an in-place replacement. Generate `IDENTIFIER_HMAC_SECRET` independently with at least 256 bits of entropy and preserve it across deploys.

Use separate identities for migrations, API and worker where the platform supports it. Restrict the worker and API to the private database/cache/storage networks. Do not expose worker port 8000 publicly. The complete variable contract is in [`configuration.md`](configuration.md).

## Database rollout

Run the migration image as a one-shot job before updating API/worker replicas. The migration runner records checksums and serializes application; it rejects changed historical migrations. Back up before schema changes and rehearse restore procedures.

Deploy backward-compatible schema additions before code that needs them. Destructive schema removal requires a later release after all old binaries have drained.

## Runtime hardening

- Run with the image-declared non-root user, a read-only root filesystem and `no-new-privileges`.
- Drop all worker Linux capabilities and mount an isolated, size-bounded temporary directory.
- Terminate public TLS at a trusted proxy and preserve request IDs; configure strict body/time limits there as well.
- Apply egress controls so the API can reach Clerk and approved HTTPS webhook destinations, while the worker reaches only required internal services.
- Keep buckets private, require encrypted writes and use five-minute-or-shorter signed URLs unless a documented workflow requires otherwise.
- Set CPU/memory/PID limits and autoscale workers from pending queue lag plus measured processing latency.

The reference Compose topology applies explicit CPU, memory and PID ceilings to both application containers. Its worker claim-idle threshold is 30 minutes; tune `WORKER_CLAIM_IDLE_MS` above the deployment's longest allowed codec execution before scaling beyond one worker. Stale pending deliveries are reclaimed automatically and exhaust after `WORKER_MAX_ATTEMPTS`.

## Health, metrics and traces

The API exposes `/health/live`, `/health/ready` and bearer-protected `/metrics`. The worker exposes the same health states and metrics on its internal port. Readiness depends on required service connectivity and worker stream-group initialization.

Set the OTLP endpoint, including `/v1/traces`, only to an authenticated/private collector. Alerts should cover readiness failure, queue lag, terminal job failures, webhook dead letters, quota rejections and capsule verification failures. Metrics deliberately omit tenant and content identifiers.

## Rollout and rollback

1. Verify source checks, SBOM and provenance for the selected immutable image digest.
2. Apply migrations once.
3. Deploy one API and worker canary; confirm readiness, database/Valkey/S3 access and a synthetic job.
4. Roll out API replicas, then workers. Keep the previous image digest available.
5. Roll back binaries on regression. Do not reverse a migration unless a separately tested down-migration exists; use forward repair instead.

Before accepting traffic, run a real Clerk organization session → scoped API key → upload → compression → artifact decode/verify → capsule plan/build/download/verify flow in the target environment. Placeholder keys validate process health only and are not release evidence.

## Backup and recovery

Back up PostgreSQL and object storage under coordinated retention policies. Valkey stream loss may delay work but must not erase authoritative job records; reconciliation should re-enqueue accepted non-terminal records. Test capsule recovery from downloaded bytes and the reconstruction manifest independently of the live service.

Original retention is controlled by `DELETE_ORIGINALS_AFTER_SECONDS`. Zero means deletion after successful verification; any longer interval must be justified against data-minimization requirements.
