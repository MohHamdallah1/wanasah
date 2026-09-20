from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
BACKEND_SCHEMA = ROOT / "schemas.py"
BACKEND_DRIVER = ROOT / "api" / "driver.py"
FRONTEND_SYNC = REPO_ROOT / "wanasah_frontend" / "lib" / "repositories" / "sync_repository.dart"
FRONTEND_DB = REPO_ROOT / "wanasah_frontend" / "lib" / "core" / "db" / "local_database.dart"
PUBSPEC = REPO_ROOT / "wanasah_frontend" / "pubspec.yaml"


def main() -> None:
    checks = 0
    failures: list[str] = []

    schema = BACKEND_SCHEMA.read_text(encoding="utf-8")
    driver = BACKEND_DRIVER.read_text(encoding="utf-8")
    sync = FRONTEND_SYNC.read_text(encoding="utf-8")
    local_db = FRONTEND_DB.read_text(encoding="utf-8")
    pubspec = PUBSPEC.read_text(encoding="utf-8")

    checks += 1
    if (
        "class VisitUpdateRequest" not in schema
        or "request_id: UUID" not in schema
    ):
        failures.append("VISIT_REQUEST_ID_SCHEMA_MISSING")

    checks += 1
    update_start = driver.find("async def update_visit(")
    update_end = driver.find("\n@router.", update_start + 1)
    update_block = driver[
        update_start:update_end if update_end >= 0 else len(driver)
    ]
    if (
        "begin_idempotent_operation(" not in update_block
        or "complete_idempotent_operation(" not in update_block
        or "request_id=str(payload.request_id)" not in update_block
    ):
        failures.append("VISIT_OPERATION_IDEMPOTENCY_INCOMPLETE")

    checks += 1
    if "uuid: ^4.5.1" not in pubspec:
        failures.append("FLUTTER_UUID_DEPENDENCY_MISSING")

    checks += 1
    if (
        "safePayload['request_id'] ??= _uuid.v4();" not in sync
        or "updatePendingSyncPayload(" not in sync
        or "payload['request_id'] = _uuid.v4();" not in sync
    ):
        failures.append("FLUTTER_DURABLE_REQUEST_ID_MISSING")

    checks += 1
    if "X-Idempotency-Key" in sync:
        failures.append("LEGACY_VISIT_IDEMPOTENCY_HEADER_STILL_USED")

    checks += 1
    if "Future<void> updatePendingSyncPayload(" not in local_db:
        failures.append("PENDING_REQUEST_ID_PERSISTENCE_MISSING")

    checks += 1
    persist_pos = sync.find("await _db.updatePendingSyncPayload(")
    dispatch_pos = sync.find(
        "await _dispatchPendingRecord(type: type, payload: payload);",
        persist_pos if persist_pos >= 0 else 0,
    )
    if persist_pos < 0 or dispatch_pos < 0 or persist_pos > dispatch_pos:
        failures.append("REQUEST_ID_NOT_PERSISTED_BEFORE_NETWORK_RETRY")

    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL:{failure}")
    if failures:
        raise SystemExit(1)
    print("MUTATION_IDEMPOTENCY_CONTRACT_GATE=PASS")


if __name__ == "__main__":
    main()
