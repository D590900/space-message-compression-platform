ALTER TABLE source_objects
  ADD COLUMN deleted_at timestamptz,
  ADD COLUMN deletion_attempt integer NOT NULL DEFAULT 0 CHECK (deletion_attempt >= 0),
  ADD COLUMN deletion_claimed_at timestamptz,
  ADD COLUMN deletion_claim_token uuid,
  ADD COLUMN deletion_error_redacted text;

CREATE INDEX source_objects_deletion_due_idx
  ON source_objects (delete_after, id)
  WHERE delete_after IS NOT NULL AND deleted_at IS NULL;
