from __future__ import annotations

from pathlib import Path
import base64
import hashlib
import zlib

ROOT = Path(__file__).resolve().parent
INV = ROOT / "dashboard" / "src" / "pages" / "inventory"
TRANSFERS = INV / "transfers"

BASELINE_BLOB_SHAS = {'TabTransfers.tsx': '2b882e189514a6b354f2ddd27db0f1b398d4d637', 'transfers/types.ts': '664c00d2420b6c545014ce29b63da37e7b119733', 'transfers/constants.ts': '9b4ad0ad6f647261930b2966b04b66437d2c09e1', 'transfers/parsers.ts': '1a75ca3f8a851bfe8258a567e7525651e23d88e0', 'transfers/utils.ts': 'e1e27e0d4ac6c6df6c179531c391e3f80aca27c8', 'transfers/TransferTable.tsx': '1e8a131346f1501bbc802d72825f119bae950067', 'transfers/TransferDetailModal.tsx': '1c5187b460f5cb10f26972e734728f5f037e616a', 'transfers/TransferDecisionModal.tsx': '634d526c5122f5a46bfec838ae7d24e72a2276ed', 'transfers/hooks/useTransferList.ts': '2b35d2f8895218db8ebdf9cea19a623085327340', 'transfers/hooks/useTransferActions.ts': '47b7cb87c07c819503bd25edc9a62586b988ef36'}
PAYLOADS = {'TabTransfers.tsx': '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', 'hooks/useTransferCreate.ts': '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', 'TransferCreateModal.tsx': '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', 'FefoOverrideEditor.tsx': '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'}


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def normalize_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    return raw.replace(b"\r\n", b"\n")


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def decode(name: str) -> str:
    return zlib.decompress(
        base64.b64decode(PAYLOADS[name])
    ).decode("utf-8")


# 1) Verify the exact dev-mainInv2/B1 baseline BEFORE writing anything.
for relative, expected_sha in BASELINE_BLOB_SHAS.items():
    path = INV / relative
    if not path.exists():
        fail(f"Baseline file missing: {relative}")

    actual_sha = git_blob_sha(normalize_bytes(path))
    if actual_sha != expected_sha:
        fail(
            f"Baseline mismatch for {relative}: "
            f"expected {expected_sha}, got {actual_sha}. "
            "No files were changed."
        )

# 2) Refuse to overwrite unrelated pre-existing B2 files.
targets = {
    INV / "TabTransfers.tsx": decode("TabTransfers.tsx"),
    TRANSFERS / "hooks" / "useTransferCreate.ts":
        decode("hooks/useTransferCreate.ts"),
    TRANSFERS / "TransferCreateModal.tsx":
        decode("TransferCreateModal.tsx"),
    TRANSFERS / "FefoOverrideEditor.tsx":
        decode("FefoOverrideEditor.tsx"),
}

for path, expected in targets.items():
    if path == INV / "TabTransfers.tsx":
        continue
    if path.exists():
        current = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if current != expected:
            fail(
                f"Refusing to overwrite existing different file: "
                f"{path.relative_to(ROOT)}. No files were changed."
            )

# 3) Static behavior-preservation checks in memory.
tab = targets[INV / "TabTransfers.tsx"]
hook = targets[TRANSFERS / "hooks" / "useTransferCreate.ts"]
modal = targets[TRANSFERS / "TransferCreateModal.tsx"]
fefo = targets[TRANSFERS / "FefoOverrideEditor.tsx"]
combined = "\n".join((tab, hook, modal, fefo))

