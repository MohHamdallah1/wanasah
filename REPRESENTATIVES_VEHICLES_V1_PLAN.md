# Wanasah Representatives & Vehicles V1 Plan

## Build Representatives completely first, then Vehicles, on top of the canonical identity/authorization foundation

**Status:** PLANNED — NOT YET IMPLEMENTED  
**Owner decision date:** 2026-10-10  
**Execution rule:** Representatives must be completed and owner-accepted before Vehicles implementation starts.  
**Hard prerequisite:** `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md` must be completed to the point where Backoffice and Field Representative identities are cleanly separated and capability-based authorization is authoritative.  
**Canonical references:** `ARCHITECTURE.md`, `.rules`, `AGENTS.md`, `RUN.txt`, `V1_SCOPE_FREEZE.md`, `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md`.

---

# 0. Frozen owner decisions and scope

- [ ] The tenant/security boundary is **Company**.
- [ ] V1 operational UX is one company context with **one or many warehouses**.
- [ ] V1 does **not** require a global Branch switcher, Branch-scoped representative management, Branch-scoped vehicle management, or Branch ownership of company master data.
- [ ] Existing Branch schema/readiness may remain for future expansion, but Representatives/Vehicles V1 must not depend on it.
- [ ] Products are company-wide master data.
- [ ] Zones/territories are company-wide master data.
- [ ] Shops/customers are company-wide master data.
- [ ] Field Representatives are company-wide master data.
- [ ] Vehicles are company-wide master data.
- [ ] Representatives and Vehicles are **not permanently owned by one warehouse**.
- [ ] Source warehouse is chosen by the concrete operational workflow/route/load, not by representative/vehicle identity.
- [ ] A representative can work from a different authorized source warehouse on another route/day without changing his master identity.
- [ ] A vehicle can be used from a different authorized source warehouse on another route/day without changing its master identity.
- [ ] Backoffice users and Company Owner belong to Dashboard identity/authorization and are **not managed by this page**.
- [ ] Field Representatives belong to Flutter field identity and are **the only human accounts managed by the Representatives tab**.
- [ ] Field Representatives must not receive Dashboard access.
- [ ] Vehicles are non-human operational assets and never authenticate.
- [ ] Dashboard complexity must remain low; backend owns validation, isolation, authorization, lifecycle, audit, idempotency, custody, and route safety.
- [ ] No hard delete for Representatives or Vehicles in V1. Lifecycle uses active/inactive and controlled state transitions so history remains valid.
- [ ] Arabic-first UI, i18n-ready from the first implementation, RTL/LTR safe, Western digits, keyboard friendly.
- [ ] No mega-file/god-hook. Page shell, representatives, and vehicles stay in separate feature folders/modules.
- [ ] Existing Dispatch/Inventory business authority must be reused; do not create duplicate route, warehouse, custody, permission, or stock truth.

---

# 1. Final page concept

## 1.1 Navigation

Recommended current sidebar label:

**المندوبون والسيارات**

Page tabs:

1. **المندوبون**
2. **السيارات**

Execution behavior:

- [ ] Build the shared page shell and the **Representatives** tab first.
- [ ] Vehicles tab may exist as a visible gated/disabled tab while Representatives are unfinished, if that is the cleanest UX, but no Vehicle workflow is implemented before the Representatives acceptance gate.
- [ ] After the owner accepts the Representatives behavior and UI, mark the Representatives completion gate `[x]` and begin Vehicles.
- [ ] Page/tab naming remains presentation-level and may be renamed later without changing domain contracts.

## 1.2 Page UX constitution

