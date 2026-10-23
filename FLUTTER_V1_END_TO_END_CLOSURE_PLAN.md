# Flutter V1 End-to-End Field Closure Plan

Status: ACTIVE  
Owner: Flutter V1 lead conversation  
Execution branch: `sol/flutter-v1-field-closure`  
Initial audited base: `be2ddbf4d24085d34727dc6fd339bf6c5997590d`  
Target: field-ready V1 in four days without weakening Backend authority.

## 0. Non-negotiable execution rules

**Checklist accounting rule (owner decision, 2026-10-23):** `[x]` means an executable task or acceptance gate actually completed with traceable evidence (usually merged source and passing tests). `[ ]` means unimplemented, unverified, or pending acceptance. Approved architecture/requirements and standing policies are recorded as **plain notes without checkbox markers**; approval alone MUST NEVER turn implementation checkboxes into `[x]`. The §6.4 FIELD decisions are binding requirements, but phases 1–4, safety gates P1–P9, Flutter UI/release acceptance and device checks remain open until proved.

- [x] Read `.rules`, `AGENTS.md`, `ARCHITECTURE.md`, `V1_SCOPE_FREEZE.md`, and `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`.
- [x] Read the damaged-goods / returns / representative-settlement plan before touching field return logic.
- [x] Backend source + current tests, not future modularization documents, define current runtime contracts.
- [x] Keep Flutter work isolated from the parallel Dashboard conversation.
- [x] Flutter branch owns `wanasah_frontend/**` and this plan unless a separately assigned Backend prerequisite is explicitly delegated.
- Re-read latest `main` before every implementation wave and resolve contract drift before coding.
- No broad refactor, dependency upgrade, generated-file cleanup, or local destructive command.
- Backend remains authority for pricing, offers, taxes, FEFO, Batch resolution, inventory status, costing, debt limits, idempotency and reconciliation.
- Never expose technical IDs such as database `batch_id` to the representative.
- Every write wave must have focused tests before broader gates.

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
- [x] Flutter stores/sends the resolved opaque resolution token without displaying technical IDs; current Visit UI/submission wiring preserves the Backend-signed token exactly.
- [x] Add Damaged + Expired + Factory_Defect consistently.
- [x] Preserve carton/pack quantities.
- [x] Preserve one stable idempotency identity across offline retry/replay.
- [x] Local projection separates AVAILABLE replacement-out from returned non-sellable custody for V1 field UX; unresolved local returns are shown as pending DAMAGED evidence, never merged into authoritative custody totals.
- [x] Reopen/correction cannot double-apply replacement or returned custody.

This may require one bounded Backend prerequisite on a separately owned worker branch. Do not fake the missing Batch truth in Flutter.

### 3.2 Client-side financial authority

Current Flutter:
- [x] uses Dart `double` and SQLite `REAL` for money;
- [x] calculates invoice totals locally from cached product prices;
- [x] blocks submission locally when its calculated debt limit would be exceeded;
- [x] can therefore reject a transaction based on stale client pricing while Backend pricing/offers/taxes are authoritative.

Required closure:
- [x] Remove client calculations as authoritative acceptance/rejection rules.
- [x] Use Backend-authoritative preview/read evidence where available.
- [x] Offline UI may display a clearly scoped estimate but does not invent final commercial truth; cached prices are display-only and never drive approval/staging.
- [x] Preserve exact monetary strings/values across transport and durable offline command storage.
- [x] Eliminate floating-point comparisons from commercial correctness decisions; legacy double compatibility state is non-authoritative.

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
   - [x] Flutter cached catalog prices are display/offline estimate evidence only; Visit submission/approval ignores cached price values and Backend preview/frozen invoice remains authority.
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
- [x] AVAILABLE vs DAMAGED local inventory projection is closed: AVAILABLE uses typed fail-closed exact projection while returned non-sellable custody remains separate.
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
- [x] Returned-Batch resolution, Damaged reason/submission wiring, and non-sellable vehicle custody are closed through the accepted FIELD/Custody integrations.
- [x] Backend-authoritative invoice preview/final commercial truth submission/operator wiring is closed; committed/frozen invoice evidence remains Backend authority.
- [x] Auth/session typed-failure adoption completed and merged.

## 5. Error model / observability

- [x] Introduce a typed Flutter API failure model.
- [x] Parse stable `code`, structured `context`, status and correlation/request ID.
- [x] Keep localized server text for display only inside Network classification.
- [x] Remove business branching on Arabic/free-text messages: current Flutter business/runtime decisions use typed/status/code evidence; the remaining SQLite duplicate-column string check is migration compatibility only, not business authority.
- [x] User-facing errors must distinguish:
  - connectivity,
  - authorization/session expiry,
  - business rejection,
  - retryable transient failure,
  - ambiguous committed-state failure,
  - local persistence/recovery failure.
- [x] Attach Sentry context without logging secrets/tokens/full sensitive payloads.

### 5.1 Typed location / free-text failure stability point — 2026-10-23

- [x] Codex branch: `codex/flutter-v1-typed-error-free-text-closure`.
- [x] Exact Codex HEAD: `6a9733f613a33497a5518aac4f74024bd88eba42`.
- [x] Lead integration commit: `886fe952d548f712f22d4a0833d7703af247f00b`.
- [x] Integration PR #478 merged to `main`; merge commit: `741bcb7e7e9054134849916adfec81af419e138d`.
- [x] Global audit covered all 150 Flutter runtime Dart files.
- [x] Device location failures are typed as serviceDisabled, permissionDenied, permissionDeniedForever, timeout, mockedLocation and unexpected with stable codes.
- [x] Arbitrary exception text cannot spoof mocked-location or timeout classification.
- [x] Add Shop GPS feedback branches on typed location kind only; no substring parsing remains.
- [x] Work Session retains optional/best-effort location semantics; location failure never becomes client-side session authorization authority.
- [x] Legacy `respondToTransfer()` deterministic 4xx rethrows original DioException, preserving status/code/context/request ID and preventing false offline fallback.
- [x] Network/timeout/408/429/5xx transfer ambiguity behavior remains unchanged.
- [x] Current `SyncRepository` has no `throw Exception(...)`, `toString().contains(...)` or `message.contains(...)` machine classification.
- [x] Current-main PR #478 gates PASS: Typed Location, FIELD, Shop, Auth/Session, Offline, Sync/Recovery and Projection.
- [x] Inventory CP2 historical unchanged-file assertion remains unrelated.
- [ ] `LocalDatabase._safeAlterTable()` still uses SQLite duplicate-column text only for low-level migration compatibility; it is not a business/runtime classification seam.
- [x] Broader Sentry typed context/redaction closed through PR #482; transaction telemetry deliberately disabled pending a proven safe allowlist.

### 5.2 Error Model / Sentry observability stability point — 2026-10-23

- [x] Worker branch `sol/flutter-v1-error-observability-closure`; accepted worker HEAD `7ff821069ab4148e9c9beccec272680a24e88598`.
- [x] Lead reviewed the 27-file production/tests scope against latest `main` and Codex transfer ownership; no changed-file overlap.
- [x] Lead privacy-hardening commit `a6552e7c1af4b9c589d31ef2fcd5c28ab79696fb` closes unsanitized transaction/fingerprint telemetry: native/Dart trace sampling disabled (0.0), transaction sends dropped, event fingerprints/threads stripped; uncaught error reporting and exception stacks retained.
- [x] Sentry application metadata is allowlisted; tokens, arbitrary `ApiFailure.context`, payloads, names, addresses and coordinates are not copied into event metadata.
- [x] Typed connectivity/timeout, authorization, deterministic business, temporary server and local recovery presentation covered without classifying on translated exception text.
- [x] Auth identity, Visit mutation, offline replay/FIFO, LocalDatabase, projection and Custody batch execution semantics unchanged.
- [x] PR #482 merged into `main` at `da4628514b1de7a2924632548d5c193bbc1bfe25`; worker branch auto-deleted.
- [x] Exact current-main PR merge tree `21ee8d1ee06d2f2c418170e997016af5b6407731`: Flutter analyze PASS, 159 focused/regression tests PASS, 14 relevant GitHub workflows PASS.
- [x] Unrelated historical CP2 unchanged-file assertion on `wa_backend/api/warehouse/live_stock.py` remains FAIL; this branch did not change that file.
- [x] No claim of full Flutter suite, Android build, real-device E2E or production readiness. Privacy-safe performance tracing remains disabled until separately specified and validated.

## 6. Authentication / identity / tenant safety

Already strong and must be preserved:
- [x] physically separate SQLite database per company code;
- [x] active pending queue owner guard;
- [x] different-driver same-company login blocked when unsafe pending work exists;
- [x] cross-company switching blocked when unsafe pending work exists;
- [x] logout preserves pending work.

Closure:
- [x] Verify current login/refresh response against canonical field principal/representative mapping.
- [x] Bind durable commands to the stable identity required by current Backend field contract.
- [x] No legacy `Driver.is_admin` or client role flag becomes authority.
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
- [x] Canonical principal/representative identity mapping contract check completed; operational `owner_driver_id` remains the Backend-mapped legacy Driver locator, not principal/profile identity.

