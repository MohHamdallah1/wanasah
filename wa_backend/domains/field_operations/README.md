# Flutter V1 FIELD prerequisites

Base: `1f69d2d8946e027aeea64d518152c4c7bf7bcc13`.
All existing driver/auth/session/visit/transfer/shop routes stay mounted.
No migration, new worker/service, frontend change, costing or financial engine.

## Returned stock identity

`POST /visits/{visit_id}/return-resolution` is a read-only POST.

Input: `product_variant_id`, positive carton/base-pack quantity (`quantity`,
`packs_quantity`), `return_type = Damaged | Expired | Factory_Defect`.
Optional evidence: `lot_number`, `production_date`, `expiry_date`,
`delivery_date` (ISO business dates).

The server scopes to the canonical FIELD actor's owned assigned visit/shop.
It considers net physical deliveries at that shop, their reversals and returned
stock. Samples/rewards/exchanges retain their actual movement evidence.
It never uses vehicle FEFO to identify the returned goods and never collapses
separate no-lot receipts into one identity. A larger requested quantity cannot
silently select the only large Batch while smaller candidates remain possible.

Success: `{status:"RESOLVED", resolution_token, evidence}`.
Evidence contains only public lot/production/expiry values. The signed token is
opaque transport, never an operator input, access credential or carton-identity
claim. It is owner/company/visit/shop/session/product/quantity/reason bound.
No expiry is applied to this reference: durable offline commands need stable
recovery; current provenance and identity are revalidated on first execution.

Ambiguity: 409 `FIELD_RETURN_EVIDENCE_REQUIRED` with
`context.required_evidence` and, where sufficient, human-readable choices.
Unresolved/no-source cases fail closed with a stable code and required business
action. No database Batch IDs or internal no-lot identities appear in choices.

Send the same existing `PUT /visits/{visit_id}` with a return line:

```json
{
  "product_variant_id": 123,
  "resolution_token": "<opaque resolved value>",
  "quantity": 0,
  "packs_quantity": 2,
  "return_type": "Damaged",
  "reason": "Packaging damaged"
}
```

`VisitReturnInput` itself still requires Batch truth for legacy callers.
The separate resolved transport is converted on the server. First execution
rechecks provenance under existing session/shop/visit locks before correction,
then checks Batch metadata after lifecycle/location guards. It delegates all
stock, FEFO replacement, costing, correction and audit to the existing engine.
Combined resolved return quantities must be substantiated by delivered evidence.

Persist the complete UUID/body/token before sending. Exact replay returns its
stored result before current session/provenance guards; changed resolution
evidence/body under the same UUID conflicts. Legacy request hashes/responses
remain compatible. Changing a completed visit is a new operation only after
the earlier result is resolved.

## Field-created shop tax completion

`POST /shops` adds `commercial_readiness` to its existing response. A new shop
has `status:"ACTION_REQUIRED"`, `sale_ready:false`,
`code:"SHOP_TAX_JURISDICTION_REQUIRED"`,
`required_action:"BACKOFFICE_SET_SHOP_TAX_JURISDICTION"`.

No jurisdiction is guessed from geography or from a singleton taxonomy.
Existing authorized Backoffice shop/tax setup supplies it.
`GET /visits/{visit_id}/commercial-state` refreshes this state and validates
the canonical active jurisdiction chain. READY addresses this tax prerequisite,
not stock, pricing, credit or final transaction acceptance.

New clients should supply optional UUID `request_id` to shop creation.
The existing operation authority commits shop + Pending visit + exact response
atomically; changed input conflicts. Missing UUID preserves legacy compatibility
and does not acquire an automatic-retry guarantee.

## Authoritative invoice

`POST /visits/{visit_id}/invoice-preview` is a read-only POST accepting
`cart_items` in the existing product/carton/base-pack shape (maximum 500).
It calls `resolve_driver_sale` with the assigned route/work-session commercial
context and canonical shop tax context; it never accepts a price.

Response: `{invoice, commit_required:true}`.
Invoice contains PREVIEW/COMMITTED status, currency, calculation timestamp,
rounding precision/mode, exact decimal-string totals (gross, discount,
post-offer, taxable, tax, line total, rounding adjustment, final payable),
line financial results and reward base quantities. It contains no costs/profit.
Preview is not stock reservation or credit approval. Commit recalculates through
the existing mutation guards/authorities.

New successful visit mutations add `invoice` to their durable response
(null for non-sales). An old durable response replays exactly as originally
stored and may lack this new field.
`GET /visits/{visit_id}/invoice` reads the current frozen sales revision,
without repricing, for the owning FIELD actor; it returns null for non-sales.
Historical immutable revision lines remain readable even after cancellation
flags change during a concurrent correction. Revision number identifies the
read evidence.

## Current non-sellable vehicle custody

`GET /driver/custody?limit=100&cursor=...`; maximum 200 rows per page.
Requires own current open, unsealed session and canonical vehicle custody.
Response: `{session_id, items, next_cursor}`. Each item has product identity/name,
language-neutral stock status, base UOM code and exact quantity string.

Quantities aggregate InventoryBalance by product/status. No Batch IDs, supplier
or valuation data is exposed. Supported statuses: QUARANTINED, BLOCKED, RECALLED,
DAMAGED, DISPOSAL_PENDING. Existing AVAILABLE reads remain unchanged.
The opaque cursor binds owner/company/session/vehicle location. This is live
pagination; restart from the first page after a mutation or reconciliation.

## Errors and acceptance

New business failures use the application's canonical
`error.code/context/request_id` envelope; never branch on localized text.
The dedicated Backend GitHub Actions workflow runs focused contracts, legacy
route/identity/session regressions, and real migrated PostgreSQL acceptance with
a restricted runtime role. No local machine/database is used.
