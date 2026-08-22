#!/bin/sh
set -eu

psql --set ON_ERROR_STOP=1 "${DATABASE_URL}" <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
  filename text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

for migration in /migrations/*.sql; do
  migration_name="$(basename "${migration}")"
  already_applied="$(
    psql --tuples-only --no-align "${DATABASE_URL}" \
      --set migration_name="${migration_name}" <<'SQL'
SELECT 1 FROM schema_migrations WHERE filename = :'migration_name';
SQL
  )"
  if [ "${already_applied}" = "1" ]; then
    continue
  fi
  psql --set ON_ERROR_STOP=1 "${DATABASE_URL}" --file "${migration}"
  psql --set ON_ERROR_STOP=1 "${DATABASE_URL}" \
    --set migration_name="${migration_name}" <<'SQL'
INSERT INTO schema_migrations (filename) VALUES (:'migration_name');
SQL
done
