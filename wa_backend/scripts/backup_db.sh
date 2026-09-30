#!/usr/bin/env bash
# Wanasah: atomic, verifiable PostgreSQL custom-format backup.
# Never write a plaintext SQL dump or remove a verified backup on failure.
set -Eeuo pipefail
umask 077

POSTGRES_DB="${POSTGRES_DB:-wanasah}"
POSTGRES_USER="${POSTGRES_USER:-wanasah_admin}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/wanasah}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

if [[ ! "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || (( RETENTION_DAYS < 1 )); then
  echo "[WanasahBackup] RETENTION_DAYS must be at least 1" >&2
  exit 2
fi
for bin in pg_dump pg_restore; do
  command -v "$bin" >/dev/null || { echo "[WanasahBackup] Missing $bin" >&2; exit 2; }
done

mkdir -p -- "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)_$$"
final="$BACKUP_DIR/wanasah_backup_$stamp.dump"
temp="$(mktemp "$BACKUP_DIR/.wanasah_backup_$stamp.XXXXXXXX")"
cleanup() { rm -f -- "$temp"; }
trap cleanup EXIT

if [[ -n "${POSTGRES_PASSWORD:-}" ]]; then
  export PGPASSWORD="$POSTGRES_PASSWORD"
fi
export PGAPPNAME=wanasah-backup
echo "[WanasahBackup] Starting verified custom-format backup ($POSTGRES_DB)"

# pg_dump -Fc already compresses each data stream; DO NOT gzip it again.
pg_dump --host="$POSTGRES_HOST" --port="$POSTGRES_PORT" \
  --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
  --format=custom --compress=6 --file="$temp"
test -s "$temp"
# This detects a malformed/truncated directory; a FULL restore is separately
# required by scripts/verify_restore_backup.sh.
pg_restore --list "$temp" >/dev/null
test ! -e "$final" || { echo "[WanasahBackup] Backup target collision" >&2; exit 2; }
mv -- "$temp" "$final"
trap - EXIT

# Retain a working backup before applying retention; only manage this script's
# .dump outputs, never legacy .sql.gz or any unrelated backup.
echo "[WanasahBackup] VERIFIED_BACKUP=$final"
echo "[WanasahBackup] SHA256=$(sha256sum "$final" | awk '{print $1}')"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'wanasah_backup_*.dump' \
  -mtime +"$RETENTION_DAYS" -print -delete
echo "[WanasahBackup] BACKUP_ARCHIVE_GATE=PASS; FULL_RESTORE_NOT_YET_VERIFIED"
