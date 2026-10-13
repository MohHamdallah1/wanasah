# Wanasah Representatives & Vehicles V1 Plan

## Build Representatives completely first, then Vehicles, on top of the canonical identity/authorization foundation

**Status:** REPRESENTATIVES IMPLEMENTED — FINAL FIELD/FLUTTER + OWNER ACCEPTANCE PENDING; VEHICLES NOT STARTED
**Owner decision date:** 2026-10-10  
**Execution rule:** Representatives must be completed and owner-accepted before Vehicles implementation starts.  
**Prerequisite status:** COMPLETE — Backoffice and Field Representative identities are cleanly separated and capability-based authorization is authoritative under `ARCHITECTURE.md`, `.rules`, and `AGENTS.md`.
**Canonical references:** `ARCHITECTURE.md`, `.rules`, `AGENTS.md`, `RUN.txt`, `V1_SCOPE_FREEZE.md`, `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`.

## 0.0 Representatives V1 release-closure ledger

This ledger is the authoritative completion snapshot for the merged Representatives implementation. The canonical FIELD identity is `CompanyPrincipal` + `FieldRepresentative`; a legacy `Driver` row remains only as a bounded operational compatibility sidecar where existing FKs/client wire contracts still require it, connected through a `FIELD_ONLY` `IdentityLegacyDriverMap`. Legacy Driver identity is never authentication or authorization authority.

Completed on merged `main`:

- [x] Representatives architecture/folder ownership freeze implemented without growing `driver.py` or `dispatch.py`.
- [x] Representative capability family implemented: `representative.read`, `representative.manage`, `representative.credentials.reset`.
- [x] Frozen seven-route Representative HTTP contract implemented with no hard-delete route.
- [x] Representative list/detail implemented.
- [x] Representative create/update implemented.
- [x] Canonical `CompanyPrincipal` + `FieldRepresentative` creation with temporary legacy `Driver` sidecar and `FIELD_ONLY` mapping implemented atomically/idempotently.
- [x] Representative deactivate/reactivate implemented while preserving canonical/profile/legacy identities.
- [x] Deactivation blocker matrix implemented for open WorkSession, current DispatchRoute states (`active`/`waiting`/`postponed`), pending HANDSHAKE expected receiver, ended unreconciled WorkSession, and unresolved VEHICLE_RECON state.
- [x] Explicit credential reset implemented through canonical credential/session authority.
- [x] `auth_revision` invalidation and FIELD refresh-session revocation implemented/tested for lifecycle/reset security boundaries.
- [x] Mutation idempotency implemented for create/update/lifecycle/credential reset, including conflict semantics.
- [x] Company tenant isolation/fail-closed cross-company behavior implemented/tested.
- [x] Dashboard `/representatives-vehicles` page and capability-gated sidebar navigation implemented.
- [x] Representative create/edit/detail Dashboard flows implemented.
- [x] Search, active/inactive/all filters, cursor pagination, and duplicate-safe infinite scrolling implemented.
- [x] Dashboard capability UX implemented for read/manage/credential-reset authority.
- [x] Dashboard lifecycle and credential-reset UI implemented.
- [x] Arabic and English Representative UI resources implemented with RTL/LTR-aware rendering.
- [x] Representative password validation enforces minimum length plus the canonical 72-byte UTF-8 ceiling using byte length, not character count alone.
- [x] Vehicles tab remains visible but explicitly disabled/gated; Vehicles implementation has not started.
- [x] Representative contract/architecture tests merged.
- [x] Real PostgreSQL Representative runtime acceptance merged.
- [x] Representative concurrency/idempotency runtime acceptance merged.

Still pending before Representatives owner-complete gate:

- [ ] Final FIELD/Flutter compatibility acceptance from the separately assigned worker.
- [ ] Final owner acceptance of Representative behavior/wording/density/forms/actions.
- [ ] **REPRESENTATIVES V1 COMPLETE + OWNER ACCEPTED**.

Vehicles status:

- [ ] Vehicles implementation — **NOT STARTED**. Do not begin until the Representatives owner-acceptance gate is explicitly closed.

---

# 0. Frozen owner decisions and scope

- [ ] The tenant/security boundary is **Company**.
- [ ] V1 operational UX is one company context with **one or many warehouses**.
- [ ] V1 does **not** require a global Branch switcher, Branch-scoped representative management, Branch-scoped vehicle management, or Branch ownership of company master data.
- [ ] Existing Branch schema/readiness may remain for future expansion, but Representatives/Vehicles V1 must not depend on it.
- [ ] Products are company-wide master data.
- [ ] Zones/territories are company-wide master data.
- [ ] Shops/customers are company-wide master data.
- [x] Field Representatives are company-wide master data.
- [ ] Vehicles are company-wide master data.
- [x] Representatives are **not permanently owned by one warehouse**.
- [ ] Vehicles are **not permanently owned by one warehouse**.
- [x] Source warehouse is chosen by the concrete operational workflow/route/load, not by representative identity.
- [ ] Source warehouse is chosen by the concrete operational workflow/route/load, not by vehicle identity.
- [x] A representative can work from a different authorized source warehouse on another route/day without changing his master identity.
- [ ] A vehicle can be used from a different authorized source warehouse on another route/day without changing its master identity.
- [x] Backoffice users and Company Owner belong to Dashboard identity/authorization and are **not managed by this page**.
- [x] Field Representatives belong to Flutter field identity and are **the only human accounts managed by the Representatives tab**.
- [x] Field Representatives must not receive Dashboard access.
- [ ] Vehicles are non-human operational assets and never authenticate.
- [x] Dashboard complexity remains low; backend owns Representative validation, isolation, authorization, lifecycle, audit, idempotency, and route/work-session safety.
- [x] No hard delete for Representatives in V1; lifecycle uses active/inactive transitions so history remains valid.
- [ ] No hard delete for Vehicles in V1.
- [x] Representative UI is Arabic-first, i18n-ready, RTL/LTR safe, Western-digit friendly, and keyboard-aware.
- [x] No Representative mega-file/god-hook; page shell and Representatives feature remain separated.
- [x] Existing Dispatch/Inventory business authority is reused; Representative administration does not duplicate route, warehouse, custody, permission, or stock truth.