### 6.2 Final architecture audit — open gates (2026-10-23)

- [x] Read-only audit on frozen baseline `00588fcb13a2344d6bd901dd4ae190b10d04f70f` identified one FIELD authorization enforcement blocker and one release-acceptance blocker; latest main was reviewed for the same identity/capability seam before recording these findings.
- [ ] **V1 security blocker — FIELD capability authority:** current FIELD context validates the canonical principal/channel and operational assignment, but actual FIELD endpoints do not yet require persisted per-operation capability grants. This is **not** evidence of a cross-tenant/assignment leak. Preserve existing owner/route/visit/vehicle scope checks.
- **Approved architecture note (not implementation):** Owner approved all seven FIELD grant/capability/scope decisions in §6.4 and `ARCHITECTURE.md` §12; there is no legacy Driver/JWT authority and later-role edits cannot bypass the field allowlist. Phases 1–2 are completed/verified in §§6.4a–6.4b; Phases 3–4 and overall security/release proof remain `[ ]`.
- [x] **V1 required — Visit read-only durable evidence:** `visit_screen.dart` now consumes a typed feature-owned read model and read-only pending command adapter; preserves existing durable storage, FIFO, owner/company guards, exact replay, public contracts, financial/stock authority and return/draft recovery. Independently reviewed, corrected legacy Visit ID alias parity and merged PR #494; exact evidence below.
- [x] **V1 required — SyncRepository Visit adapter:** moved Visit-specific PUT replay dispatch and local atomic finalization into small Visit-owned adapter modules, leaving global FIFO, owner/company guards, UUID repair, exact replay, retry/error classification, finalization/delete order and `saveInvoice()` API in the shared scheduler. Independently reviewed and merged PR #497; exact CI evidence below.

### 6.2a Visit durable read-model architecture stability point — 2026-10-23

