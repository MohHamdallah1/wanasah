# Flutter V1 End-to-End Field Closure Plan

Status: ACTIVE  
Owner: Flutter V1 lead conversation  
Execution branch: `sol/flutter-v1-field-closure`  
Initial audited base: `be2ddbf4d24085d34727dc6fd339bf6c5997590d`  
Target: field-ready V1 in four days without weakening Backend authority.

## 0. Non-negotiable execution rules

- [x] Read `.rules`, `AGENTS.md`, `ARCHITECTURE.md`, `V1_SCOPE_FREEZE.md`, and `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`.
- [x] Read the damaged-goods / returns / representative-settlement plan before touching field return logic.
- [x] Backend source + current tests, not future modularization documents, define current runtime contracts.
- [x] Keep Flutter work isolated from the parallel Dashboard conversation.
- [x] Flutter branch owns `wanasah_frontend/**` and this plan unless a separately assigned Backend prerequisite is explicitly delegated.
- [ ] Re-read latest `main` before every implementation wave and resolve contract drift before coding.
- [ ] No broad refactor, dependency upgrade, generated-file cleanup, or local destructive command.
- [ ] Backend remains authority for pricing, offers, taxes, FEFO, Batch resolution, inventory status, costing, debt limits, idempotency and reconciliation.
- [ ] Never expose technical IDs such as database `batch_id` to the representative.
- [ ] Every write wave must have focused tests before broader gates.

## 1. V1 field journey that must close

`login -> identity/session recovery -> assigned route/work -> session start -> visits -> shop -> sale/collection/samples/returns -> offline/retry -> transfer handshake -> session end -> settlement/reconciliation handoff`

The application is not V1-done until this journey works with:
- [ ] normal network;
- [ ] network loss before mutation;
- [ ] network loss after an ambiguous mutation result;
- [ ] app restart with pending offline work;
- [ ] token refresh during field work;
- [ ] same-user recovery;
- [ ] blocked unsafe user/company switching;
- [ ] server rejection with preserved recoverable evidence;
- [ ] no duplicate stock/financial mutation.

## 2. Current runtime contract baseline

Verified on the initial base:
- [x] `POST /driver/login`
- [x] `POST /driver/sessions/start`
- [x] `PUT /driver/sessions/end`
- [x] `PUT /driver/sessions/break`
- [x] `GET /driver/dashboard`
- [x] `GET /driver/visits`
- [x] `PUT /visits/{visit_id}`
- [x] `GET /driver/transfers/pending`
- [x] `PUT /driver/transfers/{transfer_id}/respond`
- [x] `POST /shops`
- [x] `GET /product_variants`

Important:
- [x] These compatibility routes are deliberately protected by current Backend tests.
- [x] Proposed routes in `DRIVER_DISPATCH_MODULARIZATION_PLAN.md` are future targets and must not trigger a blind Flutter cutover.
- [x] Reconciled against the independent Backend audit. No main contract drift was found at audit time.
- [x] `GET /driver/sessions/active` is the restart/session-recovery read.
- [x] `GET /visits/{visit_id}` is the visit detail/recovery read.
- [x] `PUT /driver/transfers/batch_respond` exists; runtime limit is 100 items despite a wider schema allowance.
- [x] `POST /driver/session/{session_id}/reconcile` exists as the legacy field reconciliation transport.

## 3. Confirmed P0 blockers / correctness gaps

### 3.1 Customer return / damaged exchange contract

Backend `VisitReturnInput` currently requires:
- `product_variant_id`
- hidden authoritative `batch_id`
- carton/base-pack quantity
- `return_type = Damaged | Expired | Factory_Defect`
- optional reason

Current Flutter:
- [x] omits `batch_id`;
- [x] has only factory-defect/expired fields in the current cart model;
- [x] does not represent ordinary `Damaged` as a first-class return reason;
- [x] projects replacement quantity locally but does not model returned non-sellable vehicle custody by Batch/status.

Required closure:
- [x] Define/verify a Backend-owned Batch-resolution seam for Flutter.
- [x] Deterministic Batch cases resolve server-side automatically.
- [x] Ambiguous cases return only minimal human-readable evidence (lot/expiry/etc.).
- [ ] Flutter stores/sends the resolved opaque resolution token without displaying technical IDs. Adapter + application orchestration are complete; Visit UI/submission wiring remains open.
- [ ] Add Damaged + Expired + Factory_Defect consistently.
- [ ] Preserve carton/pack quantities.
- [ ] Preserve one stable idempotency identity across offline retry/replay.
- [x] Local projection separates AVAILABLE replacement-out from returned non-sellable custody for V1 field UX; unresolved local returns are shown as pending DAMAGED evidence, never merged into authoritative custody totals.
- [ ] Reopen/correction cannot double-apply replacement or returned custody.

This may require one bounded Backend prerequisite on a separately owned worker branch. Do not fake the missing Batch truth in Flutter.

### 3.2 Client-side financial authority

Current Flutter:
- [x] uses Dart `double` and SQLite `REAL` for money;
- [x] calculates invoice totals locally from cached product prices;
- [x] blocks submission locally when its calculated debt limit would be exceeded;
- [x] can therefore reject a transaction based on stale client pricing while Backend pricing/offers/taxes are authoritative.

Required closure:
- [ ] Remove client calculations as authoritative acceptance/rejection rules.
- [ ] Use Backend-authoritative preview/read evidence where available.
- [ ] Offline UI may display a clearly scoped estimate but must not invent final commercial truth.
- [ ] Preserve exact monetary strings/values across transport and durable offline command storage.
- [ ] Eliminate floating-point comparisons from correctness decisions.

### 3.3 Generic HTTP retry policy

Current `AuthInterceptor`:
- [x] automatically retries every HTTP request once after `429`.
- [x] retry decision is not mutation-specific.

Required closure:
- [x] Introduce operation-aware retry classification.
- [x] Auto-replay only requests proven safe/idempotent.
- [x] Durable visit submission reuses the exact same `request_id` and body.
- [x] Non-idempotent/ambiguous mutations reconcile rather than receiving blind generic retry.
- [x] Token-refresh retry remains allowed only under the authenticated-before-handler safety contract.

### 3.4 Offline break semantics

Current Flutter:
- [x] queues break start/end offline;
- [x] immediately changes local break state;
- [x] deletes queued break operations on generic HTTP 400 during replay.

Required closure:
- [x] Backend contract confirms break changes are online/reconcile-only for V1.
- [x] Do not replay stale temporal commands blindly.
- [x] Never treat arbitrary 400 as proof that a deferred command is safely settled.
- [x] Offline tentative break state was removed; break state remains server-confirmed.

### 3.5 Quarantine/recovery data loss

Current Flutter:
- [x] stores rejected/corrupt commands as `quarantined_*`;
- [x] Dashboard exposes a path that deletes all quarantined rows locally.

