# Identity Phase 2 Decision Freeze

**Status:** CANONICAL FOR PHASE 2 IMPLEMENTATION
**Owner/lead decision date:** 2026-10-10
**Depends on:** `ARCHITECTURE.md`, `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md`, `IDENTITY_PHASE1_SEMANTIC_INVENTORY.md`, `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`.

## 1. Identity model

- `CompanyPrincipal` is the company credential root.
- It owns: `id`, `company_id`, `username`, `password_hash`, `full_name`, optional `phone_number`, `principal_type`, `is_active`, an auth/session revision field, timestamps, and tenant-safe uniqueness/indexes.
- Initial principal types are exactly `BACKOFFICE` and `FIELD_REPRESENTATIVE`.
- Principal type defines the allowed identity/channel family. It is NOT a permission system.
- `BackofficeUser` and `FieldRepresentative` are separate 1:1 domain profiles with their own independent primary keys and tenant-safe unique `principal_id` links. Do not reuse one numeric ID as an implicit alias for the other identity.
- `FieldRepresentative` owns field-only business attributes such as debt allowance/limit. `BackofficeUser` must not carry them.
- New identity persistence belongs under a dedicated modular boundary (`wa_backend/domains/identity/` or the exact equivalent approved by the lead), not as more unrelated logic piled into `driver.py`, `dispatch.py`, or a new god-file.

## 2. Access channels

- `/login` remains the Dashboard entry point and accepts only active `BACKOFFICE` principals with a valid Backoffice profile.
- `/driver/login` remains the Flutter field entry point and accepts only active `FIELD_REPRESENTATIVE` principals with a valid FieldRepresentative profile.
- Public URLs remain stable during this migration.
- Dual-channel access is never inferred. A credential/profile from one channel is rejected by the other channel unless a future explicitly approved workflow is designed.

## 3. Company Owner

- Company Owner is a protected system-managed authority, not `is_admin=true` and not an editable normal role.
- V1 target is exactly one primary owner relation per company.
- Owner must reference a Backoffice identity.
- Owner receives the complete company capability set centrally.
- Owner authority never bypasses tenant existence, object existence, structural route validity, stock integrity, or other business invariants.
- Ownership transfer is a separate future/explicit strongly confirmed audited operation.
- Legacy owner selection is NOT guessed from source. Phase 3 live-data preflight must identify the intended owner and fail closed if multiple candidates or dual-use rows are ambiguous.

## 4. Authorization engine

- Preserve the existing strong pieces: `Permission`, `Role`, role-permission bundles, company grants, exact-location grants, and pre-pagination authorization filtering.
- Replace identity coupling and the `is_admin` shortcut; do not rewrite working permission semantics from scratch.
- `UserRole` and `UserLocationAccess` become Backoffice-only grants after cutover.
- Authorization target remains: `authenticated principal + channel + capability + applicable scope -> backend decision`.
- Roles remain named bundles; role names are not authorization contracts.
- No generic `admin.*` capability family is allowed as a shortcut.
- Reuse existing capability codes where the existing code accurately owns the business action. Add narrow new codes only for genuinely new administration actions.

## 5. Phase-2 schema shape

Additive/expand work only. Do not drop `drivers`, `is_admin`, old FKs, old response fields, or old login behavior in this phase.

Target new tables/concepts:

- `company_principals`
- `backoffice_users`
- `field_representatives`
- `company_owners`

Required invariants:

- tenant-safe composite uniqueness/FKs;
- company-local username uniqueness;
- each profile principal link is unique and same-company;
- Backoffice profile only links to a `BACKOFFICE` principal;
- FieldRepresentative profile only links to a `FIELD_REPRESENTATIVE` principal;
- one primary owner per company and owner references Backoffice identity;
- schema/index/RLS changes occur via Alembic, never app startup.

Exact enforcement may use DB constraints plus application/domain validation where PostgreSQL cannot express cross-table type checks directly without harmful coupling, but the invariant must be explicit and testable.

## 6. Principal vs profile FK rule

