# Driver / Dispatch Seam Inventory

> **Status:** analysis only; candidate seams, not final architecture.
>
> **Baseline:** `main` @ `d0a15d770bbdac553d4f69a813ccd2761dfd8a48`.
>
> **Scope:** `wa_backend/api/driver.py` and `wa_backend/api/dispatch.py` only. No endpoint, import, test, transaction, lock, or behavior was changed.

## 1. Guardrails used for this inventory

This inventory follows `.rules`, `AGENTS.md`, `ARCHITECTURE.md`, `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`, `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md`, and `REPRESENTATIVES_VEHICLES_V1_PLAN.md`.

The purpose is to expose the current seams and invariants before a future split. It does **not** choose a final package structure, create a new authorization model, redefine representative/vehicle ownership, move routers, or convert orchestration into services. Any choice that would change an established architectural ownership rule is listed under **ARCHITECTURE DECISIONS REQUIRED**.

## 2. Inventory totals

| File | Router endpoints | Internal/top-level helpers | Total top-level functions |
|---|---:|---:|---:|
| `wa_backend/api/driver.py` | 13 | 11 | 24 |
| `wa_backend/api/dispatch.py` | 26 | 23 | 49 |
| **Total** | **39** | **34** | **73** |

## 3. Public HTTP contract inventory — must remain stable during refactor

### 3.1 `driver.py`

| Method | URL | Function | Primary responsibility |
|---|---|---|---|
| POST | `/driver/sessions/start` | `start_work_session` | field identity + work-session start + route/vehicle/custody binding |
| POST | `/driver/sessions/end` | `end_work_session` | work-session close + route/session completion guards |
| POST | `/driver/breaks/toggle` | `toggle_break` | work-break state transition |
| POST | `/driver/visits/update` | `update_visit` | visit execution + commercial action + inventory/finance side effects |
| GET | `/driver/dashboard` | `driver_dashboard` | driver operational read model |
| POST | `/driver/custody/transfers/{public_id}/respond` | `respond_to_driver_transfer` | custody-transfer handshake response |
| POST | `/driver/custody/batch/respond` | `respond_to_driver_constraint_batch` | batch custody/constraint handshake response |
| GET | `/driver/visits/pending` | `driver_pending_visits` | pending visit queue/read model |
| POST | `/driver/shops/add` | `driver_add_new_shop` | field shop capture |
| GET | `/driver/products` | `get_products` | route-aware driver commercial catalog/pricing read |
| GET | `/driver/visits` | `get_driver_visits` | visit history/list read |
| GET | `/driver/visits/{visit_id}` | `get_visit_details` | visit detail read |
| GET | `/driver/sessions/active` | `get_active_session` | active field-session read |

### 3.2 `dispatch.py`

