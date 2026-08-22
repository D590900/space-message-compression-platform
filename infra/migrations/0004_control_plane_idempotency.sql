BEGIN;

ALTER TABLE projects
  ADD COLUMN idempotency_key text,
  ADD COLUMN request_fingerprint bytea
    CHECK (request_fingerprint IS NULL OR octet_length(request_fingerprint) = 32);

CREATE UNIQUE INDEX projects_idempotency_idx
  ON projects (tenant_subject, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

ALTER TABLE source_objects
  ADD COLUMN idempotency_key text,
  ADD COLUMN request_fingerprint bytea
    CHECK (request_fingerprint IS NULL OR octet_length(request_fingerprint) = 32);

CREATE UNIQUE INDEX source_objects_idempotency_idx
  ON source_objects (tenant_subject, project_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

ALTER TABLE api_key_rotations
  ADD COLUMN claim_token uuid,
  ADD COLUMN claimed_at timestamptz,
  ADD COLUMN attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  ADD COLUMN last_error text;

CREATE UNIQUE INDEX api_key_rotations_old_key_once_idx
  ON api_key_rotations (tenant_subject, old_key_id);

COMMIT;
