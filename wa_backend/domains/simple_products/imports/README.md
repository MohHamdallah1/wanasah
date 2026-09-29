# Product Import V1

Product Import is the V1 bulk-ingestion capability owned by
`domains/simple_products/imports/`.

## Boundary

- `api/` is transport only: authentication/permission entry, request parsing,
  application calls and explicit response DTOs.
- `application/` owns use cases, lifecycle orchestration, validation/execution
  sequencing, correction/cancellation and source lifecycle.
- `domain/` owns stable import rules, state/error contracts, normalization and
  mapping semantics.
- `infrastructure/` owns PostgreSQL persistence, SourceStore, parsers, queue,
  realtime relay and operational monitoring.
- Product Import does not own Product, Pricing, UOM, barcode, Tracking or
  Inventory business truth. It calls the existing authorities.

## Catalog identity

See the [canonical catalog identity dictionary](../../../../docs/architecture/CATALOG_IDENTITY_GLOSSARY.md). Each successfully imported row records the sellable `ProductVariant.id` for source-row lineage; master `Product.id` is distinct. The legacy import workflow omits the Quick Create-only `family_mode` field and keeps name-based parent resolution.

## Final execution contract

The job identity is durable and tenant-scoped. Source data is immutable and
SourceStore-backed. Parsing/staging is transactional and bounded. Validation is
best-effort across rows. Execution is atomic per committed unit and idempotent
across retries/duplicate queue delivery. Imported rows are terminal and never
replayed by correction/retry.

Every worker step re-establishes tenant context and execution revalidates the
active actor and required permissions before Product/Pricing writes. Cancellation
and retry operate on the same durable job rather than creating parallel truth.

## Scale/security contract

- CSV and XLSX parsing/staging use bounded working-memory gates at 50,000 rows.
- Barcode validation is database-backed/set-based; giant parameterized candidate
  lists are forbidden.
- Tenant-prefixed staging indexes and FORCE RLS remain required.
- Public API errors use stable user-safe codes; SQL/constraint/trace details are
  server-log-only with correlation IDs.
- Correction CSV/XLSX output is formula-injection sanitized.
- Client MIME is not trusted; actual content/signature and XLSX archive safety
  are validated.

## Operations

Use `scripts/run_product_import_worker.ps1`; see `RUNBOOK.md` for health,
recovery and release gates.