| Method | URL | Function | Primary responsibility |
|---|---|---|---|
| GET | `/admin/dispatch/authorize` | `authorize_dispatch` | dispatcher authorization/bootstrap decision |
| GET | `/admin/dispatch/dashboard` | `dispatcher_dashboard` | dispatch operational dashboard read model |
| GET | `/admin/dispatch/settlement-report` | `get_settlement_report` | session settlement/reconciliation read model |
| POST | `/admin/dispatch/settle-session/{session_id}` | `settle_session` | settlement/reconciliation mutation |
| POST | `/admin/dispatch/initialize` | `initialize_dispatcher` | dispatch bootstrap/initialization |
| POST | `/admin/dispatch/routes` | `dispatch_route` | route creation/assignment/load planning/custody initialization |
| GET | `/dispatch/vehicle-inventory` | `get_vehicle_inventory` | vehicle inventory read |
| GET | `/dispatch/routes/{route_id}/inventory/live` | `get_route_inventory_live` | route live inventory read |
| POST | `/admin/dispatch/route/inventory/adjust` | `adjust_route_inventory` | route inventory adjustment |
| POST | `/admin/dispatch/route/{route_id}/force-cancel` | `force_cancel_route` | exceptional route cancellation + custody/inventory cleanup |
| GET | `/admin/dispatch/transfers` | `list_custody_transfers` | custody transfer read/navigation |
| POST | `/admin/dispatch/shops/bulk-update` | `bulk_update_shops` | shop/zone bulk governance |
| POST | `/admin/dispatch/shops` | `add_shop` | admin shop creation |
| GET | `/admin/dispatch/routes/active` | `get_active_routes` | active-route read model |
| PUT | `/admin/dispatch/route/status` | `update_route_status` | route lifecycle state machine |
| POST | `/admin/dispatch/route/undo-end` | `undo_route_end` | exceptional route-end reversal |
| POST | `/admin/dispatch/zones` | `add_zone` | zone creation |
| POST | `/admin/dispatch/zones/{zone_id}/archive` | `archive_zone` | zone archive + dependent-shop rules |
| PUT | `/admin/dispatch/zones/{zone_id}` | `update_zone` | zone edit |
| GET | `/admin/dispatch/zones/archived` | `get_archived_zones` | archive/navigation read |
| POST | `/admin/dispatch/zones/{zone_id}/restore` | `restore_zone` | zone restore |
| PUT | `/admin/dispatch/shop/{shop_id}` | `edit_shop` | admin shop edit + zone move + balance/tax mutation |
| GET | `/dispatch/shortages` | `get_shortages` | shortages read model |
| POST | `/dispatch/shortages` | `add_shortages` | shortages creation + visit/route assignment integration |
| DELETE | `/admin/dispatch/shortages/{shortage_id}` | `delete_shortage` | shortage cancellation/deletion workflow |
| POST | `/admin/dispatch/shops/bulk-import` | `bulk_import_shops` | shop bulk import + zone/shop governance |

**Contract warning:** `dispatch.py` intentionally exposes both `/admin/dispatch/...` and `/dispatch/...` URLs. A future module split must not normalize or rename these paths as a side effect.

## 4. Responsibility map — `driver.py`

### D1. Field authentication / representative identity / session integration

**Functions/endpoints**
- `_require_driver_identity`
- `start_work_session`
- `end_work_session`
- `get_active_session`

**Models/services**
- identity/authorization services (`get_current_identity` and driver/representative identity resolution)
- `RepresentativeProfile`, representative/vehicle assignment models
- `Driver`, `DispatchRoute`, `WorkSession`, `Vehicle`, `VehicleAssignment`
- inventory session snapshot/custody models when a session starts or ends

**Cross-domain dependencies**
- identity/authorization
- representatives/vehicles
- route lifecycle
- custody/inventory

**Transaction / locking / audit invariants**
- session start is not a pure insert: route, representative/driver, vehicle assignment, current session, and custody state are validated together.
- route/session rows are lock-sensitive; extraction must preserve lock ordering and the single transaction that binds the session to operational ownership.
- session start may establish the inventory snapshot used later for reconciliation; it cannot be split into an eventually-consistent secondary operation without an architecture decision.
- session end must keep its close guards and audit/state transitions atomic.

**Tests / coverage anchors**
- direct field-session tests are not isolated by filename in the observed `wa_backend/tests` inventory; behavior is exercised indirectly by cross-domain route/inventory/driver-sale suites.
- identity migration work in `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md` is a mandatory compatibility constraint.
- representative/vehicle binding is constrained by `REPRESENTATIVES_VEHICLES_V1_PLAN.md`.

**Candidate seam**
- `driver/session_access` (candidate only): identity resolution + start/end/active-session orchestration. Do not invent another auth abstraction.

### D2. Work breaks

**Functions/endpoints**
- `toggle_break` — `POST /driver/breaks/toggle`

**Models/services**
- `WorkSession`, `WorkBreakLog`, driver identity/session resolution.

**Invariants**
- one public toggle contract currently owns both entering and leaving break state.
- open-break uniqueness and session ownership must survive any move.

**Candidate seam**
- keep with field-session orchestration unless leadership decides breaks deserve a separate bounded module.

### D3. Visit execution + commercial actions + inventory/finance effects

**Functions/endpoints**
- `update_visit` — `POST /driver/visits/update`

