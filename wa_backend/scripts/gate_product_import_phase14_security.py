from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))


errors = read(
    "wa_backend/domains/simple_products/imports/domain/errors.py"
)
router = read(
    "wa_backend/domains/simple_products/imports/api/router.py"
)
queue = read(
    "wa_backend/domains/simple_products/imports/infrastructure/queue.py"
)
correction = read(
    "wa_backend/domains/simple_products/imports/application/correction_service.py"
)
content_security = read(
    "wa_backend/domains/simple_products/imports/infrastructure/content_security.py"
)
parsers = read(
    "wa_backend/domains/simple_products/imports/infrastructure/parsers.py"
)
tests = read(
    "wa_backend/tests/test_product_import_phase14_security.py"
)

check(
    "stable user-safe Product Import error taxonomy exists",
    "USER_SAFE_ERROR_MESSAGES" in errors
    and "PRODUCT_IMPORT_SYSTEM_FAILURE" in errors
    and "PRODUCT_IMPORT_SOURCE_TYPE_MISMATCH" in errors
)
check(
    "runtime failure summary never persists technical exception text",
    '"technical"' not in errors[errors.index("def runtime_failure_summary"):],
)
check(
    "legacy job summaries are public-whitelisted",
    "def public_error_summary" in errors
    and "public_error_summary(" in router
    and "dict(\n            job.error_summary" not in router,
)
check(
    "API never returns raw exception strings",
    "str(exc)" not in router
    and "_log_api_exception" in router
    and "correlation_id" in router,
)
check(
    "worker technical failures are server-logged with correlation id",
    "logger.exception(" in queue
    and "correlation_id=%s" in queue
    and "message=str(exc)" not in queue,
)
check(
    "row diagnostics expose safe code message and actionable field",
    "def import_error_field" in errors
    and "def user_safe_row_error_message" in errors
    and '"field":' in router
    and "row.error_message" not in router,
)
check(
    "CSV and XLSX correction cells are formula-injection sanitized",
    "def sanitize_spreadsheet_cell" in correction
    and "_FORMULA_PREFIXES" in correction
    and "sanitize_spreadsheet_cell(" in correction
    and "user_safe_row_error_message(" in correction,
)
check(
    "client MIME is not Product Import parser authority",
    "file.content_type" not in router
    and "validate_source_content(" in router
    and "validate_source_content(" in parsers,
)
check(
    "content signature rejects mismatched CSV and XLSX payloads",
    "_ZIP_SIGNATURES" in content_security
    and "_REQUIRED_XLSX_MEMBERS" in content_security
    and "PRODUCT_IMPORT_SOURCE_TYPE_MISMATCH" in content_security,
)
check(
    "XLSX zip-bomb entry compression and macro defenses remain active",
    "MAX_XLSX_UNCOMPRESSED_BYTES" in content_security
    and "MAX_XLSX_ARCHIVE_ENTRIES" in content_security
    and "MAX_XLSX_COMPRESSION_RATIO" in content_security
    and "vbaproject.bin" in content_security.lower()
    and "MAX_XLSX_COMPRESSION_RATIO" in parsers
    and "vbaproject.bin" in parsers.lower(),
)
check(
    "adversarial malformed and spreadsheet-injection tests exist",
    "test_binary_payload_disguised_as_csv_is_rejected" in tests
    and "test_nul_containing_csv_is_rejected" in tests
    and "test_malformed_xlsx_is_rejected_before_workbook_traversal" in tests
    and "test_macro_payload_is_rejected" in tests
    and "test_high_compression_ratio_xlsx_is_rejected" in tests
    and "test_correction_artifact_sanitizes_headers_source_and_error_cells" in tests
)

failures = [label for label, passed in checks if not passed]
for label, passed in checks:
    print(("[PASS] " if passed else "[FAIL] ") + label)

print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failures)}")
if failures:
    for label in failures:
        print("FAILED_CHECK=" + label)
    print("PRODUCT_IMPORT_PHASE14_SECURITY_GATE=FAIL")
    raise SystemExit(1)

print("PRODUCT_IMPORT_PHASE14_SECURITY_GATE=PASS")