Required closure:
- [x] Remove destructive “clear all rejected operations” from ordinary field UX.
- [x] Quarantine is evidence/recovery state, not trash.
- [x] Store stable failure classification/code/context/correlation ID where available.
- [x] Allow only safe retry, explicit supersession, or an approved recovery workflow.
- [x] Never lose an unresolved sale/collection/return command silently.


### 3.6 Strict visit payload mismatch

Independent audit confirmed the current Flutter visit command can fail the strict Backend schema:
- [x] Flutter payload includes `visit_id` and compatibility `visitId`; only the path ID is authoritative.
- [x] NoSale additionally emits `no_sale_reason`, while Backend expects the reason in `notes`.
- [x] Canonical Flutter serializer emits only fields accepted by `VisitUpdateRequest`.
- [x] Characterization tests lock Sale / NoSale / Postponed payloads.

### 3.7 UUID durability before first send

Backend visit replay is durable and exact only if Flutter preserves the original UUID and semantic body.
- [x] Current Flutter creates the UUID before direct send but persists the pending command only after failure.
- [x] Persist the durable visit command identity/body before the first mutation attempt.
- [x] Lost response or app crash replays the same UUID/body, never minting a new identity.
- [x] A later deliberate completed-visit correction uses a new UUID only after the prior logical result is resolved.

### 3.8 Confirmed Backend prerequisites for field V1

The independent Backend audit found four genuine field-transport prerequisites. These are not permission to move authority into Flutter.

1. **Returned-Batch resolution seam**
   - [x] Add a FIELD-authorized Backend capability that resolves the returned Batch from owned shop/visit/product plus authoritative provenance/tracking evidence.
   - [x] Deterministic cases resolve internally.
   - [x] Ambiguity requests only the smallest human-readable discriminator.
   - [x] Mutation revalidates the resolved identity.
   - [x] Never expose or ask the representative for database `batch_id`.

2. **Tax jurisdiction for field-created shops**
   - [x] `POST /shops` returns an explicit actionable commercial-readiness completion path.
   - [x] Backend contract does not guess jurisdiction from GPS/zone; Flutter must consume the readiness result.
   - [x] Backend exposes `commercial_readiness` plus `GET /visits/{id}/commercial-state` so Flutter can surface the required Backoffice completion instead of dead-ending.

3. **Authoritative field invoice result/preview**
   - [x] Reuse the existing Backend sale calculator and expose FIELD preview/frozen invoice transport for payable/final totals, rounding and currency.
   - [ ] Flutter cached catalog prices remain display/offline estimate evidence only; client authority cleanup remains open.
   - [x] Backend authoritative invoice seam exists; do not build a second pricing engine in Dart.

4. **Non-sellable vehicle custody read**
   - [x] Add bounded `GET /driver/custody` FIELD projection for supported non-sellable custody including DAMAGED.
   - [x] Preserve hidden Batch authority and expose business-readable product/status/UOM/quantity evidence only.
   - [x] Backend now exposes non-sellable custody separately from AVAILABLE reads.

### 3.9 Shop-create retry and session semantics

- [x] Backend shop creation accepts a stable request UUID, and Flutter now generates/preserves one per logical shop-create command.
- [x] Lost/ambiguous shop creation replays the exact same request UUID/body through the Backend idempotency contract; Flutter never mints a new identity for the unresolved logical command.
- [x] Session start/end have no durable command identity; reconcile active session/dashboard before retry.
- [x] Historical offline break replay is unsupported by Backend because server execution time defines break timing.
- [x] Break start/end are online/reconcile operations for V1; no stale temporal replay queue.

## 4. Offline command engine hardening

Current pending queue is generic `id/type/payload/created_at`.

Target V1 durable command record should support, as needed:
- [x] stable operation/request identity;
- [x] command type;
- [x] owner company + field identity binding;
- [x] exact canonical payload;
- [x] created time;
- [x] state: pending / in-flight-recoverable / blocked (success is removed after finalize);
- [x] retry attempt metadata;
- [x] last stable error code/message/correlation ID;
- [x] no free-text-message decisions inside the durable command engine;
- [x] deterministic FIFO where ordering matters;
- [x] explicit operation-specific replay policy.

Migration rules:
- [x] preserve existing pending rows;
- [x] no destructive migration;
- [x] legacy rows receive safe defaults;
- [x] unattributed active pending work fails closed.

### 4.1 Frozen Offline V1 command model

The existing `pending_sync(type,payload,created_at)` table is retained and migrated in place; no drop/recreate and no deletion of old evidence.

V1 durable command metadata:
- `command_id`: local stable UUID/operation identity; for visit commands it binds to the durable visit `request_id`.
- `state`: `pending | in_flight | blocked`.
- `owner_company_code`: explicit tenant evidence in addition to physical DB isolation.
- `owner_driver_id`: nullable only for migrated legacy rows until safely attributed; new field commands must carry the current field owner when available.
- `attempt_count`: monotonically increasing diagnostic count.
- `last_error_code`: stable machine-readable classification when known.
- `last_error_message`: display/diagnostic fallback only; never business authority.
- `last_request_id`: latest HTTP incident/correlation ID when available.
- `updated_at`: lifecycle timestamp.

Compatibility:
- Keep legacy `type`, `payload`, `created_at` during V1.
- Existing `quarantined_*` rows migrate to/behave as `blocked`; evidence is preserved.
- Legacy rows without command/owner metadata are never silently discarded.
- FIFO remains `created_at ASC, id ASC` among eligible pending commands.

### 4.2 Lifecycle and evidence rules

- [x] A visit command is persisted before its first mutation network attempt so lost-response replay retains durable identity.
- [x] `pending -> in_flight -> success(delete after local finalize)` is the normal path.
- [x] Ambiguous network/5xx result retains the same durable row/identity/body for replay.
- [x] Confirmed business/semantic rejection becomes `blocked` in place.
- [x] Corrupt payload becomes `blocked` in place while raw payload is preserved.
- [x] Unknown command type becomes `blocked` in place; never delete a poison pill.
- [x] Moving to blocked/quarantine is one UPDATE on the same row, not add-then-delete.
- [x] Blocked commands remain ownership-protected unresolved evidence.
- [x] Session/cache clearing fails closed while ANY unresolved command exists, including blocked/quarantined evidence.
- [x] Ordinary representative UI has no “clear all quarantine” or permanent evidence-delete action.
- [x] Retry is operation-specific; corrupt and stale temporal commands are not generic retry candidates.

### 4.3 Operation policy

**Visit update**
- [x] Durable `request_id` + exact semantic body are persisted before first send.
- [x] Lost response replays the same identity/body.
- [x] Successful server replay finalizes local visit/projection exactly once before command deletion using `local_effect_applied`.
- [x] Strict server rejection preserves the command as blocked evidence without pretending the sale committed.
- [x] A deliberate later correction is blocked while prior evidence is unresolved; once resolved, it becomes a new logical UUID.