**Models/services**
- `Visit`, `VisitItem`, `VisitReturn`, `Shop`, `ProductVariant`, `ShortageRequest`
- `DispatchRoute`, `WorkSession`
- `InventoryLocation`, `InventoryBalance`, `InventoryMovement`, `ProductBatch`
- commercial context, driver sale resolution, price/UOM resolution, sales-evidence freezing
- debt-limit checks / visit credit exposure
- product lifecycle capability guards
- inventory location guards, inventory-lock checks, FEFO allocation, inventory movement application
- finance posting / COGS paths
- visit reversal/correction helper(s)
- audit/idempotency support where invoked by the visit flow

**Cross-domain dependencies**
- field session + route ownership
- shop/debt/credit
- pricing/UOM/commercial context
- product lifecycle
- inventory/batch/expiry
- returns
- shortages
- finance/COGS
- audit/idempotency

**Transaction / locking / idempotency / audit invariants**
- `update_visit` is a transaction boundary, not merely request mapping.
- stock authority is protected before quantity-affecting actions; product lifecycle guards and inventory locks must keep the current ordering.
- FEFO/batch allocation and vehicle/location movement are part of the same business outcome as visit completion/correction.
- correction/reversal paths must remain symmetric with original postings; moving only the happy-path sale logic would break accounting/inventory reversibility.
- mobile retry/idempotency behavior must stay at the orchestration boundary where the complete outcome is known.
- audit/financial evidence must not be committed independently from the visit state that produced it.

**Tests / coverage anchors observed**
- `wa_backend/tests/test_costed_driver_customer_return_c2_db.py`
- `wa_backend/tests/test_costed_driver_sale_correction_real_c2_db.py`
- `wa_backend/tests/test_catalog_sales_identity_a3.py`
- inventory cost/batch/lifecycle contract suites also cover dependencies used by this path.

**God-function flag:** **YES — highest driver regression risk.** The function coordinates multiple established domains. Future work should first isolate seams without changing transaction ownership.

**Candidate seam**
- `driver/visit_execution` as an orchestration boundary, with calls to existing domain services; not a new inventory/pricing/finance owner.

### D4. Driver custody / transfer handshake

**Functions/endpoints**
- `_load_vehicle_inventory_projection`
- `_load_handshake_product_totals`
- `_load_active_dispatch_handshake_rows`
- `_validate_payload_against_handshake_snapshot`
- `_resolve_handshake_lines_against_source`
- `_handshake_signed_pack_deltas`
- `_load_handshake_lines`
- `_build_handshake_specs`
- `respond_to_driver_transfer`
- `respond_to_driver_constraint_batch`

**Models/services**
- `InventoryTransferHeader`, `InventoryTransferLine`, transfer status/types
- vehicle inventory locations/balances/movements
- `RouteLoadPlan`, `RouteLoadPlanLine`
- `SessionInventorySnapshot` and reconciliation status
- `DispatchRoute`, `WorkSession`, `Vehicle`
- inflight-transfer status resolution, location guards, inventory locks/movement services

**Cross-domain dependencies**
- dispatch-created custody transfers
- vehicle inventory
- active route/session ownership
- session reconciliation

**Transaction / locking / audit invariants**
- response must lock/validate the transfer and its owning session/route before applying inventory effects.
- accepted/rejected/constraint responses are handshake state transitions, not ordinary CRUD.
- snapshot/source comparison prevents stale mobile payloads from silently overwriting authoritative custody state.
- signed pack-delta semantics and source resolution must remain byte-for-byte behaviorally equivalent during extraction.
- batch response must retain all-or-nothing expectations currently enforced by its transaction and validation sequence.

**Coverage anchors**
- `wa_backend/tests/test_special_transfer_action_options.py`
- `wa_backend/tests/test_system_transit_provision_guard.py`
- inventory multi-location / batch restriction tests exercise shared inventory rules.

**Candidate seam**
- `driver/custody_handshake` — these helpers are cohesive and should not become generic `shared` utilities.

### D5. Driver operational read models / route reads / navigation

**Functions/endpoints**
- `driver_dashboard`
- `driver_pending_visits`
- `get_driver_visits`
- `get_visit_details`
- `get_active_session`

**Models/services**
- route/session/visit/shop/zone
- vehicle/custody transfer/snapshot projections
- product/UOM/pricing display helpers where required by response shape

