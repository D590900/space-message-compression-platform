#!/bin/sh
set -eu

# Emit one psql program so the session-level advisory lock covers discovery,
# checksum validation and every migration transaction.
{
  printf '%s\n' \
    '\set ON_ERROR_STOP on' \
    'CREATE TABLE IF NOT EXISTS schema_migrations (' \
    '  filename text PRIMARY KEY,' \
    '  checksum_sha256 text,' \
    '  applied_at timestamptz NOT NULL DEFAULT now()' \
    ');' \
    'ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum_sha256 text;' \
    "SELECT pg_advisory_lock(hashtextextended('smcp-schema-migrations', 0));"

  for migration in /migrations/*.sql; do
    migration_name="$(basename "${migration}")"
    migration_checksum="$(sha256sum "${migration}" | cut -d ' ' -f 1)"
    printf "\\set migration_name '%s'\n" "${migration_name}"
    printf "\\set migration_checksum '%s'\n" "${migration_checksum}"
    printf '%s\n' \
      "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE filename = :'migration_name') AS migration_exists \\gset" \
      '\if :migration_exists' \
      "  SELECT checksum_sha256 IS NULL AS checksum_missing, COALESCE(checksum_sha256 <> :'migration_checksum', false) AS checksum_mismatch FROM schema_migrations WHERE filename = :'migration_name' \\gset" \
      '  \if :checksum_mismatch' \
      "    \\echo 'checksum mismatch for migration' :migration_name" \
      "    DO \$\$ BEGIN RAISE EXCEPTION 'migration checksum mismatch'; END \$\$;" \
      '  \endif' \
      '  \if :checksum_missing' \
      "    UPDATE schema_migrations SET checksum_sha256 = :'migration_checksum' WHERE filename = :'migration_name';" \
      '  \endif' \
      '\else' \
      '  BEGIN;'
    printf '\\i %s\n' "${migration}"
    printf '%s\n' \
      "  INSERT INTO schema_migrations (filename, checksum_sha256) VALUES (:'migration_name', :'migration_checksum');" \
      '  COMMIT;' \
      '\endif'
  done

  printf '%s\n' "SELECT pg_advisory_unlock(hashtextextended('smcp-schema-migrations', 0));"
} | psql --set ON_ERROR_STOP=1 "${DATABASE_URL}"
