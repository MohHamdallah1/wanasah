# Phase 19 — real isolated import authorization, RLS, FK and audit inspection

**2026-10-01: production API source, real FastAPI HTTP, live PostgreSQL 16, all three Worker roles on a disposable Windows rehearsal cluster.**

Command: `WANASAH_P19_HTTP_LOCAL_GATE=1` with `run_product_import_phase19_http_isolated_gate.py`; `PRODUCT_IMPORT_PHASE19_REAL_HTTP_ISOLATED=PASS`.

The parent guard bootstraps only from the approved **empty** development synthetic tenant under read-only access. It launches an entirely disposable PostgreSQL database at `127.0.0.1:55446/p19_http_synthetic` and FastAPI at `127.0.0.1:18046`, with a second synthetic tenant created only inside the ephemeral cluster. No user's XLSX or old import jobs were used.

| Evidence | Result |
| --- | --- |
| Real signed bearer import authorization | PASS, HTTP worker readiness 200 |
| Persisted unprivileged driver with forged `is_admin` token claim | PASS, 403 |
| Foreign-tenant job GET, rejected-row GET, correction POST, correction CSV/XLSX GET | PASS, cross-tenant 404 |
| Forged identity and previously imported row correction | PASS, 409; original Product/Variant versions, price publication and active barcodes unchanged |
| Real inline, official CSV and XLSX corrections and exact idempotent replay | PASS; each 100/100 imported, with 100 price variants, 100 audit and outbox events |
| Lost HTTP response, then replay same request ID/body | PASS, final state reconciled |
| Actual ProductVariant audit **contents** | PASS: all 100 linked rows carry one tenant-2, actor-1 audit with a nonempty event/reason, UUID request, context/snapshot schema and matching tenant/aggregate/request outbox event |
| Wrong-company actor assigned as creator of company-2 import job | PASS, real `fk_product_import_job_tenant_creator` composite FK rejected; original creator unchanged |
| App-role row read with `app.current_tenant=3` | PASS, 0 foreign rows visible; `app.current_tenant=2` restores 100 own rows, demonstrating real FORCE RLS in the disposable DB |
| Disable persisted driver while its JWT is still cryptographically valid | PASS, immediate HTTP 403; independent company-3 token remained HTTP 200 |
| Restore driver then blacklist the original signed JWT | PASS, same bearer HTTP 401; foreign token remained HTTP 200 |
| Real StagingIOGuard PG lock release | PASS, existing short-deadline test |
| Developer source and temporary cluster | `ORIGINAL_DEV_TENANT_UNMODIFIED=PASS`, `P19_HTTP_SOURCE_DEVELOPER_UNMODIFIED=PASS`, `P19_HTTP_DISPOSABLE_CLUSTER_REMOVED=PASS`; run exited 0 |

These tests verify the **Product Import V1** authorization, cross-tenant ownership, critical composite FK, RLS, correction immutability, audit-content and replay boundaries, not every FK in the entire ERP. Distinct pending work includes some concurrency/fault injection, browser/real touch and performance-resource envelope, release owner signoff and first-customer deployment. Neither Product/Pricing business logic nor Worker state-machine authority nor production schema was changed.