**Cross-domain dependencies**
- dashboard deliberately aggregates multiple domains; extraction must not turn it into a domain owner.

**Invariants**
- response JSON field names, nullability, ordering, IDs, status strings, and URL paths are public contracts.
- read-model extraction must avoid new lazy-load/N+1 regressions.

**Candidate seam**
- `driver/read_models` is plausible, but ownership of `get_active_session` between session and read-model modules is an architecture choice.

### D6. Field shop capture

**Functions/endpoints**
- `driver_add_new_shop` — `POST /driver/shops/add`

**Dependencies**
- `Shop`, `Zone`, representative/driver identity, company scope and shop validation helpers.

**Candidate seam**
- `driver/shop_capture`, or remain with visit/field workflow. It should not be merged into a generic shop-admin helper because field capture has different authorization/context.

### D7. Driver commercial catalog / pricing

**Functions/endpoints**
- `_load_driver_pricing_route`
- `get_products` — `GET /driver/products`

**Dependencies**
- route commercial context
- product variants/UOM contracts
- driver display-price resolution
- product lifecycle capability predicates

**Invariants**
- route-specific pricing/commercial context and UOM display rules are contract-sensitive.
- this seam must consume the pricing/UOM authorities; it must not recreate pricing rules in a driver module.

**Coverage anchors**
- `wa_backend/tests/test_pricing_bulk_catalog_b3_db.py`
- `wa_backend/tests/test_catalog_batch_uom_cache_b3.py`
- `wa_backend/tests/test_catalog_sales_identity_a3.py`

**Candidate seam**
- `driver/commercial_catalog`.

## 5. Responsibility map — `dispatch.py`

### X1. Dispatcher identity / authorization / commercial precondition

**Functions/endpoints**
- `_require_commercial_tax_settings`
- `authorize_dispatch` — `GET /admin/dispatch/authorize`

**Dependencies**
- centralized identity/authorization (`get_current_identity`, role permissions / dispatcher scope)
- system/company tax settings
- active route/session compatibility checks

**Invariants**
- do not replace centralized identity work with raw `is_admin` checks during extraction.
- commercial tax validation is a domain precondition, not a generic auth helper.

**Candidate seam**
- `dispatch/access` for dispatcher scope/authorize; tax guard placement remains a decision.

### X2. Dispatch dashboard / projections / read models

**Functions/endpoints**
- `_dispatcher_route_projection`
- `_route_session_cash_map`
- `_route_session_cash`
- `_route_custody_reconciliation_state`
- `_route_vehicle_inventory_location_ids`
- `dispatcher_dashboard`
- `get_active_routes`
- `list_custody_transfers`

**Dependencies**
- routes, sessions, visits, cash movements
- representatives/drivers/vehicles
- inventory locations/balances/transfers
- reconciliation snapshots

**Invariants**
- these helpers are projection-specific; they are not domain authorities.
- preserve response shape and query batching. Do not replace current batched projections with per-route queries.

**Candidate seam**
- `dispatch/read_models`.

### X3. Settlement / reconciliation

**Functions/endpoints**
- `get_settlement_report` — `GET /admin/dispatch/settlement-report`
- `settle_session` — `POST /admin/dispatch/settle-session/{session_id}`

**Dependencies**
- `WorkSession`, `DispatchRoute`, cash/visit totals
- session inventory snapshot/lines/reconciliation status
- custody transfers and vehicle inventory
- audit trail

**Cross-domain dependencies**
- cash settlement
- inventory custody reconciliation
- route/session lifecycle

**Transaction / locking / audit invariants**
- settlement is a multi-domain close operation; locks/snapshot comparisons and state gates must remain in one authoritative transaction until architecture explicitly says otherwise.
- reconciliation status cannot be updated independently from the evidence it reconciles.
- audit is part of the state transition.

**God-function flag:** `settle_session` is multi-responsibility and high-risk.

**Candidate seam**
- `dispatch/settlement`.

### X4. Dispatch bootstrap / initialization

**Functions/endpoints**
- `initialize_dispatcher` — `POST /admin/dispatch/initialize`