---

## 0.1 Frozen implementation structure — mandatory

These decisions are approved architecture for this plan. Workers may not replace them with a simpler mega-file layout without lead approval.

- [x] Single Responsibility Principle is mandatory for every backend function/service and every Dashboard component/hook.
- [x] Representatives/Vehicles are built in their own first-class modules from day one; they are not appended to `driver.py`, `dispatch.py`, `OperationsDashboard.tsx`, or `DispatchBoard.tsx`.
- [x] `driver.py` and `dispatch.py` are **shrinking compatibility surfaces**. Representatives/Vehicles work may add only thin delegation/wiring there when absolutely unavoidable. Any required business logic currently buried there must be extracted to the correct module rather than extended in place.
- [x] No new god-function, mega-component, god-hook, generic `shared.py`, or cross-domain dumping module is permitted.
- [x] Copy-paste-only relocation is not the final architecture. Behavior-preserving extraction may be staged, but long/multi-responsibility functions must ultimately be decomposed by responsibility under the Driver/Dispatch modularization plan.
- [x] New Representatives/Vehicles modules are intentionally the **target architecture** that future Driver/Dispatch extraction will consume, so this work must reduce future refactor cost rather than create another one.

### Frozen backend module ownership

```text
wa_backend/domains/representatives/
  __init__.py
  contracts.py        # public domain/application contracts only
  repository.py       # representative-owned persistence/query primitives only
  queries.py          # list/detail/search read models only
  management.py       # create/update orchestration only
  lifecycle.py        # deactivate/reactivate safety transitions only
  credentials.py      # representative credential operations; delegates auth/identity authority

wa_backend/api/representatives/
  __init__.py         # aggregated router only
  schemas.py          # HTTP request/response schemas only
  read.py             # GET endpoints only
  management.py       # create/update endpoints only
  lifecycle.py        # deactivate/reactivate endpoints only
  credentials.py      # credential-reset endpoint only
```

Identity remains authoritative for `CompanyPrincipal` credentials/session semantics. Representatives owns the Field Representative master-management use cases. Dispatch consumes representative contracts; it does not own Representative CRUD.

### Frozen Dashboard module ownership

```text
dashboard/src/pages/representatives-vehicles/
  RepresentativesVehiclesPage.tsx   # page shell/tabs only
  representatives/
    contracts.ts                     # view/API types only
    api.ts                           # representative HTTP client only
    useRepresentatives.ts            # list/query state only
    RepresentativesTab.tsx           # tab composition only
    RepresentativeTable.tsx          # list/table rendering only
    RepresentativeForm.tsx           # create/edit form only
    RepresentativeDrawer.tsx         # details/actions composition only
    RepresentativeLifecycleActions.tsx
    RepresentativeCredentialAction.tsx
  vehicles/
    VehiclesTabPlaceholder.tsx       # visible gated placeholder until Representatives acceptance
```

Exact filenames may change only by technical-lead approval when repository conventions prove a better equivalent; responsibility boundaries may not be collapsed.

### Frozen V1 Representative capabilities

All are company-scoped capabilities resolved through canonical Backoffice authorization:

- [x] `representative.read` — list/detail/search.
- [x] `representative.manage` — create/update/deactivate/reactivate.
- [x] `representative.credentials.reset` — explicit credential reset.

Company Owner receives these through canonical owner authority. Backoffice users receive them through Roles. Field Representatives never receive Dashboard management authority merely because they are field representatives.

### Frozen V1 Representative HTTP surface

- [x] `GET /representatives` — bounded cursor list/search/filter.
- [x] `GET /representatives/{representative_id}` — detail.
- [x] `POST /representatives` — create.
- [x] `PATCH /representatives/{representative_id}` — update allowed profile fields.
- [x] `POST /representatives/{representative_id}/deactivate` — lifecycle transition.
- [x] `POST /representatives/{representative_id}/reactivate` — lifecycle transition.
- [x] `POST /representatives/{representative_id}/credentials/reset` — explicit credential reset.
- [x] No hard-delete route.

List/detail use `representative.read`; create/update/lifecycle use `representative.manage`; reset uses `representative.credentials.reset`. Tenant authority always comes from the canonical Backoffice access context, never from a request body/query `company_id`.

---
## 0.2 Frozen Wave 1 HTTP wire contract — mandatory

DTO/class names are **not** frozen and tests must not depend on implementation class names. The external JSON/query/status contract below is frozen.

### Representative view

List items, detail responses, create responses, and update responses expose only:

- `id` — canonical `FieldRepresentative.id`.
- `full_name`.
- `username`.
- `phone_number` (`null` allowed).
- `is_active` — canonical principal active state.
- `can_allow_debt`.
- `max_debt_limit` — exact decimal value; clients must not use binary-float arithmetic for business decisions.

Do not expose `principal_id`, legacy `Driver.id`, `password_hash`, refresh/session identifiers, capabilities, or internal ownership/FK fields.

### List

`GET /representatives`

Query contract:

- `search`: optional string, 2..100 characters; searches normalized full name, username, and phone.
- `active`: optional boolean; omitted = all, `true` = active, `false` = inactive.
- `cursor`: optional opaque string, max 512 characters. Clients/tests must not depend on cursor encoding.
- `limit`: integer, default 30, min 1, max 100.

Response:

```json
{
  "items": [],
  "next_cursor": null,
  "has_more": false
}
```

Ordering is stable: active representatives first when the list is unfiltered, then normalized full name, then representative id as deterministic tie-breaker.

