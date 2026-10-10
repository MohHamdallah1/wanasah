# Wanasah Identity & Authorization Migration Plan

## Remove `is_admin`, split Backoffice vs Field Representative identity, and establish capability-based authorization

**Status:** PLANNED — NOT YET IMPLEMENTED  
**Owner decision date:** 2026-10-10  
**Scope:** Backend identity/authentication/authorization, database identity references, Dashboard auth/access contracts, Flutter field identity contracts, realtime auth, audit/idempotency actor references, and legacy cleanup.  
**Canonical architecture:** `ARCHITECTURE.md`, `.rules`, `AGENTS.md`, `V1_SCOPE_FREEZE.md`.

---

## 0. Owner decisions frozen for this plan

- [ ] The company remains the tenant/security boundary.
- [ ] Current V1 organizational UX is one company context with one or many warehouses.
- [ ] Products, zones/territories, shops, field representatives, and vehicles are company-wide master data.
- [ ] Do not permanently attach a representative, vehicle, product, zone, or shop to one warehouse as identity authority.
- [ ] This migration must not introduce a global Branch switcher or make Branch a sub-tenant.
- [ ] Branch readiness may remain possible for future expansion, but this migration must work correctly without Branch and must not depend on `branch_id` for identity/authorization.
- [ ] Backoffice users and field representatives are different domain identities and different access channels.
- [ ] Field representatives use Flutter only in V1.
- [ ] Backoffice users use the company Dashboard only.
- [ ] Company Owner is a protected system-managed authority, not an ordinary editable role.
- [ ] New authorization uses stable capabilities + applicable scope, not persona names and not `is_admin`.
- [ ] UI remains simple; permission/scope complexity stays backend-authoritative.
- [ ] No long-lived compatibility debt is accepted. Temporary migration compatibility may exist only inside this plan and must be removed before final acceptance.

---

## 1. Why this is not a simple line replacement

The legacy `Driver` entity currently represents several different concepts at once:

1. login credentials / authenticated company principal;
2. Dashboard administrator/backoffice user;
3. Flutter field representative;
4. audit actor for administrative operations;
5. route/visit/work-session representative identity.

`is_admin` is therefore used for more than one semantic purpose:

- authorization bypass / admin gate;
- Dashboard-vs-field classification;
- selecting field representatives with `is_admin = false`;
- response/UI display;
- Dispatch validation;
- Inventory access behavior;
- realtime authorization.

A blind `is_admin -> capability` replacement would leave the deeper `Driver` identity coupling intact and can corrupt authorization semantics. The migration must split **who the principal is**, **which application channel is allowed**, **what the actor may do**, and **which business profile the principal owns**.

---

## 2. Audited baseline — 2026-10-10

These counts are evidence from `origin/main` at planning time. Phase 1 must re-run the inventory against the newest `main` before implementation because counts can drift.

- [ ] ~53 direct Runtime references to `is_admin` were identified.
- [ ] 94 combined Runtime references to `is_admin` and/or `get_current_admin` were identified across 22 files.
- [ ] 43 database foreign-key relationships in `wa_backend/models.py` currently target `drivers`.
- [ ] 769 `Driver` / `driver_id`-related Runtime references were identified across 49 backend files. Not all 769 require mutation, but every one must be classified before the legacy model is removed.
- [ ] Flutter has 16 identity-related references across 4 source files, including `/driver/login` and persisted `driver_id`.
- [ ] Dashboard has 61 `driver_id` / `is_admin` / admin-contract references across 39 source/test files in the planning grep; production and test references must both be reconciled.

### High-risk existing facts

- [ ] `/driver/login` and `/login` both authenticate from the same legacy `Driver` table.
- [ ] Dashboard authorization still uses `get_current_admin()` and direct `is_admin` checks in several modules.
- [ ] Dispatch identifies representatives in multiple places using `Driver.is_admin == False`.
- [ ] `UserRole` and `UserLocationAccess` currently reference `drivers`.
- [ ] `RefreshToken` currently references `driver_id`.
- [ ] Audit/financial/inventory tables frequently use `drivers` as the actor FK even when the actor is not a field representative.

---

## 3. Target identity model

### 3.1 Platform realm remains separate

Platform administration stays a different security realm from company identities.

Target concepts:

- Platform Owner;
- future Platform Staff / Support with platform-scoped capabilities;
- any future support access into a tenant must be explicit, tenant-scoped, audited, revocable, and attributable.

This migration must not merge platform credentials into company credentials.

### 3.2 Company credential root

Introduce a dedicated credential/authentication root such as `CompanyPrincipal`.

Required contract:

