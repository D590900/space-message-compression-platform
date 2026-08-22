# Data model

The executable PostgreSQL schema lives in [`infra/migrations/0001_initial.sql`](../../infra/migrations/0001_initial.sql). All tenant-owned tables carry `tenant_subject`; foreign-key paths and repository methods must preserve it.

## State machine

`PENDING → VALIDATING → PREPROCESSING → ENCODING → MEASURING → SELECTING → PACKAGING → COMPLETED`

Any active state may move to `FAILED_RETRYABLE`, `FAILED_TERMINAL` or `CANCELLED`. A retry uses an incremented attempt and a compare-and-set transition back to the recorded resume state. Terminal states cannot transition. Each successful state change inserts an `audit_events` row in the same transaction.

## Idempotency

Mutating API requests store `(tenant_subject, route, idempotency_key, request_fingerprint)`. Reuse with the same fingerprint returns the stored response; reuse with different input returns conflict. Entries expire only after the documented retry horizon.