**Transfer response**
- [x] Store exact transfer ID, decision and rejection reason.
- [x] Local command UUID is for lifecycle/diagnostics; Backend replay truth remains the exact state decision.
- [x] Exact repeated transfer decision may replay; conflicting server decision becomes blocked/actionable.
- [x] Do not reconstruct inventory movement in Flutter.

**Break**
- [x] Backend audit proves historical offline break replay is unsupported.
- [x] Stop creating new `toggle_break` offline commands.
- [x] Do not optimistically change durable break state on network failure.
- [x] Existing legacy queued break commands are preserved as blocked/recovery evidence; they are not replayed later.

**Unknown/corrupt legacy commands**
- [x] preserve row + raw payload;
- [x] mark blocked with stable local reason;
- [x] never delete merely to unblock sync.

### 4.4 Ownership guard

- [x] Any unresolved row—pending, in-flight, blocked, or legacy quarantined—protects the original offline owner.
- [x] Quarantine-only work blocks unsafe driver/company switching exactly like pending financial/stock work.
- [x] Same owner may resume recovery.
- [x] Invalid/missing owner marker with unresolved rows fails closed.
- [x] Refresh/logout cleanup failures never turn a blocked ownership decision into allow.

### 4.5 Offline slice ownership

Lead Offline branch will own only:
- `wanasah_frontend/lib/core/db/local_database.dart`
- new `wanasah_frontend/lib/core/sync/**`
- `wanasah_frontend/lib/repositories/sync_repository.dart`
- `wanasah_frontend/lib/repositories/dashboard_repository.dart` only for removing deferred break persistence
- `wanasah_frontend/lib/blocs/auth/offline_owner_guard.dart`
- Flutter quarantine UI/event/BLoC code only to remove destructive evidence deletion
- focused tests for this slice

It will not touch Backend, web Dashboard, pricing/returns UI, or the Network worker-owned `core/network/**`.

## 4.6 Offline foundation stability point — 2026-10-22

- [x] Implementation branch: `sol/flutter-v1-offline-durable-commands`.
- [x] PR #424 merged into `sol/flutter-v1-field-closure` only; main remains untouched.
- [x] Merge commit: `0ec2a748ad7deb0acfcb627e5d558a2639746801`.
- [x] SQLite upgraded in place to V10; legacy command evidence is preserved.
- [x] `PendingCommandStore` mechanically extracted while `LocalDatabase` keeps compatibility facades.
- [x] Persist-before-send implemented for visit mutations.
- [x] `local_effect_applied` prevents double local projection after crash/replay.
- [x] FIFO fails closed on blocked evidence; later commands do not leapfrog it.
- [x] Offline break replay removed; break transitions require live/reconciled server state.
- [x] Field quarantine/recovery UI is read-only; no destructive clear action.
- [x] GitHub `flutter analyze`: PASS.
- [x] Focused `offline_owner_guard_test.dart` + `offline_durable_command_test.dart`: PASS.
- [ ] AVAILABLE vs DAMAGED local inventory projection remains a separate V1 projection wave.
- [x] Completed online visit correction now applies AVAILABLE vehicle inventory by old-to-new delta; returned non-sellable custody remains separate.
- [ ] Full Flutter suite / Android build / real-device offline acceptance remain final gates.

## 4.7 Network + visit-command stability point — 2026-10-22

- [x] Network foundation PR #426 merged into `sol/flutter-v1-field-closure` only.
- [x] Network merge commit: `1c3cc63d07617126ca387492f5cf77faa7f1944a`.
- [x] Network `flutter analyze`: PASS.
- [x] Focused retry / ApiFailure / AuthInterceptor tests: PASS.
- [x] Visit correction PR #427 merged into `sol/flutter-v1-field-closure` only.
- [x] Visit correction merge commit: `a1fa6d123ad417433fb9ab811476d0b3906c5ef1`.
- [x] Canonical Sale / NoSale / Postponed serializer removes compatibility-only HTTP fields.
- [x] Money is serialized as fixed three-decimal strings at the visit transport boundary.
- [x] Completed visit AVAILABLE projection uses old-to-new delta instead of double-deducting the replacement command.
- [x] Integrated Network + Offline + Visit `flutter analyze`: PASS.
- [x] Integrated focused Offline + Visit tests: PASS.
- [ ] Returned-Batch resolution, Damaged reason/UI, and non-sellable vehicle custody remain open.
- [ ] Backend-authoritative invoice preview/final commercial truth UI/submission wiring remains open; application use-cases are complete.
- [x] Auth/session typed-failure adoption completed and merged.

## 5. Error model / observability

- [x] Introduce a typed Flutter API failure model.
- [x] Parse stable `code`, structured `context`, status and correlation/request ID.
- [x] Keep localized server text for display only inside Network classification.
- [ ] Remove business branching on Arabic/free-text messages.
- [ ] User-facing errors must distinguish:
  - connectivity,
  - authorization/session expiry,
  - business rejection,
  - retryable transient failure,
  - ambiguous committed-state failure,
  - local persistence/recovery failure.
- [ ] Attach Sentry context without logging secrets/tokens/full sensitive payloads.

## 6. Authentication / identity / tenant safety

Already strong and must be preserved:
- [x] physically separate SQLite database per company code;
- [x] active pending queue owner guard;
- [x] different-driver same-company login blocked when unsafe pending work exists;
- [x] cross-company switching blocked when unsafe pending work exists;
- [x] logout preserves pending work.

Closure:
- [ ] Verify current login/refresh response against canonical field principal/representative mapping.
- [ ] Bind durable commands to the stable identity required by current Backend field contract.
- [ ] No legacy `Driver.is_admin` or client role flag becomes authority.
- [x] Token refresh / unauthorized logout cannot wipe pending work; unresolved offline evidence is preserved.
- [x] Same-user app restart restores a complete validated stored identity and selects the correct tenant DB without destructive repair guesses.
- [ ] Final same-user restart acceptance still verifies resumed pending sync state end-to-end on device.

### 6.1 Auth / session recovery stability point — 2026-10-22

- [x] Implementation branch: `sol/flutter-v1-auth-session-recovery`.
- [x] Typed login failure policy uses `ApiFailure` status/code/context/request ID.
- [x] 401/403 are confirmed auth rejection; 429 is rate-limit; network/timeout are connectivity; 5xx is server failure.
- [x] Localized/free-text server content is display fallback only, not auth classification.
- [x] Offline-owner guard remains before returned session persistence.
- [x] Ambiguous refresh transport/5xx does not force logout.
- [x] Only confirmed refresh 401/403 reaches unauthorized logout.
- [x] Stored identity restore fails closed on missing/blank/`null` tokens, invalid driver IDs, or missing company code.
- [x] CheckAuth failure performs no destructive local cleanup.
- [x] User logout preserves unresolved offline evidence.
- [x] New helper responsibilities are organized under `features/auth/application/**` and `features/auth/presentation/**`.
- [x] PR #432 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `6ac2f48f2539cf12bb7524e08a6a686682b73113`.
- [x] GitHub `flutter analyze`: PASS.
- [x] Focused Auth/session tests: PASS.
- [x] Offline durable-command regression gate: PASS.
- [ ] Canonical principal/representative identity mapping remains a separate contract check before final field acceptance.