- `id`;
- `company_id` with tenant-safe composite uniqueness/FK support;
- `username` unique within company;
- `password_hash`;
- `full_name` / display identity fields that are genuinely common;
- `phone_number` if retained as common identity data;
- `is_active`;
- stable language-neutral principal type, initially at least `BACKOFFICE` and `FIELD_REPRESENTATIVE`;
- auth/session version or equivalent revocation-safe field if required by the final session design;
- timestamps/version as required by project conventions.

Rules:

- [ ] No `is_admin` column on the target principal.
- [ ] Principal type is not a permission system; it defines the identity/access-channel family.
- [ ] Principal type never replaces capability checks.
- [ ] Company/tenant isolation is enforced in every principal query and FK.
- [ ] RLS/policies/indexes are added through Alembic, not application startup.

### 3.3 Backoffice profile

Introduce a distinct `BackofficeUser` profile linked 1:1 to a `BACKOFFICE` `CompanyPrincipal`.

- [ ] Dashboard login requires a valid active Backoffice profile.
- [ ] Backoffice permissions are roles/capabilities, not fields on the profile.
- [ ] Warehouse/location scope is assigned only through the authorization model.
- [ ] No field-representative commercial/debt fields live here.

### 3.4 Field Representative profile

Introduce a distinct `FieldRepresentative` domain profile linked 1:1 to a `FIELD_REPRESENTATIVE` `CompanyPrincipal`.

Move field-only business data here, including `can_allow_debt`, `max_debt_limit`, and future field-only properties.

- [ ] Flutter field login requires an active Field Representative profile.
- [ ] Field representative cannot authenticate to Dashboard merely because credentials are valid.
- [ ] Dispatch/Visit/WorkSession field FKs target the representative profile, not generic credentials.
- [ ] No Dashboard role name is used to infer that a principal is a representative.

### 3.5 Company Owner

Create an explicit system-managed ownership authority, preferably a dedicated tenant-safe ownership relation rather than another boolean.

- [ ] Exactly one primary owner authority per active company unless an explicitly approved future model changes this.
- [ ] Owner principal must be a Backoffice principal.
- [ ] Owner receives complete company capabilities through owner authority, not an editable role assignment.
- [ ] Ordinary Backoffice users cannot demote/delete/replace the owner.
- [ ] Ownership transfer is a dedicated, strongly confirmed, audited operation.
- [ ] Migration must never guess among multiple legacy admin candidates; ambiguity fails closed.

---

## 4. Target authorization model

Canonical decision:

`authenticated principal + access channel + capability code + applicable scope -> backend decision`

- [ ] `Permission` remains a stable language-neutral capability catalog.
- [ ] `Role` remains a named company-owned bundle of capabilities.
- [ ] Role names are never authorization contracts.
- [ ] Replace `get_current_admin()` with explicit capability guards.
- [ ] Introduce/reuse one central authorization context/resolver instead of module-specific ad-hoc admin booleans.
- [ ] Owner authority is resolved centrally.
- [ ] Missing capability fails closed.
- [ ] Wrong company fails closed.
- [ ] Wrong location scope fails closed.
- [ ] Hidden/disabled frontend controls never replace backend enforcement.

### Location scope

- [ ] Backoffice users may receive company-wide capabilities and/or exact warehouse/location-scoped grants as appropriate.
- [ ] Company Owner has full company authority.
- [ ] Field representatives are not modeled as generic warehouse users. Their operational warehouse context comes from authoritative field workflows such as Route/Load/WorkSession.
- [ ] Vehicles are not users and receive no permissions; Inventory may treat a vehicle as a custody location.

---

# EXECUTION PLAN

## Phase 0 — Stability checkpoint and source freeze

- [ ] Start from the newest verified GitHub `main`.
- [ ] Confirm repository backup/mirror before identity schema work.
- [ ] Open one dedicated task branch/worktree; never edit `main` directly.
- [ ] Read `ARCHITECTURE.md`, `.rules`, `AGENTS.md`, `V1_SCOPE_FREEZE.md`, `RUN.txt`, current auth/access code, and this plan.
- [ ] Record current Alembic head.
- [ ] Confirm clean-bootstrap migration is healthy before adding new migrations.
- [ ] Record current authentication/session focused tests already passing; do not rerun unrelated suites.
- [ ] Do not touch unrelated local/generated Flutter or editor changes.

**Gate 0:** known-good main + backup + migration baseline recorded.

---

## Phase 1 — Exhaustive semantic inventory before code changes

### 1A. Re-run source inventory