**Dependencies**
- company/dispatcher state and default operational records.

**Candidate seam**
- `dispatch/bootstrap`; keep small rather than putting bootstrap into a generic utilities module.

### X5. Route creation / assignment / load planning

**Functions/endpoints**
- `_get_vehicle_location`
- `_resolve_source_warehouse_id`
- `_available_source_inventory_totals`
- `_allocate_variant_packs`
- `_set_load_plan_snapshot`
- `dispatch_route` — `POST /admin/dispatch/routes`

**Models/services**
- `DispatchRoute`, `Zone`, `Shop`, visits
- representative/driver/vehicle assignment models
- warehouse / vehicle inventory locations
- `RouteLoadPlan`, `RouteLoadPlanLine`
- inventory balances/batches/transfers
- UOM pack conversion
- inventory locks and product-lifecycle capability checks

**Cross-domain dependencies**
- route assignment
- representatives/vehicles
- warehouses
- inventory/custody
- product lifecycle/UOM
- visit generation/navigation

**Transaction / locking / audit invariants**
- route creation also establishes assignment/load/custody expectations; it is not safe to commit the route before load-plan/custody setup if current behavior treats them as one outcome.
- warehouse and vehicle stock calculations rely on stable inventory authority and pack conversion.
- route/driver/vehicle uniqueness and concurrent assignment checks must remain lock-safe.

**God-function flag:** **YES — highest dispatch creation risk.**

**Candidate seam**
- `dispatch/route_planning`, with existing inventory/representative/vehicle authorities called through their established services.

### X6. Route inventory / load-plan synchronization

**Functions/endpoints**
- `get_vehicle_inventory`
- `get_route_inventory_live`
- `_format_item_id`
- `_bound_session_for_route`
- `_variant_map_from_item_ids`
- `_pending_handshake_net_by_variant`
- `_apply_route_pack_deltas`
- `_absolute_targets_to_deltas`
- `_sync_started_session_load_plan`
- `adjust_route_inventory`

**Dependencies**
- vehicle inventory locations/balances/movements/batches
- route load plan
- active work session + session inventory snapshot
- custody transfers/handshake state
- UOM/pack conversion
- inventory lock/location guards

**Transaction / locking invariants**
- `_apply_route_pack_deltas` is a core mutation seam: pack-level request semantics become authoritative quantity/location movements.
- pending handshake quantities are included in effective inventory; dropping this during extraction causes double-load/short stock errors.
- started-session load plan synchronization and snapshot behavior must remain consistent with the same mutation.
- lock order around locations/balances/transfers is regression-sensitive.

**God-function flag:** `_apply_route_pack_deltas` is a domain-spanning orchestration helper and must not be casually promoted to generic inventory service without an architecture decision.

**Coverage anchors**
- `wa_backend/tests/test_inventory_multi_location_authority.py`
- `wa_backend/tests/test_batch_multilocation_read_acceptance.py`
- `wa_backend/tests/test_batch_reservation_owner_contract.py`
- `wa_backend/tests/test_batch_stock_sources_contract.py`
- `wa_backend/tests/test_product_batch_restrictions.py`
- `wa_backend/tests/test_system_transit_provision_guard.py`

**Candidate seam**
- `dispatch/route_inventory`.

### X7. Route lifecycle / exceptional cancellation

**Functions/endpoints**
- `force_cancel_route`
- `update_route_status`
- `undo_route_end`

**Dependencies**
- route/session/visits
- representative/vehicle assignment
- custody transfers
- load plan / session snapshots
- inventory locations/balances/movements
- visit reversal and transfer-reversal services
- audit

**Transaction / locking / audit invariants**
- route state transitions have dependent session, visit, vehicle, assignment, inventory, and custody consequences.
- `force_cancel_route` and `undo_route_end` are exceptional recovery paths; they must remain symmetrical with the normal lifecycle and preserve reversal provenance.
- audit entries are part of the lifecycle evidence.

**God-function flag:** `update_route_status` is a major state-machine god-function; `force_cancel_route` is also high-risk due to compensating actions.

**Candidate seam**
- `dispatch/route_lifecycle`.

