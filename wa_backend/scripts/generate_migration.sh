#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Wanasah — Alembic Migration Generation Script
# ═══════════════════════════════════════════════════════════════════════════════
# Usage:  cd wa_backend && ./scripts/generate_migration.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

LOG_TAG="[AlembicMigration]"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WA_BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | Starting migration generation..."

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

# ═══ 4. Generate the autogenerate migration ═══
MIGRATION_MSG="Phase 1: Core DB schema hardening (constraints, precision, nullability)"

echo "${LOG_TAG} Running: alembic revision --autogenerate -m \"${MIGRATION_MSG}\""

if alembic revision --autogenerate -m "${MIGRATION_MSG}" 2>&1; then
    echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | ✓ Migration generated successfully."
    echo "${LOG_TAG} Review the new migration file in: ${WA_BACKEND_DIR}/alembic/versions/"
    exit 0
else
    echo "${LOG_TAG} $(date '+%Y-%m-%d %H:%M:%S') | ✗ Migration generation FAILED. Review the error output above." >&2
    exit 1
fi