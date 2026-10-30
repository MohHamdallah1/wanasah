# Live Stock operational browser closure
Base: `a07dfa6e06acbd9c0c8a1dfe6974f6eb53fb9f84`. Evidence is pending the dedicated production Dashboard / actual FastAPI / disposable PostgreSQL 16 run. No checklist completion is claimed before that run succeeds.

This wave unblocks the frozen V1 warehouse Live Stock read workflow. It reuses #660 PostgreSQL/session/auth foundations and #665's visual matrix. It does not change backend production code or the lead-owned closure plan, and excludes #668's accounting/date/snapshot proof.

## Corrections
- Bound the mobile top dock to its viewport, preserve native horizontal scrolling and locale-aware roving keyboard navigation, scroll the selected tab into view, keep focus inside the rail and suppress proximity expansion while overflowing.
- Add a translated refresh action inside the still-open batch dialog using the existing invalidation and list-then-detail freshness flow.
- Propagate source/batch authorization denial to the parent: cancel requests, invalidate warm evidence and remove rows, summary, batch, source and costs.
- Retry summary independently of the verified list. Clear its freshness marker while reloading, and deny all evidence on summary authorization failure.

## Independent fixture truth
Two canonical receipts: 100 cartons × 8 at 16 JOD/carton, then 25 × 8 at 24 JOD/carton. Before browser reads: 1,000 base units, value 2,200 JOD, average 2.2 JOD/base or 17.600 JOD/carton; last purchase 24.000 JOD/carton. Initial reservation 16, blocked 8, available 976; after the production reservation command adds 8: reserved 24, available 968, unchanged physical quantity/value. Two lots remain 800 and 200 units. Policy variants each receive 10 units, minimum10; only ACTIVE has low-stock eligibility, so summary is109 items/1 alert.105 paging variants,55 families,211 warehouses, one persisted inventory.read-only warehouse grant. Master/catalog/auth fixture records are permitted; every stock change uses production commands, never inventory/cost/ledger inserts.

## Exact checkbox matrix
The identifiers below quote the existing lead-owned plan. PASS requires the linked CI evidence; until then these are OPEN.

| Existing clause | Genuine new evidence | State / reason |
|---|---|---|
| Phase2: fields and quantity semantics; minimum-stock warnings | Independent receipt/UOM/cost truth plus desktop/mobile policy assertions | OPEN pending real run |
| Phase2: old responses, cancellations and independent summary/list failure | Existing affected freshness regressions; real FastAPI422 summary and second-page retries | OPEN pending run; validation failure only, no claim of503 outage |
| Phase2: list/detail/source authority and snapshot visibility | Still-open dialog invalidation, canonical reservation, refreshed batch/source | OPEN pending run; separate reads, no cross-request atomic snapshot claim |
| Phase2: no frontend business calculations | Display server low-stock flags across ACTIVE/RETIRING/SALES_HOLD/RECALL | OPEN pending run |
| Phase3: actual frontend corrections with regression proof | Mobile width/focus, modal refresh, denial propagation and summary retry | OPEN pending run |
| Phase4: owner-visible mobile top-tab clipping | Five real-server responsive/locale/theme screenshots plus keyboard bounds | OPEN pending run; owner approval remains required |
| Additional UI: real low-stock status across four policies desktop/mobile and summary | Canonical policy operations, independent109/1 truth and UI indicators | OPEN pending run |
| Additional UI: inventory.read one warehouse without location.read among>200 |211 warehouses, one discovery option, no setup read, same/foreign denial | OPEN pending run |
| Additional UI: refresh while batch dialog STILL OPEN; source/batch recovery | Two lots, real reservation/status, source422/retry, modal refresh | OPEN pending run |
| Additional UI: family selection identity and infinite continuation across filter/scope changes |105 unique real cursor IDs, family051 keyboard selection, warehouse reset, real revocation | OPEN pending run; external deep-link name resolution is not covered |
| Section5.B browser scope denial and stale disclosure | Same-token persisted grant revocation while source/dialog/costs are visible;403 purges evidence | OPEN pending run; hidden-vehicle/backend cases remain with their owners |
| Phase5: integrated authenticated browser acceptance and required CI | Production build, actual authentication, actual FastAPI, PG16 FORCE RLS runtime role | OPEN pending run; broader accounting, all release gates and owner sign-off remain OPEN |
| Additional UI: currency/UOM/dates/RTL/LTR and focus | Exact compact JOD/carton display, company date distinct from browser date, five visual states | OPEN pending run; no real midnight transition claim |
| Additional UI: exit/re-entry request budget | Real SPA navigation on Batches tab produces zero Live Stock reads; Live resumes one list/summary | OPEN pending run |
| Phase4/5: owner functional/visual approval, merge and complete release closure | Artifacts supplied for review | OPEN owner/lead only |
| Section5.B: company-day midnight, financial reconciliation, cross-request consistency | Not modified, delegated acceptance in#668 | OPEN separate backend ownership |
| R4 performance | No50k rerun or tuning in this wave | OPEN/accepted status remains lead-owned |

## CI and artifacts
Pending. The dedicated workflow archives screenshots, request budgets and cursor IDs, plus actual FastAPI logs. Credentials and bearer tokens are not archived. HTTP failure injection forwards a deliberately invalid query to actual FastAPI; it never fulfills or stubs inventory HTTP responses. This proves real validation-error recovery, not database-outage or5xx handling.

Historical CP13/#665 ownership guards now compare against the actual PR base and preserve an explicit bounded allowlist for this authorized wave. Their product assertions are unchanged. Automatic affected regressions are not presented as new operational acceptance.