- [ ] Use the same compact Wanasah shell language as Products/Inventory/Suppliers.
- [ ] Compact top bar; no oversized dashboard cards.
- [ ] Primary action changes by tab: `إضافة مندوب` or `إضافة سيارة`.
- [ ] Search/filter controls stay close to the table.
- [ ] Prefer infinite scrolling / cursor pagination over fixed 50-row paging where backend contract supports it.
- [ ] Sticky table header.
- [ ] Internal page/table scrolling; avoid nested uncontrolled scrollbars.
- [ ] Row actions use a compact actions trigger and/or detail drawer consistent with the accepted Wanasah interaction pattern.
- [ ] Do not expose internal terms such as principal, RLS, role join, InventoryLocation, or FK to normal operators.
- [ ] Backend errors must be translated into clear business Arabic/English messages.
- [ ] Focus starts on the first meaningful field when forms/drawers open.
- [ ] `Escape` closes dismissible overlays, `Tab/Shift+Tab` remain trapped correctly, Enter submits where safe.
- [ ] No hidden authorization assumptions in the UI; disabled/hidden buttons are UX only, backend remains authoritative.

---

# 2. Prerequisite gate — Identity & authorization foundation

**Do not implement Representative CRUD on top of legacy mixed `Driver` identity.**

Before Representatives implementation proceeds beyond harmless page-shell work:

- [ ] `CompanyPrincipal` (or the final canonical equivalent) is authoritative for company credentials/session identity.
- [ ] Backoffice profile/type is distinct from Field Representative profile/type.
- [ ] Dashboard login fails closed for field-only identities.
- [ ] Flutter field login fails closed for backoffice-only identities.
- [ ] Company Owner authority is explicit/system-managed.
- [ ] New permissions are capability-based, not `is_admin` based.
- [ ] Existing role/scope model is attached to Backoffice identity, not Field Representative identity by accident.
- [ ] Actor/audit references needed by administrative mutations point to the correct principal type.
- [ ] Dispatch/visit/work-session representative references point to the Field Representative identity/profile.
- [ ] No new endpoint created by this plan may depend on `is_admin` or infer representative status from `is_admin=false`.
- [ ] Authentication/session/token claims expose stable identity/channel semantics required by Dashboard and Flutter.
- [ ] Relevant migration tests from `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md` pass before Representative mutations are enabled.

**Gate:**

- [ ] **IDENTITY FOUNDATION READY FOR REPRESENTATIVES**

---

# 3. Representatives — domain contract freeze

## 3.1 Representative master identity

A Field Representative is a company-wide field actor. V1 data should be intentionally minimal and operationally useful.

Required/owned concepts:

- [ ] `company_id` — tenant authority; never client-trusted across tenants.
- [ ] stable representative/profile ID.
- [ ] linked company principal/credential identity.
- [ ] full name.
- [ ] username/login identifier according to canonical company credential rules.
- [ ] phone number (optional unless product owner later makes it mandatory).
- [ ] active/inactive lifecycle state.
- [ ] created/updated timestamps/version where the project convention requires them.
- [ ] commercial debt permission currently represented by `can_allow_debt` where still required by V1 business flow.
- [ ] maximum debt limit currently represented by `max_debt_limit`, preserving Decimal/Numeric precision and existing nonnegative invariant.

Explicitly **not identity fields**:

- [ ] no mandatory warehouse ownership.
- [ ] no mandatory branch ownership.
- [ ] no permanent vehicle assignment.
- [ ] no permanent route assignment.
- [ ] no permanent zone ownership merely to simplify UI.
- [ ] no inventory balance stored on representative profile.

Operational relationships remain owned by Dispatch/Inventory workflows.

## 3.2 Representative lifecycle

- [ ] Create representative.
- [ ] Read/list/search representatives.
- [ ] Edit allowed profile fields.
- [ ] Deactivate representative.
- [ ] Reactivate representative.
- [ ] Reset/change credentials through the canonical credential service.
- [ ] No hard delete endpoint/UI.
- [ ] Deactivation must preserve route/visit/sales/audit history.
- [ ] Deactivation must not silently rewrite historical records.
- [ ] Backend must block or explicitly handle deactivation if an active work session/route creates an unsafe state.
- [ ] Exact blocking rules must be derived from current Dispatch/WorkSession invariants before implementation, not invented in the UI.
- [ ] Reactivation must not create duplicate identities or duplicate credentials.

---

# 4. Representatives — capability and security model

Proposed capability family; exact names must be finalized against the global permission catalog before migration/seed work:

- [ ] representative read capability.
- [ ] representative create/update/lifecycle management capability.
- [ ] representative credential-reset capability if separated from general management.

Rules:

- [ ] Company Owner resolves to all company representative-management capabilities.
- [ ] Backoffice users may receive representative capabilities through Roles.
- [ ] Field Representatives never receive Dashboard representative-management capabilities merely because they are representatives.
- [ ] All reads/mutations are tenant-scoped in backend queries.
- [ ] Cross-company representative IDs return fail-closed behavior; never leak existence/details.
- [ ] Direct API calls without capability fail even when a UI control is hidden.
- [ ] Credential mutation requires stronger confirmation/policy if the canonical auth design requires it.
- [ ] Password hash is never returned by any API or log.
- [ ] Username uniqueness follows the canonical company identity rule.
- [ ] Rate limiting/login attempt protections stay in the shared credential/auth infrastructure.

---

# 5. Representatives — backend service/API design

## 5.1 Ownership and module boundaries

- [ ] Create/identify a dedicated Representatives domain/application module; do not grow `dispatch.py` or an auth mega-file with CRUD logic.
- [ ] Credential creation/reset delegates to the canonical identity/auth service.
- [ ] Dispatch consumes representative public contracts; it does not own Representative CRUD.
- [ ] Inventory does not own Representative CRUD.
- [ ] Keep DTO/schema/service/repository concerns separated according to existing architecture conventions.

## 5.2 List/read contract

- [ ] Tenant-scoped representative list endpoint.
- [ ] Cursor-based pagination if consistent with current page architecture.
- [ ] Bounded page size.
- [ ] Search by normalized name, username, and phone as appropriate.
- [ ] Filter active/inactive/all.
- [ ] Stable deterministic sort; default active representatives first, then a predictable secondary key.
- [ ] Return only fields required by UI.
- [ ] Include compact operational summary only if it can be obtained without coupling list reads to heavy Dispatch queries.
- [ ] Avoid N+1 queries.
- [ ] Index search/sort paths if query plans show need.

## 5.3 Create contract

- [ ] Validate company ownership server-side.
- [ ] Validate full name and username using shared limits/normalization.
- [ ] Validate phone with a stable minimal contract; do not over-normalize destructively.
- [ ] Validate password through canonical password policy.
- [ ] Validate debt permission/limit invariants.
- [ ] Create principal + Field Representative profile atomically.
- [ ] Never create a Backoffice profile for a field representative.
- [ ] Ensure field access channel is explicit.
- [ ] Idempotency/request ID for duplicate-submit protection following project conventions.
- [ ] Audit event records actor, company, representative target, and meaningful changed data without secrets/passwords.

## 5.4 Update contract

- [ ] Optimistic/version concurrency according to project convention where applicable.
- [ ] Minimal-diff updates; omitted values are not silently reset.
- [ ] Username changes, if allowed, pass credential uniqueness/security rules.
- [ ] Debt settings validated atomically.
- [ ] Audit before/after meaningful business changes without exposing credentials.

## 5.5 Credential-reset contract

- [ ] Dedicated explicit operation, not generic profile PATCH carrying raw password fields casually.
- [ ] Authorization capability checked independently if policy requires.
- [ ] Password policy reused.
- [ ] Existing sessions/refresh tokens are revoked or preserved according to canonical security policy; decision must be explicit and tested.
- [ ] Response never echoes password/hash.
- [ ] Audit records reset event but never secret material.

## 5.6 Deactivate/reactivate contract

- [ ] Deactivate by explicit action endpoint/service.
- [ ] Reactivate by explicit action endpoint/service.
- [ ] No physical delete.
- [ ] Active work-session/route safety rules enforced in backend.
- [ ] Existing history remains readable.
- [ ] Login fails for inactive representative.
- [ ] Repeated same lifecycle request is idempotent or returns a clear stable business response.

---

# 6. Representatives — Dispatch/Flutter integration protection

This phase is required because Representatives are not just Dashboard records; they must remain valid field actors.

