# Batch reservation owner evidence

Read-only addition to `GET /warehouse/batches/{batch_id}/stock-sources`.
Every `sources[].statuses[]` keeps its existing stock quantities and gains
`reservation_evidence`. Quantities remain exact canonical decimal strings in
the response's existing `base_uom_id`. No browser summation or new reservation
model is required.

## Response example

```json
{
  "stock_status": "AVAILABLE",
  "on_hand_quantity": "100",
  "reserved_quantity": "3.25",
  "movable_quantity": "96.75",
  "reservation_evidence": {
    "coverage": "COMPLETE",
    "reason": null,
    "unattributed_quantity": "0",
    "owners_truncated": false,
    "owners": [{
      "owner_type": "DISPATCH_HANDSHAKE",
      "module": "DISPATCH",
      "transfer_id": 21,
      "reference_number": "HS-21",
      "transfer_purpose": "ROUTE_LOAD",
      "work_session_id": 8,
      "route_id": 7,
      "expected_receiver_id": 9,
      "created_by": 17,
      "quantity": "3.25",
      "operation_status": "PENDING",
      "navigation_target": "DISPATCH_ROUTE_TRANSFERS",
      "action": "FORCE_CANCEL_HANDSHAKE"
    }]
  }
}
```

`action` is null when the current reader cannot cancel on the exact source.
It is a snapshot hint, not permission to mutate from Inventory. Navigate using
`route_id` and `transfer_id` to Dispatch's existing owner. The existing command
`POST /dispatch/transfers/{transfer_id}/force_cancel` still requires its reason,
stable request ID, fresh source permission and locked PENDING state. Do not send
these HANDSHAKE IDs to Inventory's TRANSIT cancellation command.

## Coverage and safe limits

| Coverage | Meaning |
| --- | --- |
| NONE | This source/status has zero reserved quantity. |
| COMPLETE | Returned proven, readable owners explain all its reserved quantity. |
| PARTIAL | Some quantity is explained; the rest is not represented in this preview. |
| UNRESOLVED | No safe attribution can be returned, or evidence contradicts the balance. |

`unattributed_quantity` is reserved quantity minus quantities represented by the
returned owners. It includes hidden/unsupported evidence and omitted owners.
`OWNER_EVIDENCE_UNAVAILABLE` deliberately does not distinguish a hidden operation
from unsupported evidence. `OWNER_EVIDENCE_MISMATCH` suppresses all owner/action
identities when proven visible allocations exceed the balance. The preview is
deterministic by transfer ID, capped at 20 owners per location/status; a larger
set reports `owners_truncated: true`, `OWNER_PREVIEW_LIMIT`, and the omitted
quantity. This is a compact explanation, not an exhaustive operation browser.
It never reports truncated or unexplained stock as resolved.

Inventory read permissions filter stock sources; Dispatch route-read authority
(both the stored route warehouse and vehicle scope) additionally filters owner
identities before preview windows. Source-scoped `transfer.cancel` determines
the action hint. Existing admin authority is retained. No names or inaccessible
destination details are fetched. Balance and owner evidence share one SQL
statement/snapshot, without additional roundtrips, locks or per-owner queries.
Normal concurrent commands can change the result after that read; Dispatch
always revalidates at execution.

## Reservation producer audit

| Existing source | Evidence and supported scope |
| --- | --- |
| Dispatch route load/return | `wa_backend/api/dispatch.py:2209–2260` creates PENDING HANDSHAKE, exact batch lines and HANDSHAKE_RESERVE movements. Both ROUTE_LOAD and ROUTE_RETURN are supported, including vehicle source balances. |
| Driver decision / Dispatch force cancel | `wa_backend/api/driver.py:2442–2464` and `wa_backend/api/dispatch.py:2656–2706` RELEASE the exact allocation. Posted/cancelled/rejected headers or any matching RELEASE evidence are excluded. |
| Transit/special-transfer allocations | `wa_backend/api/warehouse/transfers.py:1585–1605,2206–2222,2468–2505` uses physical/status movements, not an independent RESERVE producer. Do not attribute HANDSHAKE reservations to these operations. |
| Custody/shortage reconciliation | `wa_backend/api/reconciliation.py:273–309` checks reservations as blockers; stocktake shortage/surplus is PHYSICAL-only (`wa_backend/services.py:2984–2992`). These are not separate reservation-owner types in the current producer path. |
| Generic movement engine / legacy or orphan evidence | The engine can apply RESERVE/RELEASE (`wa_backend/services.py:3830–3849`); visit reversal supports inverse reservation evidence but excludes transfers and is VISIT-only (`5749–5756,5820–5840`). No additional active business producer was found in the audited API paths. Non-HANDSHAKE, missing-route, missing/mismatched movement, foreign, unsupported-status or otherwise unverifiable evidence stays unattributed. No guessed owner or cancellation action is emitted. |

Supported attribution requires a tenant-safe header/line/route relation, matching
receiver/work session, PENDING HANDSHAKE, AVAILABLE source, an exact matching
RESERVE movement and no matching RELEASE. InventoryBalance remains the quantity
authority; this projection does not repair inconsistent evidence.

Focused acceptance executes the real endpoint's SQL statements with synthetic
SQLite fixtures and compiles the joined query for PostgreSQL. It covers tenant
and permission negatives, precise quantities, preview limits and read-only
behavior. PostgreSQL RLS and concurrent mutation acceptance remain deployment
verification; this change does not modify their policies or command semantics.
