# Live Stock in-flight authority: evidence and stop boundary

Base: `6fac1a885a8bdc47b057a57b6be0edc14d4fe862`. Frozen V1 workflow: authorized Warehouse Live Stock reads and their separate batch/source evidence. This branch changes tests, an isolated acceptance workflow and this document only. No production repair, #697/#704 file, closure-plan edit, production database or user-machine operation is authorized.

Executed results belong to the PR's exact-head CI and sanitized `http-evidence.json`/JUnit artifacts. This document describes the source trace, deterministic experiments and required safe invariants; it does not turn a source inference into runtime PASS.

## Source trace and evidence boundaries

| Consumer | Exact-base source | Authority / ordering mechanism | Focused evidence |
|---|---|---|---|
| List | MainInventory.tsx:385–439,997–1144 | Global+location canonical admission, company/principal/profile scope, location, request sequence and admission epoch before state/cache writes | Delayed page after known revocation, three identity-storage switches, Warehouse101→102 and superseded Vehicle32→NO_ACCESS/null |
| Summary | MainInventory.tsx:1147–1223,1414–1433 | Separate reader sequence/epoch; independent freshness; denied summary clears Warehouse evidence | Held summary after revocation/switch, late old-Warehouse count, summary before still-warm page with EN/AR freshness/direction |
| Batch detail | useLiveStockBatchDetail.ts:44–134 | Abort+sequence, exact location/product/currency, invalidation and parent denial | Delayed continuation after source403; existing refresh, Warehouse and revocation regressions |
| Source | useLiveStockBatchDetail.ts:209–299 | Abort+sequence and exact location/product/batch;403 propagates to parent and clears source/page | Delayed source after product change; existing collapse, fresh reopen, deny and identity checks |
| Warm cache | inventorySessionCache.ts:102–198; MainInventory.tsx:568–591 | Partitioned company/profile/principal and Warehouse; never an access grant; identity event clears old scope | Explicit cache readback after stale callbacks, null preserved instead of zero |
| Shared transport | useAuthFetch.ts:211–241,243–415 | Inventory AbortSignal guards the initial/retry read; refresh fetch at283–295 has no supplied signal; successful refresh at331–348 writes global storage and releases a global queue | Genuine FastAPI/PG16 delayed-refresh experiment below |
| Existing same-identity recovery | authStorage.ts:143–185; auth-session-refresh.test.tsx | readAccessTokenIfRefreshAdvanced handles same-sub/company refresh rotation on failed refresh | Existing focused regressions retained; this is distinct from a successful old refresh after a different login |

Paths in the table are under `dashboard/src/pages/inventory/` unless named as transport (`dashboard/src/hooks/useAuthFetch.ts`) or storage helper (`dashboard/src/lib/authStorage.ts`). Line references are the immutable base, not future edits.

React ordering tests deliberately hold promises even after AbortSignal cancellation, so correctness depends on admission/identity/sequence checks rather than a cooperative mock transport. Their capability hook is a unit boundary, **not genuine backend authorization proof**. AR/EN desktop/mobile Vehicle disclosure rendering remains covered by the existing actual component CP7 matrix, run alongside these tests. No new real Chromium or manual screen-reader certificate is claimed.

## Genuine authorization witness

The dedicated PG16 workflow reuses the accepted operational fixture: restricted NOSUPERUSER/NOBYPASSRLS role, FORCE RLS, actual FastAPI and real canonical login. All stock comes from the existing production-command fixture with independent Warehouse1000/value2200/reserved16/available976/blocked8 truth; no inventory/cost/ledger fixture writes are introduced.

The reader's same bearer reads real list, summary, batch and source responses under a persisted Warehouse grant, then the accepted fixture revoke command removes that grant in a separate committed runtime session. All four subsequent real HTTP reads must be403 with request IDs. Initial list must show Warehouse1000 and NO_ACCESS/null Vehicle disclosure; summary109/1 is independently prescribed by the fixture.

A previously committed authorized response and a later403 are not contradictory database snapshots. No claim is made that a server can retract bytes already sent. Once the client knows authorization/scope has changed, the old response must not reauthorize rows, costs, details, sources or cache.

## IF-01: stale successful refresh must not replace a new principal/company

Required invariant: a canceled reader from session A cannot install session A credentials after a genuinely authenticated session B has replaced it.

Reproduction in `dashboard/e2e/live-stock-inflight-auth.test.tsx`:
1. Log in A against actual FastAPI/PG16 using the canonical Owner fixture.
2. Use an invalid old access credential with A's genuine refresh credential; the actual inventory endpoint returns401 and the production useAuthFetch hook starts a real refresh.
3. Allow the server to complete the refresh successfully, then hold delivery of that unmodified Response at the client transport boundary. No HTTP response is fulfilled, fabricated or rewritten.
4. Log in B in the other real fixture company, store the actual canonical identity/credentials as Login does, and verify B through real `/inventory/access/me`.
5. Abort A's inventory reader and dispatch the principal storage-change event, representing the existing workspace invalidation.
6. Deliver A's held refresh response. The original inventory retry should remain canceled, and B's access/refresh credentials must remain unchanged.
7. Read `/inventory/access/me` with the credential now stored. The artifact records only company/principal IDs, status/Boolean outcomes and cancellation, never passwords or bearer/refresh values.

Current source has no identity/generation comparison before the successful refresh storage writes. The isolated jsdom environment supplies a test-only standards-compatible AbortSignal.any combiner when missing; it verifies cancellation propagation before the experiment. Production code is unchanged, and login/inventory/refresh responses still come from actual FastAPI. The experiment asserts the safe behavior and must stay **RED** if the old refresh overwrites B. If reproduced, this is a session-authority defect; **no claim of unauthorized inventory-row disclosure is made without separate proof**. MainInventory may still redact its mounted stale scope while the shared credential store is wrong.