## 7. Session / route / custody

- [ ] Start session requires current location and correct route/vehicle/custody prerequisites.
- [ ] Do not duplicate Backend custody/vehicle-operational checks in Flutter as authority.
- [ ] Show actionable Backend rejection states instead of generic SnackBars.
- [ ] End session remains online/reconciled where Backend requires pending handshake/custody closure.
- [ ] Pending transfer acceptance/rejection preserves exact decision and reason.
- [x] Backend transfer response is state-idempotent for exact repeated accepted/rejected decisions on current base.
- [ ] Flutter replay must preserve that exact decision and must surface conflicting prior decisions.
- [ ] Batch transfer UI and single transfer UI share one command model.

## 8. Visit workflow / commercial action closure

- [ ] Pending / completed / postponed semantics match Backend.
- [ ] Sale requires real sold quantity.
- [ ] NoSale supports samples, returns, or prior-debt collection according to Backend.
- [ ] Postponed contains no financial/inventory actions.
- [ ] Samples require reason and preserve canonical quantities.
- [ ] Bonus/reward quantity is never client-authoritative.
- [ ] Flutter never sends a sale price or chooses FEFO Batch.
- [ ] Shop debt/cash inputs use exact money transport.
- [ ] Server response/rejection drives final outcome.
- [ ] Existing completed/offline visit edit/reopen behavior is audited before preservation.

## 9. Local inventory projection

Current model aggregates cartons/packs by product only.

Closure:
- [ ] Treat local stock as a projection, never inventory SSOT.
- [x] Keep AVAILABLE sellable quantity distinct from non-sellable returned custody; Backend custody and pending local return evidence are separate presentation/read models.
- [x] Do not invent Batch allocation locally; pending local custody derives only product/reason/quantity evidence from the durable command and exposes no Batch identity.
- [ ] Re-sync safely after accepted transfer, visit submission and recovery.
- [ ] Offline edits reverse only their own local projection exactly once.
- [ ] No clamp-to-zero behavior may silently hide a negative/inconsistent projection; surface reconciliation error instead.

## 10. Flutter target architecture

Do not create “clean architecture ceremony” for every trivial file. Use feature ownership + small shared infrastructure.

Target direction:

```
lib/
  app/
    app.dart
    bootstrap.dart
    router/
    theme/
  core/
    errors/
    network/
    persistence/
    sync/
    money/
    observability/
  features/
    auth/
      data/
      application/
      presentation/
    work_session/
      data/
      application/
      presentation/
    visits/
      data/
      application/
      presentation/
      sale/
      returns/
      samples/
    custody/
      data/
      application/
      presentation/
    shops/
      data/
      application/
      presentation/
  shared/
    ui/
    formatting/
```

Architecture policy — frozen for V1 and future expansion:
- [x] Feature-first ownership is mandatory for new/extracted product code.
- [x] Single Responsibility Principle is mandatory: one file/class should have one primary reason to change.
- [x] `core/**` is reserved for genuinely cross-cutting infrastructure, not business-feature dumping grounds.
- [x] New business contracts/models live under their owning feature/domain.
- [x] Tests mirror production feature ownership.
- [x] Generic dumping folders such as `helpers/`, `utils/`, `misc/` are forbidden unless the contents are truly cross-cutting and narrowly defined.
- [x] Prefer small cohesive folders/files over one mega client/repository/BLoC.
- [x] Mechanical extraction must preserve behavior and pass focused characterization before the checkbox is closed.
- [x] Compatibility facades/exports may remain temporarily when they reduce migration risk, but new logic goes to the feature-owned location.

Rules:
- [ ] Screens do not call `ApiClient` directly.
- [ ] Widgets do not decide Backend business authority.
- [ ] Repositories own transport/persistence boundaries.
- [ ] Application controllers/BLoCs orchestrate one feature, not the whole app.
- [ ] Offline command engine is shared infrastructure with typed operation adapters.
- [ ] Files should remain reviewable; split by responsibility before god-files grow again.
- [ ] Avoid a single mega repository or mega BLoC replacing current mega screens.

### 10.1 V1 decomposition strategy — preserve behavior first

We will not choose between a pure file move and a full rewrite. The V1 strategy is staged:

**Stage A — mechanical extraction with zero intended behavior change**
- [ ] Move cohesive widgets, DTOs, mappers, repository helpers and persistence helpers out of god files while preserving public behavior and contracts.
- [ ] Keep existing event/state semantics during the first extraction unless a proven V1 defect requires change.
- [ ] Add focused characterization tests around the behavior being moved before or with the extraction.
- [ ] One extraction owns a narrow file set and must remain reviewable as a standalone diff.

**Stage B — responsibility split only where V1 needs correctness work**
- [ ] Separate transport/persistence/orchestration from presentation for Offline, Visit, Returns, Session and Custody because these areas require contract fixes now.
- [ ] Replace duplicated client business authority only where the Backend contract is already authoritative and verified.
- [ ] Do not rewrite stable code merely to fit the target folder tree.

**Stage C — post-V1 cleanup**
- [ ] Defer broad renames, aesthetic layering, dependency changes and non-blocking abstractions until after field acceptance.
- [ ] Leave an explicit debt note for any god-file region intentionally kept for V1.

Decision rule:
- If a split reduces collision/risk for code we are about to change, do it now.
- If a split is only cosmetic and does not improve V1 safety, testing or ownership, defer it.
- Never combine a large behavior rewrite with a large file move in the same wave.

This prevents two opposite failures: shipping new V1 logic deeper into current god files, or spending the four-day closure window on architecture for its own sake.


### 10.2 Frozen audit classification

Independent Flutter architecture audit confirmed staged extraction rather than rewrite.

**B — responsibility correction required for V1**
- `ApiClient` retry/error responsibilities.
- durable sync/queue.
- `LocalDatabase` command/projection responsibilities.
- `SyncRepository`.
- Visit commercial/returns logic.
- work-session/break.
- quarantine/recovery.
- completed-visit correction.

**A — mechanical extraction first**
- Visit presentation widgets.
- Dashboard presentation widgets.
- Visit List presentation.
- app/bootstrap/theme.
- DTOs and payload mappers before behavior change.

**C — leave largely intact until after V1**
- broad `AuthBloc` restructuring.
- `VisitListBloc` redesign.
- `LocationService` redesign.
- router framework migration.
- dependency modernization.
- cosmetic architecture cleanup.

The line count is not the criterion. Ownership/correctness risk is.

