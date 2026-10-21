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
- [ ] Define/verify a Backend-owned Batch-resolution seam for Flutter.
- [ ] Deterministic Batch cases resolve server-side automatically.
- [ ] Ambiguous cases return only minimal human-readable evidence (lot/expiry/etc.).
- [ ] Flutter stores/sends the resolved hidden identity without displaying technical IDs.
- [ ] Add Damaged + Expired + Factory_Defect consistently.
- [ ] Preserve carton/pack quantities.
- [ ] Preserve one stable idempotency identity across offline retry/replay.
- [ ] Local projection separates AVAILABLE replacement-out from returned non-sellable custody sufficiently for accurate field UX.
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
- [ ] Introduce operation-aware retry classification.
- [ ] Auto-replay only requests proven safe/idempotent.
- [ ] Durable visit submission reuses the exact same `request_id` and body.
- [ ] Non-idempotent/ambiguous mutations must reconcile rather than blind replay.
- [ ] Token-refresh retry remains allowed only under the authenticated-before-handler safety contract.

### 3.4 Offline break semantics

Current Flutter:
- [x] queues break start/end offline;
- [x] immediately changes local break state;
- [x] deletes queued break operations on generic HTTP 400 during replay.

Required closure:
- [ ] Decide from Backend contract whether break changes are online-only or have an explicit reconciliation model.
- [ ] Do not replay stale temporal commands blindly.
- [ ] Never treat arbitrary 400 as proof that a deferred command is safely settled.
- [ ] UI distinguishes local tentative state from server-confirmed state if offline behavior is retained.

### 3.5 Quarantine/recovery data loss

Current Flutter:
- [x] stores rejected/corrupt commands as `quarantined_*`;
- [x] Dashboard exposes a path that deletes all quarantined rows locally.

Required closure:
- [ ] Remove destructive “clear all rejected operations” from ordinary field UX.
- [ ] Quarantine is evidence/recovery state, not trash.
- [ ] Store stable failure classification/code/context/correlation ID.
- [ ] Allow only safe retry, explicit supersession, or an approved recovery workflow.
- [ ] Never lose an unresolved sale/collection/return command silently.


### 3.6 Strict visit payload mismatch

Independent audit confirmed the current Flutter visit command can fail the strict Backend schema:
- [x] Flutter payload includes `visit_id` and compatibility `visitId`; only the path ID is authoritative.
- [x] NoSale additionally emits `no_sale_reason`, while Backend expects the reason in `notes`.
- [ ] Canonical Flutter serializer must emit only fields accepted by `VisitUpdateRequest`.
- [ ] Characterization tests must lock Sale / NoSale / Postponed payloads before refactor.

### 3.7 UUID durability before first send

Backend visit replay is durable and exact only if Flutter preserves the original UUID and semantic body.
- [x] Current Flutter creates the UUID before direct send but persists the pending command only after failure.
- [ ] Persist the durable visit command identity/body before the first mutation attempt.
- [ ] Lost response or app crash must replay the same UUID/body, never mint a new identity.
- [ ] A later deliberate completed-visit correction uses a new UUID only after the prior logical result is resolved.

### 3.8 Confirmed Backend prerequisites for field V1

The independent Backend audit found four genuine field-transport prerequisites. These are not permission to move authority into Flutter.

1. **Returned-Batch resolution seam**
   - [ ] Add a FIELD-authorized Backend capability that resolves the returned Batch from owned shop/visit/product plus authoritative provenance/tracking evidence.
   - [ ] Deterministic cases resolve internally.
   - [ ] Ambiguity requests only the smallest human-readable discriminator.
   - [ ] Mutation revalidates the resolved identity.
   - [ ] Never expose or ask the representative for database `batch_id`.

2. **Tax jurisdiction for field-created shops**
   - [ ] `POST /shops` must lead to an approved canonical tax-jurisdiction outcome or an explicit actionable completion path.
   - [ ] Do not guess jurisdiction from GPS/zone in Flutter.
   - [ ] New-shop first sale must not dead-end on `TAX_JURISDICTION_REQUIRED`.

3. **Authoritative field invoice result/preview**
   - [ ] Reuse the existing Backend sale calculator and expose enough FIELD transport for authoritative payable/final totals, rounding and currency.
   - [ ] Flutter cached catalog prices remain display/offline estimate evidence only.
   - [ ] Do not build a second pricing engine in Dart.

4. **Non-sellable vehicle custody read**
   - [ ] Add a bounded FIELD projection/read for supported non-sellable custody such as DAMAGED after exchanges/recovery.
   - [ ] Preserve hidden Batch authority and business-readable evidence.
   - [ ] AVAILABLE-only reads are insufficient for return/recovery field truth.

### 3.9 Shop-create retry and session semantics

