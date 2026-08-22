ALTER TABLE outbox_events
  ADD COLUMN claim_token uuid,
  ADD COLUMN claimed_at timestamptz,
  ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN last_error text;

CREATE INDEX outbox_job_due_idx
  ON outbox_events (next_attempt_at, created_at)
  WHERE published_at IS NULL
    AND topic IN (
      'compression.requested',
      'decompression.requested',
      'capsule.requested'
    );