Known extraction targets and V1 timing:
- [x] Network core: `ApiClient` auth/retry/error responsibilities extracted into focused files.
- [x] Auth typed-failure and stored-identity helpers placed under `features/auth/application/**`; user-facing auth messages under `features/auth/presentation/**`.
- [x] `local_database.dart`: durable command lifecycle extracted to `PendingCommandStore`; compatibility facade retained.
- [ ] `local_database.dart`: remaining visit/inventory projection persistence split when Returns/Custody wiring lands.
- [x] `visit_bloc.dart`: canonical payload serializer and local projection helpers extracted before further Visit behavior work.
- [x] `visit_bloc.dart`: Event/State declarations extracted behind compatibility exports.
- [x] `visit_bloc.dart`: completed-visit restoration, cart policy, submission mapping, and submission use-case extracted before FIELD seam wiring; Bloc reduced to orchestration shell.
- [x] `visit_screen.dart`: catalog/product-card presentation mechanically extracted before Returns/Batch UI changes; screen reduced from ~1445 to ~1018 lines.
- [ ] `visit_screen.dart`: residual shell/footer/contact/submit presentation split only when the next owned responsibility requires it.
- [x] `dashboard_bloc.dart`: Work Session and Custody responsibilities mechanically extracted before behavior work.
- [x] `dashboard_bloc.dart`: Recovery/quarantine/sync classification extracted behind feature-owned RecoveryReader/RecoverySyncCoordinator; compatibility counts/events remain only as wiring.
- [x] `dashboard_screen.dart`: Work Session controls, pending-transfer dialog, and vehicle-inventory presentation extracted into feature-owned presentation files.
- [x] `dashboard_screen.dart`: Recovery/sync presentation extracted to `features/recovery/presentation/**`; residual summaries/navigation shell remains.
- [ ] `sync_repository.dart` (~480 lines): extract operation-specific Visit/Transfer/Shop adapters as those contracts are wired.
- [x] Visit List / Route Execution responsibility extracted into `features/visits/list/{application,data,presentation}`; `VisitListBloc` remains a thin compatibility shell and `VisitListScreen` a composition/navigation shell.
- [ ] app/bootstrap/theme extraction: perform with the design-system wave, not before P0 contracts close.

### 10.3 Frozen decomposition execution order

This is not a separate refactor project. Each split happens immediately before the feature area is changed:

1. [x] Network seam split before Network behavior hardening.
2. [x] Durable command persistence split before Offline lifecycle hardening.
3. [x] Visit command serializer/projection helper split before Visit contract correction.
4. [x] Mechanically extract `VisitCatalog` / product-card presentation and Visit Event/State declarations with zero intended behavior change.
5. [x] Extract completed-visit restoration, cart policy, sale/sample/return submission mapping, and financial submission use-case before FIELD seam wiring.
6. [x] Mechanically extract Work Session and Custody application/presentation responsibilities before behavior implementation.
7. [x] Split Recovery/quarantine/sync read, classification, orchestration and presentation into `features/recovery/**`.
8. [ ] Split app/bootstrap/theme immediately before the field-first UI redesign.
9. [ ] Post-V1 only: cosmetic renames, broad folder migration, dependency modernization, and non-blocking abstractions.

Rule: a decomposition checkbox becomes `[x]` only after focused characterization/analyze gates pass. A partial extraction never marks the whole god-file as complete.

### 10.4 Backend FIELD seam stability point — 2026-10-22

- [x] Backend branch: `codex/flutter-v1-backend-field-seams`.
- [x] Exact implementation HEAD: `d2498f46aeba050f5d6cb43ca6d0d568fb39e585`.
- [x] Exact GitHub Actions run `39682777565`: PASS.
- [x] Returned-Batch resolution contract: PASS.
- [x] Shop commercial/tax readiness contract: PASS.
- [x] Authoritative invoice preview/frozen-read contract: PASS.
- [x] Non-sellable vehicle custody contract: PASS.
- [x] Real PostgreSQL FIELD acceptance: PASS, zero skipped.
- [x] Legacy FIELD transport compatibility coverage: PASS.
- [x] PR #428 merged to `main`.
- [x] Backend merge commit: `8aa76c2099024e627da0cae34f15da9310020d7c`.
- [x] Feature-owned Flutter typed adapters for Visit/Custody FIELD seams are complete and merged.
- [ ] Visit/Custody behavioral wiring for those adapters remains open.

### 10.5 Visit mechanical decomposition stability point — 2026-10-22

- [x] Implementation branch: `sol/flutter-v1-visit-decomposition`.
- [x] `VisitCatalog` + product-card presentation extracted to `features/visits/presentation/visit_catalog.dart`.
- [x] Visit Events extracted to `features/visits/application/visit_event.dart`.
- [x] Visit States extracted to `features/visits/application/visit_state.dart`.
- [x] Legacy `visit_bloc.dart` imports remain compatible through explicit exports.
- [x] `visit_screen.dart` reduced from ~1445 to ~1018 lines without intended behavior change.
- [x] `visit_bloc.dart` reduced to ~378 lines.
- [x] PR #430 merged into `sol/flutter-v1-field-closure` only.
- [x] Merge commit: `3afb27403573296bfe0a6dd67f15c8a0041544fd`.
- [x] GitHub `flutter analyze`: PASS.
- [x] Focused decomposition characterization: PASS.
- [x] Existing Visit command-correction regression: PASS.
- [ ] Remaining Visit shell/orchestration is split only as the next Returns/Finance responsibility requires it; no cosmetic rewrite.

### 10.6 Session / Custody mechanical decomposition stability point — 2026-10-22

- [x] Implementation branch: `sol/flutter-v1-session-custody-decomposition`.
- [x] Work Session application logic extracted to `features/work_session/application/work_session_handlers.dart`.
- [x] Work Session controls extracted to `features/work_session/presentation/work_session_controls.dart`.
- [x] Custody transfer orchestration extracted to `features/custody/application/custody_handlers.dart`.
- [x] Pending-transfer dialog extracted to `features/custody/presentation/pending_transfer_dialog.dart`.
- [x] Vehicle-inventory presentation extracted to `features/custody/presentation/vehicle_inventory_section.dart`.
- [x] `dashboard_bloc.dart` reduced by ~36.9% in the mechanical wave.
- [x] `dashboard_screen.dart` reduced by ~41.4% in the mechanical wave.
- [x] GitHub run `39688931001`: `flutter analyze` PASS + 14 focused/regression tests PASS.
- [x] PR #434 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `19a04e76085db29a265e84fadf33c64ec5088793`.
- [x] Work Session `part of DashboardBloc` coupling removed; Work Session authority now lives behind feature-owned data/application boundaries.
- [ ] Custody transitional DashboardBloc coupling remains until the Custody behavioral wave.
- [x] Recovery/quarantine/sync business classification and presentation are removed from the Dashboard shell; only compatibility count/event wiring remains.

