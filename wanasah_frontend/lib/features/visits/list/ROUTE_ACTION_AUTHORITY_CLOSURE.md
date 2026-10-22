# Visit route-action authority closure

Frozen V1 workflow: open a Visit, edit/save field work while offline, and let
Backend decide current mutation eligibility. Base:
7ae7f778021547023c31ed93bd59a39feec7dd94.

## Independently verified current Backend contract

Source: wa_backend/api/driver.py update_visit, canonical FIELD dependencies,
domains/vehicles/custody.py, and main.py error envelope. Existing acceptance:
test_driver_session_field_context_cutover.py, test_driver_mixed_visit_authorization_cutover.py,
test_field_read_contracts.py and test_field_return_resolution.py.

- Canonical authenticated company/representative maps to its exact operational
  Driver locator. Visit queries scope company + assigned Driver + Visit.
- Durable idempotency replay returns the original result before current session
  and custody checks. A new mutation locks session, shop, Visit and inventory.
- Active session requires matching company/driver and end_time=None.
  inventory_reconciled_at blocks new mutations. Original Visit session sealing
  or financial is_settled blocks correction; another session cannot adopt it.
- Cancelled Visits reject updates. Current active route must match company,
  Driver and current session and carry a vehicle.
- Shop zone must match route zone unless persisted/request emergency or an
  applicable pending shortage permits the action. Cached Flutter zone fields
  do not contain this complete current evidence.
- Canonical vehicle custody must be unique and active; vehicle must be operational.
  Product/location guards revalidate custody later in the mutation.
- Inventory locks cover touched products and returned Batch keys. Active break,
  is_authorized_to_sell=false and a pending HANDSHAKE for the current receiver
  reject the mutation.
- Return provenance, exact quantities, commercial context, pricing, rewards,
  tax, credit, FEFO and inventory movements remain Backend authorities.
- Several old eligibility refusals still use HTTP detail strings. main.py emits
  canonical fallback HTTP_403 / HTTP_409 plus context and request_id; the client
  preserves these and must not infer a semantic reason from Arabic/free text.

## Before / after

Before: VisitScreen read SecureStorage flags at startup and permanently disabled
editing/submission from that snapshot. Visit List denied form navigation on
cached break/unauthorized, malformed/missing values or read failure.

After: navigation policy permits opening forms without reading cache or making
a live preflight. Visit editing locks only while its own submission is active.
Cached zone refusal is removed because Backend owns current emergency/shortage
allowances. The historical compatibility source is retained as last-known
evidence, with no Visit-screen/navigation consumers and no new writes/cache.

Online submission still uses existing readiness/preview/return orchestration and
the existing durable mutation port. Backend rejection stays rejection and
restores the draft; no refusal is reclassified through message text.

Offline staging gains no eligibility preflight. The existing save port stages
one original UUID/body; pending evidence yields unresolved, never committed
acceptance. Existing commercial prerequisites are unchanged: this is not an
offline replacement for Backend return resolution or a fresh invoice preview.
A previously unresolved command still blocks a new correction. Later rejection
remains recoverable evidence; replay/idempotency/projection code is untouched.

## Separate Add Shop audit

POST /shops checks current active/unsealed session, current assigned active route,
break and sell authorization itself. ShopCreationService/Client performs online
creation and bounded exact UUID/body replay for ambiguous results; it does not
use Visit's durable offline queue. Existing ShopCreationFailure preserves status,
code, context and requestId.

Both the Visit List cached denial and AddShopScreen's cached-break IgnorePointer
could block an otherwise valid online request. Those presentation denials are
removed, without changing Shop creation, UUID, ambiguity, readiness or retry
semantics. This does not add offline Shop creation.

## Ownership and validation

No SyncRepository, Recovery, core/sync, Auth/identity, LocalDatabase, projection,
Transfer, Work Session/Dashboard composition, Backend production, Dashboard web,
design system/theme or closure plan edits. No visual redesign; only stale-lock
banners/interaction gates are removed.

Existing FIELD workflow checks out exact PR HEAD. It runs analyze; all Visit
List/commercial/application/wiring/adapter tests; Offline owner/durable;
correction; pending/local projection; existing Session authority and Shop
reconciliation regressions. Read-only Backend execution covers current route
bodies, FIELD contracts and 17 pre-business-effect authority probes, including
zone emergency/shortage exceptions. Probes stop before mutation success and do
not claim end-to-end database execution.

New Flutter tests exercise stale/absent/malformed cache, inaccessible storage,
one unresolved offline save/no preflight, preserved refusal evidence/no retry/
no correction, source boundaries, and actual Add Shop form editability.
