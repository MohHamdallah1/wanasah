# Product batch-restriction read contract

Inventory owns `load_batch_restrictions`; Simple Products consumes its public
contract. This is additive evidence on each `GET /simple-products` item, under
`batch_restrictions`. It does not change list selection, pagination, lifecycle,
Product operational hold, sale authority, FEFO, batch transitions or recall close.

## Scope and permission

The existing `catalog.read` gate remains. A company-wide `inventory.read` grant
(or the existing company-admin authority) is additionally required to expose any
company-wide batch evidence. `batch_restrictions: null` means unavailable by
permission, **not** zero restrictions. A location-only inventory grant does not
qualify; no other-location quantities, counts or reasons are disclosed.
Authenticated actor company and the existing tenant/RLS session remain mandatory.
No client-supplied company or warehouse scope is introduced.

## Version 1 shape and semantics

```json
{
  "schema_version": 1,
  "scope": "COMPANY",
  "affected_batch_count": 3,
  "affected_on_hand_quantity": "12.345678",
  "quantity_unit": "BASE_STOCK_UNIT",
  "counts_by_disposition": {"QUARANTINED": 1, "BLOCKED": 1, "RECALLED": 1},
  "representative_reason": {
    "selection": "LOWEST_BATCH_ID_WITH_CURRENT_REASON",
    "batch_id": 41,
    "disposition": "QUARANTINED",
    "disposition_revision": 2,
    "disposition_reason": "Awaiting laboratory release"
  }
}
```

- Counts are distinct current `ProductBatch` records in those three dispositions,
  including inactive, empty and historical batches. They are not stock-status
  bucket counts. `RELEASED` batches are excluded even if individual stock portions
  have restrictions; those portions belong to the existing inventory authority.
- On-hand is the exact sum of `InventoryBalance.on_hand_quantity` over all
  company locations and stock-status buckets for those batches, in the item's
  base stock UOM (`base_uom_id`). Reserved is already contained in on-hand and is
  never added or subtracted. No stock means `0.000000`, not missing evidence.
- Zero-count summaries have all three counts zero and a null reason. A missing
  reason stays null; an unavailable summary never becomes a fake zero summary.
- This is a warning read, not a claim about complete sellability: expiry,
  production dates, portion status, locks, Product hold and lifecycle are separate.

## Authoritative reason and bounded reads

The current human-entered reason is already queryable in
`product_batches.disposition_reason`, with `disposition_revision`.
`services.change_product_batch_disposition` persists it, and records
`DomainAuditEvent(event_type='BatchDispositionChanged').reason_text` and before/
after snapshots; the same event is emitted to the transactional outbox.
No migration or mutation change is needed.

Return the current reason of the lowest-ID affected batch with a non-null reason,
with its batch ID, current disposition and revision. This is deliberately **not**
labelled the latest reason across batches: `ProductBatch.updated_at` is a general
row-update timestamp. True disposition chronology belongs to audit `occurred_at`.
There is no audit-history scan or invented/truncated fallback reason here.

The loader consumes at most 200 already-paginated variant IDs. It performs one
fresh company-wide permission read and one aggregate query (zero aggregate reads
when denied or the page is empty). Balances aggregate per batch before counting;
reason ranking returns at most one reason per variant. All joins include company
and variant identity. Existing company/variant-prefixed ProductBatch indexes and
InventoryBalance company/variant indexes remain unchanged; no speculative index
or projection is added. No row/advisory locks, flushes, commits, mutations,
idempotency records or domain events are introduced by this read path.
Both read statements explicitly disable ORM autoflush; pending objects from a
caller cannot be persisted as a side effect of reading this warning contract.

Focused tests use synthetic in-memory SQL fixtures and PostgreSQL SQL compilation.
Production PostgreSQL RLS execution and query-plan/performance verification are
not claimed by those tests and remain deployment verification requirements.
