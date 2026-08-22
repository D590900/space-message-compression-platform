ALTER TABLE webhook_endpoints
  ADD COLUMN event_types text[] NOT NULL DEFAULT '{}',
  ADD COLUMN idempotency_key text,
  ADD COLUMN request_fingerprint bytea
    CHECK (request_fingerprint IS NULL OR octet_length(request_fingerprint) = 32),
  ADD COLUMN disabled_at timestamptz;

CREATE UNIQUE INDEX webhook_endpoints_idempotency_idx
  ON webhook_endpoints (tenant_subject, project_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

ALTER TABLE outbox_events
  ADD COLUMN project_id uuid,
  ADD CONSTRAINT outbox_project_fk
    FOREIGN KEY (tenant_subject, project_id) REFERENCES projects (tenant_subject, id);

ALTER TABLE webhook_deliveries
  ADD COLUMN event_type text NOT NULL DEFAULT 'unknown',
  ADD COLUMN payload jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN claim_token uuid,
  ADD COLUMN claimed_at timestamptz,
  ADD COLUMN delivered_at timestamptz,
  ADD COLUMN last_error text;

CREATE UNIQUE INDEX webhook_delivery_event_once_idx
  ON webhook_deliveries (endpoint_id, event_id);
