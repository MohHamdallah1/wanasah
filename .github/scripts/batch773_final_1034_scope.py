"""Exact LEAD integration of Worker1 #773 on latest MAIN with owner CI."""
BATCH773_FINAL_1034_FILES = frozenset({
    ".github/workflows/inventory-cp2-batch-index-acceptance.yml",
    "V1_SCOPE_FREEZE.md",
    "dashboard/src/pages/inventory/batches/BatchDispositionManager.tsx",
    "dashboard/src/pages/inventory/batches/BatchMetadataCorrectionPanel.tsx",
    "dashboard/src/test/batch-773-metadata-correction.test.tsx",
    "docs/operations/BATCH_773_POSTED_METADATA_CORRECTION_ACCEPTANCE.md",
    "wa_backend/alembic/versions/b77c4e2a1073_posted_single_receipt_metadata_correction.py",
    "wa_backend/api/warehouse/__init__.py",
    "wa_backend/api/warehouse/batch_metadata_correction.py",
    "wa_backend/domains/inventory_batch_metadata/__init__.py",
    "wa_backend/domains/inventory_batch_metadata/models.py",
    "wa_backend/domains/inventory_batch_metadata/service.py",
    "wa_backend/models.py",
    "wa_backend/tests/test_batch_773_posted_metadata_pg16.py",
    ".github/scripts/batch773_final_1034_scope.py",
    ".github/workflows/inventory-ledger-817-acceptance.yml",
    ".github/workflows/dispatch-p0-route-stock-safety.yml",
})
def batch773_final_1034_mode(paths):
    return set(paths)==BATCH773_FINAL_1034_FILES
def selftest():
    s=BATCH773_FINAL_1034_FILES
    assert len(s)==17
    assert batch773_final_1034_mode(s)
    for missing in s:
        assert not batch773_final_1034_mode(s-{missing}), missing
    for foreign in (
        "wa_backend/services.py",
        "dashboard/src/pages/inventory/Tab4Ledger.tsx",
        "dashboard/src/pages/DispatchBoard.tsx",
        "wanasah_frontend/lib/main.dart",
    ):
        assert not batch773_final_1034_mode(s|{foreign}), foreign
    print("BATCH773_FINAL_1034_SCOPE=PASS exact=17 partial=17 foreign=4")
if __name__=="__main__":
    selftest()
