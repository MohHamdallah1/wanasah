# Wanasah V1 Product Import — Release Runbook (2026-09-30)

**Status: V1 development/import acceptance locally evidenced; first-company DEPLOYMENT sign-off OPEN until a real deployment target is selected.** This file is the operational launch checklist, not proof that a customer/server was updated. The owner launches V1 for one company. The former 1,000-concurrent-connection/multi-company scale target was moved to `VERSION_2_FUTURE_FEATURES.md` §8 (historical audit: `docs/archive/V1_MULTITENANT_ASYNC_AND_IMPORT_RELEASE_PLAN_2026-09-30.md`). It is not a condition for this first-company pilot. Never defer V1 financial, stock, RLS or durability safety to V2.

## Existing proofs — do not rerun without a relevant change

D1: real Sales, Supplier Inbound, Route Launch during Import. D2: deliberate Company/Pricing/Live Stock lock contention. D3: separated execution/control/maintenance workers and durable event-driven scheduling with 2 bounded import slots. D4: orphan recovery, parsing cancellation and worker-kill replay. D5: WebSocket JWT no longer in URL; Uvicorn access-log canaries. D6: measured equivalent bounded predecessor pricing query. D7-L: local 1,000-request mixed ASGI workload, not 1,000 active HTTP connections.

D8's NEW synthetic backup/restore toolchain passes an atomic PostgreSQL custom archive test, a FULL three-row restore in a new disposable PostgreSQL 16 database, a rejection of malformed archives and of invalid retention settings, and cleanup of the test database. It did not read or overwrite the development data. The local read-only preflight reported matching Alembic HEAD, FORCE RLS on required import tables, and a connection budget of 46 within 60 against max_connections=100. The local Product Import worker roles were not connected, and six nonterminal synthetic test imports still existed.

## Backup migration and restore instructions

The revised scripts/backup_db.sh creates a PostgreSQL custom-format .dump file without double-gzipping, writes to a temporary file with restricted permissions, validates the archive directory and publishes atomically before retention. It prunes only its own new .dump outputs AFTER successful backup, leaving every legacy .sql.gz artifact untouched. A readable archive is not proof of full restoration.

On a Linux deployment host, configure POSTGRES_DB, POSTGRES_USER, POSTGRES_HOST, POSTGRES_PORT, BACKUP_DIR and RETENTION_DAYS from approved secrets/deployment settings; use secure libpq credentials and encrypted offsite storage. Run wa_backend/scripts/backup_db.sh. Then, on a dedicated disposable local restore host, run wa_backend/scripts/verify_restore_backup.sh with the absolute .dump path and RESTORE_HOST=127.0.0.1, RESTORE_PORT, RESTORE_USER. That script creates a NEW randomly named disposable database and destroys it after successful or failed verification. It refuses non-loopback restore hosts. Do NOT point it at existing development or production databases. Verify FULL production-sized anonymized backups separately; the tiny synthetic gate is only a test of the backup/restore code path.

To rerun the backup toolchain gate ONLY after changing these scripts: from wa_backend, set WANASAH_D8_DISPOSABLE_GATE=1 and run python -m scripts.gate_product_import_d8_backup_restore_disposable. This gate starts and tears down its own loopback PostgreSQL cluster on port 55447.

## Historical external load-generator safety baseline — optional V2 scale gate, not first-company V1 requirement

The old `wa_backend/locustfile.py` had hardcoded example login credentials
and issued unconstrained stock-transfer POSTs. It has been replaced by a
**read-only, fail-closed** staging driver: catalogue GET, optional same-company
import-status GET, and optional other-company status GET expecting 404.
It never logs JWTs/response bodies or creates inventory movements.

Install Locust **on the separate approved load-generator host**, not into
the developer API runtime. Configure these variables with synthetic staging
secrets: `WANASAH_LOAD_TEST_ACK=I_ACK_ISOLATED_SYNTHETIC_STAGING`,
`WANASAH_LOAD_STAGING_URL=https://<approved-stage-host>`,
`WANASAH_LOAD_APPROVED_URL` to the **same exact URL**,
`WANASAH_LOAD_TOKEN_COMPANY_A`, optional
`WANASAH_LOAD_TOKEN_COMPANY_B`, and optional
`WANASAH_LOAD_JOB_COMPANY_A/B` (the latter two must be **synthetic
existing job UUIDs**, one for each different company). The guard refuses
host mismatch, missing acknowledgement/tokens, URLs with credentials or
non-loopback HTTP, and can be verified without Locust/DB using
`python -m unittest tests.test_staging_load_guard`.

For a read-only *user-emulation* baseline from that separate host:

```bash
cd wa_backend
locust -f locustfile.py --headless --host "$WANASAH_LOAD_STAGING_URL" \
  --users 1000 --spawn-rate 50 --run-time 2m --csv staging-readonly-load
```

