#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Wanasah — Alembic Database Migration Execution Script
# ═══════════════════════════════════════════════════════════════════════════════
# Usage:  cd wa_backend && ./scripts/run_migration.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

LOG_TAG="[AlembicRun]"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WA_BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | Starting database migration..."

# ═══ 1. Verify alembic is available ═══
if ! command -v alembic &> /dev/null; then
    echo "${LOG_TAG} ERROR: 'alembic' command not found. Please install it via pip (pip install alembic)." >&2
    exit 1
fi

# ═══ 2. Change to backend directory ═══
cd "$WA_BACKEND_DIR"

# ═══ 3. Check for alembic.ini ═══
if [ ! -f "alembic.ini" ]; then
    echo "${LOG_TAG} ERROR: 'alembic.ini' not found in $WA_BACKEND_DIR." >&2
    echo "${LOG_TAG} Please run 'alembic init alembic' first to initialize the Alembic environment." >&2
    exit 1
fi

echo "${LOG_TAG} Using WA_BACKEND_DIR: ${WA_BACKEND_DIR}"

# ═══ 4. Show current migration state before upgrade ═══
echo "${LOG_TAG} Current migration state:"
alembic current 2>&1 || true

# ═══ 5. Run the upgrade ═══
echo "${LOG_TAG} Running: alembic upgrade head"

START_EPOCH=$(date +%s)

if alembic upgrade head 2>&1; then
    END_EPOCH=$(date +%s)
    DURATION=$((END_EPOCH - START_EPOCH))

    echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | ✓ Migration executed successfully."
    echo "${LOG_TAG} Duration: ${DURATION} seconds"
    echo "${LOG_TAG} New migration state:"
    alembic current 2>&1 || true
    exit 0
else
    echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | ✗ Migration execution FAILED. Review the error output above." >&2
    echo "${LOG_TAG} The database may be in an inconsistent state. Restore from backup if needed." >&2
    exit 1
fi