from __future__ import annotations

from pathlib import Path
import base64
import hashlib
import zlib

ROOT = Path(__file__).resolve().parent
INV = ROOT / "dashboard" / "src" / "pages" / "inventory"
TAB = INV / "TabTransfers.tsx"
TRANSFERS = INV / "transfers"
HOOKS = TRANSFERS / "hooks"

EXPECTED_TAB_SHA256 = '5fbf45b5fffcecd073c35aa3b7a7b741a0e6448fe2ffac26ef8a744980c049db'
PAYLOADS = {'TabTransfers.tsx': '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', 'hooks/useTransferList.ts': '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', 'hooks/useTransferActions.ts': 'eNrNV19P40YQf8+nGKzq5EhRgvoYLqgIWom290cE1IcT4hZ7k7g469Rew0Xgh0NQEN+iqiooulNLTy1qP4n9bTr2eu1d2wHRpyIBu7Mzs/P3N15nOvN8DscQBnSduO4+sQ466WbICacQwcj3pmD4lFjcWGk5kp17JODFceAxRn31HDWshXzyFeXWpGD7ojfxvIOgpx6WQnw+o3DcAtj2CQtG1F+zuOOxDlK+Iz6deCgmj751Ar7J6bTTkrq73V6qIFCNGFP+pe97/gsaBGRMOynhRYiOodqcBop8yB03lW85jFN/RCwKO+WVwppgzR8HmZWuZ2WKNu0+sHC6T/0VpOKeHVLGPX++PiFsTPHUbMNgFQ49x4YTeI23OQF9nm5XhcS6N525lOusK62o1aLvMk9GIcsuh7Bmjqmb0mk0oaNfg0HrL/Csnblm4Y4DwRShGgd1U1skcqDl1WxjrCT3GyKyBQHlQuGuYM8K6bl+F8aBha67aqZ/2ytVJZJZUSZJqBS5oVS8sDQW3mFTywlQ5RYlQW7whkZSDTcNo27fFv0hpHiLrRhY0DTpLJ+ZwZY/n3Gvi0ba3nRnZ3PDbCO9rnsY7k8dzh02VpSXRE37iLgBVZPgzSjLIzxQO9rMTBB/AXgeqf5DfSVYGX2Xm9CvtGXGkFXrcc7rjMCUqrsBGhgGsDQYgLH5cm97a+3lcHPbaBfcICCkS9MGNY3kIv49uYD4OjmL/07Ok7PkKv4VkvP4Nr6OP6bL98lpfA94cBZ/TC4zxuv4NpNA/sv4A/7+JhivhJ77+C65Sk67IoPix6c89JncR618IcLnBEMv9LHtB1A6klH2ZIvtYRMP0Kmy5VYqKjawChxGRBJKZ6U+uzx+UKkS1DIJGZdhEWZR14Bnz2BJmrwwsFkkfsHffzBcPxURxUXyI2DQLkSY/8TY3YmwyejKmD8Yv9LKgqVmr08t6hxSA05OoH72PcXJ0kZnCgVLWhBz8sMOXsef4tv0f3Leywh3yfv4r7J+rtFZzePLfPF0j/NFDZmK2i9kCxYlIuqhjjoSaTTJAlXMBvzI2SPRrG/K6tkVyFLAguV6CNtNuGAqHZwmsYpBbc19xSGJqU2B0A+bvYw6dcDbVW0OZzZCnC5cNf6QuCHtQ8D9zNTCk/qtGWfV4MeDm1qpWYXz1HabQ0mCObOgGtAlkg+8E1jSh1sZ2lYJH770Ux9SXfRwaub2p2rzRGk9lN5B6jDRznBCKC6bSG+hT/FNfCOg9DS+w465S1vnHreX8Y3SDWoxRIUxQnfXpWzMJ7AKny8vLz/lJmxbQLhPAfwPiH9OW/UK+/YDcqWUVB1gD2NLLzRFT2xZUtiUYT4hUwyeF1bhhxD45KgPITtg3hHTAJc0gJeKPyiIKSJHxGn6SiqREMDoHckR2wuZM3Ko3ZM40ZOqO4rAsbIGmFI+8fCz0Hj9arit8QHse/a8D18PX73sigZwRnNTF0+jlJU4Dpg+VL9dKqzSrL0JJTb+K0VkxXadmtCCadavsEFV0wI5XX3UVvdRsS5qIAKKH0D/KTFvH0rMZ8c1x6OCGL39f+RLIsSeaL9+jh1PDWFLa9MgtCx8GJn1h5KJsW03jbYS7B+ZBY/MPOWBYhZEkcr6i0ZyRIDpxYeJmeFL0c1ls/Z68A2lM8BagIBMqRJhGHk+EHxUMUsoRYZRyoA40W0Ar8prUlxZDGEYYT27bokwTWgkP9hlMtL50irbo6OsK3mvPIwErVbhgl554LQq0ZWEpldiPuwEuOau1G3TzWi6rvaWEXcWzxOxV75LBKFp6IsTdfCmlCh9H/8LXhCiTA==', 'TransferTable.tsx': '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', 'TransferDetailModal.tsx': 'eNrVWE9v2zYUv/tTsMJQ2EBkO2myDY7trVjbW9cBzdBDELi0SMdEJVKjqMSGY2Dtki7IbcC+wA5b2qxBkGUB1m8iXfdJ9ijJsWzJSZ0lxXaxaOr9/b3H9x7FHFdIhQbosSDYRkPUkcJBxpcVS8AbTrnyKj6rOPqtsVpgI/Kna/fXvn3aevxw7f4FUxmYuKcw8IxJVd+lQP8MS9oVvkfXJOZeh8oHVGFmp3g1oZdW0RHSweoBVjRF5Stma6oC44rKDrYompQY+fGNFK6HBgWESLRZm6l/B3HftleB0haYML5ZQ20hbIq53hP8K1t4tIaKJdRooi3ByGphWCjQXmRjx+eWYoLnmVAca18YS18YC10oDGszbS9FxkuqfMlREZYI1aO30RIh5j1xKW8MYgXoTqMR+YF2dkaahglloq0xSBajfcWUTRtGcBS+DA6D8/Ag3EXBYbgbHIf70fOtkVA6uPeMEdVtGLAyt82Vnh2/aiYEg0Qluns3sTWyl7AtZNnY877GDmhyzcUlpGhPmRbVsYvXng3xNVeqVQg3V2Zb2MRoXshAKHgH1p2GB7AAm97EJqZsLpfLY40VUDliLkGYEvPupOxLALvUUs+FtDL75sqEJdNUm5IRpH9MS9ieuYQcUhv/XUab2DXvTUjIypDC54QSs2ej9uYFFijLmGWN0FtfrLq9jTSSy9Wq0dQghXvBKYD3fgKUWcIusE+L+lyLmmIENGMEyyrJ3LKk8Eu5RVvcd9pUDqd1ZQ3I2/qoyJwHJ8HprSPjCV8CLLawsK4SLQ4S//vo7MNJ+zF4e+voEOopxmNk/l8QBcdxgbxxiFJNdT2TTAor39so27hN7etAlGykdgbFaSVcKOrpJpINlsU8HSBJsSd4abKAXoW/kATqffxIEFiq6lgsJ6A4GTQG+aZl1Eaq3SyWsAtlnOdGwmiGexC/Q4jjX/B7VKtXNG1zYCBjmCMp35YsZb2SMaQ0LFx5DCaQneVh2hFHmUvGvC4HZ8GbpH+Gr6A1QFed2+8pW6+DQCYtx306L4tmpU4qu8QWzIG22Daxr4QeVsyuub68stXdmG6+Crdtmpa+bXb00JTkYPyUbLOrsiVCdSkmE5aligoUMutFHynhmnnnuq5kbrRUd3I+ujfqT+Hr4Ch4V6+o7jx8wQmMRe91WZqT7zw+DOHB/LzhD2DtnHyPHj56kk8PuxmkNCVAnw1IW5B+WjZkDiMwtqFkEUdn8dJmZDNOvbKD3WJRL6Mhv5jrhkQvaL8x0FRlRoZ5vmoyMuUtmqP8j4ZprcKVgviWyu2HF7iQ+axwBBexFT3vCvVtrKzujHnuGuoTpWkIPr0SArhjMdlvEaC+KQTiShiL/86HeypT/eF1PLnC9A7tiJauS3AdoEmxbDEygwehL9BzfeDhQO0HfyA4UfvB7+FP4asa+iRPoG4/ukkbUNFPwv3wNQKG8/ClMXw+U0UNGfrcIbg76fp/GPwWHhjz4Zp3OqF+l7LDSHQ2p8eRqPpePpBc64qVl10rmeyq54xqF9eks3C3ltcEZ/fTtLLPPnDeZSANjhUlrXZ/xqAbteMPmXRnuHIWhXfv9p2R1KJsa+xKlI5/f/+zccM+Bb9CL/wT0vWXm/dp/H0pMwdbcGYVeIdV6aYdOoJ8O9ZfLj6qQ67w/o0/UxvTH1rivej7lN4t6W9k/wDGDumZ', 'TransferDecisionModal.tsx': 'eNqdVlFv40QQfs+vGCx0SqQ4CTmKTmmc43T3Uuko6K4Sjz3H3jQL9jryrnOpTB6OKy30Bf4CqlB71SGoToDgl9iv/BJm13ayduL2xJN3d2a+mZ35dsbUnwWhgBg+C1zbgyVMwsAH49OuE6CEESZ4N6JdX0qN3QbN1MXxjEDcADgIbcYnJHzkCBqwNp58aYdkGkScFKKnlIs9Qfx2owDvdKU9R7gGZYKEE9shK6QnxKEcsVQ8X4TBjCtHtnIwqDiEb4BFnreLCiIXDOoj0LTd3MszYnMJy0VI2ZGU8GjsUyFwN4BxEHjEZvI4YI+9gJMBNFtgjWAeUDc7flJCejy12ZHUmtteRArcislz5UKHwsjwqj7lZCi3o93GstEgC5XrScSyu27NUHOdnLaWhfbGHdulu7XXV2rXXqOtRYvVG9xSo5YqUkhEFDJo4hJgqKRqCUD55zPCrDiLFD6wLFUKuHdvFfLqcJnb5PFZcb4ozgUVHp7mu+L2YKG5ERKH0DkxVkKAh2Ak18lF+jo9T36D5DJ5l1ynJ8ll+h1ucPFr+r36vtGNBhXUr4gjdHkGe5O+Sv68BUXiGMkvePwP+v25RjO71yjfDV06B8ezOd+3fWIZfIavwzw2PzZGK+SqThhEzCWuufBgfGRyzxbE3OkhfUMX85p98uN+rwcz8z4IshAm9zXQTdhJwIQ5Djw311YAD3q9khFAXFTwYSck+CHMIYcs8sckXOroXYS/zZ1ysuC6sx2M1hfmR/UeeRCF6M4LHFvW65Ah1BL+Pf0pNsBY1lm5hOMryCzKpvUB59vVXufyineS0M3KHcuxDz17TLxt996a7k820g2ADL5KrlYB6BRVtJTsUtQ0FP/kdsXBSk6GXRVOJUTpH5uoXfGrepoVl/vKsqJUNA8rbpI5jg/Z4yoqdf0mM+ig6yMiOspbq2Ja9ebbi6eEHYmpFSOze1WxlmVJI3hpTmTX8Skzp2b/AegPp+6xLPC1zI7NfmcHgkh4lBGT4WDEcjkRH8j2bvb1zRjDlsTt9nvlXtAd1ZOrtdwklnUXsepbAPFJaHvuZhMoBKU2ULy5QohPfE3GCvuSd9hGr7F3pqfpt+kJpK9lJ8VFcoG0/Cu5qTQ5QOEp7O0fHjx7tP987wAkFdMfAOVv0zNEOksuM5OL5A+UnCdvOmWHUiadSkbfQHouAZO/1Tkuf0xuUHqSuant80U46A6SKwz9FRqddd6vHsNxJETAGiWOe9T5Gim+nuDFoGy2dBK6lNtjj7hWvJ69unxdwfhFTk7k2n2dmKo0L6dUEK1DFLiDAMcDFcey0h/GpcTdMRbzGaaRRbaaisLdY3ANE5KtEGoGotiW86CqsHyxTobOMy1bG0P3LZb2Jj2HvKBYSyz4751Opzp53y8BJc5Ivqx587+zUcXMmvG2xFQ1t/XpYTcj4OoPYU3VYVf9ZMlNS/4z/geDXeqH'}


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def decode_payload(key: str) -> str:
    return zlib.decompress(base64.b64decode(PAYLOADS[key])).decode("utf-8")


