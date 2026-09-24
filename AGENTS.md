# Wanasah project instructions

Read `ARCHITECTURE.md`, `.rules`, and `.cursor/rules/business-workflow-protection.mdc` before making
changes. `ARCHITECTURE.md` is the canonical architecture constitution for the entire repository and all future modules.
The workflow-protection rule applies to the entire repository and all future tasks.
No business workflow change is authorized without explicit prior discussion and approval from the project owner.


## Mandatory internationalization and durable-command rules

Internationalization is a permanent project requirement. For every new frontend file and every frontend file modified from now on:
- use translation keys for user-facing text; do not introduce hardcoded UI copy;
- keep RTL/LTR locale-driven, never hardcoded;
- format numbers, money, dates, and times with locale-aware APIs;
- keep backend/API/UOM/status identifiers language-neutral and translate labels only at presentation boundaries;
- rely on backend error `code` + structured `context`, never localized message text, for program logic;
- require every API failure to expose a correlation/request id in the canonical error contract; dashboard transport must preserve code/context/safe reason/request id, show deterministic 4xx reasons instead of generic failures, and hide unexpected 5xx internals while surfacing the request id;
- localized CSV/XLSX headers must map to canonical language-neutral import fields.

Network failure is also a permanent architecture requirement. Every new or modified mutating workflow must:
- be server-idempotent (or provably state-idempotent);
- preserve one stable operation/request id across timeout, disconnect, and lost-response retries;
- reject reuse of the same id with different input;
- never silently queue administrative mutations in the browser for later execution;
- surface offline/unknown-result state and preserve user drafts where data loss would otherwise occur;
- make asynchronous workers tenant-safe, resumable, bounded, and authorization-aware;
- reconcile or safely replay after an ambiguous network result before creating a duplicate business operation.

Read the full requirements in `.rules` before editing.

## Stage 7.4 inventory costing authority
- Physical batch allocation and financial cost flow are separate authorities. Physical FEFO stays inside the backend and never requires the driver to choose a batch.
- Without per-carton serial/scan or enforced physical segregation, never claim the exact physical carton identity. Batch allocation is deterministic book allocation.
- Supplier receipts require actual purchase unit cost and purchase UOM. Preserve every receipt cost as immutable history; never overwrite an older cost.
- The company selects MOVING_AVERAGE or FIFO before its first costed supplier receipt; the method locks on that first receipt.
- Financial FIFO consumes acquisition cost layers by product/company acquisition order and must never be coupled to the physical FEFO batch selected for a sale.
- Internal warehouse/vehicle transfers move physical stock only and never create COGS or change company inventory value.
- Sale, sample, reward, exchange, and other external stock exits remain invisible to the driver at batch level but must create financial cost evidence when costing is active. Samples use VISIT_SAMPLE_OUT, not VISIT_ITEM_OUT.
