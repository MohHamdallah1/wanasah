# Product Import SourceStore

## Contract

Product Import application code depends on the `SourceStore` port in
`application/source_store.py`. A job owns an immutable `source_id`, byte
size and SHA-256 snapshot. Queue/application code must not assume where source
bytes are physically stored.

Every source must provide these properties:

- immutable source bytes for the lifetime of the retained source;
- exact byte size and SHA-256 metadata;
- tenant isolation;
- streaming/bounded persistence;
- streaming integrity verification before parsing/retry;
- idempotent deletion of bytes while preserving source metadata for audit.

## Current production adapter

At the current V1 upload ceiling of **8 MiB**, the production adapter is
`PostgresProductImportSourceStore`.

It stores immutable source metadata in `product_import_sources` and source
bytes in fixed **256 KiB** rows in `product_import_source_chunks`. Source
metadata and chunks are tenant-RLS protected. Database triggers reject source
metadata/chunk mutation. Upload hashing and size accounting are performed while
streaming to a disk-backed spool; the HTTP request never materializes the whole
source merely to calculate size or SHA-256.

This adapter is intentionally chosen for the present 8 MiB boundary because it
keeps source persistence, durable capacity reservation, job creation and queue
defer in one PostgreSQL transaction. It is not a requirement of the
application layer.

## Admission and capacity

Defaults are production-safe starting values and are environment-configurable:

- `PRODUCT_IMPORT_USER_WINDOW_SECONDS=60`
- `PRODUCT_IMPORT_MAX_UPLOADS_PER_USER_WINDOW=10`
- `PRODUCT_IMPORT_MAX_UPLOADS_PER_TENANT_WINDOW=50`
- `PRODUCT_IMPORT_MAX_ACTIVE_JOBS_PER_TENANT=25`
- `PRODUCT_IMPORT_MAX_LIVE_SOURCE_BYTES_PER_TENANT=134217728` (128 MiB)
- `PRODUCT_IMPORT_GLOBAL_LIVE_SOURCE_BYTES=2147483648` (2 GiB)
- `PRODUCT_IMPORT_ADMISSION_RETRY_AFTER_SECONDS=30`
- `PRODUCT_IMPORT_STORAGE_ALERT_PERCENT=80`
- `PRODUCT_IMPORT_OLDEST_SOURCE_ALERT_SECONDS=300`

Admission is checked before source persistence. Tenant admissions are serialized
with a tenant advisory transaction lock. Live-byte reservations are stored in
durable tenant/global counters and rechecked atomically before commit, so
concurrent uploads cannot race past byte ceilings. Rejections are persisted for
capacity telemetry and returned with stable error codes plus HTTP
`Retry-After`.

The platform's general HTTP/IP rate limiter remains defense-in-depth. It is not
the Product Import tenant/user admission authority.

## Integrity

The SourceStore re-reads stored chunks in order and computes SHA-256 and exact
size before any bytes are handed to the parser. A changed, missing, reordered
or truncated source fails closed as a deterministic job-level source-integrity
error. Queue retry therefore repeats integrity verification before parsing.

## Cleanup and retention

Successful staging deletes source bytes immediately through the SourceStore and
records `source_payload_cleared_at` on the job. Phase 10 retention remains the
hard safety net: terminal jobs with retained source bytes are cleaned after the
7-day upload-byte window in bounded batches. Source metadata/hash remain for
audit while bytes/chunks are removed and durable capacity counters are
decremented atomically.

## Metrics and alerts

Periodic capacity tasks expose/log:

- live/queued source bytes;
- historical source-byte high-water marks;
- oldest retained source age;
- admission rejections in the last hour;
- active Product Import jobs.

Warnings are emitted when tenant/global live bytes cross the configured
high-water percentage, retained sources exceed the age threshold, or quota
rejections occur.

## Scaling beyond the current boundary

If the source ceiling or ingestion volume grows materially, replace only the
SourceStore adapter with durable object storage (for example an S3-compatible
service) using immutable object keys/checksums, server-side encryption,
tenant-scoped authorization and lifecycle deletion. Keep `source_id`,
size/hash verification, admission, retention and application contracts
unchanged.

Database-backed source capacity tests include PostgreSQL WAL amplification.
That measurement must remain part of release capacity testing for as long as
source bytes are stored in PostgreSQL.
