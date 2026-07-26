#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Wanasah — Production Database Backup & Retention Script
# ═══════════════════════════════════════════════════════════════════════════════
# Usage:  ./backup_db.sh
# Cron:   0 2 * * * /opt/wanasah/wa_backend/scripts/backup_db.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ═══ 1. Configuration (environment with safe defaults) ═══
: "${POSTGRES_DB:=wanasah}"
: "${POSTGRES_USER:=wanasah_admin}"
: "${POSTGRES_PASSWORD:=}"
: "${POSTGRES_HOST:=localhost}"
: "${POSTGRES_PORT:=5432}"
: "${BACKUP_DIR:=/var/backups/wanasah}"
: "${RETENTION_DAYS:=30}"

# ═══ 2. Ensure backup directory exists ═══
mkdir -p "$BACKUP_DIR"

# ═══ 3. Generate ISO timestamped filename ═══
TIMESTAMP=$(date +'%Y%m%d_%H%M%S')
BACKUP_FILE="${BACKUP_DIR}/wanasah_backup_${TIMESTAMP}.sql.gz"
LOG_TAG="[WanasahBackup]"

echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | Starting database backup for '${POSTGRES_DB}'..."

# ═══ 4. Execute pg_dump with compression ═══
START_EPOCH=$(date +%s)

export PGPASSWORD="${POSTGRES_PASSWORD}"

if pg_dump \
    --host="${POSTGRES_HOST}" \
    --port="${POSTGRES_PORT}" \
    --username="${POSTGRES_USER}" \
    --dbname="${POSTGRES_DB}" \
    --format=custom \
    --compress=9 \
    --verbose \
    2>&1 | gzip > "${BACKUP_FILE}"; then

    END_EPOCH=$(date +%s)
    DURATION=$((END_EPOCH - START_EPOCH))
    FILE_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)

    echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | ✓ Backup completed successfully."
    echo "${LOG_TAG} File: ${BACKUP_FILE}"
    echo "${LOG_TAG} Size: ${FILE_SIZE}"
    echo "${LOG_TAG} Duration: ${DURATION} seconds"
else
    echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | ✗ Backup FAILED for database '${POSTGRES_DB}'." >&2
    exit 1
fi

# ═══ 5. Retention cleanup — delete backups older than RETENTION_DAYS ═══
echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | Running retention cleanup (>${RETENTION_DAYS} days)..."

DELETED_COUNT=$(find "$BACKUP_DIR" -name "wanasah_backup_*.sql.gz" -type f -mtime +"${RETENTION_DAYS}" -print -delete | wc -l)

echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | Cleanup finished. Deleted ${DELETED_COUNT} old backup file(s)."
echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | === Backup & retention job completed. ==="

unset PGPASSWORD