- [ ] Re-run direct Runtime search for `is_admin`.
- [ ] Re-run Runtime search for `get_current_admin`.
- [ ] Re-run Runtime search for `Driver`, `driver_id`, `/driver/login`, JWT `role`, Dashboard `driver_id`, Flutter `driver_id`.
- [ ] Re-run `drivers.id` FK inventory from the current model/migration head.
- [ ] Save the exact source inventory as implementation evidence.

### 1B. Classify every `is_admin` use

Every occurrence must be assigned exactly one category:

- [ ] **A — Authorization gate**: become capability/scope check.
- [ ] **B — Owner/full-authority behavior**: become Company Owner authority.
- [ ] **C — Identity classification**: become explicit Backoffice vs Field Representative profile/type.
- [ ] **D — Presentation/response field**: remove or replace with capability/owner/profile contract.
- [ ] **E — Test/fixture/historical artifact**: update active fixtures; do not rewrite immutable historical migrations merely to erase text.

### 1C. Build endpoint -> capability matrix

For every endpoint currently depending on `get_current_admin` or direct `is_admin`:

- [ ] identify owning module;
- [ ] identify read vs mutation;
- [ ] define one stable capability code;
- [ ] define scope: company-wide, exact location, route/territory, or other explicit scope;
- [ ] document whether Company Owner is automatically authorized;
- [ ] add negative expected behavior for missing/revoked capability.

Do not invent broad `admin.*` shortcuts when a precise business capability can be named.

### 1D. Classify all 43 `drivers` FKs

Each FK must be classified as:

- [ ] **PRINCIPAL_ACTOR** — who created/approved/updated/performed an operation;
- [ ] **FIELD_REPRESENTATIVE** — the representative whose route/session/visit/business work it is;
- [ ] **BACKOFFICE_USER** — a Dashboard-specific user assignment if any truly requires that profile;
- [ ] **AMBIGUOUS** — semantics resolved from the owning workflow before migration; no guessing.

**Gate 1:** zero unclassified `is_admin` use, zero unclassified `get_current_admin` endpoint, zero unclassified `drivers` FK.

---

## Phase 2 — Database target contract and migration design

- [ ] Finalize `CompanyPrincipal` schema and indexes.
- [ ] Finalize `BackofficeUser` schema.
- [ ] Finalize `FieldRepresentative` schema.
- [ ] Finalize Company Owner relation/invariants.
- [ ] Finalize tenant-safe composite FK strategy.
- [ ] Add required RLS/policies through Alembic.
- [ ] Define role-assignment FK target so field principals cannot accidentally receive Dashboard roles.
- [ ] Define exact-location access FK target so field principals cannot accidentally receive generic Dashboard warehouse grants.
- [ ] Define `RefreshToken` target as principal identity.
- [ ] Define idempotency/audit actor FK target as principal identity.
- [ ] Define field-business FK target as Field Representative identity.
- [ ] Define sequence/index handling after explicit-ID backfill.
- [ ] Confirm no new table introduces nullable tenant authority or client-controlled `company_id` trust.

### Migration strategy

Use **expand -> backfill/cutover -> contract**. Temporary compatibility is allowed only while this task is in progress and must be removed by final acceptance.

- [ ] Expand migration adds target tables/columns/constraints without dropping `drivers`.
- [ ] Backfill step copies and classifies legacy rows.
- [ ] Cutover code reads/writes the new authority.
- [ ] Contract migration removes legacy FKs/table/columns only after acceptance.
- [ ] PostgreSQL migration remains transactional wherever practical.
- [ ] No `Base.metadata.create_all()` or startup repair.

**Gate 2:** reviewed schema diagram + migration mapping before any destructive schema action.

---

## Phase 3 — Legacy data preflight and deterministic classification

For each legacy `drivers` row record:

- [ ] company;
- [ ] `is_admin` value;
- [ ] UserRole membership;
- [ ] UserLocationAccess grants;
- [ ] route/session/visit/shortage references;
- [ ] audit/created_by/approved_by references;
- [ ] active refresh tokens;
- [ ] owner candidacy;
- [ ] active/inactive state.

Rules:

- [ ] `is_admin = true` is migration evidence only, not the target authority.
- [ ] role/location grants are evidence of Backoffice use.
- [ ] route/session/visit/field references are evidence of Field Representative use.
- [ ] a row used as both Backoffice and Field is **DUAL-USE AMBIGUITY**, not silent dual access.
- [ ] dual-use ambiguity requires explicit split into separate principals/profiles and deterministic FK remapping.
- [ ] zero or multiple owner candidates fail closed until mapping is explicit.
- [ ] password hashes are copied unchanged.

**Gate 3:** classification report has zero unresolved rows.

---

