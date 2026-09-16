# Wanasah project instructions

Read `.rules` and `.cursor/rules/business-workflow-protection.mdc` before making
changes. The workflow-protection rule applies to the entire repository and all
future tasks. No business workflow change is authorized without explicit prior
discussion and approval from the project owner.


## Mandatory internationalization and durable-command rules

Internationalization is a permanent project requirement. For every new frontend file and every frontend file modified from now on:
- use translation keys for user-facing text; do not introduce hardcoded UI copy;
- keep RTL/LTR locale-driven, never hardcoded;
- format numbers, money, dates, and times with locale-aware APIs;
- keep backend/API/UOM/status identifiers language-neutral and translate labels only at presentation boundaries;
- rely on backend error `code` + structured `context`, never localized message text, for program logic;
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
