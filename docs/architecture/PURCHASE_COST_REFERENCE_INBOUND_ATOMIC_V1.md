# Purchase cost reference: atomic Supplier Inbound integration

This bounded V1 change unblocks Supplier Inbound's actual purchase cost and future receipt reference workflow. The Product reference UI is separately owned by PR #407. The accounting kernel, historical receipts, sale prices and PriceBook remain independent.

## Transport and prefill

`POST /warehouse/inbound/options` adds nullable `items[].purchase_cost_reference`. It contains the native amount (exact six-decimal string), purchase UOM, company currency, independent revision and provenance. It is a suggestion, potentially stale. Clients must only initialize an untouched actual-cost draft, preserve every operator-entered value across options refreshes, and never submit a reference amount instead of the entered actual cost. Every receipt line still requires explicit `unit_cost` and `uom_id`; the server never substitutes a reference for actual cost.

Prefill requires company-scoped `inventory.purchase_cost_reference.read` or `.manage`, in addition to inbound access. Existing inbound-only users receive null suggestions and can enter actual receipt costs. Catalog/Pricing authority does not expose the reference.

`POST /warehouse/inbound` accepts optional `purchase_reference_selections`:
```json
[{"product_variant_id": 123, "uom_id": 2, "unit_cost": "24.000000"}]
```
At most one entry per product. A single distinct native (UOM, actual unit cost) pair is automatic. Multiple distinct pairs require an explicit pair present on that product's receipt lines, even if two pairs convert to the same base cost. Failure returns `INBOUND_REFERENCE_SELECTION_REQUIRED` with actual cost/UOM options. Quantity, lot order and array order never choose the reference. No averaging occurs. Identical selected pairs across multiple lots are equivalent; all supporting cost-event IDs are audited and the smallest ID anchors the FK, without choosing a different cost.

Selection entries are canonicalized by product and encoded in hash context. The new field is excluded from the historical body hash. Absent/null/empty selection leaves historical hashes byte-compatible, including the existing optional Supplier compatibility path. The shared item-sorting hash function is unchanged. Reusing the same request with a different selection conflicts.

## Transaction, authorization and concurrency

The existing receipt durable idempotency guard and replay branch run first. Completed replay returns the stored receipt response before any reference guard or mutation. This includes receipts posted before this feature, regardless of a newer manual reference.

For a new receipt the domain verifies canonical active actor, tenant context and exact-warehouse `inbound.create`, then acquires the reference command advisory guard followed by the company writer advisory guard. These precede Supplier, invoice, lifecycle, batch, costing policy, stock and accounting locks. The command -> writer order matches manual reference writes, including collisions between manual and receipt request UUIDs. The company guard handles absent-row first insert races and serializes receipt/manual writers. Manual edits retain expected-revision checks; receipts append to the latest committed revision.

After the existing engine posts movements and Supplier snapshots, the domain verifies every selected source through company, product, batch, movement, actual purchase event, receipt reference, destination warehouse and Supplier request UUID. It uses actual native unit cost and the exact rational base quantity/input quantity from immutable cost evidence. Product parents lock in sorted order before one Company SHARE lock stabilizes currency. Reference, command and change rows flush without commit. The receipt adapter then completes durable idempotency and performs its existing single commit. Any failure rolls everything back, including reference audit. The domain cannot commit independently and rejects completed receipts or a writer context reused outside its original session/transaction.

Exact warehouse inbound permission authorizes this receipt side effect only. It never grants general manual manage or company cost visibility. Canonical principal/profile attribution remains separate from legacy movement attribution.

## Currency and schema

The reference stores current company currency explicitly. A mismatch with an existing reference fails closed and rolls back the receipt; there is no FX conversion or relabeling of evidence. This change does not impose global company-currency immutability. That policy remains a separate Lead/Owner review item. Legacy receipts already use company currency implicitly.

No new migration or backfill is required: foundation migration f1a6c8e2b940 already reserves SUPPLIER_INBOUND_SET and receipt source provenance. Existing RLS, tenant-safe FKs, append-only audit protections, deferred audited-current checks and runtime grants apply. This adds evidence only for newly committed receipts. No old operation is replayed to seed references.

## Acceptance

The focused GitHub PostgreSQL 16 gate runs against the exact branch HEAD with a non-superuser, non-BYPASSRLS runtime role. It covers native prefill and operator override, mixed-cost/UOM selection and reordered replay, atomic success/forced rollback, lost response and replay after newer manual edits, legacy hashes with/without Supplier, manual/receipt and receipt/receipt first-insert races, exact receipt provenance, scoped authority, historical accounting preservation and normal receipt accounting under FIFO and MOVING_AVERAGE. Foundation acceptance and canonical Supplier authorization regression tests remain included.