## Phase 4 — Expand schema and backfill identities

- [ ] Create CompanyPrincipal table + tenant constraints/RLS/indexes.
- [ ] Create BackofficeUser profile table.
- [ ] Create FieldRepresentative profile table.
- [ ] Create Company Owner authority relation.
- [ ] Copy legacy credentials/common identity into CompanyPrincipal.
- [ ] Create Backoffice profiles from the approved classification map.
- [ ] Create Field Representative profiles from the approved classification map.
- [ ] Move `can_allow_debt` and `max_debt_limit` to FieldRepresentative authority.
- [ ] Preserve existing IDs where safely useful; document every intentional preservation.
- [ ] Split dual-use rows explicitly rather than enabling accidental dual-channel access.
- [ ] Advance PostgreSQL sequences after explicit-ID inserts.
- [ ] Backfill Company Owner only from approved mapping.
- [ ] Verify per-company username uniqueness.
- [ ] Verify no credential/hash changed unexpectedly.

**Gate 4:** row-count, uniqueness, tenant, profile, and owner invariants pass before auth cutover.

---

## Phase 5 — Authentication, sessions, tokens, and dependencies

### 5A. Central dependencies

- [ ] Replace legacy `get_current_driver()` as generic auth authority with principal-aware dependency.
- [ ] Add explicit Backoffice dependency.
- [ ] Add explicit Field Representative dependency.
- [ ] Never infer channel from a role name.

### 5B. Dashboard login

- [ ] Authenticate CompanyPrincipal credentials.
- [ ] Require Backoffice profile/type.
- [ ] Valid field-only credentials are denied Dashboard access.
- [ ] Remove `is_admin` from authority response.
- [ ] Return explicit owner/capability/access contract.

### 5C. Field login

- [ ] Replace canonical `/driver/login` with field-specific contract/name.
- [ ] Require Field Representative profile/type.
- [ ] Backoffice-only credentials are denied field login.
- [ ] Return `representative_id`, not ambiguous `driver_id`.
- [ ] Remove old `/driver/login` compatibility before final acceptance unless explicitly approved otherwise.

### 5D. JWT / refresh

- [ ] `sub` represents CompanyPrincipal.
- [ ] token carries trusted company context and explicit access channel/type needed to fail closed.
- [ ] remove `is_admin` claim.
- [ ] retire auth dependence on JWT `role = Admin|Inventory|Driver`.
- [ ] refresh token references principal identity.
- [ ] refresh cannot switch channel/profile type.
- [ ] disabled principal cannot refresh.
- [ ] company suspension remains enforced.
- [ ] forged claims cannot override persisted authority.
- [ ] invalidate legacy refresh tokens at cutover if safe migration is impossible; document one-time re-login.

### 5E. Logout / blacklist / credential confirmation

- [ ] logout/revocation remains correct.
- [ ] token blacklist remains valid.
- [ ] credential-confirmation uses principal identity.
- [ ] brute-force/login-attempt protections remain channel-safe.

**Gate 5:** cross-channel denial + refresh + logout + disabled-account behavior pass.

---

## Phase 6 — Backoffice RBAC and capability engine

- [ ] Refactor `UserRole` to target Backoffice identity.
- [ ] Refactor `UserLocationAccess` to target Backoffice identity.
- [ ] Rename persistence/contracts where needed so names no longer imply field Driver identity.
- [ ] Preserve correct `Role` + `Permission` semantics.
- [ ] Introduce one central capability resolver/context.
- [ ] Introduce reusable `require_capability(...)` guard.
- [ ] Support exact-location capability resolution without N+1.
- [ ] Company Owner resolves centrally to full tenant capabilities.
- [ ] Ordinary Backoffice users receive only assigned capabilities/scopes.
- [ ] revocation takes effect without trusting frontend state.
- [ ] Field representatives cannot receive Dashboard roles through these tables.
- [ ] permission APIs list/manage only Backoffice users.
- [ ] protected owner cannot be modified through ordinary role/grant APIs.

**Gate 6:** allow/deny + owner + exact-location tests pass.

---

## Phase 7 — Replace all `get_current_admin` gates module by module

### Branch APIs

- [ ] audit `wa_backend/api/branches.py` admin dependencies.
- [ ] do not couple new identities to Branch.
- [ ] if Branch endpoints remain enabled, protect them with a precise capability instead of `is_admin`.
- [ ] Branch UI defer/hide decision stays separate from this identity migration.

### Dispatch

- [ ] replace Dashboard admin gates with precise Dispatch capabilities.
- [ ] replace `is_admin == false` representative detection with FieldRepresentative identity.
- [ ] preserve route source warehouse checks and company/route/vehicle/representative isolation.