**Important:** 1000 Locust users are not proof of 1000 active TCP/HTTP
connections at the same instant. Record actual ingress open-connections
and in-flight queries separately. The API's current default global limit
is **1000 requests/minute per source IP**; this load may legitimately
produce 429s. Capture those separately rather than weakening production
rate protection or misreporting them as unexplained 5xx. The read-only
driver is NOT the required D7-S *mixed write* test: sales, stock,
pricing and import writes must be run ONLY on isolated staged fixtures
with proven request UUIDs, bounded admission, financial reconciliation
and explicit approved credentials. Do not run destructive transfers on
a production host.

## D8/E deployed PostgreSQL connection and transaction preflight

The read-only `wa_backend/scripts/audit_product_import_d8_readonly.py` now
inspects **actual target-database** PostgreSQL connection pressure and session
lifetime. **Before any DB connection**, the staging preflight requires the
explicit `--env-file` to declare literal `DATABASE_URL` and
`DATABASE_URL_MIGRATION`. If inherited environment URLs conflict with that
file, it refuses to proceed without logging the URLs or credentials. It also
requires migration/runtime URLs to resolve to the **same host, port and DB**
(different database roles and PostgreSQL drivers are allowed). This
prevents an inherited developer/production URL silently overriding the
operator-specified staging target (`python -m unittest
tests.test_product_import_d8_target_binding` checks this contract without
DB/network). Do not commit the protected staging env file to Git.

The FORCE RLS inventory checks `public` tables explicitly, and worker
connections are matched by the exact entrypoint PGAPPNAME, not substrings.
Observing `wanasah-product-import-{role}` in `pg_stat_activity` proves
only a role-labeled DB connection. **It does not prove which commit is
loaded by that worker.** Procrastinate 3.9's `procrastinate_workers` table
stores worker id/heartbeat, not worker names or source hashes. Independently
compare freshly captured `PRODUCT_IMPORT_WORKER_CODE` startup records for
all three roles (commit+source_sha256+PID+start time) with the immutable
release checkout and the currently supervised OS processes. Preserve
startup logs and operator evidence; D8 stays OPEN without this live proof.

The known developer-only historical synthetic company-ID probe is not
executed on staging, so a staging tenant with the same numeric ID cannot be
misreported as an old developer job. This does not resolve the six old
nonterminal jobs on the actual developer database.

The read-only inventory script verifies observer privileges, compares the
configured web + operational + import pool envelope to reserved/max slots, prints only
**aggregate** client, idle-in-transaction, aged-transaction, lock-wait and
blocked-edge counts, and groups import execution/control/maintenance
`todo`/`doing` queue ages. It never prints query text, connection strings,
JWTs, user identifiers or customer row data, and never runs VACUUM, migrations,
recovery or worker starts.

On staging, with a **genuinely isolated** configured target DB, run the
documented `--scope staging --env-file .env.staging` command while the actual
4 web/operational/import workers and mixed staged workload are **running**.
A privileged observer role or `pg_read_all_stats` is required for complete
DB activity coverage. A missing worker role, over-budget clients, or
transactions **idle over 30 seconds** fails that staging preflight. The
script warns about any transactions older than 60 seconds or blocked-lock
edges, but these are diagnostics requiring SQL/operation attribution, not
proof of deadlock or a particular ORM regression.

The 2026-09-30 development **one-shot** snapshot showed a single local
observer connection, **0** idle transactions, **0** 60s-old transactions,
**0** lock blocking edges and no queued/running import deliveries at that
instant; **all three** import role connections remained absent and the
six previously observed historical synthetic nonterminal imports remained.
This does **not** prove that workload-time locks never occur or that staging
workers have been deployed. No action was taken against those six jobs.

## Local evidence and first-company V1 deployment gate

- [x] **Product Import engineering gate accepted locally:** D1 committed Sale/COGS, Supplier Inbound, Route Launch during import, D2 contested pricing/Live Stock lock ordering, D3 queue fairness, D4 cancellation/crash/recovery, D5 WebSocket application-layer security, D6 measured predecessor-query correction and D7-L isolated integrity/load have independently recorded PASS results. This is NOT real ingress/TLS, production backup or browser acceptance; see historical archived audit for exact limitations.
- [x] **Local D8 backup/restore tooling reconfirmed 2026-09-30:** isolated PG16 disposable three-row FULL restore, atomic custom archive, corrupt input rejection, invalid retention fail-closed and zero residual restore DB all PASS. No customer data touched or full-size real DB restored.
- [x] **Import source-row/Excel + D8 target-contract no-DB regression:** one scoped execution of `tests.test_product_import_phase11_source_semantics` and `tests.test_product_import_d8_target_binding` on a deliberately non-running DB URL: **23/23 PASS**. This is a pure parsing/target contract gate, not an import execution/load/deployed-DB acceptance. Live-DB integration remains evidenced by the prior private D1/D4/D7-L runs; no test wrote to the existing developer data.

### Release-time acceptance on the actual installation — OPEN until then