### Detail

`GET /representatives/{representative_id}` returns one Representative view. A missing or cross-company id is indistinguishable and returns the same fail-closed not-found contract.

### Create

`POST /representatives` -> `201` + Representative view.

Request body:

```json
{
  "request_id": "UUID",
  "full_name": "string",
  "username": "string",
  "phone_number": null,
  "password": "string",
  "can_allow_debt": false,
  "max_debt_limit": "0.000"
}
```

Constraints:

- `full_name`: 1..120.
- `username`: 1..80, canonical company-local uniqueness.
- `phone_number`: optional/null, max 20.
- `password`: 8..72 and hashed with the canonical company credential mechanism; never logged or returned.
- `can_allow_debt`: defaults `false`.
- `max_debt_limit`: nonnegative exact decimal, defaults `0.000`; if debt is disabled, the stored limit must remain business-safe and must not silently grant debt.
- `request_id`: UUID idempotency key in the body; no client-supplied `company_id`, principal id, representative id, role, capability, or profile type.

### Update

`PATCH /representatives/{representative_id}` -> `200` + Representative view.

Request body contains `request_id: UUID` plus any subset of:

- `full_name`.
- `username`.
- `phone_number` (including explicit `null`).
- `can_allow_debt`.
- `max_debt_limit`.

`password`, active state, principal/profile ids, company id, role/capability data, and legacy Driver fields are forbidden in generic PATCH. Omitted fields stay unchanged. At least one mutable field must be present. Username changes are allowed only through canonical company uniqueness/security validation. Wave 1 adds no synthetic version field solely for this endpoint; concurrency/locking must use the existing persistence/transaction model rather than inventing an unrelated version contract.

### Mutation idempotency

Create/update/lifecycle/credential mutations use body `request_id: UUID`. Repeating the same operation with the same request id and same semantic payload must not duplicate the mutation. Reusing the same request id for a materially different payload/target must fail with the project's stable idempotency-conflict behavior.

### Credential reset

`POST /representatives/{representative_id}/credentials/reset`

Request body:

```json
{
  "request_id": "UUID",
  "new_password": "string"
}
```

`new_password` is 8..72. On successful implementation the operation must be one transaction that:

1. tenant-safely resolves the canonical Field Representative principal;
2. writes the new canonical password hash;
3. increments `auth_revision` exactly once for a non-replayed reset;
4. revokes that principal's FIELD refresh sessions through the canonical auth-session invalidation service;
5. records audit/idempotency evidence without secret material.

Success response is `204 No Content`; it never echoes password/hash/session data. A replay of the same request id/payload must remain successful without a second credential mutation/revision bump.

### Common HTTP security behavior

- unauthenticated -> `401`.
- authenticated Backoffice without the required capability -> `403`.
- missing/cross-company representative target -> same fail-closed `404` contract.
- validation failures -> normal `422` transport validation unless a domain-specific stable conflict applies.
- company authority always comes from canonical Backoffice access context, never request data.

---
# 1. Final page concept
## 1.1 Navigation

Recommended current sidebar label:

**المندوبون والسيارات**

Page tabs:

1. **المندوبون**
2. **السيارات**

Execution behavior:

- [x] Shared page shell and the **Representatives** tab are implemented.
- [x] Vehicles tab exists as a visible gated/disabled tab; no Vehicle workflow has been implemented.
- [ ] After the owner accepts the Representatives behavior and UI, mark the Representatives completion gate `[x]` and begin Vehicles.
- [x] Page/tab naming remains presentation-level and does not change domain contracts.

## 1.2 Page UX constitution

- [x] Use the same compact Wanasah shell language as Products/Inventory/Suppliers.
- [x] Compact top bar; no oversized dashboard cards.
- [ ] Primary action changes by tab: `إضافة مندوب` or `إضافة سيارة` — Vehicle action remains intentionally unavailable while Vehicles is gated.
- [x] Search/filter controls stay close to the Representative table.
- [x] Infinite scrolling / cursor pagination is used for Representatives.
- [x] Row actions/detail surface follow the accepted compact Wanasah interaction pattern.
- [x] Representative UI does not expose internal terms such as principal, RLS, role join, InventoryLocation, or FK to normal operators.
- [x] Backend Representative errors map to business Arabic/English messages.
- [x] No hidden authorization assumptions in the UI; backend remains authoritative.

---

# 2. Prerequisite gate — Identity & authorization foundation

Representative administration is built on canonical identity rather than legacy mixed Driver authority. Existing operational `Driver.id` FKs remain compatibility locators only where the current runtime still requires them.

Before Representatives implementation proceeds beyond harmless page-shell work:

- [x] `CompanyPrincipal` is authoritative for company credentials/session identity.
- [x] Backoffice profile/type is distinct from Field Representative profile/type.
- [x] Dashboard login fails closed for field-only identities.
- [x] Flutter field login fails closed for backoffice-only identities.
- [x] Company Owner authority is explicit/system-managed.
- [x] New permissions are capability-based and never derive authority from a generic admin/persona flag.
- [x] Existing role/scope model is attached to Backoffice identity, not Field Representative identity by accident.
- [x] Actor/audit references needed by administrative mutations point to the correct principal type while bounded legacy provenance fields remain legacy IDs where required.
- [x] FIELD identity/authority resolves canonically; old Dispatch/Visit/WorkSession operational FKs may retain mapped legacy `Driver.id` until their separately approved migration.
- [x] No new endpoint created by this plan derives authority or representative identity from a generic admin/persona boolean.
- [x] Authentication/session/token claims expose stable identity/channel semantics required by Dashboard and FIELD runtime.
- [x] Canonical identity/authorization acceptance gates passed before Representative mutations were enabled.

**Gate:**

- [x] **IDENTITY FOUNDATION READY FOR REPRESENTATIVES**