checks = {
    "ORCHESTRATOR_SMALL": len(tab.splitlines()) < 260,
    "CREATE_HOOK_EXTRACTED": "export function useTransferCreate" in hook,
    "CREATE_MODAL_EXTRACTED": "export function TransferCreateModal" in modal,
    "FEFO_EDITOR_EXTRACTED": "export function FefoOverrideEditor" in fefo,
    "CREATE_ENDPOINT_LOCATIONS": "/warehouse/unified/transfer/locations?" in hook,
    "CREATE_ENDPOINT_SOURCE": "/warehouse/unified/transfer/source-inventory?" in hook,
    "CREATE_ENDPOINT_OVERRIDE": "/warehouse/unified/transfer/override-options?" in hook,
    "CREATE_ENDPOINT_DISPATCH": '"/warehouse/unified/transfer/dispatch"' in hook,
    "SOURCE_LOCATION_ID": "location_id: String(sourceLocationId)" in hook,
    "OVERRIDE_PRODUCT_ID": "product_variant_id: String(productId)" in hook,
    "DISPATCH_SOURCE_DESTINATION": (
        "source_location_id: sourceLocationId" in hook
        and "destination_location_id: destinationLocationId" in hook
    ),
    "DISPATCH_IDEMPOTENCY": "request_id: createRequestId" in hook,
    "AUTO_FEFO": "is_fefo_override: false" in hook,
    "OVERRIDE_FEFO": (
        "is_fefo_override: true" in hook
        and "override_batch_id: item.override_batch_id" in hook
        and "override_reason_id: item.override_reason_id" in hook
    ),
    "NO_MIXED_FEFO": (
        "لا يجوز خلط FEFO التلقائي وتجاوز FEFO لنفس الصنف." in hook
    ),
    "MULTI_BATCH_OVERRIDE": "addOverrideBatchLine" in hook and "addOverrideBatchLine" in modal,
    "SOURCE_CURSOR": (
        'params.set("cursor", pageCursor)' in hook
        and "sourceProductsNextCursor" in hook
        and "loadMoreSourceProducts" in hook
    ),
    "LOCATION_SEARCH": (
        "transferLocationSearchInput" in hook
        and 'params.set("search", transferLocationSearch)' in hook
    ),
    "RACE_GUARDS": (
        "transferLocationsRequestSeq.current" in hook
        and "sourceProductsRequestSeq.current" in hook
        and "overrideRequestSeq.current" in hook
    ),
    "REQUEST_ID_RESETS": hook.count("resetCreateRequestId();") >= 8,
    "SAFE_RETRY": (
        "setCreateRequestId(crypto.randomUUID())" not in
        hook.split("catch (error: unknown) {")[-1].split("finally")[0]
    ),
    "INVENTORY_REFRESH": (
        "onCompleted();" in hook
        and "await onInventoryChanged();" in hook
    ),
    "NO_COMPANY_ID": "company_id" not in combined,
    "NO_EXPLICIT_ANY": ": any" not in combined and "any[]" not in combined,
    "LIST_HOOK_PRESERVED": "useTransferList(locationId)" in tab,
    "ACTION_HOOK_PRESERVED": "useTransferActions({" in tab,
    "DETAIL_MODAL_PRESERVED": "<TransferDetailModal" in tab,
    "DECISION_MODAL_PRESERVED": "<TransferDecisionModal" in tab,
    "TABLE_PRESERVED": "<TransferTable" in tab,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(
        "In-memory behavior gate failed before writes: "
        + ", ".join(failed)
    )

# 4) Write new files first, orchestrator last. Re-run is safe.
(TRANSFERS / "hooks").mkdir(parents=True, exist_ok=True)
TRANSFERS.mkdir(parents=True, exist_ok=True)

for path in (
    TRANSFERS / "hooks" / "useTransferCreate.ts",
    TRANSFERS / "TransferCreateModal.tsx",
    TRANSFERS / "FefoOverrideEditor.tsx",
):
    expected = targets[path]
    if path.exists():
        print(f"UNCHANGED={path.name}")
    else:
        path.write_text(expected, encoding="utf-8")
        print(f"CREATED={path.name}")

(INV / "TabTransfers.tsx").write_text(
    targets[INV / "TabTransfers.tsx"],
    encoding="utf-8",
)
print("PATCHED=TabTransfers.tsx")

# 5) Post-write structural gate.
written_tab = (INV / "TabTransfers.tsx").read_text(
    encoding="utf-8"
).replace("\r\n", "\n")
written_hook = (
    TRANSFERS / "hooks" / "useTransferCreate.ts"
).read_text(encoding="utf-8").replace("\r\n", "\n")

post_checks = {
    "TAB_IS_ORCHESTRATOR": (
        "useTransferCreate({" in written_tab
        and "<TransferCreateModal" in written_tab
        and "authenticatedFetch" not in written_tab
        and "createRequestId" not in written_tab
        and "overrideOptionsByProduct" not in written_tab
    ),
    "CREATE_LOGIC_OUTSIDE_TAB": (
        "authenticatedFetch" in written_hook
        and "createRequestId" in written_hook
        and "overrideOptionsByProduct" in written_hook
    ),
}
post_failed = [name for name, ok in post_checks.items() if not ok]
if post_failed:
    fail(
        "Post-write structural gate failed: "
        + ", ".join(post_failed)
    )

print("TRANSFER_CREATE_STATE_EXTRACTED=OK")
print("TRANSFER_CREATE_API_WORKFLOW_EXTRACTED=OK")
print("TRANSFER_FEFO_WORKFLOW_EXTRACTED=OK")
print("TRANSFER_CREATE_UI_EXTRACTED=OK")
print("TRANSFER_FEFO_UI_EXTRACTED=OK")
print("TRANSFER_CREATE_IDEMPOTENCY_PRESERVED=OK")
print("TRANSFER_CREATE_LOCATION_SCOPE_PRESERVED=OK")
print("TRANSFER_CREATE_SCALABILITY_PRESERVED=OK")
print("TRANSFER_TAB_ORCHESTRATOR=OK")
print("TRANSFER_MODULARIZE_PHASE_B2=OK")
