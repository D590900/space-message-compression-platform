CREATE INDEX outbox_job_published_aggregate_idx
  ON outbox_events (topic, aggregate_id, published_at DESC)
  WHERE published_at IS NOT NULL
    AND topic IN (
      'compression.requested',
      'decompression.requested',
      'capsule.requested'
    )
    AND payload ->> 'transport_marker_version' = '1';

CREATE INDEX outbox_job_unpublished_aggregate_idx
  ON outbox_events (topic, aggregate_id)
  WHERE published_at IS NULL
    AND topic IN (
      'compression.requested',
      'decompression.requested',
      'capsule.requested'
    );