- [ ] Replace any Dispatch representative discovery still based on `is_admin=false` with Field Representative profile/type queries.
- [ ] Route assignment accepts only active Field Representatives from the same company.
- [ ] WorkSession creation accepts only active Field Representatives from the same company.
- [ ] Visit ownership references the canonical representative identity/profile.
- [ ] Sales/returns/collection flows that attribute work to a representative keep the same business meaning after migration.
- [ ] Flutter `/driver/login` legacy path is migrated/aliased according to the identity plan, with no ambiguous cross-channel login.
- [ ] Flutter persisted `driver_id` is migrated to the final representative/principal contract without corrupting existing local state.
- [ ] Logout/session invalidation works after representative deactivate/reset.
- [ ] Offline retry/idempotency payloads continue to attribute the correct representative.
- [ ] Realtime authorization recognizes Field Representative identity explicitly and does not depend on `is_admin`.
- [ ] No new Dashboard-only capability leaks into Flutter tokens.

---

# 7. Representatives — Dashboard page structure

Recommended feature boundary:

```text
pages/representatives-vehicles/
  RepresentativesVehiclesPage.tsx
  representatives/
    ...representative list/search/form/drawer/actions...
  vehicles/
    ...vehicle implementation later...
```

Exact names may follow current repository conventions, but:

- [ ] one shared page shell.
- [ ] Representatives and Vehicles have separate submodules.
- [ ] no single giant component.
- [ ] no one hook owning fetch/list/form/password/lifecycle/vehicle behavior together.
- [ ] shared UI extracted only when genuinely shared; avoid premature abstraction.

---

# 8. Representatives — list/table UX

Recommended compact columns:

- [ ] row number/identity indicator if useful.
- [ ] representative name.
- [ ] username.
- [ ] phone.
- [ ] status.
- [ ] compact commercial/debt indicator if useful and not visually noisy.
- [ ] actions.

Rules:

- [ ] Search input Arabic-aligned and visually consistent with accepted Wanasah search bars.
- [ ] Search name/username/phone.
- [ ] Status filter: all / active / inactive.
- [ ] Active representatives first by default.
- [ ] Western digits.
- [ ] Clear empty state.
- [ ] Clear error + retry state.
- [ ] No loader flash that replaces settled content unnecessarily.
- [ ] Infinite scroll/cursor loading must not duplicate rows or lose selection.
- [ ] Keyboard access to action menu; arrow/wrap behavior consistent with project conventions where supported.
- [ ] Row/action focus restored predictably after drawer/modal close.

---

# 9. Representatives — Add Representative flow

The operator should reach a usable representative with the fewest safe steps.

## 9.1 Initial form fields

- [ ] Full name.
- [ ] Username.
- [ ] Phone number.
- [ ] Initial password / credential setup according to canonical auth policy.
- [ ] Active by default unless security policy says otherwise.
- [ ] Debt permission control only if business flow requires it for the representative.
- [ ] Maximum debt limit shown/enabled only when logically applicable.

Not shown:

- [ ] no branch selector.
- [ ] no mandatory warehouse selector.
- [ ] no vehicle selector.
- [ ] no route selector.
- [ ] no internal role/permission selector for the representative Dashboard access, because the representative is Flutter-only.

## 9.2 Form UX

- [ ] Focus first field on open.
- [ ] Clear inline validation.
- [ ] Enter submits when safe.
- [ ] Prevent accidental double submit.
- [ ] Backend remains source of truth for uniqueness/conflicts.
- [ ] Success closes form and inserts/refreshes row without full page reload.
- [ ] Newly created representative can immediately authenticate to Flutter when active and credentials are valid.

---

# 10. Representatives — Edit/details/actions UX

Preferred behavior:

- [ ] Row action opens a clean right-side drawer or compact action surface consistent with accepted Wanasah patterns.
- [ ] View identity/basic info without exposing secrets.
- [ ] Edit name/phone/allowed fields.
- [ ] Username change only if the final identity policy permits it.
- [ ] Separate `تغيير/إعادة تعيين كلمة المرور` action.
- [ ] Separate deactivate/reactivate action with clear consequences.
- [ ] Debt settings grouped in business language, not technical flags.
- [ ] No hard-delete button.
- [ ] Show active operational conflict in clear language when deactivation is blocked.
- [ ] Do not dump route history/visit history into this drawer unless later requested; keep V1 administration focused.