---

# 3. Representatives — domain contract freeze

## 3.1 Representative master identity

A Field Representative is a company-wide field actor. V1 data is intentionally minimal and operationally useful.

Required/owned concepts:

- [x] `company_id` — tenant authority; never client-trusted across tenants.
- [x] stable representative/profile ID.
- [x] linked canonical company principal/credential identity.
- [x] temporary mapped legacy Driver operational sidecar for frozen legacy FKs/wire compatibility; never identity authority.
- [x] `FIELD_ONLY` legacy mapping classification.
- [x] full name.
- [x] username/login identifier according to canonical company credential rules.
- [x] phone number (optional).
- [x] active/inactive lifecycle state.
- [x] commercial debt permission represented by `can_allow_debt`.
- [x] maximum debt limit represented by `max_debt_limit`, preserving Decimal/Numeric precision and nonnegative invariant.

Explicitly **not identity fields**:

- [x] no mandatory warehouse ownership.
- [x] no mandatory branch ownership.
- [x] no permanent vehicle assignment.
- [x] no permanent route assignment.
- [x] no permanent zone ownership merely to simplify UI.
- [x] no inventory balance stored on representative profile.

Operational relationships remain owned by Dispatch/Inventory workflows.

## 3.2 Representative lifecycle

- [x] Create representative.
- [x] Read/list/search representatives.
- [x] Edit allowed profile fields.
- [x] Deactivate representative.
- [x] Reactivate representative.
- [x] Reset credentials through the canonical credential service.
- [x] No hard delete endpoint/UI.
- [x] Deactivation preserves route/visit/sales/audit history.
- [x] Deactivation does not rewrite historical records.
- [x] Backend blocks unsafe deactivation using the proven operational blocker matrix.
- [x] Exact blocker rules are derived from current WorkSession/Dispatch/Inventory reconciliation invariants, not invented in the UI.
- [x] Reactivation reuses the existing canonical identity/profile/map/legacy sidecar and does not create duplicates.

---

# 4. Representatives — capability and security model

Capability names are frozen by section 0.1 and are present in the canonical global permission catalog as company-scoped authorities:

- [x] `representative.read` wired and grantable.
- [x] `representative.manage` wired and grantable.
- [x] `representative.credentials.reset` wired and grantable.

Rules:

- [x] Company Owner resolves to all company Representative-management capabilities.
- [x] Backoffice users may receive Representative capabilities through Roles.
- [x] Field Representatives never receive Dashboard Representative-management capabilities merely because they are representatives.
- [x] All reads/mutations are tenant-scoped in backend queries.
- [x] Cross-company Representative IDs fail closed without leaking existence/details.
- [x] Direct API calls without required capability fail even when a UI control is hidden.
- [x] Password hash is never returned by Representative API contracts.
- [x] Username uniqueness follows the canonical company identity rule.
- [x] Login/session protections remain in shared credential/auth infrastructure.

---

# 5. Representatives — backend service/API design

## 5.1 Ownership and module boundaries

- [x] Dedicated Representatives domain/application modules implemented; no Representative CRUD was added to `driver.py` or `dispatch.py`.
- [x] Credential creation/reset delegates to canonical identity/auth authority.
- [x] Dispatch remains owner of route/assignment workflow, not Representative CRUD.
- [x] Inventory does not own Representative CRUD.
- [x] DTO/schema/query/repository/management/lifecycle/credentials concerns remain separated.

## 5.2 List/read contract

- [x] Tenant-scoped Representative list endpoint.
- [x] Cursor-based pagination.
- [x] Bounded page size.
- [x] Search by normalized name, username, and phone.
- [x] Filter active/inactive/all.
- [x] Stable deterministic sort with active representatives first when unfiltered.
- [x] Public responses return only UI-required fields.
- [x] Runtime query-count acceptance guards the list path against accidental N+1 behavior.

## 5.3 Create contract

- [x] Company ownership/tenant authority validated server-side.
- [x] Full name/username/phone/password/debt inputs validated by frozen contracts.
- [x] Canonical Principal + Field Representative profile + temporary Driver sidecar + FIELD_ONLY mapping created atomically.
- [x] No Backoffice profile is created for a Field Representative.
- [x] FIELD channel/type is explicit.
- [x] Request-id idempotency prevents duplicate submits.
- [x] Audit/idempotency evidence excludes secret material.

## 5.4 Update contract

- [x] Minimal-diff updates; omitted values are not silently reset.
- [x] Username changes pass company uniqueness/security rules.
- [x] Debt settings are validated atomically.
- [x] Meaningful identity/profile compatibility fields stay synchronized without turning legacy Driver into authority.

## 5.5 Credential-reset contract

- [x] Dedicated explicit credential-reset operation; password is not accepted through generic profile PATCH.
- [x] Independent `representative.credentials.reset` capability check.
- [x] Canonical password policy reused.
- [x] Canonical `CompanyPrincipal.password_hash` is changed; legacy Driver password hash is not credential authority.
- [x] `auth_revision` increments exactly once for each non-replayed reset.
- [x] FIELD refresh sessions are revoked through canonical auth-session invalidation.
- [x] Response never echoes password/hash/session data.
- [x] Audit/idempotency evidence never stores secret material.

## 5.6 Deactivate/reactivate contract

- [x] Explicit deactivate action endpoint/service.
- [x] Explicit reactivate action endpoint/service.
- [x] No physical delete.
- [x] Active/current work-session/route/transfer/reconciliation safety rules enforced in backend.
- [x] Existing history remains readable and legacy operational identifiers are preserved.
- [x] Inactive canonical principal cannot field-login.
- [x] Deactivation bumps canonical auth revision and revokes FIELD refresh sessions.
- [x] Replayed lifecycle request is idempotent; conflicting lifecycle state returns stable business conflict behavior.

---

