# Atomic transfer batch failure identity

Exact base: 2893c134d3f892e0d4aa2ef32ee0ad3aa08cd607.
Frozen V1 workflow: field transfer decision / exact replay / blocked recovery.
No new queue, migration, table, authorization or replay authority.

Wire identity is error.context.transfer_id: the same public transfer_id used by
BatchTransferItem. real_transfer_id remains the pending-read compatibility name;
no second wire error key is introduced. No Batch/line/movement/storage ID is added.

## Backend matrix

| Code | Scope / context |
| --- | --- |
| FIELD_TRANSFER_NOT_FOUND | Single missing/not-owned requested transfer: transfer_id. Multiple missing: empty context. Same refusal does not reveal ownership/existence. |
| FIELD_TRANSFER_DECISION_CONFLICT | Exact transfer with previously confirmed different rejection reason. |
| FIELD_TRANSFER_ALREADY_PROCESSED | Exact transfer in an incompatible processed state. |
| FIELD_TRANSFER_REJECTION_REASON_REQUIRED | Exact transfer, including schema rejection through the batch-only route adapter. |
| FIELD_TRANSFER_DUPLICATE_ID | Before map construction / mutation; one duplicated ID is identified, multiple duplicated identities remain batch-level. |
| FIELD_TRANSFER_LINES_INVALID | Exact header with missing or multi-product inventory lines. Shared individual path stays unchanged via default field_batch_errors=false. |
| FIELD_TRANSFER_PRODUCT_MISSING | First deterministically known transfer whose product is unavailable. Other items are not claimed valid. |
| Existing product capability code | Reused unchanged, with the exact transfer_id appended. |
| FIELD_TRANSFER_DESTINATION_INVALID | Exact transfer failing its location or destination-state check. Existing structured helper code is preserved where supplied; private helper context is not copied. |
| FIELD_TRANSFER_BATCH_EMPTY / FIELD_TRANSFER_BATCH_TOO_LARGE | Batch-level, no transfer_id. Runtime maximum remains 100; 101 rejects with 413. |
| FIELD_TRANSFER_BATCH_MIXED_SESSIONS / FIELD_TRANSFER_BATCH_SESSION_INVALID | Batch-level, no fabricated identity. |
| FIELD_TRANSFER_BATCH_INVENTORY_CONFLICT / FIELD_TRANSFER_BATCH_CONFLICT | Atomic movement/concurrency failure without trustworthy item evidence; empty context. |
| FIELD_TRANSFER_BATCH_INTERNAL | Unexpected failure; no inferred last-iterated transfer. |
| Existing route/vehicle/session refusal | Remains global where one transfer cannot be blamed. |

The schema keeps its rejection validators. PydanticCustomError carries only
stable type and safe transfer identity; the batch-only APIRoute adapter maps
those two validation classes to the existing canonical HTTP envelope. All other
validation/error handling, including global/Sentry handlers, stays untouched.
The public PUT URL, typed request body/OpenAPI and authentication graph remain.

## Flutter transitions

| Result | Durable lifecycle |
| --- | --- |
| Deterministic 4xx with canonical code + integer transfer_id in this unique staged chunk | Failed decision blocked; every sibling pending with TRANSFER_BATCH_NOT_COMMITTED. None live/finalized/deleted. |
| Missing, malformed, out-of-chunk identity or missing structured code | Whole chunk blocked, preserving prior fail-closed behavior. |
| Network/timeout/408/429/5xx | Whole attempted chunk pending/unresolved, regardless of any identity. |
| 401 | Existing auth-recovery pending semantics preserved. |
| Unexpected non-4xx response exception | Cannot confer per-item attribution; whole chunk fails closed under existing classification. |
| Confirmed mutation success | Existing per-command finalization only. |

Identity parsing accepts only positive JSON integers within Backend DB-int bounds;
no strings, floats, booleans, regex or localized message extraction. Attribution
is used only on atomic batch calls. Individual transfer handling is unchanged.
The existing coordinator already stops later chunks on any non-live result.

All transitions use the original StoredTransferDecision object and its
commandId/recordId/body. TransferDecisionStore, owner checks, SyncRepository and
replay engine are unchanged. Retry of unaffected commands uses stageOrReuse;
blocked work is resolved by the existing Recovery owner, never silently replaced.

## Atomicity / proof

The batch retains one commit at the end and rollback on each exception path.
Allocation, movement-spec construction and individual endpoint source are
unchanged. Item refusals occur before posting; unknown movement/integrity
failures remain batch-level.

Focused PostgreSQL tests use the existing migrated/RLS synthetic FIELD fixture:
- middle prior-reason conflict returns exact ID and leaves all stored header,
  movement, reservation and audit evidence unchanged;
- a fault after actual movement writes verifies rollback of those writes;
- exact accepted replay has no second effect;
- exact rejected/same-reason replay has no second effect.

The historical body parity gate freezes the two authorized batch error-path
functions at 5d36daf3f096937e8af045fc62452c63408e6419. All other endpoint/helper
parity remains against the prior immutable baseline. New functional tests cover
the new contract rather than weakening those old gates.

## Ownership

Only batch transport/error metadata, its narrow shared-loader error option,
schema error evidence, two Custody dispatch files, focused tests and workflows
change. No Sentry/observability, LocalDatabase, Store semantics, owner identity,
projection, SyncRepository, Visit, Shop, Work Session, Auth, Dashboard, UI/UX or
closure-plan changes. No merge.
