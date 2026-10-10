# Identity additive schema validation

Source main: 5cf830518580f9287fb141d29355e7b62b88ba70.
Migration: e9c4b1a7d620; down_revision: c6f1a4d8e203.

Existing backend interpreter/packages only; no installations or developer database access.
Fresh PostgreSQL 16 cluster bound only to 127.0.0.1; all data synthetic.
Retained stopped cluster/log path: C:\Users\admin\AppData\Local\Temp\wanasah_identity_expand_i9_axjew.

## Results

- PASS: 8 static/model/offline-DDL unittest checks (existing interpreter; no pytest required).
- PASS: CLEAN_BASELINE_BOOTSTRAP
- PASS: ADDITIVE_EXPAND_UPGRADE
- PASS: CONSTRAINTS_INDEXES_RLS_GRANTS_SEQUENCES
- PASS: NEGATIVE_CONSTRAINTS_18
- PASS: RUNTIME_RLS_ALL_FOUR_TABLES_MISSING_AND_FOREIGN_TENANT
- PASS: POPULATED_DOWNGRADE_REFUSED_AT_HEAD
- PASS: CONCURRENT_INSERT_PREVENTS_DOWNGRADE_DATA_LOSS
- PASS: ALEMBIC_MODEL_DRIFT_CHECK
- PASS: EMPTY_DOWNGRADE_UPGRADE_AND_LEGACY_PRESERVATION
- PASS: ISOLATED_CLUSTER_STOPPED

Owner slot uniqueness/Backoffice/type linkage are DB-enforced. Expand leaves all four
tables empty; exactly-one owner presence for each operating company belongs to the later
approved provisioning/live-data preflight and cutover. No legacy owner was selected.
Runtime role grants follow existing backend DML conventions; protected ownership mutation
authorization remains part of the later dedicated workflow, with no owner-management API here.
Downgrade accepts only empty new tables and refuses populated identity tables before any DROP.
The emptiness check holds ACCESS EXCLUSIVE locks; a concurrent committed insert was retained.
No legacy FK or ambiguous actor field was changed or classified.

## Schema contract verified

- Four new tables; three independent SERIAL sequences for principal and profile IDs.
- Seven new FKs, seven tenant-safe unique constraints, five CHECK constraints and four PKs.
- Twelve indexes (including PK/unique indexes), eight RLS policies; four restrictive tenant fences.
- Company-local username uniqueness; fixed profile type plus same-company/type composite principal FK.
- `company_owners.company_id` is the owner-slot PK, referencing the same-company Backoffice profile.
- `auth_revision` is a positive integer starting at 1. Credentials/common display fields stay on principal.
- `can_allow_debt` and nonnegative NUMERIC(12,3) `max_debt_limit` are FieldRepresentative-only.
- All 55 legacy `drivers` FKs and all legacy table/column/index/RLS definitions retained identically.
- Alembic metadata registration changes by one import only; no application startup/auth wiring changes.

Reproduce from `wa_backend` with the existing backend interpreter:

```text
python -m unittest tests.test_identity_schema_expand -v
python tests/run_identity_schema_expand_gate.py --run
```

The gate accepts no development DSN. It initializes a new cluster, checks its exact data directory,
uses separate synthetic restricted runtime/migration roles, stops the cluster and preserves logs/data.
The first sandbox attempt denied initdb directory creation; the scoped test-cluster escalation passed.
No migration was applied to the development/production database. Runtime login/capability cutover,
live-data preflight, owner selection and active-company owner-presence acceptance remain later phases.