### Inventory access management

- [ ] replace `get_current_admin` with role/access-management capability.
- [ ] remove raw `is_admin` from `is_company_admin` authority.
- [ ] expose owner/full-access status from new resolver.

### Sales / Returns

- [ ] replace generic admin dependency with exact read/manage capabilities.

### Stocktake / stock policy / Live Stock

- [ ] remove direct `current_admin.is_admin` branches.
- [ ] preserve exact location permissions.
- [ ] separate approval vs read/count capabilities where required.

### Archive/navigation helpers

- [ ] replace `actor.is_admin` with capability/owner checks.
- [ ] navigation visibility remains UX only.

**Gate 7:** Runtime `get_current_admin` count = 0.

---

## Phase 8 — Field Representative domain cutover

- [ ] Rename runtime domain class/contract from generic `Driver` to `FieldRepresentative` where it truly means field representative.
- [ ] Replace Dispatch queries using `is_admin=False`.
- [ ] Replace “reject admin as driver” with profile-type validation.
- [ ] Convert route assignment FK.
- [ ] Convert WorkSession representative FK.
- [ ] Convert Visit representative FK.
- [ ] Convert ShortageRequest representative FK.
- [ ] Convert session/custody field-owned references where representative-specific.
- [ ] Convert shop `added_by_driver_id` provenance where it explicitly means field representative.
- [ ] Convert pricing/driver display and sales-calculation naming where it genuinely represents field context.
- [ ] Keep generic actor references generic; do not rename admin actor FKs to representative.
- [ ] Update API DTOs from `driver_id` to `representative_id` where semantically correct.
- [ ] Update error context keys accordingly.

**Gate 8:** field workflows operate without `is_admin` classification and without generic Driver auth authority.

---

## Phase 9 — Re-home every legacy `drivers` foreign key

### Expected PRINCIPAL_ACTOR examples

- [ ] InventoryCostPolicy `created_by` / `updated_by` / `selected_by`.
- [ ] ProductImportJob `created_by`.
- [ ] ProductLocation `created_by`.
- [ ] WorkSession `inventory_reconciled_by`.
- [ ] SessionInventorySnapshot `settled_by`.
- [ ] PriceBook `created_by`.
- [ ] PricePublication `created_by` / `approved_by`.
- [ ] PriceBookAssignment `created_by`.
- [ ] ImportLog legacy `admin_id`.
- [ ] SystemAuditLog actor.
- [ ] DomainAuditEvent actor.
- [ ] InventoryDamageEvent actor fields.
- [ ] OperationIdempotency actor.
- [ ] TenantOperationalPolicy actor fields.
- [ ] InventoryMovement `performed_by`.
- [ ] InventoryTransfer action actors where semantics mean authenticated actor.
- [ ] InventoryTransferLine FEFO override actor.
- [ ] Stocktake started/approved/cancelled/recount-authorizer actor fields.
- [ ] Stocktake count/discovery actor fields when workflow confirms generic actor semantics.
- [ ] InventoryLock creator/releaser.

### Expected FIELD_REPRESENTATIVE examples

- [ ] WorkSession representative ownership.
- [ ] DispatchRoute representative assignment.
- [ ] Visit representative ownership.
- [ ] ShortageRequest representative ownership.
- [ ] Dispatch load-plan representative references.
- [ ] shop field-creation provenance when it explicitly means field representative.

### Must be semantically reviewed — do not guess

- [ ] Inventory transfer `expected_receiver_id` and receiver/dispatched/cancelled fields.
- [ ] pricing references containing legacy driver naming: distinguish actor vs assigned representative.
- [ ] stocktake count/discovery fields used by more than one channel.
- [ ] any relation named `driver` whose business meaning is generic user/actor.

### FK migration rules

- [ ] preserve tenant-safe composite FKs.
- [ ] preserve RESTRICT/CASCADE semantics intentionally.
- [ ] validate FK target counts before dropping old constraints.
- [ ] accept zero orphan rows.
- [ ] never rewrite historical actor to a different person.
- [ ] numeric ID preservation is an implementation aid, not identity authority.

**Gate 9:** all 43 legacy `drivers` FKs have approved destination and validated data.

---

## Phase 10 — Dashboard contract migration

