# Identity Phase 1 — Exhaustive Semantic Inventory

**Repository:** `MohHamdallah1/wanasah`
**Task branch:** `codex/is-admin-semantic-inventory`
**Date:** 2026-10-10 (Asia/Amman)
**Source baseline:** `31f3ac64f68a0bb6a43c87475654bd3a85276d5f` (`origin/main`, fetched before writing). Initial inspection began at `d0a15d770bbdac553d4f69a813ccd2761dfd8a48`; main then gained only `IDENTITY_PHASE0_BASELINE.md`. The clean task branch was fast-forwarded to that newer checkpoint; no Runtime source changed.
**Authority:** Evidence and proposed mapping only. This is NOT an approved architecture, capability catalog, migration mapping, or permission to begin Phase 2.
**Allowed write:** this file only. No Runtime/schema/migration/workflow changes, application imports/startup, database queries, tests, merge, or main changes.

## 1. Scope, method and limits

This analysis unblocks frozen V1 §5.1 **company setup → users/access/authentication/session**, with its required Dispatch/Flutter and exact-location inventory isolation consumers (§5.3–5.5). It inventories existing Runtime, including enabled backend foundations whose UI is deferred; it does not promote those foundations into V1.

The original checkout had owner changes in RUN.txt, editor settings, generated Flutter registrants and an untracked image. They were not reset, stashed, overwritten or committed. Analysis/writing took place in a clean task worktree. Phase 0's database/bootstrap/test/backup gates remain open as documented there; none is claimed passed here.

Source universe: Git-tracked Python, TS/TSX, JS/JSX, Dart, SQL, PowerShell, shell and YAML. Backend Runtime means wa_backend Python excluding tests/, scripts/, perf_reports/, alembic/, seed_dev.py and bootstrap_platform_admin.py. Dashboard Runtime means dashboard/src excluding test directories and *.test.* / *.spec.*. Flutter Runtime is wanasah_frontend/lib. Local tooling/locust helpers remain in the backend source census but are identified by their evidence rather than treated as mounted APIs. Historical snapshots/scripts/tests/seeds are retained separately as E. Markdown planning prose is not executable source and is not counted as a Runtime occurrence.

Counts distinguish **matched lines**, **lexical token occurrences**, **files**, **function bodies**, and **HTTP method + full route registrations**. A line can have multiple is_admin tokens with different semantics; token ordinal is left-to-right. Imports, comments, declarations and query projections are retained, not silently removed to improve counts. Evidence source trailing whitespace is normalized for Markdown; tokens and line positions are unchanged. Identical route aliases are separate registrations, not separate implementations.

Python ast parsing and rg searches were read-only. No SQLAlchemy application modules were imported and no Alembic operation was executed. ForeignKeyConstraint with (company_id, actor_id) counts as ONE relationship, not two. All domain model files were included, then compared to upgrade-side migration declarations and Alembic's imported metadata owners.

The endpoint census follows direct references, Depends arguments, imported/local helper calls, InventoryAccess methods and module helper calls to the legacy leaves. It does not mistake variables named roles/locations/capabilities for calls to endpoint functions. Auth emitters and identity classification endpoints are included even where is_admin is not a permission gate. Shared helpers are tracked explicitly below. Product Import websocket uses require_admin=False; its admin condition is dormant, but InventoryAccess remains an active legacy dependency.

**Static evidence is not live database preflight or proof of security acceptance.** No actual owner candidate, dual-use row, orphan, existing grant, expired token, or history remapping can be classified from source alone. No inference depending on an unresolved decision is made.

## Final counts (explicit reproducible units)

| Census / pattern | Area | Matched lines | Token occurrences | Files |
|---|---|---|---|---|
| is_admin exact | wa_backend/ Runtime | 45 | 52 | 17 |
| is_admin exact | dashboard/ Runtime | 6 | 7 | 2 |
| is_admin exact | wanasah_frontend/ Runtime | 0 | 0 | 0 |
| get_current_admin exact | wa_backend/ Runtime | 41 | 41 | 5 |
| get_current_admin exact | dashboard/ Runtime | 0 | 0 | 0 |
| get_current_admin exact | wanasah_frontend/ Runtime | 0 | 0 | 0 |
| Driver exact | wa_backend/ Runtime | 436 | 450 | 49 |
| Driver exact | dashboard/ Runtime | 5 | 5 | 4 |
| Driver exact | wanasah_frontend/ Runtime | 0 | 0 | 0 |
| driver_id exact | wa_backend/ Runtime | 300 | 396 | 19 |
| driver_id exact | dashboard/ Runtime | 39 | 41 | 26 |
| driver_id exact | wanasah_frontend/ Runtime | 9 | 9 | 2 |
| Driver or driver_id exact | wa_backend/ Runtime | 729 | 846 | 52 |
| Driver or driver_id exact | dashboard/ Runtime | 44 | 46 | 30 |
| Driver or driver_id exact | wanasah_frontend/ Runtime | 9 | 9 | 2 |
| /driver/login literal | wa_backend/ Runtime | 1 | 1 | 1 |
| /driver/login literal | dashboard/ Runtime | 0 | 0 | 0 |
| /driver/login literal | wanasah_frontend/ Runtime | 2 | 2 | 2 |
| Driver/driver_id substring (includes compound contracts) | wa_backend/ Runtime | 799 | 949 | 52 |
| Driver/driver_id substring (includes compound contracts) | dashboard/ Runtime | 139 | 163 | 38 |
| Driver/driver_id substring (includes compound contracts) | wanasah_frontend/ Runtime | 14 | 17 | 3 |
| Flutter field identity broad | wanasah_frontend/ Runtime | 62 | 89 | 10 |
| Flutter compound identity union | wanasah_frontend/ Runtime | 64 | 99 | 10 |
| Dashboard authority/identity broad | dashboard/ Runtime | 349 | 380 | 81 |
| Dashboard compound identity/authority union | dashboard/ Runtime | 440 | 502 | 90 |
| is_admin exact | tracked executable-source, Runtime + artifacts | 161 | 174 | 85 |
| get_current_admin exact | tracked executable-source, Runtime + artifacts | 43 | 43 | 6 |
| Dashboard driver_id / is_admin / derived contracts | tracked executable-source, Runtime + artifacts | 408 | 444 | 104 |

Taxonomy lexical totals (all executable-source corpora): A=16, B=10, C=11, D=21, E=116; total=174; unclassified=0.

Runtime source taxonomy: A=16, B=10, C=11, D=21, E=1; total=59. E here is one explanatory docstring token; executable/contract Runtime tokens excluding it=58.

Backend combined exact is_admin/get_current_admin census: matched-line union=86; files=19.

Endpoint census: 237 affected registrations / 31 owner files; 48 direct flag/admin-dependent registrations; 36 get_current_admin dependency registrations; 189 additional helper-dependent registrations; 0 unrecorded in this census. FK census: 55 relationships / 36 tables / 5 model files; 45 PRINCIPAL_ACTOR, 5 FIELD_REPRESENTATIVE, 2 BACKOFFICE_USER, 3 AMBIGUOUS; 0 unclassified.

## 2. Current identity and authorization semantics

| Authority / consumer | Current meaning and evidence | Consequence for Phase 1 |
|---|---|---|
| Driver | wa_backend/models.py:215–239 combines company credential, username/password, active flag, is_admin, and field debt policy. Unique company+username and company+id. | Shared generic human principal AND representative; do not blindly rename all Driver references to FieldRepresentative. |
| /driver/login | api/auth.py:89, :112, :126–140 queries any active tenant Driver; role=Driver regardless of persisted is_admin; returns driver_id and is_admin. | Backoffice row can take the field login path; no explicit field profile/channel check. No behavior changed. |
| /login | api/auth.py:144, :177–198 same credential table; InventoryAccess.allows(PERMISSIONS, any_location=True) admits any grant or full is_admin shortcut. role=Admin if flag else Inventory. | Membership in any permitted capability can admit a non-admin shared Driver; identity type is not enforced here. |
| Access JWT | api/auth.py:37–48: sub=Driver.id, company_id, type=access, role, jti, exp; callers also emit username/is_admin. | Claims are coarse transport semantics, not persisted capability authority. |
| HTTP identity resolver | api/dependencies.py:13–114 verifies HS256/exp and token_identity.py:15–19 requires access type and canonical positive subject/company ids; checks blacklist, persisted Driver/company, active Driver and tenant context. | Does NOT consult JWT role/is_admin for HTTP authority. Forged flag/role is not the get_current_admin decision. HTTP dependency itself does not reload active Company; login/refresh do. |
| Admin gate | api/dependencies.py:126–130 tests persisted current_driver.is_admin; 403 for non-admin. | 41 exact source hits = 1 definition + 4 imports + 36 endpoint dependencies; exact matrix below. |
| Owned-driver helper | api/dependencies.py:119–123 allows same id OR persisted is_admin. | No mounted Runtime caller found. Retain as an unconsumed Runtime authorization helper, not an endpoint omission. |
| InventoryAccess | inventory_access.py:64–166 resolves UserRole company grants and UserLocationAccess exact grants; PERMISSIONS has 55 codes; COMPANY_ONLY excludes location grants for specific capabilities. is_admin returns true/all codes and skips reads. | Full-company-authority behavior B; preserve tenant scoping separately. Owner authority cannot be inferred from the legacy flag. |
| Dispatch scope | dispatch_access.py:7–51 uses stored route source_location_id AND vehicle custody-location authority for restricted actors. is_admin bypasses filters / vehicle checks / missing route endpoints. | B; preserving exact-location structural checks vs privileged historical-route compatibility is AD10, not a decision made here. |
| Dashboard | Login.tsx consumes is_admin/dashboard_access, stores driver_id; useInventoryAccess.ts validates driver_id and consumes is_company_admin derived from persisted is_admin. | driver_id here is authenticated principal, not route representative. is_company_admin is an additional derived legacy authority contract, not a separate owner relation. |
| Flutter | AuthBloc consumes/persists driver_id, emits driverId state; events/screens/repository propagate it; break offline payload stores driver_id. HTTP field operations often obtain current_driver.id server-side. | Field identity contract currently uses the same credential id; camelCase/state/queue consumers must be audited too. |
| Platform | api/platform_manager.py:27–59 uses PlatformAdmin, type=platform_access and is_platform_admin; :176–227 provisions tenant Driver(is_admin=True). role=GodMode / response PlatformAdmin is a separate realm. | Tenant Company Owner must never replace platform authorization. Tenant provisioning's flag is full-authority initialization, not a proven explicit Owner. |

### 2.1 RefreshToken, logout and revocation

RefreshToken (models.py:2388–2411) has a **single-column driver_id → drivers.id CASCADE FK**, no company_id column, plus replacement self-FK, revoked flag, expiry and created_at. Both login paths persist credential Driver.id. This is PRINCIPAL_ACTOR/authentication identity, not representative assignment.

api/auth.py:238–353 verifies signed exp/type=refresh, derives sub/company, sets tenant context, locks by exact stored token, reloads active Driver and Company and checks Driver.company_id. It does not explicitly compare db_token.driver_id to decoded sub, nor successor.driver_id to the requested actor. _recent_rotation_successor looks up stored replacement id; 15-second grace replays the successor refresh with a newly issued access token. _refresh_role accepts signed Admin/Inventory/Driver values, otherwise derives Admin/Driver from persisted is_admin. No persisted access-channel field binds rotation, and role-like strings do not prove target profile type.

These are source facts, not an exploit claim or an authorized fix. Safe legacy-token conversion vs one-time invalidation and binding invariants remain AD09. Do not create new sessions from a guessed channel.

Logout (auth.py:367 onward) blacklists the supplied access-token string after structural decode, and deletes an exact X-Refresh-Token when supplied; TokenBlacklist has no drivers FK. No identity migration conclusion may reinterpret a blacklisted token as another person.

### 2.2 UserRole and UserLocationAccess

models.py:116–145: UserRole(company_id, driver_id, role_id) is company-wide; UserLocationAccess adds exact location_id. Both use tenant-safe composite Driver FKs and logical unique constraints. InventoryAccess uses the same actor.id for both, always with company_id. Field route membership, branch membership, names and selected UI state do not supply grants.

inventory_permissions.py:146–217 lists ALL Drivers and validates target existence by company/id only. Current grants can therefore name a field-looking Driver. **BACKOFFICE_USER** is the source-backed target semantic classification under the frozen plan Phase 6, not a claim that current data or constraints already enforce Backoffice type. Historical memberships still require Phase 3 preflight. System-role edit rejection exists; explicit primary Company Owner protection does not exist here.

### 2.3 Audit, idempotency and asynchronous actors

- SystemAuditLog.admin_id and DomainAuditEvent.actor_user_id record who performed an operation, including field actions. Literal Driver_N targets and JSON old/new values are additional historical identity contracts even when not FKs. product_lifecycle.py:324 record_domain_event and services.py:759, :1106, :1231 attribute actor_id.
- OperationIdempotency.created_by is PRINCIPAL_ACTOR. services.py:2852–2949 keys by company + operation + canonical request UUID, locks that key, rejects a different created_by or request_hash and returns a stored completed response only. Same request id must not acquire a different principal after remapping.
- InventoryMovement.performed_by is generic actor across field sale/return and Backoffice inbound/transfers/corrections; it is not necessarily the representative owning a session. See services.py:4195 and api/driver.py:1777, :2865, :3095.
- Import jobs retain created_by; execution_service.py:649–675 reloads the active actor using job.created_by and rechecks catalog.manage + catalog.publish + pricing.manage in each execution transaction through require_all. queue/recovery/worker evidence remains tenant-bound. Do not substitute a representative id into these jobs.
- Workers, audit payloads, cache/storage identity suffixes and response fields require principal mapping even without a direct drivers FK. Their exact Runtime source hits are retained in the appendix.

### 2.4 Dispatch, inventory and pricing actors

WorkSession.driver_id, DispatchRoute.driver_id, Visit.driver_id and ShortageRequest.driver_id identify the field representative who owns assigned work, sessions, visits and shortage requests. Dispatch representative discovery/validation uses is_admin=False in seven sites; changing the flag to a permission would not preserve that identity meaning.

DispatchLoadPlanLine has **updated_by as a principal actor FK**, not a direct representative FK; representative assignment is reached through DispatchRoute. Do not re-home its editor attribution to FieldRepresentative because the owning module is Dispatch.

InventoryTransferHeader.expected_receiver_id is FIELD_REPRESENTATIVE: models.py handshake constraints require work_session_id/expected_receiver_id for HANDSHAKE and require expected_receiver_id NULL outside HANDSHAKE; dispatch.py:2228 binds route.driver_id, driver.py:2743, :3190 bind field caller, dispatch_reservations.py:62, :134 joins stored route.driver_id to expected_receiver_id. dispatched_by / received_by / cancelled_by are PRINCIPAL_ACTOR: warehouse transit records Backoffice callers, field handshake records representative callers. These are actual action actors. Separation-of-duties remains a workflow invariant, not an Owner bypass.

Stocktake started/approved/cancelled/recount-authorizer/count/discovery fields are PRINCIPAL_ACTOR. stocktake.py:1922, :1947 uses current actor for discoveries/counts; :2350 onward resolves another credentialed recount authorizer with exact stocktake.recount authority; services.py:4365, :4510–4522 permits owning representative to open VEHICLE_RECON. Username/password confirmation does not make a counter a field representative or imply primary Owner. Generic actor semantics are established; delegated supervisor policy is separately AMBIGUOUS (AD02).

Pricing DriverDisplayPrice / LegacyDriverPrice / DriverSale* names describe the field price/display compatibility contract, not credential principals or admin actors. driver_authority.py:373 binds session.driver_id to stored route; PriceBook/Publication/Assignment created_by/approved_by remain principal attribution. PriceBookAssignment.scope_id is polymorphic CUSTOMER/BRANCH/COMPANY_DEFAULT scope evidence, NOT a drivers FK (models.py:1542–1547; pricing/publishing.py:39–42, :1547). There is no active DRIVER assignment scope. RouteCommercialContext links dispatch_route_id and immutable commercial revision/context fields (models.py:1620 onward); it has no direct Driver FK and no driver_business_snapshot column. Field identity is reached through route/session ownership.

Shop.added_by_driver_id and both InventoryDamageEvent actor-looking fields are AMBIGUOUS; exact reasons are in the FK table and AD06/AD07.

## 3. is_admin taxonomy

Every lexical executable-source occurrence receives exactly one category. Mixed lines have one row per token. A = authorization gate (including source-supported projections used by a selective gate), B = Owner/full-authority behavior (legacy behavior only), C = identity classification/declaration, D = presentation/response/JWT transport field, E = test/fixture/historical/explanatory artifact. An occurrence marked B does not establish that the row is the canonical Company Owner.

| File:line#token ordinal | Category | Corpus | Semantic evidence | Exact source line |
|---|---|---|---|---|
| dashboard/src/pages/Login.tsx:25#1 | D | Runtime source | Login response field or UI navigation; not backend authorization. | `is_admin: boolean;` |
| dashboard/src/pages/Login.tsx:100#1 | A | Runtime source | UI Dashboard admission; backend remains authority. | `if (!data.is_admin && data.dashboard_access !== true) {` |
| dashboard/src/pages/Login.tsx:131#1 | D | Runtime source | Login response field or UI navigation; not backend authorization. | `navigate(data.is_admin ? '/' : '/inventory');` |
| dashboard/src/pages/inventory/TabInventoryAccess.tsx:9#1 | D | Runtime source | Shared user flag parsing/type/full-authority label. | `interface User { id: number; full_name: string; is_admin: boolean; is_active: boolean }` |
| dashboard/src/pages/inventory/TabInventoryAccess.tsx:100#1 | D | Runtime source | Shared user flag parsing/type/full-authority label. | `is_admin: asBoolean(row.is_admin),` |
| dashboard/src/pages/inventory/TabInventoryAccess.tsx:100#2 | D | Runtime source | Shared user flag parsing/type/full-authority label. | `is_admin: asBoolean(row.is_admin),` |
| dashboard/src/pages/inventory/TabInventoryAccess.tsx:256#1 | D | Runtime source | Shared user flag parsing/type/full-authority label. | `<option value="">اختر المستخدم</option>{users.data?.items.map(user=><option key={user.id} value={user.id}>{user.full_name}{user.is_admin?' — Admin كامل الصلاحيات':''}{!user.is_active?' — موقوف':''}</option>)}` |
| wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:105#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `sa.Column('is_admin', sa.Boolean(), server_default='false', nullable=False),` |
| wa_backend/api/auth.py:126#1 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `access_token = create_access_token({"sub": str(driver.id), "is_admin": driver.is_admin, "username": driver.username}, company_id=comp_id, role_name="Driver")` |
| wa_backend/api/auth.py:126#2 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `access_token = create_access_token({"sub": str(driver.id), "is_admin": driver.is_admin, "username": driver.username}, company_id=comp_id, role_name="Driver")` |
| wa_backend/api/auth.py:138#1 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `"is_admin": driver.is_admin,` |
| wa_backend/api/auth.py:138#2 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `"is_admin": driver.is_admin,` |
| wa_backend/api/auth.py:184#1 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `access_token = create_access_token({"sub": str(admin.id), "is_admin": admin.is_admin, "username": admin.username}, company_id=comp_id, role_name="Admin" if admin.is_admin else "Inventory")` |
| wa_backend/api/auth.py:184#2 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `access_token = create_access_token({"sub": str(admin.id), "is_admin": admin.is_admin, "username": admin.username}, company_id=comp_id, role_name="Admin" if admin.is_admin else "Inventory")` |
| wa_backend/api/auth.py:184#3 | C | Runtime source | Legacy Admin/Inventory/Driver token-role classification; not persisted capability authority. | `access_token = create_access_token({"sub": str(admin.id), "is_admin": admin.is_admin, "username": admin.username}, company_id=comp_id, role_name="Admin" if admin.is_admin else "Inventory")` |
| wa_backend/api/auth.py:185#1 | C | Runtime source | Legacy Admin/Inventory/Driver token-role classification; not persisted capability authority. | `refresh_token = create_refresh_token({"sub": str(admin.id), "role": "Admin" if admin.is_admin else "Inventory"}, company_id=comp_id)` |
| wa_backend/api/auth.py:196#1 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `"is_admin": admin.is_admin,` |
| wa_backend/api/auth.py:196#2 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `"is_admin": admin.is_admin,` |
| wa_backend/api/auth.py:206#1 | C | Runtime source | Legacy Admin/Inventory/Driver token-role classification; not persisted capability authority. | `return "Admin" if driver.is_admin else "Driver"` |
| wa_backend/api/auth.py:313#1 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `"is_admin": driver.is_admin,` |
| wa_backend/api/auth.py:313#2 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `"is_admin": driver.is_admin,` |
| wa_backend/api/auth.py:328#1 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `"is_admin": driver.is_admin,` |
| wa_backend/api/auth.py:328#2 | D | Runtime source | JWT/login response key or value; HTTP privilege resolver does not trust this claim. | `"is_admin": driver.is_admin,` |
| wa_backend/api/dependencies.py:121#1 | A | Runtime source | Persisted admin or cross-owner access gate. | `if current_driver.id != driver_id and not current_driver.is_admin:` |
| wa_backend/api/dependencies.py:127#1 | E | Runtime source | Explanatory docstring only; non-executable. | `"""حارس البوابة: يمنع دخول أي شخص لا يملك صلاحيات (is_admin) لمسارات الإدارة"""` |
| wa_backend/api/dependencies.py:128#1 | A | Runtime source | Persisted admin or cross-owner access gate. | `if not current_driver.is_admin:` |
| wa_backend/api/dispatch.py:1070#1 | C | Runtime source | Representative discovery/validation inferred from persisted non-admin flag. | `select(Driver).filter_by(company_id=company_id, is_active=True, is_admin=False).order_by(Driver.id.asc())` |
| wa_backend/api/dispatch.py:1391#1 | C | Runtime source | Representative discovery/validation inferred from persisted non-admin flag. | `is_admin=False,` |
| wa_backend/api/dispatch.py:3710#1 | C | Runtime source | Representative discovery/validation inferred from persisted non-admin flag. | `if driver is None or not driver.is_active or driver.is_admin:` |
| wa_backend/api/dispatch.py:3759#1 | C | Runtime source | Representative discovery/validation inferred from persisted non-admin flag. | `or target_driver.is_admin` |
| wa_backend/api/dispatch.py:4300#1 | C | Runtime source | Representative discovery/validation inferred from persisted non-admin flag. | `is_admin=False,` |
| wa_backend/api/dispatch.py:4916#1 | C | Runtime source | Representative discovery/validation inferred from persisted non-admin flag. | `valid = {int(d.id) for d in drivers if d.is_active and not d.is_admin}` |
| wa_backend/api/dispatch.py:5011#1 | C | Runtime source | Representative discovery/validation inferred from persisted non-admin flag. | `Driver.is_admin.is_(False),` |
| wa_backend/api/driver.py:3746#1 | A | Runtime source | Visit ownership exception for persisted admin. | `if not current_driver.is_admin and visit.driver_id != current_driver.id:` |
| wa_backend/api/inventory_permissions.py:44#1 | D | Runtime source | Response/projection of admin flag for capability/UI contract. | `'is_company_admin': actor.is_admin, 'location_id': location_id,` |
| wa_backend/api/inventory_permissions.py:148#1 | D | Runtime source | Response/projection of admin flag for capability/UI contract. | `rows = (await db.execute(select(Driver.id, Driver.full_name, Driver.is_active, Driver.is_admin).where(` |
| wa_backend/api/inventory_stock_policy.py:242#1 | A | Runtime source | Legacy minimum-stock supervisor gate beyond inventory.read. | `if not bool(current_admin.is_admin):` |
| wa_backend/api/inventory_stock_policy.py:680#1 | A | Runtime source | Legacy minimum-stock supervisor gate beyond inventory.read. | `if not bool(current_admin.is_admin):` |
| wa_backend/api/platform_manager.py:227#1 | B | Runtime source | Provisioning initializes tenant full authority; does not prove primary Owner identity. | `is_admin=True,` |
| wa_backend/api/warehouse/live_stock.py:230#1 | B | Runtime source | Full-authority shortcut before restricted warehouse checks. | `if bool(actor.is_admin):` |
| wa_backend/api/warehouse/stocktake.py:2038#1 | A | Runtime source | Additional supervisor gate after exact-location stocktake capability. | `if not current_admin.is_admin:` |
| wa_backend/api/warehouse/stocktake.py:2429#1 | A | Runtime source | Additional supervisor gate after exact-location stocktake capability. | `if not current_admin.is_admin:` |
| wa_backend/dispatch_access.py:8#1 | B | Runtime source | Legacy full-company permission/scope shortcut; not explicit Company Owner relation. | `if access.actor.is_admin:` |
| wa_backend/dispatch_access.py:20#1 | B | Runtime source | Legacy full-company permission/scope shortcut; not explicit Company Owner relation. | `if access.actor.is_admin:` |
| wa_backend/dispatch_access.py:27#1 | B | Runtime source | Legacy full-company permission/scope shortcut; not explicit Company Owner relation. | `if access.actor.is_admin:` |
| wa_backend/dispatch_access.py:44#1 | B | Runtime source | Legacy full-company permission/scope shortcut; not explicit Company Owner relation. | `if access.actor.is_admin:` |
| wa_backend/domains/dispatch_archive_navigation.py:44#1 | A | Runtime source | Privilege-gated archive navigation; target permissions/scope remain AD03. | `if samples.get("OPEN_SHORTAGE") and access.actor.is_admin:` |
| wa_backend/domains/operations_archive_navigation.py:12#1 | A | Runtime source | Privilege-gated archive navigation; target permissions/scope remain AD03. | `if not actor.is_admin or not samples.get("OPEN_CUSTODY"):` |
| wa_backend/inventory_access.py:87#1 | B | Runtime source | Legacy full-company permission/scope shortcut; not explicit Company Owner relation. | `if self.actor.is_admin:` |
| wa_backend/inventory_access.py:118#1 | B | Runtime source | Legacy full-company permission/scope shortcut; not explicit Company Owner relation. | `if self.actor.is_admin:` |
| wa_backend/inventory_access.py:124#1 | B | Runtime source | Legacy full-company permission/scope shortcut; not explicit Company Owner relation. | `if self.actor.is_admin:` |
| wa_backend/inventory_access.py:155#1 | B | Runtime source | Legacy full-company permission/scope shortcut; not explicit Company Owner relation. | `if visible and not self.actor.is_admin:` |
| wa_backend/models.py:228#1 | C | Runtime source | Legacy identity flag schema declaration; no independent capability/owner model. | `is_admin      = Column(Boolean,     nullable=False, default=False, server_default='false')` |
| wa_backend/perf_reports/phase11_baseline_warehouse.py:9383#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `if not current_admin.is_admin:` |
| wa_backend/perf_reports/phase11_baseline_warehouse.py:9765#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `if not current_admin.is_admin:` |
| wa_backend/perf_reports/phase1_baseline/schemas.py:322#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin: bool` |
| wa_backend/perf_reports/phase1_baseline/warehouse.py:9336#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `if not current_admin.is_admin:` |
| wa_backend/perf_reports/phase1_baseline/warehouse.py:9718#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `if not current_admin.is_admin:` |
| wa_backend/realtime/auth.py:64#1 | A | Runtime source | Conditional persisted admin websocket gate; user wrapper disables it explicitly. | `and not bool(driver.is_admin)` |
| wa_backend/schemas.py:323#1 | D | Runtime source | LoginResponse presentation schema. | `is_admin: bool` |
| wa_backend/scripts/b37_family_race_disposable.py:62#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.company_id==2,Driver.is_admin.is_(True),` |
| wa_backend/scripts/b38_profile_real_import_disposable.py:184#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.company_id==ACTOR_COMPANY,Driver.is_admin.is_(True),` |
| wa_backend/scripts/b3_profile_catalog_service.py:147#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `actor=await db.scalar(select(Driver).where(Driver.company_id==2,Driver.is_admin.is_(True)))` |
| wa_backend/scripts/diagnose_stage823_uvicorn_layers.py:76#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_admin": bool(driver.is_admin),` |
| wa_backend/scripts/diagnose_stage823_uvicorn_layers.py:76#2 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_admin": bool(driver.is_admin),` |
| wa_backend/scripts/diagnose_stage823_uvicorn_layers.py:80#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `role_name="Admin" if driver.is_admin else "Inventory",` |
| wa_backend/scripts/gate_auth_session_refresh.py:50#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `'{"sub": str(admin.id), "role": "Admin" if admin.is_admin else "Inventory"}'` |
| wa_backend/scripts/gate_auth_session_refresh_runtime.py:75#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `full_name, is_active, is_admin,` |
| wa_backend/scripts/gate_inventory_batches_roundtrip.py:212#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `stmt.order_by(Driver.is_admin.desc(), Driver.id.asc()).limit(1)` |
| wa_backend/scripts/gate_inventory_batches_roundtrip.py:511#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=False,` |
| wa_backend/scripts/gate_inventory_expiry_semantics.py:82#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=True,` |
| wa_backend/scripts/gate_live_stock_minimum_policy.py:43#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"if not bool(current_admin.is_admin):" in api` |
| wa_backend/scripts/gate_live_stock_phase11.py:84#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `admin = await add(Driver, company_id=cid, username=tag, full_name=tag, password_hash="not-a-login", is_admin=True)` |
| wa_backend/scripts/gate_live_stock_phase11.py:85#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `actor = await add(Driver, company_id=cid, username=tag+"R", full_name=tag, password_hash="not-a-login", is_admin=False)` |
| wa_backend/scripts/gate_live_stock_scale.py:508#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.is_admin.is_(True),` |
| wa_backend/scripts/gate_live_stock_scale.py:636#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_admin": bool(driver.is_admin),` |
| wa_backend/scripts/gate_live_stock_scale.py:636#2 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_admin": bool(driver.is_admin),` |
| wa_backend/scripts/gate_live_stock_scale.py:640#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `role_name="Admin" if driver.is_admin else "Inventory",` |
| wa_backend/scripts/gate_live_stock_scale_v2.py:369#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_admin": bool(driver.is_admin),` |
| wa_backend/scripts/gate_live_stock_scale_v2.py:369#2 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_admin": bool(driver.is_admin),` |
| wa_backend/scripts/gate_live_stock_scale_v2.py:373#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `role_name="Admin" if driver.is_admin else "Inventory",` |
| wa_backend/scripts/gate_product_tracking_runtime.py:377#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_admin, created_at) "` |
| wa_backend/scripts/gate_products_p8_concurrency_idempotency.py:107#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"full_name, is_active, is_admin, created_at) "` |
| wa_backend/scripts/gate_products_p8_isolation.py:162#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"full_name, is_active, is_admin, "` |
| wa_backend/scripts/gate_products_p8_isolation.py:311#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"full_name, is_active, is_admin, "` |
| wa_backend/scripts/gate_products_p8_price_publication_scale.py:139#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"full_name, is_active, is_admin, created_at) "` |
| wa_backend/scripts/gate_products_p9_family_reassignment.py:160#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"full_name, is_active, is_admin, created_at) "` |
| wa_backend/scripts/gate_products_p9_rename.py:159#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"full_name, is_active, is_admin, created_at) "` |
| wa_backend/scripts/gate_products_read_contract_p2.py:310#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"full_name, is_active, is_admin, "` |
| wa_backend/scripts/gate_stage3_lifecycle.py:132#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"INSERT INTO drivers (company_id, username, password_hash, full_name, phone_number, is_active, is_admin, created_at) "` |
| wa_backend/scripts/gate_stage4_batch_expiry.py:129#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"INSERT INTO drivers (company_id, username, password_hash, full_name, phone_number, is_active, is_admin, created_at) "` |
| wa_backend/scripts/gate_stage4_final.py:218#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin: bool,` |
| wa_backend/scripts/gate_stage4_final.py:228#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_active, is_admin, created_at) "` |
| wa_backend/scripts/gate_stage4_final.py:230#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"true, :is_admin, NOW()) RETURNING id"` |
| wa_backend/scripts/gate_stage4_final.py:236#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_admin": is_admin,` |
| wa_backend/scripts/gate_stage4_final.py:236#2 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_admin": is_admin,` |
| wa_backend/scripts/gate_stage4_final.py:955#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `su, company_a, is_admin=True, label="Dispatcher"` |
| wa_backend/scripts/gate_stage4_final.py:958#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `su, company_a, is_admin=True, label="Receiver"` |
| wa_backend/scripts/gate_stage4_final.py:1804#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `su, company_a, is_admin=True, label="A"` |
| wa_backend/scripts/gate_stage4_final.py:1831#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `su, company_b, is_admin=True, label="B"` |
| wa_backend/scripts/gate_stage4e2a_policy.py:163#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `" is_active, is_admin, created_at) "` |
| wa_backend/scripts/gate_stage5_commercial_pricing.py:318#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_active, is_admin, created_at) "` |
| wa_backend/scripts/gate_stage75_isolation_runtime.py:82#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"INSERT INTO drivers (company_id,username,password_hash,full_name,phone_number,is_active,is_admin,created_at) "` |
| wa_backend/scripts/gate_stage823_live_stock_read_model.py:87#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_active, is_admin, can_allow_debt,` |
| wa_backend/scripts/gate_stage823_live_stock_read_model.py:135#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_active, is_admin, can_allow_debt,` |
| wa_backend/scripts/gate_stage823_live_stock_read_model.py:475#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin: bool,` |
| wa_backend/scripts/gate_stage823_live_stock_read_model.py:484#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=bool(is_admin),` |
| wa_backend/scripts/gate_stage823_live_stock_read_model.py:484#2 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=bool(is_admin),` |
| wa_backend/scripts/gate_stage823_live_stock_read_model.py:603#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_admin": True,` |
| wa_backend/scripts/gate_stage823_live_stock_read_model.py:717#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=True,` |
| wa_backend/scripts/gate_stage823_live_stock_read_model.py:722#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=False,` |
| wa_backend/scripts/gate_stage823_live_stock_read_model_core.py:137#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `and item.attr == "is_admin"` |
| wa_backend/scripts/gate_stage823_live_stock_read_model_core.py:328#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"actor.is_admin",` |
| wa_backend/scripts/product_import_d1_business_matrix.py:76#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=False,is_active=True,` |
| wa_backend/scripts/product_import_d1_business_matrix.py:139#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.is_admin.is_(True),Driver.is_active.is_(True),` |
| wa_backend/scripts/product_import_d1_real_business_child.py:71#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.company_id==2,Driver.is_admin.is_(True),` |
| wa_backend/scripts/product_import_d1_real_business_child.py:119#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=False,is_active=True,` |
| wa_backend/scripts/product_import_d7_burst_child.py:127#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.is_active.is_(True),Driver.is_admin.is_(True),` |
| wa_backend/scripts/product_import_phase19_contention_child.py:201#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `token = create_access_token({"sub": str(actor), "is_admin": True}, company, "Admin")` |
| wa_backend/scripts/product_import_phase19_edge_isolated_child.py:154#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `token = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")` |
| wa_backend/scripts/product_import_phase19_http_cancel_stall_child.py:48#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `primary = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")` |
| wa_backend/scripts/product_import_phase19_http_cancel_stall_child.py:49#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `foreign = create_access_token({"sub": "2", "is_admin": True}, 3, "Admin")` |
| wa_backend/scripts/product_import_phase19_http_isolated_child.py:656#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `primary_token = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")` |
| wa_backend/scripts/product_import_phase19_http_isolated_child.py:657#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `foreign_token = create_access_token({"sub": "2", "is_admin": True}, 3, "Admin")` |
| wa_backend/scripts/product_import_phase19_http_isolated_child.py:659#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `# A forged is_admin claim cannot override the persisted permission gate.` |
| wa_backend/scripts/product_import_phase19_http_isolated_child.py:663#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"is_active,is_admin,can_allow_debt,max_debt_limit,created_at"` |
| wa_backend/scripts/product_import_phase19_http_isolated_child.py:669#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `{"sub": "3", "is_admin": True}, 2, "Admin",` |
| wa_backend/scripts/product_import_phase19_medium_isolated_child.py:210#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `token = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")` |
| wa_backend/scripts/product_import_phase19_real_browser_child.py:296#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `token = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")` |
| wa_backend/scripts/product_import_phase19_retention_retry_child.py:238#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `token = create_access_token({"sub":"1","is_admin":True},2,"Admin")` |
| wa_backend/scripts/product_import_phase19_worker_fault_child.py:319#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `primary = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")` |
| wa_backend/scripts/run_product_import_d32_isolated_gate.py:86#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_active,is_admin,can_allow_debt,max_debt_limit,created_at` |
| wa_backend/scripts/run_product_import_d32_isolated_gate.py:89#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_active,is_admin,can_allow_debt,max_debt_limit,created_at` |
| wa_backend/scripts/seed_live_stock_demo.py:242#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `.order_by(Driver.is_admin.desc(), Driver.id.asc())` |
| wa_backend/scripts/seed_live_stock_scale.py:103#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `ORDER BY is_admin DESC, id ASC` |
| wa_backend/scripts/test_e2e_stress_simulation.py:171#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=True,` |
| wa_backend/scripts/test_e2e_stress_simulation.py:245#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=False,` |
| wa_backend/scripts/test_stage4d_api.py:57#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `user=Driver(id=i,company_id=c,username=f'user{i}',full_name='Same name',is_admin=admin_flag)` |
| wa_backend/scripts/test_stage4d_api.py:204#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `assert response.json()['is_admin'] is (user==1)` |
| wa_backend/scripts/test_stage4d_postgres.py:127#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `access = InventoryAccess(db, SimpleNamespace(id=7, company_id=1, is_admin=False))` |
| wa_backend/scripts/test_stage4d_postgres.py:159#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `access = InventoryAccess(db, SimpleNamespace(id=8, company_id=1, is_admin=True))` |
| wa_backend/seed_dev.py:104#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=True,` |
| wa_backend/seed_dev.py:113#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `admin.is_admin = True` |
| wa_backend/services.py:4401#1 | A | Runtime source | Persisted actor flag projected/checked for owning-session reconciliation or supervisor-only posting. | `select(Driver.id, Driver.is_admin).filter_by(` |
| wa_backend/services.py:4430#1 | A | Runtime source | Persisted actor flag projected/checked for owning-session reconciliation or supervisor-only posting. | `if started_by != work_session.driver_id and not bool(actor.is_admin):` |
| wa_backend/services.py:4588#1 | A | Runtime source | Persisted actor flag projected/checked for owning-session reconciliation or supervisor-only posting. | `select(Driver.id, Driver.is_admin).filter_by(` |
| wa_backend/services.py:4610#1 | A | Runtime source | Persisted actor flag projected/checked for owning-session reconciliation or supervisor-only posting. | `if settled_by != work_session.driver_id and not bool(actor.is_admin):` |
| wa_backend/services.py:4788#1 | A | Runtime source | Persisted actor flag projected/checked for owning-session reconciliation or supervisor-only posting. | `is_admin=True,` |
| wa_backend/tests/test_archive_owner_navigation.py:105#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `return InventoryAccess(None, SimpleNamespace(company_id=company, id=17, is_admin=admin))` |
| wa_backend/tests/test_batch_reservation_owner_contract.py:203#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `return SimpleNamespace(company_id=company, id=17, is_admin=admin)` |
| wa_backend/tests/test_catalog_family_batch_b37_db.py:63#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.company_id==2,Driver.is_admin.is_(True)` |
| wa_backend/tests/test_committed_costed_inbound_race_c2_isolated.py:100#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"AND is_admin=true AND is_active=true LIMIT 1"` |
| wa_backend/tests/test_committed_costed_inbound_race_c2_isolated.py:105#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `id=int(actor_id), company_id=2, is_admin=True, is_active=True,` |
| wa_backend/tests/test_cost_policy_lock_contention_c2_db.py:55#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `text("SELECT id FROM drivers WHERE company_id=:c AND is_admin=true "` |
| wa_backend/tests/test_costed_driver_customer_return_c2_db.py:76#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.is_admin.is_(True),` |
| wa_backend/tests/test_costed_driver_sale_correction_real_c2_db.py:79#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.is_admin.is_(True),` |
| wa_backend/tests/test_costed_inbound_asgi_http_c2_db.py:65#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"AND is_admin=true AND is_active=true LIMIT 1"),` |
| wa_backend/tests/test_costed_inbound_asgi_http_c2_db.py:70#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `company_id=self.company_id, id=actor_id, is_admin=True, is_active=True,` |
| wa_backend/tests/test_costed_inbound_asgi_http_c2_db.py:191#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=False,` |
| wa_backend/tests/test_inventory_multi_location_authority.py:62#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `actor=SimpleNamespace(company_id=1, id=17, is_admin=False),` |
| wa_backend/tests/test_pricing_bulk_catalog_b3_db.py:56#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.company_id == 2, Driver.is_admin.is_(True)` |
| wa_backend/tests/test_product_batch_restrictions.py:82#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `return SimpleNamespace(company_id=company, id=driver, is_admin=admin)` |
| wa_backend/tests/test_simple_products_warehouse_filter.py:54#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `actor=SimpleNamespace(company_id=2, id=9, is_admin=False),` |
| wa_backend/tests/test_simple_products_warehouse_filter.py:86#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `actor=SimpleNamespace(company_id=2, id=9, is_admin=False),` |
| wa_backend/tests/test_supplier_master_db.py:80#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `actors = [Driver(company_id=c.id, username="gate", full_name="Gate admin", password_hash="synthetic", is_admin=True) for c in companies]` |
| wa_backend/tests/test_supplier_master_db.py:125#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `actor = SimpleNamespace(id=gate.actors[0].id, company_id=gate.companies[0].id, is_admin=True, is_active=True,` |
| wa_backend/tests/test_supplier_master_db.py:226#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `api.actor.is_admin = False` |
| wa_backend/tests/test_supplier_master_db.py:423#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `await api.db.commit(); api.actor.is_admin = False` |
| wa_backend/tests/test_warehouse_costed_inbound_c2_db.py:75#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"AND is_admin=true AND is_active=true ORDER BY id LIMIT 1"` |
| wa_backend/tests/test_warehouse_costed_inbound_c2_db.py:82#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=True, is_active=True,` |
| wa_backend/tests/test_warehouse_inbound_concurrent_recovery_c2_db.py:64#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `"SELECT id FROM drivers WHERE company_id=:c AND is_admin=true "` |
| wa_backend/tests/test_warehouse_inbound_concurrent_recovery_c2_db.py:72#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `is_admin=True, is_active=True,` |
| wa_backend/tests/test_warehouse_inbound_requires_cost_policy_c2_db.py:54#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `Driver.is_admin.is_(True),` |
| wa_backend/tests/test_whole_product_quality_issue_sources.py:228#1 | E | Artifact | Fixture/gate/seed or immutable historical source; no Runtime authority inferred. | `return SimpleNamespace(company_id=1, id=17, is_admin=admin)` |

## 4. Endpoint → capability matrix

**237 registrations** (including read-only POSTs, websocket subscriptions and one GET alias) are affected directly or through the recorded helper paths. **48** contain direct is_admin or get_current_admin references; **36** directly use get_current_admin. The remaining **189** depend on legacy helpers. Dormant is_admin in authenticate_websocket_user is explicitly separated from its live InventoryAccess dependency.

Each proposed new code is a **candidate for lead/owner review**, not a capability added to the catalog. Existing codes are labeled existing. Distinct current guard/UX codes must not be interpreted as an ALL-of list: source expressions retain OR/ANY semantics, optional side branches and query filters. Exact gate expressions are recorded per route in Appendix B. AMBIGUOUS cells terminate the inference; they do not approve a workaround.

Owner column: **FULL** means the already-frozen Company Owner has complete company capabilities, but never crosses company, changes channel, bypasses current business constraints (self-authorization, separation of duties, password, stock/price history, lifecycle/closed-session checks) or receives platform credentials. **CHANNEL** preserves explicit target channel. **PLATFORM** is a separate realm; tenant Owner is not authorized by tenant ownership. Ambiguous structural bypass policy remains AD10.

Expected denial codes below are **target negative expectations**, not assertions that those scenarios were dynamically tested or that every existing error matches: **DENY** = missing/revoked capability → 403 before business effects; foreign tenant/resource → fail closed (normally 404); scope-filtered reads omit unauthorized rows. Existing current validation order is evidenced in source. **AUTH** = invalid credential/token/channel or inactive principal/company denied under frozen auth contract (401/403); **WS** = no subscription, close 1008; **OPEN** = fail closed pending the named decision. Canonical coded/context/request-id transport requirement remains mandatory, without this inventory choosing new error codes.

### wa_backend/api/auth.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/auth.py:89 | POST /driver/login — driver_login | mutation | Authenticates any active Driver credentials; NO persisted field-profile check; emits role Driver, is_admin and driver_id; persists refresh token. | AMBIGUOUS (AD09): authentication/channel contract; no business capability inferred | active company + authenticated FIELD_REPRESENTATIVE channel (frozen target) | CHANNEL | AUTH |
| wa_backend/api/auth.py:144 | POST /login — admin_login | mutation | Authenticates shared Driver credentials; admits if InventoryAccess allows any catalog capability at any location; is_admin shortcut admits automatically; role Admin/Inventory. | AMBIGUOUS (AD09): explicit Backoffice channel + current ANY(PERMISSIONS) admission | active company + BACKOFFICE channel; applicable existing grants | CHANNEL | AUTH |
| wa_backend/api/auth.py:238 | POST /refresh — refresh_access_token | mutation | Rotates refresh token; 15-second lost-response successor recovery; preserves allowlisted role claim/falls back to is_admin; reloads active Driver/company. | AMBIGUOUS (AD09): session refresh contract; no new privilege inferred | stored principal + active company + explicit original channel required by target | CHANNEL | AUTH |

### wa_backend/api/branches.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/branches.py:181 | GET /warehouse/branches/options — list_branch_options | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | location.create, location.update (existing guard/side-path codes; see Appendix B) | AMBIGUOUS (AD01): branch-option metadata visibility vs current any-location permission admission | FULL | OPEN + DENY |
| wa_backend/api/branches.py:202 | GET /warehouse/branches/manage — manage_branches | read | Lists company branches (admin gate). | branch.read | company | FULL | DENY |
| wa_backend/api/branches.py:222 | POST /warehouse/branches — create_branch | mutation | Creates branch with tenant validation; admin gate. | branch.create | company | FULL | DENY |
| wa_backend/api/branches.py:287 | PATCH /warehouse/branches/{branch_id} — update_branch | mutation | Updates branch fields/version under tenant admin gate. | branch.update | company + addressed branch | FULL | DENY |
| wa_backend/api/branches.py:423 | POST /warehouse/branches/{branch_id}/activate — activate_branch | mutation | Reactivates branch under admin gate. | branch.state | company + addressed branch | FULL | DENY |
| wa_backend/api/branches.py:439 | POST /warehouse/branches/{branch_id}/deactivate — deactivate_branch | mutation | Deactivates branch subject to workflow blockers. | branch.state | company + addressed branch | FULL | DENY |

### wa_backend/api/catalog.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/catalog.py:583 | GET /catalog/uoms — list_uoms | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:592 | GET /catalog/products — list_products | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:610 | POST /catalog/products — create_product | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:636 | PATCH /catalog/products/{product_id} — update_product | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:669 | GET /catalog/variants — list_variants | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:691 | POST /catalog/variants/resolve — resolve_variants | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:716 | POST /catalog/variants — create_variant | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:756 | PATCH /catalog/variants/{variant_id} — update_variant | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:796 | PATCH /catalog/variants/{variant_id}/name — rename_variant_name | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:875 | PATCH /catalog/variants/{variant_id}/family — reassign_variant_family | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:950 | GET /catalog/variants/{variant_id}/conversions — list_conversions | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:961 | POST /catalog/variants/{variant_id}/conversions — create_conversion | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:989 | PATCH /catalog/conversions/{conversion_id} — update_conversion | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1068 | GET /catalog/variants/{variant_id}/barcodes — list_barcodes | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1124 | POST /catalog/variants/{variant_id}/barcodes — create_barcode | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1167 | POST /catalog/variants/{variant_id}/barcodes/replace-primary — replace_variant_primary_barcode | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1266 | POST /catalog/variants/{variant_id}/barcodes/package-independent — set_variant_package_barcode_independent | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1352 | PATCH /catalog/barcodes/{barcode_id} — update_barcode | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1390 | POST /catalog/gs1/parse — parse_gs1_endpoint | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1620 | POST /catalog/variants/{variant_id}/publish — publish_variant | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.publish (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1657 | GET /catalog/variants/{variant_id}/delete-draft-preflight — variant_delete_draft_preflight | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1694 | POST /catalog/variants/{variant_id}/delete-draft — delete_draft_variant | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1793 | POST /catalog/variants/{variant_id}/retire — retire_variant | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.retire (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1798 | POST /catalog/variants/{variant_id}/restore — restore_variant | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.restore (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1803 | GET /catalog/variants/{variant_id}/recall-readiness — variant_recall_readiness | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.hold, inventory.read (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1857 | GET /catalog/variants/{variant_id}/archive-preflight — variant_archive_preflight | read | Catalog archive preflight; blocker owner navigation uses is_admin for shortage and custody targets plus capability-gated links. | catalog.archive (existing); AMBIGUOUS privileged shortage/custody navigation (AD03) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | OPEN + DENY |
| wa_backend/api/catalog.py:1876 | POST /catalog/variants/{variant_id}/archive — archive_variant | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.archive (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1881 | POST /catalog/variants/{variant_id}/sales-hold — place_variant_sales_hold | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.hold (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1886 | POST /catalog/variants/{variant_id}/release-sales-hold — release_variant_sales_hold | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.hold (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1891 | GET /catalog/variants/{variant_id}/recall-preflight — recall_variant_preflight | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.hold (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1922 | POST /catalog/variants/{variant_id}/recall — recall_variant | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.hold (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1927 | POST /catalog/variants/{variant_id}/cancel-recall — cancel_variant_recall | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.hold (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |
| wa_backend/api/catalog.py:1932 | POST /catalog/variants/{variant_id}/close-recall — close_variant_recall | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.hold (existing guard/side-path codes; see Appendix B) | company catalog; preserve any-location admission and exact authorized archive-navigation targets | FULL | DENY |

### wa_backend/api/commercial_policy.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/commercial_policy.py:91 | GET /commercial-policy/rounding — get_rounding_policy | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/commercial_policy.py:112 | POST /commercial-policy/rounding/publish — publish_rounding_policy | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.approve, pricing.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |

### wa_backend/api/dispatch.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/dispatch.py:125 | PUT /admin/sessions/{session_id}/authorize — authorize_session | mutation | Changes sell authorization; rejects self-session and closed/settled sessions. | work_session.authorize_sale | AMBIGUOUS (AD03): company + stored session; route/vehicle/location delegation unresolved | FULL | OPEN + DENY |
| wa_backend/api/dispatch.py:614 | GET /admin/sessions/today — get_admin_dashboard_data | read | Reads today's field work, financial and custody projections under admin gate. | work_session.read | AMBIGUOUS (AD03): company today projection; assigned session/location visibility unresolved | FULL | OPEN + DENY |
| wa_backend/api/dispatch.py:766 | GET /admin/sessions/{session_id}/settlement_report — get_session_settlement_report | read | Reads immutable/session settlement evidence; admin gate. | settlement.read | AMBIGUOUS (AD03): company + stored session and custody locations | FULL | OPEN + DENY |
| wa_backend/api/dispatch.py:898 | PUT /admin/sessions/{session_id}/settle — settle_session | mutation | Financial settlement only after inventory reconciliation/snapshot seal; admin gate. | settlement.execute | AMBIGUOUS (AD03): company + stored session and vehicle custody | FULL | OPEN + DENY |
| wa_backend/api/dispatch.py:1058 | GET /dispatch/init — dispatch_init | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | dispatch.execute, dispatch.read (existing guard/side-path codes; see Appendix B) | company + stored route source warehouse AND VEHICLE custody location; exact transfer side if applicable | FULL | DENY |
| wa_backend/api/dispatch.py:1369 | POST /dispatch/route — dispatch_route | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | dispatch.execute (existing guard/side-path codes; see Appendix B) | company + stored route source warehouse AND VEHICLE custody location; exact transfer side if applicable | FULL | DENY |
| wa_backend/api/dispatch.py:1829 | GET /dispatch/inventory/{vehicle_id} — get_vehicle_inventory | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | dispatch.read (existing guard/side-path codes; see Appendix B) | company + stored route source warehouse AND VEHICLE custody location; exact transfer side if applicable | FULL | DENY |
| wa_backend/api/dispatch.py:1909 | GET /dispatch/route/{route_id}/live_inventory — get_route_live_inventory | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | dispatch.read (existing guard/side-path codes; see Appendix B) | company + stored route source warehouse AND VEHICLE custody location; exact transfer side if applicable | FULL | DENY |
| wa_backend/api/dispatch.py:2468 | PUT /dispatch/route/{route_id}/adjust_inventory — adjust_route_inventory | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | dispatch.execute (existing guard/side-path codes; see Appendix B) | company + stored route source warehouse AND VEHICLE custody location; exact transfer side if applicable | FULL | DENY |
| wa_backend/api/dispatch.py:2627 | POST /dispatch/transfers/{transfer_id}/force_cancel — force_cancel_handshake | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | transfer.cancel (existing guard/side-path codes; see Appendix B) | company + stored route source warehouse AND VEHICLE custody location; exact transfer side if applicable | FULL | DENY |
| wa_backend/api/dispatch.py:2745 | GET /dispatch/route/{route_id}/transfers — get_route_transfers | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | dispatch.read, transfer.cancel (existing guard/side-path codes; see Appendix B) | company + stored route source warehouse AND VEHICLE custody location; exact transfer side if applicable | FULL | DENY |
| wa_backend/api/dispatch.py:2902 | GET /dispatch/shops — get_dispatch_shops | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | dispatch.read (existing guard/side-path codes; see Appendix B) | company shop master; any-location dispatch.read admission | FULL | DENY |
| wa_backend/api/dispatch.py:3070 | PUT /dispatch/shops/bulk_update — bulk_update_shops | mutation | Bulk updates company shop operational data; admin gate. | shop.manage | company + addressed shops | FULL | DENY |
| wa_backend/api/dispatch.py:3231 | POST /dispatch/shops — admin_add_shop | mutation | Creates shop and attributes added_by_driver_id to current admin (AD06). | shop.create | company | FULL | DENY |
| wa_backend/api/dispatch.py:3393 | GET /dispatch/active_routes — get_active_routes | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | dispatch.execute, dispatch.read (existing guard/side-path codes; see Appendix B) | company + stored route source warehouse AND VEHICLE custody location; exact transfer side if applicable | FULL | DENY |
| wa_backend/api/dispatch.py:3536 | PUT /dispatch/route/{route_id}/status — update_route_status | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | dispatch.execute (existing guard/side-path codes; see Appendix B) | company + stored route source warehouse AND VEHICLE custody location; exact transfer side if applicable | FULL | DENY |
| wa_backend/api/dispatch.py:4265 | PUT /dispatch/session/{session_id}/undo_end_work — undo_end_work | mutation | Undo closed work workflow; validates active non-admin representative. | work_session.reopen | AMBIGUOUS (AD03): company + stored session/route/vehicle | FULL | OPEN + DENY |
| wa_backend/api/dispatch.py:4404 | POST /dispatch/zones — add_zone | mutation | Creates zone; admin gate. | territory.create | company | FULL | DENY |
| wa_backend/api/dispatch.py:4464 | DELETE /dispatch/zones/{zone_id} — archive_zone | mutation | Archives zone with current blockers; admin gate. | territory.archive | company + addressed zone | FULL | DENY |
| wa_backend/api/dispatch.py:4528 | PUT /dispatch/zones/{zone_id} — update_zone | mutation | Updates zone; admin gate. | territory.update | company + addressed zone | FULL | DENY |
| wa_backend/api/dispatch.py:4590 | GET /dispatch/zones/archived — get_archived_zones | read | Lists archived zones; admin gate. | territory.read | company | FULL | DENY |
| wa_backend/api/dispatch.py:4610 | PUT /dispatch/zones/{zone_id}/restore — restore_zone | mutation | Restores zone; admin gate. | territory.restore | company + addressed zone | FULL | DENY |
| wa_backend/api/dispatch.py:4668 | PUT /dispatch/shops/{shop_id} — edit_shop_details | mutation | Edits shop fields with tenant and workflow validation. | shop.update | company + addressed shop | FULL | DENY |
| wa_backend/api/dispatch.py:4846 | GET /dispatch/shortages — get_shortages | read | Lists pending shortage work under admin gate. | shortage.read | AMBIGUOUS (AD03): company + representative/request; warehouse visibility unresolved | FULL | OPEN + DENY |
| wa_backend/api/dispatch.py:4892 | POST /dispatch/shortages — add_shortages | mutation | Creates shortage requests; rejects inactive/admin target Drivers. | shortage.create | AMBIGUOUS (AD03): company + validated active representative(s)/variant; location policy unresolved | FULL | OPEN + DENY |
| wa_backend/api/dispatch.py:5133 | DELETE /dispatch/shortages/{shortage_id} — delete_shortage | mutation | Cancels/removes shortage request through current handler; admin gate. | shortage.cancel | AMBIGUOUS (AD03): company + stored shortage request | FULL | OPEN + DENY |
| wa_backend/api/dispatch.py:5228 | POST /dispatch/shops/bulk_import — bulk_import_shops | mutation | Imports shop data; admin gate; admin authorship stored (AD06). | shop.import | company | FULL | DENY |

### wa_backend/api/driver.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/driver.py:3728 | GET /visits/{visit_id} — get_visit_details | read | Allows visit owner OR persisted is_admin; no capability grant path. | AMBIGUOUS (AD04): visit.read for Backoffice and assigned representative | company + owned Visit or approved Backoffice visibility scope | FULL | OPEN + DENY |

### wa_backend/api/inventory_permissions.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/inventory_permissions.py:37 | GET /inventory/access/me — capabilities | read | Returns driver_id as principal identity, is_company_admin from is_admin; company/any/location codes. | current ANY(PERMISSIONS) admission; self capability projection (no new code proposed) | company + self + optional exact tenant location | FULL | DENY |
| wa_backend/api/inventory_permissions.py:56 | POST /inventory/access/locations/capabilities — location_capabilities | read | POST read-only projection; foreign/ungranted locations omitted. | current ANY(PERMISSIONS) admission; self capability projection | company + self + bounded exact location ids (1..100) | FULL | DENY |
| wa_backend/api/inventory_permissions.py:66 | GET /inventory/access/catalog — permission_catalog | read | Reads fixed permission catalog and company-only subset. | access.catalog.read | company | FULL | DENY |
| wa_backend/api/inventory_permissions.py:71 | GET /inventory/access/roles — roles | read | Lists company role bundles with permissions. | access.roles.read | company | FULL | DENY |
| wa_backend/api/inventory_permissions.py:134 | POST /inventory/access/roles — create_role | mutation | Creates permission bundle, serialized/audited. | access.roles.manage | company | FULL | DENY |
| wa_backend/api/inventory_permissions.py:140 | PUT /inventory/access/roles/{role_id} — update_role | mutation | Updates ordinary role; system roles reject mutation (409). | access.roles.manage | company + stored role | FULL | DENY |
| wa_backend/api/inventory_permissions.py:146 | GET /inventory/access/users — users | read | Lists all legacy Drivers, including field/admin; exposes is_admin (no Backoffice filter). | access.users.read | company | FULL | DENY |
| wa_backend/api/inventory_permissions.py:155 | GET /inventory/access/locations — locations | read | Lists company WAREHOUSE/VEHICLE grant candidates; admin gate. | access.locations.read | company | FULL | DENY |
| wa_backend/api/inventory_permissions.py:171 | GET /inventory/access/users/{user_id}/grants — user_grants | read | Lists grants for any current Driver; target Backoffice boundary already frozen. | access.grants.read | company + addressed Backoffice user; stored company/location grants | FULL | DENY |
| wa_backend/api/inventory_permissions.py:183 | POST /inventory/access/users/{user_id}/grants — grant | mutation | Grants role to any current tenant Driver; company or explicit location; audit/state-idempotent insert. | access.grants.manage | company + addressed Backoffice user + exact granted location when supplied | FULL | DENY |
| wa_backend/api/inventory_permissions.py:206 | DELETE /inventory/access/users/{user_id}/grants/{grant_id} — revoke | mutation | Revokes stored company/location grant with tenant audit. | access.grants.manage | company + addressed Backoffice user + exact stored grant location | FULL | DENY |

### wa_backend/api/inventory_stock_policy.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/inventory_stock_policy.py:500 | POST /warehouse/inventory/minimum-stock/bulk/preview — preview_bulk_minimum_stock | read | POST read/preview; helper _require_bulk_admin requires persisted is_admin and inventory.read. | AMBIGUOUS (AD02): inventory.minimum_stock.manage candidate | company + exact ordinary warehouse + selected product set | FULL | OPEN + DENY |
| wa_backend/api/inventory_stock_policy.py:531 | PUT /warehouse/inventory/minimum-stock/bulk — apply_bulk_minimum_stock | mutation | Bulk threshold mutation; same _require_bulk_admin helper and durable operation. | AMBIGUOUS (AD02): inventory.minimum_stock.manage candidate | company + exact ordinary warehouse + selected product set | FULL | OPEN + DENY |
| wa_backend/api/inventory_stock_policy.py:661 | PUT /warehouse/inventory/{product_variant_id}/minimum-stock — update_minimum_stock | mutation | Requires persisted is_admin then inventory.read for exact location; durable request/actor binding. | AMBIGUOUS (AD02): inventory.minimum_stock.manage candidate; current inventory.read is insufficient mutation authority | company + exact ordinary warehouse + variant | FULL | OPEN + DENY |

### wa_backend/api/offers.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/offers.py:423 | GET /offers/policy — get_policy | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:436 | GET /offers/references/variants — list_reference_variants | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:467 | POST /offers/references/variants/resolve — resolve_reference_variants | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:506 | GET /offers/definitions — list_definitions | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:535 | POST /offers/definitions — add_definition | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:566 | PATCH /offers/definitions/{definition_id} — edit_definition | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:600 | DELETE /offers/definitions/{definition_id} — remove_definition | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:630 | GET /offers/definitions/{definition_id}/versions — list_versions | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:676 | GET /offers/versions/{version_id} — get_version | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:701 | POST /offers/definitions/{definition_id}/versions — add_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:742 | PUT /offers/versions/{version_id} — edit_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:781 | DELETE /offers/versions/{version_id} — remove_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:811 | POST /offers/preview — preview_basket | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:830 | POST /offers/versions/{version_id}/validate — validate_offer_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | offers.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:885 | POST /offers/versions/{version_id}/submit — submit | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | offers.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:904 | POST /offers/versions/{version_id}/publish — publish | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | offers.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:923 | POST /offers/versions/{version_id}/approve — approve | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | offers.approve (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/offers.py:942 | POST /offers/versions/{version_id}/cancel — cancel | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | offers.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |

### wa_backend/api/platform_manager.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/platform_manager.py:176 | POST /platform/companies — create_new_tenant | mutation | PlatformAdmin-authenticated company provisioning creates legacy tenant admin is_admin=True; no tenant owner relation. | AMBIGUOUS: platform capability naming outside company migration | separate platform realm; newly provisioned company | PLATFORM | OPEN + DENY |

### wa_backend/api/pricing.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/pricing.py:311 | GET /pricing/policy — get_pricing_policy | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:324 | GET /pricing/books — list_books | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:355 | POST /pricing/books — add_book | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:413 | GET /pricing/books/{book_id}/publications — list_publications | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:460 | POST /pricing/books/{book_id}/publications — add_publication | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:517 | GET /pricing/publications/{publication_id}/entries — list_entries | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:564 | POST /pricing/publications/{publication_id}/entries — add_entry | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:621 | PATCH /pricing/entries/{entry_id} — edit_entry | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:675 | DELETE /pricing/entries/{entry_id} — remove_entry | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:794 | POST /pricing/publications/{publication_id}/submit — submit | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | pricing.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:813 | POST /pricing/publications/{publication_id}/approve — approve | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | pricing.approve (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:832 | POST /pricing/publications/{publication_id}/publish — publish | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | pricing.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:851 | POST /pricing/publications/{publication_id}/cancel — cancel | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:905 | GET /pricing/assignments — list_assignments | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:936 | POST /pricing/assignments — add_assignment | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/pricing.py:995 | POST /pricing/resolve-preview — resolve_preview | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |

### wa_backend/api/product_locations.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/product_locations.py:130 | GET /warehouse/product-locations — list_product_locations | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | product_location.read (existing guard/side-path codes; see Appendix B) | company + exact stored/payload product-location; validated variant | FULL | DENY |
| wa_backend/api/product_locations.py:175 | POST /warehouse/product-locations — create_product_location | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | product_location.manage (existing guard/side-path codes; see Appendix B) | company + exact stored/payload product-location; validated variant | FULL | DENY |
| wa_backend/api/product_locations.py:248 | PATCH /warehouse/product-locations/{product_location_id} — update_product_location | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | product_location.manage (existing guard/side-path codes; see Appendix B) | company + exact stored/payload product-location; validated variant | FULL | DENY |
| wa_backend/api/product_locations.py:307 | DELETE /warehouse/product-locations/{product_location_id} — delete_product_location | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | product_location.manage (existing guard/side-path codes; see Appendix B) | company + exact stored/payload product-location; validated variant | FULL | DENY |

### wa_backend/api/product_tracking.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/product_tracking.py:153 | GET /simple-products/tracking/defaults — get_product_tracking_defaults | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |
| wa_backend/api/product_tracking.py:175 | PUT /simple-products/tracking/defaults — update_product_tracking_defaults | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |
| wa_backend/api/product_tracking.py:255 | PATCH /simple-products/tracking/variants/{variant_id} — update_variant_product_tracking | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |

### wa_backend/api/reconciliation.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/reconciliation.py:74 | POST /driver/session/{session_id}/reconcile — reconcile_driver_end_of_day | mutation | Handler requires own session; helper permits session owner OR active is_admin; seals snapshots or opens bounded VEHICLE_RECON. | AMBIGUOUS (AD04): field inventory reconciliation capability; helper privileged override unresolved | company + own WorkSession + stored route/VEHICLE location | CHANNEL (AD04) | OPEN + DENY |

### wa_backend/api/sales_returns.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/sales_returns.py:33 | GET /sales-returns — list_returns | read | Lists official sales-return documents; admin gate. | sales_return.read | company | FULL | DENY |
| wa_backend/api/sales_returns.py:51 | GET /sales-returns/sources — returnable_sales | read | Lists eligible original sales evidence; admin gate. | sales_return.sources.read | company + addressed sales/visits | FULL | DENY |
| wa_backend/api/sales_returns.py:75 | GET /sales-returns/source/{visit_id} — return_source | read | Reads original-sale return source; admin gate. | sales_return.sources.read | company + stored original visit | FULL | DENY |
| wa_backend/api/sales_returns.py:91 | GET /sales-returns/{return_id} — return_detail | read | Reads return detail; admin gate. | sales_return.read | company + stored return document | FULL | DENY |
| wa_backend/api/sales_returns.py:107 | POST /sales-returns — post_return | mutation | Posts reversal against original sale evidence through return service; authenticated actor attribution. | sales_return.create | company + original sale/visit + AMBIGUOUS affected stock location scope (AD03) | FULL | OPEN + DENY |

### wa_backend/api/simple_products.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/simple_products.py:1106 | GET /simple-products/package-uoms — package_uoms | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |
| wa_backend/api/simple_products.py:1124 | GET /simple-products/families — families | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |
| wa_backend/api/simple_products.py:1196 | POST /simple-products/families — create_product_family | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |
| wa_backend/api/simple_products.py:1263 | PATCH /simple-products/families/{family_id} — update_product_family | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |
| wa_backend/api/simple_products.py:1333 | DELETE /simple-products/families/{family_id} — delete_product_family | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.manage (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |
| wa_backend/api/simple_products.py:1411 | GET /simple-products/summary — catalog_summary | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |
| wa_backend/api/simple_products.py:1420 | GET /simple-products — list_simple_products | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read, pricing.view (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |
| wa_backend/api/simple_products.py:2055 | POST /simple-products — create_simple_product | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |
| wa_backend/api/simple_products.py:2157 | PATCH /simple-products/{variant_id}/price — update_simple_product_price | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | pricing.manage (existing guard/side-path codes; see Appendix B) | company catalog; current any-location read admission; company-only mutations | FULL | DENY |

### wa_backend/api/suppliers.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/suppliers.py:28 | GET /suppliers — suppliers | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | supplier.read (existing guard/side-path codes; see Appendix B) | company Supplier Master + addressed tenant supplier | FULL | DENY |
| wa_backend/api/suppliers.py:38 | GET /suppliers/{supplier_id} — supplier | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | supplier.read (existing guard/side-path codes; see Appendix B) | company Supplier Master + addressed tenant supplier | FULL | DENY |
| wa_backend/api/suppliers.py:45 | POST /suppliers — create_supplier | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | supplier.manage, supplier.read (existing guard/side-path codes; see Appendix B) | company Supplier Master + addressed tenant supplier | FULL | DENY |
| wa_backend/api/suppliers.py:51 | PUT /suppliers/{supplier_id} — update_supplier | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | supplier.manage, supplier.read (existing guard/side-path codes; see Appendix B) | company Supplier Master + addressed tenant supplier | FULL | DENY |
| wa_backend/api/suppliers.py:57 | PATCH /suppliers/{supplier_id}/state — supplier_state | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | supplier.manage, supplier.read (existing guard/side-path codes; see Appendix B) | company Supplier Master + addressed tenant supplier | FULL | DENY |

### wa_backend/api/taxation.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/taxation.py:313 | GET /taxation/policy — get_policy | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:326 | POST /taxation/preview — preview_tax | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:343 | GET /taxation/jurisdictions — list_jurisdictions | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:372 | POST /taxation/jurisdictions — add_jurisdiction | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:402 | PATCH /taxation/jurisdictions/{jurisdiction_id} — edit_jurisdiction | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:434 | DELETE /taxation/jurisdictions/{jurisdiction_id} — remove_jurisdiction | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:461 | GET /taxation/rule-sets — list_rule_sets | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:490 | POST /taxation/rule-sets — add_rule_set | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:516 | PATCH /taxation/rule-sets/{rule_set_id} — edit_rule_set | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:548 | DELETE /taxation/rule-sets/{rule_set_id} — remove_rule_set | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:575 | GET /taxation/rule-sets/{rule_set_id}/versions — list_versions | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:621 | GET /taxation/versions/{version_id} — get_version | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:646 | POST /taxation/rule-sets/{rule_set_id}/versions — add_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:681 | PUT /taxation/versions/{version_id} — edit_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:714 | DELETE /taxation/versions/{version_id} — remove_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:741 | POST /taxation/versions/{version_id}/validate — validate_tax_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | tax.view (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:825 | POST /taxation/versions/{version_id}/submit — submit_tax_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | tax.approve, tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:837 | POST /taxation/versions/{version_id}/publish — publish_tax_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | tax.approve, tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:849 | POST /taxation/versions/{version_id}/approve — approve_tax_version | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | tax.approve, tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |
| wa_backend/api/taxation.py:861 | POST /taxation/versions/{version_id}/cancel — cancel_tax_version_endpoint | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | tax.approve, tax.manage (existing guard/side-path codes; see Appendix B) | company (COMPANY_ONLY grants); addressed stored version/book/rule | FULL | DENY |

### wa_backend/api/warehouse/inbound.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/inbound.py:287 | POST /warehouse/inbound/options — warehouse_inbound_options | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inbound.create (existing guard/side-path codes; see Appendix B) | company + explicit ordinary supplier-inbound warehouse + tenant variants | FULL | DENY |
| wa_backend/api/warehouse/inbound.py:344 | GET /warehouse/costing-policy — warehouse_costing_policy | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inbound.create, inventory.costing.manage (existing guard/side-path codes; see Appendix B) | company costing policy; exact warehouse admission where present | FULL | DENY |
| wa_backend/api/warehouse/inbound.py:370 | PUT /warehouse/costing-policy — update_warehouse_costing_policy | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.costing.manage (existing guard/side-path codes; see Appendix B) | company costing policy; exact warehouse admission where present | FULL | DENY |
| wa_backend/api/warehouse/inbound.py:422 | POST /warehouse/inbound — warehouse_inbound | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inbound.create (existing guard/side-path codes; see Appendix B) | company + explicit ordinary supplier-inbound warehouse + tenant variants | FULL | DENY |

### wa_backend/api/warehouse/inbound_adjustments.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/inbound_adjustments.py:40 | POST /warehouse/ledger/{entry_id}/adjust — adjust_warehouse_entry | mutation | Requires ledger.adjust at server-stored inbound destination. | ledger.adjust (existing) | company + exact destination of stored supplier inbound movement | FULL | DENY |

### wa_backend/api/warehouse/ledger.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/ledger.py:301 | GET /warehouse/ledger/cursor — get_warehouse_ledger_cursor | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | ledger.read (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |

### wa_backend/api/warehouse/live_stock.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/live_stock.py:713 | GET /warehouse/inventory/alerts/summary — get_warehouse_inventory_alert_summary | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.read (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |
| wa_backend/api/warehouse/live_stock.py:738 | GET /warehouse/inventory/summary — get_warehouse_inventory_summary | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.read (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |
| wa_backend/api/warehouse/live_stock.py:856 | GET /warehouse/inventory/families — get_warehouse_inventory_families | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.read (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |
| wa_backend/api/warehouse/live_stock.py:929 | GET /warehouse/inventory/batch-products — get_warehouse_inventory_batch_products | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.read (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |
| wa_backend/api/warehouse/live_stock.py:1151 | GET /warehouse/inventory/cursor — get_warehouse_inventory | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.read (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |
| wa_backend/api/warehouse/live_stock.py:1798 | GET /warehouse/inventory/{product_variant_id}/batches — get_warehouse_inventory_batches | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.read (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |
| wa_backend/api/warehouse/live_stock.py:2439 | GET /warehouse/variants/{product_variant_id}/quality-batch-candidates — get_quality_batch_candidates | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.read (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |
| wa_backend/api/warehouse/live_stock.py:2477 | GET /warehouse/variants/{product_variant_id}/quality-issue-sources — get_whole_product_quality_issue_sources | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.disposal.confirm, inventory.read, inventory.vendor_return.confirm, transfer.destination, transfer.send (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |
| wa_backend/api/warehouse/live_stock.py:2857 | GET /warehouse/batches/{batch_id}/stock-sources — get_batch_stock_sources | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.disposal.confirm, inventory.read, inventory.vendor_return.confirm, transfer.destination, transfer.send (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |

### wa_backend/api/warehouse/locations.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/locations.py:230 | GET /warehouse/setup-status — get_warehouse_setup_status | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | location.create, location.read (existing guard/side-path codes; see Appendix B) | company + filtered exact readable locations | FULL | DENY |
| wa_backend/api/warehouse/locations.py:274 | GET /warehouse/locations — manage_warehouse_locations | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | location.read (existing guard/side-path codes; see Appendix B) | company + filtered exact readable locations | FULL | DENY |
| wa_backend/api/warehouse/locations.py:274 | GET /warehouse/locations/manage — manage_warehouse_locations | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | location.read (existing guard/side-path codes; see Appendix B) | company + filtered exact readable locations | FULL | DENY |
| wa_backend/api/warehouse/locations.py:381 | POST /warehouse/locations — create_warehouse_location | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | location.create (existing guard/side-path codes; see Appendix B) | company + exact addressed location; creation is company-only | FULL | DENY |
| wa_backend/api/warehouse/locations.py:519 | PATCH /warehouse/locations/{location_id} — update_warehouse_location | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | location.update (existing guard/side-path codes; see Appendix B) | company + exact addressed location; creation is company-only | FULL | DENY |
| wa_backend/api/warehouse/locations.py:668 | POST /warehouse/locations/{location_id}/activate — activate_warehouse_location | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | location.state (existing guard/side-path codes; see Appendix B) | company + exact addressed location; creation is company-only | FULL | DENY |
| wa_backend/api/warehouse/locations.py:789 | POST /warehouse/locations/{location_id}/deactivate — deactivate_warehouse_location | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | location.state (existing guard/side-path codes; see Appendix B) | company + exact addressed location; creation is company-only | FULL | DENY |

### wa_backend/api/warehouse/status.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/status.py:20 | GET /warehouse/status — get_warehouse_status | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | dispatch.read, location.read (existing guard/side-path codes; see Appendix B) | company + exact warehouse/locations from stored balance/movement; preserve query location filters | FULL | DENY |

### wa_backend/api/warehouse/stocktake.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/stocktake.py:439 | GET /warehouse/unified/stocktake/cycle-batches — list_stocktake_cycle_batches | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | stocktake.start (existing guard/side-path codes; see Appendix B) | company + exact stored stocktake location/session; recount actor and work session when relevant | FULL | DENY |
| wa_backend/api/warehouse/stocktake.py:655 | GET /warehouse/unified/stocktake/vehicle-recon-candidates — list_vehicle_recon_candidates | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | location.read, stocktake.start (existing guard/side-path codes; see Appendix B) | company + exact stored stocktake location/session; recount actor and work session when relevant | FULL | DENY |
| wa_backend/api/warehouse/stocktake.py:1013 | GET /warehouse/unified/stocktakes/active — list_active_stocktake_sessions | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | stocktake.read (existing guard/side-path codes; see Appendix B) | company + exact stored stocktake location/session; recount actor and work session when relevant | FULL | DENY |
| wa_backend/api/warehouse/stocktake.py:1183 | GET /warehouse/unified/stocktake/{session_id}/context — get_stocktake_session_context | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | location.read, stocktake.read (existing guard/side-path codes; see Appendix B) | company + exact stored stocktake location/session; recount actor and work session when relevant | FULL | DENY |
| wa_backend/api/warehouse/stocktake.py:1376 | POST /warehouse/unified/stocktake/start — start_unified_stocktake | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | stocktake.start (existing guard/side-path codes; see Appendix B) | company + exact stored stocktake location/session; recount actor and work session when relevant | FULL | DENY |
| wa_backend/api/warehouse/stocktake.py:1624 | GET /warehouse/unified/stocktake/{session_id}/count-sheet — get_stocktake_count_sheet | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | stocktake.count (existing guard/side-path codes; see Appendix B) | company + exact stored stocktake location/session; recount actor and work session when relevant | FULL | DENY |
| wa_backend/api/warehouse/stocktake.py:1712 | POST /warehouse/unified/stocktake/{session_id}/count — submit_stocktake_count | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | stocktake.count (existing guard/side-path codes; see Appendix B) | company + exact stored stocktake location/session; recount actor and work session when relevant | FULL | DENY |
| wa_backend/api/warehouse/stocktake.py:2029 | GET /warehouse/unified/stocktake/{session_id}/review — get_stocktake_review | read | Requires stocktake.review AND persisted is_admin; review requires PENDING_REVIEW. | stocktake.review (existing); AMBIGUOUS extra supervisor gate (AD02) | company + exact stored stocktake location/session | FULL | OPEN + DENY |
| wa_backend/api/warehouse/stocktake.py:2209 | POST /warehouse/unified/stocktake/{session_id}/approve — approve_stocktake_session | mutation | Requires stocktake.approve and password confirmation; posting service still queries active is_admin=True. | stocktake.approve (existing); AMBIGUOUS posting supervisor gate (AD02) | company + exact stored stocktake location/session/attempt | FULL | OPEN + DENY |
| wa_backend/api/warehouse/stocktake.py:2318 | POST /warehouse/unified/stocktake/{session_id}/recount — recount_stocktake_session | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | stocktake.recount (existing guard/side-path codes; see Appendix B) | company + exact stored stocktake location/session; recount actor and work session when relevant | FULL | DENY |
| wa_backend/api/warehouse/stocktake.py:2418 | POST /warehouse/unified/stocktake/{session_id}/cancel — cancel_stocktake_session | mutation | Requires stocktake.cancel AND persisted is_admin and actor password; audits rejection/cancellation. | stocktake.cancel (existing); AMBIGUOUS extra supervisor gate (AD02) | company + exact stored stocktake location/session | FULL | OPEN + DENY |

### wa_backend/api/warehouse/transfer_policy.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/transfer_policy.py:115 | GET /warehouse/operational-policy/transfer-destinations — get_transfer_destination_policy | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.transfer_policy.manage (existing guard/side-path codes; see Appendix B) | company-wide operational policy (COMPANY_ONLY) | FULL | DENY |
| wa_backend/api/warehouse/transfer_policy.py:149 | PUT /warehouse/operational-policy/transfer-destinations/draft — save_transfer_destination_policy | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.transfer_policy.manage (existing guard/side-path codes; see Appendix B) | company-wide operational policy (COMPANY_ONLY) | FULL | DENY |
| wa_backend/api/warehouse/transfer_policy.py:235 | POST /warehouse/operational-policy/transfer-destinations/{policy_id}/publish — publish_transfer_destination_policy_endpoint | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.transfer_policy.manage (existing guard/side-path codes; see Appendix B) | company-wide operational policy (COMPANY_ONLY) | FULL | DENY |

### wa_backend/api/warehouse/transfers.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/transfers.py:228 | POST /warehouse/batches/{batch_id}/disposition — change_batch_disposition | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | batch.disposition (existing guard/side-path codes; see Appendix B) | company batch disposition (COMPANY_ONLY); inventory effects preserve affected locations | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:334 | POST /warehouse/inventory/status-change — change_inventory_status | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.status_change (existing guard/side-path codes; see Appendix B) | company + exact stored/payload source AND destination/decision side; purpose-specific company grant and backend transit custody | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:469 | GET /warehouse/unified/transfer/locations — list_unified_transfer_locations | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | transfer.destination, transfer.read, transfer.send (existing guard/side-path codes; see Appendix B) | company + exact source/destination visibility; transfer reads preserve OR(source,destination) | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:558 | GET /warehouse/unified/transfer/source-inventory — get_unified_transfer_source_inventory | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | transfer.send (existing guard/side-path codes; see Appendix B) | company + exact source/destination visibility; transfer reads preserve OR(source,destination) | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:809 | GET /warehouse/unified/transfer/override-options — get_unified_transfer_override_options | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.fefo_override (existing guard/side-path codes; see Appendix B) | company + exact source/destination visibility; transfer reads preserve OR(source,destination) | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:1181 | GET /warehouse/unified/transfers — list_unified_transfers | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | transfer.read (existing guard/side-path codes; see Appendix B) | company + exact source/destination visibility; transfer reads preserve OR(source,destination) | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:1338 | GET /warehouse/unified/transfers/{header_id} — get_unified_transfer_detail | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | transfer.read (existing guard/side-path codes; see Appendix B) | company + stored source/destination; preserve OR read access | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:1449 | POST /warehouse/unified/transfer/special/dispatch — special_transfer_dispatch | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | transfer.destination, transfer.send (existing guard/side-path codes; see Appendix B) | company + exact stored/payload source AND destination/decision side; purpose-specific company grant and backend transit custody | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:1714 | POST /warehouse/quality/stage — stage_inventory_quality_handling | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | transfer.destination, transfer.send (existing guard/side-path codes; see Appendix B) | company + exact stored/payload source AND destination/decision side; purpose-specific company grant and backend transit custody | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:1856 | POST /warehouse/quality/disposal/confirm — confirm_inventory_disposal | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.disposal.confirm (existing guard/side-path codes; see Appendix B) | company + exact stored/payload source AND destination/decision side; purpose-specific company grant and backend transit custody | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:1945 | POST /warehouse/quality/vendor-return/confirm — confirm_inventory_vendor_handover | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.vendor_return.confirm (existing guard/side-path codes; see Appendix B) | company + exact stored/payload source AND destination/decision side; purpose-specific company grant and backend transit custody | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:2017 | POST /warehouse/unified/transfer/dispatch — unified_transfer_dispatch | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | inventory.fefo_override, transfer.destination, transfer.send, transfer.warehouse_balancing_override (existing guard/side-path codes; see Appendix B) | company + exact stored/payload source AND destination/decision side; purpose-specific company grant and backend transit custody | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:2820 | POST /warehouse/unified/transfer/receive — unified_transfer_receive | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | transfer.receive (existing guard/side-path codes; see Appendix B) | company + exact stored/payload source AND destination/decision side; purpose-specific company grant and backend transit custody | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:2945 | POST /warehouse/unified/transfer/{header_id}/cancel — unified_transfer_cancel | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | transfer.cancel (existing guard/side-path codes; see Appendix B) | company + exact stored/payload source AND destination/decision side; purpose-specific company grant and backend transit custody | FULL | DENY |
| wa_backend/api/warehouse/transfers.py:3062 | POST /warehouse/unified/transfer/{header_id}/reject — unified_transfer_reject | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | transfer.reject (existing guard/side-path codes; see Appendix B) | company + exact stored/payload source AND destination/decision side; purpose-specific company grant and backend transit custody | FULL | DENY |

### wa_backend/api/warehouse/whole_product_quality.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/whole_product_quality.py:125 | POST /warehouse/quality/products/{product_variant_id}/resolve-all — resolve_whole_product_quality | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | inventory.disposal.confirm, inventory.vendor_return.confirm (existing guard/side-path codes; see Appendix B) | company + all exact affected source/destination locations; company special-purpose authority | FULL | DENY |

### wa_backend/api/warehouse/whole_product_quality_preview.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/api/warehouse/whole_product_quality_preview.py:128 | GET /warehouse/quality/products/{product_variant_id}/resolve-preview — get_whole_product_quality_preview | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | inventory.read, supplier.read (existing guard/side-path codes; see Appendix B) | company + all exact affected source/destination locations; company special-purpose authority | FULL | DENY |

### wa_backend/domains/simple_products/imports/api/router.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/domains/simple_products/imports/api/router.py:477 | GET /simple-products/import-template — get_product_import_template | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:512 | GET /simple-products/import-worker/readiness — get_product_import_worker_readiness | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:560 | WEBSOCKET /simple-products/imports/{job_id}/ws — product_import_progress_websocket | read subscription | authenticate_websocket_user(require_admin=False), then active tenant Driver and catalog.read; admin check branch is inactive here. | catalog.read (existing); explicit Backoffice channel target | company + stored tenant job UUID; current any-location catalog.read | FULL | WS |
| wa_backend/domains/simple_products/imports/api/router.py:663 | POST /simple-products/imports — create_product_import | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:806 | GET /simple-products/imports/{job_id} — get_product_import | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:841 | GET /simple-products/imports/{job_id}/errors — get_product_import_errors | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Exact guards in Appendix B. | catalog.read (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:879 | GET /simple-products/imports/{job_id}/lineage — get_product_import_lineage | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:926 | GET /simple-products/imports/{job_id}/correction — get_product_import_correction | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:1002 | POST /simple-products/imports/{job_id}/correction — upload_product_import_correction | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:1127 | PUT /simple-products/imports/{job_id}/mapping — set_product_import_mapping | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:1210 | POST /simple-products/imports/{job_id}/cancel — cancel_product_import | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:1245 | POST /simple-products/imports/{job_id}/retry — retry_product_import | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:1375 | GET /simple-products/imports/{job_id}/correction/rows — get_product_import_correction_rows | read | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |
| wa_backend/domains/simple_products/imports/api/router.py:1409 | POST /simple-products/imports/{job_id}/correction/rows — patch_product_import_correction_rows | mutation | InventoryAccess capability/filter authorization; is_admin full-authority shortcut. Permission supplied through imported/parameterized helper. | catalog.manage, catalog.publish, pricing.manage (existing guard/side-path codes; see Appendix B) | company + stored job UUID/source; exact existing admission; actor-attributed worker recheck | FULL | DENY |

### wa_backend/main.py

| File:line | Endpoint / function | Read or mutation | Current behavior | Proposed capability | Required scope | Owner | Expected denial |
|---|---|---|---|---|---|---|---|
| wa_backend/main.py:459 | WEBSOCKET /ws/dispatch — websocket_dispatch_endpoint | read subscription | WS signature/type/sub/company/blacklist/active Driver AND persisted is_admin; broadcasts by company. | dispatch.read candidate; AMBIGUOUS stream scope (AD05) | company stream; narrow route/warehouse subscriptions unresolved | FULL | WS |

## 5. All drivers-targeting foreign keys

**55 relationships across 36 tables and 5 model files**: 43 central + 4 Offers + 5 Taxation + 1 Sales Returns + 2 Suppliers. There are 54 tenant-safe composite relationships and one single-column authentication FK (RefreshToken). The planning baseline of 43 described models.py only and is not the repository-wide total. Evidence classification describes current business meaning; it does not choose new persistence identifiers or a migration layout.

| # | Model/table + local actor column(s) | Source definition | Class | Workflow evidence/reason | Current FK delete behavior | Upgrade declaration evidence |
|---|---|---|---|---|---|---|
| FK01 | OfferDefinition / offer_definitions.(company_id, created_by) | wa_backend/domains/offers/models.py:36 | PRINCIPAL_ACTOR | Offer definition creator actor in domains/offers/publishing.py:388; company commercial administration. | RESTRICT | wa_backend/alembic/versions/6a1f9c2e4d70_stage6a_offers_foundation.py:60 |
| FK02 | OfferVersion / offer_versions.(company_id, created_by) | wa_backend/domains/offers/models.py:89 | PRINCIPAL_ACTOR | Draft creator, approver, cancellation performer in offers publishing; preserve immutable attribution. | RESTRICT | wa_backend/alembic/versions/6a1f9c2e4d70_stage6a_offers_foundation.py:127 |
| FK03 | OfferVersion / offer_versions.(company_id, approved_by) | wa_backend/domains/offers/models.py:95 | PRINCIPAL_ACTOR | Draft creator, approver, cancellation performer in offers publishing; preserve immutable attribution. | RESTRICT | wa_backend/alembic/versions/6a1f9c2e4d70_stage6a_offers_foundation.py:128 |
| FK04 | OfferVersion / offer_versions.(company_id, cancelled_by) | wa_backend/domains/offers/models.py:101 | PRINCIPAL_ACTOR | Draft creator, approver, cancellation performer in offers publishing; preserve immutable attribution. | RESTRICT | wa_backend/alembic/versions/6a1f9c2e4d70_stage6a_offers_foundation.py:129 |
| FK05 | SalesReturnDocument / sales_return_documents.(company_id, created_by) | wa_backend/domains/sales_returns/models.py:56 | PRINCIPAL_ACTOR | Official return creator in sales_returns/service.py:881 via Backoffice API actor_id; original sale representative is separate. | RESTRICT | wa_backend/alembic/versions/d2a6c8e4f1b7_stage6_return_reversal_original_lines.py:121 |
| FK06 | Supplier / suppliers.(company_id, created_by) | wa_backend/domains/suppliers/models.py:13 | PRINCIPAL_ACTOR | Supplier creator/editor in domains/suppliers/application.py:28 and subsequent update actor; independent company master. | RESTRICT | wa_backend/alembic/versions/b7f2a9c4d681_supplier_master_v1.py:40 |
| FK07 | Supplier / suppliers.(company_id, updated_by) | wa_backend/domains/suppliers/models.py:15 | PRINCIPAL_ACTOR | Supplier creator/editor in domains/suppliers/application.py:28 and subsequent update actor; independent company master. | RESTRICT | wa_backend/alembic/versions/b7f2a9c4d681_supplier_master_v1.py:42 |
| FK08 | TaxJurisdiction / tax_jurisdictions.(company_id, created_by) | wa_backend/domains/taxation/models.py:42 | PRINCIPAL_ACTOR | Tax jurisdiction creator, taxonomy/publishing command actor; not field work owner. | RESTRICT | wa_backend/alembic/versions/7c2a8b4d6e91_stage6c_tax_foundation.py:85 |
| FK09 | TaxRuleSet / tax_rule_sets.(company_id, created_by) | wa_backend/domains/taxation/models.py:117 | PRINCIPAL_ACTOR | Company tax rule-set creator from authenticated actor in taxation/publishing.py. | RESTRICT | wa_backend/alembic/versions/7c2a8b4d6e91_stage6c_tax_foundation.py:108 |
| FK10 | TaxRuleSetVersion / tax_rule_set_versions.(company_id, created_by) | wa_backend/domains/taxation/models.py:169 | PRINCIPAL_ACTOR | Version creator/approver/canceller, taxation/publishing.py; historical commercial authority. | RESTRICT | wa_backend/alembic/versions/7c2a8b4d6e91_stage6c_tax_foundation.py:155 |
| FK11 | TaxRuleSetVersion / tax_rule_set_versions.(company_id, approved_by) | wa_backend/domains/taxation/models.py:175 | PRINCIPAL_ACTOR | Version creator/approver/canceller, taxation/publishing.py; historical commercial authority. | RESTRICT | wa_backend/alembic/versions/7c2a8b4d6e91_stage6c_tax_foundation.py:156 |
| FK12 | TaxRuleSetVersion / tax_rule_set_versions.(company_id, cancelled_by) | wa_backend/domains/taxation/models.py:181 | PRINCIPAL_ACTOR | Version creator/approver/canceller, taxation/publishing.py; historical commercial authority. | RESTRICT | wa_backend/alembic/versions/7c2a8b4d6e91_stage6c_tax_foundation.py:157 |
| FK13 | UserRole / user_roles.(company_id, driver_id) | wa_backend/models.py:121 | BACKOFFICE_USER | Company role assignment consumed by InventoryAccess; frozen plan Phase 6 targets Backoffice. Current user_exists accepts any Driver (inventory_permissions.py:163); historical membership/type not proven. | CASCADE | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:406 |
| FK14 | UserLocationAccess / user_location_access.(company_id, driver_id) | wa_backend/models.py:134 | BACKOFFICE_USER | Exact-location role assignment consumed by InventoryAccess; plan Phase 6 freezes Backoffice target. Existing data/type checks do not enforce that target. | CASCADE | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:807 |
| FK15 | InventoryCostPolicy / inventory_cost_policies.(company_id, created_by) | wa_backend/models.py:437 | PRINCIPAL_ACTOR | Cost-policy creator/editor/explicit selector actor; domains/inventory_costing/service.py:343, :390 and warehouse/inbound.py costing command. | RESTRICT | wa_backend/alembic/versions/fa7c9d3e1b24_stage74_inventory_costing.py:101 |
| FK16 | InventoryCostPolicy / inventory_cost_policies.(company_id, updated_by) | wa_backend/models.py:443 | PRINCIPAL_ACTOR | Cost-policy creator/editor/explicit selector actor; domains/inventory_costing/service.py:343, :390 and warehouse/inbound.py costing command. | RESTRICT | wa_backend/alembic/versions/fa7c9d3e1b24_stage74_inventory_costing.py:104 |
| FK17 | InventoryCostPolicy / inventory_cost_policies.(company_id, selected_by) | wa_backend/models.py:449 | PRINCIPAL_ACTOR | Cost-policy creator/editor/explicit selector actor; domains/inventory_costing/service.py:343, :390 and warehouse/inbound.py costing command. | RESTRICT | wa_backend/alembic/versions/ce41f0a92b68_inventory_cost_choice_provenance.py:23 |
| FK18 | ProductImportJob / product_import_jobs.(company_id, created_by) | wa_backend/models.py:811 | PRINCIPAL_ACTOR | Creating authenticated actor persisted for bounded worker reauthorization; execution_service.py:649–675 reloads job.created_by. | RESTRICT | wa_backend/alembic/versions/f7a1c3d5e9b2_stage7_async_product_import.py:58 |
| FK19 | ProductLocation / product_locations.(company_id, created_by) | wa_backend/models.py:948 | PRINCIPAL_ACTOR | Actor creating operational catalog/location assignment; API and inbound lazy assignment use actor id. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:695 |
| FK20 | WorkSession / work_sessions.(company_id, driver_id) | wa_backend/models.py:1025 | FIELD_REPRESENTATIVE | Owning representative in driver.py start/end/dashboard and reconciliation.py:119. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:434 |
| FK21 | WorkSession / work_sessions.(company_id, inventory_reconciled_by) | wa_backend/models.py:1045 | PRINCIPAL_ACTOR | Who sealed inventory reconciliation; services.py:4762; can be representative or supervisor, not session ownership. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:435 |
| FK22 | SessionInventorySnapshot / session_inventory_snapshots.(company_id, settled_by) | wa_backend/models.py:1121 | PRINCIPAL_ACTOR | Who sealed ending custody evidence; services.py:4753 sets settled_by from actor, separate from session owner. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:755 |
| FK23 | Shop / shops.(company_id, added_by_driver_id) | wa_backend/models.py:1169 | AMBIGUOUS | AD06: field driver.py:3344 AND Backoffice dispatch.py:3363, :5408 write added_by_driver_id. Field-only name conflicts with generic authorship; no destination chosen. | SET NULL (added_by_driver_id) | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:789 |
| FK24 | DispatchRoute / dispatch_routes.(company_id, driver_id) | wa_backend/models.py:1240 | FIELD_REPRESENTATIVE | Assigned active non-admin representative in dispatch.py:1391, :3710, :3759; company route/session ownership. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:483 |
| FK25 | PriceBook / price_books.(company_id, created_by) | wa_backend/models.py:1284 | PRINCIPAL_ACTOR | Authenticated price-book creator in domains/pricing/publishing.py:167, not the representative consuming prices. | RESTRICT | wa_backend/alembic/versions/e5a1c9d4b7f2_stage5_temporal_pricing_foundation.py:80 |
| FK26 | PricePublication / price_publications.(company_id, created_by) | wa_backend/models.py:1355 | PRINCIPAL_ACTOR | Publication creator/approver from actor_id in domains/pricing/publishing.py; immutable price history. | RESTRICT | wa_backend/alembic/versions/e5a1c9d4b7f2_stage5_temporal_pricing_foundation.py:113 |
| FK27 | PricePublication / price_publications.(company_id, approved_by) | wa_backend/models.py:1361 | PRINCIPAL_ACTOR | Publication creator/approver from actor_id in domains/pricing/publishing.py; immutable price history. | RESTRICT | wa_backend/alembic/versions/e5a1c9d4b7f2_stage5_temporal_pricing_foundation.py:114 |
| FK28 | PriceBookAssignment / price_book_assignments.(company_id, created_by) | wa_backend/models.py:1535 | PRINCIPAL_ACTOR | Assignment creator actor_id (publishing.py:1708); scope_id assignment target is a different polymorphic contract, not this FK. | RESTRICT | wa_backend/alembic/versions/e5a1c9d4b7f2_stage5_temporal_pricing_foundation.py:231 |
| FK29 | DispatchLoadPlanLine / dispatch_load_plan_lines.(company_id, updated_by) | wa_backend/models.py:1720 | PRINCIPAL_ACTOR | updated_by is load-plan editor attribution; representative comes via dispatch_route_id, not this actor field. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:842 |
| FK30 | Visit / visits.(company_id, driver_id) | wa_backend/models.py:1751 | FIELD_REPRESENTATIVE | Field visit owner; driver.py tenant/driver-scoped queries and get_visit_details ownership check :3746. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:996 |
| FK31 | ShortageRequest / shortage_requests.(company_id, driver_id) | wa_backend/models.py:2104 | FIELD_REPRESENTATIVE | Representative whose shortage is requested; dispatch.py:4916/:5011 validates active non-admin Driver. | unspecified / DB default NO ACTION | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:1065 |
| FK32 | ImportLog / import_logs.(company_id, admin_id) | wa_backend/models.py:2169 | PRINCIPAL_ACTOR | Legacy importer/admin attribution, explicitly retained actor history (models.py:2166 onward, plan Phase 9). No inferred representative. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:515 |
| FK33 | SystemAuditLog / system_audit_logs.(company_id, admin_id) | wa_backend/models.py:2205 | PRINCIPAL_ACTOR | Current actor across field/admin commands; inventory_permissions.py:30, dispatch.py:165 and driver operation audit evidence. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:391 |
| FK34 | DomainAuditEvent / domain_audit_events.(company_id, actor_user_id) | wa_backend/models.py:2230 | PRINCIPAL_ACTOR | Generic audit actor_user_id, product_lifecycle.py:324 + services record_domain_event calls. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:236 |
| FK35 | InventoryDamageEvent / inventory_damage_events.(company_id, source_driver_id) | wa_backend/models.py:2339 | AMBIGUOUS | AD07: source_driver_id has no active Runtime writer/consumer beyond model; name and historical baseline alone do not prove channel or actor meaning. No migration target inferred. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:1295 |
| FK36 | InventoryDamageEvent / inventory_damage_events.(company_id, receiving_admin_id) | wa_backend/models.py:2345 | AMBIGUOUS | AD07: receiving_admin_id has no active Runtime writer/consumer beyond model; name and historical baseline alone do not prove channel or actor meaning. No migration target inferred. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:1294 |
| FK37 | RefreshToken / refresh_tokens.(driver_id) | wa_backend/models.py:2400 | PRINCIPAL_ACTOR | Credential principal of both login channels; auth.py:129, :187, :340. Not a field profile. Single-column FK lacks persisted tenant/channel. | CASCADE | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:367 |
| FK38 | OperationIdempotency / operation_idempotency.(company_id, created_by) | wa_backend/models.py:2428 | PRINCIPAL_ACTOR | Replay must bind same actor, input and tenant operation; services.py:2852–2949. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:299 |
| FK39 | TenantOperationalPolicy / tenant_operational_policies.(company_id, created_by) | wa_backend/models.py:2620 | PRINCIPAL_ACTOR | Creator/publisher of versioned transfer policy; warehouse/transfer_policy.py command actor. | RESTRICT | wa_backend/alembic/versions/dfe93e142cea_stage4e2a_tenant_transfer_destination_.py:81 |
| FK40 | TenantOperationalPolicy / tenant_operational_policies.(company_id, approved_by) | wa_backend/models.py:2626 | PRINCIPAL_ACTOR | Creator/publisher of versioned transfer policy; warehouse/transfer_policy.py command actor. | RESTRICT | wa_backend/alembic/versions/dfe93e142cea_stage4e2a_tenant_transfer_destination_.py:87 |
| FK41 | InventoryMovement / inventory_movements.(company_id, performed_by) | wa_backend/models.py:2944 | PRINCIPAL_ACTOR | Performer of field stock exit or Backoffice stock mutation; services.py:4195; driver.py:1777/:2865/:3095; dispatch.py:1701. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:1225 |
| FK42 | InventoryTransferHeader / inventory_transfer_headers.(company_id, dispatched_by) | wa_backend/models.py:3113 | PRINCIPAL_ACTOR | Action actor for dispatched_by; warehouse/transfers.py:2427/:2882/:3004/:3134 and field handshake driver.py; do not confuse receiver action with expected field representative. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:592 |
| FK43 | InventoryTransferHeader / inventory_transfer_headers.(company_id, received_by) | wa_backend/models.py:3115 | PRINCIPAL_ACTOR | Action actor for received_by; warehouse/transfers.py:2427/:2882/:3004/:3134 and field handshake driver.py; do not confuse receiver action with expected field representative. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:594 |
| FK44 | InventoryTransferHeader / inventory_transfer_headers.(company_id, cancelled_by) | wa_backend/models.py:3117 | PRINCIPAL_ACTOR | Action actor for cancelled_by; warehouse/transfers.py:2427/:2882/:3004/:3134 and field handshake driver.py; do not confuse receiver action with expected field representative. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:590 |
| FK45 | InventoryTransferHeader / inventory_transfer_headers.(company_id, expected_receiver_id) | wa_backend/models.py:3119 | FIELD_REPRESENTATIVE | HANDSHAKE-only receiver bound to route.driver_id; models handshake/receiver-scope constraints; dispatch.py:2228 and driver.py:2743/:3190. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:593 |
| FK46 | InventoryTransferLine / inventory_transfer_lines.(company_id, fefo_overridden_by) | wa_backend/models.py:3326 | PRINCIPAL_ACTOR | FEFO override performer, warehouse/transfers.py:2501; physical batch allocation authority stays separate. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:891 |
| FK47 | StocktakeSession / stocktake_sessions.(company_id, started_by) | wa_backend/models.py:3379 | PRINCIPAL_ACTOR | Starter/approver/canceller/recount authorizer; stocktake.py:2259/:2473 and services.py:4510. Starter can be owning field actor in VEHICLE_RECON. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:949 |
| FK48 | StocktakeSession / stocktake_sessions.(company_id, approved_by) | wa_backend/models.py:3380 | PRINCIPAL_ACTOR | Starter/approver/canceller/recount authorizer; stocktake.py:2259/:2473 and services.py:4510. Starter can be owning field actor in VEHICLE_RECON. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:942 |
| FK49 | StocktakeSession / stocktake_sessions.(company_id, cancelled_by) | wa_backend/models.py:3381 | PRINCIPAL_ACTOR | Starter/approver/canceller/recount authorizer; stocktake.py:2259/:2473 and services.py:4510. Starter can be owning field actor in VEHICLE_RECON. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:943 |
| FK50 | StocktakeSession / stocktake_sessions.(company_id, pending_recount_authorized_by) | wa_backend/models.py:3382 | PRINCIPAL_ACTOR | Starter/approver/canceller/recount authorizer; stocktake.py:2259/:2473 and services.py:4510. Starter can be owning field actor in VEHICLE_RECON. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:945 |
| FK51 | StocktakeLine / stocktake_lines.(company_id, discovered_by) | wa_backend/models.py:3506 | PRINCIPAL_ACTOR | Discovery by authenticated counter, stocktake.py:1922; not automatically the representative whose vehicle is reconciled. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:1125 |
| FK52 | StocktakeCountAttempt / stocktake_count_attempts.(company_id, counted_by) | wa_backend/models.py:3550 | PRINCIPAL_ACTOR | counted_by=current actor (:1947); authorized_by separately password/capability verified recount actor (:2350 onward); separation preserved. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:1095 |
| FK53 | StocktakeCountAttempt / stocktake_count_attempts.(company_id, authorized_by) | wa_backend/models.py:3556 | PRINCIPAL_ACTOR | counted_by=current actor (:1947); authorized_by separately password/capability verified recount actor (:2350 onward); separation preserved. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:1094 |
| FK54 | InventoryLock / inventory_locks.(company_id, created_by) | wa_backend/models.py:3642 | PRINCIPAL_ACTOR | Lock creator/releaser operational actor; services.py:4522 and stocktake lock release. Not custody owner. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:1029 |
| FK55 | InventoryLock / inventory_locks.(company_id, released_by) | wa_backend/models.py:3643 | PRINCIPAL_ACTOR | Lock creator/releaser operational actor; services.py:4522 and stocktake lock release. Not custody owner. | RESTRICT | wa_backend/alembic/versions/000000000001_initial_schema_baseline.py:1033 |

FK totals: PRINCIPAL_ACTOR=45; BACKOFFICE_USER=2; FIELD_REPRESENTATIVE=5; AMBIGUOUS=3; unclassified=0. BACKOFFICE_USER labels derive from the frozen target grant semantics, not an undocumented current field filter. PRINCIPAL_ACTOR includes login/session principal references.

Migration source inspection found 55 upgrade-side drivers-targeting declarations (including 4 inline SQL declarations), matching the model relationship set when mapped by table+local columns. Code head is `c6f1a4d8e203`; the Alembic metadata imports include Offers, Taxation, Sales Evidence, Sales Returns and Suppliers. Sales Evidence and supplier receipt evidence have no extra direct drivers FK. No migrations were run; physical deployed schema/orphans remain a future preflight gate. Constraint mapping is by table/columns, retaining explicit names and deletion behavior. InventoryCostPolicy.selected_by uses `fk_inventory_cost_policy_tenant_selector` in both current model and migration. Physical deployed names still require later database preflight.

## 6. Frontend contracts beyond direct flag hits

| Surface | Actual identity contract | Evidence / boundaries |
|---|---|---|
| Dashboard Login | response driver_id is credential identity; is_admin/dashboard_access gates UI; localStorage driver_id scopes caches/drafts; is_admin chooses '/' vs '/inventory'. | Login.tsx:25, :100–131; frontend checks are UX only. |
| Dashboard InventoryAccess | driver_id numeric principal contract; is_company_admin marks inherited full authority; company/location permissions are separate sets. | hooks/useInventoryAccess.ts:15, :53–79, :119–151. No primary Owner relation here. |
| Inventory access manager | users id is shared Driver.id; raw is_admin labels full admin; request user_id and grant ids target shared table. | TabInventoryAccess.tsx:9, :100, :167, :256; API users/grants inventory_permissions.py. |
| Dashboard cache/durable commands | driver_id is current actor suffix in product lifecycle, product-location, supplier, quality, batch, drafts and display preferences. | Complete production ledger below. Do not substitute the assigned route representative into principal cache scopes. |
| Dashboard Dispatch | request driver_id is assigned FIELD_REPRESENTATIVE. | DispatchBoard.tsx:821; separate from stored Dashboard driver_id even though both are integers. |
| Dashboard vehicle reconciliation | response driver_id identifies WorkSession representative. | stocktake/types.ts:154 and parsers.ts:259–261; not the counter/approver's principal. |
| Flutter secure storage | driver_id + company_code reconstruct local auth; changing representative clears own session/cache; token/refresh are separate keys. | auth_bloc.dart:38, :94, :114, :159, :209. |
| Flutter offline | toggle_break stores driver_id with action; online sends action while server derives current actor. | dashboard_repository.dart:36–59 and :107–110; dashboard_bloc calls getDriverId/toggleBreak; sync_repository consumes persisted queue. |
| Flutter typed propagation | AuthAuthenticated.driverId → screens → Dashboard events and repository calls; DriverId spelling variants are Runtime contracts too. | auth_state.dart, dashboard_event.dart, dashboard_screen.dart, splash_screen.dart, login_screen.dart, auth_bloc.dart. Complete broad ledger below. |
| Flutter refresh | /driver/login is interceptor auth-path exclusion; /refresh rotates stored pair with serialized refresh and original-request replay. | core/network/api_client.dart:80–152. No is_admin consumption found. |

Planning grep totals are not silently reused: the final exact/broad counter table and file ledger below use this baseline, not the approximate planning numbers. Source/test/historical evidence remains separate.

## 7. ARCHITECTURE DECISIONS REQUIRED

These are escalations for the owner/primary lead. The worker has stopped every dependent target-policy/remapping conclusion. Completing the source inventory does not satisfy the later schema/backfill/cutover gates.

| ID | AMBIGUOUS question / required decision | Concrete evidence | Dependent inference stopped |
|---|---|---|---|
| AD01 | Freeze exact new capability codes and ownership for admin-only branch, role/grant, shop/territory, shortage, work-session and sales-return endpoints, and branch-option metadata visibility relative to any-location location.create/update admission. Matrix candidates are review proposals only. | 36 get_current_admin registrations; capability catalog currently contains 55 codes and no generic admin.* replacement. | No new catalog, guards, role bundles, or broader access granted. |
| AD02 | Which minimum-stock and Stocktake supervisor behaviors may be delegated by exact capability, and which need protected Owner/supervisor authority? Preserve password confirmation and independent-counter/recount constraints. | inventory_stock_policy.py:242/:680; stocktake.py:2038/:2429; services.py:4788 posting requires active is_admin=True; recount credentials use stocktake.recount. | No assumption that inventory.read authorizes threshold mutation; no removal of second supervisory gate; proposed mutation capability remains AMBIGUOUS. |
| AD03 | Freeze delegated company vs stored session/representative/route/vehicle/location scope for operational/financial reports, session authorization/reopen/settlement, shortages, official returns and privileged archive navigation. | dispatch.py admin session/shortage endpoints; archive helpers gate OPEN_SHORTAGE/OPEN_CUSTODY on is_admin; sales_returns.py and stock movement service. | No guessed narrow report scope, extra location authority or broad admin bypass. |
| AD04 | Freeze access policy for shared Visit details and field reconciliation helper privilege once Backoffice and field principals are separate. | driver.py:3746 owner OR admin; reconciliation.py own-session filter; services.py:4430/:4610 allow own owner OR admin internally. | No conflation of credential id with representative id; no implicit Backoffice field login or privileged field workflow. |
| AD05 | Company-wide /ws/dispatch broadcast currently admits only admin. Define capability/subscription scope for restricted Backoffice users, revocation and topic visibility before broadening it. | main.py:459; realtime/auth.py:64; ws_manager.py company-keyed broadcast. | dispatch.read alone is not asserted sufficient to receive all company events. |
| AD06 | Resolve Shop.added_by_driver_id meaning: preserve generic creator provenance vs separate field provenance with deterministic historical mapping. | driver.py:3344 field creator; dispatch.py:3363/:5408 Backoffice creator; model FK :1169. | FK class AMBIGUOUS; no field-only remap and no loss/reassignment of Backoffice authors. |
| AD07 | Resolve dormant InventoryDamageEvent.source_driver_id and receiving_admin_id from approved workflow/history before target classification. | models.py:2339/:2345; no current Runtime writers found (source census excludes historical snapshots). | Both FK classes AMBIGUOUS; no classification from column names or old fixtures. |
| AD08 | Explicit per-company Owner selection and dual-use legacy-row classification need real data plus owner-approved mapping. is_admin=True alone cannot pick one primary owner or silently enable two channels. | shared Driver credential/field model; role/location tables accept generic Drivers; target plan Phase 3. | No owner candidate, dual-use split, numeric-id reuse or historical data remap chosen. |
| AD09 | Final channel/session contract and safe legacy refresh cutover (convert vs revoke), including stored row/successor identity binding, must be frozen. | /driver/login permits any active Driver; /login admits any inventory grant; _refresh_role claim/fallback; RefreshToken has no company/channel; :277 reloads subject without explicit row.driver_id match. | No new JWT fields, session schema, token migration, or inferred channel conversion. Existing source findings only. |
| AD10 | Full capability authority vs legacy structural-check shortcuts: decide treatment of old routes missing source/vehicle and exact-location readiness checks during cutover. | dispatch_access.py:27/:44 returns before structural validation for admin; live_stock.py:230 returns before restricted warehouse checks. | Owner full capabilities do not authorize this worker to skip tenant/location existence or reinterpret historical route state. |

There are **3 AMBIGUOUS FK relationships** and **24 matrix registrations with explicitly AMBIGUOUS capability/scope**. AD01 applies to every proposed new capability name even where current workflow is clear; those proposals are not automatically counted as semantic ambiguity. AD08 needs data, not source guessing. Ambiguity is not an unclassified entry.

## 8. Verification and handoff limits

One source-based verification checks the token ledger against fresh tracked-source searches, matrix registrations against the dependency census, all 55 FK table+column mappings, category completeness, duplicate entries, markdown column integrity, and changed-file allowlist. No application tests/builds/DB commands are appropriate for this documentation-only task, and none was run. No claim is made that Runtime auth or migration bootstrap passed acceptance.

Gate 1 **inventory coverage** is represented here: zero uncategorized is_admin occurrences, zero unrecorded affected route registrations, zero unclassified drivers FK. **Lead/owner review, capability freeze, ambiguous semantic resolution and data preflight remain OPEN**. The canonical migration plan and RUN.txt have not been edited or marked complete by this worker.

Static census verification **PASS** at the pinned SHA: 174 categorized source occurrences, 237 affected registrations, 36 admin dependency endpoints, 55 FK relationships, 24 explicitly ambiguous matrix registrations; 1,398 raw evidence lines resolve to their normalized source and 42 Markdown tables have consistent column widths. Branch and single-file write allowlist passed. Git whitespace check reports no document errors (the no-index command returns 1 because the document is a new file; only the repository CRLF conversion notice remains).

## Appendix A — Exact Runtime identity source inventory

The following appendices retain file/line/source evidence and code-first read summaries. The exact-word census is complemented by compound-identifier union ledgers (Dashboard selectedDriverId and Flutter driverIdString/oldDriverId), so aliases are not dropped. They are not implementation instructions. Within the report, repository-relative paths refer to the pinned source SHA above.

### Backend — Driver/driver_id compound and exact source hits

| File | Matched lines | Source role / interpretation |
|---|---|---|
| wa_backend/api/auth.py | 18 | Credential/principal/auth transport; separate field ownership from authentication. |
| wa_backend/api/branches.py | 8 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/catalog.py | 37 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/commercial_policy.py | 4 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/dependencies.py | 9 | Credential/principal/auth transport; separate field ownership from authentication. |
| wa_backend/api/dispatch.py | 186 | Mixed field ownership and authenticated action actor; use exact function/FK mapping. |
| wa_backend/api/driver.py | 106 | Mixed field ownership and authenticated action actor; use exact function/FK mapping. |
| wa_backend/api/inventory_permissions.py | 21 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/inventory_stock_policy.py | 5 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/offers.py | 23 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/platform_manager.py | 2 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/pricing.py | 20 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/product_locations.py | 5 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/product_tracking.py | 6 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/reconciliation.py | 10 | Mixed field ownership and authenticated action actor; use exact function/FK mapping. |
| wa_backend/api/sales_returns.py | 6 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/simple_products.py | 13 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/suppliers.py | 6 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/taxation.py | 25 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/tenant.py | 2 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/inbound.py | 5 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/inbound_adjustments.py | 2 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/ledger.py | 7 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/live_stock.py | 11 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/locations.py | 7 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/status.py | 2 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/stocktake.py | 32 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/transfer_policy.py | 4 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/transfers.py | 20 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/whole_product_quality.py | 2 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/warehouse/whole_product_quality_preview.py | 2 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/domains/credential_confirmation.py | 2 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/domains/dispatch_reservations.py | 2 | Mixed field ownership and authenticated action actor; use exact function/FK mapping. |
| wa_backend/domains/inventory_batch_restrictions/queries.py | 2 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/domains/inventory_catalog_presence.py | 2 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/domains/pricing/driver_authority.py | 5 | Field price/display/sale context; generic creator/approver remain principal (FK matrix). |
| wa_backend/domains/pricing/driver_display.py | 5 | Field price/display/sale context; generic creator/approver remain principal (FK matrix). |
| wa_backend/domains/sales_calculation/driver_sale.py | 18 | Field price/display/sale context; generic creator/approver remain principal (FK matrix). |
| wa_backend/domains/simple_products/imports/api/router.py | 21 | Principal/job actor reload and tenant-safe async attribution. |
| wa_backend/domains/simple_products/imports/infrastructure/repository.py | 6 | Principal/job actor reload and tenant-safe async attribution. |
| wa_backend/domains/simple_products/service.py | 9 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/inventory_access.py | 6 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/main.py | 1 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/models.py | 41 | Persistence/DTO contracts; column meaning is classified in FK matrix. |
| wa_backend/product_lifecycle.py | 1 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/realtime/auth.py | 7 | Credential/principal/auth transport; separate field ownership from authentication. |
| wa_backend/schemas.py | 11 | Persistence/DTO contracts; column meaning is classified in FK matrix. |
| wa_backend/services.py | 16 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/tools/staging_load/wanasah_d7s_mixed_load_config.py | 6 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py | 17 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/workers/tasks/handshake.py | 6 | Principal/job actor reload and tenant-safe async attribution. |
| wa_backend/workers/tasks/session_monitor.py | 10 | Principal/job actor reload and tenant-safe async attribution. |

#### wa_backend/api/auth.py

```text
wa_backend/api/auth.py:7 from models import Driver, SystemAuditLog, TokenBlacklist, RefreshToken, utc_now
wa_backend/api/auth.py:37 def create_access_token(data: dict, company_id: int, role_name: str = "Driver"):
wa_backend/api/auth.py:88 @router.post("/driver/login", response_model=LoginResponse)
wa_backend/api/auth.py:109     stmt = select(Driver).filter_by(username=payload.username, company_id=comp_id, is_active=True)
wa_backend/api/auth.py:126     access_token = create_access_token({"sub": str(driver.id), "is_admin": driver.is_admin, "username": driver.username}, company_id=comp_id, role_name="Driver")
wa_backend/api/auth.py:127     refresh_token = create_refresh_token({"sub": str(driver.id), "role": "Driver"}, company_id=comp_id)
wa_backend/api/auth.py:129     db.add(RefreshToken(token=refresh_token, driver_id=driver.id, expires_at=utc_now() + timedelta(days=30)))
wa_backend/api/auth.py:136         "driver_id": driver.id,
wa_backend/api/auth.py:161     stmt = select(Driver).filter_by(username=payload.username, company_id=comp_id, is_active=True)
wa_backend/api/auth.py:187     db.add(RefreshToken(token=refresh_token, driver_id=admin.id, expires_at=utc_now() + timedelta(days=30)))
wa_backend/api/auth.py:194         "driver_id": admin.id,
wa_backend/api/auth.py:202 def _refresh_role(decoded: dict, driver: Driver) -> str:
wa_backend/api/auth.py:204     if role in {"Admin", "Inventory", "Driver"}:
wa_backend/api/auth.py:206     return "Admin" if driver.is_admin else "Driver"
wa_backend/api/auth.py:249         driver_id = int(decoded.get("sub", 0))
wa_backend/api/auth.py:252         if not driver_id or not company_id:
wa_backend/api/auth.py:279         driver = await db.get(Driver, driver_id)
wa_backend/api/auth.py:340             driver_id=driver.id,
```


#### wa_backend/api/branches.py

```text
wa_backend/api/branches.py:18 from models import Branch, Driver, SystemAuditLog
wa_backend/api/branches.py:186     current_driver: Driver = Depends(get_current_driver),
wa_backend/api/branches.py:208     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/branches.py:225     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/branches.py:291     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/branches.py:364     current_admin: Driver,
wa_backend/api/branches.py:427     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/branches.py:443     current_admin: Driver = Depends(get_current_admin),
```


#### wa_backend/api/catalog.py

```text
wa_backend/api/catalog.py:29     Driver,
wa_backend/api/catalog.py:285 async def _require(db: AsyncSession, actor: Driver, permission: str) -> None:
wa_backend/api/catalog.py:574 def _audit(db: AsyncSession, actor: Driver, target: str, action: str, old: Any, new: Any) -> None:
wa_backend/api/catalog.py:584     db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:596     db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:611     payload: ProductCreate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:637     product_id: int, payload: ProductUpdate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:674     db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:694     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:717     payload: VariantCreate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:757     variant_id: int, payload: VariantUpdate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:800     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:879     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:950 async def list_conversions(variant_id: int, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:961 async def create_conversion(variant_id: int, payload: ConversionCreate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:993     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:1073     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:1124 async def create_barcode(variant_id: int, payload: BarcodeCreate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1171     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:1270     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:1352 async def update_barcode(barcode_id: int, payload: BarcodeUpdate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1390 async def parse_gs1_endpoint(payload: Gs1Request, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1406     actor: Driver,
wa_backend/api/catalog.py:1620 async def publish_variant(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1660     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:1698     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:1793 async def retire_variant(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1798 async def restore_variant(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1806     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:1857 async def variant_archive_preflight(variant_id: int, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1876 async def archive_variant(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1881 async def place_variant_sales_hold(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1886 async def release_variant_sales_hold(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1894     actor: Driver = Depends(get_current_driver),
wa_backend/api/catalog.py:1922 async def recall_variant(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1927 async def cancel_variant_recall(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/catalog.py:1932 async def close_variant_recall(variant_id: int, payload: CloseRecallCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
```


#### wa_backend/api/commercial_policy.py

```text
wa_backend/api/commercial_policy.py:22 from models import Driver, SystemAuditLog
wa_backend/api/commercial_policy.py:67     actor: Driver,
wa_backend/api/commercial_policy.py:93     actor: Driver = Depends(get_current_driver),
wa_backend/api/commercial_policy.py:115     actor: Driver = Depends(get_current_driver),
```


#### wa_backend/api/dependencies.py

```text
wa_backend/api/dependencies.py:7 from models import Driver, TokenBlacklist
wa_backend/api/dependencies.py:25         driver_id_int, comp_id_int = access_token_identity(payload)
wa_backend/api/dependencies.py:50         # Driver + حالة blacklist معاً، بدون إسقاط أي فحص أمني.
wa_backend/api/dependencies.py:58                 Driver,
wa_backend/api/dependencies.py:62                 Driver.id == driver_id_int,
wa_backend/api/dependencies.py:63                 Driver.company_id == comp_id_int,
wa_backend/api/dependencies.py:119 async def get_current_driver_owned(driver_id: int, current_driver: Driver = Depends(get_current_driver)):
wa_backend/api/dependencies.py:121     if current_driver.id != driver_id and not current_driver.is_admin:
wa_backend/api/dependencies.py:126 async def get_current_admin(current_driver: Driver = Depends(get_current_driver)):
```


#### wa_backend/api/dispatch.py

```text
wa_backend/api/dispatch.py:48     Driver,
wa_backend/api/dispatch.py:107 from schemas import ( MessageResponse, AuthorizeSessionRequest, AdminDashboardDriverResponse,
wa_backend/api/dispatch.py:130     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:150     if session.driver_id == current_admin.id:
wa_backend/api/dispatch.py:163                 target_id=f"Session_{session.id}_Driver_{session.driver_id}",
wa_backend/api/dispatch.py:551         select(WorkSession.id, WorkSession.driver_id, WorkSession.end_time)
wa_backend/api/dispatch.py:613 @router.get("/admin/sessions/today", response_model=List[AdminDashboardDriverResponse], status_code=200)
wa_backend/api/dispatch.py:616     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:769     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:902     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:1025             target_id=f"Session_{session.id}_Driver_{session.driver_id}",
wa_backend/api/dispatch.py:1060     current_admin: Driver = Depends(get_current_driver)
wa_backend/api/dispatch.py:1070         select(Driver).filter_by(company_id=company_id, is_active=True, is_admin=False).order_by(Driver.id.asc())
wa_backend/api/dispatch.py:1372     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/dispatch.py:1386                 select(Driver)
wa_backend/api/dispatch.py:1389                     id=payload.driver_id,
wa_backend/api/dispatch.py:1393                 .order_by(Driver.id.asc())
wa_backend/api/dispatch.py:1473                     driver_id=payload.driver_id,
wa_backend/api/dispatch.py:1493                     WorkSession.driver_id == payload.driver_id,
wa_backend/api/dispatch.py:1516                         DispatchRoute.driver_id == payload.driver_id,
wa_backend/api/dispatch.py:1575             driver_id=payload.driver_id,
wa_backend/api/dispatch.py:1723                     f"pending-visit:{payload.driver_id}:{shop_id}"
wa_backend/api/dispatch.py:1731                         Visit.driver_id == payload.driver_id,
wa_backend/api/dispatch.py:1758                             ShortageRequest.driver_id == payload.driver_id,
wa_backend/api/dispatch.py:1759                             ShortageRequest.driver_id.is_(None),
wa_backend/api/dispatch.py:1773                         driver_id=payload.driver_id,
wa_backend/api/dispatch.py:1832     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/dispatch.py:1912     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/dispatch.py:2017                 driver_id=route.driver_id,
wa_backend/api/dispatch.py:2054     driver_id: int,
wa_backend/api/dispatch.py:2077                 InventoryTransferHeader.expected_receiver_id == driver_id,
wa_backend/api/dispatch.py:2103     admin: Driver,
wa_backend/api/dispatch.py:2228                 expected_receiver_id=route.driver_id,
wa_backend/api/dispatch.py:2360     admin: Driver,
wa_backend/api/dispatch.py:2386             driver_id=route.driver_id,
wa_backend/api/dispatch.py:2472     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/dispatch.py:2517         if route is None or route.driver_id is None or route.vehicle_id is None:
wa_backend/api/dispatch.py:2549                 driver_id=route.driver_id,
wa_backend/api/dispatch.py:2631     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/dispatch.py:2748     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/dispatch.py:2762     if route is None or route.driver_id is None or route.vehicle_id is None:
wa_backend/api/dispatch.py:2788                 InventoryTransferHeader.expected_receiver_id == route.driver_id,
wa_backend/api/dispatch.py:2904     current_admin: Driver = Depends(get_current_driver)
wa_backend/api/dispatch.py:3046                     DispatchRoute.driver_id == Visit.driver_id,
wa_backend/api/dispatch.py:3073     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:3234     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:3363             added_by_driver_id=current_admin.id,
wa_backend/api/dispatch.py:3395     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/dispatch.py:3436     driver_ids = list({r.driver_id for r in routes if r.driver_id})
wa_backend/api/dispatch.py:3448     if driver_ids:
wa_backend/api/dispatch.py:3449         stmt_drivers = select(Driver.id, Driver.full_name).filter(
wa_backend/api/dispatch.py:3450             Driver.company_id == current_admin.company_id,
wa_backend/api/dispatch.py:3451             Driver.id.in_(driver_ids)
wa_backend/api/dispatch.py:3458     if driver_ids:
wa_backend/api/dispatch.py:3464             stmt_pending = select(Visit.driver_id, func.count(Visit.id).label('pending_count')).join(
wa_backend/api/dispatch.py:3469                 Visit.driver_id.in_(driver_ids),
wa_backend/api/dispatch.py:3472             ).group_by(Visit.driver_id)
wa_backend/api/dispatch.py:3476             pending_visits_map = {row.driver_id: row.pending_count for row in pending_counts}
wa_backend/api/dispatch.py:3497         Visit.driver_id.is_(None) # استخدام is_(None) للآمان في SQLAlchemy
wa_backend/api/dispatch.py:3507         if r.status == 'active' and r.driver_id:
wa_backend/api/dispatch.py:3508             shops_remaining = pending_visits_map.get(r.driver_id, 0)
wa_backend/api/dispatch.py:3518             "driverId": str(r.driver_id) if r.driver_id else "",
wa_backend/api/dispatch.py:3519             "driverName": drivers_map.get(r.driver_id, "بدون مندوب") if r.driver_id else "بدون مندوب",
wa_backend/api/dispatch.py:3540     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/dispatch.py:3553                     DispatchRoute.driver_id,
wa_backend/api/dispatch.py:3567         snap_driver_id = int(snapshot.driver_id) if snapshot.driver_id is not None else None
wa_backend/api/dispatch.py:3577         requested_driver_id = (
wa_backend/api/dispatch.py:3578             int(payload.driverId) if payload.driverId is not None else snap_driver_id
wa_backend/api/dispatch.py:3597                         driver_id=snap_driver_id,
wa_backend/api/dispatch.py:3610             if snap_driver_id is not None:
wa_backend/api/dispatch.py:3613                         select(Driver)
wa_backend/api/dispatch.py:3616                             id=snap_driver_id,
wa_backend/api/dispatch.py:3618                         .order_by(Driver.id.asc())
wa_backend/api/dispatch.py:3666                 route.driver_id,
wa_backend/api/dispatch.py:3673                 snap_driver_id,
wa_backend/api/dispatch.py:3686             target_driver_id = (
wa_backend/api/dispatch.py:3687                 int(payload.driverId) if payload.driverId is not None else route.driver_id
wa_backend/api/dispatch.py:3692             driver_changed = target_driver_id != route.driver_id
wa_backend/api/dispatch.py:3734             driver_ids_to_lock = sorted({
wa_backend/api/dispatch.py:3735                 int(driver_id)
wa_backend/api/dispatch.py:3736                 for driver_id in (snap_driver_id, requested_driver_id)
wa_backend/api/dispatch.py:3737                 if driver_id is not None
wa_backend/api/dispatch.py:3740             if driver_ids_to_lock:
wa_backend/api/dispatch.py:3743                         select(Driver)
wa_backend/api/dispatch.py:3745                             Driver.company_id == company_id,
wa_backend/api/dispatch.py:3746                             Driver.id.in_(driver_ids_to_lock),
wa_backend/api/dispatch.py:3748                         .order_by(Driver.id.asc())
wa_backend/api/dispatch.py:3754             if requested_driver_id is not None:
wa_backend/api/dispatch.py:3755                 target_driver = driver_map.get(requested_driver_id)
wa_backend/api/dispatch.py:3813                 route.driver_id,
wa_backend/api/dispatch.py:3820                 snap_driver_id,
wa_backend/api/dispatch.py:3833             target_driver_id = (
wa_backend/api/dispatch.py:3834                 int(payload.driverId) if payload.driverId is not None else route.driver_id
wa_backend/api/dispatch.py:3839             driver_changed = target_driver_id != route.driver_id
wa_backend/api/dispatch.py:3843         old_driver_id = route.driver_id
wa_backend/api/dispatch.py:3885             if target_driver_id is None or target_vehicle_id is None:
wa_backend/api/dispatch.py:3904                             DispatchRoute.driver_id == target_driver_id,
wa_backend/api/dispatch.py:3919         if bound_session is None and target_driver_id is not None and driver_changed:
wa_backend/api/dispatch.py:3925                         WorkSession.driver_id == target_driver_id,
wa_backend/api/dispatch.py:3955             route.driver_id = target_driver_id
wa_backend/api/dispatch.py:4035         if driver_changed and old_driver_id is not None:
wa_backend/api/dispatch.py:4040                     Visit.driver_id == old_driver_id,
wa_backend/api/dispatch.py:4045                 .values(driver_id=route.driver_id)
wa_backend/api/dispatch.py:4054                         ShortageRequest.driver_id == old_driver_id,
wa_backend/api/dispatch.py:4055                         ShortageRequest.driver_id.is_(None),
wa_backend/api/dispatch.py:4058                 .values(driver_id=route.driver_id)
wa_backend/api/dispatch.py:4061         if target_status in {"closed", "waiting", "postponed"} and route.driver_id is not None:
wa_backend/api/dispatch.py:4066                     Visit.driver_id == route.driver_id,
wa_backend/api/dispatch.py:4071                     driver_id=None,
wa_backend/api/dispatch.py:4081                     ShortageRequest.driver_id == route.driver_id,
wa_backend/api/dispatch.py:4083                 .values(driver_id=None)
wa_backend/api/dispatch.py:4086         if target_status == "active" and route.driver_id is not None:
wa_backend/api/dispatch.py:4107                         f"pending-visit:{route.driver_id}:{shop_id}"
wa_backend/api/dispatch.py:4119                         Visit.driver_id.is_(None),
wa_backend/api/dispatch.py:4122                         driver_id=route.driver_id,
wa_backend/api/dispatch.py:4132                         ShortageRequest.driver_id.is_(None),
wa_backend/api/dispatch.py:4134                     .values(driver_id=route.driver_id)
wa_backend/api/dispatch.py:4141                             Visit.driver_id == route.driver_id,
wa_backend/api/dispatch.py:4168                                 ShortageRequest.driver_id == route.driver_id,
wa_backend/api/dispatch.py:4169                                 ShortageRequest.driver_id.is_(None),
wa_backend/api/dispatch.py:4183                             driver_id=route.driver_id,
wa_backend/api/dispatch.py:4196             or old_driver_id != route.driver_id
wa_backend/api/dispatch.py:4208                         f"status={old_status}|driver={old_driver_id}|vehicle={old_vehicle_id}"
wa_backend/api/dispatch.py:4211                         f"status={route.status}|driver={route.driver_id}|vehicle={route.vehicle_id}|"
wa_backend/api/dispatch.py:4268     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:4295                 select(Driver)
wa_backend/api/dispatch.py:4298                     id=session.driver_id,
wa_backend/api/dispatch.py:4302                 .order_by(Driver.id.asc())
wa_backend/api/dispatch.py:4318                     driver_id=session.driver_id,
wa_backend/api/dispatch.py:4364                     WorkSession.driver_id == session.driver_id,
wa_backend/api/dispatch.py:4383             target_id=f"Session_{session.id}_Driver_{session.driver_id}",
wa_backend/api/dispatch.py:4407     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4467     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4532     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4592     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4614     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4672     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4848     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:4875         "driverId": str(s.driver_id) if s.driver_id else "",
wa_backend/api/dispatch.py:4895     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:4907         driver_ids = sorted({int(item.driverId) for item in payload if item.driverId is not None})
wa_backend/api/dispatch.py:4909         if driver_ids:
wa_backend/api/dispatch.py:4911                 select(Driver).filter(
wa_backend/api/dispatch.py:4912                     Driver.company_id == company_id,
wa_backend/api/dispatch.py:4913                     Driver.id.in_(driver_ids),
wa_backend/api/dispatch.py:4914                 ).order_by(Driver.id.asc()).with_for_update()
wa_backend/api/dispatch.py:4917             if valid != set(driver_ids):
wa_backend/api/dispatch.py:4985                         DispatchRoute.driver_id.is_not(None),
wa_backend/api/dispatch.py:4993                 route_driver_id = int(active_route.driver_id)
wa_backend/api/dispatch.py:4995                 if prior is not None and prior != route_driver_id:
wa_backend/api/dispatch.py:5000                 active_route_driver_by_zone[zone_id] = route_driver_id
wa_backend/api/dispatch.py:5002             auto_driver_ids = sorted(set(active_route_driver_by_zone.values()))
wa_backend/api/dispatch.py:5003             if auto_driver_ids:
wa_backend/api/dispatch.py:5006                         select(Driver)
wa_backend/api/dispatch.py:5008                             Driver.company_id == company_id,
wa_backend/api/dispatch.py:5009                             Driver.id.in_(auto_driver_ids),
wa_backend/api/dispatch.py:5010                             Driver.is_active.is_(True),
wa_backend/api/dispatch.py:5011                             Driver.is_admin.is_(False),
wa_backend/api/dispatch.py:5013                         .order_by(Driver.id.asc())
wa_backend/api/dispatch.py:5019                     zone_id: driver_id
wa_backend/api/dispatch.py:5020                     for zone_id, driver_id in active_route_driver_by_zone.items()
wa_backend/api/dispatch.py:5021                     if driver_id in valid_auto_ids
wa_backend/api/dispatch.py:5024         def resolve_shortage_driver_id(item: CreateShortageItem):
wa_backend/api/dispatch.py:5030             (driver_id, int(item.shopId))
wa_backend/api/dispatch.py:5032             for driver_id in [resolve_shortage_driver_id(item)]
wa_backend/api/dispatch.py:5033             if driver_id is not None
wa_backend/api/dispatch.py:5040                     f"pending-visit:{driver_id}:{shop_id}"
wa_backend/api/dispatch.py:5041                     for driver_id, shop_id in owner_pairs
wa_backend/api/dispatch.py:5047             owner_driver_ids = sorted({driver_id for driver_id, _ in owner_pairs})
wa_backend/api/dispatch.py:5052                     Visit.driver_id.in_(owner_driver_ids),
wa_backend/api/dispatch.py:5055                 ).order_by(Visit.driver_id.asc(), Visit.shop_id.asc(), Visit.id.asc()).with_for_update()
wa_backend/api/dispatch.py:5058                 key = (int(visit.driver_id), int(visit.shop_id))
wa_backend/api/dispatch.py:5081             driver_id = resolve_shortage_driver_id(item)
wa_backend/api/dispatch.py:5086                 driver_id=driver_id,
wa_backend/api/dispatch.py:5091             if driver_id is None:
wa_backend/api/dispatch.py:5094             owner_key = (driver_id, shop_id)
wa_backend/api/dispatch.py:5099                     driver_id=driver_id,
wa_backend/api/dispatch.py:5136     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:5141             select(ShortageRequest.shop_id, ShortageRequest.zone_id, ShortageRequest.driver_id).filter(
wa_backend/api/dispatch.py:5149         driver_id = int(pre.driver_id) if pre.driver_id is not None else None
wa_backend/api/dispatch.py:5171         if driver_id is not None:
wa_backend/api/dispatch.py:5176                     ShortageRequest.driver_id == driver_id,
wa_backend/api/dispatch.py:5185                         Visit.driver_id == driver_id,
wa_backend/api/dispatch.py:5193                         DispatchRoute.driver_id == driver_id,
wa_backend/api/dispatch.py:5231     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:5408                 added_by_driver_id=current_admin.id,
```


#### wa_backend/api/driver.py

```text
wa_backend/api/driver.py:32     Driver, WorkSession, DispatchRoute, Visit,
wa_backend/api/driver.py:60     DriverSaleInput,
wa_backend/api/driver.py:137 router = APIRouter(tags=["Driver Operations"])
wa_backend/api/driver.py:145     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:147     driver_id = current_driver.id
wa_backend/api/driver.py:154                 select(Driver)
wa_backend/api/driver.py:157                     id=driver_id,
wa_backend/api/driver.py:159                 .order_by(Driver.id.asc())
wa_backend/api/driver.py:180                     WorkSession.driver_id == driver_id,
wa_backend/api/driver.py:202                     driver_id=driver_id,
wa_backend/api/driver.py:243                     driver_id=driver_id,
wa_backend/api/driver.py:312             driver_id=driver_id,
wa_backend/api/driver.py:394                 Visit.driver_id == driver_id,
wa_backend/api/driver.py:442     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:445     driver_id = current_driver.id
wa_backend/api/driver.py:453                     driver_id=driver_id,
wa_backend/api/driver.py:479                     InventoryTransferHeader.expected_receiver_id == driver_id,
wa_backend/api/driver.py:513     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:516     driver_id = current_driver.id
wa_backend/api/driver.py:524                     driver_id=driver_id,
wa_backend/api/driver.py:589     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:594     driver_id = current_driver.id
wa_backend/api/driver.py:623             actor_id=driver_id,
wa_backend/api/driver.py:639                     driver_id=driver_id,
wa_backend/api/driver.py:665                     driver_id=driver_id,
wa_backend/api/driver.py:699                     driver_id=driver_id,
wa_backend/api/driver.py:733         if visit.driver_id != driver_id:
wa_backend/api/driver.py:751                     driver_id=driver_id,
wa_backend/api/driver.py:780                         ShortageRequest.driver_id.is_(None),
wa_backend/api/driver.py:781                         ShortageRequest.driver_id == driver_id,
wa_backend/api/driver.py:859                     InventoryTransferHeader.expected_receiver_id == driver_id,
wa_backend/api/driver.py:904                 admin_id=driver_id,
wa_backend/api/driver.py:909                     admin_id=driver_id,
wa_backend/api/driver.py:1058                     DriverSaleInput(
wa_backend/api/driver.py:1252                         Visit.driver_id == driver_id,
wa_backend/api/driver.py:1254                         WorkSession.driver_id == driver_id,
wa_backend/api/driver.py:1349                         "Driver sale boundary quantity does not match commercial calculation."
wa_backend/api/driver.py:1777                 performed_by=driver_id,
wa_backend/api/driver.py:1798                     driver_id,
wa_backend/api/driver.py:1855                         admin_id=driver_id,
wa_backend/api/driver.py:1881                         ShortageRequest.driver_id.is_(None),
wa_backend/api/driver.py:1882                         ShortageRequest.driver_id == driver_id,
wa_backend/api/driver.py:1900                         Visit.driver_id == active_session.driver_id,
wa_backend/api/driver.py:2250     driver_id: int,
wa_backend/api/driver.py:2258         driver_id=driver_id,
wa_backend/api/driver.py:2518     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:2521     driver_id = current_driver.id
wa_backend/api/driver.py:2528                 driver_id=driver_id,
wa_backend/api/driver.py:2544                     driver_id=driver_id,
wa_backend/api/driver.py:2557                     DispatchRoute.driver_id == driver_id,
wa_backend/api/driver.py:2623                     Visit.driver_id == driver_id,
wa_backend/api/driver.py:2638                     Visit.driver_id == driver_id,
wa_backend/api/driver.py:2650                     Visit.driver_id == driver_id,
wa_backend/api/driver.py:2670                     Visit.driver_id == driver_id,
wa_backend/api/driver.py:2728     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:2731     driver_id = current_driver.id
wa_backend/api/driver.py:2743                     expected_receiver_id=driver_id,
wa_backend/api/driver.py:2754         if response == "accepted" and header.status == "POSTED" and header.received_by == driver_id:
wa_backend/api/driver.py:2757         if response == "rejected" and header.status == "REJECTED" and header.received_by == driver_id:
wa_backend/api/driver.py:2781                     driver_id=driver_id,
wa_backend/api/driver.py:2796                 driver_id=driver_id,
wa_backend/api/driver.py:2865             performed_by=driver_id,
wa_backend/api/driver.py:2870         header.received_by = driver_id
wa_backend/api/driver.py:2889             admin_id=driver_id,
wa_backend/api/driver.py:2922     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:2925     driver_id = current_driver.id
wa_backend/api/driver.py:2943                     InventoryTransferHeader.expected_receiver_id == driver_id,
wa_backend/api/driver.py:2960             if request_item.status == "accepted" and header.status == "POSTED" and header.received_by == driver_id:
wa_backend/api/driver.py:2962             if request_item.status == "rejected" and header.status == "REJECTED" and header.received_by == driver_id:
wa_backend/api/driver.py:2993                         driver_id=driver_id,
wa_backend/api/driver.py:3011                     driver_id=driver_id,
wa_backend/api/driver.py:3095                     performed_by=driver_id,
wa_backend/api/driver.py:3102                 header.received_by = driver_id
wa_backend/api/driver.py:3121                     admin_id=driver_id,
wa_backend/api/driver.py:3153     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:3156     driver_id = current_driver.id
wa_backend/api/driver.py:3163                 driver_id=driver_id,
wa_backend/api/driver.py:3176         driver_id=driver_id,
wa_backend/api/driver.py:3190                 expected_receiver_id=driver_id,
wa_backend/api/driver.py:3255     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:3258     driver_id = current_driver.id
wa_backend/api/driver.py:3263         .filter_by(company_id=current_driver.company_id, driver_id=driver_id, end_time=None)
wa_backend/api/driver.py:3281             driver_id=driver_id,
wa_backend/api/driver.py:3344             added_by_driver_id=driver_id,
wa_backend/api/driver.py:3354             driver_id=driver_id,
wa_backend/api/driver.py:3383     driver_id: int,
wa_backend/api/driver.py:3390                 driver_id=driver_id,
wa_backend/api/driver.py:3405                     driver_id=driver_id,
wa_backend/api/driver.py:3418                     DispatchRoute.driver_id == driver_id,
wa_backend/api/driver.py:3433             context={"driver_id": int(driver_id)},
wa_backend/api/driver.py:3444     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:3447     driver_id = int(current_driver.id)
wa_backend/api/driver.py:3452             driver_id=driver_id,
wa_backend/api/driver.py:3506     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:3509     driver_id = current_driver.id
wa_backend/api/driver.py:3516                 driver_id=driver_id,
wa_backend/api/driver.py:3531                     driver_id=driver_id,
wa_backend/api/driver.py:3544                     DispatchRoute.driver_id == driver_id,
wa_backend/api/driver.py:3591             Visit.driver_id == driver_id,
wa_backend/api/driver.py:3667                 driver_id=driver_id,
wa_backend/api/driver.py:3681                     expected_receiver_id=driver_id,
wa_backend/api/driver.py:3731     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:3746     if not current_driver.is_admin and visit.driver_id != current_driver.id:
wa_backend/api/driver.py:3758     current_driver: Driver = Depends(get_current_driver)
wa_backend/api/driver.py:3760     driver_id = current_driver.id
wa_backend/api/driver.py:3764     stmt_session = select(WorkSession).filter_by(company_id=current_driver.company_id, driver_id=driver_id, end_time=None).order_by(WorkSession.id.desc()).limit(1)
```


#### wa_backend/api/inventory_permissions.py

```text
wa_backend/api/inventory_permissions.py:10 from models import (Driver, Role, Permission, UserRole, UserLocationAccess,
wa_backend/api/inventory_permissions.py:38                        db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/inventory_permissions.py:43     return {'company_id': actor.company_id, 'driver_id': actor.id,
wa_backend/api/inventory_permissions.py:57         db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/inventory_permissions.py:66 async def permission_catalog(actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:72                 db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:135                       actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:141                       actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:147                 db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:148     rows = (await db.execute(select(Driver.id, Driver.full_name, Driver.is_active, Driver.is_admin).where(
wa_backend/api/inventory_permissions.py:149         Driver.company_id == actor.company_id, Driver.id > after_id).order_by(Driver.id).limit(limit + 1))).all()
wa_backend/api/inventory_permissions.py:156                     db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:166     if await db.scalar(select(Driver.id).where(Driver.company_id == actor.company_id, Driver.id == user_id)) is None:
wa_backend/api/inventory_permissions.py:173                       db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:177         model.driver_id == user_id, model.id > after_id).order_by(model.id).limit(limit+1))).all()
wa_backend/api/inventory_permissions.py:184                 actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:189     values = {'company_id': actor.company_id, 'driver_id': user_id, 'role_id': role.id}
wa_backend/api/inventory_permissions.py:200         audit(db, actor, f'Driver_{user_id}', 'INVENTORY_GRANT_ADDED', None, values)
wa_backend/api/inventory_permissions.py:207                  db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:211         model.driver_id == user_id, model.id == grant_id).with_for_update())
wa_backend/api/inventory_permissions.py:216     audit(db, actor, f'Driver_{user_id}', 'INVENTORY_GRANT_REVOKED', old, None)
```


#### wa_backend/api/inventory_stock_policy.py

```text
wa_backend/api/inventory_stock_policy.py:22     Driver,
wa_backend/api/inventory_stock_policy.py:239     current_admin: Driver,
wa_backend/api/inventory_stock_policy.py:503     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/inventory_stock_policy.py:534     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/inventory_stock_policy.py:665     current_admin: Driver = Depends(get_current_driver),
```


#### wa_backend/api/offers.py

```text
wa_backend/api/offers.py:51 from models import Driver, ProductVariant, SystemAuditLog, UOM
wa_backend/api/offers.py:93 async def _require(db: AsyncSession, actor: Driver, permission: str) -> None:
wa_backend/api/offers.py:103     actor: Driver,
wa_backend/api/offers.py:366     actor: Driver,
wa_backend/api/offers.py:425     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:440     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:470     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:510     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:538     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:570     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:604     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:635     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:679     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:705     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:746     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:785     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:814     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:833     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:850     actor: Driver,
wa_backend/api/offers.py:889     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:908     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:927     actor: Driver = Depends(get_current_driver),
wa_backend/api/offers.py:946     actor: Driver = Depends(get_current_driver),
```


#### wa_backend/api/platform_manager.py

```text
wa_backend/api/platform_manager.py:14 from models import Branch, Company, Driver, LoginAttempt, PlatformAdmin, utc_now
wa_backend/api/platform_manager.py:222         admin_driver = Driver(
```


#### wa_backend/api/pricing.py

```text
wa_backend/api/pricing.py:35     Driver,
wa_backend/api/pricing.py:105     db: AsyncSession, actor: Driver, permission: str
wa_backend/api/pricing.py:112     actor: Driver,
wa_backend/api/pricing.py:313     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:328     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:358     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:418     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:464     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:522     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:568     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:625     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:679     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:733     actor: Driver,
wa_backend/api/pricing.py:798     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:817     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:836     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:855     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:909     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:939     actor: Driver = Depends(get_current_driver),
wa_backend/api/pricing.py:998     actor: Driver = Depends(get_current_driver),
```


#### wa_backend/api/product_locations.py

```text
wa_backend/api/product_locations.py:17 from models import Driver, InventoryLocation, ProductLocation, ProductVariant
wa_backend/api/product_locations.py:136     actor: Driver = Depends(get_current_driver),
wa_backend/api/product_locations.py:178     actor: Driver = Depends(get_current_driver),
wa_backend/api/product_locations.py:252     actor: Driver = Depends(get_current_driver),
wa_backend/api/product_locations.py:311     actor: Driver = Depends(get_current_driver),
```


#### wa_backend/api/product_tracking.py

```text
wa_backend/api/product_tracking.py:22 from models import Driver, SystemAuditLog
wa_backend/api/product_tracking.py:100     actor: Driver,
wa_backend/api/product_tracking.py:115     actor: Driver,
wa_backend/api/product_tracking.py:155     actor: Driver = Depends(get_current_driver),
wa_backend/api/product_tracking.py:178     actor: Driver = Depends(get_current_driver),
wa_backend/api/product_tracking.py:259     actor: Driver = Depends(get_current_driver),
```


#### wa_backend/api/reconciliation.py

```text
wa_backend/api/reconciliation.py:25     Driver,
wa_backend/api/reconciliation.py:78     current_driver: Driver = Depends(get_current_driver),
wa_backend/api/reconciliation.py:88     driver_id = int(current_driver.id)
wa_backend/api/reconciliation.py:99                     driver_id=driver_id,
wa_backend/api/reconciliation.py:133                     driver_id=driver_id,
wa_backend/api/reconciliation.py:341                 settled_by=driver_id,
wa_backend/api/reconciliation.py:348                 admin_id=driver_id,
wa_backend/api/reconciliation.py:355                     "inventory_reconciled_by": driver_id,
wa_backend/api/reconciliation.py:381             started_by=driver_id,
wa_backend/api/reconciliation.py:388             admin_id=driver_id,
```


#### wa_backend/api/sales_returns.py

```text
wa_backend/api/sales_returns.py:10 from models import Driver
wa_backend/api/sales_returns.py:37     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/sales_returns.py:58     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/sales_returns.py:78     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/sales_returns.py:94     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/sales_returns.py:110     current_admin: Driver = Depends(get_current_admin),
```


#### wa_backend/api/simple_products.py

```text
wa_backend/api/simple_products.py:81     Driver,
wa_backend/api/simple_products.py:1053     actor: Driver,
wa_backend/api/simple_products.py:1077     actor: Driver,
wa_backend/api/simple_products.py:1091     actor: Driver,
wa_backend/api/simple_products.py:1108     actor: Driver = Depends(get_current_driver),
wa_backend/api/simple_products.py:1139     actor: Driver = Depends(get_current_driver),
wa_backend/api/simple_products.py:1199     actor: Driver = Depends(get_current_driver),
wa_backend/api/simple_products.py:1267     actor: Driver = Depends(get_current_driver),
wa_backend/api/simple_products.py:1337     actor: Driver = Depends(get_current_driver),
wa_backend/api/simple_products.py:1413     actor: Driver = Depends(get_current_driver),
wa_backend/api/simple_products.py:1447     actor: Driver = Depends(get_current_driver),
wa_backend/api/simple_products.py:2058     actor: Driver = Depends(get_current_driver),
wa_backend/api/simple_products.py:2161     actor: Driver = Depends(get_current_driver),
```


#### wa_backend/api/suppliers.py

```text
wa_backend/api/suppliers.py:7 from models import Driver
wa_backend/api/suppliers.py:31                     db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/suppliers.py:38 async def supplier(supplier_id: int, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/suppliers.py:45 async def create_supplier(payload: SupplierCreate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/suppliers.py:51 async def update_supplier(supplier_id: int, payload: SupplierUpdate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
wa_backend/api/suppliers.py:57 async def supplier_state(supplier_id: int, payload: SupplierState, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
```


#### wa_backend/api/taxation.py

```text
wa_backend/api/taxation.py:55 from models import Driver, SystemAuditLog
wa_backend/api/taxation.py:97 async def _require(db: AsyncSession, actor: Driver, permission: str) -> None:
wa_backend/api/taxation.py:107     actor: Driver,
wa_backend/api/taxation.py:127     actor: Driver,
wa_backend/api/taxation.py:315     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:329     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:347     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:375     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:406     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:438     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:465     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:493     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:520     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:552     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:580     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:624     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:650     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:685     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:718     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:744     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:763     actor: Driver,
wa_backend/api/taxation.py:829     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:841     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:853     actor: Driver = Depends(get_current_driver),
wa_backend/api/taxation.py:865     actor: Driver = Depends(get_current_driver),
```


#### wa_backend/api/tenant.py

```text
wa_backend/api/tenant.py:12 from models import Company, Country, Driver, SystemSetting
wa_backend/api/tenant.py:45     current_driver: Driver = Depends(get_current_driver),
```


#### wa_backend/api/warehouse/inbound.py

```text
wa_backend/api/warehouse/inbound.py:19     Driver,
wa_backend/api/warehouse/inbound.py:290     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/inbound.py:346     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/inbound.py:373     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/inbound.py:425     current_admin: Driver = Depends(get_current_driver)
```


#### wa_backend/api/warehouse/inbound_adjustments.py

```text
wa_backend/api/warehouse/inbound_adjustments.py:17     Driver,
wa_backend/api/warehouse/inbound_adjustments.py:44     current_admin: Driver = Depends(get_current_driver)
```


#### wa_backend/api/warehouse/ledger.py

```text
wa_backend/api/warehouse/ledger.py:18     Driver,
wa_backend/api/warehouse/ledger.py:309     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/ledger.py:350             Driver.full_name,
wa_backend/api/warehouse/ledger.py:358             Driver,
wa_backend/api/warehouse/ledger.py:360                 Driver.company_id == InventoryMovement.company_id,
wa_backend/api/warehouse/ledger.py:361                 Driver.id == InventoryMovement.performed_by,
wa_backend/api/warehouse/ledger.py:397                     func.lower(Driver.full_name).like(
```


#### wa_backend/api/warehouse/live_stock.py

```text
wa_backend/api/warehouse/live_stock.py:27     Driver,
wa_backend/api/warehouse/live_stock.py:222     actor: Driver,
wa_backend/api/warehouse/live_stock.py:716     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/live_stock.py:741     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/live_stock.py:861     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/live_stock.py:935     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/live_stock.py:1169     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/live_stock.py:1810     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/live_stock.py:2444     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/live_stock.py:2482     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/live_stock.py:2860     current_admin: Driver = Depends(get_current_driver),
```


#### wa_backend/api/warehouse/locations.py

```text
wa_backend/api/warehouse/locations.py:19     Driver,
wa_backend/api/warehouse/locations.py:232     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/locations.py:280     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/locations.py:384     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/locations.py:523     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/locations.py:672     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/locations.py:793     current_admin: Driver = Depends(get_current_driver),
```


#### wa_backend/api/warehouse/status.py

```text
wa_backend/api/warehouse/status.py:8 from models import Driver, InventoryLocation, InventoryLock
wa_backend/api/warehouse/status.py:23     current_admin: Driver = Depends(get_current_driver)
```


#### wa_backend/api/warehouse/stocktake.py

```text
wa_backend/api/warehouse/stocktake.py:32     Driver,
wa_backend/api/warehouse/stocktake.py:136 ) -> Optional[Driver]:
wa_backend/api/warehouse/stocktake.py:137     stmt = select(Driver).filter_by(
wa_backend/api/warehouse/stocktake.py:446     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/stocktake.py:675     current_admin: Driver = Depends(
wa_backend/api/warehouse/stocktake.py:735                 Driver.full_name.ilike(
wa_backend/api/warehouse/stocktake.py:755             WorkSession.driver_id,
wa_backend/api/warehouse/stocktake.py:756             Driver.full_name.label(
wa_backend/api/warehouse/stocktake.py:783                     DispatchRoute.driver_id
wa_backend/api/warehouse/stocktake.py:784                     == WorkSession.driver_id,
wa_backend/api/warehouse/stocktake.py:805                 Driver,
wa_backend/api/warehouse/stocktake.py:807                     Driver.company_id
wa_backend/api/warehouse/stocktake.py:809                     Driver.id
wa_backend/api/warehouse/stocktake.py:810                     == WorkSession.driver_id,
wa_backend/api/warehouse/stocktake.py:937                 "driver_id":
wa_backend/api/warehouse/stocktake.py:938                     int(row.driver_id),
wa_backend/api/warehouse/stocktake.py:1018     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/stocktake.py:1066             Driver.full_name.label("started_by_name"),
wa_backend/api/warehouse/stocktake.py:1089             Driver,
wa_backend/api/warehouse/stocktake.py:1091                 Driver.company_id == StocktakeSession.company_id,
wa_backend/api/warehouse/stocktake.py:1092                 Driver.id == StocktakeSession.started_by,
wa_backend/api/warehouse/stocktake.py:1190     current_admin: Driver = Depends(
wa_backend/api/warehouse/stocktake.py:1379     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/stocktake.py:1627     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/stocktake.py:1716     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/stocktake.py:2032     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/stocktake.py:2080                     select(Driver.id, Driver.full_name).filter(
wa_backend/api/warehouse/stocktake.py:2081                         Driver.company_id == company_id,
wa_backend/api/warehouse/stocktake.py:2082                         Driver.id.in_(user_ids),
wa_backend/api/warehouse/stocktake.py:2213     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/stocktake.py:2322     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/stocktake.py:2422     current_admin: Driver = Depends(get_current_driver),
```


#### wa_backend/api/warehouse/transfer_policy.py

```text
wa_backend/api/warehouse/transfer_policy.py:10 from models import Driver, TenantOperationalPolicy
wa_backend/api/warehouse/transfer_policy.py:117     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfer_policy.py:152     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfer_policy.py:239     current_admin: Driver = Depends(get_current_driver),
```


#### wa_backend/api/warehouse/transfers.py

```text
wa_backend/api/warehouse/transfers.py:19     Driver,
wa_backend/api/warehouse/transfers.py:232     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:337     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:478     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:564     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:813     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:1089                         Driver.id,
wa_backend/api/warehouse/transfers.py:1090                         Driver.full_name,
wa_backend/api/warehouse/transfers.py:1092                         Driver.company_id == company_id,
wa_backend/api/warehouse/transfers.py:1093                         Driver.id.in_(actor_ids),
wa_backend/api/warehouse/transfers.py:1189     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:1341     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:1452     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:1717     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:1859     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:1948     current_admin: Driver = Depends(get_current_driver),
wa_backend/api/warehouse/transfers.py:2020     current_admin: Driver = Depends(get_current_driver)
wa_backend/api/warehouse/transfers.py:2823     current_admin: Driver = Depends(get_current_driver)
wa_backend/api/warehouse/transfers.py:2949     current_admin: Driver = Depends(get_current_driver)
wa_backend/api/warehouse/transfers.py:3066     current_admin: Driver = Depends(get_current_driver)
```


#### wa_backend/api/warehouse/whole_product_quality.py

```text
wa_backend/api/warehouse/whole_product_quality.py:28 from models import Driver, InventoryBalance, InventoryLocation, ProductVariant, SystemAuditLog
wa_backend/api/warehouse/whole_product_quality.py:129     current_admin: Driver = Depends(get_current_driver),
```


#### wa_backend/api/warehouse/whole_product_quality_preview.py

```text
wa_backend/api/warehouse/whole_product_quality_preview.py:20     Driver,
wa_backend/api/warehouse/whole_product_quality_preview.py:131     current_admin: Driver = Depends(get_current_driver),
```


#### wa_backend/domains/credential_confirmation.py

```text
wa_backend/domains/credential_confirmation.py:7 from models import Driver
wa_backend/domains/credential_confirmation.py:10 async def verify_actor_password(actor: Driver, password: str) -> bool:
```


#### wa_backend/domains/dispatch_reservations.py

```text
wa_backend/domains/dispatch_reservations.py:62         route.driver_id == h.expected_receiver_id,
wa_backend/domains/dispatch_reservations.py:134         route.driver_id == h.expected_receiver_id,
```


#### wa_backend/domains/inventory_batch_restrictions/queries.py

```text
wa_backend/domains/inventory_batch_restrictions/queries.py:9 from models import Driver, InventoryBalance, ProductBatch
wa_backend/domains/inventory_batch_restrictions/queries.py:77     db: AsyncSession, *, actor: Driver, variant_ids: Sequence[int],
```


#### wa_backend/domains/inventory_catalog_presence.py

```text
wa_backend/domains/inventory_catalog_presence.py:9 from models import Driver, InventoryBalance, InventoryLocation
wa_backend/domains/inventory_catalog_presence.py:19     actor: Driver,
```


#### wa_backend/domains/pricing/driver_authority.py

```text
wa_backend/domains/pricing/driver_authority.py:28 class LegacyDriverPrice:
wa_backend/domains/pricing/driver_authority.py:254 ) -> dict[int, LegacyDriverPrice]:
wa_backend/domains/pricing/driver_authority.py:292     result: dict[int, LegacyDriverPrice] = {}
wa_backend/domains/pricing/driver_authority.py:320         result[variant_id] = LegacyDriverPrice(
wa_backend/domains/pricing/driver_authority.py:373             DispatchRoute.driver_id == int(session.driver_id),
```


#### wa_backend/domains/pricing/driver_display.py

```text
wa_backend/domains/pricing/driver_display.py:24 class DriverDisplayPrice:
wa_backend/domains/pricing/driver_display.py:112 ) -> dict[int, DriverDisplayPrice]:
wa_backend/domains/pricing/driver_display.py:121             "Driver display pricing requires positive tenant, route and variant identifiers.",
wa_backend/domains/pricing/driver_display.py:253     result: dict[int, DriverDisplayPrice] = {}
wa_backend/domains/pricing/driver_display.py:271         result[variant_id] = DriverDisplayPrice(
```


#### wa_backend/domains/sales_calculation/driver_sale.py

```text
wa_backend/domains/sales_calculation/driver_sale.py:36 class DriverSaleInput:
wa_backend/domains/sales_calculation/driver_sale.py:43 class DriverSaleUomContract:
wa_backend/domains/sales_calculation/driver_sale.py:53 class ResolvedDriverSale:
wa_backend/domains/sales_calculation/driver_sale.py:58     uom_contracts: dict[int, DriverSaleUomContract]
wa_backend/domains/sales_calculation/driver_sale.py:75 ) -> dict[int, DriverSaleUomContract]:
wa_backend/domains/sales_calculation/driver_sale.py:80             "Driver mobile quantity contracts require positive product variant identifiers.",
wa_backend/domains/sales_calculation/driver_sale.py:120     result: dict[int, DriverSaleUomContract] = {}
wa_backend/domains/sales_calculation/driver_sale.py:163         result[variant_id] = DriverSaleUomContract(
wa_backend/domains/sales_calculation/driver_sale.py:176     contract: DriverSaleUomContract,
wa_backend/domains/sales_calculation/driver_sale.py:191             "Driver mobile quantities must be non-negative integers.",
wa_backend/domains/sales_calculation/driver_sale.py:224     inputs: Sequence[DriverSaleInput],
wa_backend/domains/sales_calculation/driver_sale.py:226     contracts: dict[int, DriverSaleUomContract],
wa_backend/domains/sales_calculation/driver_sale.py:231             "Driver sale requires at least one sold product.",
wa_backend/domains/sales_calculation/driver_sale.py:250                 "Driver sale UOM contract is missing.",
wa_backend/domains/sales_calculation/driver_sale.py:308     inputs: Sequence[DriverSaleInput],
wa_backend/domains/sales_calculation/driver_sale.py:310 ) -> ResolvedDriverSale:
wa_backend/domains/sales_calculation/driver_sale.py:320             "Driver sale requires explicit positive tenant, route, context, customer and tax jurisdiction identifiers.",
wa_backend/domains/sales_calculation/driver_sale.py:481     return ResolvedDriverSale(
```


#### wa_backend/domains/simple_products/imports/api/router.py

```text
wa_backend/domains/simple_products/imports/api/router.py:90 from models import Driver, ProductImportJob
wa_backend/domains/simple_products/imports/api/router.py:445     actor: Driver,
wa_backend/domains/simple_products/imports/api/router.py:459     actor: Driver,
wa_backend/domains/simple_products/imports/api/router.py:488     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:515     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:578                 select(Driver).where(
wa_backend/domains/simple_products/imports/api/router.py:579                     Driver.company_id
wa_backend/domains/simple_products/imports/api/router.py:583                     Driver.id
wa_backend/domains/simple_products/imports/api/router.py:585                         identity.driver_id
wa_backend/domains/simple_products/imports/api/router.py:587                     Driver.is_active.is_(
wa_backend/domains/simple_products/imports/api/router.py:670     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:810     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:847     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:891     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:941     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:1008     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:1132     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:1214     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:1249     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:1382     actor: Driver = Depends(get_current_driver),
wa_backend/domains/simple_products/imports/api/router.py:1413     actor: Driver = Depends(get_current_driver),
```


#### wa_backend/domains/simple_products/imports/infrastructure/repository.py

```text
wa_backend/domains/simple_products/imports/infrastructure/repository.py:30     Driver,
wa_backend/domains/simple_products/imports/infrastructure/repository.py:623 ) -> Driver | None:
wa_backend/domains/simple_products/imports/infrastructure/repository.py:625         select(Driver).where(
wa_backend/domains/simple_products/imports/infrastructure/repository.py:626             Driver.company_id
wa_backend/domains/simple_products/imports/infrastructure/repository.py:628             Driver.id
wa_backend/domains/simple_products/imports/infrastructure/repository.py:630             Driver.is_active.is_(True),
```


#### wa_backend/domains/simple_products/service.py

```text
wa_backend/domains/simple_products/service.py:40     Driver,
wa_backend/domains/simple_products/service.py:1012     actor: Driver,
wa_backend/domains/simple_products/service.py:1115     actor: Driver,
wa_backend/domains/simple_products/service.py:1201     actor: Driver,
wa_backend/domains/simple_products/service.py:1402     actor: Driver,
wa_backend/domains/simple_products/service.py:1696     actor: Driver,
wa_backend/domains/simple_products/service.py:1739     actor: Driver,
wa_backend/domains/simple_products/service.py:1774     actor: Driver,
wa_backend/domains/simple_products/service.py:1940     actor: Driver,
```


#### wa_backend/inventory_access.py

```text
wa_backend/inventory_access.py:11 from models import (Driver, Permission, UserRole, UserLocationAccess, role_permissions,
wa_backend/inventory_access.py:61     actor: Driver
wa_backend/inventory_access.py:70             assignment.driver_id == self.actor.id,
wa_backend/inventory_access.py:129             assignment.company_id == self.company_id, assignment.driver_id == self.actor.id)
wa_backend/inventory_access.py:134                 UserLocationAccess.driver_id == self.actor.id)
wa_backend/inventory_access.py:161                     UserLocationAccess.driver_id == self.actor.id,
```


#### wa_backend/main.py

```text
wa_backend/main.py:439 app.include_router(driver.router, tags=["Driver Operations"])
```


#### wa_backend/models.py

```text
wa_backend/models.py:120         UniqueConstraint('company_id', 'driver_id', 'role_id', name='uq_user_role_tenant'),
wa_backend/models.py:121         ForeignKeyConstraint(['company_id', 'driver_id'], ['drivers.company_id', 'drivers.id'], ondelete='CASCADE'),
wa_backend/models.py:126     driver_id  = Column(Integer, nullable=False, index=True)
wa_backend/models.py:133         UniqueConstraint('company_id', 'driver_id', 'location_id', 'role_id', name='uq_user_loc_access_tenant'),
wa_backend/models.py:134         ForeignKeyConstraint(['company_id', 'driver_id'], ['drivers.company_id', 'drivers.id'], ondelete='CASCADE'),
wa_backend/models.py:140     driver_id   = Column(Integer, nullable=False, index=True)
wa_backend/models.py:215 class Driver(Base):
wa_backend/models.py:1011         Index('ix_ws_driver_unsettled', 'driver_id', 'is_settled', 'end_time'),
wa_backend/models.py:1015             'driver_id',
wa_backend/models.py:1020         UniqueConstraint('company_id', 'id', 'driver_id', name='uq_work_sessions_company_driver_id'),
wa_backend/models.py:1026             ['company_id', 'driver_id'],
wa_backend/models.py:1068     driver_id    = Column(Integer, nullable=False, index=True)
wa_backend/models.py:1087     driver = relationship('Driver', foreign_keys=[driver_id], backref=backref('work_sessions', lazy='raise'), lazy='raise')
wa_backend/models.py:1170             ['company_id', 'added_by_driver_id'],
wa_backend/models.py:1172             ondelete='SET NULL (added_by_driver_id)',
wa_backend/models.py:1207     added_by_driver_id = Column(Integer, nullable=True, index=True)
wa_backend/models.py:1228         Index('uq_active_route_per_driver', 'company_id', 'driver_id', unique=True,
wa_backend/models.py:1240         ForeignKeyConstraint(['company_id', 'driver_id'], ['drivers.company_id', 'drivers.id'],
wa_backend/models.py:1245             ['company_id', 'work_session_id', 'driver_id'],
wa_backend/models.py:1246             ['work_sessions.company_id', 'work_sessions.id', 'work_sessions.driver_id'],
wa_backend/models.py:1254         CheckConstraint('work_session_id IS NULL OR driver_id IS NOT NULL',
wa_backend/models.py:1263     driver_id          = Column(Integer, nullable=True, index=True)
wa_backend/models.py:1272     driver  = relationship('Driver', foreign_keys=[driver_id], lazy='raise')
wa_backend/models.py:1751         ForeignKeyConstraint(['company_id', 'driver_id'], ['drivers.company_id', 'drivers.id'],
wa_backend/models.py:1756             ['company_id', 'work_session_id', 'driver_id'],
wa_backend/models.py:1757             ['work_sessions.company_id', 'work_sessions.id', 'work_sessions.driver_id'],
wa_backend/models.py:1760         CheckConstraint('work_session_id IS NULL OR driver_id IS NOT NULL',
wa_backend/models.py:1848             'company_id', 'driver_id', 'shop_id', 'operational_date',
wa_backend/models.py:1850             postgresql_where=text("status = 'Pending' AND driver_id IS NOT NULL"),
wa_backend/models.py:1855     driver_id       = Column(Integer, nullable=True,  index=True)
wa_backend/models.py:1907     driver       = relationship('Driver', foreign_keys=[driver_id], backref=backref('visits', lazy='raise'))
wa_backend/models.py:2104         ForeignKeyConstraint(['company_id', 'driver_id'], ['drivers.company_id', 'drivers.id'],
wa_backend/models.py:2120     driver_id          = Column(Integer, nullable=True,  index=True)
wa_backend/models.py:2134     driver          = relationship('Driver', foreign_keys=[driver_id], lazy='raise')
wa_backend/models.py:2185     admin = relationship('Driver', foreign_keys=[admin_id], lazy='raise')
wa_backend/models.py:2221     admin = relationship('Driver', foreign_keys=[admin_id], lazy='raise')
wa_backend/models.py:2340             ['company_id', 'source_driver_id'],
wa_backend/models.py:2361     source_driver_id      = Column(Integer, nullable=True, index=True)
wa_backend/models.py:2400     driver_id = Column(Integer, ForeignKey('drivers.id', ondelete='CASCADE'), nullable=False, index=True)
wa_backend/models.py:2410     driver = relationship('Driver', lazy='raise')
wa_backend/models.py:3131             ['work_sessions.company_id', 'work_sessions.id', 'work_sessions.driver_id'],
```


#### wa_backend/product_lifecycle.py

```text
wa_backend/product_lifecycle.py:345         actor_context={"actor_type": "Driver", "source": "admin_api"},
```


#### wa_backend/realtime/auth.py

```text
wa_backend/realtime/auth.py:9 from models import Driver, TokenBlacklist
wa_backend/realtime/auth.py:21     driver_id: int
wa_backend/realtime/auth.py:37         driver_id, company_id = access_token_identity(payload)
wa_backend/realtime/auth.py:52                 select(Driver).where(
wa_backend/realtime/auth.py:53                     Driver.company_id == company_id,
wa_backend/realtime/auth.py:54                     Driver.id == driver_id,
wa_backend/realtime/auth.py:73         driver_id=driver_id,
```


#### wa_backend/schemas.py

```text
wa_backend/schemas.py:321     driver_id: int
wa_backend/schemas.py:452     driver_id: Optional[int] = None
wa_backend/schemas.py:464 # 5. دروع عمليات الميدان والجلسات (Driver Operations)
wa_backend/schemas.py:565 class DriverVisitResponse(BaseModel):
wa_backend/schemas.py:614     def compute_legacy_fields(self) -> 'DriverVisitResponse':
wa_backend/schemas.py:653     visits: List[DriverVisitResponse]
wa_backend/schemas.py:877 class AdminDashboardDriverResponse(BaseModel):
wa_backend/schemas.py:943 class DispatchDriverResponse(BaseModel):
wa_backend/schemas.py:963     drivers: List[DispatchDriverResponse]
wa_backend/schemas.py:970     driver_id: PositiveDbInt
wa_backend/schemas.py:2507     driver_id: int
```


#### wa_backend/services.py

```text
wa_backend/services.py:15     Driver,
wa_backend/services.py:415     driver_id: int,
wa_backend/services.py:418     pre_fetched_driver: Optional[Driver] = None,
wa_backend/services.py:422         driver_id = _strict_int(driver_id, "driver_id", minimum=1)
wa_backend/services.py:438         pre_fetched_driver.id != driver_id
wa_backend/services.py:443     stmt_driver = select(Driver).execution_options(populate_existing=True).filter_by(
wa_backend/services.py:444         id=driver_id,
wa_backend/services.py:2832                 DispatchRoute.driver_id == work_session.driver_id,
wa_backend/services.py:4401             select(Driver.id, Driver.is_admin).filter_by(
wa_backend/services.py:4430     if started_by != work_session.driver_id and not bool(actor.is_admin):
wa_backend/services.py:4588             select(Driver.id, Driver.is_admin).filter_by(
wa_backend/services.py:4610     if settled_by != work_session.driver_id and not bool(actor.is_admin):
wa_backend/services.py:4639                 DispatchRoute.driver_id == work_session.driver_id,
wa_backend/services.py:4784             select(Driver.id).filter_by(
wa_backend/services.py:6339         if locked_visit.driver_id != locked_session.driver_id:
wa_backend/services.py:6367             select(Driver.id).filter_by(
```


#### wa_backend/tools/staging_load/wanasah_d7s_mixed_load_config.py

```text
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_config.py:121     driver_id: int
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_config.py:225         require(set(data) == {"zone_id", "driver_id", "vehicle_id", "source_location_id", "inventory"}, "ROUTE_FIXTURE_FIELDS")
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_config.py:226         for key in ("zone_id", "driver_id", "vehicle_id", "source_location_id"):
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_config.py:300         ids = [integer(entry.get(k), 1, 2147483647) for k in ("company_id", "admin_id", "driver_id")]
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_config.py:336             for column in ("driver_id", "vehicle_id", "zone_id"):
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_config.py:341             require(fixture["driver_id"] != own.driver_id, "ROUTE_DRIVER_HAS_SALE_SESSION")
```


#### wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py

```text
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:418                      "zone_id": o.fixture.get("zone_id"), "driver_id": o.fixture.get("driver_id"),
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:428         driver_ids = sorted({tenant.admin_id, tenant.driver_id}
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:429                             | {o.fixture["driver_id"] for o in ops if o.kind == "route"})
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:430         c.execute("SELECT id,is_active FROM drivers WHERE company_id=%s AND id=ANY(%s)", (company, driver_ids))
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:432         require(len(actors) == len(driver_ids) and all(a["is_active"] for a in actors), "FIXTURE_ACTOR_NOT_ACTIVE")
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:484         c.execute("SELECT id,driver_id,is_authorized_to_sell,is_settled,commercial_context_id FROM work_sessions "
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:485                   "WHERE company_id=%s AND driver_id=ANY(%s) AND end_time IS NULL", (company, driver_ids))
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:488             require(any(r["driver_id"] == tenant.driver_id and r["is_authorized_to_sell"]
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:491         route_drivers = {o.fixture["driver_id"] for o in ops if o.kind == "route"}
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:492         require(not any(r["driver_id"] in route_drivers for r in sessions), "ROUTE_DRIVER_ACTIVE_SESSION")
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:525             SELECT p.key, v.id, v.driver_id, v.status, v.outcome, v.final_amount_due,
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:547         """, (plan, company, company, tenant.driver_id, company))
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:571               AS x(key text,kind text,zone_id int,driver_id int,vehicle_id int,source_location_id int))
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:575               AND r.driver_id=p.driver_id AND r.vehicle_id=p.vehicle_id
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:657                 require(row["id"] == op.fixture["visit_id"] and row["driver_id"] == tenant.driver_id
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:783                     and result[1].get("driver_id") == tenant.driver_id, "DRIVER_AUTH_PREFLIGHT_FAILED")
wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py:1206     # Driver cannot attest hardware, 4 worker deployment, fairness or DB locks from HTTP.
```


#### wa_backend/workers/tasks/handshake.py

```text
wa_backend/workers/tasks/handshake.py:8 from models import Driver, InventoryTransferHeader, SystemAuditLog
wa_backend/workers/tasks/handshake.py:154                     select(Driver.id, Driver.full_name).where(
wa_backend/workers/tasks/handshake.py:155                         Driver.company_id == int(company_id),
wa_backend/workers/tasks/handshake.py:156                         Driver.id.in_(receiver_ids),
wa_backend/workers/tasks/handshake.py:161                 int(driver_id): str(full_name)
wa_backend/workers/tasks/handshake.py:162                 for driver_id, full_name in receiver_rows
```


#### wa_backend/workers/tasks/session_monitor.py

```text
wa_backend/workers/tasks/session_monitor.py:8 from models import Driver, SystemAuditLog, WorkSession
wa_backend/workers/tasks/session_monitor.py:137         driver_ids = sorted(
wa_backend/workers/tasks/session_monitor.py:138             {int(session.driver_id) for session in sessions}
wa_backend/workers/tasks/session_monitor.py:142                 select(Driver.id, Driver.full_name).where(
wa_backend/workers/tasks/session_monitor.py:143                     Driver.company_id == int(company_id),
wa_backend/workers/tasks/session_monitor.py:144                     Driver.id.in_(driver_ids),
wa_backend/workers/tasks/session_monitor.py:149             int(driver_id): str(full_name)
wa_backend/workers/tasks/session_monitor.py:150             for driver_id, full_name in driver_rows
wa_backend/workers/tasks/session_monitor.py:167                 int(session.driver_id),
wa_backend/workers/tasks/session_monitor.py:211                         "driver_id": int(session.driver_id),
```

### Dashboard — principal/representative and derived authority contracts

| File | Matched lines | Source role / interpretation |
|---|---|---|
| dashboard/src/components/dispatch/PendingRoutesTable.tsx | 1 | Mixed field ownership and authenticated action actor; use exact function/FK mapping. |
| dashboard/src/components/dispatch/PostponedRoutesModal.tsx | 4 | Mixed field ownership and authenticated action actor; use exact function/FK mapping. |
| dashboard/src/components/dispatch/RouteManagementModal.tsx | 1 | Mixed field ownership and authenticated action actor; use exact function/FK mapping. |
| dashboard/src/components/dispatch/ShortageModal.tsx | 5 | Mixed field ownership and authenticated action actor; use exact function/FK mapping. |
| dashboard/src/components/operations/DashboardLayout.tsx | 6 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/components/operations/OperationsSidebar.tsx | 2 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/catalog/lifecycle/CatalogLifecycleActions.tsx | 5 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/commercialRules/CommercialRulesWorkspace.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/commercialRules/OfferManagement.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/commercialRules/PreviewLab.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/commercialRules/TaxManagement.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/inventory/productLocations/ProductLocationManager.tsx | 4 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/inventory/quality/QualityHandlingDestinationsCard.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/inventory/quality/WholeProductQualityActionsPanel.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/inventory/quality/useProductQualityCommands.ts | 7 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/inventory/quality/useProductQualitySources.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/inventory/quality/useWholeProductQualityPreview.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/suppliers/SupplierSelector.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/features/suppliers/useSupplierSearch.ts | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/hooks/useInventoryAccess.ts | 13 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/lib/durableOperations.ts | 2 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/lib/productDisplayPreferences.ts | 8 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/CommercialRulesDashboard.tsx | 2 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/DispatchBoard.tsx | 28 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/Login.tsx | 7 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/PricingDashboard.tsx | 2 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/SalesReturnsDashboard.tsx | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/MainInventory.tsx | 10 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/TabBatches.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/TabInventoryAccess.tsx | 4 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/TabWarehouseLocations.tsx | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/archive/ArchiveOwnerWorkspace.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/batches/BatchDispositionManager.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/batches/BatchFocusWorkspace.tsx | 2 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/batches/BatchQuantityActions.tsx | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/batches/useBatchDispositionCommand.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/batches/useBatchSpecialTransfer.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/batches/useBatchStockSources.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/batches/useBatchTerminalAction.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/inventorySessionCache.ts | 2 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/quality/useQualityBatchCandidates.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/stocktake/parsers.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/inventory/stocktake/types.ts | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/ProductsPage.tsx | 16 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx | 10 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx | 8 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/barcode/useIndependentPackageBarcode.ts | 5 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/barcode/usePrimaryBarcodeReplacement.ts | 5 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/barcode/useProductBarcodeWorkflow.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/create/productDraftStorageKey.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/create/useCreateProductMutation.ts | 5 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/create/useCreateProductWorkflow.ts | 6 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/deriveProductsCapabilities.ts | 8 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/display-preferences/createProductDisplayPreferenceActions.ts | 4 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/display-preferences/useProductDisplayPreferencesState.ts | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/family/ProductFamiliesManager.tsx | 12 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/family/ProductFamilyReassignDialog.tsx | 5 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/family/useProductFamiliesWorkflow.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/family/useProductFamilyReassignWorkflow.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/import/ImportInlineCorrectionPanel.tsx | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/import/ImportProductModal.tsx | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/import/ImportProductStatusPanel.tsx | 6 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/import/correctionRouteGate.ts | 8 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/import/productImportSessionKey.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/import/useImportCorrection.ts | 5 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/import/useImportInlineCorrection.ts | 5 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/import/useImportProductUpload.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/import/useImportProductWorkflow.ts | 8 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/list/useProductCatalogSummary.ts | 4 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/list/useProductsListWorkflow.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/pricing/usePriceEditMutation.ts | 5 | Field price/display/sale context; generic creator/approver remain principal (FK matrix). |
| dashboard/src/pages/products/pricing/usePriceEditWorkflow.ts | 4 | Field price/display/sale context; generic creator/approver remain principal (FK matrix). |
| dashboard/src/pages/products/productDurableScope.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/rename/ProductRenameDialog.tsx | 5 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/rename/useProductRenameWorkflow.ts | 3 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/tracking/useProductTrackingMutations.ts | 8 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/tracking/useProductTrackingWorkflow.ts | 5 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/products/useProductsIdentityScopeReset.ts | 5 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/suppliers/SuppliersPage.tsx | 2 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/pages/suppliers/useSupplierListSearch.ts | 1 | Dashboard principal/cache/draft, except Dispatch assignment and vehicle-recon field contracts. |
| dashboard/src/types/dispatch.ts | 2 | Mixed field ownership and authenticated action actor; use exact function/FK mapping. |

#### dashboard/src/components/dispatch/PendingRoutesTable.tsx

```text
dashboard/src/components/dispatch/PendingRoutesTable.tsx:158         const driverShortageCount = driverShortagesMap[route.driverId] || 0;
```


#### dashboard/src/components/dispatch/PostponedRoutesModal.tsx

```text
dashboard/src/components/dispatch/PostponedRoutesModal.tsx:10   onUpdateDriver: (id: string, driverId: string) => void;
dashboard/src/components/dispatch/PostponedRoutesModal.tsx:53                           drivers.some((driver) => driver.id === route.driverId)
dashboard/src/components/dispatch/PostponedRoutesModal.tsx:54                             ? route.driverId
dashboard/src/components/dispatch/PostponedRoutesModal.tsx:79                           !drivers.some((driver) => driver.id === route.driverId))
```


#### dashboard/src/components/dispatch/RouteManagementModal.tsx

```text
dashboard/src/components/dispatch/RouteManagementModal.tsx:88                   .filter((driver) => driver.id !== activeRoute?.driverId)
```


#### dashboard/src/components/dispatch/ShortageModal.tsx

```text
dashboard/src/components/dispatch/ShortageModal.tsx:36   onEditShortageGroup: (shopId: string, driverId?: string) => void;
dashboard/src/components/dispatch/ShortageModal.tsx:49     driverId: string;
dashboard/src/components/dispatch/ShortageModal.tsx:56     const groupKey = `${sh.shopId}:${sh.driverId || ""}`;
dashboard/src/components/dispatch/ShortageModal.tsx:62         driverId: sh.driverId || "",
dashboard/src/components/dispatch/ShortageModal.tsx:541                   onEdit={() => onEditShortageGroup(group.shopId, group.driverId)}
```


#### dashboard/src/components/operations/DashboardLayout.tsx

```text
dashboard/src/components/operations/DashboardLayout.tsx:90     !access.isCompanyAdmin &&
dashboard/src/components/operations/DashboardLayout.tsx:101     !access.isCompanyAdmin &&
dashboard/src/components/operations/DashboardLayout.tsx:114     !access.isCompanyAdmin &&
dashboard/src/components/operations/DashboardLayout.tsx:127     !access.isCompanyAdmin &&
dashboard/src/components/operations/DashboardLayout.tsx:140     !access.isCompanyAdmin &&
dashboard/src/components/operations/DashboardLayout.tsx:156     !access.isCompanyAdmin &&
```


#### dashboard/src/components/operations/OperationsSidebar.tsx

```text
dashboard/src/components/operations/OperationsSidebar.tsx:304                   {access.isCompanyAdmin
dashboard/src/components/operations/OperationsSidebar.tsx:401                 access.isCompanyAdmin ||
```


#### dashboard/src/features/catalog/lifecycle/CatalogLifecycleActions.tsx

```text
dashboard/src/features/catalog/lifecycle/CatalogLifecycleActions.tsx:273   const driverId =
dashboard/src/features/catalog/lifecycle/CatalogLifecycleActions.tsx:274     access.data?.driver_id ??
dashboard/src/features/catalog/lifecycle/CatalogLifecycleActions.tsx:278     driverId !== null
dashboard/src/features/catalog/lifecycle/CatalogLifecycleActions.tsx:281           driverId,
dashboard/src/features/catalog/lifecycle/CatalogLifecycleActions.tsx:290     access.isCompanyAdmin ||
```


#### dashboard/src/features/commercialRules/CommercialRulesWorkspace.tsx

```text
dashboard/src/features/commercialRules/CommercialRulesWorkspace.tsx:10   const access = useInventoryAccess(); const canOffers = access.isCompanyAdmin || access.canAny("offers.view"); const canTax = access.isCompanyAdmin || access.canAny("tax.view"); const [tab, setTab] = useState<Tab>(canOffers ? "offers" : "tax");
```


#### dashboard/src/features/commercialRules/OfferManagement.tsx

```text
dashboard/src/features/commercialRules/OfferManagement.tsx:19   const canManage = access.isCompanyAdmin || access.canAny("offers.manage"); const canApprove = access.isCompanyAdmin || access.canAny("offers.approve"); const catalogAvailable = access.isCompanyAdmin || access.canAny("catalog.read");
```


#### dashboard/src/features/commercialRules/PreviewLab.tsx

```text
dashboard/src/features/commercialRules/PreviewLab.tsx:32   const authFetch = useAuthFetch(); const access = useInventoryAccess(); const catalogAvailable = access.isCompanyAdmin || access.canAny("catalog.read");
```


#### dashboard/src/features/commercialRules/TaxManagement.tsx

```text
dashboard/src/features/commercialRules/TaxManagement.tsx:19   const canManage = access.isCompanyAdmin || access.canAny("tax.manage"); const canApprove = access.isCompanyAdmin || access.canAny("tax.approve"); const catalogAvailable = access.isCompanyAdmin || access.canAny("catalog.read");
```


#### dashboard/src/features/inventory/productLocations/ProductLocationManager.tsx

```text
dashboard/src/features/inventory/productLocations/ProductLocationManager.tsx:267   const driverId =
dashboard/src/features/inventory/productLocations/ProductLocationManager.tsx:268     access.data?.driver_id ??
dashboard/src/features/inventory/productLocations/ProductLocationManager.tsx:272     driverId !== null
dashboard/src/features/inventory/productLocations/ProductLocationManager.tsx:275           driverId,
```


#### dashboard/src/features/inventory/quality/QualityHandlingDestinationsCard.tsx

```text
dashboard/src/features/inventory/quality/QualityHandlingDestinationsCard.tsx:112   const canManage = access.isCompanyAdmin || access.can("inventory.transfer_policy.manage");
```


#### dashboard/src/features/inventory/quality/WholeProductQualityActionsPanel.tsx

```text
dashboard/src/features/inventory/quality/WholeProductQualityActionsPanel.tsx:55     access.data?.driver_id,
```


#### dashboard/src/features/inventory/quality/useProductQualityCommands.ts

```text
dashboard/src/features/inventory/quality/useProductQualityCommands.ts:52   const driverId = access.data?.driver_id ?? null;
dashboard/src/features/inventory/quality/useProductQualityCommands.ts:64     if (companyId === null || driverId === null) return;
dashboard/src/features/inventory/quality/useProductQualityCommands.ts:67       durableScope(companyId, driverId, "whole-product-quality-resolve-v3", productVariantId),
dashboard/src/features/inventory/quality/useProductQualityCommands.ts:69         durableScope(companyId, driverId, "whole-product-quality-resolve-v2", `${productVariantId}:${action}`),
dashboard/src/features/inventory/quality/useProductQualityCommands.ts:92   }, [companyId, driverId, productVariantId, recoveryRevision]);
dashboard/src/features/inventory/quality/useProductQualityCommands.ts:113       || driverId === null
dashboard/src/features/inventory/quality/useProductQualityCommands.ts:131       ?? durableScope(companyId, driverId, "whole-product-quality-resolve-v3", productVariantId);
```


#### dashboard/src/features/inventory/quality/useProductQualitySources.ts

```text
dashboard/src/features/inventory/quality/useProductQualitySources.ts:12   const driverId = access.data?.driver_id ?? null;
dashboard/src/features/inventory/quality/useProductQualitySources.ts:14     queryKey: ["inline-product-quality-sources", companyId, driverId, productVariantId],
dashboard/src/features/inventory/quality/useProductQualitySources.ts:15     enabled: productVariantId !== null && companyId !== null && driverId !== null,
```


#### dashboard/src/features/inventory/quality/useWholeProductQualityPreview.ts

```text
dashboard/src/features/inventory/quality/useWholeProductQualityPreview.ts:14   const driverId = access.data?.driver_id ?? null;
dashboard/src/features/inventory/quality/useWholeProductQualityPreview.ts:20       driverId,
dashboard/src/features/inventory/quality/useWholeProductQualityPreview.ts:23     enabled: enabled && companyId !== null && driverId !== null,
```


#### dashboard/src/features/suppliers/SupplierSelector.tsx

```text
dashboard/src/features/suppliers/SupplierSelector.tsx:26     queryKey: ["supplier-selection", search.access.data?.company_id, search.access.data?.driver_id, value],
```


#### dashboard/src/features/suppliers/useSupplierSearch.ts

```text
dashboard/src/features/suppliers/useSupplierSearch.ts:23     queryKey: ["suppliers", access.data?.company_id, access.data?.driver_id, active, search, cursor],
```


#### dashboard/src/hooks/useInventoryAccess.ts

```text
dashboard/src/hooks/useInventoryAccess.ts:15   driver_id: number;
dashboard/src/hooks/useInventoryAccess.ts:16   is_company_admin: boolean;
dashboard/src/hooks/useInventoryAccess.ts:53   const driverId = value.driver_id;
dashboard/src/hooks/useInventoryAccess.ts:54   const isCompanyAdmin = value.is_company_admin;
dashboard/src/hooks/useInventoryAccess.ts:61     typeof driverId !== 'number' ||
dashboard/src/hooks/useInventoryAccess.ts:62     !Number.isSafeInteger(driverId) ||
dashboard/src/hooks/useInventoryAccess.ts:63     driverId <= 0 ||
dashboard/src/hooks/useInventoryAccess.ts:64     typeof isCompanyAdmin !== 'boolean' ||
dashboard/src/hooks/useInventoryAccess.ts:79     driver_id: driverId as number,
dashboard/src/hooks/useInventoryAccess.ts:80     is_company_admin: isCompanyAdmin as boolean,
dashboard/src/hooks/useInventoryAccess.ts:119   const user = localStorage.getItem('driver_id');
dashboard/src/hooks/useInventoryAccess.ts:143   return { ...query, data, can, canAny, isCompanyAdmin: data?.is_company_admin === true };
dashboard/src/hooks/useInventoryAccess.ts:151     queryKey: ['inventory-access', localStorage.getItem('company_id'), localStorage.getItem('driver_id'), 'batch', ids],
```


#### dashboard/src/lib/durableOperations.ts

```text
dashboard/src/lib/durableOperations.ts:116   driverId: number,
dashboard/src/lib/durableOperations.ts:122   `${PREFIX}:${companyId}:${driverId}:${operation}:${target}`;
```


#### dashboard/src/lib/productDisplayPreferences.ts

```text
dashboard/src/lib/productDisplayPreferences.ts:125   driverId: number,
dashboard/src/lib/productDisplayPreferences.ts:127   `wanasah:products:display:v${PRODUCT_DISPLAY_PREFERENCES_VERSION}:${companyId}:${driverId}`;
dashboard/src/lib/productDisplayPreferences.ts:251     driverId: number,
dashboard/src/lib/productDisplayPreferences.ts:255       !positiveSafeInteger(driverId)
dashboard/src/lib/productDisplayPreferences.ts:265             driverId,
dashboard/src/lib/productDisplayPreferences.ts:282     driverId: number,
dashboard/src/lib/productDisplayPreferences.ts:287       !positiveSafeInteger(driverId)
dashboard/src/lib/productDisplayPreferences.ts:301           driverId,
```


#### dashboard/src/pages/CommercialRulesDashboard.tsx

```text
dashboard/src/pages/CommercialRulesDashboard.tsx:15   const canOffers = access.isCompanyAdmin || access.canAny("offers.view");
dashboard/src/pages/CommercialRulesDashboard.tsx:16   const canTax = access.isCompanyAdmin || access.canAny("tax.view");
```


#### dashboard/src/pages/DispatchBoard.tsx

```text
dashboard/src/pages/DispatchBoard.tsx:250   const { isCompanyAdmin } = useInventoryAccess();
dashboard/src/pages/DispatchBoard.tsx:252     if (!isCompanyAdmin && activeTab === 'zones') setActiveTab('routes');
dashboard/src/pages/DispatchBoard.tsx:253   }, [isCompanyAdmin, activeTab]);
dashboard/src/pages/DispatchBoard.tsx:443     if (isCompanyAdmin) authenticatedFetch("/dispatch/shortages", { signal })
dashboard/src/pages/DispatchBoard.tsx:448   }, [authenticatedFetch, isCompanyAdmin]); // +++ E-04: إضافة authenticatedFetch كـ Dependency لتجنب تحذيرات وتسريبات الذاكرة +++
dashboard/src/pages/DispatchBoard.tsx:487     if (!isCompanyAdmin) {
dashboard/src/pages/DispatchBoard.tsx:623   }, [fetchInitialData, isCompanyAdmin]);
dashboard/src/pages/DispatchBoard.tsx:666       if (s.status === "pending" && s.driverId) {
dashboard/src/pages/DispatchBoard.tsx:667         if (!map[s.driverId]) map[s.driverId] = new Set();
dashboard/src/pages/DispatchBoard.tsx:668         map[s.driverId].add(s.shopId);
dashboard/src/pages/DispatchBoard.tsx:672     for (const driverId in map) {
dashboard/src/pages/DispatchBoard.tsx:673       countMap[driverId] = map[driverId].size;
dashboard/src/pages/DispatchBoard.tsx:821         driver_id: selectedDriverId,
dashboard/src/pages/DispatchBoard.tsx:853       routeModalType === "transfer" ? transferDriverId : activeRoute.driverId;
dashboard/src/pages/DispatchBoard.tsx:857       (!newDriverId || newDriverId === activeRoute.driverId)
dashboard/src/pages/DispatchBoard.tsx:864       (newDriverId !== activeRoute.driverId ||
dashboard/src/pages/DispatchBoard.tsx:876           driverId: newDriverId,
dashboard/src/pages/DispatchBoard.tsx:1161         driverId: number | null;
dashboard/src/pages/DispatchBoard.tsx:1222       driverId: shortageDriverId ? Number(shortageDriverId) : null,
dashboard/src/pages/DispatchBoard.tsx:1314     driverId?: string
dashboard/src/pages/DispatchBoard.tsx:1319         (item.driverId || "") === (driverId || "")
dashboard/src/pages/DispatchBoard.tsx:1327           `${item.zoneId}:${item.shopId}:${item.driverId || ""}`
dashboard/src/pages/DispatchBoard.tsx:1337     setShortageDriverId(first.driverId || "");
dashboard/src/pages/DispatchBoard.tsx:1389             ] as const).filter(tab => isCompanyAdmin || tab.id !== 'zones').map(tab => (
dashboard/src/pages/DispatchBoard.tsx:1397           {isCompanyAdmin && activeTab === "routes" && <button onClick={() => setIsShortageModalOpen(true)} className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold transition-all shadow-sm ${shortages.length > 0 ? "bg-amber-500 text-white animate-pulse" : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"}`}><ClipboardList className="w-4 h-4" /> 📦 طلبات ونواقص</button>}
dashboard/src/pages/DispatchBoard.tsx:1472                       setTransferDriverId(r.driverId);
dashboard/src/pages/DispatchBoard.tsx:1861       <PostponedRoutesModal isOpen={isShowPostponedModalOpen} onClose={() => setIsShowPostponedModalOpen(false)} routes={pendingRoutes.filter(r => r.status === "postponed" && (!archiveRouteFocus || r.id === archiveRouteFocus))} drivers={drivers} onUpdateDriver={(id, drvId) => { const d = drivers.find(drv => drv.id === drvId); setPendingRoutes(prev => prev.map(r => r.id === id ? { ...r, driverId: drvId, driverName: d?.name || "" } : r)); }} onRestore={async (id) => { try { const route = pendingRoutes.find(r => r.id === id); await authenticatedFetch(`/dispatch/route/${id}/status`, { method: "PUT", body: JSON.stringify(
dashboard/src/pages/DispatchBoard.tsx:1864             : { status: "waiting", driverId: route?.driverId }
```


#### dashboard/src/pages/Login.tsx

```text
dashboard/src/pages/Login.tsx:25   is_admin: boolean;
dashboard/src/pages/Login.tsx:26   dashboard_access: boolean;
dashboard/src/pages/Login.tsx:27   driver_id: number;
dashboard/src/pages/Login.tsx:100       if (!data.is_admin && data.dashboard_access !== true) {
dashboard/src/pages/Login.tsx:109         !Number.isSafeInteger(data.driver_id) || Number(data.driver_id) <= 0
dashboard/src/pages/Login.tsx:125       localStorage.setItem('driver_id', String(data.driver_id));
dashboard/src/pages/Login.tsx:131       navigate(data.is_admin ? '/' : '/inventory');
```


#### dashboard/src/pages/PricingDashboard.tsx

```text
dashboard/src/pages/PricingDashboard.tsx:273   const canManage = access.isCompanyAdmin || access.canAny("pricing.manage");
dashboard/src/pages/PricingDashboard.tsx:274   const canApprove = access.isCompanyAdmin || access.canAny("pricing.approve");
```


#### dashboard/src/pages/SalesReturnsDashboard.tsx

```text
dashboard/src/pages/SalesReturnsDashboard.tsx:279     enabled: access.isCompanyAdmin,
dashboard/src/pages/SalesReturnsDashboard.tsx:285     enabled: access.isCompanyAdmin,
dashboard/src/pages/SalesReturnsDashboard.tsx:344   if (!access.isCompanyAdmin) {
```


#### dashboard/src/pages/inventory/MainInventory.tsx

```text
dashboard/src/pages/inventory/MainInventory.tsx:230   const driverId = localStorage.getItem("driver_id") || "";
dashboard/src/pages/inventory/MainInventory.tsx:231   const warmScopeKey = inventoryWarmScopeKey(companyId, driverId);
dashboard/src/pages/inventory/MainInventory.tsx:306   const { isCompanyAdmin, canAny } = access;
dashboard/src/pages/inventory/MainInventory.tsx:309     if (id === 'permissions') return isCompanyAdmin;
dashboard/src/pages/inventory/MainInventory.tsx:313   }, [isCompanyAdmin, canAny, canAtLocation, selectedLocationId]);
dashboard/src/pages/inventory/MainInventory.tsx:1367             key={`${locationAccess.data.company_id}:${locationAccess.data.driver_id}:${selectedLocationId}`}
dashboard/src/pages/inventory/MainInventory.tsx:1369             actorId={locationAccess.data.driver_id}
dashboard/src/pages/inventory/MainInventory.tsx:1381             key={`${locationAccess.data.company_id}:${locationAccess.data.driver_id}:${selectedLocationId}`}
dashboard/src/pages/inventory/MainInventory.tsx:1383             companyId={`${locationAccess.data.company_id}:${locationAccess.data.driver_id}`}
dashboard/src/pages/inventory/MainInventory.tsx:1418         {activeTab === "permissions" && access.isCompanyAdmin && <TabInventoryAccess />}
```


#### dashboard/src/pages/inventory/TabBatches.tsx

```text
dashboard/src/pages/inventory/TabBatches.tsx:85     access.isCompanyAdmin || access.can("batch.disposition");
```


#### dashboard/src/pages/inventory/TabInventoryAccess.tsx

```text
dashboard/src/pages/inventory/TabInventoryAccess.tsx:9 interface User { id: number; full_name: string; is_admin: boolean; is_active: boolean }
dashboard/src/pages/inventory/TabInventoryAccess.tsx:100       is_admin: asBoolean(row.is_admin),
dashboard/src/pages/inventory/TabInventoryAccess.tsx:167   const queryPrefix = ['inventory-access-admin', localStorage.getItem('company_id'), localStorage.getItem('driver_id')];
dashboard/src/pages/inventory/TabInventoryAccess.tsx:256               <option value="">اختر المستخدم</option>{users.data?.items.map(user=><option key={user.id} value={user.id}>{user.full_name}{user.is_admin?' — Admin كامل الصلاحيات':''}{!user.is_active?' — موقوف':''}</option>)}
```


#### dashboard/src/pages/inventory/TabWarehouseLocations.tsx

```text
dashboard/src/pages/inventory/TabWarehouseLocations.tsx:450           {access.isCompanyAdmin && selectedLocationId !== null && (
dashboard/src/pages/inventory/TabWarehouseLocations.tsx:456           {access.isCompanyAdmin && (
dashboard/src/pages/inventory/TabWarehouseLocations.tsx:650       {access.isCompanyAdmin && (
```


#### dashboard/src/pages/inventory/archive/ArchiveOwnerWorkspace.tsx

```text
dashboard/src/pages/inventory/archive/ArchiveOwnerWorkspace.tsx:62       {intent.flow === "stocktake" && access.data && <Tab3Stocktake locationId={intent.locationId} companyId={`${access.data.company_id}:${access.data.driver_id}`} focusSessionId={intent.operationId} onFocusUnavailable={focusUnavailable} isAuditLocked authenticatedFetch={authFetch} onStocktakeChanged={onInventoryChanged} />}
```


#### dashboard/src/pages/inventory/batches/BatchDispositionManager.tsx

```text
dashboard/src/pages/inventory/batches/BatchDispositionManager.tsx:92     access.isCompanyAdmin ||
```


#### dashboard/src/pages/inventory/batches/BatchFocusWorkspace.tsx

```text
dashboard/src/pages/inventory/batches/BatchFocusWorkspace.tsx:26     access.isCompanyAdmin || access.can("inventory.transfer_policy.manage");
dashboard/src/pages/inventory/batches/BatchFocusWorkspace.tsx:78           {(access.isCompanyAdmin || access.can("batch.disposition")) && <button type="button" onClick={() => setEditingDisposition(true)} className="rounded-lg border px-3 py-2 text-sm focus-visible:ring-2">{t("batchFocus.changeDisposition")}</button>}
```


#### dashboard/src/pages/inventory/batches/BatchQuantityActions.tsx

```text
dashboard/src/pages/inventory/batches/BatchQuantityActions.tsx:318                         access.isCompanyAdmin ||
```


#### dashboard/src/pages/inventory/batches/useBatchDispositionCommand.ts

```text
dashboard/src/pages/inventory/batches/useBatchDispositionCommand.ts:89   const driverId = access.data?.driver_id ?? null;
dashboard/src/pages/inventory/batches/useBatchDispositionCommand.ts:91     batch && companyId !== null && driverId !== null
dashboard/src/pages/inventory/batches/useBatchDispositionCommand.ts:94           driverId,
```


#### dashboard/src/pages/inventory/batches/useBatchSpecialTransfer.ts

```text
dashboard/src/pages/inventory/batches/useBatchSpecialTransfer.ts:56   const driverId = access.data?.driver_id ?? null;
dashboard/src/pages/inventory/batches/useBatchSpecialTransfer.ts:64       driverId === null ||
dashboard/src/pages/inventory/batches/useBatchSpecialTransfer.ts:77       driverId,
```


#### dashboard/src/pages/inventory/batches/useBatchStockSources.ts

```text
dashboard/src/pages/inventory/batches/useBatchStockSources.ts:17   const driverId = access.data?.driver_id ?? null;
dashboard/src/pages/inventory/batches/useBatchStockSources.ts:23       driverId,
dashboard/src/pages/inventory/batches/useBatchStockSources.ts:30       driverId !== null,
```


#### dashboard/src/pages/inventory/batches/useBatchTerminalAction.ts

```text
dashboard/src/pages/inventory/batches/useBatchTerminalAction.ts:40   const driverId = access.data?.driver_id ?? null;
dashboard/src/pages/inventory/batches/useBatchTerminalAction.ts:43     if (!isOnline || companyId === null || driverId === null || busyKey !== null) return false;
dashboard/src/pages/inventory/batches/useBatchTerminalAction.ts:45     const scope = durableScope(companyId, driverId, "batch-terminal-quality-v1", key);
```


#### dashboard/src/pages/inventory/inventorySessionCache.ts

```text
dashboard/src/pages/inventory/inventorySessionCache.ts:104   driverId: string,
dashboard/src/pages/inventory/inventorySessionCache.ts:107   const driver = driverId.trim();
```


#### dashboard/src/pages/inventory/quality/useQualityBatchCandidates.ts

```text
dashboard/src/pages/inventory/quality/useQualityBatchCandidates.ts:12   const driverId = access.data?.driver_id ?? null;
dashboard/src/pages/inventory/quality/useQualityBatchCandidates.ts:15     queryKey: ["quality-batch-candidates", companyId, driverId, productVariantId],
dashboard/src/pages/inventory/quality/useQualityBatchCandidates.ts:16     enabled: productVariantId !== null && companyId !== null && driverId !== null,
```


#### dashboard/src/pages/inventory/stocktake/parsers.ts

```text
dashboard/src/pages/inventory/stocktake/parsers.ts:259         driver_id: positiveInt(
dashboard/src/pages/inventory/stocktake/parsers.ts:260           item.driver_id,
dashboard/src/pages/inventory/stocktake/parsers.ts:261           "vehicle_recon.driver_id"
```


#### dashboard/src/pages/inventory/stocktake/types.ts

```text
dashboard/src/pages/inventory/stocktake/types.ts:154   driver_id: number;
```


#### dashboard/src/pages/products/ProductsPage.tsx

```text
dashboard/src/pages/products/ProductsPage.tsx:63   const driverId =
dashboard/src/pages/products/ProductsPage.tsx:64     access.data?.driver_id ??
dashboard/src/pages/products/ProductsPage.tsx:85     isCompanyAdmin:
dashboard/src/pages/products/ProductsPage.tsx:86       access.isCompanyAdmin,
dashboard/src/pages/products/ProductsPage.tsx:102     access.isCompanyAdmin ||
dashboard/src/pages/products/ProductsPage.tsx:108       driverId,
dashboard/src/pages/products/ProductsPage.tsx:130       driverId,
dashboard/src/pages/products/ProductsPage.tsx:136       driverId,
dashboard/src/pages/products/ProductsPage.tsx:150       driverId,
dashboard/src/pages/products/ProductsPage.tsx:156       driverId,
dashboard/src/pages/products/ProductsPage.tsx:168       driverId,
dashboard/src/pages/products/ProductsPage.tsx:185       driverId,
dashboard/src/pages/products/ProductsPage.tsx:228       driverId,
dashboard/src/pages/products/ProductsPage.tsx:238       driverId,
dashboard/src/pages/products/ProductsPage.tsx:258     driverId,
dashboard/src/pages/products/ProductsPage.tsx:284     driverId,
```


#### dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx

```text
dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx:205   const driverId =
dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx:206     access.data?.driver_id ?? null;
dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx:208     access.isCompanyAdmin ||
dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx:211     access.isCompanyAdmin ||
dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx:448       driverId === null ||
dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx:461             driverId,
dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx:509               driverId,
dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx:596     driverId,
dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx:607       driverId === null
dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx:615       driverId,
```


#### dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx

```text
dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx:42   driverId: number | null;
dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx:57   driverId,
dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx:111         driverId !== null
dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx:114               driverId,
dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx:119       [companyId, driverId],
dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx:299     driverId !== null;
dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx:309       driverId,
dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx:323       driverId,
```


#### dashboard/src/pages/products/barcode/useIndependentPackageBarcode.ts

```text
dashboard/src/pages/products/barcode/useIndependentPackageBarcode.ts:34   driverId: number | null;
dashboard/src/pages/products/barcode/useIndependentPackageBarcode.ts:43   driverId,
dashboard/src/pages/products/barcode/useIndependentPackageBarcode.ts:61       driverId !== null &&
dashboard/src/pages/products/barcode/useIndependentPackageBarcode.ts:65             driverId,
dashboard/src/pages/products/barcode/useIndependentPackageBarcode.ts:72       driverId,
```


#### dashboard/src/pages/products/barcode/usePrimaryBarcodeReplacement.ts

```text
dashboard/src/pages/products/barcode/usePrimaryBarcodeReplacement.ts:40   driverId: number | null;
dashboard/src/pages/products/barcode/usePrimaryBarcodeReplacement.ts:50   driverId,
dashboard/src/pages/products/barcode/usePrimaryBarcodeReplacement.ts:68       driverId !== null &&
dashboard/src/pages/products/barcode/usePrimaryBarcodeReplacement.ts:72             driverId,
dashboard/src/pages/products/barcode/usePrimaryBarcodeReplacement.ts:79       driverId,
```


#### dashboard/src/pages/products/barcode/useProductBarcodeWorkflow.ts

```text
dashboard/src/pages/products/barcode/useProductBarcodeWorkflow.ts:5   driverId: number | null;
dashboard/src/pages/products/barcode/useProductBarcodeWorkflow.ts:12   driverId,
dashboard/src/pages/products/barcode/useProductBarcodeWorkflow.ts:31       driverId,
```


#### dashboard/src/pages/products/create/productDraftStorageKey.ts

```text
dashboard/src/pages/products/create/productDraftStorageKey.ts:3   driverId: number | null,
dashboard/src/pages/products/create/productDraftStorageKey.ts:5   return companyId && driverId
dashboard/src/pages/products/create/productDraftStorageKey.ts:6     ? `wanasah:product-draft:v2:${companyId}:${driverId}`
```


#### dashboard/src/pages/products/create/useCreateProductMutation.ts

```text
dashboard/src/pages/products/create/useCreateProductMutation.ts:66   driverId: number | null;
dashboard/src/pages/products/create/useCreateProductMutation.ts:118   driverId,
dashboard/src/pages/products/create/useCreateProductMutation.ts:292               driverId,
dashboard/src/pages/products/create/useCreateProductMutation.ts:382           driverId !== null &&
dashboard/src/pages/products/create/useCreateProductMutation.ts:397               driverId,
```


#### dashboard/src/pages/products/create/useCreateProductWorkflow.ts

```text
dashboard/src/pages/products/create/useCreateProductWorkflow.ts:48   driverId: number | null;
dashboard/src/pages/products/create/useCreateProductWorkflow.ts:70   driverId,
dashboard/src/pages/products/create/useCreateProductWorkflow.ts:112         driverId !== null
dashboard/src/pages/products/create/useCreateProductWorkflow.ts:119                 driverId,
dashboard/src/pages/products/create/useCreateProductWorkflow.ts:175       driverId
dashboard/src/pages/products/create/useCreateProductWorkflow.ts:264     driverId,
```


#### dashboard/src/pages/products/deriveProductsCapabilities.ts

```text
dashboard/src/pages/products/deriveProductsCapabilities.ts:2   isCompanyAdmin: boolean;
dashboard/src/pages/products/deriveProductsCapabilities.ts:8   isCompanyAdmin,
dashboard/src/pages/products/deriveProductsCapabilities.ts:13     isCompanyAdmin ||
dashboard/src/pages/products/deriveProductsCapabilities.ts:16     isCompanyAdmin ||
dashboard/src/pages/products/deriveProductsCapabilities.ts:19     isCompanyAdmin ||
dashboard/src/pages/products/deriveProductsCapabilities.ts:22     isCompanyAdmin ||
dashboard/src/pages/products/deriveProductsCapabilities.ts:25     isCompanyAdmin ||
dashboard/src/pages/products/deriveProductsCapabilities.ts:45       isCompanyAdmin ||
```


#### dashboard/src/pages/products/display-preferences/createProductDisplayPreferenceActions.ts

```text
dashboard/src/pages/products/display-preferences/createProductDisplayPreferenceActions.ts:21   driverId: number | null;
dashboard/src/pages/products/display-preferences/createProductDisplayPreferenceActions.ts:40   driverId,
dashboard/src/pages/products/display-preferences/createProductDisplayPreferenceActions.ts:53       driverId === null ||
dashboard/src/pages/products/display-preferences/createProductDisplayPreferenceActions.ts:56         driverId,
```


#### dashboard/src/pages/products/display-preferences/useProductDisplayPreferencesState.ts

```text
dashboard/src/pages/products/display-preferences/useProductDisplayPreferencesState.ts:25               "driver_id"
```


#### dashboard/src/pages/products/family/ProductFamiliesManager.tsx

```text
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:42   driverId: number | null;
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:181   driverId,
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:320       !driverId
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:328       driverId,
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:382     driverId,
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:390       !driverId
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:398       driverId,
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:456     driverId,
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:518       !driverId
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:526       driverId,
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:974         !driverId
dashboard/src/pages/products/family/ProductFamiliesManager.tsx:982         driverId,
```


#### dashboard/src/pages/products/family/ProductFamilyReassignDialog.tsx

```text
dashboard/src/pages/products/family/ProductFamilyReassignDialog.tsx:51   driverId: number | null;
dashboard/src/pages/products/family/ProductFamilyReassignDialog.tsx:119   driverId,
dashboard/src/pages/products/family/ProductFamilyReassignDialog.tsx:180       driverId === null
dashboard/src/pages/products/family/ProductFamilyReassignDialog.tsx:186       driverId,
dashboard/src/pages/products/family/ProductFamilyReassignDialog.tsx:192     driverId,
```


#### dashboard/src/pages/products/family/useProductFamiliesWorkflow.ts

```text
dashboard/src/pages/products/family/useProductFamiliesWorkflow.ts:5   driverId: number | null;
dashboard/src/pages/products/family/useProductFamiliesWorkflow.ts:10   driverId,
dashboard/src/pages/products/family/useProductFamiliesWorkflow.ts:24       driverId,
```


#### dashboard/src/pages/products/family/useProductFamilyReassignWorkflow.ts

```text
dashboard/src/pages/products/family/useProductFamilyReassignWorkflow.ts:5   driverId: number | null;
dashboard/src/pages/products/family/useProductFamilyReassignWorkflow.ts:10   driverId,
dashboard/src/pages/products/family/useProductFamilyReassignWorkflow.ts:29       driverId,
```


#### dashboard/src/pages/products/import/ImportInlineCorrectionPanel.tsx

```text
dashboard/src/pages/products/import/ImportInlineCorrectionPanel.tsx:10   driverId: number | null;
dashboard/src/pages/products/import/ImportInlineCorrectionPanel.tsx:17   jobId, companyId, driverId, online, authFetch, onAccepted,
dashboard/src/pages/products/import/ImportInlineCorrectionPanel.tsx:21     jobId, companyId, driverId, online, authFetch, onAccepted,
```


#### dashboard/src/pages/products/import/ImportProductModal.tsx

```text
dashboard/src/pages/products/import/ImportProductModal.tsx:25   driverId: number | null;
dashboard/src/pages/products/import/ImportProductModal.tsx:88   driverId,
dashboard/src/pages/products/import/ImportProductModal.tsx:235             driverId={driverId}
```


#### dashboard/src/pages/products/import/ImportProductStatusPanel.tsx

```text
dashboard/src/pages/products/import/ImportProductStatusPanel.tsx:21   driverId: number | null;
dashboard/src/pages/products/import/ImportProductStatusPanel.tsx:48   driverId,
dashboard/src/pages/products/import/ImportProductStatusPanel.tsx:195             key={`${companyId ?? "no-company"}:${driverId ?? "no-actor"}:${jobId}`}
dashboard/src/pages/products/import/ImportProductStatusPanel.tsx:198             driverId={driverId}
dashboard/src/pages/products/import/ImportProductStatusPanel.tsx:365               key={`${companyId ?? "no-company"}:${driverId ?? "no-actor"}:${jobId}`}
dashboard/src/pages/products/import/ImportProductStatusPanel.tsx:368               driverId={driverId}
```


#### dashboard/src/pages/products/import/correctionRouteGate.ts

```text
dashboard/src/pages/products/import/correctionRouteGate.ts:15   driverId: number | null,
dashboard/src/pages/products/import/correctionRouteGate.ts:19   if (!companyId || !driverId || !jobId) return true;
dashboard/src/pages/products/import/correctionRouteGate.ts:21     companyId, driverId, "product-import-correction", jobId,
dashboard/src/pages/products/import/correctionRouteGate.ts:24     companyId, driverId, "product-import-inline-correction", jobId,
dashboard/src/pages/products/import/correctionRouteGate.ts:38   driverId: number | null,
dashboard/src/pages/products/import/correctionRouteGate.ts:41   if (!companyId || !driverId || !jobId) return false;
dashboard/src/pages/products/import/correctionRouteGate.ts:43     companyId, driverId, "product-import-correction", jobId,
dashboard/src/pages/products/import/correctionRouteGate.ts:46     companyId, driverId, "product-import-inline-correction", jobId,
```


#### dashboard/src/pages/products/import/productImportSessionKey.ts

```text
dashboard/src/pages/products/import/productImportSessionKey.ts:3   driverId: number | null,
dashboard/src/pages/products/import/productImportSessionKey.ts:5   return companyId && driverId
dashboard/src/pages/products/import/productImportSessionKey.ts:6     ? `wanasah:product-import:v1:${companyId}:${driverId}`
```


#### dashboard/src/pages/products/import/useImportCorrection.ts

```text
dashboard/src/pages/products/import/useImportCorrection.ts:21   driverId: number | null;
dashboard/src/pages/products/import/useImportCorrection.ts:56   driverId,
dashboard/src/pages/products/import/useImportCorrection.ts:65   const currentScope = companyId && driverId && jobId
dashboard/src/pages/products/import/useImportCorrection.ts:66     ? productDurableScope(companyId, driverId, "product-import-correction", jobId)
dashboard/src/pages/products/import/useImportCorrection.ts:117       if (correctionRouteBlocked(companyId, driverId, jobId, "file")) {
```


#### dashboard/src/pages/products/import/useImportInlineCorrection.ts

```text
dashboard/src/pages/products/import/useImportInlineCorrection.ts:34   driverId: number | null;
dashboard/src/pages/products/import/useImportInlineCorrection.ts:86   jobId, companyId, driverId, online, authFetch, onAccepted,
dashboard/src/pages/products/import/useImportInlineCorrection.ts:89   const scope = companyId && driverId
dashboard/src/pages/products/import/useImportInlineCorrection.ts:90     ? productDurableScope(companyId, driverId, "product-import-inline-correction", jobId)
dashboard/src/pages/products/import/useImportInlineCorrection.ts:239       if (correctionRouteBlocked(companyId, driverId, jobId, "inline")) {
```


#### dashboard/src/pages/products/import/useImportProductUpload.ts

```text
dashboard/src/pages/products/import/useImportProductUpload.ts:43   driverId: number | null;
dashboard/src/pages/products/import/useImportProductUpload.ts:69   driverId,
dashboard/src/pages/products/import/useImportProductUpload.ts:121             driverId,
```


#### dashboard/src/pages/products/import/useImportProductWorkflow.ts

```text
dashboard/src/pages/products/import/useImportProductWorkflow.ts:38   driverId: number | null;
dashboard/src/pages/products/import/useImportProductWorkflow.ts:54   driverId,
dashboard/src/pages/products/import/useImportProductWorkflow.ts:91   const identity = String(companyId) + ":" + String(driverId);
dashboard/src/pages/products/import/useImportProductWorkflow.ts:115       driverId
dashboard/src/pages/products/import/useImportProductWorkflow.ts:152     driverId,
dashboard/src/pages/products/import/useImportProductWorkflow.ts:241     if (hasUnresolvedCorrectionWork(companyId, driverId, importJobId)) {
dashboard/src/pages/products/import/useImportProductWorkflow.ts:250     driverId,
dashboard/src/pages/products/import/useImportProductWorkflow.ts:279       driverId,
```


#### dashboard/src/pages/products/list/useProductCatalogSummary.ts

```text
dashboard/src/pages/products/list/useProductCatalogSummary.ts:5 export function useProductCatalogSummary({ companyId, driverId, authFetch }: {
dashboard/src/pages/products/list/useProductCatalogSummary.ts:7   driverId: number | null;
dashboard/src/pages/products/list/useProductCatalogSummary.ts:12     queryKey: ["simple-products", companyId, "catalog-summary", driverId],
dashboard/src/pages/products/list/useProductCatalogSummary.ts:13     enabled: Boolean(companyId && driverId),
```


#### dashboard/src/pages/products/list/useProductsListWorkflow.ts

```text
dashboard/src/pages/products/list/useProductsListWorkflow.ts:20   driverId: number | null;
dashboard/src/pages/products/list/useProductsListWorkflow.ts:31   driverId,
dashboard/src/pages/products/list/useProductsListWorkflow.ts:141   const summaryQuery = useProductCatalogSummary({ companyId, driverId, authFetch });
```


#### dashboard/src/pages/products/pricing/usePriceEditMutation.ts

```text
dashboard/src/pages/products/pricing/usePriceEditMutation.ts:80   driverId: number | null;
dashboard/src/pages/products/pricing/usePriceEditMutation.ts:99   driverId,
dashboard/src/pages/products/pricing/usePriceEditMutation.ts:151               driverId,
dashboard/src/pages/products/pricing/usePriceEditMutation.ts:226           driverId !== null &&
dashboard/src/pages/products/pricing/usePriceEditMutation.ts:239               driverId,
```


#### dashboard/src/pages/products/pricing/usePriceEditWorkflow.ts

```text
dashboard/src/pages/products/pricing/usePriceEditWorkflow.ts:34   driverId: number | null;
dashboard/src/pages/products/pricing/usePriceEditWorkflow.ts:43   driverId,
dashboard/src/pages/products/pricing/usePriceEditWorkflow.ts:75           driverId,
dashboard/src/pages/products/pricing/usePriceEditWorkflow.ts:135     driverId,
```


#### dashboard/src/pages/products/productDurableScope.ts

```text
dashboard/src/pages/products/productDurableScope.ts:7   driverId: number | null,
dashboard/src/pages/products/productDurableScope.ts:13     !driverId
dashboard/src/pages/products/productDurableScope.ts:21     driverId,
```


#### dashboard/src/pages/products/rename/ProductRenameDialog.tsx

```text
dashboard/src/pages/products/rename/ProductRenameDialog.tsx:36   driverId: number | null;
dashboard/src/pages/products/rename/ProductRenameDialog.tsx:98   driverId,
dashboard/src/pages/products/rename/ProductRenameDialog.tsx:125       driverId === null
dashboard/src/pages/products/rename/ProductRenameDialog.tsx:131       driverId,
dashboard/src/pages/products/rename/ProductRenameDialog.tsx:137     driverId,
```


#### dashboard/src/pages/products/rename/useProductRenameWorkflow.ts

```text
dashboard/src/pages/products/rename/useProductRenameWorkflow.ts:5   driverId: number | null;
dashboard/src/pages/products/rename/useProductRenameWorkflow.ts:10   driverId,
dashboard/src/pages/products/rename/useProductRenameWorkflow.ts:28       driverId,
```


#### dashboard/src/pages/products/tracking/useProductTrackingMutations.ts

```text
dashboard/src/pages/products/tracking/useProductTrackingMutations.ts:124   driverId: number | null;
dashboard/src/pages/products/tracking/useProductTrackingMutations.ts:162   driverId,
dashboard/src/pages/products/tracking/useProductTrackingMutations.ts:200             driverId,
dashboard/src/pages/products/tracking/useProductTrackingMutations.ts:273           driverId !== null &&
dashboard/src/pages/products/tracking/useProductTrackingMutations.ts:284               driverId,
dashboard/src/pages/products/tracking/useProductTrackingMutations.ts:327             driverId,
dashboard/src/pages/products/tracking/useProductTrackingMutations.ts:393           driverId !== null &&
dashboard/src/pages/products/tracking/useProductTrackingMutations.ts:405               driverId,
```


#### dashboard/src/pages/products/tracking/useProductTrackingWorkflow.ts

```text
dashboard/src/pages/products/tracking/useProductTrackingWorkflow.ts:57   driverId: number | null;
dashboard/src/pages/products/tracking/useProductTrackingWorkflow.ts:71   driverId,
dashboard/src/pages/products/tracking/useProductTrackingWorkflow.ts:125             driverId,
dashboard/src/pages/products/tracking/useProductTrackingWorkflow.ts:181             driverId,
dashboard/src/pages/products/tracking/useProductTrackingWorkflow.ts:245     driverId,
```


#### dashboard/src/pages/products/useProductsIdentityScopeReset.ts

```text
dashboard/src/pages/products/useProductsIdentityScopeReset.ts:175   driverId: number | null;
dashboard/src/pages/products/useProductsIdentityScopeReset.ts:187   driverId,
dashboard/src/pages/products/useProductsIdentityScopeReset.ts:253       driverId !== null
dashboard/src/pages/products/useProductsIdentityScopeReset.ts:256             driverId
dashboard/src/pages/products/useProductsIdentityScopeReset.ts:312     driverId,
```


#### dashboard/src/pages/suppliers/SuppliersPage.tsx

```text
dashboard/src/pages/suppliers/SuppliersPage.tsx:31   const commands = useSupplierCommands(search.access.data?.company_id, search.access.data?.driver_id);
dashboard/src/pages/suppliers/SuppliersPage.tsx:131       storageKey={supplierDraftKey(search.access.data?.company_id, search.access.data?.driver_id, editor.supplier?.id ?? "new")}
```


#### dashboard/src/pages/suppliers/useSupplierListSearch.ts

```text
dashboard/src/pages/suppliers/useSupplierListSearch.ts:23     queryKey: ["supplier-list", access.data?.company_id, access.data?.driver_id, active, search, generation],
```


#### dashboard/src/types/dispatch.ts

```text
dashboard/src/types/dispatch.ts:23   driverId: string;
dashboard/src/types/dispatch.ts:54   driverId?: string;
```

### Flutter — exact-word persisted/camelCase/channel identity contracts

| File | Matched lines | Source role / interpretation |
|---|---|---|
| wanasah_frontend/lib/blocs/auth/auth_bloc.dart | 17 | Credential/principal/auth transport; separate field ownership from authentication. |
| wanasah_frontend/lib/blocs/auth/auth_state.dart | 3 | Credential/principal/auth transport; separate field ownership from authentication. |
| wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart | 11 | Field auth/state/event/screen/repository/queue contract. |
| wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart | 12 | Field auth/state/event/screen/repository/queue contract. |
| wanasah_frontend/lib/core/network/api_client.dart | 1 | Field auth/state/event/screen/repository/queue contract. |
| wanasah_frontend/lib/repositories/dashboard_repository.dart | 4 | Field auth/state/event/screen/repository/queue contract. |
| wanasah_frontend/lib/screens/dashboard_screen.dart | 10 | Field auth/state/event/screen/repository/queue contract. |
| wanasah_frontend/lib/screens/login_screen.dart | 1 | Field auth/state/event/screen/repository/queue contract. |
| wanasah_frontend/lib/screens/splash_screen.dart | 1 | Field auth/state/event/screen/repository/queue contract. |
| wanasah_frontend/lib/screens/visit_list_screen.dart | 2 | Field auth/state/event/screen/repository/queue contract. |

#### wanasah_frontend/lib/blocs/auth/auth_bloc.dart

```text
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:38       final String? driverIdString = await _storage.read(key: 'driver_id');
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:42         final int? driverId = int.tryParse(driverIdString);
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:44         if (driverId != null) {
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:49             '[AuthBloc] CheckAuth → Authenticated (driverId=$driverId, Tenant=$companyCode)',
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:51           emit(AuthAuthenticated(driverId: driverId));
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:55             '[AuthBloc] CheckAuth → Failed to parse driver_id: "$driverIdString" is not an integer.',
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:78         '/driver/login',
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:94       final int? driverId = (data['driver_id'] as num?)?.toInt();
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:96       if (token == null || token.isEmpty || driverId == null) {
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:97         developer.log('[AuthBloc] Login → Missing token or driver_id in response.');
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:114       final String? oldDriverId = await _storage.read(key: 'driver_id');
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:141       } else if (oldDriverId != null && oldDriverId.isNotEmpty && oldDriverId != driverId.toString()) {
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:142         developer.log('[AuthBloc] Login → Different driver for same company ($oldDriverId → $driverId). Wiping legacy data.');
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:159       await _storage.write(key: 'driver_id', value: driverId.toString());
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:161       developer.log('[AuthBloc] Login → Authenticated (driverId=$driverId, Tenant=$returnedCompanyCode)');
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:162       emit(AuthAuthenticated(driverId: driverId));
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:209     await _storage.delete(key: 'driver_id');
```


#### wanasah_frontend/lib/blocs/auth/auth_state.dart

```text
wanasah_frontend/lib/blocs/auth/auth_state.dart:29   final int driverId;
wanasah_frontend/lib/blocs/auth/auth_state.dart:31   const AuthAuthenticated({required this.driverId});
wanasah_frontend/lib/blocs/auth/auth_state.dart:34   List<Object?> get props => [driverId];
```


#### wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart

```text
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:475         final int? driverId = await _dashboardRepo.getDriverId();
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:476         add(FetchDashboardData(driverId: driverId ?? 0));
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:518         final int? driverId = await _dashboardRepo.getDriverId();
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:519         add(FetchDashboardData(driverId: driverId ?? 0));
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:543       add(FetchDashboardData(driverId: event.driverId));
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:548         add(FetchDashboardData(driverId: event.driverId));
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:580       add(FetchDashboardData(driverId: event.driverId));
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:588         add(FetchDashboardData(driverId: event.driverId));
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:615       final wasSentLive = await _dashboardRepo.toggleBreak(event.driverId, event.action);
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:623       add(FetchDashboardData(driverId: event.driverId));
wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart:630         add(FetchDashboardData(driverId: event.driverId));
```


#### wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart

```text
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:28   final int driverId;
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:29   const FetchDashboardData({required this.driverId});
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:32   List<Object?> get props => [driverId];
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:76   final int driverId;
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:77   const StartSessionEvent({required this.driverId});
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:80   List<Object?> get props => [driverId];
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:85   final int driverId;
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:86   const EndSessionEvent({required this.driverId});
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:89   List<Object?> get props => [driverId];
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:94   final int driverId;
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:97   const ToggleBreakEvent({required this.driverId, required this.action});
wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart:100   List<Object?> get props => [driverId, action];
```


#### wanasah_frontend/lib/core/network/api_client.dart

```text
wanasah_frontend/lib/core/network/api_client.dart:81                          err.requestOptions.path.endsWith('/driver/login') ||
```


#### wanasah_frontend/lib/repositories/dashboard_repository.dart

```text
wanasah_frontend/lib/repositories/dashboard_repository.dart:36   Future<bool> toggleBreak(int driverId, String action) async {
wanasah_frontend/lib/repositories/dashboard_repository.dart:59           payload: jsonEncode({'driver_id': driverId, 'action': action}),
wanasah_frontend/lib/repositories/dashboard_repository.dart:107   Future<int?> getDriverId() async {
wanasah_frontend/lib/repositories/dashboard_repository.dart:108     final str = await _storage.read(key: 'driver_id');
```


#### wanasah_frontend/lib/screens/dashboard_screen.dart

```text
wanasah_frontend/lib/screens/dashboard_screen.dart:17   final int driverId;
wanasah_frontend/lib/screens/dashboard_screen.dart:18   const DashboardScreen({required this.driverId, super.key});
wanasah_frontend/lib/screens/dashboard_screen.dart:36       FetchDashboardData(driverId: widget.driverId),
wanasah_frontend/lib/screens/dashboard_screen.dart:83     context.read<DashboardBloc>().add(StartSessionEvent(driverId: widget.driverId));
wanasah_frontend/lib/screens/dashboard_screen.dart:87     context.read<DashboardBloc>().add(EndSessionEvent(driverId: widget.driverId));
wanasah_frontend/lib/screens/dashboard_screen.dart:91     context.read<DashboardBloc>().add(ToggleBreakEvent(driverId: widget.driverId, action: action));
wanasah_frontend/lib/screens/dashboard_screen.dart:362                   FetchDashboardData(driverId: widget.driverId),
wanasah_frontend/lib/screens/dashboard_screen.dart:443                               FetchDashboardData(driverId: widget.driverId),
wanasah_frontend/lib/screens/dashboard_screen.dart:877                         (context) => VisitListScreen(driverId: widget.driverId),
wanasah_frontend/lib/screens/dashboard_screen.dart:882                       FetchDashboardData(driverId: widget.driverId),
```


#### wanasah_frontend/lib/screens/login_screen.dart

```text
wanasah_frontend/lib/screens/login_screen.dart:74               builder: (_) => DashboardScreen(driverId: state.driverId),
```


#### wanasah_frontend/lib/screens/splash_screen.dart

```text
wanasah_frontend/lib/screens/splash_screen.dart:38               builder: (_) => DashboardScreen(driverId: state.driverId),
```


#### wanasah_frontend/lib/screens/visit_list_screen.dart

```text
wanasah_frontend/lib/screens/visit_list_screen.dart:17   final int driverId;
wanasah_frontend/lib/screens/visit_list_screen.dart:18   const VisitListScreen({required this.driverId, super.key});
```

### Backend — get_current_admin definition/import/dependency source hits

| File | Matched lines | Source role / interpretation |
|---|---|---|
| wa_backend/api/branches.py | 6 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/dependencies.py | 1 | Credential/principal/auth transport; separate field ownership from authentication. |
| wa_backend/api/dispatch.py | 18 | Mixed field ownership and authenticated action actor; use exact function/FK mapping. |
| wa_backend/api/inventory_permissions.py | 10 | Shared actor/field contract; evidence below; no blanket rename. |
| wa_backend/api/sales_returns.py | 6 | Shared actor/field contract; evidence below; no blanket rename. |

#### wa_backend/api/branches.py

```text
wa_backend/api/branches.py:15 from api.dependencies import get_current_admin, get_current_driver
wa_backend/api/branches.py:208     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/branches.py:225     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/branches.py:291     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/branches.py:427     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/branches.py:443     current_admin: Driver = Depends(get_current_admin),
```


#### wa_backend/api/dependencies.py

```text
wa_backend/api/dependencies.py:126 async def get_current_admin(current_driver: Driver = Depends(get_current_driver)):
```


#### wa_backend/api/dispatch.py

```text
wa_backend/api/dispatch.py:8 from api.dependencies import get_current_admin, get_current_driver
wa_backend/api/dispatch.py:130     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:616     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:769     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:902     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:3073     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:3234     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4268     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:4407     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4467     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4532     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4592     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4614     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4672     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:4848     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:4895     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/dispatch.py:5136     current_admin: Driver = Depends(get_current_admin)
wa_backend/api/dispatch.py:5231     current_admin: Driver = Depends(get_current_admin)
```


#### wa_backend/api/inventory_permissions.py

```text
wa_backend/api/inventory_permissions.py:8 from api.dependencies import get_current_driver, get_current_admin
wa_backend/api/inventory_permissions.py:66 async def permission_catalog(actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:72                 db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:135                       actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:141                       actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:147                 db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:156                     db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:173                       db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:184                 actor: Driver = Depends(get_current_admin)):
wa_backend/api/inventory_permissions.py:207                  db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
```


#### wa_backend/api/sales_returns.py

```text
wa_backend/api/sales_returns.py:8 from api.dependencies import get_current_admin
wa_backend/api/sales_returns.py:37     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/sales_returns.py:58     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/sales_returns.py:78     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/sales_returns.py:94     current_admin: Driver = Depends(get_current_admin),
wa_backend/api/sales_returns.py:110     current_admin: Driver = Depends(get_current_admin),
```


### Dashboard compound Driver / driverId identifiers beyond canonical payload keys

The union with the prior word/payload ledger covers 440 matched lines / 502 occurrences / 90 files. Additional source lines (all other matches already retained above):

```text
dashboard/src/components/dashboard/HeroSettlement.tsx:32       {/* Driver info */}
dashboard/src/components/dispatch/PostponedRoutesModal.tsx:19   onUpdateDriver,
dashboard/src/components/dispatch/PostponedRoutesModal.tsx:58                         onChange={(e) => onUpdateDriver(route.id, e.target.value)}
dashboard/src/components/dispatch/RouteManagementModal.tsx:14   transferDriverId: string;
dashboard/src/components/dispatch/RouteManagementModal.tsx:15   onTransferDriverChange: (id: string) => void;
dashboard/src/components/dispatch/RouteManagementModal.tsx:32   transferDriverId,
dashboard/src/components/dispatch/RouteManagementModal.tsx:33   onTransferDriverChange,
dashboard/src/components/dispatch/RouteManagementModal.tsx:79             <span className="text-xs font-semibold text-slate-600">المندوب / Driver</span>
dashboard/src/components/dispatch/RouteManagementModal.tsx:90                 value={transferDriverId}
dashboard/src/components/dispatch/RouteManagementModal.tsx:91                 onChange={onTransferDriverChange}
dashboard/src/components/dispatch/ShortageModal.tsx:40   shortageDriverId: string;
dashboard/src/components/dispatch/ShortageModal.tsx:41   onDriverChange: (id: string) => void;
dashboard/src/components/dispatch/ShortageModal.tsx:340   shortageDriverId,
dashboard/src/components/dispatch/ShortageModal.tsx:341   onDriverChange,
dashboard/src/components/dispatch/ShortageModal.tsx:395                 value={shortageDriverId}
dashboard/src/components/dispatch/ShortageModal.tsx:396                 onChange={onDriverChange}
dashboard/src/components/operations/CommandCenter.tsx:9 interface DriverVisits {
dashboard/src/components/operations/CommandCenter.tsx:36 export interface ActiveDriver {
dashboard/src/components/operations/CommandCenter.tsx:43   visits?: DriverVisits;
dashboard/src/components/operations/CommandCenter.tsx:49   driver: ActiveDriver | null;
dashboard/src/components/operations/FleetRadar.tsx:4 import type { DriverData } from "@/data/operations-data";
dashboard/src/components/operations/FleetRadar.tsx:7   drivers: DriverData[];
dashboard/src/components/operations/FleetRadar.tsx:44       {/* Driver rows */}
dashboard/src/components/operations/PulseBar.tsx:13   activeDrivers: number;
dashboard/src/components/operations/PulseBar.tsx:14   onBreakDrivers: number;
dashboard/src/components/operations/PulseBar.tsx:22   activeDrivers, onBreakDrivers, onOpenSalesDetails, onRefresh,
dashboard/src/components/operations/PulseBar.tsx:106             <span className="text-3xl font-black tabular-nums tracking-tighter text-slate-800 leading-none">{activeDrivers}</span>
dashboard/src/components/operations/PulseBar.tsx:114             <span className="text-3xl font-black tabular-nums tracking-tighter text-slate-800 leading-none">{onBreakDrivers}</span>
dashboard/src/components/operations/SettlementModal.tsx:16 import type { DriverData, SessionSettlementReport } from "@/data/operations-data";
dashboard/src/components/operations/SettlementModal.tsx:33   driver: DriverData | null;
dashboard/src/data/operations-data.ts:121 export interface DriverData {
dashboard/src/data/operations-data.ts:155 export function parseDriverDataList(raw: unknown): DriverData[] {
dashboard/src/data/operations-data.ts:162   return result.data as DriverData[];
dashboard/src/data/operations-data.ts:172 export function getFleetStats(drivers: DriverData[]) {
dashboard/src/data/operations-data.ts:185   const activeDrivers = drivers.filter(
dashboard/src/data/operations-data.ts:188   const onBreakDrivers = drivers.filter(
dashboard/src/data/operations-data.ts:200     activeDrivers,
dashboard/src/data/operations-data.ts:201     onBreakDrivers,
dashboard/src/data/operations-data.ts:202     totalDrivers: drivers.length,
dashboard/src/features/operations/useSettlementOwnerNavigation.ts:6 import { FINANCIAL_SETTLEMENT_READY_STATUS, parseDriverDataList, type DriverData } from "@/data/operations-data";
dashboard/src/features/operations/useSettlementOwnerNavigation.ts:11   onReady: (driver: DriverData) => void;
dashboard/src/features/operations/useSettlementOwnerNavigation.ts:22         const driver = parseDriverDataList(raw).find((item) => item.session.session_id === intent.sessionId);
dashboard/src/i18n/resources.ts:3758               ROUTE_LOAD: "Driver load · {{reference}}",
dashboard/src/i18n/resources.ts:3759               ROUTE_RETURN: "Driver custody return · {{reference}}",
dashboard/src/pages/DispatchBoard.tsx:256   const [drivers, setDrivers] = useState<{ id: string; name: string }[]>([]);
dashboard/src/pages/DispatchBoard.tsx:280   const [selectedDriverId, setSelectedDriverId] = useState(() => localStorage.getItem("wanasah_route_driver") || "");
dashboard/src/pages/DispatchBoard.tsx:285     localStorage.setItem("wanasah_route_driver", selectedDriverId);
dashboard/src/pages/DispatchBoard.tsx:287   }, [selectedZoneId, selectedDriverId, selectedVehicleId]);
dashboard/src/pages/DispatchBoard.tsx:297   const [transferDriverId, setTransferDriverId] = useState("");
dashboard/src/pages/DispatchBoard.tsx:301   const [shortageDriverId, setShortageDriverId] = useState("");
dashboard/src/pages/DispatchBoard.tsx:385         const nextDrivers = Array.isArray(data.drivers) ? data.drivers : [];
dashboard/src/pages/DispatchBoard.tsx:391         setDrivers(nextDrivers);
dashboard/src/pages/DispatchBoard.tsx:404         setSelectedDriverId((prev) =>
dashboard/src/pages/DispatchBoard.tsx:405           nextDrivers.some((driver) => driver.id === prev) ? prev : ""
dashboard/src/pages/DispatchBoard.tsx:795       !selectedDriverId ||
dashboard/src/pages/DispatchBoard.tsx:829         setSelectedZoneId(""); setSelectedDriverId(""); setSelectedVehicleId(""); setPreloadQuantities({});
dashboard/src/pages/DispatchBoard.tsx:852     const newDriverId =
dashboard/src/pages/DispatchBoard.tsx:1374     setShortageDriverId("");
dashboard/src/pages/DispatchBoard.tsx:1560                 <CustomSelect labelBg="bg-slate-50" label="المندوب" options={drivers.map(d => ({ id: d.id, label: d.name }))} value={selectedDriverId} onChange={setSelectedDriverId} placeholder="اختر المندوب" />
dashboard/src/pages/DispatchBoard.tsx:1773         shortageDriverId={shortageDriverId}
dashboard/src/pages/DispatchBoard.tsx:1774         onDriverChange={setShortageDriverId}
dashboard/src/pages/DispatchBoard.tsx:1776         onCancelEdit={() => { setShortageDraft([]); setEditingShortageIds([]); setShortageZoneId(""); setShortageShopId(""); setShortageDriverId(""); }}
dashboard/src/pages/DispatchBoard.tsx:1788         transferDriverId={transferDriverId}
dashboard/src/pages/DispatchBoard.tsx:1789         onTransferDriverChange={setTransferDriverId}
dashboard/src/pages/OperationsDashboard.tsx:11   parseDriverDataList,
dashboard/src/pages/OperationsDashboard.tsx:15   DriverData,
dashboard/src/pages/OperationsDashboard.tsx:121   const [drivers, setDrivers] = useState<DriverData[]>([]);
dashboard/src/pages/OperationsDashboard.tsx:125   const [settlementDriver, setSettlementDriver] = useState<DriverData | null>(null);
dashboard/src/pages/OperationsDashboard.tsx:142         setDrivers(parseDriverDataList(data));
dashboard/src/pages/OperationsDashboard.tsx:238   const selectedDriver = drivers.find((d) => d.session.session_id === selectedId) ?? null;
dashboard/src/pages/OperationsDashboard.tsx:241     if (!selectedDriver) return;
dashboard/src/pages/OperationsDashboard.tsx:242     setSettlementDriver(selectedDriver);
dashboard/src/pages/OperationsDashboard.tsx:244     void loadSettlementReport(selectedDriver.session.session_id);
dashboard/src/pages/OperationsDashboard.tsx:245   }, [loadSettlementReport, selectedDriver]);
dashboard/src/pages/OperationsDashboard.tsx:248   const openSettlementOwner = useCallback((driver: DriverData) => {
dashboard/src/pages/OperationsDashboard.tsx:250     setDrivers((rows) => [driver, ...rows.filter((row) => row.session.session_id !== driver.session.session_id)]);
dashboard/src/pages/OperationsDashboard.tsx:251     setSettlementDriver(driver);
dashboard/src/pages/OperationsDashboard.tsx:272     if (settlementDriver) {
dashboard/src/pages/OperationsDashboard.tsx:273       void loadSettlementReport(settlementDriver.session.session_id);
dashboard/src/pages/OperationsDashboard.tsx:275   }, [loadSettlementReport, settlementDriver]);
dashboard/src/pages/OperationsDashboard.tsx:332     setDrivers((prev) => prev.map((d) => d.session.session_id === id ? { ...d, session: { ...d.session, is_authorized_to_sell: newAuthStatus } } : d));
dashboard/src/pages/OperationsDashboard.tsx:343       setDrivers((prev) => prev.map((d) => d.session.session_id === id ? { ...d, session: { ...d.session, is_authorized_to_sell: !newAuthStatus } } : d));
dashboard/src/pages/OperationsDashboard.tsx:350     if (!settlementDriver || !settlementReport || isSettling) return;
dashboard/src/pages/OperationsDashboard.tsx:358       const response = await authFetch(`/admin/sessions/${settlementDriver.session.session_id}/settle`, {
dashboard/src/pages/OperationsDashboard.tsx:364       toast.success(`تم اعتماد تسوية ${settlementDriver.session.driver_name} وإغلاق العهدة بنجاح!`);
dashboard/src/pages/OperationsDashboard.tsx:414         activeDrivers={stats.activeDrivers}
dashboard/src/pages/OperationsDashboard.tsx:415         onBreakDrivers={stats.onBreakDrivers}
dashboard/src/pages/OperationsDashboard.tsx:443             driver={selectedDriver}
dashboard/src/pages/OperationsDashboard.tsx:446               if (!selectedDriver) return;
dashboard/src/pages/OperationsDashboard.tsx:447               setUndoSessionId(selectedDriver.session.session_id);
dashboard/src/pages/OperationsDashboard.tsx:456         driver={settlementDriver}
```

### Flutter compound identity identifiers beyond exact word census

The union with the prior word/payload ledger covers 64 matched lines / 99 occurrences / 10 files. Additional source lines (all other matches already retained above):

```text
wanasah_frontend/lib/blocs/auth/auth_bloc.dart:41       if (token != null && token.isNotEmpty && driverIdString != null && companyCode != null) {
wanasah_frontend/lib/blocs/auth/auth_state.dart:26 // ─── مُوثَّق — يوجد توكن وdriverId صالحان ──────────────────────────────────
```

### JWT/access-channel semantic source ledger

```text
wa_backend/api/auth.py:37 def create_access_token(data: dict, company_id: int, role_name: str = "Driver"):
wa_backend/api/auth.py:43         "jti": uuid.uuid4().hex,
wa_backend/api/auth.py:45         "role": role_name  # +++ حقن الـ Role للـ RBAC +++
wa_backend/api/auth.py:47     return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")
wa_backend/api/auth.py:49 def create_refresh_token(data: dict, company_id: int):
wa_backend/api/auth.py:55         "jti": uuid.uuid4().hex,
wa_backend/api/auth.py:58     return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")
wa_backend/api/auth.py:126     access_token = create_access_token({"sub": str(driver.id), "is_admin": driver.is_admin, "username": driver.username}, company_id=comp_id, role_name="Driver")
wa_backend/api/auth.py:127     refresh_token = create_refresh_token({"sub": str(driver.id), "role": "Driver"}, company_id=comp_id)
wa_backend/api/auth.py:184     access_token = create_access_token({"sub": str(admin.id), "is_admin": admin.is_admin, "username": admin.username}, company_id=comp_id, role_name="Admin" if admin.is_admin else "Inventory")
wa_backend/api/auth.py:185     refresh_token = create_refresh_token({"sub": str(admin.id), "role": "Admin" if admin.is_admin else "Inventory"}, company_id=comp_id)
wa_backend/api/auth.py:203     role = decoded.get("role")
wa_backend/api/auth.py:204     if role in {"Admin", "Inventory", "Driver"}:
wa_backend/api/auth.py:205         return str(role)
wa_backend/api/auth.py:240         decoded = jwt.decode(
wa_backend/api/auth.py:246         if decoded.get("type") != "refresh":
wa_backend/api/auth.py:249         driver_id = int(decoded.get("sub", 0))
wa_backend/api/auth.py:250         company_id = decoded.get("company_id")
wa_backend/api/auth.py:295         role_name = _refresh_role(decoded, driver)
wa_backend/api/auth.py:310             replacement_access = create_access_token(
wa_backend/api/auth.py:312                     "sub": str(driver.id),
wa_backend/api/auth.py:317                 role_name=role_name,
wa_backend/api/auth.py:325         new_access = create_access_token(
wa_backend/api/auth.py:327                 "sub": str(driver.id),
wa_backend/api/auth.py:332             role_name=role_name,
wa_backend/api/auth.py:334         new_refresh = create_refresh_token(
wa_backend/api/auth.py:335             {"sub": str(driver.id), "role": role_name},
wa_backend/api/auth.py:375         jwt.decode(access_token, options={"verify_signature": False})
wa_backend/api/dependencies.py:10 from token_identity import access_token_identity
wa_backend/api/dependencies.py:19         payload = jwt.decode(
wa_backend/api/dependencies.py:25         driver_id_int, comp_id_int = access_token_identity(payload)
wa_backend/token_identity.py:14 def access_token_identity(payload: Mapping[str, Any]) -> tuple[int, int]:
wa_backend/token_identity.py:16     if payload.get('type') != 'access':
wa_backend/token_identity.py:18     return _positive_id(payload.get('sub')), _positive_id(payload.get('company_id'))
wa_backend/realtime/auth.py:11 from token_identity import access_token_identity
wa_backend/realtime/auth.py:28     require_admin: bool,
wa_backend/realtime/auth.py:31         payload = jwt.decode(
wa_backend/realtime/auth.py:37         driver_id, company_id = access_token_identity(payload)
wa_backend/realtime/auth.py:63                 require_admin
wa_backend/realtime/auth.py:83         require_admin=True,
wa_backend/realtime/auth.py:93         require_admin=False,
wa_backend/api/platform_manager.py:32         payload = jwt.decode(
wa_backend/api/platform_manager.py:36             options={"require": ["exp", "sub", "type"]},
wa_backend/api/platform_manager.py:38         if payload.get("type") != "platform_access" or payload.get("is_platform_admin") is not True:
wa_backend/api/platform_manager.py:40         raw_admin_id = payload.get("sub")
wa_backend/api/platform_manager.py:163     token = jwt.encode({
wa_backend/api/platform_manager.py:164         "sub": str(admin.id),
wa_backend/api/platform_manager.py:166         "is_platform_admin": True,
wa_backend/api/platform_manager.py:167         "role": "GodMode",
wa_backend/api/platform_manager.py:168         "type": "platform_access",
wa_backend/api/platform_manager.py:169         "jti": uuid.uuid4().hex,
wa_backend/api/platform_manager.py:173     return {"token": token, "admin": admin.username, "role": "PlatformAdmin"}
wa_backend/api/platform_manager.py:200         # The application role remains subject to RLS; it never receives a bypass.
```

## Appendix B — Endpoint dependency and guard evidence

For each matrix registration, the file/function at the matrix line is the HTTP owner. The following list identifies reachable legacy leaves and current guard call expressions with source positions. Parameterized guard arguments, explicit route/location ids and any_location are retained; a flat code list is never substituted for their decision semantics.

### POST /driver/login — driver_login

Source: `wa_backend/api/auth.py:89`. Legacy path: `wa_backend/api/auth.py:89:driver_login`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /login — admin_login

Source: `wa_backend/api/auth.py:144`. Legacy path: `wa_backend/api/auth.py:144:admin_login`, `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /refresh — refresh_access_token

Source: `wa_backend/api/auth.py:238`. Legacy path: `wa_backend/api/auth.py:202:_refresh_role`, `wa_backend/api/auth.py:238:refresh_access_token`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /warehouse/branches/options — list_branch_options

Source: `wa_backend/api/branches.py:181`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/branches.py:189 access.require(('location.create', 'location.update'), any_location=True)
```

### GET /warehouse/branches/manage — manage_branches

Source: `wa_backend/api/branches.py:202`. Legacy path: `wa_backend/api/branches.py:202:manage_branches`, `wa_backend/api/dependencies.py:126:get_current_admin`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /warehouse/branches — create_branch

Source: `wa_backend/api/branches.py:222`. Legacy path: `wa_backend/api/branches.py:222:create_branch`, `wa_backend/api/dependencies.py:126:get_current_admin`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### PATCH /warehouse/branches/{branch_id} — update_branch

Source: `wa_backend/api/branches.py:287`. Legacy path: `wa_backend/api/branches.py:287:update_branch`, `wa_backend/api/dependencies.py:126:get_current_admin`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /warehouse/branches/{branch_id}/activate — activate_branch

Source: `wa_backend/api/branches.py:423`. Legacy path: `wa_backend/api/branches.py:423:activate_branch`, `wa_backend/api/dependencies.py:126:get_current_admin`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /warehouse/branches/{branch_id}/deactivate — deactivate_branch

Source: `wa_backend/api/branches.py:439`. Legacy path: `wa_backend/api/branches.py:439:deactivate_branch`, `wa_backend/api/dependencies.py:126:get_current_admin`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /catalog/uoms — list_uoms

Source: `wa_backend/api/catalog.py:583`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:586 _require(db, actor, 'catalog.read')
```

### GET /catalog/products — list_products

Source: `wa_backend/api/catalog.py:592`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:598 _require(db, actor, 'catalog.read')
```

### POST /catalog/products — create_product

Source: `wa_backend/api/catalog.py:610`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:613 _require(db, actor, 'catalog.manage')
```

### PATCH /catalog/products/{product_id} — update_product

Source: `wa_backend/api/catalog.py:636`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:639 _require(db, actor, 'catalog.manage')
```

### GET /catalog/variants — list_variants

Source: `wa_backend/api/catalog.py:669`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:676 _require(db, actor, 'catalog.read')
```

### POST /catalog/variants/resolve — resolve_variants

Source: `wa_backend/api/catalog.py:691`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:696 _require(db, actor, 'catalog.read')
```

### POST /catalog/variants — create_variant

Source: `wa_backend/api/catalog.py:716`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:719 _require(db, actor, 'catalog.manage')
```

### PATCH /catalog/variants/{variant_id} — update_variant

Source: `wa_backend/api/catalog.py:756`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:759 _require(db, actor, 'catalog.manage')
```

### PATCH /catalog/variants/{variant_id}/name — rename_variant_name

Source: `wa_backend/api/catalog.py:796`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:802 _require(db, actor, 'catalog.manage')
```

### PATCH /catalog/variants/{variant_id}/family — reassign_variant_family

Source: `wa_backend/api/catalog.py:875`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:881 _require(db, actor, 'catalog.manage')
```

### GET /catalog/variants/{variant_id}/conversions — list_conversions

Source: `wa_backend/api/catalog.py:950`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:951 _require(db, actor, 'catalog.read')
```

### POST /catalog/variants/{variant_id}/conversions — create_conversion

Source: `wa_backend/api/catalog.py:961`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:962 _require(db, actor, 'catalog.manage')
```

### PATCH /catalog/conversions/{conversion_id} — update_conversion

Source: `wa_backend/api/catalog.py:989`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:995 _require(db, actor, 'catalog.manage')
```

### GET /catalog/variants/{variant_id}/barcodes — list_barcodes

Source: `wa_backend/api/catalog.py:1068`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1075 _require(db, actor, 'catalog.read')
```

### POST /catalog/variants/{variant_id}/barcodes — create_barcode

Source: `wa_backend/api/catalog.py:1124`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1125 _require(db, actor, 'catalog.manage')
```

### POST /catalog/variants/{variant_id}/barcodes/replace-primary — replace_variant_primary_barcode

Source: `wa_backend/api/catalog.py:1167`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1173 _require(db, actor, 'catalog.manage')
```

### POST /catalog/variants/{variant_id}/barcodes/package-independent — set_variant_package_barcode_independent

Source: `wa_backend/api/catalog.py:1266`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1272 _require(db, actor, 'catalog.manage')
```

### PATCH /catalog/barcodes/{barcode_id} — update_barcode

Source: `wa_backend/api/catalog.py:1352`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1353 _require(db, actor, 'catalog.manage')
```

### POST /catalog/gs1/parse — parse_gs1_endpoint

Source: `wa_backend/api/catalog.py:1390`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1391 _require(db, actor, 'catalog.read')
```

### POST /catalog/variants/{variant_id}/publish — publish_variant

Source: `wa_backend/api/catalog.py:1620`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /catalog/variants/{variant_id}/delete-draft-preflight — variant_delete_draft_preflight

Source: `wa_backend/api/catalog.py:1657`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1662 _require(db, actor, 'catalog.manage')
```

### POST /catalog/variants/{variant_id}/delete-draft — delete_draft_variant

Source: `wa_backend/api/catalog.py:1694`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1700 _require(db, actor, 'catalog.manage')
```

### POST /catalog/variants/{variant_id}/retire — retire_variant

Source: `wa_backend/api/catalog.py:1793`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /catalog/variants/{variant_id}/restore — restore_variant

Source: `wa_backend/api/catalog.py:1798`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /catalog/variants/{variant_id}/recall-readiness — variant_recall_readiness

Source: `wa_backend/api/catalog.py:1803`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1808 _require(db, actor, 'catalog.hold')
wa_backend/api/catalog.py:1828 inventory_access.allows('inventory.read', any_location=True)
wa_backend/api/catalog.py:1840 inventory_access.location_filter('inventory.read')
```

### GET /catalog/variants/{variant_id}/archive-preflight — variant_archive_preflight

Source: `wa_backend/api/catalog.py:1857`. Legacy path: `wa_backend/dispatch_access.py:19:route_filter`, `wa_backend/dispatch_access.py:7:vehicle_filter`, `wa_backend/domains/dispatch_archive_navigation.py:13:dispatch_archive_target_query`, `wa_backend/domains/operations_archive_navigation.py:11:operations_archive_target_query`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1858 _require(db, actor, 'catalog.archive')
wa_backend/dispatch_access.py:23 vehicle_filter(access, code, DispatchRoute.vehicle_id)
wa_backend/domains/dispatch_archive_navigation.py:26 route_filter(access, 'dispatch.execute')
wa_backend/domains/dispatch_archive_navigation.py:26 route_filter(access, 'dispatch.read')
wa_backend/domains/dispatch_archive_navigation.py:38 route_filter(access, 'dispatch.read')
wa_backend/domains/dispatch_archive_navigation.py:39 access.allows('transfer.cancel', header.source_location_id)
wa_backend/domains/inventory_archive_navigation.py:40 access.allows('location.read', anchor.id)
wa_backend/domains/inventory_archive_navigation.py:41 access.allows('inventory.read', anchor.id)
wa_backend/domains/inventory_archive_navigation.py:52 access.allows('inventory.read', location.id)
wa_backend/domains/inventory_archive_navigation.py:53 access.allows('catalog.read', any_location=True)
wa_backend/domains/inventory_archive_navigation.py:54 access.allows('location.read', location.id)
wa_backend/domains/inventory_archive_navigation.py:59 access.allows('transfer.read', header.source_location_id)
wa_backend/domains/inventory_archive_navigation.py:60 access.allows('location.read', header.source_location_id)
wa_backend/domains/inventory_archive_navigation.py:61 access.allows('transfer.cancel', header.source_location_id)
wa_backend/domains/inventory_archive_navigation.py:62 access.allows('transfer.read', header.destination_location_id)
wa_backend/domains/inventory_archive_navigation.py:63 access.allows('location.read', header.destination_location_id)
wa_backend/domains/inventory_archive_navigation.py:64 access.allows(('transfer.receive', 'transfer.reject'), header.destination_location_id)
wa_backend/domains/inventory_archive_navigation.py:65 access.allows('location.read', header.source_location_id)
wa_backend/domains/inventory_archive_navigation.py:65 access.allows('transfer.read', header.source_location_id)
wa_backend/domains/inventory_archive_navigation.py:77 access.allows('location.read', location.id)
wa_backend/domains/inventory_archive_navigation.py:77 access.allows('transfer.read', location.id)
wa_backend/domains/inventory_archive_navigation.py:102 access.allows('stocktake.read', anchor.id)
wa_backend/domains/inventory_archive_navigation.py:102 access.allows('stocktake.read', session.location_id)
wa_backend/domains/inventory_archive_navigation.py:103 access.allows('location.read', anchor.id)
wa_backend/domains/inventory_archive_navigation.py:104 access.allows('stocktake.count', session.location_id)
wa_backend/domains/inventory_archive_navigation.py:105 access.allows('stocktake.review', session.location_id)
wa_backend/domains/inventory_archive_navigation.py:127 access.allows('product_location.manage', location.id)
wa_backend/domains/inventory_archive_navigation.py:127 access.allows('product_location.read', location.id)
wa_backend/domains/inventory_archive_navigation.py:128 access.allows('catalog.read', any_location=True)
wa_backend/domains/inventory_archive_navigation.py:128 access.allows('location.read', location.id)
```

### POST /catalog/variants/{variant_id}/archive — archive_variant

Source: `wa_backend/api/catalog.py:1876`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /catalog/variants/{variant_id}/sales-hold — place_variant_sales_hold

Source: `wa_backend/api/catalog.py:1881`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /catalog/variants/{variant_id}/release-sales-hold — release_variant_sales_hold

Source: `wa_backend/api/catalog.py:1886`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /catalog/variants/{variant_id}/recall-preflight — recall_variant_preflight

Source: `wa_backend/api/catalog.py:1891`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/catalog.py:1896 _require(db, actor, 'catalog.hold')
```

### POST /catalog/variants/{variant_id}/recall — recall_variant

Source: `wa_backend/api/catalog.py:1922`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /catalog/variants/{variant_id}/cancel-recall — cancel_variant_recall

Source: `wa_backend/api/catalog.py:1927`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /catalog/variants/{variant_id}/close-recall — close_variant_recall

Source: `wa_backend/api/catalog.py:1932`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /commercial-policy/rounding — get_rounding_policy

Source: `wa_backend/api/commercial_policy.py:91`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/commercial_policy.py:95 _require(db, actor, 'pricing.view')
```

### POST /commercial-policy/rounding/publish — publish_rounding_policy

Source: `wa_backend/api/commercial_policy.py:112`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/commercial_policy.py:119 _require(db, actor, 'pricing.manage')
wa_backend/api/commercial_policy.py:120 _require(db, actor, 'pricing.approve')
```

### PUT /admin/sessions/{session_id}/authorize — authorize_session

Source: `wa_backend/api/dispatch.py:125`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:125:authorize_session`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /admin/sessions/today — get_admin_dashboard_data

Source: `wa_backend/api/dispatch.py:614`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:614:get_admin_dashboard_data`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /admin/sessions/{session_id}/settlement_report — get_session_settlement_report

Source: `wa_backend/api/dispatch.py:766`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:766:get_session_settlement_report`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### PUT /admin/sessions/{session_id}/settle — settle_session

Source: `wa_backend/api/dispatch.py:898`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:898:settle_session`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /dispatch/init — dispatch_init

Source: `wa_backend/api/dispatch.py:1058`. Legacy path: `wa_backend/api/dispatch.py:1058:dispatch_init`, `wa_backend/dispatch_access.py:7:vehicle_filter`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/dispatch.py:1063 access.require('dispatch.read', any_location=True)
wa_backend/api/dispatch.py:1073 vehicle_filter(access, 'dispatch.read', Vehicle.id)
wa_backend/api/dispatch.py:1076 vehicle_filter(access, 'dispatch.execute', Vehicle.id)
wa_backend/api/dispatch.py:1081 access.location_filter('dispatch.read')
wa_backend/api/dispatch.py:1087 access.location_filter('dispatch.execute')
```

### POST /dispatch/route — dispatch_route

Source: `wa_backend/api/dispatch.py:1369`. Legacy path: `wa_backend/api/dispatch.py:1369:dispatch_route`, `wa_backend/dispatch_access.py:26:require_vehicle`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/dispatch.py:1375 access.require('dispatch.execute', any_location=True)
wa_backend/api/dispatch.py:1376 require_vehicle(access, 'dispatch.execute', payload.vehicle_id)
wa_backend/api/dispatch.py:1460 access.require('dispatch.execute', int(source_location.id))
```

### GET /dispatch/inventory/{vehicle_id} — get_vehicle_inventory

Source: `wa_backend/api/dispatch.py:1829`. Legacy path: `wa_backend/dispatch_access.py:26:require_vehicle`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/dispatch.py:1835 require_vehicle(access, 'dispatch.read', vehicle_id)
```

### GET /dispatch/route/{route_id}/live_inventory — get_route_live_inventory

Source: `wa_backend/api/dispatch.py:1909`. Legacy path: `wa_backend/dispatch_access.py:26:require_vehicle`, `wa_backend/dispatch_access.py:38:require_route`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/dispatch.py:1915 require_route(access, 'dispatch.read', route_id)
wa_backend/dispatch_access.py:49 require_vehicle(access, code, row.vehicle_id)
```

### PUT /dispatch/route/{route_id}/adjust_inventory — adjust_route_inventory

Source: `wa_backend/api/dispatch.py:2468`. Legacy path: `wa_backend/dispatch_access.py:26:require_vehicle`, `wa_backend/dispatch_access.py:38:require_route`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/dispatch.py:2475 require_route(access, 'dispatch.execute', route_id)
wa_backend/dispatch_access.py:49 require_vehicle(access, code, row.vehicle_id)
```

### POST /dispatch/transfers/{transfer_id}/force_cancel — force_cancel_handshake

Source: `wa_backend/api/dispatch.py:2627`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/dispatch.py:2634 require_transfer(access, 'transfer.cancel', transfer_id, 'source')
```

### GET /dispatch/route/{route_id}/transfers — get_route_transfers

Source: `wa_backend/api/dispatch.py:2745`. Legacy path: `wa_backend/dispatch_access.py:26:require_vehicle`, `wa_backend/dispatch_access.py:38:require_route`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/dispatch.py:2751 require_route(access, 'dispatch.read', route_id)
wa_backend/api/dispatch.py:2779 access.allows('transfer.cancel', InventoryTransferHeader.source_location_id)
wa_backend/dispatch_access.py:49 require_vehicle(access, code, row.vehicle_id)
```

### GET /dispatch/shops — get_dispatch_shops

Source: `wa_backend/api/dispatch.py:2902`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/dispatch.py:2910 access.require('dispatch.read', any_location=True)
```

### PUT /dispatch/shops/bulk_update — bulk_update_shops

Source: `wa_backend/api/dispatch.py:3070`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:3070:bulk_update_shops`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /dispatch/shops — admin_add_shop

Source: `wa_backend/api/dispatch.py:3231`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:3231:admin_add_shop`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /dispatch/active_routes — get_active_routes

Source: `wa_backend/api/dispatch.py:3393`. Legacy path: `wa_backend/dispatch_access.py:19:route_filter`, `wa_backend/dispatch_access.py:7:vehicle_filter`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/dispatch.py:3401 access.require('dispatch.read', any_location=True)
wa_backend/api/dispatch.py:3406 route_filter(access, 'dispatch.execute')
wa_backend/api/dispatch.py:3418 route_filter(access, 'dispatch.read')
wa_backend/dispatch_access.py:23 vehicle_filter(access, code, DispatchRoute.vehicle_id)
```

### PUT /dispatch/route/{route_id}/status — update_route_status

Source: `wa_backend/api/dispatch.py:3536`. Legacy path: `wa_backend/api/dispatch.py:3536:update_route_status`, `wa_backend/dispatch_access.py:26:require_vehicle`, `wa_backend/dispatch_access.py:38:require_route`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/dispatch.py:3543 require_route(access, 'dispatch.execute', route_id)
wa_backend/api/dispatch.py:3584 require_vehicle(access, 'dispatch.execute', requested_vehicle_id)
wa_backend/dispatch_access.py:49 require_vehicle(access, code, row.vehicle_id)
```

### PUT /dispatch/session/{session_id}/undo_end_work — undo_end_work

Source: `wa_backend/api/dispatch.py:4265`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:4265:undo_end_work`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /dispatch/zones — add_zone

Source: `wa_backend/api/dispatch.py:4404`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:4404:add_zone`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### DELETE /dispatch/zones/{zone_id} — archive_zone

Source: `wa_backend/api/dispatch.py:4464`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:4464:archive_zone`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### PUT /dispatch/zones/{zone_id} — update_zone

Source: `wa_backend/api/dispatch.py:4528`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:4528:update_zone`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /dispatch/zones/archived — get_archived_zones

Source: `wa_backend/api/dispatch.py:4590`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:4590:get_archived_zones`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### PUT /dispatch/zones/{zone_id}/restore — restore_zone

Source: `wa_backend/api/dispatch.py:4610`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:4610:restore_zone`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### PUT /dispatch/shops/{shop_id} — edit_shop_details

Source: `wa_backend/api/dispatch.py:4668`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:4668:edit_shop_details`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /dispatch/shortages — get_shortages

Source: `wa_backend/api/dispatch.py:4846`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:4846:get_shortages`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /dispatch/shortages — add_shortages

Source: `wa_backend/api/dispatch.py:4892`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:4892:add_shortages`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### DELETE /dispatch/shortages/{shortage_id} — delete_shortage

Source: `wa_backend/api/dispatch.py:5133`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:5133:delete_shortage`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /dispatch/shops/bulk_import — bulk_import_shops

Source: `wa_backend/api/dispatch.py:5228`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/dispatch.py:5228:bulk_import_shops`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /visits/{visit_id} — get_visit_details

Source: `wa_backend/api/driver.py:3728`. Legacy path: `wa_backend/api/driver.py:3728:get_visit_details`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /inventory/access/me — capabilities

Source: `wa_backend/api/inventory_permissions.py:37`. Legacy path: `wa_backend/api/inventory_permissions.py:37:capabilities`, `wa_backend/inventory_access.py:123:codes`, `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /inventory/access/locations/capabilities — location_capabilities

Source: `wa_backend/api/inventory_permissions.py:56`. Legacy path: `wa_backend/inventory_access.py:123:codes`, `wa_backend/inventory_access.py:145:codes_by_location`, `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /inventory/access/catalog — permission_catalog

Source: `wa_backend/api/inventory_permissions.py:66`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/inventory_permissions.py:66:permission_catalog`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /inventory/access/roles — roles

Source: `wa_backend/api/inventory_permissions.py:71`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/inventory_permissions.py:71:roles`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /inventory/access/roles — create_role

Source: `wa_backend/api/inventory_permissions.py:134`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/inventory_permissions.py:134:create_role`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### PUT /inventory/access/roles/{role_id} — update_role

Source: `wa_backend/api/inventory_permissions.py:140`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/inventory_permissions.py:140:update_role`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /inventory/access/users — users

Source: `wa_backend/api/inventory_permissions.py:146`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/inventory_permissions.py:146:users`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /inventory/access/locations — locations

Source: `wa_backend/api/inventory_permissions.py:155`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/inventory_permissions.py:155:locations`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /inventory/access/users/{user_id}/grants — user_grants

Source: `wa_backend/api/inventory_permissions.py:171`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/inventory_permissions.py:171:user_grants`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /inventory/access/users/{user_id}/grants — grant

Source: `wa_backend/api/inventory_permissions.py:183`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/inventory_permissions.py:183:grant`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### DELETE /inventory/access/users/{user_id}/grants/{grant_id} — revoke

Source: `wa_backend/api/inventory_permissions.py:206`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/inventory_permissions.py:206:revoke`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /warehouse/inventory/minimum-stock/bulk/preview — preview_bulk_minimum_stock

Source: `wa_backend/api/inventory_stock_policy.py:500`. Legacy path: `wa_backend/api/inventory_stock_policy.py:236:_require_bulk_admin`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/inventory_stock_policy.py:253 access.require('inventory.read', int(location_id))
```

### PUT /warehouse/inventory/minimum-stock/bulk — apply_bulk_minimum_stock

Source: `wa_backend/api/inventory_stock_policy.py:531`. Legacy path: `wa_backend/api/inventory_stock_policy.py:236:_require_bulk_admin`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/inventory_stock_policy.py:253 access.require('inventory.read', int(location_id))
```

### PUT /warehouse/inventory/{product_variant_id}/minimum-stock — update_minimum_stock

Source: `wa_backend/api/inventory_stock_policy.py:661`. Legacy path: `wa_backend/api/inventory_stock_policy.py:661:update_minimum_stock`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/inventory_stock_policy.py:691 access.require('inventory.read', int(payload.location_id))
```

### GET /offers/policy — get_policy

Source: `wa_backend/api/offers.py:423`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:427 _require(db, actor, 'offers.view')
```

### GET /offers/references/variants — list_reference_variants

Source: `wa_backend/api/offers.py:436`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:442 _require(db, actor, 'catalog.read')
```

### POST /offers/references/variants/resolve — resolve_reference_variants

Source: `wa_backend/api/offers.py:467`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:472 _require(db, actor, 'catalog.read')
```

### GET /offers/definitions — list_definitions

Source: `wa_backend/api/offers.py:506`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:512 _require(db, actor, 'offers.view')
```

### POST /offers/definitions — add_definition

Source: `wa_backend/api/offers.py:535`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:540 _require(db, actor, 'offers.manage')
```

### PATCH /offers/definitions/{definition_id} — edit_definition

Source: `wa_backend/api/offers.py:566`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:572 _require(db, actor, 'offers.manage')
```

### DELETE /offers/definitions/{definition_id} — remove_definition

Source: `wa_backend/api/offers.py:600`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:606 _require(db, actor, 'offers.manage')
```

### GET /offers/definitions/{definition_id}/versions — list_versions

Source: `wa_backend/api/offers.py:630`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:637 _require(db, actor, 'offers.view')
```

### GET /offers/versions/{version_id} — get_version

Source: `wa_backend/api/offers.py:676`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:681 _require(db, actor, 'offers.view')
```

### POST /offers/definitions/{definition_id}/versions — add_version

Source: `wa_backend/api/offers.py:701`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:707 _require(db, actor, 'offers.manage')
```

### PUT /offers/versions/{version_id} — edit_version

Source: `wa_backend/api/offers.py:742`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:748 _require(db, actor, 'offers.manage')
```

### DELETE /offers/versions/{version_id} — remove_version

Source: `wa_backend/api/offers.py:781`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:787 _require(db, actor, 'offers.manage')
```

### POST /offers/preview — preview_basket

Source: `wa_backend/api/offers.py:811`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:816 _require(db, actor, 'offers.view')
```

### POST /offers/versions/{version_id}/validate — validate_offer_version

Source: `wa_backend/api/offers.py:830`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/offers.py:835 _require(db, actor, 'offers.view')
```

### POST /offers/versions/{version_id}/submit — submit

Source: `wa_backend/api/offers.py:885`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /offers/versions/{version_id}/publish — publish

Source: `wa_backend/api/offers.py:904`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /offers/versions/{version_id}/approve — approve

Source: `wa_backend/api/offers.py:923`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /offers/versions/{version_id}/cancel — cancel

Source: `wa_backend/api/offers.py:942`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /platform/companies — create_new_tenant

Source: `wa_backend/api/platform_manager.py:176`. Legacy path: `wa_backend/api/platform_manager.py:176:create_new_tenant`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /pricing/policy — get_pricing_policy

Source: `wa_backend/api/pricing.py:311`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:315 _require(db, actor, 'pricing.view')
```

### GET /pricing/books — list_books

Source: `wa_backend/api/pricing.py:324`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:330 _require(db, actor, 'pricing.view')
```

### POST /pricing/books — add_book

Source: `wa_backend/api/pricing.py:355`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:360 _require(db, actor, 'pricing.manage')
```

### GET /pricing/books/{book_id}/publications — list_publications

Source: `wa_backend/api/pricing.py:413`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:420 _require(db, actor, 'pricing.view')
```

### POST /pricing/books/{book_id}/publications — add_publication

Source: `wa_backend/api/pricing.py:460`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:466 _require(db, actor, 'pricing.manage')
```

### GET /pricing/publications/{publication_id}/entries — list_entries

Source: `wa_backend/api/pricing.py:517`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:524 _require(db, actor, 'pricing.view')
```

### POST /pricing/publications/{publication_id}/entries — add_entry

Source: `wa_backend/api/pricing.py:564`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:570 _require(db, actor, 'pricing.manage')
```

### PATCH /pricing/entries/{entry_id} — edit_entry

Source: `wa_backend/api/pricing.py:621`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:627 _require(db, actor, 'pricing.manage')
```

### DELETE /pricing/entries/{entry_id} — remove_entry

Source: `wa_backend/api/pricing.py:675`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:681 _require(db, actor, 'pricing.manage')
```

### POST /pricing/publications/{publication_id}/submit — submit

Source: `wa_backend/api/pricing.py:794`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /pricing/publications/{publication_id}/approve — approve

Source: `wa_backend/api/pricing.py:813`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /pricing/publications/{publication_id}/publish — publish

Source: `wa_backend/api/pricing.py:832`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /pricing/publications/{publication_id}/cancel — cancel

Source: `wa_backend/api/pricing.py:851`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:857 _require(db, actor, 'pricing.manage')
```

### GET /pricing/assignments — list_assignments

Source: `wa_backend/api/pricing.py:905`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:911 _require(db, actor, 'pricing.view')
```

### POST /pricing/assignments — add_assignment

Source: `wa_backend/api/pricing.py:936`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:941 _require(db, actor, 'pricing.manage')
```

### POST /pricing/resolve-preview — resolve_preview

Source: `wa_backend/api/pricing.py:995`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/pricing.py:1000 _require(db, actor, 'pricing.view')
```

### GET /warehouse/product-locations — list_product_locations

Source: `wa_backend/api/product_locations.py:130`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/product_locations.py:140 access.require('product_location.read', location_id)
wa_backend/api/product_locations.py:142 access.require('product_location.read', any_location=True)
wa_backend/api/product_locations.py:158 access.location_filter('product_location.read', ProductLocation.location_id)
```

### POST /warehouse/product-locations — create_product_location

Source: `wa_backend/api/product_locations.py:175`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/product_locations.py:181 access.require('product_location.manage', payload.location_id)
```

### PATCH /warehouse/product-locations/{product_location_id} — update_product_location

Source: `wa_backend/api/product_locations.py:248`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/product_locations.py:261 InventoryAccess(db, actor).require('product_location.manage', scope.location_id)
```

### DELETE /warehouse/product-locations/{product_location_id} — delete_product_location

Source: `wa_backend/api/product_locations.py:307`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/product_locations.py:314 access.require('product_location.manage', any_location=True)
wa_backend/api/product_locations.py:339 access.require('product_location.manage', replay_location_id)
wa_backend/api/product_locations.py:381 access.require('product_location.manage', location_id)
```

### GET /simple-products/tracking/defaults — get_product_tracking_defaults

Source: `wa_backend/api/product_tracking.py:153`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/product_tracking.py:157 _require(db, actor, 'catalog.read')
```

### PUT /simple-products/tracking/defaults — update_product_tracking_defaults

Source: `wa_backend/api/product_tracking.py:175`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/product_tracking.py:180 _require(db, actor, 'catalog.manage')
```

### PATCH /simple-products/tracking/variants/{variant_id} — update_variant_product_tracking

Source: `wa_backend/api/product_tracking.py:255`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/product_tracking.py:261 _require(db, actor, 'catalog.manage')
```

### POST /driver/session/{session_id}/reconcile — reconcile_driver_end_of_day

Source: `wa_backend/api/reconciliation.py:74`. Legacy path: `wa_backend/services.py:4365:open_vehicle_reconciliation_stocktake`, `wa_backend/services.py:4570:finalize_vehicle_inventory_reconciliation`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /sales-returns — list_returns

Source: `wa_backend/api/sales_returns.py:33`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/sales_returns.py:33:list_returns`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /sales-returns/sources — returnable_sales

Source: `wa_backend/api/sales_returns.py:51`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/sales_returns.py:51:returnable_sales`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /sales-returns/source/{visit_id} — return_source

Source: `wa_backend/api/sales_returns.py:75`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/sales_returns.py:75:return_source`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /sales-returns/{return_id} — return_detail

Source: `wa_backend/api/sales_returns.py:91`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/sales_returns.py:91:return_detail`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /sales-returns — post_return

Source: `wa_backend/api/sales_returns.py:107`. Legacy path: `wa_backend/api/dependencies.py:126:get_current_admin`, `wa_backend/api/sales_returns.py:107:post_return`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /simple-products/package-uoms — package_uoms

Source: `wa_backend/api/simple_products.py:1106`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/simple_products.py:1110 _require(db, actor, 'catalog.read')
```

### GET /simple-products/families — families

Source: `wa_backend/api/simple_products.py:1124`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/simple_products.py:1141 _require(db, actor, 'catalog.read')
```

### POST /simple-products/families — create_product_family

Source: `wa_backend/api/simple_products.py:1196`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/simple_products.py:1201 _require(db, actor, 'catalog.manage')
```

### PATCH /simple-products/families/{family_id} — update_product_family

Source: `wa_backend/api/simple_products.py:1263`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/simple_products.py:1269 _require(db, actor, 'catalog.manage')
```

### DELETE /simple-products/families/{family_id} — delete_product_family

Source: `wa_backend/api/simple_products.py:1333`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/simple_products.py:1339 _require(db, actor, 'catalog.manage')
```

### GET /simple-products/summary — catalog_summary

Source: `wa_backend/api/simple_products.py:1411`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/simple_products.py:1415 _require(db, actor, 'catalog.read')
```

### GET /simple-products — list_simple_products

Source: `wa_backend/api/simple_products.py:1420`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/simple_products.py:1449 _require(db, actor, 'catalog.read')
wa_backend/api/simple_products.py:1505 access.allows('pricing.view', any_location=True)
wa_backend/domains/inventory_catalog_presence.py:44 access.location_filter('inventory.read', InventoryLocation.id)
wa_backend/domains/inventory_catalog_presence.py:71 access.location_filter('inventory.read', InventoryLocation.id)
```

### POST /simple-products — create_simple_product

Source: `wa_backend/api/simple_products.py:2055`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### PATCH /simple-products/{variant_id}/price — update_simple_product_price

Source: `wa_backend/api/simple_products.py:2157`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/simple_products.py:2163 _require(db, actor, 'pricing.manage')
```

### GET /suppliers — suppliers

Source: `wa_backend/api/suppliers.py:28`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /suppliers/{supplier_id} — supplier

Source: `wa_backend/api/suppliers.py:38`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /suppliers — create_supplier

Source: `wa_backend/api/suppliers.py:45`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/domains/suppliers/application.py:15 require_supplier_permission(db, actor, 'supplier.manage')
```

### PUT /suppliers/{supplier_id} — update_supplier

Source: `wa_backend/api/suppliers.py:51`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/domains/suppliers/application.py:15 require_supplier_permission(db, actor, 'supplier.manage')
```

### PATCH /suppliers/{supplier_id}/state — supplier_state

Source: `wa_backend/api/suppliers.py:57`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/domains/suppliers/application.py:15 require_supplier_permission(db, actor, 'supplier.manage')
```

### GET /taxation/policy — get_policy

Source: `wa_backend/api/taxation.py:313`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:317 _require(db, actor, 'tax.view')
```

### POST /taxation/preview — preview_tax

Source: `wa_backend/api/taxation.py:326`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:331 _require(db, actor, 'tax.view')
```

### GET /taxation/jurisdictions — list_jurisdictions

Source: `wa_backend/api/taxation.py:343`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:349 _require(db, actor, 'tax.view')
```

### POST /taxation/jurisdictions — add_jurisdiction

Source: `wa_backend/api/taxation.py:372`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:377 _require(db, actor, 'tax.manage')
```

### PATCH /taxation/jurisdictions/{jurisdiction_id} — edit_jurisdiction

Source: `wa_backend/api/taxation.py:402`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:408 _require(db, actor, 'tax.manage')
```

### DELETE /taxation/jurisdictions/{jurisdiction_id} — remove_jurisdiction

Source: `wa_backend/api/taxation.py:434`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:440 _require(db, actor, 'tax.manage')
```

### GET /taxation/rule-sets — list_rule_sets

Source: `wa_backend/api/taxation.py:461`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:467 _require(db, actor, 'tax.view')
```

### POST /taxation/rule-sets — add_rule_set

Source: `wa_backend/api/taxation.py:490`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:495 _require(db, actor, 'tax.manage')
```

### PATCH /taxation/rule-sets/{rule_set_id} — edit_rule_set

Source: `wa_backend/api/taxation.py:516`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:522 _require(db, actor, 'tax.manage')
```

### DELETE /taxation/rule-sets/{rule_set_id} — remove_rule_set

Source: `wa_backend/api/taxation.py:548`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:554 _require(db, actor, 'tax.manage')
```

### GET /taxation/rule-sets/{rule_set_id}/versions — list_versions

Source: `wa_backend/api/taxation.py:575`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:582 _require(db, actor, 'tax.view')
```

### GET /taxation/versions/{version_id} — get_version

Source: `wa_backend/api/taxation.py:621`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:626 _require(db, actor, 'tax.view')
```

### POST /taxation/rule-sets/{rule_set_id}/versions — add_version

Source: `wa_backend/api/taxation.py:646`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:652 _require(db, actor, 'tax.manage')
```

### PUT /taxation/versions/{version_id} — edit_version

Source: `wa_backend/api/taxation.py:681`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:687 _require(db, actor, 'tax.manage')
```

### DELETE /taxation/versions/{version_id} — remove_version

Source: `wa_backend/api/taxation.py:714`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:720 _require(db, actor, 'tax.manage')
```

### POST /taxation/versions/{version_id}/validate — validate_tax_version

Source: `wa_backend/api/taxation.py:741`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/taxation.py:746 _require(db, actor, 'tax.view')
```

### POST /taxation/versions/{version_id}/submit — submit_tax_version

Source: `wa_backend/api/taxation.py:825`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /taxation/versions/{version_id}/publish — publish_tax_version

Source: `wa_backend/api/taxation.py:837`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /taxation/versions/{version_id}/approve — approve_tax_version

Source: `wa_backend/api/taxation.py:849`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /taxation/versions/{version_id}/cancel — cancel_tax_version_endpoint

Source: `wa_backend/api/taxation.py:861`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /warehouse/inbound/options — warehouse_inbound_options

Source: `wa_backend/api/warehouse/inbound.py:287`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/inbound.py:293 access.require('inbound.create', any_location=True)
```

### GET /warehouse/costing-policy — warehouse_costing_policy

Source: `wa_backend/api/warehouse/inbound.py:344`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/inbound.py:349 access.require('inbound.create', any_location=True)
wa_backend/api/warehouse/inbound.py:351 access.allows('inventory.costing.manage')
```

### PUT /warehouse/costing-policy — update_warehouse_costing_policy

Source: `wa_backend/api/warehouse/inbound.py:370`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/inbound.py:376 access.require('inventory.costing.manage')
```

### POST /warehouse/inbound — warehouse_inbound

Source: `wa_backend/api/warehouse/inbound.py:422`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/inbound.py:428 access.require('inbound.create', any_location=True)
wa_backend/api/warehouse/inbound.py:432 access.require('inbound.create', payload.location_id)
```

### POST /warehouse/ledger/{entry_id}/adjust — adjust_warehouse_entry

Source: `wa_backend/api/warehouse/inbound_adjustments.py:40`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/inbound_adjustments.py:47 require_inbound_adjustment(access, entry_id)
```

### GET /warehouse/ledger/cursor — get_warehouse_ledger_cursor

Source: `wa_backend/api/warehouse/ledger.py:301`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/ledger.py:312 access.require('ledger.read', location_id, any_location=location_id is None)
wa_backend/api/warehouse/ledger.py:365 access.allows('ledger.read', InventoryMovement.source_location_id)
wa_backend/api/warehouse/ledger.py:366 access.allows('ledger.read', InventoryMovement.destination_location_id)
wa_backend/api/warehouse/ledger.py:448 access.allows('ledger.read', InventoryMovement.source_location_id)
wa_backend/api/warehouse/ledger.py:449 access.allows('ledger.read', InventoryMovement.destination_location_id)
wa_backend/api/warehouse/ledger.py:574 access.allows('ledger.read', InventoryBalance.location_id)
```

### GET /warehouse/inventory/alerts/summary — get_warehouse_inventory_alert_summary

Source: `wa_backend/api/warehouse/live_stock.py:713`. Legacy path: `wa_backend/api/warehouse/live_stock.py:216:_require_live_stock_warehouse_read`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/live_stock.py:250 access.allows('inventory.read', location_id)
wa_backend/api/warehouse/live_stock.py:254 access.allows('inventory.read')
```

### GET /warehouse/inventory/summary — get_warehouse_inventory_summary

Source: `wa_backend/api/warehouse/live_stock.py:738`. Legacy path: `wa_backend/api/warehouse/live_stock.py:216:_require_live_stock_warehouse_read`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/live_stock.py:189 access.location_filter('inventory.read')
wa_backend/api/warehouse/live_stock.py:250 access.allows('inventory.read', location_id)
wa_backend/api/warehouse/live_stock.py:254 access.allows('inventory.read')
```

### GET /warehouse/inventory/families — get_warehouse_inventory_families

Source: `wa_backend/api/warehouse/live_stock.py:856`. Legacy path: `wa_backend/api/warehouse/live_stock.py:216:_require_live_stock_warehouse_read`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/live_stock.py:250 access.allows('inventory.read', location_id)
wa_backend/api/warehouse/live_stock.py:254 access.allows('inventory.read')
```

### GET /warehouse/inventory/batch-products — get_warehouse_inventory_batch_products

Source: `wa_backend/api/warehouse/live_stock.py:929`. Legacy path: `wa_backend/api/warehouse/live_stock.py:216:_require_live_stock_warehouse_read`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/live_stock.py:250 access.allows('inventory.read', location_id)
wa_backend/api/warehouse/live_stock.py:254 access.allows('inventory.read')
```

### GET /warehouse/inventory/cursor — get_warehouse_inventory

Source: `wa_backend/api/warehouse/live_stock.py:1151`. Legacy path: `wa_backend/api/warehouse/live_stock.py:216:_require_live_stock_warehouse_read`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/live_stock.py:189 access.location_filter('inventory.read')
wa_backend/api/warehouse/live_stock.py:250 access.allows('inventory.read', location_id)
wa_backend/api/warehouse/live_stock.py:254 access.allows('inventory.read')
```

### GET /warehouse/inventory/{product_variant_id}/batches — get_warehouse_inventory_batches

Source: `wa_backend/api/warehouse/live_stock.py:1798`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/live_stock.py:1835 access.allows('inventory.read', location_id)
```

### GET /warehouse/variants/{product_variant_id}/quality-batch-candidates — get_quality_batch_candidates

Source: `wa_backend/api/warehouse/live_stock.py:2439`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/live_stock.py:2450 access.require('inventory.read', any_location=True)
wa_backend/api/warehouse/live_stock.py:2455 access.location_filter('inventory.read', InventoryLocation.id)
```

### GET /warehouse/variants/{product_variant_id}/quality-issue-sources — get_whole_product_quality_issue_sources

Source: `wa_backend/api/warehouse/live_stock.py:2477`. Legacy path: `wa_backend/dispatch_access.py:19:route_filter`, `wa_backend/dispatch_access.py:7:vehicle_filter`, `wa_backend/inventory_access.py:123:codes`, `wa_backend/inventory_access.py:145:codes_by_location`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/live_stock.py:2495 access.require('inventory.read', any_location=True)
wa_backend/api/warehouse/live_stock.py:2542 access.location_filter('inventory.read', InventoryLocation.id)
wa_backend/api/warehouse/live_stock.py:2563 access.location_filter('inventory.read', InventoryLocation.id)
wa_backend/api/warehouse/live_stock.py:2582 access.location_filter('inventory.read', InventoryLocation.id)
wa_backend/api/warehouse/live_stock.py:2617 access.allows('transfer.send', InventoryLocation.id)
wa_backend/api/warehouse/live_stock.py:2639 access.allows('inventory.disposal.confirm', InventoryLocation.id)
wa_backend/api/warehouse/live_stock.py:2642 access.allows('inventory.vendor_return.confirm', InventoryLocation.id)
wa_backend/api/warehouse/live_stock.py:2695 access.location_filter('inventory.read', InventoryLocation.id)
wa_backend/dispatch_access.py:23 vehicle_filter(access, code, DispatchRoute.vehicle_id)
wa_backend/domains/dispatch_reservations.py:125 access.allows('transfer.cancel', h.source_location_id)
wa_backend/domains/dispatch_reservations.py:143 access.location_filter('inventory.read', h.source_location_id)
wa_backend/domains/dispatch_reservations.py:144 route_filter(access, 'dispatch.read')
```

### GET /warehouse/batches/{batch_id}/stock-sources — get_batch_stock_sources

Source: `wa_backend/api/warehouse/live_stock.py:2857`. Legacy path: `wa_backend/dispatch_access.py:19:route_filter`, `wa_backend/dispatch_access.py:7:vehicle_filter`, `wa_backend/inventory_access.py:123:codes`, `wa_backend/inventory_access.py:145:codes_by_location`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/live_stock.py:2873 access.require('inventory.read', any_location=True)
wa_backend/api/warehouse/live_stock.py:2927 access.location_filter('inventory.read', InventoryLocation.id)
wa_backend/api/warehouse/live_stock.py:2941 access.allows('inventory.read')
wa_backend/api/warehouse/live_stock.py:2959 access.allows('transfer.send', InventoryLocation.id)
wa_backend/api/warehouse/live_stock.py:2971 access.allows('inventory.disposal.confirm', InventoryLocation.id)
wa_backend/api/warehouse/live_stock.py:2974 access.allows('inventory.vendor_return.confirm', InventoryLocation.id)
wa_backend/api/warehouse/live_stock.py:3018 access.location_filter('inventory.read', InventoryLocation.id)
wa_backend/dispatch_access.py:23 vehicle_filter(access, code, DispatchRoute.vehicle_id)
wa_backend/domains/dispatch_reservations.py:53 access.allows('transfer.cancel', h.source_location_id)
wa_backend/domains/dispatch_reservations.py:70 access.location_filter('inventory.read', h.source_location_id)
wa_backend/domains/dispatch_reservations.py:71 route_filter(access, 'dispatch.read')
```

### GET /warehouse/setup-status — get_warehouse_setup_status

Source: `wa_backend/api/warehouse/locations.py:230`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/locations.py:235 access.require('location.read', any_location=True)
wa_backend/api/warehouse/locations.py:249 access.location_filter('location.read')
wa_backend/api/warehouse/locations.py:252 access.allows('location.create')
```

### GET /warehouse/locations — manage_warehouse_locations

Source: `wa_backend/api/warehouse/locations.py:274`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/locations.py:283 access.require('location.read', any_location=True)
wa_backend/api/warehouse/locations.py:307 access.location_filter('location.read')
```

### GET /warehouse/locations/manage — manage_warehouse_locations

Source: `wa_backend/api/warehouse/locations.py:274`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/locations.py:283 access.require('location.read', any_location=True)
wa_backend/api/warehouse/locations.py:307 access.location_filter('location.read')
```

### POST /warehouse/locations — create_warehouse_location

Source: `wa_backend/api/warehouse/locations.py:381`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/locations.py:387 access.require('location.create')
```

### PATCH /warehouse/locations/{location_id} — update_warehouse_location

Source: `wa_backend/api/warehouse/locations.py:519`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/locations.py:526 access.require('location.update', location_id)
```

### POST /warehouse/locations/{location_id}/activate — activate_warehouse_location

Source: `wa_backend/api/warehouse/locations.py:668`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/locations.py:675 access.require('location.state', location_id)
```

### POST /warehouse/locations/{location_id}/deactivate — deactivate_warehouse_location

Source: `wa_backend/api/warehouse/locations.py:789`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/locations.py:796 access.require('location.state', location_id)
```

### GET /warehouse/status — get_warehouse_status

Source: `wa_backend/api/warehouse/status.py:20`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/status.py:26 access.require(('location.read', 'dispatch.read'), location_id)
```

### GET /warehouse/unified/stocktake/cycle-batches — list_stocktake_cycle_batches

Source: `wa_backend/api/warehouse/stocktake.py:439`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/stocktake.py:449 access.require('stocktake.start', location_id)
```

### GET /warehouse/unified/stocktake/vehicle-recon-candidates — list_vehicle_recon_candidates

Source: `wa_backend/api/warehouse/stocktake.py:655`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/stocktake.py:680 access.require('location.read', source_location_id)
wa_backend/api/warehouse/stocktake.py:681 access.require('stocktake.start', any_location=True)
wa_backend/api/warehouse/stocktake.py:722 access.location_filter('stocktake.start')
```

### GET /warehouse/unified/stocktakes/active — list_active_stocktake_sessions

Source: `wa_backend/api/warehouse/stocktake.py:1013`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/stocktake.py:1021 access.require('stocktake.read', location_id)
```

### GET /warehouse/unified/stocktake/{session_id}/context — get_stocktake_session_context

Source: `wa_backend/api/warehouse/stocktake.py:1183`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/stocktake.py:1195 access.require('location.read', anchor_location_id)
wa_backend/api/warehouse/stocktake.py:1196 require_stocktake(access, 'stocktake.read', session_id)
```

### POST /warehouse/unified/stocktake/start — start_unified_stocktake

Source: `wa_backend/api/warehouse/stocktake.py:1376`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/stocktake.py:1383 access.require('stocktake.start', payload.location_id)
```

### GET /warehouse/unified/stocktake/{session_id}/count-sheet — get_stocktake_count_sheet

Source: `wa_backend/api/warehouse/stocktake.py:1624`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/stocktake.py:1630 require_stocktake(access, 'stocktake.count', session_id)
```

### POST /warehouse/unified/stocktake/{session_id}/count — submit_stocktake_count

Source: `wa_backend/api/warehouse/stocktake.py:1712`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/stocktake.py:1720 require_stocktake(access, 'stocktake.count', session_id)
```

### GET /warehouse/unified/stocktake/{session_id}/review — get_stocktake_review

Source: `wa_backend/api/warehouse/stocktake.py:2029`. Legacy path: `wa_backend/api/warehouse/stocktake.py:2029:get_stocktake_review`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/stocktake.py:2035 require_stocktake(access, 'stocktake.review', session_id)
```

### POST /warehouse/unified/stocktake/{session_id}/approve — approve_stocktake_session

Source: `wa_backend/api/warehouse/stocktake.py:2209`. Legacy path: `wa_backend/inventory_access.py:84:allows`, `wa_backend/services.py:4570:finalize_vehicle_inventory_reconciliation`, `wa_backend/services.py:4762:post_approved_stocktake_adjustments`.

```text
wa_backend/api/warehouse/stocktake.py:2217 require_stocktake(access, 'stocktake.approve', session_id)
```

### POST /warehouse/unified/stocktake/{session_id}/recount — recount_stocktake_session

Source: `wa_backend/api/warehouse/stocktake.py:2318`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/stocktake.py:155 InventoryAccess(db, admin).require('stocktake.recount', location_id)
wa_backend/api/warehouse/stocktake.py:2326 require_stocktake(access, 'stocktake.recount', session_id)
```

### POST /warehouse/unified/stocktake/{session_id}/cancel — cancel_stocktake_session

Source: `wa_backend/api/warehouse/stocktake.py:2418`. Legacy path: `wa_backend/api/warehouse/stocktake.py:2418:cancel_stocktake_session`, `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/stocktake.py:2426 require_stocktake(access, 'stocktake.cancel', session_id)
```

### GET /warehouse/operational-policy/transfer-destinations — get_transfer_destination_policy

Source: `wa_backend/api/warehouse/transfer_policy.py:115`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfer_policy.py:120 access.require('inventory.transfer_policy.manage', any_location=True)
```

### PUT /warehouse/operational-policy/transfer-destinations/draft — save_transfer_destination_policy

Source: `wa_backend/api/warehouse/transfer_policy.py:149`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfer_policy.py:101 access.require('location.read', location_id)
wa_backend/api/warehouse/transfer_policy.py:155 access.require('inventory.transfer_policy.manage', any_location=True)
```

### POST /warehouse/operational-policy/transfer-destinations/{policy_id}/publish — publish_transfer_destination_policy_endpoint

Source: `wa_backend/api/warehouse/transfer_policy.py:235`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfer_policy.py:101 access.require('location.read', location_id)
wa_backend/api/warehouse/transfer_policy.py:242 access.require('inventory.transfer_policy.manage', any_location=True)
```

### POST /warehouse/batches/{batch_id}/disposition — change_batch_disposition

Source: `wa_backend/api/warehouse/transfers.py:228`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:235 access.require('batch.disposition')
```

### POST /warehouse/inventory/status-change — change_inventory_status

Source: `wa_backend/api/warehouse/transfers.py:334`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:340 access.require('inventory.status_change', payload.location_id)
```

### GET /warehouse/unified/transfer/locations — list_unified_transfer_locations

Source: `wa_backend/api/warehouse/transfers.py:469`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:481 access.require(('transfer.read', 'transfer.send', 'transfer.destination'), any_location=True)
wa_backend/api/warehouse/transfers.py:496 access.location_filter('transfer.send' if purpose == 'source' else 'transfer.destination' if purpose == 'destination' else ('transfer.read', 'transfer.send', 'transfer.destination'))
```

### GET /warehouse/unified/transfer/source-inventory — get_unified_transfer_source_inventory

Source: `wa_backend/api/warehouse/transfers.py:558`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:567 access.require('transfer.send', location_id)
```

### GET /warehouse/unified/transfer/override-options — get_unified_transfer_override_options

Source: `wa_backend/api/warehouse/transfers.py:809`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:816 access.require('inventory.fefo_override', location_id)
```

### GET /warehouse/unified/transfers — list_unified_transfers

Source: `wa_backend/api/warehouse/transfers.py:1181`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:1192 access.require('transfer.read', location_id, any_location=location_id is None)
```

### GET /warehouse/unified/transfers/{header_id} — get_unified_transfer_detail

Source: `wa_backend/api/warehouse/transfers.py:1338`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:1344 require_transfer(access, 'transfer.read', header_id)
```

### POST /warehouse/unified/transfer/special/dispatch — special_transfer_dispatch

Source: `wa_backend/api/warehouse/transfers.py:1449`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:1469 access.require('transfer.send', payload.source_location_id)
wa_backend/api/warehouse/transfers.py:1513 access.require('transfer.destination', destination_location_id)
```

### POST /warehouse/quality/stage — stage_inventory_quality_handling

Source: `wa_backend/api/warehouse/transfers.py:1714`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:1733 access.require('transfer.send', payload.source_location_id)
wa_backend/api/warehouse/transfers.py:1760 access.require('transfer.destination', destination_location_id)
```

### POST /warehouse/quality/disposal/confirm — confirm_inventory_disposal

Source: `wa_backend/api/warehouse/transfers.py:1856`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:1862 access.require('inventory.disposal.confirm', payload.source_location_id)
```

### POST /warehouse/quality/vendor-return/confirm — confirm_inventory_vendor_handover

Source: `wa_backend/api/warehouse/transfers.py:1945`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:1951 access.require('inventory.vendor_return.confirm', payload.source_location_id)
```

### POST /warehouse/unified/transfer/dispatch — unified_transfer_dispatch

Source: `wa_backend/api/warehouse/transfers.py:2017`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:2023 access.require('transfer.send', payload.source_location_id)
wa_backend/api/warehouse/transfers.py:2024 access.require('transfer.destination', payload.destination_location_id)
wa_backend/api/warehouse/transfers.py:2026 access.require('inventory.fefo_override', payload.source_location_id)
wa_backend/api/warehouse/transfers.py:2166 access.require('transfer.warehouse_balancing_override')
```

### POST /warehouse/unified/transfer/receive — unified_transfer_receive

Source: `wa_backend/api/warehouse/transfers.py:2820`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:2826 require_transfer(access, 'transfer.receive', payload.transfer_header_id, 'destination')
```

### POST /warehouse/unified/transfer/{header_id}/cancel — unified_transfer_cancel

Source: `wa_backend/api/warehouse/transfers.py:2945`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:2952 require_transfer(access, 'transfer.cancel', header_id, 'source')
```

### POST /warehouse/unified/transfer/{header_id}/reject — unified_transfer_reject

Source: `wa_backend/api/warehouse/transfers.py:3062`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/api/warehouse/transfers.py:3069 require_transfer(access, 'transfer.reject', header_id, 'destination')
```

### POST /warehouse/quality/products/{product_variant_id}/resolve-all — resolve_whole_product_quality

Source: `wa_backend/api/warehouse/whole_product_quality.py:125`. Legacy path: `wa_backend/inventory_access.py:123:codes`, `wa_backend/inventory_access.py:145:codes_by_location`, `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /warehouse/quality/products/{product_variant_id}/resolve-preview — get_whole_product_quality_preview

Source: `wa_backend/api/warehouse/whole_product_quality_preview.py:128`. Legacy path: `wa_backend/inventory_access.py:123:codes`, `wa_backend/inventory_access.py:145:codes_by_location`, `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /simple-products/import-template — get_product_import_template

Source: `wa_backend/domains/simple_products/imports/api/router.py:477`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /simple-products/import-worker/readiness — get_product_import_worker_readiness

Source: `wa_backend/domains/simple_products/imports/api/router.py:512`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### WEBSOCKET /simple-products/imports/{job_id}/ws — product_import_progress_websocket

Source: `wa_backend/domains/simple_products/imports/api/router.py:560`. Legacy path: `wa_backend/inventory_access.py:84:allows`, `wa_backend/realtime/auth.py:25:_authenticate_websocket_identity`.

```text
wa_backend/domains/simple_products/imports/api/router.py:597 InventoryAccess(db, actor).require('catalog.read', any_location=True)
```

### POST /simple-products/imports — create_product_import

Source: `wa_backend/domains/simple_products/imports/api/router.py:663`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /simple-products/imports/{job_id} — get_product_import

Source: `wa_backend/domains/simple_products/imports/api/router.py:806`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/domains/simple_products/imports/api/router.py:812 _require(db, actor, 'catalog.read')
```

### GET /simple-products/imports/{job_id}/errors — get_product_import_errors

Source: `wa_backend/domains/simple_products/imports/api/router.py:841`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

```text
wa_backend/domains/simple_products/imports/api/router.py:849 _require(db, actor, 'catalog.read')
```

### GET /simple-products/imports/{job_id}/lineage — get_product_import_lineage

Source: `wa_backend/domains/simple_products/imports/api/router.py:879`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /simple-products/imports/{job_id}/correction — get_product_import_correction

Source: `wa_backend/domains/simple_products/imports/api/router.py:926`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /simple-products/imports/{job_id}/correction — upload_product_import_correction

Source: `wa_backend/domains/simple_products/imports/api/router.py:1002`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### PUT /simple-products/imports/{job_id}/mapping — set_product_import_mapping

Source: `wa_backend/domains/simple_products/imports/api/router.py:1127`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /simple-products/imports/{job_id}/cancel — cancel_product_import

Source: `wa_backend/domains/simple_products/imports/api/router.py:1210`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /simple-products/imports/{job_id}/retry — retry_product_import

Source: `wa_backend/domains/simple_products/imports/api/router.py:1245`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### GET /simple-products/imports/{job_id}/correction/rows — get_product_import_correction_rows

Source: `wa_backend/domains/simple_products/imports/api/router.py:1375`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### POST /simple-products/imports/{job_id}/correction/rows — patch_product_import_correction_rows

Source: `wa_backend/domains/simple_products/imports/api/router.py:1409`. Legacy path: `wa_backend/inventory_access.py:84:allows`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

### WEBSOCKET /ws/dispatch — websocket_dispatch_endpoint

Source: `wa_backend/main.py:459`. Legacy path: `wa_backend/realtime/auth.py:25:_authenticate_websocket_identity`.

Current direct gate/emitter/classification behavior is described in the matrix; no replacement capability exists in this source path.

## Appendix C — Read-file summary and census checks

Canonical documents read: `.rules`, `AGENTS.md`, `ARCHITECTURE.md`, `RUN.txt`, `V1_SCOPE_FREEZE.md`, `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md`, `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`, `.cursor/rules/business-workflow-protection.mdc`, `IDENTITY_PHASE0_BASELINE.md`.

All tracked executable-source files were searched; all backend Runtime Python was AST-parsed for the affected endpoint/helper graph; model/upgrade declarations parsed without execution. Semantic review focused on auth/dependencies/token_identity, inventory_access/dispatch_access, realtime/main/router registration, central/domain models, dispatch/driver/reconciliation/services, Inventory permissions/policies/warehouse modules, Catalog/Pricing/Offers/Taxation/Suppliers/Sales Returns, lifecycle audit, import worker reauthorization, Dashboard Login/useInventoryAccess/access UI/Dispatch/stocktake and Flutter auth/network/state/events/screens/repository/queue. No unpublished owner file was used as source authority.

| Runtime source with requested identity/flag/admin contract evidence | Reviewed evidence count (union matched lines) |
|---|---|
| dashboard/src/components/dashboard/HeroSettlement.tsx | 1 |
| dashboard/src/components/dispatch/PendingRoutesTable.tsx | 1 |
| dashboard/src/components/dispatch/PostponedRoutesModal.tsx | 6 |
| dashboard/src/components/dispatch/RouteManagementModal.tsx | 8 |
| dashboard/src/components/dispatch/ShortageModal.tsx | 11 |
| dashboard/src/components/operations/CommandCenter.tsx | 4 |
| dashboard/src/components/operations/DashboardLayout.tsx | 6 |
| dashboard/src/components/operations/FleetRadar.tsx | 3 |
| dashboard/src/components/operations/OperationsSidebar.tsx | 2 |
| dashboard/src/components/operations/PulseBar.tsx | 5 |
| dashboard/src/components/operations/SettlementModal.tsx | 2 |
| dashboard/src/data/operations-data.ts | 9 |
| dashboard/src/features/catalog/lifecycle/CatalogLifecycleActions.tsx | 5 |
| dashboard/src/features/commercialRules/CommercialRulesWorkspace.tsx | 1 |
| dashboard/src/features/commercialRules/OfferManagement.tsx | 1 |
| dashboard/src/features/commercialRules/PreviewLab.tsx | 1 |
| dashboard/src/features/commercialRules/TaxManagement.tsx | 1 |
| dashboard/src/features/inventory/productLocations/ProductLocationManager.tsx | 4 |
| dashboard/src/features/inventory/quality/QualityHandlingDestinationsCard.tsx | 1 |
| dashboard/src/features/inventory/quality/WholeProductQualityActionsPanel.tsx | 1 |
| dashboard/src/features/inventory/quality/useProductQualityCommands.ts | 7 |
| dashboard/src/features/inventory/quality/useProductQualitySources.ts | 3 |
| dashboard/src/features/inventory/quality/useWholeProductQualityPreview.ts | 3 |
| dashboard/src/features/operations/useSettlementOwnerNavigation.ts | 3 |
| dashboard/src/features/suppliers/SupplierSelector.tsx | 1 |
| dashboard/src/features/suppliers/useSupplierSearch.ts | 1 |
| dashboard/src/hooks/useInventoryAccess.ts | 13 |
| dashboard/src/i18n/resources.ts | 2 |
| dashboard/src/lib/durableOperations.ts | 2 |
| dashboard/src/lib/productDisplayPreferences.ts | 8 |
| dashboard/src/pages/CommercialRulesDashboard.tsx | 2 |
| dashboard/src/pages/DispatchBoard.tsx | 48 |
| dashboard/src/pages/Login.tsx | 7 |
| dashboard/src/pages/OperationsDashboard.tsx | 27 |
| dashboard/src/pages/PricingDashboard.tsx | 2 |
| dashboard/src/pages/SalesReturnsDashboard.tsx | 3 |
| dashboard/src/pages/inventory/MainInventory.tsx | 10 |
| dashboard/src/pages/inventory/TabBatches.tsx | 1 |
| dashboard/src/pages/inventory/TabInventoryAccess.tsx | 4 |
| dashboard/src/pages/inventory/TabWarehouseLocations.tsx | 3 |
| dashboard/src/pages/inventory/archive/ArchiveOwnerWorkspace.tsx | 1 |
| dashboard/src/pages/inventory/batches/BatchDispositionManager.tsx | 1 |
| dashboard/src/pages/inventory/batches/BatchFocusWorkspace.tsx | 2 |
| dashboard/src/pages/inventory/batches/BatchQuantityActions.tsx | 1 |
| dashboard/src/pages/inventory/batches/useBatchDispositionCommand.ts | 3 |
| dashboard/src/pages/inventory/batches/useBatchSpecialTransfer.ts | 3 |
| dashboard/src/pages/inventory/batches/useBatchStockSources.ts | 3 |
| dashboard/src/pages/inventory/batches/useBatchTerminalAction.ts | 3 |
| dashboard/src/pages/inventory/inventorySessionCache.ts | 2 |
| dashboard/src/pages/inventory/quality/useQualityBatchCandidates.ts | 3 |
| dashboard/src/pages/inventory/stocktake/parsers.ts | 3 |
| dashboard/src/pages/inventory/stocktake/types.ts | 1 |
| dashboard/src/pages/products/ProductsPage.tsx | 16 |
| dashboard/src/pages/products/advanced-uom/AdvancedUomDashboard.tsx | 10 |
| dashboard/src/pages/products/barcode/ProductBarcodeManager.tsx | 8 |
| dashboard/src/pages/products/barcode/useIndependentPackageBarcode.ts | 5 |
| dashboard/src/pages/products/barcode/usePrimaryBarcodeReplacement.ts | 5 |
| dashboard/src/pages/products/barcode/useProductBarcodeWorkflow.ts | 3 |
| dashboard/src/pages/products/create/productDraftStorageKey.ts | 3 |
| dashboard/src/pages/products/create/useCreateProductMutation.ts | 5 |
| dashboard/src/pages/products/create/useCreateProductWorkflow.ts | 6 |
| dashboard/src/pages/products/deriveProductsCapabilities.ts | 8 |
| dashboard/src/pages/products/display-preferences/createProductDisplayPreferenceActions.ts | 4 |
| dashboard/src/pages/products/display-preferences/useProductDisplayPreferencesState.ts | 1 |
| dashboard/src/pages/products/family/ProductFamiliesManager.tsx | 12 |
| dashboard/src/pages/products/family/ProductFamilyReassignDialog.tsx | 5 |
| dashboard/src/pages/products/family/useProductFamiliesWorkflow.ts | 3 |
| dashboard/src/pages/products/family/useProductFamilyReassignWorkflow.ts | 3 |
| dashboard/src/pages/products/import/ImportInlineCorrectionPanel.tsx | 3 |
| dashboard/src/pages/products/import/ImportProductModal.tsx | 3 |
| dashboard/src/pages/products/import/ImportProductStatusPanel.tsx | 6 |
| dashboard/src/pages/products/import/correctionRouteGate.ts | 8 |
| dashboard/src/pages/products/import/productImportSessionKey.ts | 3 |
| dashboard/src/pages/products/import/useImportCorrection.ts | 5 |
| dashboard/src/pages/products/import/useImportInlineCorrection.ts | 5 |
| dashboard/src/pages/products/import/useImportProductUpload.ts | 3 |
| dashboard/src/pages/products/import/useImportProductWorkflow.ts | 8 |
| dashboard/src/pages/products/list/useProductCatalogSummary.ts | 4 |
| dashboard/src/pages/products/list/useProductsListWorkflow.ts | 3 |
| dashboard/src/pages/products/pricing/usePriceEditMutation.ts | 5 |
| dashboard/src/pages/products/pricing/usePriceEditWorkflow.ts | 4 |
| dashboard/src/pages/products/productDurableScope.ts | 3 |
| dashboard/src/pages/products/rename/ProductRenameDialog.tsx | 5 |
| dashboard/src/pages/products/rename/useProductRenameWorkflow.ts | 3 |
| dashboard/src/pages/products/tracking/useProductTrackingMutations.ts | 8 |
| dashboard/src/pages/products/tracking/useProductTrackingWorkflow.ts | 5 |
| dashboard/src/pages/products/useProductsIdentityScopeReset.ts | 5 |
| dashboard/src/pages/suppliers/SuppliersPage.tsx | 2 |
| dashboard/src/pages/suppliers/useSupplierListSearch.ts | 1 |
| dashboard/src/types/dispatch.ts | 2 |
| wa_backend/api/auth.py | 25 |
| wa_backend/api/branches.py | 9 |
| wa_backend/api/catalog.py | 37 |
| wa_backend/api/commercial_policy.py | 4 |
| wa_backend/api/dependencies.py | 11 |
| wa_backend/api/dispatch.py | 195 |
| wa_backend/api/driver.py | 106 |
| wa_backend/api/inventory_permissions.py | 23 |
| wa_backend/api/inventory_stock_policy.py | 7 |
| wa_backend/api/offers.py | 23 |
| wa_backend/api/platform_manager.py | 3 |
| wa_backend/api/pricing.py | 20 |
| wa_backend/api/product_locations.py | 5 |
| wa_backend/api/product_tracking.py | 6 |
| wa_backend/api/reconciliation.py | 10 |
| wa_backend/api/sales_returns.py | 7 |
| wa_backend/api/simple_products.py | 13 |
| wa_backend/api/suppliers.py | 6 |
| wa_backend/api/taxation.py | 25 |
| wa_backend/api/tenant.py | 2 |
| wa_backend/api/warehouse/inbound.py | 5 |
| wa_backend/api/warehouse/inbound_adjustments.py | 2 |
| wa_backend/api/warehouse/ledger.py | 7 |
| wa_backend/api/warehouse/live_stock.py | 12 |
| wa_backend/api/warehouse/locations.py | 7 |
| wa_backend/api/warehouse/status.py | 2 |
| wa_backend/api/warehouse/stocktake.py | 34 |
| wa_backend/api/warehouse/transfer_policy.py | 4 |
| wa_backend/api/warehouse/transfers.py | 20 |
| wa_backend/api/warehouse/whole_product_quality.py | 2 |
| wa_backend/api/warehouse/whole_product_quality_preview.py | 2 |
| wa_backend/dispatch_access.py | 4 |
| wa_backend/domains/credential_confirmation.py | 2 |
| wa_backend/domains/dispatch_archive_navigation.py | 1 |
| wa_backend/domains/dispatch_reservations.py | 2 |
| wa_backend/domains/inventory_batch_restrictions/queries.py | 2 |
| wa_backend/domains/inventory_catalog_presence.py | 2 |
| wa_backend/domains/operations_archive_navigation.py | 1 |
| wa_backend/domains/pricing/driver_authority.py | 5 |
| wa_backend/domains/pricing/driver_display.py | 5 |
| wa_backend/domains/sales_calculation/driver_sale.py | 18 |
| wa_backend/domains/simple_products/imports/api/router.py | 21 |
| wa_backend/domains/simple_products/imports/infrastructure/repository.py | 6 |
| wa_backend/domains/simple_products/service.py | 9 |
| wa_backend/inventory_access.py | 10 |
| wa_backend/main.py | 1 |
| wa_backend/models.py | 42 |
| wa_backend/product_lifecycle.py | 1 |
| wa_backend/realtime/auth.py | 8 |
| wa_backend/schemas.py | 18 |
| wa_backend/services.py | 17 |
| wa_backend/tools/staging_load/wanasah_d7s_mixed_load_config.py | 6 |
| wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py | 17 |
| wa_backend/workers/tasks/handshake.py | 6 |
| wa_backend/workers/tasks/session_monitor.py | 10 |
| wanasah_frontend/lib/blocs/auth/auth_bloc.dart | 17 |
| wanasah_frontend/lib/blocs/auth/auth_state.dart | 3 |
| wanasah_frontend/lib/blocs/dashboard/dashboard_bloc.dart | 11 |
| wanasah_frontend/lib/blocs/dashboard/dashboard_event.dart | 12 |
| wanasah_frontend/lib/core/network/api_client.dart | 1 |
| wanasah_frontend/lib/repositories/dashboard_repository.dart | 4 |
| wanasah_frontend/lib/screens/dashboard_screen.dart | 10 |
| wanasah_frontend/lib/screens/login_screen.dart | 1 |
| wanasah_frontend/lib/screens/splash_screen.dart | 1 |
| wanasah_frontend/lib/screens/visit_list_screen.dart | 2 |

Reproduction from the pinned baseline (read-only):

```powershell
git ls-files
rg -n '\bis_admin\b|\bget_current_admin\b|Driver|driver_id|/driver/login' wa_backend -g '*.py' -g '!**/tests/**' -g '!**/scripts/**' -g '!**/perf_reports/**' -g '!**/alembic/**' -g '!seed_dev.py'
rg -n 'driver_id|is_admin|is_company_admin|isCompanyAdmin|dashboard_access' dashboard/src
rg -n 'driver_id|driverId|getDriverId|/driver/login' wanasah_frontend/lib
rg -n 'drivers\.id|drivers\.company_id|REFERENCES drivers' wa_backend/models.py wa_backend/domains wa_backend/alembic/versions
```

AST census follows Depends/get_current_admin and is_admin leaves; resolves named local/imported helpers and InventoryAccess methods; records prefixes and route aliases; excludes historical/test code. FK extraction visits mapped classes and composite/inline ForeignKeys targeting drivers; upgrade evidence excludes downgrade bodies and includes raw SQL. Static graph does not claim dynamic execution or physical database equivalence.