### X8. Shop / zone governance and route-safe assignment

**Functions/endpoints**
- `_acquire_advisory_locks`
- `_lock_zones_for_update`
- `_lock_shops_for_update`
- `_blocking_shop_zone_move_route`
- `bulk_update_shops`
- `add_shop`
- `add_zone`
- `archive_zone`
- `update_zone`
- `get_archived_zones`
- `restore_zone`
- `edit_shop`
- `bulk_import_shops`

**Dependencies**
- `Shop`, `Zone`, active routes/visits
- tax jurisdiction validation
- audit logs for manual balance edits
- company scope

**Transaction / locking / audit invariants**
- advisory locks plus row locks serialize conflicting shop/zone mutations.
- zone moves are blocked when a pending visit belongs to an active route; this is an operational invariant, not UI validation.
- edit-shop preserves the existing contract that an empty phone payload does not clear the phone.
- manual shop balance edits emit `SystemAuditLog` evidence.
- archive/restore must preserve dependent-shop/archive provenance semantics.

**God-function flags**
- `bulk_update_shops` and `bulk_import_shops` combine validation, concurrency control, domain mutation, and reporting.

**Coverage anchors**
- `wa_backend/tests/test_archive_owner_navigation.py` is relevant to archive/navigation ownership constraints.
- dedicated filename-level shop/zone API coverage was not isolated in the observed `wa_backend/tests` list; these invariants should therefore be treated as explicit refactor acceptance targets.

**Candidate seam**
- `dispatch/shop_zone_admin` as one candidate. Splitting shops, zones, and imports further requires a decision because their concurrency rules are shared.

### X9. Shortages / urgent replenishment

**Functions/endpoints**
- `get_shortages`
- `add_shortages`
- `delete_shortage`

**Dependencies**
- `ShortageRequest`, `Shop`, `Zone`, `Driver`, `ProductVariant`
- active `DispatchRoute`, pending `Visit`
- product lifecycle guard/capability service (`REPLENISHMENT_NEW`)
- company-local-date service
- dispatch shop/zone locks/advisory locks

**Cross-domain behavior observed**
- shortage creation validates active non-admin drivers and active zones/shops.
- it rejects lifecycle states that cannot accept replenishment.
- when driver is omitted it can resolve ownership from the active route for the zone.
- it serializes `pending-visit:{driver}:{shop}` ownership and may merge/create visit work rather than merely insert a shortage row.

**Transaction / locking invariants**
- product lifecycle guards, driver/zone/shop locks, existing shortage locks, active-route locks, and pending-visit locks form one concurrency-sensitive operation.
- duplicate pending shortage and duplicate pending visit protections must remain intact.

**God-function flag:** `add_shortages` is broader than a shortage CRUD handler because it integrates route/visit ownership.

**Candidate seam**
- `dispatch/shortages`, retaining calls to route/visit/product authorities rather than duplicating them.

## 6. Helper ownership — what is actually shared vs domain-specific

### 6.1 Existing cross-domain services that are valid shared authorities

These are already cross-domain concepts and should be reused rather than reimplemented during a split:

- centralized identity / role permission / dispatcher scope resolution
- company-local-date resolution
- commercial context validation
- driver display pricing and UOM contract resolution
- product lifecycle guards/capability evaluation
- inventory location guards
- inventory lock checks
- FEFO/batch allocation and inventory movement services
- inflight transfer status resolution / transfer reversal
- visit reversal/correction services
- default warehouse resolution where already established as an authority
- finance/COGS posting services where already established

### 6.2 Helpers that should remain domain-specific

Do **not** move these into a generic `shared.py` dumping ground simply because more than one endpoint uses them:

**Driver-specific**
- `_require_driver_identity`
- all `_load_*handshake*`, `_validate_payload_against_handshake_snapshot`, `_resolve_handshake_lines_against_source`, `_handshake_signed_pack_deltas`, `_build_handshake_specs`
- `_load_driver_pricing_route`