if not TAB.exists():
    fail("TabTransfers.tsx missing")

current = normalize(TAB.read_text(encoding="utf-8"))
expected_tab = decode_payload("TabTransfers.tsx")

already_done = (
    './transfers/hooks/useTransferList' in current
    and './transfers/hooks/useTransferActions' in current
    and '<TransferTable' in current
    and '<TransferDetailModal' in current
    and '<TransferDecisionModal' in current
)

if already_done:
    if current != expected_tab:
        fail("TabTransfers.tsx is partially modularized but differs from expected B1 output.")
    print("UNCHANGED=TabTransfers.tsx")
elif sha256_text(current) != EXPECTED_TAB_SHA256:
    fail(
        "TabTransfers.tsx differs from the exact Stage-1 baseline. "
        f"Current SHA256={sha256_text(current)}"
    )
else:
    TAB.write_text(expected_tab, encoding="utf-8")
    print("PATCHED=TabTransfers.tsx")

HOOKS.mkdir(parents=True, exist_ok=True)

for rel in (
    "hooks/useTransferList.ts",
    "hooks/useTransferActions.ts",
    "TransferTable.tsx",
    "TransferDetailModal.tsx",
    "TransferDecisionModal.tsx",
):
    target = TRANSFERS / rel
    expected = decode_payload(rel)
    if target.exists():
        existing = normalize(target.read_text(encoding="utf-8"))
        if existing != expected:
            fail(f"{rel} already exists with different content")
        print(f"UNCHANGED={rel}")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(expected, encoding="utf-8")
        print(f"CREATED={rel}")