### 10.7 Visit commercial decomposition stability point — 2026-10-22

- [x] Implementation branch: `sol/flutter-v1-visit-commercial-decomposition`.
- [x] Completed-visit restoration extracted to `features/visits/application/completed_visit_restorer.dart`.
- [x] Cart quantity/inventory mutation policy extracted to `features/visits/application/visit_cart_policy.dart`.
- [x] Sale/sample/legacy-return transport mapping extracted to `features/visits/data/visit_submission_mapper.dart`.
- [x] Visit submission use-case extracted to `features/visits/application/visit_submission_service.dart`.
- [x] Submission use-case is decoupled from `VisitReady` / Bloc state and receives explicit inputs only.
- [x] `visit_bloc.dart` reduced to ~187 lines and remains the compatibility orchestration shell.
- [x] Canonical Visit serializer remains the mutation-body authority.
- [x] PR #435 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `2697caf44152b04e23d9c55cc4c455237b0aa84d`.
- [x] GitHub `flutter analyze`: PASS.
- [x] Visit commercial decomposition tests: PASS.
- [x] Visit decomposition regression: PASS.
- [x] Visit command-correction regression: PASS.
- [x] Offline durable-command regression: PASS.
- [ ] FIELD Return Resolution / Damaged / commercial-readiness / authoritative invoice UI/submission wiring remains open; application orchestration is complete.
- [ ] Legacy Factory_Defect/Expired mapping remains compatibility behavior until the new feature-owned Return Resolution contracts are integrated.

### 10.8 Feature-owned FIELD adapter stability point — 2026-10-22

- [x] Existing PR #429 architecture correction completed at `e9f42b32ea9f02d8a37eca8b590da1df49e71b0e`.
- [x] Mixed `core/field/**` production/test buckets removed completely.
- [x] Visit FIELD contracts live under `features/visits/**`.
- [x] Custody FIELD contracts live under `features/custody/**`.
- [x] Shared `core/errors/api_failure_exception.dart` and `core/serialization/json_contract.dart` contain technical cross-cutting concerns only.
- [x] VisitFieldClient owns return resolution, commercial readiness, invoice preview and committed/frozen invoice read.
- [x] CustodyClient owns non-sellable custody read only.
- [x] Exact opaque tokens and decimal strings are preserved.
- [x] Public business models expose no raw database `batch_id`.
- [x] GitHub run `39693684776`: analyze PASS; Visits 29 PASS; Custody 15 PASS; Offline regression 23 PASS; ownership gate PASS.
- [x] PR #429 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `5f1419edadf4ff2c77c4a5920236f47c1805a05d`.
- [ ] Visit FIELD UI/submission behavioral wiring remains open and is assigned to Codex; feature-owned FIELD application orchestration is complete.
- [ ] Custody behavioral wiring remains open.

### 10.9 Shop creation stability point — 2026-10-22

- [x] Feature-first structure added under `features/shops/{domain,data,application}`.
- [x] AddShopScreen no longer owns direct `ApiClient` transport.
- [x] One stable `request_id` is generated per logical shop-create command.
- [x] Ambiguous network/timeout/5xx result replays the exact same command identity/body through Backend idempotency.
- [x] Same-screen explicit retry preserves the unresolved request identity instead of minting a new UUID.
- [x] `commercial_readiness` is modeled explicitly; Flutter does not infer tax jurisdiction.
- [x] Shop domain is independent from Dio/ApiFailure implementation types; network adaptation stays in data layer.
- [x] GitHub Shop creation gate: analyze PASS + focused Shop tests PASS.
- [x] Offline durable-command regression: PASS.
- [x] PR #437 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `d91aa92aa4d453e66b246b25127926b795c46fd4`.

### 10.10 Work Session behavioral stability point — 2026-10-22

- [x] Implementation branch HEAD: `d887520c09be31a1f6a537b09d1ad11d0ceb0492`.
- [x] Work Session owns transport, active-session read model, mutation/reconciliation orchestration, typed failures and presentation result mapping.
- [x] Legacy `work_session_handlers.dart` / Dart `part of DashboardBloc` coupling removed.
- [x] Start Session uses Backend authority and reconciles ambiguous outcomes via active-session read.
- [x] Restart recovery uses `GET /driver/sessions/active` as authoritative truth.
- [x] Break remains online/reconcile-only with no deferred/offline mutation command.
- [x] End Session never silently closes locally after ambiguous response; it reconciles active-session state.
- [x] Free/localized text is display fallback only; no Work Session decision branches on it.
- [x] GitHub run `39694394292`: analyze PASS + 36/36 focused/regression tests PASS.
- [x] PR #438 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `b2b71651c43601a38b365fa7d87316a0eef77ada`.
- [ ] Custody behavioral closure remains separate.
- [x] Recovery/sync UX behavioral closure completed and integrated.

### 10.10a Visit FIELD application stability point — 2026-10-22

- [x] Implementation branch: `codex/flutter-v1-visit-field-application`.
- [x] Exact implementation HEAD: `78f2aa0b046cd3a03a1d342b21dc7917f727269b`.
- [x] Return Resolution application flow owns deterministic resolution and explicit ambiguity follow-up.
- [x] Opaque resolution token and Backend-provided human evidence are preserved without Batch inference.
- [x] Authoritative invoice preview and committed/frozen invoice reads are separate typed application use-cases.
- [x] Exact financial strings remain exact through the application layer; no authoritative float conversion was added.
- [x] Commercial readiness read is typed and preserves canonical code/required action without geographic inference.
- [x] Capability-specific failure/result types remain separate; no giant FIELD result union.
- [x] Application boundary imports no Flutter widgets, BLoC, LocalDatabase, SyncRepository or peer feature.
- [x] Exact-head GitHub run `39702349730`: analyze PASS; 25 application/architecture tests PASS; 29 existing Visit adapter tests PASS; 23 Offline regression tests PASS.
- [x] PR #439 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `373cc3943c139706d30bdacd632622a9526b93c3`.
- [ ] Visit FIELD UI/submission wiring remains the next Codex wave.
- [ ] Local projection / returned non-sellable custody integration remains separate.

### 10.11 Recovery / Sync UX behavioral stability point — 2026-10-22