# 6. Representatives — Dispatch/Flutter integration protection

This phase is required because Representatives are not just Dashboard records; they must remain valid field actors. A separate worker owns the final FIELD/Flutter compatibility acceptance; this closure task must not duplicate it.

Current canonical compatibility contract:

- Canonical FIELD authentication/authority is `CompanyPrincipal` + `FieldRepresentative` + FIELD channel/context.
- `IdentityLegacyDriverMap` provides the bounded bridge to the existing operational `Driver.id` locator with `FIELD_ONLY` classification.
- Existing WorkSession/DispatchRoute/Visit/transfer FKs that still store `Driver.id` are not reinterpreted as principal/profile IDs.
- Flutter may continue carrying the frozen `driver_id`/`legacy_driver_id` compatibility locator where current V1 wire/offline behavior still requires it; this is not credential or authorization authority.

Final integration acceptance remains pending until the assigned worker reports/merges evidence:

- [ ] FIELD/Dispatch representative discovery and assignment remain canonical/fail-closed under merged runtime behavior.
- [ ] Route assignment accepts only valid active same-company FIELD representatives under existing rules.
- [ ] WorkSession creation accepts only valid active same-company FIELD representatives under existing rules.
- [ ] Sales/returns/collection attribution preserves existing business meaning through canonical FIELD context plus bounded legacy locator compatibility.
- [ ] Flutter `/driver/login` compatibility returns/uses canonical FIELD identity without ambiguous cross-channel login.
- [ ] Flutter persisted legacy driver locator remains compatible without corrupting local state during the V1 transition.
- [ ] Logout/session invalidation works after Representative deactivate/reset in the real FIELD/Flutter client flow.
- [ ] Offline retry/idempotency payloads continue to attribute the correct representative.
- [ ] Realtime/FIELD authorization does not depend on legacy admin/persona flags.
- [ ] No Dashboard-only capability leaks into FIELD tokens.

---

# 7. Representatives — Dashboard page structure

Implemented feature boundary:

```text
pages/representatives-vehicles/
  RepresentativesVehiclesPage.tsx
  representatives/
    ...representative list/search/form/drawer/actions...
  vehicles/
    ...gated placeholder only; implementation later...
```

- [x] one shared page shell.
- [x] Representatives and Vehicles have separate feature boundaries.
- [x] no single giant component.
- [x] no one hook owns fetch/list/form/password/lifecycle/vehicle behavior together.
- [x] shared UI is extracted only where genuinely shared.

---

# 8. Representatives — list/table UX

Implemented Representative table/list behavior:

- [x] representative name.
- [x] username.
- [x] phone.
- [x] status.
- [x] compact commercial/debt indicator.
- [x] actions.

Rules:

- [x] Search input is localized and visually consistent with Wanasah.
- [x] Search name/username/phone.
- [x] Status filter: all / active / inactive.
- [x] Active representatives first by default when unfiltered.
- [x] Western digits are preserved by the page/localization conventions.
- [x] Clear empty state.
- [x] Clear error + retry state.
- [x] Infinite scroll/cursor loading prevents duplicate rows.
- [x] Detail/action state remains local to the Representative feature.

---

# 9. Representatives — Add Representative flow

The operator reaches a usable Representative with the fewest safe steps.

## 9.1 Initial form fields

- [x] Full name.
- [x] Username.
- [x] Phone number.
- [x] Initial password using canonical policy including 72-byte UTF-8 ceiling.
- [x] Active by default according to the frozen create contract.
- [x] Debt permission control.
- [x] Maximum debt limit with exact-decimal validation.

Not shown:

- [x] no branch selector.
- [x] no mandatory warehouse selector.
- [x] no vehicle selector.
- [x] no route selector.
- [x] no internal role/permission selector for Representative Dashboard access.

## 9.2 Form UX

- [x] Clear inline validation.
- [x] Duplicate-submit protection through request id / mutation state.
- [x] Backend remains source of truth for uniqueness/conflicts.
- [x] Success updates the Representative list without a full page reload.
- [ ] Newly created representative can immediately authenticate in the real Flutter/FIELD client flow — pending the separate FIELD/Flutter compatibility acceptance.

---

# 10. Representatives — Edit/details/actions UX

- [x] Row action opens a focused detail/action surface.
- [x] View identity/basic info without exposing secrets.
- [x] Edit allowed profile fields.
- [x] Username change follows the frozen identity contract.
- [x] Separate credential-reset action.
- [x] Separate deactivate/reactivate action with clear consequences.
- [x] Debt settings use business wording.
- [x] No hard-delete button.
- [x] Deactivation blocker conflicts map to clear business feedback.
- [x] Route/visit history is not dumped into the V1 administration drawer.

---

# 11. Representatives — i18n, accessibility, and resilience

- [x] Representative strings are i18n-backed.
- [x] Arabic resources are implemented and RTL rendering follows `i18n.dir()`.
- [x] English resources are implemented for LTR use.
- [x] Password validation explains and enforces the 72-byte UTF-8 limit in both languages.
- [x] API 401/403/409/422/5xx Representative states map to useful user feedback.
- [x] Capability-denied states remain readable without granting mutation controls.

---

# 12. Representatives — focused acceptance gates

Code analysis precedes tests; tests prove the identified contracts.

Backend/security:

- [x] create/read/update/deactivate/reactivate same-company representative.
- [x] cross-company read/mutation blocked.
- [x] missing capability blocked.
- [x] Company Owner allowed.
- [x] field representative cannot access Dashboard management API through FIELD authority.
- [x] Dashboard-only backoffice identity cannot authenticate as field representative accidentally.
- [x] password hash/secret never returned by Representative API.
- [x] inactive representative cannot field-login at canonical server auth boundary.
- [x] deactivation blocker matrix proven against real PostgreSQL.
- [x] duplicate create/idempotency proven.
- [x] debt-limit precision/nonnegative invariant proven.
- [x] concurrency/idempotency runtime behavior proven.
- [x] architecture and HTTP contract suites merged.
- [x] PostgreSQL runtime acceptance merged.

