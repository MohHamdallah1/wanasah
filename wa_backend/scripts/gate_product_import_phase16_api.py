from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[1]
REPO = ROOT.parent


def read(
    relative: str,
) -> str:
    return (
        REPO
        / relative
    ).read_text(
        encoding="utf-8"
    )


router = read(
    "wa_backend/domains/simple_products/imports/api/router.py"
)
schemas = read(
    "wa_backend/domains/simple_products/imports/api/schemas.py"
)
service = read(
    "wa_backend/domains/simple_products/imports/application/api_service.py"
)
tests = read(
    "wa_backend/tests/test_product_import_phase16_api.py"
)

checks: list[
    tuple[str, bool]
] = []


def check(
    label: str,
    condition: bool,
) -> None:
    checks.append(
        (
            label,
            bool(
                condition
            ),
        )
    )


check(
    "router owns no Pydantic mapping validator",
    "field_validator" not in router
    and "CANONICAL_IMPORT_FIELDS"
    not in router
    and "class ImportMappingRequest"
    not in router,
)
check(
    "mapping authority lives in application layer",
    "def validate_import_mapping("
    in service
    and "PRODUCT_IMPORT_MAPPING_INVALID"
    in service
    and "PRODUCT_IMPORT_MAPPING_NAME_REQUIRED"
    in service
    and "PRODUCT_IMPORT_MAPPING_PRICE_REQUIRED"
    in service,
)
check(
    "HTTP router no longer shapes Product Import ORM rows",
    "ProductImportRow"
    not in router
    and "count_job_progress"
    not in router
    and "def _job_payload("
    not in router,
)
check(
    "status and error ORM work is application-owned",
    "async def read_import_status("
    in service
    and "async def read_import_errors("
    in service
    and "ProductImportRow.company_id"
    in service,
)
check(
    "tenant-scoped job lookup is company-prefixed",
    "ProductImportJob.company_id"
    in service
    and "ProductImportJob.id"
    in service
    and "PRODUCT_IMPORT_NOT_FOUND"
    in service,
)
check(
    "correction upload checks tenant scope before reading file",
    router.index(
        "await ensure_import_job_access("
    )
    < router.index(
        ") = await _parse_correction_upload("
    ),
)
check(
    "explicit DTOs cover stable Product Import response contracts",
    all(
        name
        in schemas
        for name in (
            "class ImportCreateResponse",
            "class ImportStatusResponse",
            "class ImportErrorsResponse",
            "class ImportActionResponse",
            "class ImportCorrectionDownloadResponse",
            "class ImportCorrectionUploadResponse",
            "class ImportTemplateResponse",
        )
    ),
)
check(
    "HTTP endpoints declare response models",
    all(
        token
        in router
        for token in (
            "response_model=ImportTemplateResponse",
            "response_model=ImportCreateResponse",
            "response_model=ImportStatusResponse",
            "response_model=ImportErrorsResponse",
            "ImportCorrectionDownloadResponse",
            "ImportCorrectionUploadResponse",
            "response_model=ImportActionResponse",
        )
    ),
)
check(
    "response shaping never returns ORM objects directly",
    "return job"
    not in router
    and "return row"
    not in router
    and ".model_validate("
    in router,
)
check(
    "integrated API lifecycle tests cover required endpoints",
    all(
        name
        in tests
        for name in (
            "test_template_contract",
            "test_create_upload_contract",
            "test_status_contract",
            "test_errors_contract",
            "test_mapping_contract",
            "test_retry_contract",
            "test_correction_download_contract",
            "test_correction_upload_contract",
            "test_cancel_contract",
        )
    ),
)
check(
    "negative tenant isolation covers job errors correction and cancel",
    all(
        name
        in tests
        for name in (
            "test_company_a_cannot_read_company_b_job",
            "test_company_a_cannot_read_company_b_errors",
            "test_company_a_cannot_download_company_b_correction",
            "test_company_a_cannot_cancel_company_b_job",
            "test_company_a_cannot_map_company_b_job",
            "test_company_a_cannot_retry_company_b_job",
            "test_company_a_cannot_read_company_b_lineage",
            "test_company_a_correction_upload_fails_before_file_read",
        )
    ),
)

tree = ast.parse(
    router
)
mapping_function = next(
    node
    for node in tree.body
    if isinstance(
        node,
        ast.AsyncFunctionDef,
    )
    and node.name
    == "set_product_import_mapping"
)
mapping_source = ast.get_source_segment(
    router,
    mapping_function,
) or ""
check(
    "mapping endpoint is transport-only",
    "detected_headers"
    not in mapping_source
    and "_CANONICAL_MAPPING_FIELDS"
    not in mapping_source
    and "set_import_mapping("
    in mapping_source,
)

failures = [
    label
    for label, passed
    in checks
    if not passed
]
for label, passed in checks:
    print(
        (
            "[PASS] "
            if passed
            else "[FAIL] "
        )
        + label
    )

print(
    f"CHECKS={len(checks)}"
)
print(
    f"FAILURES={len(failures)}"
)
if failures:
    for label in failures:
        print(
            "FAILED_CHECK="
            + label
        )
    print(
        "PRODUCT_IMPORT_PHASE16_API_GATE=FAIL"
    )
    raise SystemExit(
        1
    )

print(
    "PRODUCT_IMPORT_PHASE16_API_GATE=PASS"
)