If CI proves the violation, STOP and request a separately approved transport/auth repair owner. Do not change production useAuthFetch/authStorage, weaken this assertion, coerce null to zero or relabel the red invariant PASS. The eventual repair must preserve legitimate same-principal token rotation and isolate queued/retried requests across actual session identity/generation.

## Unverified risks / exclusions

- A stale failed refresh may call forceLogout with a newer current credential (useAuthFetch.ts:111–145,350–369); global refresh queue entries are not partitioned by principal. These are source-grounded risks, not runtime findings from the one success-race experiment.
- Revoke-between-server-authorization-and-SQL/response-emission semantics, the deliberately raced multi-request visual snapshot under a physical movement, full network-outage handling, real company midnight and manual visual/screen-reader approval remain outside this proof.
- Existing unit-level separately committed response/freshness checks are not a new whole-browser atomic snapshot guarantee. Backend R1 one-statement consistency and physical-location authority are unchanged.
- If IF-01 stops the wave, do not claim complete in-flight acceptance. Record passed cases, the precise confirmed failure and every unexecuted boundary in the PR.

## Owner-authorized repair — issue #706

The earlier STOP above is preserved as historical evidence, and was explicitly
superseded by the owner/lead decision on #705 (comment 6542866024). The repair
unblocks frozen V1 §5.1 session handling and fail-closed company isolation.

Production response admission now captures login generation plus canonical
company/principal/profile and refresh identity. Login creates a new generation,
including same-principal re-login. Refresh rotation preserves the generation.
Refresh work and cancellation consumers are partitioned by that snapshot.
Every awaited response/body and retry is rechecked; stale success, failure,
permission event and logout cannot mutate/admit into the newer session.
One canceled waiter does not cancel another live same-session waiter; an
abandoned flight cannot commit credentials. Rotated access from another browser
context is reused only within the still-current captured session.

The directly adjacent explicit logout handlers also await network completion.
Their final storage-clear/navigation now require their captured generation.
This bounded source finding and precise A-logout/B-login reproducer were
reported on #706; focused deterministic tests exercise the shared finalization.
The server remains the sole bearer/capability/RLS authority.

The dedicated gate retains the original 76 assertions and IF-01, adds 14 focused
auth cases, and requires exactly seven genuine HTTP cases plus the one canonical
fixture, without skips. New genuine cases exercise rejected old refresh,
overlapping company refresh/retry, same-session coalescing/rotation and foreign
read/mutation rejection. A read-only restricted-role PG digest compares both
tenants' balances, movements and cost states/events before/after the denied
mutation. It does not write inventory fixtures. Sanitized exact-head results
and limitations belong in the PR/CI; this text does not presume their outcome.

Still outside this bounded proof: a full multi-tab browser scheduling certificate,
the full remaining Live Stock movement-vs-reader freshness matrix, production
load certification, and independent Worker 2/lead security sign-off.

Adjacent finding ADJ-02: Login's successful response callback also crossed an
awaited boundary without session admission. Holding an older valid A login200
until after B login allowed A to replace credentials/metadata. Login now
captures before sending and checks after JSON, before any storage mutation;
stale failures also leave the newer session alone. The seventh genuine HTTP
case renders the production Login component, submits actual fixture credentials,
holds its unmodified real200, installs/verifies genuine B login, then releases A
and requires B's exact credentials and canonical identity to survive. Source
reproducer was reported immediately on #706. Runtime outcome is in exact-head CI.

## Final bounded consumer gaps — SEC-CACHE-01 / SEC-WS-01

Lead comment6543143361 and Worker2 review5722616499 accepted the core credential
repair but withheld cross-tenant sign-off on these two untested consumers.
This continuation retains that history and the unchanged90 units/seven real
HTTP/PG16 assertions. It does not claim historical unauthorized inventory rows.

SEC-CACHE-01: the actual tenant hook now observes complete same-SPA login/logout
commits and native cross-tab storage changes. Its key contains company/principal/
profile identity and login generation, with no bearer/refresh values. Both
sides of the awaited query are fenced; A data is not placeholder data for B.
Same-session token rotation retains the cache; a new login generation does not.

SEC-WS-01: the existing Dispatch socket effect captures its original session.
Open/message/close, refresh/alert timers, reconnect and visibility callbacks
check it. A session change closes the socket, aborts obsolete refreshes, drops
pending alerts and dismisses that feed's own visible alerts. Late callbacks
remain rejected even before the native storage notification arrives.
Only the socket-lifetime block and one auth import change in DispatchBoard;
a Git diff guard rejects any route/load/status/business changes outside it.
PR #697 and its branch are not edited or integrated.

The adjacent Product Import hook had the same unfenced session pattern.
Its socket, HTTP status admission, progress/debounce, fallback/reconnect and
completion toast/state now stop at the captured-session boundary. Existing
same-session lifecycle tests remain unchanged and are included.

The focused unit extension comprises16 actual-hook/component cases (including
AR/EN), plus the four existing Import lifecycle regressions. Deterministic
fake socket delivery explicitly invokes callbacks after close; it is not a
certificate of a real server WebSocket. The existing seven genuine HTTP/PG16
cases remain separate and mandatory. Expected dedicated total:110 units,
seven real HTTP cases, one canonical fixture, zero skipped. Exact-head outcomes
and renewed independent Worker2 review are recorded in the PR.
