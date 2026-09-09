from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
INV = ROOT / "dashboard" / "src" / "pages" / "inventory"
TRANSFERS = INV / "transfers"

FILES = {
    "tab": INV / "TabTransfers.tsx",
    "create_hook": TRANSFERS / "hooks" / "useTransferCreate.ts",
    "create_modal": TRANSFERS / "TransferCreateModal.tsx",
    "fefo_editor": TRANSFERS / "FefoOverrideEditor.tsx",
    "list_hook": TRANSFERS / "hooks" / "useTransferList.ts",
    "actions_hook": TRANSFERS / "hooks" / "useTransferActions.ts",
    "types": TRANSFERS / "types.ts",
    "parsers": TRANSFERS / "parsers.ts",
}


def fail(label: str) -> None:
    raise SystemExit(f"TRANSFER_B2_GATE=FAIL\n{label}=FAIL")


def require(ok: bool, label: str) -> None:
    if not ok:
        fail(label)
    print(f"{label}=OK")


for name, path in FILES.items():
    require(path.exists(), f"FILE_{name.upper()}")

text = {
    name: path.read_text(encoding="utf-8").replace("\r\n", "\n")
    for name, path in FILES.items()
}

tab = text["tab"]
hook = text["create_hook"]
modal = text["create_modal"]
fefo = text["fefo_editor"]
list_hook = text["list_hook"]
actions = text["actions_hook"]
combined = "\n".join(text.values())

require(len(tab.splitlines()) < 260, "TAB_ORCHESTRATOR_SIZE")
require("authenticatedFetch" not in tab, "TAB_NO_DIRECT_API")
require("createRequestId" not in tab, "TAB_NO_CREATE_STATE")
require("overrideOptionsByProduct" not in tab, "TAB_NO_FEFO_STATE")
require("useTransferList(locationId)" in tab, "TAB_USES_LIST_HOOK")
require("useTransferActions({" in tab, "TAB_USES_ACTIONS_HOOK")
require("useTransferCreate({" in tab, "TAB_USES_CREATE_HOOK")

for endpoint, label in (
    ("/warehouse/unified/transfer/locations?", "CREATE_LOCATIONS_ENDPOINT"),
    ("/warehouse/unified/transfer/source-inventory?", "CREATE_SOURCE_ENDPOINT"),
    ("/warehouse/unified/transfer/override-options?", "CREATE_OVERRIDE_ENDPOINT"),
    ("/warehouse/unified/transfer/dispatch", "CREATE_DISPATCH_ENDPOINT"),
):
    require(endpoint in hook, label)

require("request_id: createRequestId" in hook, "CREATE_REQUEST_ID")
require(
    "source_location_id: sourceLocationId" in hook
    and "destination_location_id: destinationLocationId" in hook,
    "CREATE_LOCATION_IDS",
)
require(
    "is_fefo_override: false" in hook
    and "is_fefo_override: true" in hook,
    "CREATE_FEFO_MODES",
)
require(
    "override_batch_id: item.override_batch_id" in hook
    and "override_reason_id: item.override_reason_id" in hook,
    "CREATE_OVERRIDE_IDS",
)
require(
    "لا يجوز خلط FEFO التلقائي وتجاوز FEFO لنفس الصنف." in hook,
    "CREATE_NO_MIXED_FEFO",
)
require("addOverrideBatchLine" in hook, "CREATE_MULTI_BATCH")
require(
    'params.set("cursor", pageCursor)' in hook
    and "sourceProductsNextCursor" in hook,
    "CREATE_SOURCE_CURSOR",
)
require(
    "transferLocationsRequestSeq.current" in hook
    and "sourceProductsRequestSeq.current" in hook
    and "overrideRequestSeq.current" in hook,
    "CREATE_RACE_GUARDS",
)
require(
    "onCompleted();" in hook
    and "await onInventoryChanged();" in hook,
    "CREATE_REFRESH_CHAIN",
)
require(
    "<FefoOverrideEditor" in modal
    and "onModeChange={setDraftFefoMode}" in modal
    and "onBatchChange={setOverrideBatch}" in modal
    and "onReasonChange={setOverrideReason}" in modal,
    "CREATE_MODAL_FEFO_WIRING",
)
require(
    "options.batches" in fefo
    and "options.reasons" in fefo
    and "firstProductLineKey" in fefo,
    "FEFO_EDITOR_BATCH_REASON_SPLIT",
)

# Existing B1 behavior remains present.
require(
    "location_id: String(locationId)" in list_hook
    and "/warehouse/unified/transfers?" in list_hook,
    "LIST_LOCATION_SCOPE",
)
require(
    "request_id: actionRequestId" in actions
    and "/warehouse/unified/transfer/receive" in actions,
    "ACTIONS_IDEMPOTENCY",
)

require("company_id" not in combined, "FRONTEND_NO_COMPANY_ID")
require(": any" not in combined and "any[]" not in combined, "FRONTEND_NO_EXPLICIT_ANY")

# Guard against accidental duplicate create implementation.
require(
    len(re.findall(r'/warehouse/unified/transfer/dispatch', combined)) == 1,
    "SINGLE_DISPATCH_IMPLEMENTATION",
)
require(
    len(re.findall(r'function useTransferCreate', combined)) == 1,
    "SINGLE_CREATE_CONTROLLER",
)

print("TRANSFER_B2_GATE=PASS")