These checks belong to launch operations, not an open-ended Product Import coding task. An isolated **local** installation with its own synthetic PostgreSQL database is acceptable for initial qualification; buying a VPS or renting a second host is not required to keep shipping the Dashboard. Previously passed D1, D2, D4, D5, D6, D7-L and import lineage/replay proofs remain valid for their stated scope; do not repeat the 1,000-arrival ASGI test absent a relevant source change. A bounded k6 REAL-HTTP pilot check must use the actual first-company estimated concurrent employees plus a deliberate headroom margin. A k6 HTTP 200 is not a committed business/stock/accounting test. Do not run synthetic writes against the existing development database.

- [ ] Identify the first company's **actual** deployment target, expected simultaneous active users and maximum import file size. Verify the target uses an isolated test DB for rehearsal, bounded HTTP/worker/PG connection budgets, and only approved sample identities; a local target and a small measured k6 smoke/load run are permitted. No forced four-web-worker or dedicated external generator requirement for one company.
- [ ] On the actual first-company target's **independent rehearsal database** run read-only `python -m scripts.audit_product_import_d8_readonly --env-file <rehearsal env> --scope staging` with `WANASAH_STAGING_READONLY_ACK=ISOLATED_SYNTHETIC_STAGING`. This requires genuine DB isolation even if hosted on the same computer. Confirm migrations, FORCE RLS, DB budget and real worker role processes; never pass this gate by renaming the developer DB or printing credentials.
- [ ] On the actual first-company target, produce a real backup and **restore the whole archive into a separate disposable DB** before any migration/launch. Verify Product/Variant/Price/Inventory/COGS/Audit/Outbox counts, duration, retention, access restrictions and an off-machine backup destination. The previously successful three-row synthetic full restore validates only the procedure/tooling, not the customer recovery-point objective.
- [ ] Migrate the approved target DB to the revision recorded in the immutable application release. Developer migration a42c9f17e6b3 was previously applied locally; this does NOT prove it was deployed elsewhere.
- [ ] Gracefully drain old workers. Deploy a single reviewed immutable backend/frontend/worker Git commit. Use worker_cli --role execution --print-code-identity (also control and maintenance) to verify code revision/checksum and confirm running process logs on startup. A source change never updates an already-running Python process.
> **Separate developer-machine maintenance, not a customer-launch prerequisite:** Six old QUEUED synthetic developer jobs (companies 2393-2398) need an owner-approved cleanup/recovery policy before ever enabling development-DB recovery. Do not execute or delete those jobs or historical queue records automatically. This cannot be used to block an unrelated, isolated first-company deployment.
- [ ] Run first-company **D7-P**: bounded k6 HTTP smoke plus a representative Sale/COGS + Supplier Inbound + Route Launch + Product Import workload on the isolated rehearsal target. Measure response p50/p95/p99 and error/429 distributions, then verify persisted accounting/stock/price/audit/outbox/idempotency and no long-lived DB transactions. Reuse previously passing D1/D2/D4/D7-L integration proofs; a read-only k6 check alone is insufficient for this acceptance. Actual traffic threshold depends on first-company workforce and host; do not invent a 1,000-user pass.

> **V2 deferred (NOT passed):** the historical D7-S 1,000 truly open TCP/TLS connections, independent load-generator host, sustained multi-company fairness and production-scale SQL/ORM/index profiling. These are tracked only in `VERSION_2_FUTURE_FEATURES.md` §8; retain old run/evidence in `docs/archive/V1_MULTITENANT_ASYNC_AND_IMPORT_RELEASE_PLAN_2026-09-30.md`.

- [ ] Confirm first-company actual network boundary logs never persist bearer tokens: Uvicorn canaries are passed locally; if a reverse proxy/CDN/WAF is deployed, also inspect its real edge logs. Do not require inspecting a proxy that does not exist, and do not assume a missing proxy makes app-layer log audit unnecessary.
- [ ] On the actual first-company target, exercise browser import start/progress, pause/lost network and retry with the original request ID, cancellation, worker restart, session expiry, and reconciliation of source-row errors/partial successes; verify already committed products are never falsely rolled back. Exercise one real product XLSX with representative default-tracking variations and clear recoverability messaging. Verify rollback/runbooks and alerts.
- [ ] Obtain release owner sign-off on first-company **D7-P/D8-P**, recovery point/time, real worker commit/source SHA, schema/index health, pilot SLOs, operational alerts and full business reconciliation. This is **release-time** acceptance, not reason to keep the already-reviewed Product Import development feature indefinitely open. Do not call the customer system production-ready before this acceptance.

## Outstanding release-time dependency

No specific first-company deployment host, ingress setup or expected employee concurrency was established. Consequently actual-target backup/restoration, live browser transport, worker SHA parity and measured first-company HTTP throughput remain **not yet executed**. No paid Staging or external generator is required now; `k6` is installed on the development Windows device. The verified developer read-only health census and disposable backup/restore gate are local evidence only. The Product Import **implementation scope** may be archived as accepted; actual deployment D7-P/D8-P must remain open here until the real target exists.