- [x] Worker branch completed at `e9f316689d61c01b108881fc38b6114f08618c65`.
- [x] Worker branch was intentionally not rebased; current-lead integration used a fresh branch because the historical branch diverged.
- [x] Current-lead Dashboard files were verified byte-identical to the worker's assigned Work Session base before Recovery changes were ported.
- [x] Recovery read model lives under `features/recovery/application/**` and preserves command identity, normalized type, state, attempts, stable error code, request ID and safe display evidence.
- [x] Recovery data access lives behind `features/recovery/data/**`; DashboardScreen no longer reads raw SQLite recovery rows.
- [x] Pending and blocked/recovery-required work are typed and distinct.
- [x] Legacy `quarantined_*` normalization reuses the existing durable-command contract.
- [x] Blocked evidence remains visible and non-destructive; no Clear All/delete-to-hide-error path exists.
- [x] Sync success requires authoritative re-read with both pending=0 and blocked=0.
- [x] Pending-after-sync -> incomplete; blocked-after-sync -> recovery required; timeout/ambiguous -> unresolved.
- [x] Recovery UI exposes no invented generic retry and generates no new command ID/body.
- [x] Localized/free text is display-only and never drives recovery classification.
- [x] DashboardScreen reduced from ~632 to ~391 lines in the Recovery wave.
- [x] PR #442 integrated the accepted Recovery closure onto the latest `sol/flutter-v1-field-closure`.
- [x] Integration merge commit: `92ab71ae3f65f32421824103176308f92d28ec8b`.
- [x] Superseded historical PR #440 closed without merge.
- [x] Current-lead Recovery workflow: PASS.
- [x] Current-lead Offline durable-command regression: PASS.
- [x] Current-lead Work Session regression: PASS.
- [x] Current-lead Session/Custody decomposition regression: PASS.
- [ ] Old DashboardLoaded offline/quarantine count fields and ForceSyncData event remain compatibility wiring only and may be removed post-V1 or when the Dashboard read model is redesigned.

### 10.12 Visit FIELD application orchestration stability point — 2026-10-22

- [x] Implementation branch: `codex/flutter-v1-visit-field-application`.
- [x] Final implementation HEAD: `78f2aa0b046cd3a03a1d342b21dc7917f727269b`.
- [x] `ReturnResolutionCoordinator.resolve` provides deterministic/ambiguous/structured-failure outcomes.
- [x] `ReturnResolutionCoordinator.submitEvidence` submits only Backend-requested human/business evidence and preserves opaque resolution semantics.
- [x] `PreviewVisitInvoice.execute` preserves authoritative preview values as exact strings.
- [x] `ReadCommittedVisitInvoice.execute` keeps frozen/committed invoice evidence distinct from preview.
- [x] `ReadCommercialReadiness.execute` exposes typed ready/action-required outcomes without local tax/geography inference.
- [x] Application result types remain capability-specific; no generic mega Visit FIELD result.
- [x] Application layer has no Flutter widget, BLoC, LocalDatabase, SyncRepository or peer-feature authority.
- [x] Raw database `batch_id` is not exposed by the application API.
- [x] Exact token/money values and original structured ApiFailure evidence are preserved.
- [x] Exact-HEAD GitHub run `39702349730`: analyze PASS; 25 application/architecture PASS; 29 adapter PASS; 23 Offline regression PASS.
- [x] PR #439 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `373cc3943c139706d30bdacd632622a9526b93c3`.
- [ ] Operator-facing Return Resolution / Damaged / invoice / commercial-readiness wiring remains the next Codex slice.
- [ ] Durable submission integration still must carry the resolved opaque return evidence without changing request-id ownership.

### 10.13 Pending local return custody projection stability point — 2026-10-22

- [x] Lead branch: `sol/flutter-v1-local-custody-projection`.
- [x] Final implementation HEAD: `5fa445a5d69fbc7e9d3ef093f345dee6916836a0`.
- [x] Pending return custody is derived from unresolved durable `submit_sale` commands instead of creating a second local inventory authority/table.
- [x] Only commands with `local_effect_applied=1` contribute pending local custody evidence; strict rejected commands with no local effect do not appear as custody.
- [x] Pending / in-flight / blocked evidence states remain distinct.
- [x] Damaged / Expired / Factory_Defect business reasons are preserved; physical local custody status is DAMAGED per the verified Backend Visit return contract.
- [x] Unknown return reasons fail closed and are not projected as DAMAGED by guesswork.
- [x] Legacy `quarantined_draft_sale` normalizes through the accepted durable-command type contract without losing blocked evidence.
- [x] Pending local custody remains visually separate from Backend-authoritative non-sellable custody; quantities are never summed into a false authoritative total.
- [x] Offline/restart Dashboard reads pending return custody directly from durable evidence.
- [x] No raw Batch identity is introduced or exposed.
- [x] PR #445 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `56360e320b81ca6b6a96353a70194154b4a15dba`.
- [x] Local custody projection workflow: PASS.
- [x] Custody behavioral regression: PASS.
- [x] Offline durable-command regression: PASS.
- [x] Recovery regression: PASS.
- [x] Work Session regression: PASS.
- [x] Session/Custody decomposition regression: PASS.
- [x] FIELD ownership/adapters regression: PASS.
- [ ] Completed/corrected return end-to-end acceptance still waits for the Visit FIELD wiring slice and final real-device journey.
- [ ] Silent clamp-to-zero behavior in AVAILABLE projection remains separate technical debt and is not marked closed by this wave.

### 10.14 Visit List / Route Execution behavioral stability point — 2026-10-22

- [x] Worker branch: `sol/flutter-v1-visit-list-route-closure`.
- [x] Worker implementation HEAD: `160d1697b4d4d9ec62a8ec29b4be8b3487e8173b`.
- [x] Feature tree organized under `features/visits/list/application/**`, `data/**`, and `presentation/**`.
- [x] `VisitListScreen` reduced from 518 to 258 lines and no longer owns filtering/counting/raw DB parsing/refresh classification/direct SecureStorage gating/map implementation.
- [x] `VisitListBloc` delegates to feature-owned reader and refresh coordinator and no longer owns LocalDatabase/SyncRepository/raw SQLite parsing.
- [x] Deterministic ordering is sequence ASC then Visit ID ASC.
- [x] Normal vs emergency route classification uses canonical `isEmergency`, never translated labels.
- [x] Completed/Pending filters and counts use Backend status as authority.
- [x] Canonical Backend semantics preserved: Sale/NoSale remain Completed; Postponed remains Pending. Legacy/noncanonical Pending+outcome rows are presentation-only and never rewrite Backend status.
- [x] Active filter survives local reload/return from Visit screen.
- [x] Refresh outcomes are typed; free/localized text never drives retry/business classification.
- [x] Existing SyncRepository remains the transport; no second sync engine was introduced.
- [x] Add Shop/Open Visit action gating is centralized behind one fail-closed compatibility boundary.
- [x] Map coordinates/link handling moved behind typed map target/launcher boundaries with unsafe schemes rejected.
- [x] New/touched Visit List copy lives behind feature-owned strings; translated text does not drive machine state.
- [x] Worker exact-head run `39704281436`: analyze PASS; 56 focused/regression tests PASS.
- [x] Current-lead PR #446 had zero ownership overlap with the 58 newer lead commits.
- [x] PR #446 merge-result gates PASS: Visit List, Visit decomposition, Visit commercial decomposition, FIELD adapters/ownership, Offline durable-command regression.
- [x] PR #446 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `19aefd88129777486fb87ce59eb02964fa32b90a`.
- [x] No Dashboard web, Backend, Visit FIELD wiring, Recovery, Work Session, Custody, Shops, Auth, LocalDatabase or SyncRepository production files were modified by this slice.
- [ ] Route-action compatibility still reads cached `is_on_break` / `is_authorized`; Backend remains authorization authority and this seam may be replaced later without changing Visit List UI.
- [ ] SyncRepository still exposes generic exceptions on some compatibility paths; Visit List fails closed rather than parsing message text.