- [x] Shop creation has no durable operation UUID; duplicate phone is not proof that a lost command succeeded.
- [ ] Lost/ambiguous shop creation must reconcile assigned visits/shop evidence before retry.
- [x] Session start/end have no durable command identity; reconcile active session/dashboard before retry.
- [x] Historical offline break replay is unsupported by Backend because server execution time defines break timing.
- [ ] Break start/end become online/reconcile operations for V1; no stale temporal replay queue.

## 4. Offline command engine hardening

Current pending queue is generic `id/type/payload/created_at`.

Target V1 durable command record should support, as needed:
- [ ] stable operation/request identity;
- [ ] command type;
- [ ] owner company + field identity binding;
- [ ] exact canonical payload;
- [ ] created time;
- [ ] state: pending / in-flight-recoverable / blocked / reconciled;
- [ ] retry attempt metadata;
- [ ] last stable error code/context/correlation ID;
- [ ] no free-text-message decisions;
- [ ] deterministic FIFO where ordering matters;
- [ ] explicit operation-specific replay policy.

Migration rules:
- [ ] preserve existing pending rows;
- [ ] no destructive migration;
- [ ] legacy rows receive safe defaults;
- [ ] unattributed active pending work fails closed.

## 5. Error model / observability

- [ ] Introduce a typed Flutter API failure model.
- [ ] Parse stable `code`, structured `context`, status and correlation/request ID.
- [ ] Keep localized server text for display only.
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
- [ ] Token refresh cannot wipe pending work.
- [ ] Same-user app restart restores the correct tenant DB and sync state.

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
- [ ] Keep AVAILABLE sellable quantity distinct from non-sellable returned custody where required for operator UX.
- [ ] Do not invent Batch allocation locally.
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

Known extraction targets:
- [ ] `visit_screen.dart` (~1400 lines)
- [ ] `dashboard_screen.dart` (~900+ lines)
- [ ] `local_database.dart` (~700+ lines)
- [ ] `dashboard_bloc.dart` (~600+ lines)
- [ ] `visit_bloc.dart` (~500+ lines)
- [ ] `sync_repository.dart` (~480 lines)

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
- [ ] API error parsing;
- [ ] mutation retry classification;
- [ ] durable command migration and persistence;
- [ ] visit request serialization;
- [ ] stable request_id replay;
- [ ] return Batch-resolution transport;
- [ ] Damaged/Expired/Factory_Defect payloads;
- [ ] exact money transport;
- [ ] break offline policy;
- [ ] transfer exact-repeat/state-idempotent replay;
- [ ] quarantine/recovery preservation;
- [ ] account/company switch with pending work;
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
- [ ] launch one isolated Backend FIELD-seam worker for the four confirmed prerequisites.
- [ ] Flutter Wave 0 characterization tests.
- [ ] Flutter Wave 1 network/error seam: mechanical extraction first, behavior fix second.
- [ ] freeze break policy as online/reconcile, not deferred replay.
- [ ] remove evidence-destruction paths behind focused tests.

### Day 2 — visit vertical slice + durable command core
- [ ] mechanically extract visit DTO/payload mapping and major presentation widgets.
- [ ] strict VisitUpdateRequest serializer: path ID only; no unknown fields.
- [ ] persist visit UUID/body before first send.
- [ ] exact-money transport; local figures are estimates, not authority.
- [ ] sale/collection/sample contract parity.
- [ ] Damaged / Expired / Factory_Defect + Backend Batch-resolution flow.
- [ ] durable command store migration preserving old rows.
- [ ] visit/offline tests.

### Day 3 — projection/session/custody + field-first UX
- [ ] correct AVAILABLE-out vs DAMAGED-custody-in projection.
- [ ] completed-visit correction apply/revert exactly once.
- [ ] separate Session / Custody / Recovery responsibilities from DashboardBloc.
- [ ] transfer exact-decision replay and 100-item runtime batch limit.
- [ ] shop creation typed transport + ambiguous-result reconciliation.
- [ ] app shell/design tokens and workday-task-first home.
- [ ] persistent sync/recovery status.
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

Future implementation workers receive disjoint file ownership only after this audit is frozen.

## 15. Audit findings still open

- [x] Backend worker report incorporated.
- [x] Flutter/UI worker report incorporated.
- [x] Current `flutter analyze` baseline recorded: PASS, no issues.
- [x] Current `flutter test` baseline recorded: 13 offline-owner tests PASS; stale default counter widget test FAILS and is not a valid product gate.
- [x] Exact verdict confirmed: no current operator-simple FIELD returned-Batch resolver; Backend prerequisite required and specified.
- [x] Current error-code/correlation-ID coverage mapped; structured envelope exists but several field business refusals still lack semantic codes.
- [x] Final P0 implementation backlog frozen by merged Backend + Flutter audits; P1 visual polish remains subordinate to field acceptance.
