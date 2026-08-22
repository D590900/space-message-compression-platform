ALTER TABLE idempotency_records
  ADD COLUMN external_resource_id text;

CREATE INDEX idempotency_records_expiry_idx
  ON idempotency_records (expires_at);
