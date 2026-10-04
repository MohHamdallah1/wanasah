# Batch-focus browser acceptance (Lane B)

This opt-in harness exercises the built Inventory destination in a real browser.
It reuses the typed navigation contract and read fixtures from the focused React
acceptance tests. Every API request is intercepted; unexpected reads and all
mutations fail. It does not use a database, real credentials, terminal disposal,
vendor handover, or whole-product workflow implementation.

Build the dashboard with `VITE_API_URL=http://127.0.0.1:4174/api`, start its Vite
preview at `http://127.0.0.1:4173`, then run the available Playwright CLI with
`test --config e2e/batch-focus.config.ts`. The harness uses `playwright/test`;
make that supplied runtime available through normal Node package resolution
(ESM imports do not use `NODE_PATH`). No dependency manifest or browser
installation is part of this harness. Override `BATCH_FOCUS_BASE_URL` and `BATCH_FOCUS_BROWSER_CHANNEL` for
another local preview or installed Chromium browser.

The browser matrix covers warehouse, multi-warehouse, warehouse + vehicle,
vehicle-only, and a server-redacted second source in Arabic and English. Every
case starts with an unrelated saved warehouse and verifies focus consumption,
keyboard entry, locale direction, unchanged preferences, and one batch read.
The focused React suite additionally exercises the real Products-warning click,
cache/revocation, mismatched identities, cancellation, per-source action gates,
and typed Dispatch navigation. Backend endpoint acceptance proves that the
redaction itself is authoritative; browser fixtures cannot prove PostgreSQL RLS.