- [x] Owner-only read path: added `features/visits/application/visit_durable_read_model.dart` and `features/visits/data/visit_durable_evidence_source.dart`; `visit_screen.dart` no longer directly interprets raw pending-command JSON or calls `getPendingSyncs()`.
- [x] Exact latest matching `submit_sale` local draft restored; preserves cash/debt/notes/cart/returns, malformed/unrelated/quarantined behavior and both supported `visitId`/`visit_id` legacy matching aliases. Lead identified and fixed a small alias-fallback regression, then added a regression test before merging.
- [x] No edits to Backend, Dashboard, Flutter SyncRepository, durable command store, transport, state/mutation authority or CI workflows; no new business capability/permission/scope.
- [x] PR [#494](https://github.com/MohHamdallah1/wanasah/pull/494) independently reviewed and merged at `93c3ce4b5f547d7f971ded057ceacee3a954a2e7`; final reviewed branch HEAD `0cebf21eeecf0b177469365f3779a221da291c7d`. Four Flutter files only; branch deleted after merge.
- [x] Exact-head full Flutter/Android CI [39980865954](https://github.com/MohHamdallah1/wanasah/actions/runs/39980865954) PASS: `flutter analyze` no issues; `flutter test` **477/477 PASS** (no skips); debug Android APK built and artifact retained. Focused Visit decomposition, Visit commercial, Offline durable and FIELD client-adapter checks also PASS.
- [x] The independent historical Inventory CP2 CI failure `test_old_product_batch_drill_down_file_is_unchanged_from_checkpoint_2_base` compares an unrelated Backend file against the old `947d4c9...` checkpoint; PR #494 does not touch that file. Do not claim historical repository-wide CI green or silently modify this unrelated test.
- [x] Subsequent **SyncRepository Visit replay adapter** closed separately in PR #497 after this earlier Visit read-model checkpoint; see §6.2b for evidence. This §6.2a checkpoint itself did not modify replay.
- [ ] Real-device/current-Backend field/offline/recovery acceptance and the owner-approved FIELD capability Phase 1–4 work remain open.

- [x] **V1 required — global `is_admin` reintroduction gate:** confirmed zero known Runtime flag/persona authority, added automatic guard with migration/test/history exclusions and 8 mutation tests plus 28 prior identity checks; independently reviewed and merged PR #502. See §6.2c for exact results and scanner limitations.
- [x] **CI acceptance:** complete Flutter suite and Android debug build passed together on current-main-integrated PR #486 with synthetic CI environment; details and exact evidence below.
- [ ] **Device/release acceptance:** real Android device/current-Backend journeys, offline/restart/replay/reconciliation and FIELD capability authority still remain open; a CI APK is not device acceptance.
- [x] No newly evidenced blocker in FIFO/exact replay, tenant/assignment checks, stock/commercial authority, or public API compatibility; do not restart closed audits or refactor `driver.py`/other facades solely because of file length.
- [x] Codex final CI/Android workflow was independently reviewed, integrated, green-gated and merged in PR #486; only its new workflow was added to production `main`.

### 6.2b Visit-owned durable replay adapter stability point — 2026-10-23

- [x] Independently reviewed [PR #497](https://github.com/MohHamdallah1/wanasah/pull/497) on exact feature HEAD `8e41690d80c16cffd6860157e3e6a6543c19be26`, base `d8a65d56ddf87775fc5748a333bd601af7f3b60c`; nine Flutter-only files, no overlapping modifications against latest `main`, merged at `fc38c0ee67281113129e492592b450ea34172e77`.
- [x] New Visit-owned `features/visits/application/visit_replay_adapter.dart` and `features/visits/data/local_visit_replay_adapter.dart` own only `PUT /visits/{visitId}` dispatch / response balance cache and delegation to existing atomic `LocalDatabase.finalizeVisitCommandLocalState`; no second queue, engine or Backend/DB schema change.
- [x] `SyncRepository` still owns global FIFO and blocked/quarantined handling, secure owner/company guard, legacy `request_id`/`command_id` repair, transport failure classification (401/403/408/429/5xx/network), in-flight lifecycle, local success-before-delete, transfer dispatch and unchanged public `saveInvoice()` API. Existing monetary text strings stay verbatim in the PUT body; local numeric finalizer behavior unchanged.
- [x] Full Flutter [CI run 39983584638](https://github.com/MohHamdallah1/wanasah/actions/runs/39983584638) on exact final HEAD PASS: `flutter analyze` clean, **484/484 `flutter test`** without skips, Android debug APK built and retained as artifact [12515315997](https://github.com/MohHamdallah1/wanasah/actions/runs/39983584638/artifacts/12515315997). [Sync/Recovery 39983584585](https://github.com/MohHamdallah1/wanasah/actions/runs/39983584585) and [Offline durable 39983584694](https://github.com/MohHamdallah1/wanasah/actions/runs/39983584694) PASS; Visit/Projection/Commercial regressions also PASS.
- [x] Five pre-existing tests were adjusted only to follow moved source invariants/delegation, not to skip cases or weaken FIFO/owner/success-delete checks. New focused Visit replay adapter tests cover exact durable payload/request ID, non-2xx, missing ID, local balance best effort, finalizer mapping and invalid Visit identity.
- [x] Unrelated Inventory CP2 historical source-check failure remains documented as **red**; no CP2 Backend file change or claim that repository-wide historical CI is all green.
- [ ] Real-device/current Backend offline/auth/financial replay acceptance remains open; FIELD authorization Phases 3–4 remain separate work. Global `is_admin` reintroduction CI gate is now complete in PR #502 (§6.2c).

### 6.2c Legacy admin/persona reintroduction prevention stability point — 2026-10-24

- [x] Independent review of three-file [PR #502](https://github.com/MohHamdallah1/wanasah/pull/502), final branch HEAD `ab7f19a3972915b4fb3aa4bb6e7efc3c6237364a`, merged into `main` at `25d0e44a2debc23312304e42aa7c8b1994a4b6b6`. No Backend, Dashboard, Flutter production, permission/migration, identity or worker runtime modifications. Confirmed no file overlap with already-merged FIELD Phase 2 PR #501.
- [x] [Dedicated GitHub Actions run 39991550486](https://github.com/MohHamdallah1/wanasah/actions/runs/39991550486) SUCCESS on exact source HEAD. Source/architecture scan: **1172 Runtime files** = 505 Backend/workers, 505 Dashboard and 162 Flutter. `LEGACY_ADMIN_RUNTIME_AUTHORITY=PASS` with zero known matches. Exclusions: 89 historical Alembic migration files; 262 Backend tests; 4 archived performance artifacts; 168 Dashboard test files/directories; no general production directory exclusion.
- [x] Guard fail-tests 8/8 PASS: prohibited `Driver.is_admin`, generic `isOwner`/`is_manager`/`is_superuser`, direct boolean persona flags, string role authority, stale legacy contract strings and reactivation of the `get_current_admin()` fail-closed tombstone. Existing Backend login/transport retirement 6/6, identity migration tooling 11/11, Driver fixture retirement 7/7, Dashboard canonical login contract 4/4 PASS; **28 prior checks plus 8 new checks**.
- [x] Automated push/PR workflow covers scanned Backend `.py`, Dashboard `src` JS/TS/TSX and Flutter `lib` Dart source, and preserves canonical CompanyOwner/PlatformAdmin actor realms. No second identity migration or revival of `is_admin` is authorized.
- **Known scope/limitation:** Backend scan is Python AST-based; Dashboard and Flutter scanners are comment-aware lexical checks rather than full TypeScript/Dart AST parsers. A passing guard is strong covered-pattern regression evidence, **not** proof against arbitrary adversarial obfuscation or every possible new representation. Maintain review of identity/role grants and extend negative tests if novel Runtime authorization patterns emerge. Historical test/migration text remains allowed without being a live security grant.
- [ ] **Unrelated release gates still open:** FIELD Phase 3 persisted per-endpoint capability enforcement, Phase 4 company/warehouse/representative isolation and network/device evidence, and remaining Flutter V1 acceptance. Historic unrelated CP2/other red workflows are not claimed green.

### 6.3 Full Flutter test / Android debug build CI stability point — 2026-10-23

- [x] Codex original workflow-only PR #486 at `b0291147248063ae0a7a3a8f1540d5883fa063bd` exposed one genuine stale counter-template test; no Flutter production defect or environment blocker was asserted.
- [x] Lead replaced only `wanasah_frontend/test/widget_test.dart` with a behavioral Wanasah SplashScreen/Arabic startup smoke test (PR #489), rather than skipping any test or weakening the full suite.
- [x] Current-main and test integration with unchanged Codex workflow at exact HEAD `8b05ef3fed0e896c1042bb6cc979116f0b34b0c7` preserved all Git history without rebase/reset/force push; integrated diff was the new workflow plus test-only correction.
- [x] GitHub Actions full Flutter/Android run [39893263065](https://github.com/MohHamdallah1/wanasah/actions/runs/39893263065) PASS on exact integrated HEAD: `flutter pub get`, `flutter analyze` with no issues, 473/473 `flutter test` with no exclusions, and `flutter build apk --debug`.
- [x] Debug APK Artifact [12475876539](https://github.com/MohHamdallah1/wanasah/actions/runs/39893263065/artifacts/12475876539) retained until 2026-11-06, built against disposable CI-only `.env` (`127.0.0.1:8000`, empty Sentry DSN). Build proof only; not a configured on-device production/release binary.
- [x] PR #489 merged to `main` at `3a74ad2fd820f6ba03cd8b2a8f196ec0aba30c89`; PR #486 merged to `main` at `df9afd0877ac6c25e4cf7abed4103885a611c2b2`. Both feature branches deleted automatically.
- [x] The final PR #486 adds only `.github/workflows/flutter-v1-final-ci-android-acceptance.yml`; no Runtime/Backend/API/DB or existing test changes in that PR after PR #489 merged.
- [ ] Real-device Android end-to-end, network disconnect/app kill/restart/exact replay, current Backend/Dashboard parity, FIELD capability security blocker, and final V1 acceptance remain open.
- [x] Historical unrelated repository CI failures are not marked green; success is claimed only for the dedicated final Flutter/Android workflow.

### 6.4 FIELD capability decision register — OWNER APPROVED, IMPLEMENTATION OPEN (2026-10-23)

**Project owner explicitly APPROVED all seven FIELD V1 authorization decisions on 2026-10-23, including the anti-escalation protection for later Role edits.** This is now a frozen architecture contract, ratified in `ARCHITECTURE.md` §12 and repeated in `.rules` and `AGENTS.md` for all future workers. **Approval is NOT implementation:** new FIELD capabilities/assignment schema, grant APIs, endpoint enforcement, migration, tests and real-device release gates stay OPEN until validated and merged. This is a security/authorization completion within the already-frozen Flutter V1 business workflow, not approval to expand unrelated Dashboard product scope. The existing canonical identity cutover is DONE and MUST NOT be reimplemented.

**Purpose / invariant:** `authenticated principal + access channel + persisted capability + applicable scope -> Backend decision`. FIELD is identity/channel only; it does not grant business permission. Never infer authority from UI visibility, JWT capability claims, Role name, `Driver.is_admin`, legacy Driver ID or Driver/Principal/Profile ID equality.

#### Seven **approved architectural decisions** — reference requirements, not completed implementation tasks

- **D1 — Three NEW codes:** add only `work_session.execute`, `visit.execute`, `shop.create` to the shared canonical catalog. The other nine codes below already exist; FIELD V1 default bundle contains twelve total permissions, not three.
- **D2 — Canonical FIELD assignment:** add `field_representative_roles` keyed by company + canonical `FieldRepresentative.id` + role ID. Reuse current Role/Permission/role_permissions. Do **not** reuse Driver-based `UserRole` / `UserLocationAccess` for FIELD: `DUAL_SPLIT` can map independent FIELD and Backoffice principals to the same legacy Driver.
- **D3 — Scope:** assign capabilities company-wide as *operation-type grants*, then AND with existing dynamic WorkSession / DispatchRoute / assigned Visit / assigned VEHICLE location / expected-receiver / tenant / business-state guards. No static Field warehouse/location grants in V1, and no scope bypass.
- **D4 — Existing/new representative provisioning:** create one limited FIELD V1 system role per company, grant it once to existing representatives through a migrated idempotent backfill before endpoint enforcement, and assign it atomically on creation of a new representative. Never auto-regrant after deliberate revocation. No unrestricted `PERMISSIONS` default.
- **D5 — Stable system role key:** add nullable `Role.system_key` with a tenant-unique reserved `FIELD_REPRESENTATIVE_V1` identity for provisioning. This is lookup metadata, **not** permission authority. Keep system-role membership and capabilities immutable except through separately controlled migration; never infer grants from role name.
- **D6 — Grant/revoke API:** owner-only FIELD role assignment management under representatives, independently of existing Backoffice grant APIs. Server loads canonical same-company representative and role; rejects roles not restricted to FIELD-assignable codes. Persist audit, idempotent add, immediate revocation without relogin.
- **D7 — Endpoint/capability matrix:** approve the exact mapping below, including composite reads and per-decision transfer requirements. Preserve existing endpoint URLs, status/error contract, command idempotency and Flutter payloads.

Proposed twelve-capability FIELD V1 default bundle (nine existing, three NEW):

`work_session.read`, `work_session.execute` (NEW), `visit.read`, `visit.execute` (NEW), `inventory.read`, `transfer.read`, `transfer.receive`, `transfer.reject`, `catalog.read`, `pricing.view`, `reconciliation.execute`, `shop.create` (NEW).

**Approved D7 endpoint matrix (per-endpoint enforcement and its acceptance tests are STILL OPEN):**

| FIELD endpoint/action | Required persisted capability | Additional runtime authority (never removed) |
| --- | --- | --- |
| Login / refresh / logout | None: authentication/session boundary | Canonical principal, channel and revocation/session validation |
| GET active session | work_session.read | Own company/representative |
| POST start, PUT break/end session | work_session.execute (NEW) | Own assigned route, WorkSession and vehicle |
| GET driver dashboard | work_session.read + visit.read + inventory.read | Own assigned work/inventory |
| GET driver visits | visit.read + inventory.read + transfer.read + pricing.view | Own route/visits, vehicle and transfers |
| GET visit detail / commercial state | visit.read | Own visit and applicable current session |
| POST invoice preview | visit.execute (NEW) + pricing.view | Assigned visit and Backend commercial readiness |
| GET invoice | visit.read + pricing.view | Own completed visit and immutable evidence |
| POST return resolution / PUT visit | visit.execute (NEW) | Owned visit, Backend stock/commercial/Batch authority |
| GET product variants | catalog.read + pricing.view | Authorized assigned context |
| GET driver custody | inventory.read | Assigned active VEHICLE location |
| GET pending transfers | transfer.read | Expected receiver and own session/vehicle |
| PUT respond transfer accepted | transfer.receive | Exact transfer, receiver, location and session |
| PUT respond transfer rejected | transfer.reject | Exact transfer, receiver and session |
| PUT batch_respond | transfer.receive and/or transfer.reject according to actual decisions | Per-item exact transfer identity, atomicity and unchanged batch limit/replay |
| POST shops | shop.create (NEW) | Own active session/route/zone and authorized-to-sell business state |
| POST driver session reconcile | reconciliation.execute | Own ended WorkSession and assigned vehicle location |

#### Mandatory safety / rollout gates — owner-approved constraints; all remain OPEN until proved

- [ ] **P1 Grant leakage:** test `DUAL_SPLIT`: one legacy Driver mapped to distinct Backoffice and FIELD canonical subjects must NEVER cause roles/grants to cross channels.
- [ ] **P2 No capability alone bypasses scope:** preserve tenant, route/zone, active WorkSession, Visit ownership, vehicle/location, expected receiver, stock/financial invariants. Capability AND scope, never OR.
- [ ] **P3 No client-side/JWT authorization:** resolve grants from persisted server Role/Permission/field assignment every request; immediate revocation with unchanged token.
- [ ] **P4 No accidental lockout:** install exact limited default grants to already-existing representatives BEFORE enforcement; new-representative assignment must be part of the same transaction. Backfill only once; revoked grants stay revoked.
- [ ] **P5 No role-escalation loophole:** define `FIELD_ASSIGNABLE_PERMISSIONS` allowlist; reject assignment if any role permission lies outside it. Critically, also reject later editing/addition of permissions to **any role already assigned to FIELD** if it would exceed this allowlist; otherwise a safe role becomes privileged after assignment. Prevent unauthorized edit/delete of the default system role, including via other role APIs and migrations.
- [ ] **P6 Schema + company isolation:** composite tenant FKs, stable uniqueness, migration against current Alembic head, FORCE RLS where applicable, indexes, and idempotent backfill. Validate active/revoked principal, exact FieldRepresentative and same-company Role.
- [ ] **P7 Denial matrix:** no grant, revoked grant with same token, foreign company, wrong vehicle/location, wrong assigned visit, unauthorized direct HTTP mutation, `DUAL_SPLIT`, no reliance on role names or `is_admin`, mixed accepted/rejected batch needing both distinct grants. Verify 403/404 as appropriate and **zero mutation/idempotency/stock side effects** on denial.
- [ ] **P8 Business-compatibility:** keep prior login/refresh/logout, Flutter request/response, structured errors, audit, exact replay, transfer batch atomicity and 100-item cap; do not rewrite god-file business logic just to insert dependencies.
- [ ] **P9 Backend scope separation:** backend FIELD authorization is a strict Flutter V1 dependency; do not touch concurrent Dashboard Reports/Settings/other owner surfaces or client visual redesign.

#### Implementation phases — `[ ]` until code, tests, and integration are verified

**Completed decision prerequisite (not an implementation checklist item):** The owner approved all seven FIELD V1 architectural decisions and role-edit anti-escalation controls. The contract is permanently documented in `ARCHITECTURE.md` §12, `.rules`, `AGENTS.md` and this plan.
1. [x] Phase 1 — Backend persisted FIELD grant foundation, three new capability codes and exact 12-code allowlist, canonical FIELD role assignments, protected `Role.system_key`, additive Alembic migration, FORCE RLS/runtime privileges, safe one-time backfill, and migrated PostgreSQL/`DUAL_SPLIT` acceptance. Merged PR #495 with verified evidence in §6.4a; no endpoint enforcement yet.
2. [x] Phase 2 — Persisted `FieldCapabilityAccess` + FIELD-only HTTP dependencies, canonical CompanyOwner role grant/list/revoke, atomic new-representative limited default provisioning, assignment and later-role-edit anti-escalation, DB race guards, instant same-token revocation; independently reviewed and merged PR #501 with exact acceptance in §6.4b. Business endpoint enforcement remains Phase 3.
3. [ ] Phase 3 — Backend FIELD dependencies at session/visit/shop/transfer/custody/reconciliation endpoints with preserved assigned scopes. No Flutter or runtime workflow refactor; negative tests.
4. [ ] Phase 4 — focused cross-channel, current Backend + Flutter acceptance, then independent review/merge and updated `[x]` evidence.

**Mandatory worker/lead protocol (2026-10-23):** Each new worker, including Codex, must read **`AGENTS.md` first**, then `.rules`, `ARCHITECTURE.md` §12, `V1_SCOPE_FREEZE.md`, `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md` and this live Flutter plan before code. Use exact `main` SHA per wave, fresh GitHub-only branch, isolated file ownership, no local-machine modification, no rebase/force-push/destructive cleanup, no overlapping writes, no autonomous merges. The **Lead** independently reviews exact diff, current-main overlap, architecture, tenant/RLS authorization, migration/backfill safety, focused tests and CI; merge to `main` only after proof. Delete merged feature branches. After a proved stability checkpoint, sync an authorized local checkout **only after verifying local `git status` is clean**, via non-destructive fast-forward; do not run automatic pulls or modify local data without explicit user approval.

**Current parallel worker ownership (after Phase 2 merge, 2026-10-23):** FIELD Phases 1–2, Visit durable read model, and Visit replay adapter are **COMPLETE AND MERGED**. Next Codex work is **FIELD Phase 3 only**: wire previously approved persisted capability requirements into relevant FIELD-only business HTTP endpoints while preserving existing tenant/route/visit/work-session/vehicle/recipient/business guards. **Do not change** owner/Backoffice role administration, Phase 1–2 migrations, grant APIs, Flutter, Dashboard, or other workers' files except a proved narrow integration defect. The separate Flutter worker finished the global legacy-admin reintroduction guard PR #502, which has now been independently reviewed and merged; do not redo its work. Each worker must read `AGENTS.md` first, respect exact branch ownership, and leave this plan/governance files to lead. Lead reviews every PR and merges independently; Phase 3–4 and P1–P9 global release gates remain OPEN.

#### 6.4a FIELD persisted-grant Phase 1 acceptance — 2026-10-23

- [x] Independently reviewed the exact seven-file PR [#495](https://github.com/MohHamdallah1/wanasah/pull/495), final HEAD `5f5f252b7712f19cb72c6793e67d6c3973a95a8e`; merged into current `main` at `5e1a24bcdb794fe022b4dccede31acd88032ad46`. Current-main overlap check confirmed only already-accepted Flutter Visit and plan docs changed in parallel; zero Backend file overlap.
- [x] Added `work_session.execute`, `visit.execute`, `shop.create` and exact `FIELD_ASSIGNABLE_PERMISSIONS` (12). `FieldRepresentativeRole` uses canonical `FieldRepresentative.id` with company-scoped composite FK to `roles` and `field_representatives`; no permission grants via legacy Driver ID.
- [x] Alembic `fa6c1e8d2b73` (from approved prior head `9c4f8a2d7e31`) installs tenant-bound FORCE RLS with restricted non-superuser runtime privileges, protected role identity `FIELD_REPRESENTATIVE_V1`, constrained system-role bundle, and one-time migration-only backfill. Re-running the data step preserves deliberate revocation, and role-name collisions fail closed.
- [x] Dedicated [FIELD PostgreSQL CI run 39902408426](https://github.com/MohHamdallah1/wanasah/actions/runs/39902408426): **26 real migrated PostgreSQL tests PASS, 0 skipped**; tested cross-company FK, RLS, restricted runtime grants, immutable system role and permission identities, revocation, DUAL_SPLIT, Backoffice grant isolation, clean repeated backfill and exact catalog.
- [x] [Clean bootstrap 39902408429](https://github.com/MohHamdallah1/wanasah/actions/runs/39902408429) PASS; [Backend FIELD prerequisite checks 39902408491](https://github.com/MohHamdallah1/wanasah/actions/runs/39902408491) PASS; [migration convergence 39902408556](https://github.com/MohHamdallah1/wanasah/actions/runs/39902408556) PASS; Alembic model parity `alembic check` reports no new upgrade operations, and fresh Backoffice HTTP permissions regression PASS.
- [x] Historical legacy authorization regression comparison: **79 PASS and 85 subtests PASS**, with **11 same failures on both exact old base and Phase 1 HEAD**. This is *zero new regression* evidence, not a claim that those 11 tests are green; unrelated older workflows remain red and owned elsewhere.
- [x] **Phase 2 completed separately:** the persisted FIELD access/owner-only audited grant APIs, atomic new representative provisioning, same-token revocation, role-edit anti-escalation and real PostgreSQL race proof were subsequently delivered in merged PR #501 (see §6.4b); Phase 1 alone did not provide these.
- [ ] **Phase 3 unimplemented:** per-route FIELD persisted authorization and complete negative matrix; cannot declare P1–P9 globally closed solely because Phase 1 migration/database checks passed.
- [ ] **Release remains open:** full real Android/current Backend operational acceptance and other Flutter V1 open items remain separate.

#### 6.4b FIELD owner-managed persisted role control Phase 2 stability point — 2026-10-23

- [x] Independently reviewed the 16-file [PR #501](https://github.com/MohHamdallah1/wanasah/pull/501), exact final worker HEAD `9fee5aab8a14fe0409c1a0f5dfbee244c8eee921`, originally based at `28e09891cf1c7051310d1446b29b725337a486f1`; no file overlap against newer current `main`. Merged at `f7862c60b72b44446ed581544577f2c1a88f69d9`.
- [x] Field-only `FieldCapabilityAccess` resolves actual persisted Role/Permission assignments through canonical CompanyPrincipal + FieldRepresentative + company + auth_revision; never legacy Driver/JWT role authority. New FIELD-specific FastAPI dependencies are NOT yet wired to V1 business endpoints; that is Phase 3.
- [x] Canonical CompanyOwner-only GET/list, POST/grant, POST/revoke under `/representatives/{id}/field-roles`; tenant and principal active matching, request-scoped checks, operation idempotency and audit preserved. A deliberate revoke takes effect on the next request with the same token; login/refresh/replay/reactivation do not silently regrant.
- [x] New representatives receive the exact restricted FIELD default role in the same creation transaction; existing Phase 1 backfill remains migration-only. Default system role stays immutable; human roles assigned to FIELD cannot acquire unauthorized Backoffice permissions later, including through concurrent grant/role edits protected by new additive migration `b2f6c8e4a901` with DB triggers/role-row serialization at READ COMMITTED and REPEATABLE READ.
- [x] [Phase 2 real PostgreSQL/HTTP/race CI 39990888514](https://github.com/MohHamdallah1/wanasah/actions/runs/39990888514) PASS: 10 new Phase 2 tests + 26 Phase 1 PostgreSQL tests, zero skips, Backoffice HTTP behavior, 51 source/unit tests + 86 subtests, Alembic metadata parity/ownership/whitespace. [Clean bootstrap 39990888495](https://github.com/MohHamdallah1/wanasah/actions/runs/39990888495), [Backend FIELD prerequisites 39990888469](https://github.com/MohHamdallah1/wanasah/actions/runs/39990888469) and [Flutter/Android full CI 39990888541](https://github.com/MohHamdallah1/wanasah/actions/runs/39990888541) PASS.
- [x] Historical legacy authorization suite still has **11 matching failures on both exact base and new HEAD**, 79 other PASS + 85 subtests; do not claim these historical failures green. The earlier Phase 1 CI ownership *false failure* was separately **corrected and verified in merged PR #506** (see §6.4c); the historical seven-file proof remains strict. Unrelated historical CP1/CP2/valuation/purchase suites remain independently red; not changed to success here.
- [ ] **Phase 3**: enforce all approved FIELD operation-to-capability endpoint mappings with correct composite reads/per-decision batch checks and unchanged scope/stock/financial rules. No production field endpoint is considered capability-enforced yet solely by Phase 2.
- [ ] **Phase 4 / global security release**: complete cross-channel, negative no-side-effect, real Android + current Backend + Dashboard parity/atomic replay acceptance and P1–P9 closure. Global `is_admin` CI gate evidence was completed separately by PR #502 (§6.2c); do not reopen it.

#### 6.4c FIELD Phase 1 historical CI ownership-gate correction — 2026-10-24

- [x] Independently reviewed and merged [PR #506](https://github.com/MohHamdallah1/wanasah/pull/506), worker HEAD `42ca6471e87d4fae114a953b01aba901390b0877` into `main` at `953ad15f5eebea75762648cd972a46a0d5b649ae`. **Exactly one file changed:** `.github/workflows/field-authorization-phase1.yml`; zero overlap with Codex's concurrently open FIELD Phase 3 PR #505. No Runtime, Flutter, Dashboard, migrations, authorization logic, tests or governance files modified by #506.
- [x] The Phase 1 historical ownership and whitespace proof now checks exact original base `9dd3dbed089f8d41f775f599ddf366a417ea6a16` → accepted Phase 1 head `5f5f252b7712f19cb72c6793e67d6c3973a95a8e`, with full-history checkout and existence/ancestor checks. All **seven original allowed files** still must match exactly; a new unrelated PR change no longer contaminates this historical comparison.
- [x] The five protected Phase 1 core files are still asserted unchanged since the accepted head. Real current-head migrated PostgreSQL tests remain live (not frozen or skipped); Phase 2's legitimate test fixture adjustment is not prohibited by the historical ownership proof.
- [x] [Exact-head GitHub CI #40030207487](https://github.com/MohHamdallah1/wanasah/actions/runs/40030207487) **SUCCESS**: **26/26 PostgreSQL PASS, 0 skips**, Alembic parity `No new upgrade operations detected`, fresh Backoffice HTTP regression 1/1 PASS, `PHASE1_ACCEPTED_HISTORY_REACHABLE=PASS`, `PHASE1_EXACT_HISTORICAL_OWNERSHIP=PASS`, `PHASE1_FROZEN_CORE_UNCHANGED=PASS`.
- **Historic failures are not erased:** original and current comparison both report **11 historical FAIL, 79 PASS + 85 subtests PASS** (`APPROVED_BASE_FAILURE_PARITY=PASS`). Independent Inventory CP2 workflow [40030207484](https://github.com/MohHamdallah1/wanasah/actions/runs/40030207484) remains RED; do not mark other historical repository-wide CI green.
- **Future modification caveat:** the historical core guard is intentionally strict about **whole-file** changes to `capabilities.py`, `field_models.py`, `models.py`, `alembic/env.py` and original Phase 1 migration. If a later approved phase legitimately changes one of the first four shared core files, explicitly revise its **current-head core invariant** after focused review and tests; never silently disable historical seven-file checks or rewrite old Git history. This is not authorization for broad refactoring.
- [ ] FIELD Phase 3 endpoint enforcement, Phase 4 full negative/no-side-effect and device release acceptance, and nine P1–P9 security acceptance gates remain open and are separate from this CI maintenance.

#### Owner-confirmed user model / boundary / login (2026-10-23)

- **Three company actor groups are distinct:** (1) protected canonical CompanyOwner: Dashboard, full company capabilities within all structural/tenant/business invariants; (2) Backoffice officials, administrators and warehouse employees: Dashboard roles/capabilities and exact warehouse/location/branch scope; (3) FieldRepresentative: Flutter/FIELD only, with field role grants AND own WorkSession/route/territory/shop/visit/vehicle custody/transfer assignment. No cross-company/channel/employee/warehouse/representative leakage.
- **Flutter task ownership:** Flutter app plus its necessary FIELD Backend seams only. Separate conversations own Dashboard Reports, Settings, employee/user-management UI and other administrative workflows. Reusing the single central capability catalog does NOT authorize changing another worker's staff/warehouse pages.
- **Retired admin flag:** `Driver.is_admin` was already removed from active ORM and Alembic `f2c7a9d4e611` drops the column. Never redo identity cutover. The global non-reintroduction CI gate is now complete through PR #502; immutable historical migrations/test-only evidence and operational Driver FKs are not authority.
- **Company code is mandatory tenant selection in FIELD login:** `POST /driver/login` requires `company_code` alongside username/password, establishes the company/RLS context before authenticating a FIELD principal. Keep this server-side check for V1; optional UX convenience is remembering only the last successfully used company code, not auto-authorizing a company or relaxing offline identity protection.
- [ ] **Login release-security gate:** current Flutter LoginScreen pre-fills a synthetic company code, username and password in `kDebugMode`. Audit and remove hardcoded credentials from any user-distributed/debug release candidate and ensure no password persistence for the company-code UX. The company-code requirement remains.
- **Database test-data note:** owner confirms present DB data is disposable testing only, but tenant-safe schema/migrations, correct company FKs, permission/RLS validation, negatives and future production safety are mandatory. This permission does not authorize modifying/deleting the user's local databases, repo, folders or other local data.
- [ ] **Pending acceptance:** scoped default field roles/backfill before enforcement, instant revocation, wrong principal/company/route/location/visit/warehouse/shop rejection with no mutation side effects, DUAL_SPLIT isolation, system-role/edit anti-escalation, offline exact replay, current Backend/Dashboard parity and real Android device end-to-end. Never mark implementation checkboxes based only on contract approval.

**Separate prior `is_admin` history (do not repeat):** Canonical Identity + persisted Backoffice capabilities/scopes already replaced Driver-flag authority. `Driver.is_admin` was physically dropped by migration `f2c7a9d4e611`, and the current ORM Driver has no such field. The *repository-wide automated reintroduction-prevention source/architecture CI gate* is now complete through merged PR #502, after a zero-known-Runtime-authority scan and mutation tests. Existing targeted login, driver, and physical-drop tests remain complementary proof alongside the automated future-regression gate. No new identity migration and no second replacement of `is_admin` are authorized.


## 7. Session / route / custody

- [x] Start Session follows the current Backend contract: location evidence is optional/best-effort, while route/vehicle/custody/commercial eligibility remains Backend-authoritative.
- [x] Flutter does not duplicate Backend custody/vehicle-operational checks as authority; local session UI/state is presentation/recovery only.
- [x] Work Session surfaces typed actionable Backend rejection state (status/code/context/request ID) without free-text machine classification or replacing the loaded Dashboard state.
- [x] End Session remains online/reconciled and only completes after Backend confirmation; active break/pending handshake and other Backend refusals preserve active state with no fake offline completion.
- [x] Pending transfer acceptance/rejection preserves exact decision and reason.
- [x] Backend transfer response is state-idempotent for exact repeated accepted/rejected decisions on current base.
- [x] Flutter replay preserves the exact decision/reason and fails closed on conflicting prior decisions.
- [x] Batch transfer UI and single transfer UI share one exact durable command model.

### 7.1 Session / route / custody authority stability point — 2026-10-23

- [x] Implementation branch: `sol/flutter-v1-session-route-authority-closure`.
- [x] Exact worker HEAD: `8a17bdf0c6f69888631fe9682a546fbcdf9a0b2d`.
- [x] PR #465 merged to `main`; merge commit: `3d9a1edd750b02f865c3258349b4148f83b16a95`.
- [x] Current Backend `SessionStartRequest` accepts nullable latitude/longitude; Flutter sends valid optional coordinates when available and omits unavailable/invalid device evidence.
- [x] Backend remains sole authority for current route, vehicle, custody location, vehicle operational state, commercial context and active-session eligibility.
- [x] Active-session restart recovery continues through `GET /driver/sessions/active`.
- [x] Break remains online/reconcile-only; no durable historical break queue exists.
- [x] End Session does not invent settlement authority in Flutter; the Backend endpoint closes the workday and separately enforces active-break/pending-handshake blockers.
- [x] Deterministic Work Session refusals preserve DashboardLoaded and attach typed actionable issue state instead of degrading to SnackBar-only/global DashboardError handling.
- [x] Work Session machine decisions use operation + HTTP status + stable code + structured context/request ID only; display text remains display-only.
- [x] Ambiguous Start/End/Break mutations reconcile by re-reading authoritative Backend session/runtime state and never blindly claim success.
- [x] Exact-head run `39774826354`: `flutter analyze` PASS + 71 focused/regression tests PASS.
- [x] Current-main PR #465 integration gates PASS: Session Route Authority, Work Session Behavioral, Session/Custody Decomposition, Custody Behavioral, Transfer Handshake, Recovery Sync UX, Offline Durable and Local Custody Projection.
- [x] Inventory CP2 historical unchanged-file assertion remains unrelated to this Flutter closure.

## 8. Visit workflow / commercial action closure

- [x] Pending / completed / postponed semantics match Backend: Sale/NoSale -> Completed; Postponed -> Pending.
- [x] Sale requires positive sold carton/pack quantity; samples/returns alone cannot constitute Sale.
- [x] NoSale supports samples, all three return reasons, and prior-debt collection exactly according to the current Backend contract.
- [x] Postponed contains no financial/inventory actions; conflicting drafts fail before durable staging.
- [x] Positive samples require a nonblank <=255-character reason and preserve canonical carton/pack quantities.
- [x] Bonus/reward quantity is never client-authoritative; Backend offer/reward calculation remains authority.
- [x] Flutter never sends authoritative sale price or chooses FEFO Batch; Backend pricing/FEFO remains authority.
- [x] Shop debt/cash inputs use exact money transport.
- [x] Server confirmation/rejection drives final Visit outcome; ambiguous results preserve the existing durable command/evidence and unresolved prior commands block correction.
- [x] Existing completed/offline correction behavior is audited and preserved: collection-only Visit money/notes restore correctly, prior unresolved commands block new correction, and old->new projection remains exactly once.

### 8.1 Visit commercial action correctness stability point — 2026-10-23

- [x] Codex implementation branch: `codex/flutter-v1-visit-commercial-action-closure`.
- [x] Exact Codex HEAD: `c8be50bc1623d8279302a839ba4232531efb5fde`.
- [x] Original PR #463 independently reviewed by Lead and incorporated as a parent of the current-main integration.
- [x] Lead integration commit: `5a429ad313b7d2c390adb3945da5cec2b68363d6`.
- [x] Integration PR #467 merged to `main`; merge commit: `c085e63ddc1a4c64aa73749340d640b6353e6d0a`.
- [x] All 11 Codex-owned paths were unchanged on current `main` from the worker base before integration, proving no hidden file-level overwrite.
- [x] Current Backend `VisitUpdateRequest` / `VisitItemInput` contract independently re-read and matched by the feature-owned action policy.
- [x] Conflicting NoSale cash and Postponed actions fail before staging instead of being silently stripped.
- [x] Application callers cannot bypass sold-quantity, sample-reason, duplicate-product and action-shape validation.
- [x] NoSale confirmation never invents a reason; Postponed never invents a shop-closed reason.
- [x] Completed collection-only Visits restore exact editable money/notes independently of cart JSON.
- [x] Cached catalog price values do not change staged payload or approval; Backend commercial readiness/preview/frozen invoice remains authority.
- [x] No client price, FEFO Batch, bonus/reward quantity, cached debt balance or tax engine became authority.
- [x] Exact-head FIELD run `39774956886` PASS; correction/offline/commercial-decomposition/decomposition exact-head gates PASS.
- [x] Current-main integration PR #467 gates PASS: FIELD seam adapters + Backend contract readback, Visit commercial decomposition, Visit decomposition, Visit correction and Offline durable.
- [x] Inventory CP2 historical unchanged-file assertion remains unrelated to this Flutter Visit closure.
- [x] Cached route-action compatibility flags (`is_on_break` / `is_authorized`) no longer act as Visit/Shop authorization authority; closed by the accepted route-action authority integration.
- [ ] Final real-device Visit journey remains part of release acceptance.

## 9. Local inventory projection

Current model aggregates cartons/packs by product only.

Closure:
- [x] Treat local stock as a projection, never inventory SSOT.
- [x] Keep AVAILABLE sellable quantity distinct from non-sellable returned custody; Backend custody and pending local return evidence are separate presentation/read models.
- [x] Do not invent Batch allocation locally; pending local custody derives only product/reason/quantity evidence from the durable command and exposes no Batch identity.
- [x] Re-sync safely after accepted transfer, Visit submission and Recovery: confirmed Visit finalizes/deletes before authoritative refresh; Transfer/Recovery reuse the accepted single sync path and unresolved evidence blocks unsafe refresh.
- [x] Offline edits/corrections change only their own local AVAILABLE projection exactly once via durable `local_effect_applied` + old-to-new delta.
- [x] No clamp-to-zero behavior silently hides a negative/inconsistent projection; typed reconciliation errors fail closed and preserve durable evidence.

### 9.1 Sync / Recovery exact reconciliation stability point — 2026-10-23

- [x] Implementation branch: `sol/flutter-v1-sync-recovery-reconciliation-closure`.
- [x] Exact worker HEAD: `24f82cd9f40dc363e9b51378d4a7e62800719133`.
- [x] PR #470 merged to `main`; merge commit: `38e1909be3327e080bb3931e3efd56cd6e539b38`.
- [x] Confirmed direct Visit ordering is Backend confirmation -> exactly-once local finalize -> durable delete -> authoritative `syncDown()` refresh attempt.
- [x] Refresh failure after a confirmed/finalized Visit is deferred as read-model recovery and does not recreate evidence or report a false mutation failure.
- [x] Failed local finalization never deletes durable evidence; later Backend idempotent replay can finish local finalization.
- [x] Queued Visit/Transfer replay remains FIFO and stops at the first unresolved/blocked/ambiguous/local-failure record.
- [x] Owner/tenant validation occurs before legacy request/command identity repair; foreign/unattributed rows are never adopted.
- [x] `LocalInventoryProjectionException` preserves its exact stable projection code.
- [x] Real typed `DatabaseException` maps to pending `LOCAL_DATABASE_TRANSIENT`; arbitrary local exceptions map to blocked `LOCAL_COMMAND_ERROR`.
- [x] Sync/Recovery owned machine decisions no longer classify failures using exception/free-text contents.
- [x] `syncDown()` reconciliation blockers use stable `SYNC_*` codes and re-check durable evidence after the authoritative network fetch before replacing local projections.
- [x] Recovery blocked evidence has precedence and can never be reported as synced.
- [x] No second queue, table, migration, replay engine, transfer store or Visit replay engine was introduced.
- [x] Exact-head run `39871813535`: `flutter analyze` PASS + 119 focused/regression tests PASS.
- [x] Current-main PR #470 integration gates PASS: Sync/Recovery Reconciliation, Recovery Sync UX, Projection Integrity, Auth Session Recovery and Offline Durable.
- [x] Inventory CP2 historical unchanged-file assertion remains unrelated to this Flutter closure.
- [x] Legacy `SyncRepository.respondToTransfer()` compatibility debt bounded and hardened: it remains outside the accepted Custody production authority path, preserves deterministic 4xx structured evidence, and retains existing ambiguous fallback behavior without text parsing.
- [x] Global Flutter business/runtime free-text classification audit completed across 150 runtime Dart files; no remaining Arabic/English exception-message branching was found outside low-level SQLite migration compatibility.

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
- [x] `local_database.dart`: remaining Visit/inventory projection persistence split completed with compatibility facade retained and transaction/exactly-once behavior preserved.
- [x] `visit_bloc.dart`: canonical payload serializer and local projection helpers extracted before further Visit behavior work.
- [x] `visit_bloc.dart`: Event/State declarations extracted behind compatibility exports.
- [x] `visit_bloc.dart`: completed-visit restoration, cart policy, submission mapping, and submission use-case extracted before FIELD seam wiring; Bloc reduced to orchestration shell.
- [x] `visit_screen.dart`: catalog/product-card presentation mechanically extracted before Returns/Batch UI changes; screen reduced from ~1445 to ~1018 lines.
### 10.2a Local Visit / inventory projection persistence split stability point — 2026-10-23

- [x] Worker branch: `sol/flutter-v1-local-visit-projection-persistence-split`.
- [x] Exact worker HEAD: `0abfdc46523cdfa747782147e68380c42915ce34`.
- [x] PR #475 merged to `main`; merge commit: `a00ae5cb5f4e46d88dbb922518ab4d60c1e92e0a`.
- [x] Lead performed two manual review passes plus an automated public-method inventory check before merge.
- [x] No public `LocalDatabase` Visit API was removed; only the two intended private projection orchestration helpers left the facade.
- [x] `LocalDatabase` reduced from 1025 to 770 lines while preserving all existing public Visit persistence signatures as delegates.
- [x] Visit-specific persistence moved to `core/db/visit/visit_local_persistence.dart` and `visit_inventory_projection_persistence.dart`; no `core -> features` dependency inversion was introduced.
- [x] Finalization order remains one SQLite transaction: command read -> `local_effect_applied` guard -> OLD evidence -> OLD->NEW projection -> Visit update -> marker=1.
- [x] Same-command replay remains a no-op before any second projection effect.
- [x] Projection failure codes and `LocalInventoryProjectionException` propagation remain unchanged.
- [x] Schema version, migrations, tables, columns, owner semantics, FIFO, request IDs, SyncRepository ordering and returned-custody separation were unchanged.
- [x] Exact-head run `39874737886`: `flutter analyze` PASS + 76 tests PASS.
- [x] Current-main PR #475 gates PASS: Persistence Split, Projection Integrity, Visit Correction, Offline Durable and Sync/Recovery.
- [x] Inventory CP2 historical unchanged-file assertion remains unrelated to this Flutter closure.

- [ ] `visit_screen.dart`: residual shell/footer/contact/submit presentation split only when the next owned responsibility requires it.
- [x] `dashboard_bloc.dart`: Work Session and Custody responsibilities mechanically extracted before behavior work.
- [x] `dashboard_bloc.dart`: Recovery/quarantine/sync classification extracted behind feature-owned RecoveryReader/RecoverySyncCoordinator; compatibility counts/events remain only as wiring.
- [x] `dashboard_screen.dart`: Work Session controls, pending-transfer dialog, and vehicle-inventory presentation extracted into feature-owned presentation files.
- [x] `dashboard_screen.dart`: Recovery/sync presentation extracted to `features/recovery/presentation/**`; residual summaries/navigation shell remains.
- [ ] `sync_repository.dart` (~480 lines): extract operation-specific Visit/Transfer/Shop adapters as those contracts are wired.
- [x] Visit List / Route Execution responsibility extracted into `features/visits/list/{application,data,presentation}`; `VisitListBloc` remains a thin compatibility shell and `VisitListScreen` a composition/navigation shell.
- [x] app/bootstrap/theme mechanical extraction completed in PR #447; broader visual design-system adoption remains intentionally deferred to the final UI/UX wave.

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
- [x] Visit/Custody behavioral wiring for the accepted FIELD adapters is complete.

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
- [x] Custody behavioral authority is feature-owned; DashboardBloc retains composition/compatibility wiring only.
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
- [x] FIELD Return Resolution / Damaged / commercial-readiness / authoritative invoice UI/submission wiring is complete on the accepted application orchestration.
- [x] Factory_Defect / Expired / Damaged return submission uses the feature-owned Return Resolution contracts.

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
- [x] Visit FIELD UI/submission behavioral wiring is complete on the feature-owned FIELD application orchestration.
- [x] Custody behavioral wiring is complete and integrated.

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
- [x] Custody behavioral closure completed separately and is integrated.
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
- [x] Visit FIELD UI/submission wiring completed in PR #449.
- [x] Local projection / returned non-sellable custody integration completed in the accepted custody projection wave.

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
- [x] Operator-facing Return Resolution / Damaged / invoice / commercial-readiness wiring completed in PR #449.
- [x] Durable submission carries resolved opaque return evidence without changing request-id ownership.

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
- [x] Silent clamp-to-zero AVAILABLE projection debt closed in PR #457; invalid pack size/state/underflow now fail closed with stable typed codes.

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
- [x] Route-action cached `is_on_break` / `is_authorized` authority seam closed: Visit/Shop forms no longer deny navigation or mutation from stale SecureStorage flags; current Backend eligibility remains final authority.
### 10.14a Visit route-action Backend-authority stability point — 2026-10-23

- [x] Codex branch: `codex/flutter-v1-visit-route-action-authority-closure`.
- [x] Exact Codex HEAD: `6e9f91163ca137d0424f2ae9a730fa54c9d3da6f`.
- [x] Lead integration commit: `ee1ee6e29cc07c15cee51bde3e16aee238908c44`.
- [x] Integration PR #472 merged to `main`; merge commit: `3b29c17609de97299809d035f8d00b306cfdb41c`.
- [x] All 9 Codex-owned paths were unchanged on current `main` from the worker base before integration.
- [x] VisitScreen no longer reads cached `is_authorized` / `is_on_break` or cached zone mismatch as final mutation authority.
- [x] Visit List navigation no longer denies Add Shop/Open Visit because of stale/missing/malformed SecureStorage flags.
- [x] Add Shop stale break/authorization UI locks were removed only after verifying current Backend `POST /shops` enforces active session, active route, break state and `is_authorized_to_sell`.
- [x] No live Visit preflight was added; offline Visit staging remains available with the same durable command identity/body and Backend replay decides final eligibility.
- [x] Current Backend Visit authority still owns active/unsealed session, route/driver assignment, zone/emergency/shortage exceptions, vehicle/custody, inventory locks, break/sell authorization and pending HANDSHAKE checks.
- [x] No new permission cache, authorization database, replay queue or business-rule engine was introduced.
- [x] Current-main PR #472 gates PASS: Visit List Route, Shop Reconciliation, Offline Durable, Visit Commercial Decomposition, Visit Decomposition and FIELD client/backend readback.
- [x] Inventory CP2 historical unchanged-file assertion remains unrelated to this closure.

- [x] SyncRepository compatibility failure seam closed: deterministic transfer rejection preserves original Dio/ApiFailure evidence, and current SyncRepository contains no generic `throw Exception(...)` or exception-text classification.


### 10.15 App / Bootstrap / Theme mechanical foundation stability point — 2026-10-22

- [x] Implementation branch: `sol/flutter-v1-app-bootstrap-theme-foundation`.
- [x] Exact implementation HEAD: `28261966c028e04ac7229d9d88baf4fcb3bf9730`.
- [x] `main.dart` is reduced to the executable bootstrap entrypoint and preserves the `MyApp` compatibility export.
- [x] Startup orchestration is mechanically owned by `app/bootstrap/**` with Widgets binding, Arabic date initialization, dotenv policy, ApiClient unauthorized wiring, Sentry initialization and runApp semantics preserved.
- [x] Release-missing-`.env` remains fatal; Debug-missing-`.env` remains nonfatal with the existing development warning policy.
- [x] Flutter framework, platform async and ErrorWidget crash handling remain preserved behind one app-level error boundary.
- [x] Exactly one production AuthBloc lifecycle remains authoritative for ApiClient unauthorized handling, provider composition and unauthenticated navigation.
- [x] MaterialApp composition, Arabic locale/delegates, Splash startup and DashboardBloc provider were mechanically extracted without router migration.
- [x] Existing theme, gradient and System UI values were centralized under `app/theme/**` without visual redesign.
- [x] No Visit, Visit List, Custody, Recovery, SyncRepository, LocalDatabase, Backend or Dashboard-web production ownership was touched.
- [x] Exact-head GitHub Actions run `39711114163`: `flutter analyze` PASS and focused/regression test gate PASS.
- [x] PR #447 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `510d1eab21e5fbaa46c5b05848ffdd2d1cc65212`.
- [ ] Broader field design-system adoption by feature screens remains open.
- [ ] Workday/task-first home remains open; this mechanical foundation does not claim that product/UI closure.


### 10.16 Visit FIELD operator wiring stability point — 2026-10-22

- [x] Implementation branch: `codex/flutter-v1-visit-field-wiring`.
- [x] Exact implementation HEAD: `b1965a2880998e4dfcd0bf8ba857004ebb711f2f`.
- [x] Sale checks Backend commercial readiness and requires explicit confirmation of Backend-authoritative invoice preview.
- [x] Damaged / Expired / Factory_Defect returns use Backend-owned Return Resolution; ambiguity has no default choice and asks only for requested human/business evidence.
- [x] Canonical submission carries the exact opaque signed return token and exact carton/pack quantities; raw `batch_id` is never exposed.
- [x] Exact cash/debt text is preserved through the current authoritative submission path; cached pricing no longer drives commercial acceptance/rejection.
- [x] Existing durable Visit UUID/body staging and replay authority remains unchanged; unresolved prior command evidence blocks a new correction.
- [x] Confirmed Sale reads committed/frozen invoice evidence; invoice-read failure never retries the Visit mutation.
- [x] All five PR-triggered regression workflows PASS on exact HEAD, including FIELD, correction, mechanical/commercial decomposition and Offline gates.
- [x] PR #449 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `c67091d59cf05f51795fce538e8f131ac0e465e4`.
- [ ] Real-device/current-Backend journey remains a final release acceptance gate.

### 10.17 Transfer handshake exact-replay stability point — 2026-10-22

- [x] Implementation branch: `sol/flutter-v1-transfer-handshake-closure`.
- [x] Exact implementation HEAD: `d6aea988b79328faba8800f5698dac78a2263bee`.
- [x] Real `real_transfer_id` is the only decision identity; invalid/missing IDs fail closed and are never reconstructed from product/quantity context.
- [x] Accepted/rejected decision and normalized rejection reason are staged in the existing durable-command store before first send and replay exactly.
- [x] Conflicting or blocked prior decision evidence fails closed without overwrite or evidence destruction.
- [x] Connection/timeout/408/429/5xx ambiguity preserves the exact pending command; deterministic failure becomes blocked evidence without free-text classification.
- [x] Confirmed server success is separated from local finalization; surviving evidence replays safely against Backend state-idempotency.
- [x] Batch responses preserve deterministic order and enforce the live Backend runtime maximum of 100; an ambiguous/blocked chunk stops later chunks.
- [x] Existing SyncRepository durable replay remains the single replay engine; no second table, migration or sync engine was introduced.
- [x] Exact-head worker run `39713469101`: analyze PASS + 68 focused/regression tests PASS.
- [x] Post-PR integration gate after Visit FIELD merge: all 8 triggered Flutter regression workflows PASS.
- [x] PR #450 merged into `sol/flutter-v1-field-closure`.
- [x] Merge commit: `435c5a0fb5b8bd7bbc47ba4937c6f6632d6e730d`.
- [x] Backend batch now returns stable public per-item `error.context.transfer_id` for deterministically attributable failures; Flutter blocks only the identified decision and preserves the sibling pending evidence without parsing messages.

### 10.17a Transfer batch per-item failure identity stability point — 2026-10-23

- [x] Codex branch `codex/flutter-v1-transfer-batch-failure-identity-closure` completed at HEAD `5486b7827b296e227b8fc09fb1deb4b3d07a319f`; no worker merge.
- [x] Lead independently inspected 14 changed files and verified public transfer ID attribution, full Backend atomicity/rollback, duplicate and max-100 guards, exact replay and fail-closed identity handling.
- [x] Current-main integration commit `4ca4daf32aa9219e0657c96f90eba9d6b6f458d1` preserves both opening inventory valuation additions in `wa_backend/schemas.py` and Codex's transfer validators, with main and worker as parents; no reset, rebase or force-push.
- [x] Real PostgreSQL migrated acceptance against integrated HEAD: 14 PASS, no skipped cases; proves rollback after real movement writes and no second effect for exact accepted/rejected replay.
- [x] Integrated-head Flutter analyze PASS, Custody 77 PASS, FIELD adapter 67 PASS, Offline/Recovery 72 PASS; Backend focused 45 PASS, authority/transport 100 PASS + 224 subtests.
- [x] All 9 transfer/Flutter/FIELD/custody/recovery relevant GitHub Actions workflows PASS on integrated HEAD.
- [x] Deterministic structured 4xx with one in-chunk public `transfer_id`: matching durable command blocked, siblings pending as `TRANSFER_BATCH_NOT_COMMITTED`; malformed/out-of-chunk identity blocks whole chunk, transport/408/429/5xx stays pending, 401 preserves auth recovery.
- [x] Existing LocalDatabase, SyncRepository, TransferDecisionStore, Visit, Shop and Sentry surfaces unchanged by Codex; no second replay engine, speculative live finalization or discarded evidence.
- [x] PR #481 merged into `main` at `9d7b72b47c8e8adeafa0ce8864d35d6ca1a6f0ea`; Codex branch auto-deleted.
- [x] Six unrelated CI failures remain red: CP1/CP2 legacy assertions, Purchase reference/currency stale Alembic fixture versions, Supplier Dashboard lint; these are not represented as PASS and require separate ownership.
- [x] Final full Flutter suite, Android debug build, real-device E2E and network-loss/restart/replay acceptance remain OPEN.

### 10.18 Local inventory projection integrity stability point — 2026-10-22

- [x] Implementation branch: `sol/flutter-v1-projection-integrity-closure`.
- [x] Exact worker HEAD: `b44b558aafefb3a404db59ce6ea37848ca68ede3`.
- [x] PR #457 merged to `main`; merge commit: `26d2dcb1dc200cba9aa15fed038bb30f92a9e13c`.
- [x] Initial Visit AVAILABLE application and completed-Visit correction share one typed projection engine.
- [x] Silent SQLite `MAX(0,...)` stock clamping removed.
- [x] Invalid `packs_per_carton`, malformed local state, missing product and underflow fail closed with stable `LOCAL_PROJECTION_*` codes.
- [x] Projection failure rolls back local state, never sets `local_effect_applied=1`, and preserves the existing durable command as unresolved/blocked evidence.
- [x] Same durable command replay cannot apply inventory twice; correction remains old-to-new delta only.
- [x] Returned DAMAGED/non-sellable custody remains separate from AVAILABLE projection.
- [x] Exact-head run `39721422304`: analyze PASS + 48 focused/regression tests PASS.
- [x] Current-main PR integration: Projection Integrity, Visit Command Correction and Offline Durable gates PASS.
- [x] Unrelated Inventory CP2 historical unchanged-file gate remains a pre-existing stale assertion and is not caused by this Flutter diff.

### 10.19 Canonical FIELD principal / durable owner stability point — 2026-10-22

- [x] Codex implementation branch: `codex/flutter-v1-principal-owner-identity-closure`.
- [x] Exact Codex HEAD: `c11f97aa126b32ef5908102ac56292656587606b`.
- [x] Original draft PR #455 was independently reviewed by Lead; its current-main conflict was limited to shared `SyncRepository` text after Projection PR #457.
- [x] Lead integration merge commit: `ce7e2af2fdb240cca370665b424986892e1c75bc`, preserving current-main Projection work and Codex identity work with both histories as parents.
- [x] Integration PR #459 merged to `main`; merge commit: `6e2d7dcb9e7e145ae9aa7c50e22f2693ed570b9f`.
- [x] Backend FIELD identity is explicitly separated into credential `principal_id`, FIELD `representative_id`, company identity and mapped operational `legacy_driver_id` / public `driver_id`.
- [x] Existing durable `owner_driver_id` keeps the mapped operational Driver locator semantics; it is not redefined as principal/profile ID.
- [x] New Visit and Transfer durable commands require authenticated company + mapped Driver ownership before staging.
- [x] Unattributed/foreign unresolved evidence fails closed and is never opportunistically rewritten or claimed by a matching marker.
- [x] Same attributed owner may resume pending/blocked evidence; different driver/company and failed inspection remain blocked.
- [x] Refresh network/timeout/5xx ambiguity preserves the session/evidence; only confirmed 401/403 rejection may trigger unauthorized logout.
- [x] Late refresh responses cannot overwrite or reject a newer authenticated session.
- [x] Projection-owned `local_database.dart` and `local_inventory_projection.dart` remained byte-identical to accepted PR #457 main state.
- [x] 19/19 non-overlap Codex files in the integration tree are byte-identical to Codex HEAD; shared `SyncRepository` preserves both durable-owner enforcement and typed Projection error preservation.
- [x] Combined PR #459 gates PASS: Auth, Network, Offline Durable, Transfer Handshake, Custody Behavior, Session/Custody Decomposition, Local Custody Projection, FIELD seams and Projection Integrity.
- [x] Inventory CP2 historical unchanged-file assertion remains an unrelated pre-existing stale gate; `live_stock.py` was unchanged by this closure.
- [ ] Real-device same-user restart with pending sync remains part of final field acceptance.

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
- [x] auth/offline owner guard regressions;
- [x] API error parsing;
- [x] mutation retry classification;
- [x] durable command migration and persistence;
- [x] visit request serialization;
- [x] stable request_id replay;
- [x] return Batch-resolution typed transport/adapters;
- [x] Damaged/Expired/Factory_Defect payloads;
- [x] exact money transport;
- [x] break offline policy;
- [x] transfer exact-repeat/state-idempotent replay;
- [x] quarantine/recovery preservation;
- [x] account/company switch with pending/blocked work;
- [x] local projection apply/correction exactly once.

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
- [x] exact-money transport; local figures are estimates, not authority.
- [x] sale/collection/sample contract parity at the Flutter contract/wiring gate.
- [x] Damaged / Expired / Factory_Defect + Backend Batch-resolution flow.
- [x] durable command store migration preserving old rows.
- [x] visit/offline focused and regression tests.

### Day 3 — projection/session/custody + field-first UX
- [x] correct AVAILABLE-out vs DAMAGED-custody-in V1 projection: replacement-out affects local AVAILABLE projection while returned goods appear separately as pending DAMAGED evidence until Backend custody becomes authoritative.
- [x] completed-visit AVAILABLE projection correction applies old-to-new delta exactly once.
- [x] Work Session behavior/authority separated from DashboardBloc into feature-owned boundaries.
- [x] Custody behavioral authority is feature-owned; DashboardBloc is compatibility/composition wiring and Recovery/quarantine/sync responsibility is feature-owned.
- [x] transfer exact-decision replay and 100-item runtime batch limit.
- [x] shop creation typed transport + stable request UUID + ambiguous-result exact replay reconciliation.
- [ ] app shell/design tokens and workday-task-first home.
- [x] persistent sync/recovery status distinguishes pending, blocked/recovery-required, synced, incomplete and unresolved outcomes.
- [ ] compact visit/quantity/returns field UX.

### Day 4 — field acceptance and only blocker fixes
- [ ] real Android device end-to-end journey;
- [ ] network-loss/restart/retry scenarios;
- [ ] Backend/Dashboard evidence verification;
- [x] CI Flutter analyze, full 473 tests and Android debug APK build (synthetic configuration, not on-device acceptance);
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