- [ ] `Login.tsx`: remove `is_admin` authority contract.
- [ ] remove navigation decision based on `data.is_admin`.
- [ ] use explicit Dashboard profile/owner/capability result.
- [ ] replace persisted Dashboard `driver_id` with unambiguous principal identity key.
- [ ] clear/migrate stale legacy localStorage keys safely.
- [ ] `TabInventoryAccess.tsx`: list Backoffice users only.
- [ ] remove “Admin كامل الصلاحيات” derivation from raw `is_admin`.
- [ ] display Company Owner as protected authority.
- [ ] role/location grants use Backoffice identity.
- [ ] no field representative appears in Dashboard role/location-grant pickers.
- [ ] migrate `useInventoryAccess.ts` identity assumptions.
- [ ] migrate Inventory cache keys using Dashboard principal identity.
- [ ] inspect every other production Dashboard `driver_id` reference from Phase 1.
- [ ] update tests/fixtures/e2e after production contract is final.
- [ ] keep UX business-simple; backend remains authority.

**Gate 10:** Dashboard works with Owner + restricted Backoffice user without `is_admin` response/state.

---

## Phase 11 — Flutter identity contract migration

Planning audit identified:

- `wanasah_frontend/lib/blocs/auth/auth_bloc.dart`
- `wanasah_frontend/lib/repositories/dashboard_repository.dart`
- `wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart`
- `wanasah_frontend/lib/core/network/api_client.dart`

- [ ] replace `/driver/login` with canonical field login endpoint.
- [ ] replace persisted `driver_id` with `representative_id`.
- [ ] migrate/clear old secure-storage key safely.
- [ ] update login response parsing.
- [ ] update payload keys that mean representative identity.
- [ ] update retry/interceptor login-path exception logic.
- [ ] preserve offline company/user isolation.
- [ ] logout clears new and legacy identity keys.
- [ ] network retry remains idempotent.

**Gate 11:** Flutter field login/session/route path uses representative identity; Backoffice is denied field login.

---

## Phase 12 — Realtime, audit, idempotency, jobs, cross-cutting identity

- [ ] `wa_backend/realtime/auth.py`: explicit channel/profile auth; no `is_admin` classifier.
- [ ] realtime remains company + actor scoped.
- [ ] audit logs use CompanyPrincipal for authenticated actor provenance.
- [ ] historical audit attribution survives migration.
- [ ] idempotency records use principal actor identity.
- [ ] background jobs persist principal creator/actor where required.
- [ ] product import creator migrates to principal.
- [ ] credential-confirmation migrates to principal.
- [ ] no worker trusts stale `is_admin`/role strings.

**Gate 12:** audit/replay/idempotency evidence retains correct actor.

---

## Phase 13 — Runtime file coverage checklist

Every current identity-related Runtime file must be inspected. “No change after semantic review” is allowed; silent skipping is not.

### Core auth/authorization

- [ ] `wa_backend/api/auth.py`
- [ ] `wa_backend/api/dependencies.py`
- [ ] `wa_backend/inventory_access.py`
- [ ] `wa_backend/dispatch_access.py`
- [ ] `wa_backend/realtime/auth.py`
- [ ] `wa_backend/api/inventory_permissions.py`
- [ ] `wa_backend/models.py`
- [ ] `wa_backend/schemas.py`
- [ ] `wa_backend/services.py`
- [ ] `wa_backend/seed_dev.py`

### Dispatch / field

- [ ] `wa_backend/api/dispatch.py`
- [ ] `wa_backend/api/driver.py`
- [ ] `wa_backend/domains/dispatch_reservations.py`
- [ ] `wa_backend/domains/dispatch_archive_navigation.py`
- [ ] `wa_backend/domains/operations_archive_navigation.py`
- [ ] `wa_backend/domains/sales_calculation/driver_sale.py`
- [ ] `wa_backend/domains/pricing/driver_authority.py`
- [ ] `wa_backend/domains/pricing/driver_display.py`

### Inventory / warehouse

- [ ] `wa_backend/api/warehouse/stocktake.py`
- [ ] `wa_backend/api/warehouse/transfers.py`
- [ ] `wa_backend/api/warehouse/live_stock.py`
- [ ] `wa_backend/api/warehouse/ledger.py`
- [ ] `wa_backend/api/warehouse/locations.py`
- [ ] `wa_backend/api/warehouse/inbound.py`
- [ ] `wa_backend/api/warehouse/transfer_policy.py`
- [ ] `wa_backend/api/warehouse/status.py`
- [ ] `wa_backend/api/warehouse/inbound_adjustments.py`
- [ ] `wa_backend/api/warehouse/whole_product_quality.py`
- [ ] `wa_backend/api/warehouse/whole_product_quality_preview.py`
- [ ] `wa_backend/api/inventory_stock_policy.py`
- [ ] `wa_backend/api/product_locations.py`
- [ ] `wa_backend/domains/inventory_batch_restrictions/queries.py`
- [ ] `wa_backend/domains/inventory_catalog_presence.py`
- [ ] `wa_backend/api/reconciliation.py`

