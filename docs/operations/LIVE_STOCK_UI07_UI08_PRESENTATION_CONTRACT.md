# Live Stock UI-07 / UI-08 — V1 presentation contract (30 October 2026)

**Scope:** Display meaning only, based on accepted main `9b485e15d0ae8e28674ab8bedca6afd136cf927a`. Does not authorize a server count, inventory projection, financial, permission or movement change.

## Verified backend meaning

1. `GET /warehouse/inventory/summary?location_id=...` returns `stock_total` as a **count of distinct product variants in the summary scope**, not an on-hand quantity, physical pieces, packets, cartons or the filtered cursor's size. The active component is `InventoryLiveStockCompanySummary.active_variant_count` (all ACTIVE variants in the company); the additional component is nonactive stock presence visible in this warehouse / permitted vehicle scope. Owner/company-wide and restricted readers follow the server's existing separate authorized logic. Its `alert_count` is the stock warning count for that summary, not the current filtered page count. These are independently fetched, server-authorized fields; they may be unknown until revalidated.
2. `GET /warehouse/inventory/cursor` intentionally returns `total=null` and `alert_count=null` in the current implementation. It loads a bounded variant page with `limit + 1` to determine `has_more` and `next_cursor` and does **not** compute a filtered `COUNT(*)`.
3. `stockItems.length` is the number of **distinct cursor rows already loaded in the browser** (including appended cursor pages); it does not claim that all filtered matches have been counted. A value of zero is meaningful only after a successful, verified empty page, not before the first request or after permission failures.
4. `lastSync` in `MainInventory.tsx` is assigned `new Date()` on a successful cursor-page response and persisted as `lastSyncMs` for the first default page. It is **time of the last successful client fetch**, including cursor continuation, not the timestamp of the last warehouse movement, the server's projection verification time or a globally consistent stock snapshot. The UI-04 stale/unverified banner remains the freshness/authority disclosure.

## V1 presentation decision

- Call `stock_total` **variants in stock summary** with a scope explanation; never imply physical stock quantity or matching search results.
- Call `lastSync` **last successful stock-list fetch** and show unknown when no current list page has been verified; never call it last stock movement.
- In the list, show **variants loaded from the list** when a page is available, even if more pages exist. When `has_more` and `total=null`, explicitly say more matches exist and the matching total is unknown; never substitute `stock_total` or `stockItems.length` for exact matching total. The compatibility field `matchingTotal`, if nonnull from a future server response, is separately labelled exact.
- Unknown/unverified/null is an em dash with accessible explanatory text, not **0**. A verified numeric zero stays **0**. Treat summary and page freshness independently and retain all UI-04 access guards.
- Clear bilingual Arabic/English wording and RTL/LTR presentation; preserve existing cursor search, filters, infinite scroll, deduplication and error disclosure.

## UI-07 classification

**The exact total matching the current search and filters is not a frozen V1 requirement. V1 = loaded-row count plus a truthful unknown-total disclosure. Exact filtered-search total is V2 / deferred** unless the product owner explicitly approves a scope change with bounded-query/performance and RLS/permission evidence. Do **not** add `COUNT(*)`, unbounded scans or a speculative extra request in V1. This decision applies only to presentation and leaves backend semantics unchanged.

## Acceptance evidence

The branch's dedicated `Live Stock UI-07 UI-08 count and freshness semantics` workflow must pass null, zero, stale, verified, filtered, unfiltered, partial loading, Arabic/English, accessible labels, prior UI-04/CP7/L-02 security and cursor regressions, TypeScript and production build. No PR may be merged on source review alone.