**Dispatch-specific**
- `_dispatcher_route_projection`
- `_route_session_cash_map`, `_route_session_cash`, `_route_custody_reconciliation_state`, `_route_vehicle_inventory_location_ids`
- `_get_vehicle_location`, `_resolve_source_warehouse_id`, `_available_source_inventory_totals`, `_allocate_variant_packs`, `_set_load_plan_snapshot`
- `_bound_session_for_route`, `_pending_handshake_net_by_variant`, `_apply_route_pack_deltas`, `_absolute_targets_to_deltas`, `_sync_started_session_load_plan`
- shop/zone advisory/row-lock and blocking-route helpers

A future extraction can colocate these helpers with their owning orchestration module without declaring them global reusable architecture.

## 7. God-functions / multi-responsibility areas

| Rank | Function/area | Why it is risky |
|---:|---|---|
| 1 | `driver.update_visit` | field auth/session + visit state + pricing/UOM + debt + sale/return + inventory/batch + finance/COGS + shortage + correction/idempotency |
| 2 | `dispatch.dispatch_route` | route creation + assignment + vehicle + warehouse + load plan + inventory/custody + visits |
| 3 | `dispatch._apply_route_pack_deltas` | pack conversion + authoritative stock delta + transfer/handshake awareness + load-plan/session synchronization |
| 4 | `dispatch.update_route_status` | route state machine + sessions + visits + assignments + custody/inventory + audit |
| 5 | `dispatch.settle_session` | cash settlement + inventory reconciliation + custody + session/route closure evidence |
| 6 | driver transfer response flows | transfer state machine + session/route ownership + stock movement + snapshot/custody evidence |
| 7 | `dispatch.force_cancel_route` | compensating/reversal path across route/session/visits/transfers/inventory |
| 8 | `dispatch.add_shortages` | shortage + product lifecycle + route owner resolution + pending-visit concurrency/merge |
| 9 | `dispatch.bulk_update_shops` | bulk validation + zone assignment + concurrency locks + active-route constraints |
| 10 | `dispatch.bulk_import_shops` | import parsing/validation + zone/shop mutation + duplicate/conflict semantics |

These are **inventory findings only**. This document does not recommend rewriting them in the same commit as a file split.

## 8. Candidate module map — NOT final architecture

The following map is a low-coupling candidate for discussion. Names and ownership are intentionally non-binding.

```text
wa_backend/api/
  driver/
    session_access.py          # identity + work sessions + breaks + active-session contract
    visit_execution.py         # update_visit orchestration only
    custody_handshake.py       # handshake helpers + transfer responses
    read_models.py             # dashboard/pending/history/detail projections
    commercial_catalog.py      # driver product/pricing/UOM read
    shop_capture.py            # field shop capture

  dispatch/
    access.py                  # authorize / dispatcher scope (tax placement unresolved)
    bootstrap.py               # initialize
    read_models.py             # dashboard/active routes/transfer projections
    settlement.py              # settlement report + settle mutation
    route_planning.py          # create/assign/load-plan orchestration
    route_inventory.py         # live vehicle/route stock + route adjustments
    route_lifecycle.py         # status/undo/force-cancel orchestration
    shop_zone_admin.py         # zone/shop governance + concurrency helpers + bulk import/update
    shortages.py               # urgent replenishment workflow
```

A future implementation should preferably preserve a thin compatibility router façade or equivalent route registration so URLs/methods/dependency contracts do not move accidentally. Whether that façade is the approved architecture is listed as a decision below.

## 9. Highest regression risks to preserve explicitly

1. **`update_visit` atomicity** across visit, stock, batch/expiry, pricing/UOM, debt, returns, finance and correction/idempotency.
2. **`dispatch_route` assignment atomicity** across route, representative/driver, vehicle, warehouse, load plan and custody creation.
3. **Route pack-delta semantics** in `_apply_route_pack_deltas`, including pending handshake stock and started-session synchronization.
4. **Route lifecycle transition/reversal symmetry** among `update_route_status`, `force_cancel_route`, and `undo_route_end`.
5. **Settlement evidence consistency** between cash, session inventory snapshot, custody transfers, reconciliation state and audit.
6. **Driver custody handshake concurrency**: transfer locks, source snapshot validation, accepted/rejected state, signed deltas and batch response.
7. **Inventory lock ordering / FEFO / batch authority** when calls move between files; deadlock or stale-stock regressions are plausible even with identical business code.
8. **Commercial contracts**: route commercial context, 14% tax prerequisite, driver display pricing and UOM conversion must not be duplicated or reordered.
9. **Shop/zone concurrency and active-route blocking**: advisory locks, row locks, pending-visit checks, archive provenance and manual-balance audit.
10. **Public read-model and URL stability**: 39 existing endpoint contracts, mixed `/admin/dispatch` vs `/dispatch` paths, JSON shapes/status strings and batched query behavior.