Frontend:

- [x] Representative focused component/hook/API/contract tests merged.
- [x] Representative list/search/filter/infinite-scroll tests merged.
- [x] add/edit/password/lifecycle tests merged.
- [x] capability-gated action tests merged.
- [x] Arabic/English translation resources merged.
- [x] password UTF-8 byte validation merged/tested.
- [ ] Final owner/browser acceptance is still pending as an owner checkpoint.

Field integration:

- [ ] newly created representative can login in the real Flutter client.
- [ ] representative can receive route/work session under existing Dispatch rules in the final FIELD/Flutter acceptance pass.
- [ ] deactivate/reset/logout behavior is accepted end-to-end in the real FIELD client.
- [ ] reactivate restores allowed FIELD login without creating duplicate profile/sidecar/map.

Owner acceptance:

- [ ] Functional behavior accepted.
- [ ] Arabic wording accepted.
- [ ] Table density accepted.
- [ ] Add form accepted.
- [ ] Edit/actions drawer accepted.
- [ ] No unnecessary steps identified.

**Gate:**

- [ ] **REPRESENTATIVES V1 COMPLETE + OWNER ACCEPTED**

**Only after this gate may Vehicles implementation start.**

---

# 13. Vehicles — domain contract freeze

A Vehicle is company-wide operational master data. It is not a user and never authenticates.

Current useful V1 concepts to preserve unless code review proves otherwise:

- [ ] `company_id` tenant authority.
- [ ] stable vehicle ID.
- [ ] plate number, unique per company.
- [ ] vehicle type (optional/basic).
- [ ] current mileage if already useful.
- [ ] next oil change if retained as a basic existing field, without expanding to fleet-maintenance product scope.
- [ ] license expiry date if retained as a basic existing field.
- [ ] maintenance status (`Active` / `In_Maintenance` or final normalized equivalent).
- [ ] active/inactive lifecycle state.
- [ ] version/timestamps according to project convention.

Explicit non-goals for V1:

- [ ] no GPS tracking.
- [ ] no fuel management.
- [ ] no advanced maintenance scheduling/work orders.
- [ ] no fleet cost accounting.
- [ ] no permanent representative assignment.
- [ ] no permanent warehouse ownership.
- [ ] no branch selector/ownership.

---

# 14. Vehicles — Inventory custody contract

This is the most important backend integration rule for Vehicles.

- [ ] Vehicle master remains owned by Fleet/Dispatch domain.
- [ ] Inventory remains owner of stock truth.
- [ ] Each usable vehicle receives/links to exactly one authoritative active `InventoryLocation` of type `VEHICLE` according to the existing inventory contract.
- [ ] Vehicle creation must create/link that `VEHICLE` location **atomically**; operator must not manually create the location in another page.
- [ ] Repeated create/retry must not create duplicate Vehicle locations.
- [ ] Vehicle location must remain tenant-scoped and uniquely attributable to the vehicle.
- [ ] UI uses business wording such as `عهدة السيارة جاهزة`; it does not expose raw InventoryLocation mechanics.
- [ ] Stock moves to/from the vehicle only through Inventory transfer/movement authority.
- [ ] Vehicle CRUD never mutates `InventoryBalance` directly.
- [ ] Vehicle deactivation must not erase or orphan inventory history/custody.

---

# 15. Vehicles — capability and security model

Proposed capability family; finalize against the global permission catalog:

- [ ] vehicle read capability.
- [ ] vehicle create/update/lifecycle management capability.

Rules:

- [ ] Company Owner allowed automatically through owner authority.
- [ ] Backoffice roles may receive vehicle capabilities.
- [ ] Field representatives cannot access Dashboard vehicle administration endpoints.
- [ ] Same-company tenant enforcement on every query/mutation.
- [ ] Cross-company IDs fail closed.
- [ ] No authorization based on `is_admin`.
- [ ] Audit vehicle create/update/state changes.
- [ ] Idempotent mutation behavior for create/state transitions following project conventions.

---

# 16. Vehicles — backend service/API design

## 16.1 Module ownership

- [ ] Dedicated Vehicles administration service/module; avoid growing `dispatch.py` into CRUD authority.
- [ ] Dispatch consumes Vehicle public contract.
- [ ] Inventory contract is called for VEHICLE location creation/linking.
- [ ] Do not duplicate inventory-location tables or stock logic in Fleet/Dispatch.

## 16.2 List/read contract

- [ ] Tenant-scoped vehicle list.
- [ ] Search by plate number and type as appropriate.
- [ ] Filter active/inactive and operational/maintenance status.
- [ ] Cursor pagination/infinite-scroll compatible contract.
- [ ] Stable sort; active/usable first by default.
- [ ] Return custody-location readiness summary without heavy stock joins.

## 16.3 Create contract

- [ ] Validate/normalize plate number without destroying meaningful format.
- [ ] Enforce company-scoped plate uniqueness.
- [ ] Validate optional basic fields.
- [ ] Create Vehicle + linked VEHICLE InventoryLocation atomically.
- [ ] Idempotency/request ID prevents duplicates.
- [ ] Audit creation.

## 16.4 Update contract

- [ ] Minimal-diff update.
- [ ] Version/concurrency protection where applicable.
- [ ] Plate uniqueness maintained.
- [ ] Maintenance status validated against finite enum/state contract.
- [ ] Updating vehicle does not replace/create a second InventoryLocation.

## 16.5 Deactivate/reactivate contract

Before implementation, inspect current Dispatch/WorkSession/Inventory constraints and define exact blockers.

At minimum evaluate:

