from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]

auth = (ROOT / "wa_backend/api/auth.py").read_text(encoding="utf-8")
models = (ROOT / "wa_backend/models.py").read_text(encoding="utf-8")
migration = (
    ROOT
    / "wa_backend/alembic/versions/8b7d2c4e9f61_refresh_token_rotation_concurrency.py"
).read_text(encoding="utf-8")
storage = (
    ROOT / "dashboard/src/lib/authStorage.ts"
).read_text(encoding="utf-8")
hook = (
    ROOT / "dashboard/src/hooks/useAuthFetch.ts"
).read_text(encoding="utf-8")

checks: list[tuple[bool, str]] = []


def check(condition: bool, label: str) -> None:
    checks.append((bool(condition), label))


check(
    "REFRESH_ROTATION_GRACE_SECONDS = 15" in auth,
    "refresh concurrency grace is explicit and bounded",
)
check(
    "replaced_by_id" in models
    and "ondelete='SET NULL'" in models
    and "uq_refresh_tokens_replaced_by_id" in models,
    "refresh token model links exactly one rotation successor",
)
check(
    "replaced_by_id" in migration
    and 'ondelete="SET NULL"' in migration
    and "unique=True" in migration,
    "refresh successor database contract is migrated",
)
check(
    ".with_for_update()" in auth
    and "_recent_rotation_successor" in auth
    and "db_token.replaced_by_id = new_refresh_row.id" in auth,
    "refresh rotation serializes and records its successor atomically",
)
check(
    '{"sub": str(admin.id), "role": "Admin" if admin.is_admin else "Inventory"}'
    in auth
    and '{"sub": str(driver.id), "role": "Driver"}' in auth,
    "new refresh tokens preserve their login surface role",
)
check(
    "readAccessTokenIfRefreshAdvanced" in storage
    and "currentRefresh === attemptedRefreshToken" in storage,
    "dashboard can detect a newer cross-tab session",
)
check(
    "readAccessTokenIfRefreshAdvanced(" in hook
    and "if (advancedAccessToken)" in hook
    and "processQueue(" in hook,
    "stale refresh rejection reuses a newer browser session",
)

failures = [label for ok, label in checks if not ok]
print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failures)}")
for label in failures:
    print(f"FAILED_CHECK={label}")

if failures:
    print("AUTH_SESSION_REFRESH_GATE=FAIL")
    sys.exit(1)

print("AUTH_SESSION_REFRESH_GATE=PASS")
