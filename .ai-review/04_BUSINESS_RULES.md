# Wanasah — Business Rules Extraction

> Phase 5 Deliverable — Business Rules Report
> Scope: Non-negotiable business rules, invariants, and hard constraints enforced across the system's core logic.
> This document does not review code for bugs/syntax errors and does not modify any existing file. It builds on `.ai-review/00_PROJECT_MAP.md`, `.ai-review/01_ARCHITECTURE.md`, `.ai-review/02_DATA_FLOW.md`, and `.ai-review/03_DEPENDENCY_GRAPH.md`.
> Sources analyzed: `wa_backend/models.py`, `wa_backend/services.py`, `wa_backend/api/driver.py`, `wa_backend/api/dispatch.py`, `wa_backend/api/warehouse.py`, `wanasah_frontend/lib/repositories/sync_repository.dart`, `wanasah_frontend/lib/core/db/local_database.dart`, `wanasah_frontend/lib/blocs/visit/visit_bloc.dart`.

---

## 1. Inventory & Warehouse Invariants

### 1.1 Database-level hard constraints (cannot be violated regardless of application logic)
- `MainWarehouse.available_quantity_packs >= 0` (`chk_main_warehouse_positive`)
- `MainWarehouse.reserved_quantity_packs >= 0` (`chk_reserved_warehouse_positive`)
- `SessionInventory.current_remaining_quantity >= 0` (`chk_positive_inventory`)
- `VehicleLoad.quantity >= 0` (`chk_vload_qty`)
- `VisitItem.quantity/packs_quantity/bonus_quantity/sample_quantity/sample_packs_quantity >= 0` (per-field CheckConstraints)
- `VisitReturn.quantity/packs_quantity >= 0` (`chk_vret_qty`, `chk_vret_pqty`)
- `DamagedItemLog.quantity_packs >= 0` (`chk_damaged_positive`)
- `MainWarehouse.product_variant_id` is the table's primary key — a product can never have more than one warehouse row (guarantees O(1) lookup and prevents duplicate stock ledgers for the same variant).

### 1.2 Packs-as-atomic-unit rule
- **Packs (`packs`), not cartons, are the system's smallest unit of accounting.** Every warehouse, vehicle, and session-inventory quantity is ultimately stored/reasoned about in packs; cartons are a display/input convenience computed via `packs_per_carton` (default 50 on `ProductVariant`).
- Conversion is always `total_packs = cartons * packs_per_carton + loose_packs`, and the reverse (`divmod(total_packs, packs_per_carton)`) is used everywhere stock is displayed to a human (dashboard, ledger, mobile dashboard).
- `packs_per_carton` is guarded against zero/None everywhere it is used (`variant.packs_per_carton or 1`) to prevent division-by-zero crashes.

### 1.3 Negative-stock prevention
- `services.adjust_inventory()` refuses any mutation that would drop `current_remaining_quantity` below zero, returning a business error instead of allowing negative custody.
- `warehouse_inbound`, `dispatch_route`, `adjust_route_inventory`, `update_route_status`, `respond_to_transfer`, and `batch_respond_to_transfers` all independently re-implement the same check before decrementing `available_quantity_packs`, `reserved_quantity_packs`, `VehicleLoad.quantity`, or `SessionInventory.current_remaining_quantity` — no negative-value commit is permitted at any of these code paths.
- `adjust_warehouse_entry` (ledger correction) explicitly rejects a delta that would make `available_quantity_packs` negative.

### 1.4 Warehouse lock (Audit Lock) rules
- A single global `SystemSetting` key `warehouse_status` (`ACTIVE` | `AUDIT_LOCK`) gates warehouse mutation:
  - `warehouse_inbound` is **fully blocked** while `AUDIT_LOCK` is active (no supplier receiving during a stocktake).
  - `dispatch_route` (creating a new route with an inventory load) is blocked while `AUDIT_LOCK` is active.
  - `adjust_route_inventory` and the inventory-adjustment branch of `update_route_status` are blocked while `AUDIT_LOCK` is active.
