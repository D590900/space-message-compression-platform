BEGIN;

ALTER TABLE capsule_plans
  ADD COLUMN idempotency_key text,
  ADD COLUMN request_fingerprint bytea
    CHECK (request_fingerprint IS NULL OR octet_length(request_fingerprint) = 32);

CREATE UNIQUE INDEX capsule_plans_idempotency_idx
  ON capsule_plans (tenant_subject, project_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

ALTER TABLE capsules
  ALTER COLUMN actual_bytes DROP NOT NULL,
  ALTER COLUMN object_key DROP NOT NULL,
  ALTER COLUMN sha256 DROP NOT NULL,
  ALTER COLUMN merkle_root DROP NOT NULL,
  ALTER COLUMN format_major DROP NOT NULL,
  ALTER COLUMN format_minor DROP NOT NULL,
  ADD COLUMN status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'BUILDING', 'VERIFYING', 'COMPLETED', 'FAILED_TERMINAL')),
  ADD COLUMN error_code text,
  ADD COLUMN idempotency_key text,
  ADD COLUMN request_fingerprint bytea
    CHECK (request_fingerprint IS NULL OR octet_length(request_fingerprint) = 32),
  ADD COLUMN build_options jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN completed_at timestamptz;

CREATE UNIQUE INDEX capsules_idempotency_idx
  ON capsules (tenant_subject, project_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

COMMIT;