# Existing Stage-1 domain files must still exist and remain separate.
for rel in ("types.ts", "constants.ts", "parsers.ts", "utils.ts"):
    if not (TRANSFERS / rel).exists():
        fail(f"Stage-1 domain file missing: {rel}")

# Behavior-preservation gate.
tab = normalize(TAB.read_text(encoding="utf-8"))
list_hook = normalize((HOOKS / "useTransferList.ts").read_text(encoding="utf-8"))
actions_hook = normalize((HOOKS / "useTransferActions.ts").read_text(encoding="utf-8"))
table = normalize((TRANSFERS / "TransferTable.tsx").read_text(encoding="utf-8"))
detail_modal = normalize((TRANSFERS / "TransferDetailModal.tsx").read_text(encoding="utf-8"))
decision_modal = normalize((TRANSFERS / "TransferDecisionModal.tsx").read_text(encoding="utf-8"))

checks = {
    "LIST_HOOK_LOCATION_SCOPE": (
        "location_id: String(locationId)" in list_hook
        and "transfer.source_location_id !== locationId" in list_hook
        and "transfer.destination_location_id !== locationId" in list_hook
    ),
    "LIST_HOOK_CURSOR": (
        'params.set("cursor", cursor)' in list_hook
        and "setCursorHistory" in list_hook
        and "setNextCursor" in list_hook
    ),
    "LIST_HOOK_DETAIL_SCOPE": (
        "parseTransferDetail(raw, locationId)" in list_hook
        and "/warehouse/unified/transfers/${transfer.id}" in list_hook
    ),
    "ACTIONS_ROLE_GATES": (
        'transfer.status !== "IN_TRANSIT"' in actions_hook
        and 'nextAction === "cancel" && !isSource' in actions_hook
        and '(nextAction === "receive" || nextAction === "reject")' in actions_hook
    ),
    "ACTIONS_IDEMPOTENCY": (
        "request_id: actionRequestId" in actions_hook
        and "setActionRequestId(crypto.randomUUID())" in actions_hook
    ),
    "ACTIONS_ENDPOINTS": (
        '"/warehouse/unified/transfer/receive"' in actions_hook
        and "/warehouse/unified/transfer/${actionTransfer.id}/${action}" in actions_hook
    ),
    "TABLE_ACTION_VISIBILITY": (
        'transfer.status === "IN_TRANSIT"' in table
        and "isDestination" in table
        and "isSource" in table
    ),
    "DETAIL_PRESENTATION_EXTRACTED": (
        "تفاصيل الحوالة" in detail_modal
        and "fefo_override_reason_id" in detail_modal
    ),
    "DECISION_PRESENTATION_EXTRACTED": (
        "decisionReason" in decision_modal
        and "تأكيد الاستلام" in decision_modal
    ),
    "TAB_ORCHESTRATES_B1": (
        "useTransferList(locationId)" in tab
        and "useTransferActions({" in tab
        and "<TransferTable" in tab
        and "<TransferDetailModal" in tab
        and "<TransferDecisionModal" in tab
    ),
    "TAB_NO_LIST_IMPLEMENTATION": (
        "const fetchTransfers =" not in tab
        and "const openDetail =" not in tab
        and "const handleNext =" not in tab
    ),
    "TAB_NO_ACTION_IMPLEMENTATION": (
        "const openAction =" not in tab
        and "const handleAction =" not in tab
    ),
    "CREATE_ENDPOINT_PRESERVED": (
        '"/warehouse/unified/transfer/dispatch"' in tab
        and "request_id: createRequestId" in tab
        and "source_location_id: sourceLocationId" in tab
        and "destination_location_id: destinationLocationId" in tab
    ),
    "CREATE_LOCATION_READS_PRESERVED": (
        "/warehouse/unified/transfer/locations?" in tab
        and "/warehouse/unified/transfer/source-inventory?" in tab
    ),
    "FEFO_OVERRIDE_PRESERVED": (
        "/warehouse/unified/transfer/override-options?" in tab
        and "is_fefo_override: true" in tab
        and "override_batch_id:" in tab
        and "override_reason_id:" in tab
    ),
    "SOURCE_CURSOR_SCALABILITY_PRESERVED": (
        "sourceProductsNextCursor" in tab
        and 'params.set("cursor", pageCursor)' in tab
        and "تحميل المزيد" in tab
    ),
    "LOCATION_SEARCH_SCALABILITY_PRESERVED": (
        "transferLocationSearchInput" in tab
        and 'params.set("search", transferLocationSearch)' in tab
    ),
    "NO_FRONTEND_COMPANY_ID": (
        "company_id" not in tab
        and "company_id" not in list_hook
        and "company_id" not in actions_hook
    ),
    "NO_EXPLICIT_ANY": all(
        ": any" not in content and "any[]" not in content
        for content in (tab, list_hook, actions_hook, table, detail_modal, decision_modal)
    ),
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"Static verification failed: {failed}")

print("TRANSFER_LIST_DETAIL_WORKFLOW_EXTRACTED=OK")
print("TRANSFER_ACTION_WORKFLOW_EXTRACTED=OK")
print("TRANSFER_LIST_LOCATION_SCOPE_PRESERVED=OK")
print("TRANSFER_ACTION_IDEMPOTENCY_PRESERVED=OK")
print("TRANSFER_CREATE_FEFO_UNTOUCHED=OK")
print("TRANSFER_SCALABILITY_UNTOUCHED=OK")
print("TRANSFER_MODULARIZE_PHASE_B1=OK")
