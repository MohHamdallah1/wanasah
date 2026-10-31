# Dispatch P0 — permanent pre-cutover Adjust Load recovery

**Scope:** PR #697 / issue #696. Owner-delegated architecture decision on PR #697 supersedes the earlier read-only-only recommendation. Latest accepted main to reconcile before sign-off: `90bf762818fc00a2335e2befeafe8121396b4618`. This document describes code/acceptance behavior, not a production deployment.

## Canonical authority

Adjust Load keeps one operation authority: `operation_idempotency` plus the existing inventory/cost transaction. The unique identity remains `(company_id, operation, request_id)`; `created_by` and the canonical request hash remain part of the semantic identity. Original execution and recovery cancellation acquire the exact same transaction advisory key used by `begin_idempotent_operation`, then re-read the unique row while holding the lock.

The table now models an explicit lifecycle:

- `PENDING`: no response/completion and no cancellation metadata. Any row that survives in this state is forensic **INDETERMINATE** and is never retired or replayed automatically.
- `COMMITTED`: response JSON and completion timestamp are present; cancellation metadata is absent.
- `CANCELLED`: response/completion are absent and permanent cancellation actor/time are present.

Database checks reject mixed states. Existing completed rows migrate to `COMMITTED`; existing incomplete rows migrate to `PENDING`. There is no second operation ledger and cancellation is never represented as a successful operation response. The direct legacy correction writer that also uses `operation_idempotency` explicitly writes `PENDING -> COMMITTED` so the migration is backward-compatible with that path.

## Pre-cutover route-only recovery contract

The old Dashboard durable command preserves the original UUID and deltas but does not independently prove its original Vehicle/Warehouse assignment, so it is never replayed merely because today's Route happens to point somewhere.

`POST /dispatch/route/{route_id}/adjust_inventory/recovery` requires current `dispatch.execute` authority on the Route and the exact legacy actor, computes the historical route-only hash, takes the canonical idempotency lock and returns:

- **COMMITTED** — exact actor/hash completed evidence. Return the original response. The operator explicitly acknowledges it; stock is not replayed.
- **NOT_CONFIRMED** — no canonical row under the locked identity. The UI may offer permanent cancellation only after this server verification.
- **CANCELLED** — the exact request is already permanently fenced. It cannot execute later.
- **INDETERMINATE** — a persistent incomplete witness exists. Preserve it for forensic handling; do not cancel or replay.

Hash conflicts and actor conflicts are stable HTTP 409 responses. Cross-company, missing current Route authority, and revoked execution rights fail closed before recovery mutation.

## Permanent same-UUID cancellation

`POST /dispatch/route/{route_id}/adjust_inventory/recovery/cancel` is the only authorized retirement path. It repeats current Route authorization, then under the same canonical transaction advisory lock re-reads `(company, operation, UUID)` and actor/hash:

- If the original operation committed first, return **COMMITTED** evidence; do not cancel and do not replay.
- If no row exists, atomically insert an immutable **CANCELLED** tombstone with the exact original company, actor, operation, UUID and payload hash plus `cancelled_at/cancelled_by`.
- If already **CANCELLED**, return **CANCELLED** again. This makes response loss, retries, multiple clients and restarts safe.
- If **PENDING/INDETERMINATE**, actor-conflicted, or hash-conflicted, fail closed. Never convert uncertain evidence into cancellation.

Every late original request that reaches `begin_idempotent_operation` and finds **CANCELLED** returns stable HTTP 409 `DISPATCH_ADJUSTMENT_CANCELLED`. No inventory movement, cost event or success response can be produced. Persisted `PENDING` returns stable 409 `DISPATCH_ADJUSTMENT_INDETERMINATE` and the Dashboard preserves the durable command identity.

## New immutable physical-context contract

Historical requests without `context` keep the exact pre-cutover route+deltas hash. New Dashboard commands carry a versioned `ADJUST_LOAD_CONTEXT_V2` object inside the durable payload and canonical backend request hash:

- expected physical Vehicle id;
- source Warehouse inventory-location id;
- WorkSession id or explicit null;
- Route adjustment-context revision.

`DispatchRoute.adjustment_context_revision` starts at 1 and increases when pre-session driver/Vehicle assignment changes or when a WorkSession is bound. The backend validates all context fields while holding the Route/session locks before inventory mutation. This closes the ABA case where a Route is moved away and later returns to the same visible Vehicle: the revision no longer matches. Route id remains in the canonical request hash.

The HTTP mutation endpoint never creates a new operation from a context-less body. A context-less identity is historical-only: an existing COMMITTED row may return its recorded response, CANCELLED returns the terminal conflict, PENDING remains forensic INDETERMINATE, and an absent row returns HTTP 409 `DISPATCH_ADJUSTMENT_CONTEXT_REQUIRED` without creating idempotency state or moving stock. The separate recovery endpoints retain the historical hash so an absent legacy identity can still be verified and explicitly cancelled. Legacy Vehicle/Warehouse headers are not an execution authority and cannot defeat ABA by matching again later. Trusted in-process callers are upgraded to a V2 expected context before hashing and then revalidated under the same Route/session locks; the repository has no production caller of this function outside the HTTP route.

## UX and acceptance

The AR/EN Dashboard never displays the technical UUID in normal recovery UI. It verifies first, then offers an explicit confirmation for permanent cancellation only after **NOT_CONFIRMED**. A lost cancellation response retains the local command; a verified **CANCELLED** or explicit successful cancellation can retire it. A cancellation race that discovers **COMMITTED** switches to the recorded-result acknowledgement path.

Focused acceptance in this PR covers real PostgreSQL16/FastAPI and built Chromium Dashboard behavior: committed-first, cancelled-first, two cancellation clients, simultaneous execute/cancel, late arrival, hash/actor/company/authorization conflicts, rollback, forensic INDETERMINATE, exact unit paths, context/ABA fencing, and zero unintended movement/cost on cancellation. The server-side ABA regression explicitly performs Vehicle V1 -> V2 -> V1, then submits a never-seen context-less UUID with the old visible V/W headers and proves 409 CONTEXT_REQUIRED, no idempotency row, and no movement/cost. Exact-head CI and independent lead review remain required before merge.
