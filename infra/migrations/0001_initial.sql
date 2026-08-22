BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE content_type AS ENUM ('TEXT', 'IMAGE', 'AUDIO', 'VIDEO');
CREATE TYPE compression_profile AS ENUM ('faithful', 'ultra', 'semantic');
CREATE TYPE job_status AS ENUM (
  'PENDING', 'VALIDATING', 'PREPROCESSING', 'ENCODING', 'MEASURING',
  'SELECTING', 'PACKAGING', 'COMPLETED', 'FAILED_RETRYABLE',
  'FAILED_TERMINAL', 'CANCELLED'
);

CREATE TABLE projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  original_retention_seconds integer CHECK (original_retention_seconds >= 0),
  quality_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  UNIQUE (tenant_subject, id)
);

CREATE TABLE project_memberships_cache (
  tenant_subject text NOT NULL,
  user_subject text NOT NULL,
  role text NOT NULL,
  clerk_membership_id text NOT NULL,
  refreshed_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_subject, user_subject)
);

CREATE TABLE source_objects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  project_id uuid NOT NULL,
  object_key text NOT NULL,
  declared_mime text NOT NULL,
  detected_mime text,
  expected_bytes bigint NOT NULL CHECK (expected_bytes > 0),
  actual_bytes bigint CHECK (actual_bytes > 0),
  sha256 bytea CHECK (sha256 IS NULL OR octet_length(sha256) = 32),
  upload_expires_at timestamptz NOT NULL,
  validated_at timestamptz,
  delete_after timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_subject, project_id) REFERENCES projects (tenant_subject, id),
  UNIQUE (tenant_subject, object_key),
  UNIQUE (tenant_subject, id)
);

CREATE TABLE compression_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  project_id uuid NOT NULL,
  input_type content_type NOT NULL,
  profile compression_profile NOT NULL,
  target_bytes bigint CHECK (target_bytes IS NULL OR target_bytes > 0),
  status job_status NOT NULL DEFAULT 'PENDING',
  source_object_id uuid NOT NULL,
  selected_candidate_id uuid,
  attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  requested_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  completed_at timestamptz,
  error_code text,
  error_detail_redacted text,
  idempotency_key text NOT NULL,
  request_fingerprint bytea NOT NULL CHECK (octet_length(request_fingerprint) = 32),
  FOREIGN KEY (tenant_subject, project_id) REFERENCES projects (tenant_subject, id),
  FOREIGN KEY (tenant_subject, source_object_id) REFERENCES source_objects (tenant_subject, id),
  UNIQUE (tenant_subject, project_id, idempotency_key),
  UNIQUE (tenant_subject, id)
);

CREATE TABLE codec_registry (
  id text NOT NULL,
  version text NOT NULL,
  content_type content_type NOT NULL,
  implementation_sha256 bytea NOT NULL CHECK (octet_length(implementation_sha256) = 32),
  deterministic boolean NOT NULL,
  enabled boolean NOT NULL,
  disabled_reason text,
  capability jsonb NOT NULL,
  PRIMARY KEY (id, version),
  CHECK (enabled OR disabled_reason IS NOT NULL)
);

CREATE TABLE model_registry (
  id text NOT NULL,
  version text NOT NULL,
  source_uri text NOT NULL,
  code_commit text NOT NULL,
  weights_sha256 bytea NOT NULL CHECK (octet_length(weights_sha256) = 32),
  config_sha256 bytea NOT NULL CHECK (octet_length(config_sha256) = 32),
  license_code text NOT NULL,
  license_weights text NOT NULL,
  input_contract text NOT NULL,
  decoder_image_digest text NOT NULL,
  enabled boolean NOT NULL DEFAULT false,
  PRIMARY KEY (id, version)
);

CREATE TABLE encoding_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  job_id uuid NOT NULL,
  codec_id text NOT NULL,
  codec_version text NOT NULL,
  model_id text,
  model_version text,
  model_hash bytea,
  config_hash bytea NOT NULL CHECK (octet_length(config_hash) = 32),
  profile compression_profile NOT NULL,
  payload_bytes bigint NOT NULL CHECK (payload_bytes >= 0),
  container_overhead_bytes bigint NOT NULL CHECK (container_overhead_bytes >= 0),
  quality_metrics jsonb NOT NULL,
  quality_gate_passed boolean NOT NULL,
  encode_duration_ms integer NOT NULL CHECK (encode_duration_ms >= 0),
  decode_duration_ms integer NOT NULL CHECK (decode_duration_ms >= 0),
  hardware jsonb NOT NULL,
  determinism_status text NOT NULL,
  object_key text NOT NULL,
  sha256 bytea NOT NULL CHECK (octet_length(sha256) = 32),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_subject, job_id) REFERENCES compression_jobs (tenant_subject, id),
  FOREIGN KEY (codec_id, codec_version) REFERENCES codec_registry (id, version),
  FOREIGN KEY (model_id, model_version) REFERENCES model_registry (id, version),
  UNIQUE (tenant_subject, id)
);

