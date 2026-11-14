# C03-FINAL — real signed custody recovery, Issue #977

This folder holds **eight authentic Chromium/Edge before-and-after screenshots** from the **production-built React Dashboard connected to actual FastAPI and disposable PostgreSQL 16.15**. The live browser exercised the integration branch containing exact C03 #975 and U02/U03 #973 parents. No HTTP interception, fake availability, client-inserted custody, or screenshots of signed tokens.

| Locale | Desktop 1440px | Mobile 390px |
|---|---|---|
| Arabic | [Before](ar-1440-before.png) / [After](ar-1440-after.png) | [Before](ar-390-before.png) / [After](ar-390-after.png) |
| English | [Before](en-1440-before.png) / [After](en-1440-after.png) | [Before](en-390-before.png) / [After](en-390-after.png) |

**Before:** an actual vehicle with physical stock and a `NEEDS_REVIEW` custody epoch remains a **disabled** option; an authorized manager can choose the separate `c03-review-blocked-car-ID` control without ever selecting the vehicle for route launch. Restricted FIELD, wrong manager and stale/tampered offer paths fail closed.

**Action:** manager opens the real stock/batch review, chooses a genuine company FIELD recipient (which need not be *available for a new launch*), sends the signed short-lived handoff; independently logged-in FIELD representative confirms the same stock snapshot through a real restricted Bearer HTTP request; manager submits the receiver proof and gets `201 ACCEPTED`. **No implicit inventory movement.** Full Flutter FIELD UI physical-count/no-offline acceptance remains proved by standalone C03 widget tests.

**After:** the browser verifies an additional **signed Backend availability GET returns AVAILABLE** and the same Dispatch workspace DOM node remains mounted throughout manager acceptance, **without reloading** the route. The previously disabled vehicle option becomes enabled only after this signed read. Subsequent fresh page reads in all four viewport/locale combinations show it selectable, while unrelated operational blockers remain in force.

**Audit:** PostgreSQL `InventoryMovement` rows for the signed receiving company remained **6 before and 6 after**. The vehicle's last epoch changed from `NEEDS_REVIEW` to genuine `ACCEPTED` revision 2, holder type `FIELD_REPRESENTATIVE`. All four before and four after screenshots were generated on a disposable synthetic tenant; no credentials, signed offer or receiver proof appear in the screenshots or source-controlled fixture.

**Local reproduction:** initialize a fresh restricted, migrated `m03_941_*` database with `FORCE RLS`, run `tests/test_dispatch_c03_final_browser_seed_postgres.py` with `RUN_C03_FINAL_BROWSER_PG16=1` and the M03 gate; start FastAPI on 4184 and production Vite preview on 4183; set `WANASAH_C03_FINAL_BROWSER_STATE` to the **private, untracked** JSON created by the seed, `C03_DISPOSABLE=1`, `C03_EVIDENCE_DIR` to a private output path, then execute `dashboard/e2e/dispatch-c03-final-real-browser.cjs` with Playwright 1.55 and Edge/Chromium. Never commit the generated JSON or a real credential.

**Scope limit:** some old outer Dispatch tabs remain Arabic even in English mode; the new C03 action, stock/recipient flow, and launch controls are localized. This is a pre-existing broader Dispatch localization gap, not a claimed C03 fix. LEAD/owner must explicitly review final UI and authorize merge. No automatic merging or weakening D15 tests.