- [ ] active/waiting/postponed route using vehicle.
- [ ] active WorkSession tied through that route/vehicle.
- [ ] stock/custody currently held in the vehicle location.
- [ ] pending/in-flight transfers involving vehicle location.
- [ ] reconciliation/settlement requirements.
- [ ] inventory locks or other explicit current invariants.

Rules:

- [ ] never silently strand stock/history.
- [ ] return clear business blocker message telling operator what must be completed.
- [ ] no hard delete.
- [ ] reactivation reuses the same vehicle and same valid inventory location; no duplicate location.

---

# 17. Vehicles — Dashboard list/table UX

Recommended compact columns:

- [ ] row number/identity indicator if useful.
- [ ] plate number.
- [ ] vehicle type.
- [ ] active/inactive state.
- [ ] maintenance/operational status.
- [ ] custody readiness indicator.
- [ ] actions.

Rules:

- [ ] Search plate/type.
- [ ] Filter all / ready-active / in maintenance / inactive, with final wording based on actual state model.
- [ ] No raw location ID shown.
- [ ] No warehouse assignment column, because vehicle is company-wide.
- [ ] Active/usable vehicles first by default.
- [ ] Same pagination/search/error/keyboard quality as Representatives.

---

# 18. Vehicles — Add Vehicle flow

Initial form stays minimal:

- [ ] plate number.
- [ ] vehicle type if useful.
- [ ] operational/maintenance status with safe default.
- [ ] mileage/license fields only if their current V1 value justifies keeping them visible; do not turn form into fleet-management software.
- [ ] active by default when appropriate.

Not shown:

- [ ] no branch selector.
- [ ] no warehouse selector.
- [ ] no representative selector.
- [ ] no manual InventoryLocation setup.

On save:

- [ ] backend creates Vehicle and custody location atomically.
- [ ] UI reports a simple success.
- [ ] newly created vehicle becomes selectable by Dispatch according to existing route rules.

---

# 19. Vehicles — Edit/details/actions UX

- [ ] Compact drawer/action surface consistent with Representatives.
- [ ] Edit plate/type/allowed basic fields.
- [ ] Change maintenance status with clear wording.
- [ ] Deactivate/reactivate with blocker feedback.
- [ ] Show `عهدة السيارة جاهزة` / equivalent readiness state, not technical inventory jargon.
- [ ] No hard-delete control.
- [ ] Do not expose stock-management controls here; link/navigate to Inventory only if a real operator need is accepted later.

---

# 20. Vehicles — Dispatch integration acceptance

- [ ] Dispatch vehicle selectors read from canonical Vehicle admin source.
- [ ] Only same-company active/eligible vehicles are assignable.
- [ ] In-maintenance/inactive vehicle rules are enforced by backend, not selector filtering alone.
- [ ] Route creation keeps explicit source warehouse/location independent from vehicle master identity.
- [ ] Active route uniqueness per vehicle remains intact.
- [ ] WorkSession requires valid route + vehicle + vehicle InventoryLocation as existing business invariant requires.
- [ ] Existing loading/launch/reconciliation logic continues to work with the newly administered Vehicle records.
- [ ] No duplicate vehicle-location mapping after retry/reactivation.

---

# 21. Vehicles — i18n/accessibility/acceptance gates

Backend/security:

- [ ] create/read/update/deactivate/reactivate same-company vehicle.
- [ ] cross-company blocked.
- [ ] capability enforcement proven.
- [ ] atomic vehicle + location creation proven.
- [ ] duplicate plate/retry behavior proven.
- [ ] active-route/work-session blocker proven.
- [ ] stock/transfer safety blocker proven according to current invariants.
- [ ] reactivation reuses vehicle location.

Frontend:

- [ ] TypeScript/build pass.
- [ ] list/search/filter pass.
- [ ] add/edit/state flows pass.
- [ ] RTL/LTR/keyboard/focus pass.
- [ ] phone-width usability pass.
- [ ] real-backend browser acceptance for critical flow.

Dispatch/Inventory:

- [ ] created vehicle selectable in Dispatch.
- [ ] route can use explicit warehouse + vehicle independently.
- [ ] vehicle inventory location recognized by live inventory/transfer/reconciliation flows.
- [ ] inactive/maintenance vehicle cannot bypass backend rules by direct API.

Owner acceptance:

- [ ] Functional behavior accepted.
- [ ] Arabic wording accepted.
- [ ] table density accepted.
- [ ] add form accepted.
- [ ] edit/actions experience accepted.
- [ ] no unnecessary steps identified.

**Gate:**

- [ ] **VEHICLES V1 COMPLETE + OWNER ACCEPTED**

---

# 22. Final integrated page acceptance

Only after both individual gates pass:

- [x] Sidebar entry exists and is capability-gated for Representatives.
- [x] `المندوبون` tab opens by intended default.
- [ ] `السيارات` tab opens as an implemented feature — currently intentionally disabled/gated.
- [ ] Search/filter state stays local to each tab once Vehicles is implemented.
- [ ] Primary action changes correctly per tab once Vehicles is implemented.
- [ ] Representative and Vehicle APIs have no duplicated ownership logic once Vehicles exists.
- [x] No Branch UI appears in the Representative page for V1.
- [x] No mandatory warehouse ownership appears on Representative master records.
- [x] Company Owner can perform required Representative management operations.
- [x] Delegated Backoffice roles can be restricted by Representative capabilities.
- [x] Field Representative cannot enter Dashboard Representative management through FIELD identity.
- [ ] Representative created here can login to the real Flutter client and receive Dispatch work — final FIELD/Flutter acceptance pending.
- [ ] Vehicle created here has valid custody location and can be used by Dispatch — Vehicles not started.
- [x] Representative tenant isolation is proven.
- [x] Representative audit/idempotency evidence exists for mutations.
- [x] No Representative hard-delete path leaves broken history.
- [x] Representative UI strings are i18n-backed.
- [x] No new Representative mega-file/god-hook introduced.
- [ ] `RUN.txt` closure is deferred until each actual V1 item is truly complete.

