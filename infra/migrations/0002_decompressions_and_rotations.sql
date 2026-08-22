CREATE TABLE decompression_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  project_id uuid NOT NULL,
  artifact_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'DECODING', 'VERIFYING', 'COMPLETED', 'FAILED_RETRYABLE', 'FAILED_TERMINAL')),
  output_object_key text,
  output_bytes bigint CHECK (output_bytes IS NULL OR output_bytes >= 0),
  output_sha256 bytea CHECK (output_sha256 IS NULL OR octet_length(output_sha256) = 32),
  verified boolean,
  error_code text,
  idempotency_key text NOT NULL,
  request_fingerprint bytea NOT NULL CHECK (octet_length(request_fingerprint) = 32),
  requested_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  FOREIGN KEY (tenant_subject, project_id) REFERENCES projects (tenant_subject, id),
  FOREIGN KEY (tenant_subject, artifact_id) REFERENCES artifacts (tenant_subject, id),
  UNIQUE (tenant_subject, project_id, idempotency_key),
  UNIQUE (tenant_subject, id)
);

CREATE TABLE api_key_rotations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  old_key_id text NOT NULL,
  new_key_id text NOT NULL,
  revoke_at timestamptz NOT NULL,
  revoked_at timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_subject, old_key_id, new_key_id)
);

CREATE INDEX decompression_jobs_queue_idx
  ON decompression_jobs (status, requested_at);
CREATE INDEX api_key_rotations_due_idx
  ON api_key_rotations (revoke_at)
  WHERE revoked_at IS NULL;

