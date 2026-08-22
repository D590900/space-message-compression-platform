# System architecture

## Request and data flow

1. A signed-in Clerk organization member creates a project and a scoped Clerk API key. The application never stores the key secret.
2. The client requests a presigned upload using the API key. The API records an object intent and returns a short-lived tenant-prefixed S3 URL.
3. The client uploads directly to object storage and creates a compression job with an idempotency key.
4. PostgreSQL commits the job and an outbox event. A dispatcher publishes the event to a Valkey Stream.
5. The Python worker claims the event, validates/sniffs input, runs real available adapters, decodes candidates, measures quality, removes dominated candidates and selects the smallest passing candidate.
6. State changes and audit events are committed idempotently. A signed webhook is delivered from an outbox with timestamp, nonce, exponential backoff and dead-letter state.
7. Downloads use short-lived signed URLs. Decompression verifies hashes and the registered decoder chain.
8. Capsule planning chooses one candidate per required message, serializes with the Rust builder, then verifies the actual result is within budget.

## Trust boundaries

- **Public edge:** untrusted requests and uploaded bytes.
- **Control plane:** tenant-aware API and database credentials; no media execution.
- **Media sandbox:** non-root worker subprocesses with bounded CPU, memory, files, duration and no network.
- **Capsule core:** memory-safe Rust parser with explicit allocation and count limits.
- **External identity:** Clerk; keys and sessions are verified server-side.
- **Object storage:** private buckets, TLS, encryption and tenant-prefixed keys.

## State ownership

PostgreSQL is authoritative. Every transition includes expected prior state, attempt number and audit record. Stream delivery is at least once; handlers are idempotent. Objects are immutable and addressed by SHA-256 after upload validation.

