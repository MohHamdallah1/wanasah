# Live Stock operational browser closure
Original base: `a07dfa6e06acbd9c0c8a1dfe6974f6eb53fb9f84`; accepted integration main: `ae858c10f04832aaf99df55db15507571986b53e` (includes #678). The executed gate and final PASS/OPEN verdicts are recorded in PR#673. No checklist completion is inferred from this static proof design.

This wave unblocks the frozen V1 warehouse Live Stock read workflow. It reuses #660 PostgreSQL/session/auth foundations and #665's visual matrix. It does not change backend production code or the lead-owned closure plan, and excludes #668's accounting/date/snapshot proof.

## Corrections
- Preserve keyboard tab focus even when a newly activated panel autofocuses an editor; pointer behavior is preserved.
- Bound the mobile top dock to its viewport, preserve native horizontal scrolling and locale-aware roving keyboard navigation, scroll the selected tab into view, keep focus inside the rail and suppress proximity expansion while overflowing.
- Add a translated refresh action inside the still-open batch dialog using the existing invalidation and list-then-detail freshness flow.
- Propagate source/batch authorization denial to the parent: cancel requests, invalidate warm evidence and remove rows, summary, batch, source and costs.
- Retry summary independently of the verified list. Clear its freshness marker while reloading, and deny all evidence on summary authorization failure.

## Independent fixture truth
Two canonical receipts: 100 cartons × 8 at 16 JOD/carton, then 25 × 8 at 24 JOD/carton. Before browser reads: 1,000 base units, value 2,200 JOD, average 2.2 JOD/base or 17.600 JOD/carton; last purchase 24.000 JOD/carton. Initial reservation 16, blocked 8, available 976; after the production reservation command adds 8: reserved 24, available 968, unchanged physical quantity/value. Two lots remain 800 and 200 units. Policy variants each receive 10 units, minimum10; only ACTIVE has low-stock eligibility, so summary is109 items/1 alert.105 paging variants,55 families,211 warehouses, one persisted inventory.read-only warehouse grant. Master/catalog/auth fixture records are permitted; every stock change uses production commands, never inventory/cost/ledger inserts.

## Exact clause verdicts
The final checkbox → genuine evidence → PASS/OPEN → reason matrix, implementation SHA, CI run and screenshot artifact links are maintained in [PR#673](https://github.com/MohHamdallah1/wanasah/pull/673). This file records the proof design and independent inputs; it does not substitute a static assertion for an executed gate.

## Known exclusions and inherited failures
- #668/#670 merged independently after the approved base. Their backend files and the closure plan are not modified here.
- R3/R4, actual company-midnight transition, comprehensive concurrent browser snapshots, external initial family-ID name resolution, 5xx/outage recovery and owner visual/release approval are not closed by this wave.
- The focused fixture uses FIFO once per disposable run. This frontend wave does not re-run the accepted moving-average financial journeys or the 50k benchmark.
- The inherited CP12 failures were corrected independently in merged #678. Integration preserves its AR/EN resources, family-cursor guard/recovery, responsive structure assertions, native inbound column-header semantics and current-contract narrow-browser fixtures. The integrated CP12/CP13 result is recorded in the PR; prior failures are not waived.
- Ownership checks retain explicit allowlists and whitespace validation. GitHub's compare API supplies the PR common base; runner Git returned1 for merge-base despite the API proving the approved common ancestor. No scope is inferred from a stale historical fixed base.

## CI and artifacts
The dedicated workflow archives screenshots, request budgets and cursor IDs, plus actual FastAPI logs. Credentials and bearer tokens are not archived. HTTP failure injection forwards a deliberately invalid query to actual FastAPI; it never fulfills or stubs inventory HTTP responses. This proves real validation-error recovery, not database-outage or5xx handling.

Historical CP13/#665 ownership guards now compare against the PR common base and preserve an explicit bounded allowlist for this authorized wave. Their product assertions are unchanged. Automatic affected regressions are not presented as new operational acceptance.