- `PRINCIPAL_ACTOR` history/action fields migrate to `CompanyPrincipal`.
- `FIELD_REPRESENTATIVE` work-owner fields migrate to `FieldRepresentative`.
- Backoffice grants migrate to Backoffice identity only.
- Do not convert every `driver_id` to one target mechanically.
- The reviewed Phase-1 FK matrix is the source of truth for each relationship.

## 7. The three ambiguous FKs

Do NOT destructively classify them during the initial expand migration:

- `Shop.added_by_driver_id`: preserve legacy data/column during expand. Future replacement must distinguish generic creator provenance from field-origin provenance deterministically.
- `InventoryDamageEvent.source_driver_id`: preserve during expand until active workflow/history proves semantic ownership.
- `InventoryDamageEvent.receiving_admin_id`: preserve during expand until active workflow/history proves semantic ownership.

No worker may guess based on column names.

## 8. Token/session contract

- After cutover, JWT subject is `CompanyPrincipal.id`.
- JWT carries stable principal/channel identity metadata needed to reject the wrong application channel, but authorization capabilities are resolved from persisted authority, not trusted from token claims.
- Refresh session persistence binds principal + company + explicit channel.
- Stored refresh identity must match decoded principal/company/channel before rotation.
- Rotation successor remains bound to the same identity/channel.
- Legacy refresh sessions are revoked at cutover instead of guessed/converted. One re-login is acceptable and safer than cross-channel ambiguity.
- Existing brute-force, blacklist, expiry, tenant-context, rotation-grace, active-company and active-account protections must be preserved.

## 9. WebSocket/realtime

- Realtime authorization uses persisted Backoffice principal/capability context after cutover.
- Do not broaden company-wide dispatch broadcasts to every holder of `dispatch.read` during Phase 2.
- Current restricted broadcast semantics remain until an explicit topic/subscription scope is designed.

## 10. Operational workflow preservation

- Stocktake second-actor/recount/password-confirmation and separation-of-duties rules remain intact.
- Settlement, returns, visits/reconciliation, shortages, archive navigation and route/vehicle/location structural checks remain intact.
- Capability migration replaces legacy authority; it is not permission to weaken workflow/state/location guards.
- Owner full capability does not mean bypassing missing source warehouse, invalid vehicle custody, missing route structure, or inventory integrity checks.

## 11. Current V1 organization

- Company remains the tenant/security boundary.
- One company may have one or many warehouses.
- Products, zones/territories, shops, representatives and vehicles remain company-wide master data.
- Branch is not part of current V1 identity/auth context and no branch switcher is introduced by this migration.
- Future organizational scopes must remain addable without changing Company as tenant.

## 12. Parallel worker boundaries for Wave 2

### Schema worker
Owns only:
- modular identity models/persistence;
- additive Alembic expand migration;
- constraints/indexes/RLS needed for new identity tables;
- focused schema/migration contract tests/evidence.

Must NOT:
- change `auth.py`, `dependencies.py`, `inventory_access.py`, `driver.py`, `dispatch.py`, Dashboard or Flutter;
- backfill/delete legacy rows;
- remove legacy fields/FKs;
- choose owner data from the live database.

### Authorization worker
Owns only:
- modular capability/authorization core;
- extraction/adaptation of existing permission catalog and grant-resolution logic behind clean interfaces;
- compatibility façade so existing Runtime behavior remains unchanged during the expand step;
- focused pure/unit/contract coverage for the authorization primitives.

Must NOT:
- change identity schema/migrations;
- change login/JWT/refresh;
- cut over endpoints;
- remove `is_admin` yet;
- touch `driver.py` or `dispatch.py`.

### Primary lead
Owns:
- auth/JWT/session/channel integration design and later cutover;
- owner/live-data preflight decisions;
- merge ordering and integration;
- capability freeze for ambiguous endpoint families;
- final review of every worker branch.

## 13. Phase-2 gate

Phase 2 is complete only when:

- additive identity schema exists cleanly and is migration/bootstrap safe;
- modular authorization primitives exist without changing current business behavior;
- no destructive legacy cleanup has occurred;
- no new god-file or mixed responsibility module was introduced;
- no worker changed `driver.py`/`dispatch.py` as a side effect;
- primary lead verifies the branches independently before merge.