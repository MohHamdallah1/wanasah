#!/usr/bin/env bash
# Verify a backup by restoring to a BRAND NEW, disposable loopback database.
# Never use a current production/development database name as a target.
set -Eeuo pipefail
umask 077

archive="${1:-}"
RESTORE_HOST="${RESTORE_HOST:-127.0.0.1}"
RESTORE_PORT="${RESTORE_PORT:-5432}"
RESTORE_USER="${RESTORE_USER:-${POSTGRES_USER:-wanasah_admin}}"
if [[ -z "$archive" || ! -s "$archive" ]]; then
  echo "[WanasahRestore] Supply an existing nonempty .dump file" >&2; exit 2
fi
if [[ "$RESTORE_HOST" != '127.0.0.1' && "$RESTORE_HOST" != 'localhost' && "$RESTORE_HOST" != '::1' ]]; then
  echo "[WanasahRestore] Refusing non-loopback restore target" >&2; exit 2
fi
for bin in pg_restore psql createdb dropdb; do
  command -v "$bin" >/dev/null || { echo "[WanasahRestore] Missing $bin" >&2; exit 2; }
done
if [[ -n "${RESTORE_PASSWORD:-}" ]]; then export PGPASSWORD="$RESTORE_PASSWORD"; fi
export PGAPPNAME=wanasah-restore-verify
db="wanasah_restore_verify_${RANDOM}_$$"
created=0
cleanup() {
  local result=$?
  trap - EXIT
  if (( created )); then
    if ! dropdb --if-exists --host="$RESTORE_HOST" --port="$RESTORE_PORT" \
       --username="$RESTORE_USER" "$db" >/dev/null; then
      echo "[WanasahRestore] FAILED TO DROP DISPOSABLE DATABASE $db" >&2
      result=1
    fi
  fi
  exit "$result"
}
trap cleanup EXIT
pg_restore --list "$archive" >/dev/null
createdb --host="$RESTORE_HOST" --port="$RESTORE_PORT" --username="$RESTORE_USER" "$db"
created=1
pg_restore --host="$RESTORE_HOST" --port="$RESTORE_PORT" \
  --username="$RESTORE_USER" --dbname="$db" --no-owner \
  --no-privileges --single-transaction --exit-on-error "$archive"

# Optional explicit fixture proof; never interpolate arbitrary identifiers.
if [[ -n "${RESTORE_EXPECTED_TABLE:-}" ]]; then
  if [[ ! "$RESTORE_EXPECTED_TABLE" =~ ^[a-z_][a-z0-9_]*$ ]]; then
    echo "[WanasahRestore] Invalid expected table name" >&2; exit 2
  fi
  count="$(psql -X -At --host="$RESTORE_HOST" --port="$RESTORE_PORT" \
    --username="$RESTORE_USER" --dbname="$db" \
    -c "SELECT count(*) FROM public.$RESTORE_EXPECTED_TABLE")"
  if [[ -n "${RESTORE_EXPECTED_ROWS:-}" && "$count" != "$RESTORE_EXPECTED_ROWS" ]]; then
    echo "[WanasahRestore] Row-count mismatch: $count" >&2; exit 1
  fi
  echo "[WanasahRestore] Verified table $RESTORE_EXPECTED_TABLE rows=$count"
fi
dropdb --host="$RESTORE_HOST" --port="$RESTORE_PORT" \
  --username="$RESTORE_USER" "$db" >/dev/null
created=0
trap - EXIT
echo "[WanasahRestore] FULL_RESTORE_GATE=PASS (new disposable DB; no live DB replaced)"
