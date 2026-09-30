# Wanasah V1 Product Import — Release Runbook (2026-09-30)

**Status: local proof completed; staging/production sign-off OPEN.** This file is a deployment procedure, not evidence that a public server was updated.

## Existing proofs — do not rerun without a relevant change

D1: real Sales, Supplier Inbound, Route Launch during Import. D2: deliberate Company/Pricing/Live Stock lock contention. D3: separated execution/control/maintenance workers and durable event-driven scheduling with 2 bounded import slots. D4: orphan recovery, parsing cancellation and worker-kill replay. D5: WebSocket JWT no longer in URL; Uvicorn access-log canaries. D6: measured equivalent bounded predecessor pricing query. D7-L: local 1,000-request mixed ASGI workload, not 1,000 active HTTP connections.

D8's NEW synthetic backup/restore toolchain passes an atomic PostgreSQL custom archive test, a FULL three-row restore in a new disposable PostgreSQL 16 database, a rejection of malformed archives and of invalid retention settings, and cleanup of the test database. It did not read or overwrite the development data. The local read-only preflight reported matching Alembic HEAD, FORCE RLS on required import tables, and a connection budget of 46 within 60 against max_connections=100. The local Product Import worker roles were not connected, and six nonterminal synthetic test imports still existed.

## Backup migration and restore instructions

The revised scripts/backup_db.sh creates a PostgreSQL custom-format .dump file without double-gzipping, writes to a temporary file with restricted permissions, validates the archive directory and publishes atomically before retention. It prunes only its own new .dump outputs AFTER successful backup, leaving every legacy .sql.gz artifact untouched. A readable archive is not proof of full restoration.

On a Linux deployment host, configure POSTGRES_DB, POSTGRES_USER, POSTGRES_HOST, POSTGRES_PORT, BACKUP_DIR and RETENTION_DAYS from approved secrets/deployment settings; use secure libpq credentials and encrypted offsite storage. Run wa_backend/scripts/backup_db.sh. Then, on a dedicated disposable local restore host, run wa_backend/scripts/verify_restore_backup.sh with the absolute .dump path and RESTORE_HOST=127.0.0.1, RESTORE_PORT, RESTORE_USER. That script creates a NEW randomly named disposable database and destroys it after successful or failed verification. It refuses non-loopback restore hosts. Do NOT point it at existing development or production databases. Verify FULL production-sized anonymized backups separately; the tiny synthetic gate is only a test of the backup/restore code path.

To rerun the backup toolchain gate ONLY after changing these scripts: from wa_backend, set WANASAH_D8_DISPOSABLE_GATE=1 and run python -m scripts.gate_product_import_d8_backup_restore_disposable. This gate starts and tears down its own loopback PostgreSQL cluster on port 55447.

## D7-S external load-generator safety baseline (read-only)

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
lifetime. It verifies observer privileges, compares the configured web +
operational + import pool envelope to reserved/max slots, prints only
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

## Remaining required deployment steps (not done)

- [ ] Provision independently isolated staging with its own test tenants, DB, TLS ingress, four web processes and SEPARATE load generator. The developer workstation and its synthetic local PostgreSQL are NOT production-like staging. Docker CLI is installed, but its Docker daemon was unavailable in the readiness inspection.
- [ ] Execute the READ-ONLY staging inventory script: python -m scripts.audit_product_import_d8_readonly --env-file .env.staging --scope staging, setting WANASAH_STAGING_READONLY_ACK=ISOLATED_SYNTHETIC_STAGING only when the DB is genuinely independent. Refuses treating the developer DB as staging. Check Alembic, FORCE RLS, DB budget, actual worker registrations.
- [ ] On the target staging environment, obtain and FULLY restore a real-size anonymized backup before schema migration. Compare schema, product/variant/stock/financial record totals and migration state. Verify restore duration and retention/offsite policy.
- [ ] Migrate the approved target DB to the revision recorded in the immutable application release. Developer migration a42c9f17e6b3 was previously applied locally; this does NOT prove it was deployed elsewhere.
- [ ] Gracefully drain old workers. Deploy a single reviewed immutable backend/frontend/worker Git commit. Use worker_cli --role execution --print-code-identity (also control and maintenance) to verify code revision/checksum and confirm running process logs on startup. A source change never updates an already-running Python process.
- [ ] Reconcile the six old QUEUED synthetic developer jobs (companies 2393-2398) under an explicit retention/cleanup policy before enabling developer DB recovery. Do NOT execute them or erase them by accident. Check Procrastinate terminal-history retention independently; do not delete historical queue records without approval.
- [ ] Run D7-S: one thousand genuinely open HTTP connections AND a separate 1000-arrival bounded mixed read/write submission through staging TLS ingress using an independent generator; production-sized catalogues and pricing histories; expected 429/Retry-After; p50/p95/p99, active connections, DB blocking duration including work_sessions, CPU/RAM, fairness and retry/crash behavior. Reconcile Sale/COGS, Inbound, Route commercial context, stock, Product/Price/Audit/Outbox and tenant RLS. The completed D7-L does not certify this test.
- [ ] Check all upstream CDN/WAF/reverse-proxy logs with synthetic canaries: Uvicorn redaction alone cannot protect credentials already recorded by an edge gateway. Investigate any historically exposed access tokens under the existing incident runbook.
- [ ] Validate actual browser import progress, cancellation, disconnect/reconnect, admin session behavior and old-build compatibility during staged rollout; verify rollback/runbooks and on-call monitoring.
- [ ] Obtain deployment owner approval of monitoring, schema/index health, remote backup/restore, worker version parity, release SLOs and alerting; only then mark Gate D7 and Gate D8 complete and authorize production rollout.

## Explicit blockers

No confirmed independent staging infrastructure or external load-generator host was discovered from the current local repository/device. Production-sized restore and upstream ingress audit have NOT been executed. Read-only developer checks and synthetic FULL restore were successful, but staging and production readiness remain OPEN by design.
