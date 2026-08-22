# Data model

The executable PostgreSQL schema lives in [`infra/migrations/0001_initial.sql`](../../infra/migrations/0001_initial.sql). All tenant-owned tables carry `tenant_subject`; foreign-key paths and repository methods must preserve it.

## State machine

`PENDING → VALIDATING → PREPROCESSING → ENCODING → MEASURING → SELECTING → PACKAGING → COMPLETED`

Any active state may move to `FAILED_RETRYABLE`, `FAILED_TERMINAL` or, for compression, `CANCELLED`. Valkey consumer-group deliveries are acknowledged only after success or terminal exhaustion. A worker reclaims stale pending deliveries with `XAUTOCLAIM`; a retry resets the authoritative row to `PENDING`, and compression retries first remove tracked partial candidates and artifacts. Crash recovery increments the attempt counter, and repeated failures become `FAILED_TERMINAL` at `WORKER_MAX_ATTEMPTS`. Completed rows are idempotent, so a crash after the completion transaction but before acknowledgement does not duplicate completion events.

Every worker failure transition appends an audit record in the same PostgreSQL transaction. Its metadata is limited to job type/ID, stable error code, state and attempt count; payloads, object keys and decoded media details are excluded.

Candidate selection operates only on measured, quality-gated Pareto points. `target_bytes`, when supplied, is a hard candidate-payload ceiling rather than a hint; if no measured candidate fits, the job ends as `FAILED_TERMINAL` with `TARGET_BYTES_UNSATISFIED` instead of returning an oversized artifact.

## Idempotency

Mutating API requests store `(tenant_subject, route, idempotency_key, request_fingerprint)`. Reuse with the same fingerprint returns the stored response; reuse with different input returns conflict. Entries expire only after the documented retry horizon.
