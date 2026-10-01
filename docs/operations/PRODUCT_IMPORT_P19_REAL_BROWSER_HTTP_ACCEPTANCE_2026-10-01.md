# Phase 19 — original ProductsPage in real Edge against real isolated FastAPI / PostgreSQL / Worker

**Date:** 2026-10-01. **Purpose:** close the missing *browser-to-live-backend* link in the previously separate real HTTP gates and Edge synthetic-HTTP UI gates. This is not a customer deployment, manual owner signoff, or release of the entire Products V1.

## Source-first scope and safety

- Reused the existing `wa_backend/scripts/run_product_import_phase19_http_isolated_gate.py` PostgreSQL16 disposable bootstrap instead of cloning a fixture runner. Added only opt-in `realbrowser` dispatch; the original modes and production API/Worker implementations are unchanged.
- Preflight requires both the parent disposable marker and `WANASAH_P19_REAL_BROWSER_CONFIRM=DISPOSABLE_PG16_ONLY`; the source and migration URLs are checked against **127.0.0.1:55446/p19_http_synthetic**. The parent binds an actual FastAPI at **18046**, three existing Worker roles and a temporary PostgreSQL16 cluster. The developer source tenant is consulted solely through the existing read-only, preapproved empty-fixture procedure.
- Test-only Vite on **127.0.0.1:5188** serves the original `ProductsPage` with the original hooks, `useAuthFetch`, modals, translations, TanStack Query, focus manager and Radix menu. Only `/acceptance-real` is proxied to the owned FastAPI. This entry is not part of the production build. A unique Edge headless user profile and localhost CDP endpoint **19226** are created and removed by the test.
- The signed company-2/actor-1 JWT is injected into the temporary browser's localStorage by CDP, **not in a URL, HTML, checked-in fixture, output or log**. The originally scoped job is put into sessionStorage using the production `productImportSessionKey` contract. No customer's Excel, development job, permanent staging database, or 5,000/10,000/50,000-row suite was used.

## Executed integrated acceptance — PASS

The runner created an isolated **six-row synthetic CSV** with five valid rows and one deliberately blank name, submitted it to the actual authenticated import HTTP endpoint, and waited for its real Worker to reach `COMPLETED_WITH_ERRORS`. PostgreSQL readback confirmed five imported Variants, one INVALID, and matching initial Product/Price/Audit/Outbox evidence.

Then Edge **actually loaded the original ProductsPage**, opened its real Radix Import action with keyboard ArrowDown/Enter, and resumed that exact job through `useImportSessionResume` and actual HTTP status/correction-row endpoints. The browser displayed the single rejected row, its required-name reason and field `aria-describedby`; focus stayed within the dialog. A browser DOM input event set the corrected name, and the original React inline-correction Save button issued the **only correction submission**. Actual Worker follow-through persisted **six imported distinct Variants, six distinct priced Variants, six audit events and six outbox events** on the **same job UUID**, with **zero** remaining INVALID rows. Existing DB evidence helper also checks against duplicate Price/Audit/Outbox effects.

Afterward Edge applied **Arabic RTL**, then switched via the test-only localized language control to **English LTR**; the original ProductsPage and dialog were rendered at a 390×844 mobile viewport, and the document had no horizontal overflow. This is a Chromium Edge rendering/keyboard/viewport check, **not** an iOS/Android physical touch test or a screen-reader audit.

The exact runner markers were:

```text
REAL_BROWSER_SCRIPT_AST=PASS
BROWSER_SOURCE_LINT=PASS
ISOLATED_PG_PORT_FREE=PASS
P19_REAL_HTTP_EXECUTION_READINESS=PASS
P19_REAL_BROWSER_RESULT={"browser":{"real_browser":"Edge headless CDP","rtl_ar":true,"ltr_en":true,"mobile_viewport":390,"keyboard_open":true,"focus_trapped":true,"rejected_row_visible":1,"accessible_field_reason":true,"same_job_ui_correction":true},"imported_before":5,"imported_after":6,"job_unchanged":true,"prices":6,"audit":6,"outbox":6}
PRODUCT_IMPORT_P19_REAL_BROWSER_BACKEND=PASS
ORIGINAL_DEV_TENANT_UNMODIFIED=PASS
P19_HTTP_SOURCE_DEVELOPER_UNMODIFIED=PASS
P19_HTTP_DISPOSABLE_CLUSTER_REMOVED=PASS
REAL_BROWSER_GATE_EXIT=0
```

**69.27 seconds** is the full test harness wall time (including PostgreSQL bootstrap, API/Worker startup and teardown), *not* the six-row import completion time and not an SLA percentile. The targeted source preparation passed Python AST, TypeScript and ESLint; final test-entry follow-up changes were only localization of the opt-in test control and a second fail-closed Vite opt-in check and have their own subsequent focused source gate.

## What remains OPEN

- Genuine mobile touch, NVDA/VoiceOver manual screen reader use and **owner visual acceptance**.
- Actual multi-user/tenant switching with the production account shell, suspended HTTP/WebSocket reconnection in the browser, and the UI's **large**-job progress and paginated error state. The existing Edge synthetic fixtures and real HTTP security gates cover other pieces separately but cannot be relabeled as a single integrated proof.
- p50/p95, valid process CPU/RSS, exact phase timings, and the historic September `ClientRead` physical cause.
- No 50k rerun is justified. Do not mark the composite release checkboxes fully closed solely on this focused six-row browser gate.

## Re-run only for relevant changes

After ensuring no other owned disposable test uses ports 55446/18046/5188/19226 and from `wa_backend` on a separate checkout:

```powershell
$env:WANASAH_P19_HTTP_LOCAL_GATE='1'
$env:WANASAH_P19_HTTP_SOURCE_ENV_FILE='<approved read-only developer .env path>'
$env:WANASAH_P19_HTTP_CASE='realbrowser'
$env:WANASAH_P19_REAL_BROWSER_CONFIRM='DISPOSABLE_PG16_ONLY'
python -m scripts.run_product_import_phase19_http_isolated_gate
```

Run only using the existing parent guard, and never against the normal developer/source DB. The parent verifies unchanged approved source fixture and removes its disposable PostgreSQL16 cluster.
