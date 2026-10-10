# Identity Phase 3/4 Backfill Contract

**Status:** CANONICAL FOR PHASE 3/4 IMPLEMENTATION  
**Lead decision date:** 2026-10-10  
**Depends on:** `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md`, `IDENTITY_PHASE1_SEMANTIC_INVENTORY.md`, `IDENTITY_PHASE2_DECISION_FREEZE.md`, `IDENTITY_PHASE2_CAPABILITY_FREEZE.md`, `IDENTITY_AUTH_SESSION_CUTOVER_CONTRACT.md`.

## 1. Purpose

Phase 3/4 must classify every legacy `drivers` row deterministically and backfill the new identity tables without changing Runtime authentication, authorization endpoints, legacy foreign keys, or business workflow behavior.

The backfill is **not** allowed to infer architecture while running. It consumes a complete reviewed mapping and fails closed when the source no longer matches that mapping.

## 2. Temporary migration bridge

Add one temporary tenant-safe bridge table named `identity_legacy_driver_map`.

Required columns:

- `company_id`
- `legacy_driver_id`
- `classification`
- nullable `backoffice_principal_id`
- nullable `backoffice_user_id`
- nullable `field_principal_id`
- nullable `field_representative_id`
- `created_at`

Primary key:

- `(company_id, legacy_driver_id)`

Allowed classification codes exactly:

- `BACKOFFICE_ONLY`
- `FIELD_ONLY`
- `DUAL_SPLIT`

Required integrity:

- tenant-safe FK to the legacy `drivers` row while that table exists;
- tenant-safe FKs to every populated target principal/profile;
- `BACKOFFICE_ONLY` requires the Backoffice pair and forbids the Field pair;
- `FIELD_ONLY` requires the Field pair and forbids the Backoffice pair;
- `DUAL_SPLIT` requires both pairs;
- RLS and restricted Runtime-role grants follow the same project conventions as the Phase-2 identity tables.

The bridge is migration infrastructure only. It must be removed in the final contract phase after all old FKs have been migrated and verified.

## 3. No generic actor guess

The bridge must NOT contain a `principal_actor_default`, generic `new_user_id`, or any equivalent shortcut.

Reason: one legacy `Driver` can historically represent both Backoffice and field actions. Later `PRINCIPAL_ACTOR` FK migration must use the reviewed per-FK/per-workflow semantics from Phase 1. The bridge records both possible target identities and does not choose an incorrect historical actor by convenience.

## 4. Mapping input is explicit and complete

Backfill execution requires a reviewed mapping document/file covering every current legacy row.

For each row the mapping must include:

- `company_id`
- `legacy_driver_id`
- `classification`
- expected source identity facts used for stale-map detection
- target username for every created principal
- explicit `company_owner` boolean

The mapping file must never contain passwords or password hashes.

Backfill apply refuses:

- missing legacy rows;
- extra unmapped legacy rows;
- duplicate `(company_id, legacy_driver_id)` entries;
- stale source facts;
- unresolved classification;
- zero or multiple owners for a company that is being cut over;
- Owner mapped to a Field-only identity;
- duplicate target usernames inside a company;
- a dual split that does not provide two distinct company-local usernames.

## 5. Proposal vs apply

The implementation may provide a read-only proposal generator, but proposal output is evidence only.

Evidence rules:

- `is_admin=true` is Backoffice evidence, not proof of Owner authority by itself;
- role/location grants are Backoffice evidence;
- route/session/visit/shortage/expected-receiver usage is Field evidence;
- both evidence families produce `DUAL_SPLIT`;
- a row with weak/insufficient evidence must be flagged for explicit mapping instead of silently guessed.

Apply always consumes an explicit mapping, even when the proposal is unambiguous.

## 6. Source fingerprint / stale mapping protection

Each mapping entry must bind enough non-secret source facts to detect a changed legacy row before apply. At minimum this includes:

- company id;
- legacy driver id;
- username;
- active state;
- legacy `is_admin` value;
- relevant Backoffice grant counts;
- relevant Field ownership/reference counts.

A stable digest over canonicalized non-secret facts is acceptable.

If the live source differs from the reviewed mapping, apply fails before any write.

## 7. Identity creation rules

For a single-channel row:

- copy the legacy username unchanged unless the explicit reviewed mapping overrides it;
- copy `password_hash` byte-for-byte/value-for-value;
- copy common display identity fields;
- copy `is_active`;
- create only the required profile.

For `FIELD_ONLY`:

- copy `can_allow_debt` and `max_debt_limit` into `FieldRepresentative`.

For `BACKOFFICE_ONLY`:

- field-only debt attributes are not copied into Backoffice profile state.

For `DUAL_SPLIT`:

- create two distinct `CompanyPrincipal` rows;
- the mapping must provide two distinct usernames;
- copying the existing password hash to both initial principals is allowed for migration continuity, but the identities remain channel-separated and later password/security policy may change them independently;
- create one Backoffice profile and one FieldRepresentative profile;
- field-only debt attributes belong only to the FieldRepresentative profile.

New target IDs are generated normally. Do not force profile IDs or principal IDs to equal legacy `driver_id`.

## 8. Company Owner backfill

Owner selection is explicit in the reviewed mapping.

Rules:

- exactly one owner per company being backfilled;
- Owner must map to a Backoffice profile;
- `is_admin=true` alone never silently creates ownership;
- the backfill inserts the dedicated `company_owners` relation;
- no ordinary Role assignment is used as a substitute for Owner authority.

## 9. Transaction and idempotency

Backfill apply must be deterministic, fail closed, and safely rerunnable.

Required behavior:

- validate the full mapping and full current source before first write;
- execute the apply in one database transaction for the selected migration scope;
- if any invariant fails, commit nothing;
- after a successful apply, rerunning the exact same mapping must verify the existing bridge/target rows and return success without creating duplicates;
- if existing target/bridge data differs from the mapping, fail instead of repairing silently.

## 10. Secrets and output

Never print or persist:

- password hashes;
- raw refresh tokens;
- access tokens;
- database passwords.

Reports may include numeric IDs, classifications, counts, non-secret usernames when required for operator review, and source fingerprints.

## 11. What Phase 3/4 does NOT change

Do not change yet:

- `/login` or `/driver/login` Runtime behavior;
- JWT/refresh schema or token claims;
- `get_current_driver` / `get_current_admin`;
- `UserRole` / `UserLocationAccess` old FKs;
- the 55 reviewed legacy FKs;
- the three unresolved legacy FK columns;
- Dashboard or Flutter contracts;
- `driver.py` or `dispatch.py`;
- old `drivers.is_admin`.

Refresh sessions are not converted. Legacy refresh tokens are revoked only at the later auth cutover defined in `IDENTITY_AUTH_SESSION_CUTOVER_CONTRACT.md`.

## 12. Validation gate

Phase 3/4 backfill implementation is accepted only when focused evidence proves:

- every legacy row is mapped exactly once;
- no unmapped extra row exists at apply time;
- stale mapping detection works;
- single-channel Backoffice backfill works;
- single-channel Field backfill works;
- dual split works only with explicit distinct usernames;
- duplicate username fails;
- zero/multiple owner fails;
- password hashes remain unchanged without being logged;
- field debt settings land only on FieldRepresentative;
- RLS prevents cross-company bridge/identity visibility;
- apply is atomic;
- exact rerun is idempotent;
- changed rerun fails closed;
- no legacy FK or Runtime auth contract changed.

Only after this gate may Phase 5 authentication cutover begin.