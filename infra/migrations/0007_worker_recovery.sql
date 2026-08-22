ALTER TABLE decompression_jobs
  ADD COLUMN attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0);

ALTER TABLE capsules
  DROP CONSTRAINT capsules_status_check,
  ADD CONSTRAINT capsules_status_check
    CHECK (status IN (
      'PENDING', 'BUILDING', 'VERIFYING', 'COMPLETED',
      'FAILED_RETRYABLE', 'FAILED_TERMINAL'
    )),
  ADD COLUMN attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0);
