# Audit A — bounded UTF-8 staging spool acceptance (2026-09-30)

**Accepted code:** Codex branch commit `1dbc1a9`, reviewer cherry-picked as
`16de908` onto `hardening/v1-import-concurrency-diagnostics-20260930`.
**Status:** Audit A application-level implementation and isolated acceptance PASS;
a production-like full 50k-row XLSX/DB load, long-lived concurrent staging
capacity and production ingestion timing are still D7-S/D8 requirements.

## Why the change was needed

Previously `source_service.prepare_import_source` consumed and inserted
the source's parsed rows while holding the single staging transaction open.
The reviewed implementation now finishes CSV/XLSX parsing and puts source
row numbers + raw values + cell metadata in an ephemeral UTF-8 JSONL spool
**before** opening the tenant SQL transaction. `staging_service` inserts
bounded 500-row statements **within one atomic transaction** and verifies
the parsed/spooled/committed row totals before any source cleanup. No
partial staging state can be made executable on write failure.
`NEEDS_MAPPING` replay now completes idempotent source cleanup without
restaging, while the source still remains the durable authority before
the staging commit. RLS, request IDs, duplicate barcodes, PriceBook,
audit, outbox, stock and row identity contracts were unchanged.

Codex correctly isolated an additional spool-size cause: default
`json.dumps` escaped Arabic BMP characters as `\uXXXX` (six
ASCII bytes per character), even though the spool is a private file
round-tripped by Python. Using `ensure_ascii=False` writes them in
two UTF-8 bytes each, with control-character and lone-surrogate escape
semantics still valid.

## Independent consolidated reviewer results

- **50,000 synthetic Arabic rows, 25 fields** with physical row numbering
  and nested cell metadata: old spool **157.26 MiB**, updated spool
  **70.47 MiB** (approximately **55.2% smaller**); new run **2.32 s**
  on the approved Windows reviewer machine. That is a local buffering
  benchmark, not an end-to-end XLSX+DB processing time.
- Files are closed on success, row 50,001 fails closed, the byte-based
  size limit and explicit 2 GiB / 2-slot / 4-slot budget calculations
  PASS. Simulated write OSError, cancellation, Unicode surrogate
  roundtrip and retryable `PRODUCT_IMPORT_STAGING_STORAGE_UNAVAILABLE`
  classification PASS. Source data/metadata remain unchanged.
- Existing targeted backend regression: **148 tests PASS**, no failures
  or skipped tests.
- Real **private PostgreSQL 16 D4**: orphan once-only recovery,
  cancellation, worker hard-kill and replay; final **2970 imported /
  30 invalid**, exactly **2970 price variants / audits / outbox**,
  no duplicated effects, PASS. Old developer source untouched.
- Real **private PostgreSQL 16 D1**: parallel actual Sale/COGS,
  Supplier Inbound and Route Launch during a 3000-row import;
  2970 imported, 30 invalid, zero negative stock, exact pricing
  and audit/outbox counts PASS. The disposable PostgreSQL cluster
  was removed; no source DB migration/worker change occurred.

## Boundaries and remaining deployment evidence

The spool uses `tempfile.gettempdir()` and divides free space above a
parser reserve by the configured execution slots, with a minimum of
two. Every 64 KiB write verifies free space then flushes. With 2 GiB
free, two slots reserve 256 MiB and allot 896 MiB per spool; four
slots reserve 512 MiB and allot 384 MiB per spool. This is **not an
OS-enforced disk reservation or multi-host coordination**. A separate
process/container/service can consume space after a check: the OS
write failure path is retryable and leaves the immutable SourceStore
intact. Deployment must configure and monitor actual temp-volume
space, quotas, worker process count and parallel file readers.

The acceptance above **did not** execute a full 50k-row XLSX against
real SQL in staging, or measure true network/driver/commit lock waits
under production-sized index/history churn. Those remain part of D7-S,
B/I, and D8 and must not be claimed as complete from the spool test.