**Final gate:**

- [ ] **REPRESENTATIVES + VEHICLES ADMINISTRATION V1 DONE**

---

# 23. Implementation order / branch discipline

Use one clean task branch at a time from latest `main`; merge only at stable checkpoints.

Current checkpoints:

1. [x] Identity/authorization foundation completed and merged.
2. [x] Representatives backend/domain contract completed and merged.
3. [x] Representatives Dashboard implementation completed and merged.
4. [ ] Representatives FIELD/Flutter compatibility integration acceptance — separate worker in progress.
5. [ ] **Representative owner-acceptance checkpoint; merge/cleanup if stable.**
6. [ ] Vehicles backend/domain + InventoryLocation integration — NOT STARTED.
7. [ ] Vehicles Dashboard implementation — NOT STARTED.
8. [ ] Vehicles Dispatch/Inventory integration + acceptance — NOT STARTED.
9. [ ] **Vehicle owner-acceptance checkpoint; merge/cleanup if stable.**
10. [ ] Final integrated page acceptance and `RUN.txt` closure.

Rules:

- [x] Analyze current code and authority before writing each completed Representative phase.
- [x] Use focused tests that prove the identified risk; do not replace analysis with broad random testing.
- [x] GitHub-first validation used for this closure; no Remote Desktop dependency.
- [ ] Do not carry temporary compatibility code past the separately approved migration that supersedes it.
- [x] Every Representative completion item changed to `[x]` only with merged evidence.
- [x] No incomplete Representative architectural migration was merged merely to reduce branch age.

---

# 24. Explicit non-goals / future-ready boundaries

Not part of this V1 plan unless separately approved:

- [ ] Branch switcher or branch-scoped page mode.
- [ ] Branch-owned Representatives/Vehicles.
- [ ] permanent warehouse ownership for Representatives/Vehicles.
- [ ] HR/payroll/attendance/commission management.
- [ ] representative performance analytics beyond later Reports scope.
- [ ] GPS/telematics.
- [ ] fuel management.
- [ ] advanced fleet maintenance/work orders/cost accounting.
- [ ] vehicle-to-driver permanent pairing.
- [ ] multi-company user identities.

Future expansion must be possible by adding explicit optional organizational assignments/scopes without changing Company as the tenant boundary or corrupting current company-wide master identities.

---

# Mandatory implementation boundaries — Representatives & Vehicles

This section is a hard implementation constraint, not a UI suggestion.

## Existing backend reality

- The project already contains substantial operational Representative logic: Flutter `/driver/*` workflows, sessions, visits, sales/returns-related behavior, transfers, reconciliation, Dispatch assignment, and route context.
- The project already contains substantial vehicle operational logic: `Vehicle` master model, Dispatch assignment, vehicle inventory/custody locations, live stock, transfers, reconciliation, and stocktake integration.
- Clean company-master administration modules and Dashboard UX now exist for Representatives. Vehicle administration remains intentionally not started.
- Legacy `wa_backend/api/driver.py` and `wa_backend/api/dispatch.py` remain large operational compatibility surfaces. New administration logic MUST NOT be piled into them.

## Backend target structure

Representative administration now lives under the dedicated domain/module boundary:

`wa_backend/domains/representatives/`

with responsibility-focused contracts, repository/query, management, lifecycle, and credential modules, plus thin HTTP routes under `wa_backend/api/representatives/`.

New vehicle administration must similarly use a dedicated boundary when that phase is approved, for example:

`wa_backend/domains/vehicles/`

with separated schemas, repository/query logic, lifecycle/policy, service orchestration, and inventory-custody integration. The Dashboard CRUD router must not become part of `dispatch.py`.

Exact filenames may be adjusted by the technical lead to match existing repository conventions, but responsibility boundaries are mandatory. A worker may NOT independently change this architecture; any proposed alternative must follow `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md` escalation.

## Existing operational logic is preserved, not duplicated

- Do not rewrite working Dispatch/Flutter/Inventory business rules from scratch.
- Administration modules own master-data management.
- Dispatch continues to own route/assignment workflow.
- Inventory continues to own stock quantity and custody movement.
- Shared identity/auth owns credential/session/authentication infrastructure.
- Representatives domain owns Field Representative profile/lifecycle business rules.
- Vehicles domain will own vehicle master/lifecycle business rules when Vehicles starts.
- Integrations call authoritative services; they must not copy validation logic.

## File-size and function-design guardrails

- No new mega-file.
- No new god-function performing validation + authorization + SQL + auditing + side effects + response construction in one block.
- Routers remain thin.
- Complex queries get named repository/query helpers.
- Domain state changes go through named service/policy operations.
- Cross-domain effects use explicit service boundaries.
- If implementation starts materially enlarging `driver.py` or `dispatch.py`, STOP and redesign the placement before continuing.

## Frontend target structure

The page shell and both tabs remain separated:

`dashboard/src/pages/representatives-vehicles/`

- page shell / tabs / page-level orchestration;
- `representatives/` for list, filters, drawer/form, actions, contracts/hooks;
- `vehicles/` remains gated until its later approved phase;
- shared page-only primitives only when truly shared.

Do not create one giant `RepresentativesVehiclesPage.tsx` containing all API calls, forms, table logic, validation, drawers, and both tabs.

## Acceptance condition

The merged Representative administration implementation now satisfies the architecture, HTTP contract, Dashboard, PostgreSQL runtime, tenant-isolation, lifecycle/reset, and idempotency/concurrency gates. Representatives are **not yet owner-complete** because final FIELD/Flutter compatibility acceptance and owner acceptance remain pending. Vehicles must remain gated and unimplemented until those two final Representative gates close.