---

# 11. Representatives — i18n, accessibility, and resilience

- [ ] All new strings use translation keys from first commit; no permanent hardcoded Arabic-only implementation.
- [ ] Arabic default RTL.
- [ ] English LTR validated.
- [ ] Western digits/currency formatting uses canonical locale helpers.
- [ ] Inputs have labels and accessible names.
- [ ] Errors announced appropriately.
- [ ] Focus trap is correct.
- [ ] Escape handling is correct.
- [ ] No focus theft during background refetch.
- [ ] Phone-width layout remains usable.
- [ ] Long names/usernames do not break table/drawer layout.
- [ ] API 401/403/409/422/5xx states map to useful user feedback.

---

# 12. Representatives — focused acceptance gates

Code analysis precedes tests; tests prove the identified contracts.

Backend/security:

- [ ] create/read/update/deactivate/reactivate same-company representative.
- [ ] cross-company read/mutation blocked.
- [ ] missing capability blocked.
- [ ] Company Owner allowed.
- [ ] field representative cannot access Dashboard management API.
- [ ] Dashboard-only backoffice identity cannot authenticate as field representative accidentally.
- [ ] password hash/secret never returned/logged.
- [ ] inactive representative cannot field-login.
- [ ] active-route/work-session deactivation rule proven.
- [ ] duplicate create/idempotency proven.
- [ ] debt-limit precision/nonnegative invariant proven.
- [ ] Dispatch accepts canonical representative and rejects backoffice principal.

Frontend:

- [ ] TypeScript/build pass.
- [ ] Representative list/search/filter pass.
- [ ] add/edit/password/lifecycle flows pass.
- [ ] capability-gated actions behave correctly.
- [ ] RTL/LTR + keyboard/focus pass.
- [ ] browser acceptance against real backend for the critical flow.

Field integration:

- [ ] newly created representative can login in Flutter.
- [ ] representative can receive route/work session under existing Dispatch rules.
- [ ] deactivate blocks login safely.
- [ ] reactivate restores allowed login without creating duplicate profile.

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

- [ ] Sidebar entry is clear and consistent.
- [ ] `المندوبون` tab opens correctly by intended default.
- [ ] `السيارات` tab opens without cross-tab state leakage.
- [ ] Search/filter state stays local to each tab unless intentionally designed otherwise.
- [ ] Primary action changes correctly per tab.
- [ ] Representative and Vehicle APIs have no duplicated ownership logic.
- [ ] No Branch UI appears in this page for V1.
- [ ] No mandatory warehouse ownership appears on Representative/Vehicle master records.
- [ ] Company Owner can perform all required management operations.
- [ ] Delegated Backoffice roles can be restricted by capabilities.
- [ ] Field Representative cannot enter Dashboard management.
- [ ] Representative created here can login to Flutter and receive Dispatch work.
- [ ] Vehicle created here has valid custody location and can be used by Dispatch.
- [ ] Tenant isolation proven for both domains.
- [ ] Audit and idempotency evidence exists for mutations.
- [ ] No hard-delete path leaves broken history.
- [ ] All new UI strings are i18n-backed.
- [ ] No new mega-file/god-hook introduced.
- [ ] `RUN.txt` is updated only when each actual V1 item is truly complete.

**Final gate:**

- [ ] **REPRESENTATIVES + VEHICLES ADMINISTRATION V1 DONE**

---

# 23. Implementation order / branch discipline

Use one clean task branch at a time from latest `main`; merge only at stable checkpoints.

Recommended checkpoints:

