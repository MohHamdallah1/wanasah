# Purchase Cost Reference — bounded backend foundation

Base: 2be59f6066419ef1de0157c48adaf8c931bfbaf2.
Owner-authorized workflow: company Product manual purchase-reference maintenance,
followed later by Supplier Inbound integration. This is not valuation or Pricing.

## Implemented boundary

Inventory Costing owns the separate purchase_reference package.
purchase_cost_references has one current row per company + sellable variant.
It stores the entered amount in its explicit purchase UOM, the exact rational
base-unit conversion snapshot, company currency, independent revision, source,
provenance and time. No historical invoice/cost/valuation/PriceBook is updated.

purchase_cost_reference_commands is append-only canonical principal/profile
idempotency evidence. purchase_cost_reference_changes is append-only change
history with previous snapshot and command linkage. Current state must match
its immutable history at commit, enforced by deferred database checks. No legacy
Driver ID is substituted for a principal/profile ID in this module.

GET /purchase-cost-references/{variant_id} returns a reference or null.
Optional quote_uom_id converts exactly; monetary precision loss fails closed.
PUT is a reference-only manual command with request_id, expected_revision
(0 for absent), amount as a decimal string, purchase_uom_id, explicit currency_code
and optional reason. No deletion/clearing command is introduced. Same-value saves
with a new request record a new explicit revision; replay does not.

Both inventory.purchase_cost_reference.read and .manage are company-only.
Manage includes reading. Catalog/Pricing/cost-policy grants do not imply either
capability. No ordinary role receives automatic grants. These endpoints change
only the reference; Catalog identity commands retain their independent authority.

## Transaction and lock contract

Application services use the caller's AsyncSession and NEVER commit/rollback.
A failed composed command must roll back its entire transaction.
The HTTP adapter owns one commit and rolls back all error/cancellation paths.

Manual write order:
authorization + tenant/actor validation -> operation advisory guard ->
durable replay lookup -> company reference-writer advisory gate ->
ProductVariant SHARE -> Company SHARE (currency stability) ->
current reference UPDATE lock -> state/command/history writes -> caller commit.
No conversion-row lock is taken: the legacy editor locks child then parent,
while structural UOM writes require the same parent Product UPDATE lock.

Acquire the reference writer gate before any other Product/Pricing/Inventory
business locks when composing a write. Do not compose read-then-write after
taking locks; acquire the public gate first instead. Reads are company scoped
and hold Product/Company SHARE locks until the caller closes its transaction.
All commands load fresh state after waiting. A stale independent reference
revision fails with PURCHASE_REFERENCE_REVISION_CONFLICT.

Replaying an old committed operation returns its frozen original response before
the writer gate, currency validation or reference mutation. It never restores an
old reference. Another actor/input with the same request identity fails closed.
A lost response is reconciled with the SAME request_id, never a fresh identity.

## Explicitly deferred integration / Lead review

Supplier Inbound runtime and the protected Product routers/models are untouched.
No receipt reference writer is enabled. The future receipt orchestrator must
acquire the public writer gate immediately AFTER its own replay branch and BEFORE
supplier/invoice/lifecycle/policy/movement locks. Its reference/audit changes must
use that same transaction and roll back with the receipt. An internal receipt
update is authorized by the exact-location receipt capability, not by granting
general manual cost-edit permission to an inbound operator.

The schema reserves SUPPLIER_INBOUND provenance and a tenant-safe cost-event FK;
the future service must verify the selected event belongs to the same variant
and is original PURCHASE_IN evidence. It must not average differently priced
lines: that future selection requires explicit Owner business input. There is
no receipt service or API that can fabricate that provenance in this foundation.

Company currency is stabilized only for each command with a row SHARE lock.
A mismatch against the stored reference fails closed; no FX or relabeling occurs.
Global currency immutability is NOT implemented: it requires separate Lead review.
No historical currency backfill or claim of legacy currency verification is made.

## Migration and verification

Alembic f1a6c8e2b940 extends the exact-base head e6b4c2d9a731.
It adds only domain tables, RLS, constraints/triggers, runtime grants and two
permission-catalog rows. No accounting data backfill or role assignment.
Downgrade refuses if any reference/command/change evidence exists.

Focused GitHub CI migrates an empty disposable PostgreSQL 16 database through
Alembic, runs alembic check, then exact-arithmetic and real committed SQL tests.
Tests use a distinct restricted NOSUPERUSER/NOBYPASSRLS runtime role, canonical
independent actor IDs, two tenants and independent concurrent sessions.
Accounting independence is checked against nonempty synthetic FIFO/MA receipts,
outbound events/layers/allocations and an existing PriceBook.

The API test overrides authenticated access; it does not prove full login/session
middleware or physically dropped TCP recovery. Later receipt integration needs
its own atomic receipt/reference, explicit-line-selection and authenticated gates.