### Catalog / pricing / commercial / suppliers

- [ ] `wa_backend/api/catalog.py`
- [ ] `wa_backend/api/simple_products.py`
- [ ] `wa_backend/domains/simple_products/service.py`
- [ ] `wa_backend/domains/simple_products/imports/api/router.py`
- [ ] `wa_backend/domains/simple_products/imports/infrastructure/repository.py`
- [ ] `wa_backend/api/product_tracking.py`
- [ ] `wa_backend/api/pricing.py`
- [ ] `wa_backend/api/offers.py`
- [ ] `wa_backend/domains/offers/models.py`
- [ ] `wa_backend/api/taxation.py`
- [ ] `wa_backend/domains/taxation/models.py`
- [ ] `wa_backend/api/commercial_policy.py`
- [ ] `wa_backend/api/suppliers.py`
- [ ] `wa_backend/domains/suppliers/models.py`
- [ ] `wa_backend/api/sales_returns.py`
- [ ] `wa_backend/domains/sales_returns/models.py`

### Tenant / platform / branches

- [ ] `wa_backend/api/tenant.py`
- [ ] `wa_backend/api/platform_manager.py`
- [ ] `wa_backend/api/branches.py`
- [ ] `wa_backend/domains/credential_confirmation.py`

### Dashboard core identity surfaces

- [ ] `dashboard/src/pages/Login.tsx`
- [ ] `dashboard/src/hooks/useInventoryAccess.ts`
- [ ] `dashboard/src/pages/inventory/MainInventory.tsx`
- [ ] `dashboard/src/pages/inventory/TabInventoryAccess.tsx`
- [ ] re-run Phase 1 grep and inspect every other production `driver_id` reference.

### Flutter

- [ ] all four source files listed in Phase 11.

**Gate 13:** coverage manifest signed off; no discovered Runtime identity file skipped.

---

## Phase 14 — Legacy removal / contract completion

Only after all new reads/writes are authoritative:

- [ ] stop writing legacy `drivers`.
- [ ] remove legacy `Driver` ORM model from current Runtime code.
- [ ] remove direct Runtime `is_admin` reads/writes.
- [ ] remove `get_current_admin`.
- [ ] remove authorization dependence on JWT `role = Admin|Inventory|Driver`.
- [ ] remove old `/driver/login` contract.
- [ ] remove legacy Dashboard `is_admin` response/state.
- [ ] remove legacy Dashboard `driver_id` Backoffice identity key.
- [ ] remove legacy Flutter `driver_id` identity key/contract.
- [ ] rename remaining field-domain `driver_id` columns/contracts to representative terminology where correct.
- [ ] re-home every legacy FK.
- [ ] drop `drivers.is_admin`.
- [ ] drop legacy `drivers` table only after FK inventory proves zero current dependency.
- [ ] drop temporary migration columns/tables/maps.
- [ ] keep historical Alembic migrations/evidence immutable; acceptance is zero current Runtime dependency.

**Gate 14:** no unintended compatibility shim remains.

---

## Phase 15 — Focused acceptance and regression gates

Analysis determines fixes; tests prove them. Do not use repeated broad suites to discover design.

### Database/migration

- [ ] upgrade from current pre-migration schema with representative data.
- [ ] fresh database `alembic upgrade head`.
- [ ] `alembic check` no drift.
- [ ] new RLS/policies/constraints present.
- [ ] zero orphan principal/profile/FK rows.
- [ ] password hashes unchanged.
- [ ] owner invariant valid.
- [ ] migration aborts on unresolved dual-use or owner ambiguity.

### Authentication/channel separation

- [ ] Owner Dashboard login succeeds.
- [ ] restricted Backoffice Dashboard login succeeds when allowed.
- [ ] Field Representative Dashboard login fails.
- [ ] Field Representative Flutter login succeeds.
- [ ] Backoffice-only Flutter login fails.
- [ ] inactive principal cannot login/refresh.
- [ ] cross-company mismatch fails closed.
- [ ] refresh cannot switch channel.
- [ ] forged `is_admin`/role-like claims provide no privilege.

### Capabilities/scopes

- [ ] owner has full company authority.
- [ ] user with capability succeeds.
- [ ] revoked capability fails.
- [ ] missing capability fails direct API access.
- [ ] allowed warehouse succeeds.
- [ ] unauthorized warehouse fails.
- [ ] cross-location operation validates all affected locations.
- [ ] Field Representative cannot enter Backoffice role/location APIs.

### Field workflow