## 11. UI / design-system closure

Current app has one global ad-hoc gradient/theme and no coherent field design system.

Design principles:
- [ ] Arabic-first RTL with Western digits.
- [ ] One-handed field operation.
- [ ] High readability outdoors.
- [ ] Strong hierarchy without generic “AI dashboard” card spam.
- [ ] Persistent, unambiguous online/offline/sync state.
- [ ] A workday/task-first home rather than decorative metrics-first UI.
- [ ] Fast product selection and quantity entry.
- [ ] Clear money confirmation.
- [ ] Returns/replacement flow described in business language.
- [ ] Visible unsynced/recovery state without frightening or misleading the representative.
- [ ] Consistent spacing, typography, surfaces, controls, motion and feedback.
- [ ] Design tokens live centrally; feature screens consume them.
- [ ] No full visual rewrite until P0 contract/offline rules are frozen.

## 12. Tests / acceptance gates

Current Flutter test coverage is minimal.

Required focused tests:
- [ ] auth/offline owner guard regressions;
- [x] API error parsing;
- [x] mutation retry classification;
- [x] durable command migration and persistence;
- [x] visit request serialization;
- [x] stable request_id replay;
- [x] return Batch-resolution typed transport/adapters;
- [ ] Damaged/Expired/Factory_Defect payloads;
- [ ] exact money transport;
- [x] break offline policy;
- [ ] transfer exact-repeat/state-idempotent replay;
- [x] quarantine/recovery preservation;
- [x] account/company switch with pending/blocked work;
- [ ] local projection apply/revert exactly once.

Per-wave gates:
- [ ] `flutter analyze`
- [ ] focused `flutter test`
- [ ] full `flutter test`
- [ ] debug Android build
- [ ] real-device journey against current Backend

Final field acceptance:
- [ ] fresh login
- [ ] session start
- [ ] route/visit data
- [ ] sale
- [ ] debt collection
- [ ] samples
- [ ] all three return reasons
- [ ] tracked and no-lot return paths
- [ ] offline visit save
- [ ] app kill/restart
- [ ] same command replay without duplication
- [ ] rejected command recovery
- [ ] transfer handshake online/offline
- [ ] session end with required reconciliation
- [ ] logout/login ownership safety
- [ ] final Backend/Dashboard evidence agrees with Flutter actions

## 13. Four-day execution order

### Day 1 — freeze contracts + launch independent prerequisites
- [x] complete Backend/Flutter contract matrix.
- [x] freeze retry/idempotency matrix.
- [x] freeze A/B/C decomposition classification.
- [x] launch and integrate one isolated Backend FIELD-seam worker for the four confirmed prerequisites.
- [ ] Flutter Wave 0 characterization tests.
- [x] Flutter Wave 1 network/error seam: mechanical extraction first, behavior fix second.
- [x] freeze break policy as online/reconcile, not deferred replay.
- [x] remove evidence-destruction paths behind focused tests.

### Day 2 — visit vertical slice + durable command core
- [x] mechanically extract Visit command serializer / projection helpers before further behavior work.
- [x] mechanically extract Visit catalog/product-card presentation before Returns UI wiring.
- [ ] mechanically extract any remaining Visit presentation only when required by the next feature slice.
- [x] strict VisitUpdateRequest serializer: path ID only; no unknown fields.
- [x] persist visit UUID/body before first send.
- [ ] exact-money transport; local figures are estimates, not authority.
- [ ] sale/collection/sample contract parity.
- [ ] Damaged / Expired / Factory_Defect + Backend Batch-resolution flow.
- [x] durable command store migration preserving old rows.
- [ ] visit/offline tests.

### Day 3 — projection/session/custody + field-first UX
- [x] correct AVAILABLE-out vs DAMAGED-custody-in V1 projection: replacement-out affects local AVAILABLE projection while returned goods appear separately as pending DAMAGED evidence until Backend custody becomes authoritative.
- [x] completed-visit AVAILABLE projection correction applies old-to-new delta exactly once.
- [x] Work Session behavior/authority separated from DashboardBloc into feature-owned boundaries.
- [ ] Custody behavioral authority remains to be separated from DashboardBloc; Recovery/quarantine/sync responsibility is now feature-owned.
- [ ] transfer exact-decision replay and 100-item runtime batch limit.
- [x] shop creation typed transport + stable request UUID + ambiguous-result exact replay reconciliation.
- [ ] app shell/design tokens and workday-task-first home.
- [x] persistent sync/recovery status distinguishes pending, blocked/recovery-required, synced, incomplete and unresolved outcomes.
- [ ] compact visit/quantity/returns field UX.

### Day 4 — field acceptance and only blocker fixes
- [ ] real Android device end-to-end journey;
- [ ] network-loss/restart/retry scenarios;
- [ ] Backend/Dashboard evidence verification;
- [ ] analyze/tests/build;
- [ ] no broad polish or scope expansion after acceptance starts;
- [ ] merge only after lead review and clean handoff.

## 14. Parallel-work ownership

Lead conversation:
- contract reconciliation;
- offline architecture;
- final Flutter architecture;
- plan and integration decisions;
- review/merge readiness.

Codex read-only audit:
- Backend field contracts;
- idempotency/retry matrix;
- server authority and real blockers.

Second chat read-only audit:
- Flutter architecture/UI/god-file map;
- extraction order;
- UX risk map.

Current implementation ownership is frozen:
- Backend worker: Backend FIELD seams only.
- Network worker: `wanasah_frontend/lib/core/network/**` + focused network tests.
- Lead Offline worker: durable command/quarantine/persistence ownership listed in §4.5.
- No worker may edit another worker's owned files without lead handoff.

## 15. Audit findings still open

- [x] Backend worker report incorporated.
- [x] Flutter/UI worker report incorporated.
- [x] Current `flutter analyze` baseline recorded: PASS, no issues.
- [x] Current `flutter test` baseline recorded: 13 offline-owner tests PASS; stale default counter widget test FAILS and is not a valid product gate.
- [x] Exact verdict confirmed: no current operator-simple FIELD returned-Batch resolver; Backend prerequisite required and specified.
- [x] Current error-code/correlation-ID coverage mapped; structured envelope exists but several field business refusals still lack semantic codes.
- [x] Final P0 implementation backlog frozen by merged Backend + Flutter audits; P1 visual polish remains subordinate to field acceptance.