- `warehouse_stocktake` **automatically re-opens** the warehouse (`warehouse_status = ACTIVE`) via an idempotent upsert immediately after a successful audit adjustment — the lock is meant to be a short, self-clearing window, not a manual-only toggle.
- Manual lock/unlock (`toggle_warehouse_lock`) only accepts the literal values `AUDIT_LOCK` or `ACTIVE`; any other value is rejected.

### 1.5 Duplicate/idempotency protection on inbound stock
- A supplier `reference_id` (invoice number) already present among prior `INBOUND_SUPPLIER`/`INBOUND_CORRECTION` ledger rows (matched case-insensitively, whitespace-trimmed) is **rejected outright** — the same supplier invoice can never be booked twice.
- Duplicate product-variant line items within a single inbound/stocktake payload are aggregated (summed) before processing rather than applied twice.

### 1.6 Ledger integrity (append-only, non-editable)
- Every mutation to `MainWarehouse.available_quantity_packs`/`reserved_quantity_packs` **must** be paired with a `WarehouseLedger` row carrying a `balance_after_packs` snapshot — this snapshot is the audit mechanism that lets balances be reconstructed/verified after the fact.
- Every mutation to `SessionInventory.current_remaining_quantity` is intended (by `services.adjust_inventory`'s design) to be paired with an `InventoryLedger` row recording `expected_quantity`, `actual_quantity`, and `difference` — though (as noted in `01_ARCHITECTURE.md`/`02_DATA_FLOW.md`) `api/dispatch.py` and `api/warehouse.py` re-implement this pairing inline rather than calling the shared service.
- `WarehouseLedger` and `InventoryLedger` rows are never updated or deleted by any reviewed endpoint — corrections are always additive (`INBOUND_CORRECTION`, `AUDIT_ADJUSTMENT`, `Surplus`/`Deficit`), preserving a full historical trail.
- Only `INBOUND_SUPPLIER` ledger entries may be corrected, and only via the dedicated `adjust_warehouse_entry` endpoint, which itself requires the acting admin's password to be re-verified before any correction is applied (a "step-up" authorization on financially sensitive corrections), and any wrong-password attempt is itself logged to `SystemAuditLog` as `UNAUTHORIZED_ADJUSTMENT`.

### 1.7 Product lifecycle rules
- A `ProductVariant` with `is_active = False` (recalled/discontinued) **cannot be sold** (`update_visit`) and **cannot be received as a new push transfer** (`respond_to_transfer`/`batch_respond_to_transfers` block accepting positive `quantity_packs` for an inactive variant) — but an inactive variant **can still be pulled/returned/withdrawn**, since a driver must be able to return discontinued stock without being blocked.
- Adding a new product variant (`add_product_variant`) enforces uniqueness on both variant name (case-insensitive) and SKU, and automatically provisions a zero-balance `MainWarehouse` row so no downstream inventory endpoint ever encounters a "missing warehouse record" for a valid product.

### 1.8 Deadlock-avoidance lock ordering (a structural invariant, not just a performance detail)
- Every code path that must lock more than one of {`VehicleLoad`, `MainWarehouse`, `SessionInventory`} does so in the **fixed hierarchical order**: `VehicleLoad` → `MainWarehouse` → `SessionInventory`, and multi-row locks within a single table are always taken in ascending `id`/`product_variant_id` order. This ordering is repeated identically across `api/driver.py` (`respond_to_transfer`, `batch_respond_to_transfers`) and `api/dispatch.py` (`dispatch_route`, `adjust_route_inventory`, `update_route_status`, `settle_session`) and is treated as a mandatory rule to prevent cross-endpoint deadlocks, not an incidental implementation choice.

---

## 2. Dispatch & Driver Handshake Rules

### 2.1 Route creation invariants
- A **zone** can have at most one route in `{active, waiting, postponed}` status at any time — a new route cannot be created for a zone that is already being worked or is queued.
- A **driver** can have at most one route in `{active, waiting}` status at any time.
- A **vehicle** can have at most one route in `{active, waiting}` status at any time.
- These three uniqueness rules are enforced both defensively at the API layer (`dispatch_route`) and structurally in the database via partial unique indexes (`uq_active_route_per_driver`, `uq_active_route_per_vehicle`, `uq_active_route_per_zone`, each scoped to `status = 'active'`) — a genuine belt-and-suspenders invariant.
- Route dispatch is blocked entirely while the warehouse is under `AUDIT_LOCK`.

### 2.2 Morning load vs. mid-day handshake — the central dispatch invariant
- **If the target driver has no active `WorkSession` yet ("morning load")**: the requested cartons are compared directly against the vehicle's current `VehicleLoad`, the delta in packs is deducted/returned to `MainWarehouse.available_quantity_packs` immediately, `VehicleLoad` is upserted, and a `DISPATCH_LOAD`/`DISPATCH_UNLOAD` ledger row is written — **this is a synchronous, immediately-effective stock movement.**
- **If the driver already has an active `WorkSession` ("mid-day handshake")**: the same dispatch/adjustment code paths instead move the delta from `MainWarehouse.available_quantity_packs` into `reserved_quantity_packs` (an in-transit holding state) and create a `pending` `InventoryTransfer` row. **`SessionInventory` (the driver's live custody) and `VehicleLoad` are explicitly NOT touched at this point** — this is a hard rule enforced by comments in the code itself ("لا نعدل VehicleLoad هنا إطلاقاً! التعديل يتم فقط بعد موافقة المندوب").
- Only after the driver explicitly **accepts** the transfer (`respond_to_transfer` / `batch_respond_to_transfers`) does the system: release the reservation, update `VehicleLoad`, and increment `SessionInventory.current_remaining_quantity` + `net_transfers`. Rejecting a transfer releases the reservation back to `available_quantity_packs` without ever touching the driver's custody.
- A pending transfer that would pull stock from the driver (`quantity_packs < 0`) can only be accepted if the driver's current live balance can actually cover the withdrawal; otherwise the accept is rejected with an explicit shortfall message.
- A pending transfer offering new stock (`quantity_packs > 0`) of a now-**inactive** product variant is rejected at accept-time even if it was created while the product was still active.

### 2.3 Session lifecycle rules
- A driver **cannot start** a new work session while they have a previous session that has ended (`end_time` set) but is **not yet settled** by an admin — this is a hard block ("عهدة سابقة معلقة لم يتم تسويتها").
- A driver **cannot start** a work session without an `active` `DispatchRoute` already assigned to them.
- A driver **cannot start** a second session while one is already open (`end_time IS NULL`).
- On session start, `SessionInventory` rows are bulk-created by copying the vehicle's current `VehicleLoad` (`starting_quantity = current_remaining_quantity = load.quantity * packs_per_carton`) — this is the literal "morning handshake."
- A driver **cannot end** their work session while a break is currently open (`break_start_time` set, `break_end_time` null).
- A driver **cannot end** their work session while any `InventoryTransfer` for that session is still `pending` — all handshakes must be resolved (accepted or rejected) before the day can close.
- A break cannot be started if one is already open, and cannot be ended if none is open — break state is a strict two-state toggle, and every completed break is archived to `WorkBreakLog` (so a second break in one day does not overwrite the record of the first).

### 2.4 Sell authorization ("green light") rule
- A brand-new session starts with `is_authorized_to_sell = False` — a driver **cannot register any sale/visit outcome** until an admin explicitly authorizes the session (`authorize_session`).
- An admin is explicitly **forbidden from authorizing their own session** (self-authorization is blocked as a conflict-of-interest guard) — this rule only makes sense in setups where an admin account can also act as a driver.
- Authorization cannot be toggled on a session that has already ended or been settled (a "closed" session's permissions are frozen).

### 2.5 Zone/territory enforcement
- A driver may only record a sale for a shop **inside the zone of their currently active route**, unless: (a) the visit/shop is explicitly flagged `is_emergency`, or (b) the shop has an active (`pending`) `ShortageRequest` — either condition grants a one-off territorial exception.
- When a route is switched to a different driver, or closed/postponed, any of that driver's still-`Pending` visits for shops in that zone are released (`driver_id = NULL`, `work_session_id = NULL`, emergency flag cleared) so they can be picked up by whoever is assigned next.

### 2.6 Driver switch / route reassignment reconciliation
- Reassigning an active route to a new driver forces a full reconciliation of the outgoing driver's live custody before the switch completes: loose (non-carton) packs are returned to the warehouse, whole cartons are kept on the vehicle as a rolled-over `VehicleLoad`, the old session is force-ended, and all of that session's pending transfers are auto-rejected — a driver swap can never leave stock "unaccounted for" mid-transition.
- "Undo end work" (reopening a session an admin or driver closed) is capped at **3 uses per session** (tracked via `SystemAuditLog` entries of type `UNDO_END_WORK`) and is blocked outright if the driver has since started a new session or been assigned a new active route for that zone (a "split-brain" guard).

---

## 3. Sales, Invoicing & Pricing Rules

### 3.1 Pure-function invoice calculation
- `services.calculate_invoice()` is a deliberately pure function: it **raises an explicit error** if `pre_fetched_tax` or `active_offers` are not supplied by the caller — the rule is that tax percentage and active offers must always be fetched once per request and passed in, never queried lazily inside the pricing function (a guard against hidden N+1 database access inside financial math).
- If both requested cartons and packs are zero or invalid, the function returns an all-zero invoice rather than raising — this is required to support "free sample only" line items with no chargeable quantity.
- All monetary math is done in `Decimal`, quantized to **3 decimal places with `ROUND_HALF_UP`** — this precision (not 2) is a deliberate business rule to avoid rounding losses on sub-currency-unit ("Baisa"-level") pricing.

### 3.2 Offer application rules
- Offer eligibility is computed on **total equivalent cartons** = `cartons_requested + packs_requested // packs_per_carton` — loose packs are folded into the carton-equivalent count so a customer cannot lose an otherwise-earned volume discount purely because part of the order was in loose packs.
- Among all active `OfferRule`s whose `threshold_quantity` is met, the rule with the **highest threshold** is selected (best-offer-wins, not first-match or stacking).
- Three offer types are supported: `free_items` (bonus cartons awarded), `fixed_discount` (flat amount × multiplier), `percentage_discount` (percentage of the discounted-carton-equivalent amount).
- The final discount applied can **never exceed the invoice's base amount** — `actual_discount_applied = min(base_amount, discount_value)`, a hard ceiling that protects gross-margin reporting from ever showing a negative net sale from discounting alone.

### 3.3 Sample quota enforcement
- Each `ProductVariant` carries a `default_max_samples_per_day` (in cartons); when a driver includes sample quantities in a cart, the server sums that driver's **already-completed** sample issuance for that product **today** and rejects the new request if the combined total would exceed `default_max_samples_per_day * packs_per_carton`.
- If the configured daily cap is `0`, samples for that product are treated as **effectively unlimited** for now (an explicit interim rule pending full dashboard configuration, called out directly in the code) — this is a real business rule, not an oversight: a zero cap does not mean "no samples allowed."

### 3.4 Visit outcome business rules
- **`Sale`** requires at least one non-empty cart item — an empty-cart "Sale" is rejected outright.
- **`NoSale`** may include returns and samples but must contain **zero real sales quantity and zero cash collected** — a `NoSale` visit that smuggles in real product quantities or cash is rejected as a security/business violation.
- **`Postponed`** must contain **no cart items, no returns, and no debt payment** — postponing a visit while sneaking in a sale to avoid immediate accounting is explicitly blocked ("Postponed Theft Shield").
- The same product variant cannot appear more than once within the same cart, nor more than once within the same returns list, in a single submission — duplicates must be pre-merged by the client.
- Every quantity field submitted in a cart item (cartons, packs, bonus, samples) must be non-negative.
- A visit's persisted `status` is derived from its `outcome`: `Sale`/`NoSale` → `Completed`; `Postponed` → stays `Pending` (so it remains visible in the driver's active list rather than disappearing).

### 3.5 Editing/reversal rules
- Editing an already-`Completed` visit **always** triggers a full reversal of its previous financial and inventory effects (`services.reverse_previous_visit_state`) before the new submission is processed — this guarantees a visit can be corrected any number of times without double-counting stock or cash, at the cost of never allowing partial edits.
- A visit belonging to a session that has already been financially settled (`is_settled = True`) can **never** be edited again — this is an absolute, unconditional rule (`403`), independent of whether the specific edit would otherwise be valid.
- A reversal that would make the shop's balance go negative (i.e., the shop already paid off debt that the reversal would have to "un-collect") is refused outright (`InventoryReversalError`) rather than silently corrupting the ledger.
- Reversing a sellable return that the driver has since partially re-sold is refused if the driver's current custody can't cover giving that stock back — the same "can't go negative" rule applies symmetrically to reversal as to forward sales.

### 3.6 Returns/damage classification (zero-trust whitelist)
- A return is only ever treated as "sellable/good" (added back to the driver's live stock) if its `return_type` is **explicitly whitelisted** as `Good` or `Resellable`. Any other value — including anything a compromised/modified client might invent — is treated as damaged/expired by default and triggers the 1:1 exchange logic (a good unit is deducted from the driver's custody to compensate). This whitelist-over-blacklist stance is a deliberate anti-tampering rule.
- Historical pricing is preserved per sale: `VisitItem.price_per_unit_at_sale` locks in the price used at the moment of sale, so a later change to `ProductVariant.price_per_carton` never retroactively alters a historical invoice's recorded value.

---

## 4. Debt & Credit Limit Guards

### 4.1 Database-level guards
- `Shop.current_balance >= 0` (`chk_positive_balance`) — a shop's outstanding debt balance can never be persisted as negative.
- `Shop.max_debt_limit >= 0` (`chk_positive_max_debt`).

### 4.2 Extending new debt (`services.check_debt_limits`)
- A driver can only extend new debt to a shop if the driver's own account has `can_allow_debt = True` — this is a per-driver permission, not a global capability.
- A shop with `max_debt_limit <= 0` can **never** carry any debt at all, regardless of the driver's permission — a zero/unset limit is a hard "cash-only" designation for that shop.
- New debt is rejected if `current_balance + new_debt_amount > max_debt_limit` — the ceiling check is done against the *shop's* configured limit, not any per-transaction cap.
- The shop row is locked (`with_for_update`) during this check specifically to close a race-condition window ("Phantom Read") where two concurrent visits could both pass the check before either commits.

### 4.3 Cash vs. debt collection separation
- `cash_collected` can **never exceed** the invoice's `final_amount_due` for a `Sale` — any cash beyond the invoice total must go through the separate `debt_paid` field, never blended into the same number.
- `debt_paid` and `cash_collected` must both be non-negative; any negative value submitted is treated as an attempted exploit and rejected outright (400).
- Debt payment (`debt_paid > 0`) is rejected if the shop's current balance is already zero/negative (there is nothing to collect), and is rejected if the amount submitted **exceeds** the shop's current outstanding balance (cannot "overpay" a debt in a single visit).

### 4.4 Balance mutation and audit trail
- The shop's `current_balance` is mutated in exactly two places system-wide: `update_visit` (new debt incurred / debt collected during a visit) and `services.reverse_previous_visit_state` (undoing a prior visit's financial effect). Both paths recompute the resulting balance and **reject the operation outright** (rather than silently clamping) if the result would be negative.
- Any debt collection **writes a `SystemAuditLog` row** (`DEBT_COLLECTION`) capturing the balance before and the amount collected — every debt movement is independently auditable outside of the `Visit` row itself.
- Reversing a visit that had previously collected cash or debt payments logs a `CASH_REVERSAL_ALERT` audit entry — a explicit compliance rule flagging that the driver may now be physically holding cash that must be manually returned to the shop.

---

## 5. Settlement & Reconciliation Rules

### 5.1 Preconditions for settlement
- A session can only be settled (`settle_session`) if it has already ended (`end_time` is set) — an in-progress session can never be settled.
- A session that has already been settled (`is_settled = True`) can never be settled again — settlement is a strictly one-time, terminal operation.

### 5.2 Cash reconciliation
- `expected_cash = sum(cash_collected) + sum(debt_paid)` across all `Completed` visits in the session, compared against the admin-entered `actual_cash`.
- Any nonzero cash difference is logged as a `SETTLEMENT_CASH_DISCREPANCY` `SystemAuditLog` entry, capturing both the expected and actual figures plus the admin's justification notes.

### 5.3 Inventory reconciliation
- For every product touched during the session, the **expected physical total** = the driver's remaining sellable `SessionInventory` quantity **plus** any quantity already classified as damaged (from `VisitReturn` rows tagged `Expired`/`Damaged`/`Factory_Defect` during the day, harvested into `DamagedItemLog` at this exact moment — damage accounting is deliberately deferred to end-of-day, not recorded live at the point of return).
- The admin-entered actual jard (physical count) is compared against this expected-physical total; any difference produces a `Surplus`/`Deficit` `InventoryLedger` entry and a corresponding `INVENTORY_DISCREPANCY` `SystemAuditLog` entry.
- **Mandatory justification rule**: if there is *any* cash discrepancy or *any* inventory discrepancy, the admin's `notes` field is **required** — the settlement is rejected with an explicit `400` if discrepancies exist but no justification was provided. Settlements with zero discrepancy require no notes.
- If declared damaged quantity ever exceeds the actual physical count for a product, the sellable quantity is floored at zero and an `AUDIT_DISCREPANCY` ledger warning is written rather than allowing a negative sellable count to propagate further.

### 5.4 Stock disposition at close
- Remaining **sellable** stock (actual jard minus damaged) is split: **loose packs** are always returned to `MainWarehouse.available_quantity_packs` (`DISPATCH_UNLOAD`); **whole cartons** remain physically in the vehicle and are re-recorded as a fresh `VehicleLoad` for the next working day (`VEHICLE_ROLLOVER`) — a session's leftover cartons are never force-returned to the warehouse if a vehicle/route association still exists.
- If the session has no vehicle/route association at settlement time (an edge/fallback case), the **entire** remaining sellable stock is force-returned to the warehouse (`DISPATCH_UNLOAD_FALLBACK`) rather than left unaccounted.
- An `END_DAY_CLEARANCE` ledger entry is written unconditionally for every product touched, documenting the closing balance of that session's custody regardless of whether it was a surplus, deficit, or exact match.

### 5.5 Finalization
- On successful settlement: `WorkSession.is_settled = True` is set, and the associated route's `work_session_id` is cleared — this permanently and irreversibly decouples the settled session from any future dispatch action.
- Once `is_settled = True`, the mobile client (Flutter) is **permanently locked out** of further edits to any visit under that session (enforced in `update_visit`), making settlement a one-way, backend-and-dashboard-only terminal state as far as the field app is concerned.

---

## 6. Offline Synchronization Invariants

### 6.1 Write-path priority rule (`SyncRepository.saveInvoice`)
- The network call is **always attempted first** — offline queuing is a fallback, never the default path, even when the app suspects it might be offline.
- A genuine business rejection from the server (any 4xx with an HTTP response) is treated as final: the exception is **rethrown immediately and NOT queued** — the driver must see and fix the rejection themselves; the app will not silently keep retrying a request the server has explicitly refused.
- Only a true connectivity failure (no HTTP response at all) or a server-side failure (5xx) causes the payload to be persisted into the `pending_sync` queue.
- Whether the network call succeeds or falls back to offline, the **local SQLite state is always updated** (visit status, cart/returns JSON, local inventory deduction) so the driver's own UI reflects the action immediately in either case.

### 6.2 Double-deduction prevention
- Before queuing a new offline edit of a visit, any **previous** offline draft for that same visit is first reverted (`revertOfflineVisit`) — this prevents a driver from repeatedly editing the same offline sale and having stock deducted multiple times for the same underlying transaction.
- `revertOfflineVisit` reverses **only cart-item quantities** (sales/samples/bonus); it explicitly does **not** reverse returns — this is a deliberate, documented business decision ("we leave returns to the server to avoid tampering with custody"), meaning returns-related local stock state can only be corrected by the next full `syncDown()`.

### 6.3 Upload queue (`syncUp`) resolution rules
- Pending records are always processed **in strict FIFO order** (`created_at ASC`) — never reordered or prioritized by type.
- Error handling is tiered by HTTP status:
  - **401/403** → the entire sync loop halts immediately (auth is broken; do not burn through the queue against a rejected/expired token — everything is preserved for the next attempt after re-login).
  - **Other 4xx** (a business-rule rejection, e.g., debt ceiling exceeded) → that single record is skipped (left queued) so the driver can manually correct and resubmit it later; the rest of the queue continues processing.
  - **No response / 5xx** (real connectivity loss or server outage) → the loop halts entirely; already-synced records in this run are kept as-is, remaining ones are retried on the next attempt.
  - **Any other unexpected exception** → treated as a "poison pill": the single record is skipped (not deleted, not blocking) so it never freezes the rest of the queue, but it can persist indefinitely with no explicit user-facing indicator that it's stuck.
- A concurrency lock (`_isSyncing`) guarantees only one `syncUp()` execution can run at a time.

### 6.4 Download (`syncDown`) safety rules
- `syncDown()` **always** calls `syncUp()` first as a best-effort flush before pulling anything from the server.
- **Hard block rule**: if any pending record exists whose type is **not** `submit_sale` (i.e., something considered more structurally sensitive, such as `toggle_break`), `syncDown()` refuses to proceed at all and throws — this protects against overwriting local state that the server hasn't yet acknowledged for non-sale operations. A driver can still refresh their day even with unsynced *sales* pending, but not with other unsynced sensitive operations.
- Once the guard passes, the entire local `products` and `visits` tables are wiped and rewritten from the server's response inside a **single atomic SQLite transaction** (`refreshSessionData`) — this guarantees no partially-written/torn local state can exist even if the app is killed mid-sync.
- A concurrency lock (`_isSyncingDown`) guarantees only one `syncDown()` execution can run at a time.

### 6.5 Local persistence model constraints
- The local SQLite database holds **exactly three tables**: `products` (flat vehicle-stock snapshot), `visits` (flat visit snapshot with `cart_items`/`returns` embedded as JSON text, not normalized rows), and `pending_sync` (the write-ahead offline queue) — there is intentionally **no** local `shops`, `zones`, or `product_variants` table; anything the UI needs beyond these three tables must already be embedded on a `visits`/`products` row at sync time.
- `pending_sync` currently only recognizes two dispatchable types: `submit_sale` (→ `PUT /visits/{id}`) and `toggle_break` (→ `PUT /driver/{id}/sessions/break`). Any other/unknown type encountered during `syncUp()` is silently logged and skipped — by design, to avoid freezing the queue — but this also means a corrupted or future/unsupported record type can remain permanently stuck with no automatic resolution path.
- The server's returned `new_balance` (from a successfully synced sale) is the **only** mechanism by which the authoritative financial state is written back into local SQLite outside of a full `syncDown()` — it is applied via a direct raw `UPDATE` immediately after a successful queued-record dispatch.