- [ ] representative route assignment works.
- [ ] route requires active representative.
- [ ] work session works.
- [ ] visit ownership uses representative identity.
- [ ] shop field creation attribution remains correct.
- [ ] vehicle/source warehouse custody semantics unchanged.

### Audit/idempotency

- [ ] audit rows resolve correct principal.
- [ ] migrated historical actor references resolve.
- [ ] idempotency replay binds correct principal.
- [ ] same request id with different actor/input still fails closed.

### Frontends

- [ ] Dashboard TypeScript/focused tests/build.
- [ ] Flutter analyze + focused auth/session tests.
- [ ] Dashboard owner + restricted-user browser acceptance.
- [ ] Flutter field login -> route/work-session acceptance.

### Performance

- [ ] no N+1 capability resolution.
- [ ] authorization indexes exist.
- [ ] owner/capability checks are request-efficient.
- [ ] no per-row authorization query loop.

**Gate 15:** one consolidated risk-appropriate acceptance passes.

---

## Phase 16 — Final source audit

- [ ] Runtime direct `is_admin` authorization/classification references = **0**.
- [ ] Runtime `get_current_admin` references = **0**.
- [ ] Runtime auth no longer uses generic legacy `Driver` as company principal.
- [ ] Dispatch no longer identifies representatives by `is_admin = false`.
- [ ] Dashboard does not receive/use `is_admin` as authority.
- [ ] Flutter does not depend on ambiguous `driver_id` login identity.
- [ ] all legacy `drivers` FKs migrated/eliminated.
- [ ] no new feature checks a role name as authorization logic.
- [ ] no Branch dependency introduced into principal/representative/vehicle identity.
- [ ] no temporary migration compatibility object remains.

Historical migrations/performance snapshots may still contain old text; they are not current authority and must not be rewritten merely for grep cleanliness.

---

## Phase 17 — Documentation, RUN, and stability merge

- [ ] Update `ARCHITECTURE.md` if implementation refines the canonical identity model without weakening it.
- [ ] Update `RUN.txt` with completed Identity/Authorization foundation checkpoint.
- [ ] Mark this plan accurately `[x]`.
- [ ] Record final Alembic revision(s).
- [ ] Record final focused acceptance evidence.
- [ ] Review full diff: migrations, deleted legacy code, permissions, tenant/location isolation, Dashboard/Flutter contracts.
- [ ] Merge only at stability point.
- [ ] Delete task branch after merge.
- [ ] Start Representatives/Vehicles implementation plan only after this foundation is stable.

---

# Side effects and risk statement

## Database impact

This work **does change the database schema** because the current schema uses `drivers` as credential identity, representative identity, and generic actor authority.

Expected schema impact:

- new principal/profile/ownership tables;
- role/location-grant FK changes;
- refresh-token FK change;
- audit/idempotency actor FK changes;
- field-business FK changes;
- final removal of legacy `is_admin` and `drivers` only after cutover.

It must **not** change:

- product identity;
- physical inventory quantities;
- warehouse balances;
- batch/expiry truth;
- price values/publication history;
- sales/return amounts;
- route/visit business history except identity FK target/name normalization;
- company IDs.

## Intentional user-visible side effect

Legacy sessions/refresh tokens may require a **one-time login again** at cutover if safe token migration is not possible. This is preferable to accepting legacy cross-channel tokens.

## Main failure risks

- confusing an audit actor with a field representative;
- silently classifying a dual-use legacy row;
- choosing Company Owner arbitrarily;
- hiding `is_admin` inside a helper instead of removing the model;
- granting Dashboard roles to field principal;
- breaking exact-location authorization;
- leaving Flutter on `/driver/login`/`driver_id`;
- losing historical actor FK integrity;
- introducing N+1 authorization queries.

---

# Definition of DONE

- [ ] Backoffice and Field Representative are separate domain profiles/access channels.
- [ ] Company Owner is explicit and protected.
- [ ] authorization is capability + scope based.
- [ ] direct Runtime `is_admin` authority/classification is gone.
- [ ] `get_current_admin` is gone.
- [ ] `Driver.is_admin == false` is not used to discover representatives.
- [ ] all current legacy `drivers` FKs have correct target authority.
- [ ] Dashboard and Flutter contracts use unambiguous identities.
- [ ] tenant and exact-location isolation still fail closed.
- [ ] audit/idempotency history remains valid.
- [ ] clean bootstrap and upgrade migrations pass.
- [ ] focused Dashboard + Flutter + backend acceptance passes.
- [ ] migration compatibility code/schema is removed.
- [ ] plan is fully marked `[x]`, merged to `main`, and recorded as a stability checkpoint.