1. [ ] Identity/authorization migration plan completed and merged.
2. [ ] Representatives backend/domain contract.
3. [ ] Representatives Dashboard implementation.
4. [ ] Representatives Flutter/Dispatch integration + acceptance.
5. [ ] **Representative owner-acceptance checkpoint; merge/cleanup if stable.**
6. [ ] Vehicles backend/domain + InventoryLocation integration.
7. [ ] Vehicles Dashboard implementation.
8. [ ] Vehicles Dispatch/Inventory integration + acceptance.
9. [ ] **Vehicle owner-acceptance checkpoint; merge/cleanup if stable.**
10. [ ] Final integrated page acceptance and `RUN.txt` closure.

Rules:

- [ ] Analyze current code and authority before writing each phase.
- [ ] Use focused tests that prove the identified risk; do not replace analysis with broad random testing.
- [ ] Keep Remote Desktop Commander usage minimal; GitHub-first for code review/edit/review, local runtime only when needed.
- [ ] Do not carry temporary compatibility code past the phase that needs it.
- [ ] Every finished checklist item changes from `[ ]` to `[x]` only with evidence.
- [ ] Do not merge incomplete architectural migrations merely to reduce branch age.

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

- The project already contains substantial operational representative logic: Flutter `/driver/*` workflows, sessions, visits, sales/returns-related behavior, transfers, reconciliation, dispatch assignment, and route context.
- The project already contains substantial vehicle operational logic: `Vehicle` master model, Dispatch assignment, vehicle inventory/custody locations, live stock, transfers, reconciliation, and stocktake integration.
- What is largely missing is a clean company-master administration module for Representatives and Vehicles (create/list/edit/lifecycle/password administration and the corresponding Dashboard experience).
- Legacy `wa_backend/api/driver.py` and `wa_backend/api/dispatch.py` are already very large operational surfaces. New administration logic MUST NOT be piled into them.

## Backend target structure

After the identity/authorization prerequisite is complete, new representative administration should live under a dedicated domain/module boundary, for example:

`wa_backend/domains/representatives/`

with small responsibility-focused modules such as:

- `models.py` or canonical profile model placement according to the identity migration contract;
- `schemas.py` — request/response contracts;
- `repository.py` — tenant-scoped persistence/query operations;
- `service.py` — application orchestration;
- `policy.py` — representative-specific domain rules/lifecycle rules;
- `credentials.py` — field-account password/reset operations if not owned by the shared identity domain;
- `audit.py` or shared audit integration where appropriate.

HTTP routes should be thin and placed in a dedicated representative administration router rather than added to the field `driver.py` router.

New vehicle administration should similarly use a dedicated boundary, for example:

`wa_backend/domains/vehicles/`

with separated schemas, repository/query logic, lifecycle/policy, service orchestration, and inventory-custody integration. The Dashboard CRUD router must not become part of `dispatch.py`.

Exact filenames may be adjusted by the technical lead to match existing repository conventions, but the responsibility boundaries are mandatory. A worker may NOT independently change this architecture; any proposed alternative must follow `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md` escalation.

## Existing operational logic is preserved, not duplicated

- Do not rewrite working Dispatch/Flutter/Inventory business rules from scratch.
- Administration modules own master-data management.
- Dispatch continues to own route/assignment workflow.
- Inventory continues to own stock quantity and custody movement.
- Shared identity/auth owns credential/session/authentication infrastructure.
- Representatives domain owns field-representative profile/lifecycle business rules.
- Vehicles domain owns vehicle master/lifecycle business rules.
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

The page shell and both tabs remain separated. Prefer dedicated feature folders, for example:

`dashboard/src/pages/representatives-vehicles/`

- page shell / tabs / page-level orchestration;
- `representatives/` for list, filters, drawer/form, actions, contracts/hooks;
- `vehicles/` for its later phase;
- shared page-only primitives only when truly shared.

Do not create one giant `RepresentativesVehiclesPage.tsx` containing all API calls, forms, table logic, validation, drawers, and both tabs.

## Acceptance condition

Representatives are not considered complete merely because the UI works. Completion requires clean module ownership, no new coupling into legacy mega-files, preservation of existing Flutter/Dispatch behavior, and focused regression coverage. Vehicles start only after Representatives are owner-accepted as required by this plan.