## 10. Test map and refactor verification implications

The current coverage around these files is cross-domain rather than neatly aligned with future module names. Observed relevant anchors include:

- driver commercial/inventory correctness: `test_costed_driver_customer_return_c2_db.py`, `test_costed_driver_sale_correction_real_c2_db.py`, `test_catalog_sales_identity_a3.py`
- inventory authority/concurrency/batch dependencies: `test_inventory_multi_location_authority.py`, `test_batch_multilocation_read_acceptance.py`, `test_batch_reservation_owner_contract.py`, `test_batch_stock_sources_contract.py`, `test_product_batch_restrictions.py`, `test_system_transit_provision_guard.py`
- transfer/action contracts: `test_special_transfer_action_options.py`, `test_special_action_reason_contract.py`
- catalog/pricing/UOM dependencies: `test_pricing_bulk_catalog_b3_db.py`, `test_catalog_batch_uom_cache_b3.py`, `test_catalog_tracking_batch_b3.py`
- archive/navigation ownership: `test_archive_owner_navigation.py`

No dedicated `test_driver.py` or `test_dispatch.py` file was present in the observed `wa_backend/tests` directory inventory. That means a later refactor should not select tests by filename alone; it must derive the acceptance set from the dependency seams above and add focused contract tests only where existing coverage proves insufficient.

This inventory did not modify or run tests because the task is documentation-only/read-only analysis of production code.

# ARCHITECTURE DECISIONS REQUIRED

The following require leadership/main-conversation approval before a split. This document intentionally does not resolve them.

1. **Driver identity/session ownership:** should `_require_driver_identity` and session orchestration live under a driver API package, or should part of that seam be owned by the centralized identity/representative layer defined by the identity migration plan?
2. **Router compatibility strategy:** during physical extraction, should `driver.py`/`dispatch.py` remain thin compatibility façades that register/re-export the same 39 routes, or should the application register subrouters directly? URL contracts must remain unchanged either way.
3. **`_apply_route_pack_deltas` ownership:** is it dispatch route-inventory orchestration that consumes inventory services, or should some/all of it become an inventory-domain service? Moving it changes domain ownership and is not decided here.
4. **Custody transfer ownership:** where is the canonical orchestration boundary between dispatch-created transfers, driver handshake responses, vehicle custody, and inventory movement?
5. **Settlement boundary:** should cash settlement and inventory custody reconciliation remain one dispatch settlement boundary or be coordinated across finance/reconciliation owners?
6. **Read-model ownership:** should dashboard/active-route/settlement projections be grouped as API read models, or colocated with each write-domain owner?
7. **Tax/commercial precondition placement:** should `_require_commercial_tax_settings` remain dispatch-local or move behind the established commercial/settings authority?
8. **Shop/zone module granularity:** should shop admin, zone lifecycle and bulk import/update stay together because they share locks/active-route constraints, or become separate modules with an explicit coordination service?
9. **Shortage workflow ownership:** shortages currently cross replenishment, active-route driver resolution and pending-visit creation/merge; decide whether dispatch remains owner or coordinates a separate replenishment/visit service.
10. **Driver shop capture ownership:** decide whether field-created shops belong to driver field workflow or the canonical shop domain while preserving different authorization/context rules.

## 11. Safe sequencing note for a later refactor

A future implementation should avoid combining physical moves with behavioral cleanup. A safer sequence is: freeze public contract tests and transaction/locking invariants; extract one cohesive seam at a time with compatibility routing; prove no URL/response/transaction change; then separately consider god-function decomposition only after architecture decisions above are approved.
