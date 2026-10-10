# Phase 3/4 legacy identity backfill validation

Source main: c13f4ba5c806f3e030fdd621c7321b1663ffcc7b.
Migration: a4d2e7c9b630; down_revision: e9c4b1a7d620.
Only existing interpreter/packages; fresh localhost PostgreSQL 16; all rows synthetic.
Retained stopped cluster: C:\Users\admin\AppData\Local\Temp\wanasah_identity_backfill_qetsuro2.

- PASS: CLEAN_BOOTSTRAP_AND_ADDITIVE_BRIDGE_UPGRADE
- PASS: EMPTY_BRIDGE_DOWNGRADE_UPGRADE
- PASS: READONLY_EVIDENCE_ALL_FIVE_FIELD_REFERENCES_AND_EXPLICIT_REVIEW
- PASS: OPERATOR_CLI_REPORT_VALIDATE_SECRET_REDACTION
- PASS: PREWRITE_REJECTION_CASES_15
- PASS: CONCURRENT_SOURCE_COMMIT_CAUSES_STALE_REFUSAL
- PASS: LATE_DATABASE_FAILURE_ROLLS_BACK_BOTH_COMPANIES
- PASS: BACKOFFICE_FIELD_DUAL_OWNER_HASH_DEBT_INDEPENDENT_IDS_EXACT_RERUN
- PASS: DIVERGENT_MAPPING_TARGET_OWNER_BRIDGE_RERUNS_REFUSED
- PASS: BRIDGE_AND_IDENTITY_RLS_FIVE_TENANT_FKS_AND_SHAPE_CHECKS
- PASS: OPERATOR_CLI_APPLY_EXACT_RERUN
- PASS: ALL_LEGACY_ROWS_55_FKS_REFRESH_AND_AMBIGUOUS_CONTRACTS_PRESERVED
- PASS: ALEMBIC_METADATA_DRIFT_CHECK
- PASS: POPULATED_BRIDGE_DOWNGRADE_REFUSED
- PASS: ISOLATED_CLUSTER_STOPPED

7 legacy rows / 2 companies -> 8 principals, 5 Backoffice profiles, 3 Field profiles, 2 explicit Owners, 7 bridge rows.
Four BACKOFFICE_ONLY, two FIELD_ONLY, one DUAL_SPLIT. Hashes copied unchanged and excluded from reports/mappings/errors.
All 55 old Driver FKs preserved; one new bridge FK references Driver. No runtime auth/token/FK cutover.
All current Driver rows must be covered globally. Companies without Drivers are outside this backfill scope.
Source and target locks are bounded; atomicity covers rows, while normal PostgreSQL sequences may consume IDs on rollback.
Password hashes are deliberately excluded from the non-secret review fingerprint; apply copies the current locked source hash,
and exact rerun compares that source hash against every mapped principal without logging it.
Bridge composite FKs enforce tenant correspondence. The service additionally verifies typed principal/profile pairs before commit/rerun.

## Reproduction and operator contract

From wa_backend, with the existing backend interpreter:

- python -m unittest tests/test_identity_legacy_backfill.py -v (6 static/model/offline-DDL checks).
- python tests/run_identity_legacy_backfill_gate.py --run (new isolated cluster, never an existing DB).

Operator CLI: python scripts/backfill_identity_from_legacy.py MODE --env-file PATH
where MODE is report, validate or apply. validate/apply additionally require --mapping-file reviewed.json.
report optionally accepts --output proposal.json; otherwise emits JSON to stdout.
Explicit env file must declare literal DATABASE_URL_MIGRATION and DATABASE_URL for the same PostgreSQL DB;
conflicting inherited URLs are rejected. Full-source visibility requires the migration role (superuser/BYPASSRLS).
No credentials or connection URLs are included in command errors.

JSON format_version=1, reviewed=true, entries=[...]. Each entry requires company_id, legacy_driver_id,
classification, expected_source, source_fingerprint, backoffice_username, field_username, company_owner.
Unknown fields (including password_hash) and duplicate JSON keys are rejected. No target IDs are provided;
PostgreSQL generates them. Usernames are used exactly as reviewed. Owner selection is always explicit.
Proposal reviewed=false, company_owner=null, weak classification=null; DUAL field_username is deliberately null.
Review resolves those fields without altering expected_source/source_fingerprint. is_admin is evidence, never Owner proof.
The reference digest includes sorted row IDs and grant attributes, detecting same-count replacement/role edits.

## Acceptance coverage

| Contract gate | Evidence |
| --- | --- |
| Complete one-to-one source; no missing/extra/duplicate/stale rows | 15 prewrite rejections; live username/role/new-row edits; concurrent source commit |
| Three classifications, explicit unique Owner, distinct DUAL usernames | 4 BO / 2 Field / 1 Dual; 2 Owners; invalid kinds/dual usernames/zero or multiple Owners/Field Owner rejected |
| Exact credential copying, field-only debt, independent IDs | All 8 principal hashes equal locked source; 3 debt profiles equal source; separate generated sequence ranges |
| No partial apply | Real trigger failure in second company; all five target tables remain empty |
| Exact rerun / divergent rerun | Bridge rows and sequences unchanged; changed username/hash/revision/debt/Owner/map/bridge/extra target refused |
| Tenant-safe bridge and identities | 5 FK tenant rejections, 2 shape rejections; missing/empty/foreign tenant read/write denied, including permissive-policy override attempt |
| Schema lifecycle and preservation | Clean bootstrap, empty round-trip, populated refusal, Alembic check; all old schema and all legacy row digests unchanged |