ALTER TABLE compression_jobs
  ADD CONSTRAINT selected_candidate_fk
  FOREIGN KEY (tenant_subject, selected_candidate_id)
  REFERENCES encoding_candidates (tenant_subject, id)
  DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  job_id uuid NOT NULL,
  candidate_id uuid NOT NULL,
  kind text NOT NULL,
  object_key text NOT NULL,
  bytes bigint NOT NULL CHECK (bytes >= 0),
  sha256 bytea NOT NULL CHECK (octet_length(sha256) = 32),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_subject, job_id) REFERENCES compression_jobs (tenant_subject, id),
  FOREIGN KEY (tenant_subject, candidate_id) REFERENCES encoding_candidates (tenant_subject, id),
  UNIQUE (tenant_subject, object_key),
  UNIQUE (tenant_subject, id)
);

CREATE TABLE capsule_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  project_id uuid NOT NULL,
  budget_bytes bigint NOT NULL DEFAULT 2000000 CHECK (budget_bytes > 0),
  ecc_percent numeric(5,2) NOT NULL DEFAULT 0 CHECK (ecc_percent BETWEEN 0 AND 50),
  status text NOT NULL,
  solver text NOT NULL,
  report jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_subject, project_id) REFERENCES projects (tenant_subject, id),
  UNIQUE (tenant_subject, id)
);

CREATE TABLE capsules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  project_id uuid NOT NULL,
  plan_id uuid NOT NULL,
  budget_bytes bigint NOT NULL CHECK (budget_bytes > 0),
  actual_bytes bigint NOT NULL CHECK (actual_bytes > 0 AND actual_bytes <= budget_bytes),
  object_key text NOT NULL,
  sha256 bytea NOT NULL CHECK (octet_length(sha256) = 32),
  merkle_root bytea NOT NULL CHECK (octet_length(merkle_root) = 32),
  format_major smallint NOT NULL,
  format_minor smallint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_subject, project_id) REFERENCES projects (tenant_subject, id),
  FOREIGN KEY (tenant_subject, plan_id) REFERENCES capsule_plans (tenant_subject, id),
  UNIQUE (tenant_subject, object_key),
  UNIQUE (tenant_subject, id)
);

CREATE TABLE capsule_entries (
  tenant_subject text NOT NULL,
  capsule_id uuid NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_id uuid NOT NULL,
  candidate_id uuid NOT NULL,
  utility bigint NOT NULL,
  encoded_bytes bigint NOT NULL CHECK (encoded_bytes >= 0),
  PRIMARY KEY (tenant_subject, capsule_id, ordinal),
  FOREIGN KEY (tenant_subject, capsule_id) REFERENCES capsules (tenant_subject, id),
  FOREIGN KEY (tenant_subject, artifact_id) REFERENCES artifacts (tenant_subject, id),
  FOREIGN KEY (tenant_subject, candidate_id) REFERENCES encoding_candidates (tenant_subject, id)
);

CREATE TABLE webhook_endpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  project_id uuid NOT NULL,
  url text NOT NULL CHECK (url LIKE 'https://%'),
  secret_ciphertext bytea NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_subject, project_id) REFERENCES projects (tenant_subject, id),
  UNIQUE (tenant_subject, id)
);

CREATE TABLE webhook_deliveries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  endpoint_id uuid NOT NULL,
  event_id uuid NOT NULL,
  attempt integer NOT NULL DEFAULT 0,
  status text NOT NULL,
  next_attempt_at timestamptz,
  response_code integer,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_subject, endpoint_id) REFERENCES webhook_endpoints (tenant_subject, id),
  UNIQUE (endpoint_id, event_id, attempt)
);

CREATE TABLE usage_counters (
  tenant_subject text NOT NULL,
  project_id uuid NOT NULL,
  period_start timestamptz NOT NULL,
  metric text NOT NULL,
  value bigint NOT NULL DEFAULT 0 CHECK (value >= 0),
  PRIMARY KEY (tenant_subject, project_id, period_start, metric),
  FOREIGN KEY (tenant_subject, project_id) REFERENCES projects (tenant_subject, id)
);

CREATE TABLE idempotency_records (
  tenant_subject text NOT NULL,
  route text NOT NULL,
  key text NOT NULL,
  request_fingerprint bytea NOT NULL CHECK (octet_length(request_fingerprint) = 32),
  response_status integer,
  response_body jsonb,
  resource_id uuid,
  locked_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_subject, route, key)
);

CREATE TABLE audit_events (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  tenant_subject text NOT NULL,
  project_id uuid,
  actor_subject text NOT NULL,
  api_key_id text,
  action text NOT NULL,
  resource_type text NOT NULL,
  resource_id text,
  request_id text NOT NULL,
  outcome text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_subject, project_id) REFERENCES projects (tenant_subject, id)
);

CREATE TABLE outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_subject text NOT NULL,
  topic text NOT NULL,
  aggregate_id uuid NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  attempt integer NOT NULL DEFAULT 0
);

CREATE INDEX compression_jobs_queue_idx ON compression_jobs (status, requested_at);
CREATE INDEX audit_events_tenant_time_idx ON audit_events (tenant_subject, occurred_at DESC);
CREATE INDEX outbox_unpublished_idx ON outbox_events (created_at) WHERE published_at IS NULL;
CREATE INDEX webhook_due_idx ON webhook_deliveries (next_attempt_at) WHERE status = 'RETRY';

COMMIT;

