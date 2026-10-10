# Principal refresh persistence expand validation

Source main: 93258405bccf3d86d6a3293b28028925b153f843.
Migration: b7e3f6a1c902; down_revision: a4d2e7c9b630.
Existing interpreter/packages only; fresh localhost PostgreSQL 16; all fixtures synthetic.
Retained stopped cluster/logs: C:\Users\admin\AppData\Local\Temp\wanasah_principal_refresh_lspcam34.

- PASS: CLEAN_BOOTSTRAP_TO_CURRENT_HEAD
- PASS: ADDITIVE_EMPTY_UPGRADE_CONSTRAINTS_EIGHT_INDEXES_RLS_GRANTS_SEQUENCE
- PASS: FK_CHECK_UNIQUE_REJECTION_CASES_16
- PASS: EXACT_TOKEN_LOOKUP_SUCCESSOR_UNIQUENESS_DELETE_SET_NULL_CASCADE
- PASS: TENANT_RLS_READ_WRITE_REPLACEMENT_AND_RESTRICTIVE_POLICY
- PASS: POPULATED_DOWNGRADE_REFUSED_WITH_ROWS_AND_HEAD_RETAINED
- PASS: ALL_OLD_SCHEMA_ROWS_56_DRIVER_FKS_LEGACY_REFRESH_ROTATION_PRESERVED
- PASS: CONCURRENT_INSERT_PREVENTS_DOWNGRADE_DATA_LOSS
- PASS: ALEMBIC_METADATA_DRIFT_CHECK
- PASS: EMPTY_DOWNGRADE_UPGRADE_ROUNDTRIP_AND_OLD_CONTRACT_PRESERVATION
- PASS: ISOLATED_CLUSTER_STOPPED

5 static/model/offline-DDL checks: python -m unittest tests/test_principal_refresh_session_expand.py -v.
Isolated gate: python tests/run_principal_refresh_session_expand_gate.py --run (from wa_backend).

Storage mirrors current RefreshToken: exact VARCHAR(500) token value, global token uniqueness,
one predecessor per successor (unique nullable replaced_by_id), explicit expiry/revocation/created_at.
Tenant principal FK and same-company/principal/channel successor FK are database-enforced.
Successor deletion sets only replaced_by_id NULL; principal deletion cascades sessions, as legacy identity deletion does.
auth_revision is required explicitly and must be positive; no implicit issuing revision is chosen.
Eight constraints, eight indexes, two RLS policies (one restrictive), one independent sequence.
Empty round-trip succeeds; populated downgrade refuses before DROP under ACCESS EXCLUSIVE lock.
A session committed while downgrade waited was retained, and downgrade refused.
All pre-existing table/column/constraint/index/RLS definitions and all old rows are fingerprint-preserved.
56 current Driver FKs (55 original plus temporary bridge) remain unchanged.
No JWTs issued or endpoints called. No legacy refresh conversion/revocation or runtime auth cutover.
Channel/principal-type/profile/activity/revision validation, locking/rotation/grace and logout remain later runtime cutover work.
