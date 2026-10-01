# Phase 19.1 HTTP correction: source fixes and acceptance evidence

Date: 2026-10-01
Branch: `hardening/v1-import-phase19-http-correction-acceptance-codex`
Source review baseline: `8740f10`. Final upstream baseline: `e30ac54` (origin/main
advanced during review; fast-forward preserved these backend changes). Upstream
changes between these baselines affect only Dashboard and the master plan.
**Real PostgreSQL/HTTP/worker acceptance remains OPEN.**

## Confirmed source defects and fixes

1. `application/correction_service.py:parse_correction_payload` rebuilt source
   cells without the XLSX reader's numeric/formula metadata. This bypassed the
   existing normalizer's barcode safety checks for uploaded correction files.
   The adapter now preserves reader-produced metadata for source columns,
   remapping sanitized headers to their original names. Reserved correction
   metadata is excluded. The existing validator remains the only authority.
2. File correction lacked the inline path's retention checks. An old correction
   file could replace compacted raw data and requeue it. The shared repository
   now checks the existing 30-day detail policy while holding the job lock,
   locks target rows in physical row order, rejects compacted targets and
   unconditionally requires `compacted_at IS NULL` in the update predicate.
   Downloads reject expired jobs, omit compacted rows and reject downloads when
   all rejected-row details are compacted. No replacement retention policy.

GET and POST `/simple-products/imports/{job_id}/correction` now return
HTTP **410**, `error.code=PRODUCT_IMPORT_CORRECTION_DETAILS_EXPIRED`, for those
expiration cases through the existing safe error envelope. Read
`error.request_id` / `error.context.correlation_id` for support correlation.
The message is safe; stored exception diagnostics are not returned.

The XLSX/CSV headers, multipart `request_id` + `file`, inline JSON contract,
202 acknowledgement and all other error contracts remain unchanged. A completed
same-input request replay still returns its persisted acknowledgement before
mutable job/row/retention checks; expiration must not invalidate that replay.

## Source review: HTTP to durable execution

- Both correction transports require the existing manage permissions and load
  the job under the actor's company before processing correction input.
- The shared write authority sets tenant context, uses the existing company/
  request idempotency lock and actor/input hash, then locks the scoped job and
  target rows. Only INVALID / IMPORT_FAILED targets can become STAGED.
  IMPORTED rows are rejected; their products are not reimported.
- Inline correction already enforces `expected_job_version` and each
  `expected_version`. These optimistic checks were not added to the legacy
  file contract: that contract uses durable request identity and locked
  eligibility, not a file-carried draft version.
- Row UUIDs and original Excel row numbers remain unchanged. SourceStore
  content is unchanged. No Product/Pricing/Tracking or permission engine added.
- Row/job updates, queue deferral and idempotency completion remain on the
  same PostgreSQL transaction/connection. A rejection rolls back the whole save.
  Job locking still serializes correction, execution and cancellation.
  Target row locking protects correction against concurrent compaction.
- Queue dispatch invokes the existing worker, validation and execution services.
  Only STAGED/VALID rows enter those stages; the existing Product service owns
  Product/Variant/Price writes and downstream audit. Execution rechecks actor
  permissions. These are source findings, not live acceptance results.

## Focused verification actually executed

Six selected unittest methods passed; no full suite or historical gate rerun:

- `FileCorrectionSafetyTests`: four methods covering real XLSX parsing and
  existing normalization (numeric/formula barcode rejection, next error after
  name repair, leading zeros, sanitized-header metadata), shared retention
  enforcement, compacted-target lock/rejection, and early completed replay.
- `InlineCorrectionHttpTests.test_file_transport_preserves_expired_code_and_request_id`:
  GET/POST file transport 410, safe canonical error code and correlation id.
- `InlineCorrectionAuthorityTests.test_same_authority_transaction_patch_and_queue`:
  correction and queue remain on the same authority/transaction path.

Result: **6/6 PASS**. XLSX parsing/normalization used real code. HTTP used the
in-process client with overridden dependencies and the existing central error
handlers; persistence and queue boundaries were doubles. Live DB connection
entry points were blocked, dotenv loading disabled and bytecode writes disabled.
These results do not establish real authentication, RLS, PostgreSQL lock behavior
or committed Product/Variant/Price/Audit persistence.

## Real acceptance still OPEN

D7S has no backend .env, DATABASE_URL or DATABASE_URL_TEST, and no import worker
was identified. PostgreSQL/API processes exist, but their presence does not
establish an authorized isolated database or synthetic tenant. No safe target
configuration was supplied. No actual import, write load, worker launch/restart,
migration or database change was performed.

The following require the isolated development target and real worker:

- Synthetic mixed successful/rejected import, official XLSX correction and
  inline HTTP correction to the same job; terminal completion and committed
  Product/Variant/Price/Audit readback, with successful rows unchanged.
- Actual same-request replay, changed-input reuse rejection, concurrent saves,
  stale row/job versions, foreign-company access and FORCE RLS enforcement.
- Next validation error after first repair through the real worker.
- Real compaction/correction race, rollback on queue failure and cancellation
  interaction under PostgreSQL locks.

No Dashboard, master hardening plan, business service, schema or test harness
was changed. This report does not mark Phase 19.1 fully accepted.
