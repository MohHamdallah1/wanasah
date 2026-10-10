# Identity Client Login Cutover Contract

**Status:** CANONICAL FOR CLIENT AUTH CUTOVER  
**Date:** 2026-10-10  
**Depends on:** `IDENTITY_AUTH_SESSION_CUTOVER_CONTRACT.md`, `IDENTITY_PHASE34_BACKFILL_CONTRACT.md`, the canonical identity schema, and the current Dashboard/Flutter login implementations.

This document freezes how the Dashboard and Flutter clients move from legacy `Driver` login identity to `CompanyPrincipal` + explicit channel/profile identity without silently changing the meaning of an existing identifier.

---

## 1. Non-negotiable identity rule

The following IDs are different concepts and must never be aliased merely for compatibility:

```text
legacy_driver_id      = legacy Driver.id only
principal_id          = CompanyPrincipal.id
backoffice_user_id    = BackofficeUser.id
representative_id     = FieldRepresentative.id
```

In particular:

- `driver_id = principal_id` is forbidden.
- `driver_id = representative_id` is forbidden as a compatibility shortcut unless the legacy `Driver` relation has already been fully removed from every consumer using that field.
- independent target-profile IDs remain independent even if values happen to match in a development database.
- token `sub` after cutover is always `principal_id`.
- field workflow ownership after its reviewed FK cutover uses `representative_id`.
- generic audit/action attribution after its reviewed FK cutover uses `principal_id`.

---

## 2. Current client facts that drive this contract

### Dashboard

The current Dashboard `/login` consumer:

- requires `token`, `refresh_token`, `company_id`, `company_code`, `driver_name`, and `driver_id`;
- treats `is_admin || dashboard_access` as Dashboard admission evidence;
- stores:
  - `admin_token`;
  - `refresh_token`;
  - `company_id`;
  - `driver_id`;
  - `company_code`;
  - `admin_name`;
- uses `is_admin` to choose the first route (`/` vs `/inventory`).

Therefore Dashboard migration must replace both the identity storage contract and the `is_admin` navigation decision. A valid Dashboard login proves Backoffice channel eligibility; initial navigation must come from persisted capabilities/Owner authority, never from `is_admin`.

### Flutter

The current Flutter `/driver/login` consumer:

- requires `token`, `refresh_token`, and `driver_id`;
- stores `auth_token`, `refresh_token`, `driver_id`, and `company_code` in secure storage;
- reconstructs `AuthAuthenticated(driverId: ...)` from stored `driver_id`;
- compares old/new `driver_id` to detect a different field user in the same company and clear session/cache state;
- exposes `getDriverId()` to field repositories;
- writes `driver_id` into at least one offline operational payload (`toggle_break`).

Therefore Flutter's current `driver_id` is not a generic login subject. It is an operational legacy field-representative identifier used by offline/session behavior. It must not be silently replaced with `principal_id`.

---

## 3. Public login URLs remain stable during V1 migration

```text
POST /login         -> DASHBOARD / BACKOFFICE
POST /driver/login  -> FIELD / FIELD_REPRESENTATIVE
POST /refresh       -> refresh the same principal/company/channel only
POST /logout        -> terminate the current company session
```

The `/driver/login` URL is a temporary naming compatibility surface. Its existence does not make legacy `Driver` the target identity model.

---

## 4. Canonical login responses

### 4.1 Dashboard canonical response

Required target fields:

```text
token
refresh_token
principal_id
backoffice_user_id
channel = DASHBOARD
principal_type = BACKOFFICE
is_company_owner
company_id
company_code
display_name
capabilities / approved capability-bootstrap contract
```

Rules:

- Dashboard admission is the successful BACKOFFICE channel authentication result.
- `is_company_owner` may describe protected Owner authority; it is not a client-created role.
- navigation/action visibility must be capability-driven.
- `is_admin` must not authorize or choose routes in the target client.
- `backoffice_user_id` is not interchangeable with `principal_id`.

### 4.2 Flutter canonical response

Required target fields:

```text
token
refresh_token
principal_id
representative_id
channel = FIELD
principal_type = FIELD_REPRESENTATIVE
company_id
company_code
display_name
```

Rules:

- Flutter session identity stores both `principal_id` and `representative_id` while those semantics are both needed.
- operational field ownership uses `representative_id` after corresponding endpoint/FK cutover.
- authentication/session ownership uses `principal_id`.
- `representative_id` is never inferred from token `sub` equality.

---

## 5. Bounded compatibility response fields

During the migration window only, Backend may additionally return:

```text
legacy_driver_id
```

If an existing client cannot be updated atomically and must temporarily receive the historical JSON name `driver_id`, then:

```text
driver_id = legacy Driver.id
```

and nothing else.

This temporary field must be resolved deterministically through the approved `identity_legacy_driver_map` bridge. It must never be populated with `principal_id` or `representative_id` simply to satisfy an old parser.

Legacy response `is_admin` may remain only until the Dashboard consumer no longer reads it. During that window it is presentation/compatibility data only and must not authorize Backend behavior.

`dashboard_access` may remain until the new Dashboard response parser is deployed, but the canonical replacement is explicit `channel=DASHBOARD` plus persisted Backoffice profile and capability/Owner bootstrap.

---

## 6. Dashboard storage cutover

### 6.1 Canonical keys

Dashboard moves to explicit storage keys:

```text
admin_token
refresh_token
company_id
company_code
principal_id
backoffice_user_id
admin_name
```

`driver_id` must be removed from Dashboard storage after all Dashboard consumers are migrated.

### 6.2 Navigation

Remove:

```text
is_admin ? '/' : '/inventory'
```

Target behavior:

1. successful `/login` establishes a DASHBOARD Backoffice session;
2. capability/Owner bootstrap is available;
3. choose the first allowed Dashboard destination through one central navigation policy;
4. no role-name or `is_admin` branch.

This policy must preserve currently authorized Inventory-only Backoffice users rather than turning Dashboard into Owner-only access.

### 6.3 Tenant switch

Existing company-change storage cleanup remains. New identity keys are tenant-scoped session state and must be overwritten/cleared with the auth session.

---

## 7. Flutter secure-storage cutover

### 7.1 Canonical keys

Target Flutter secure storage:

```text
auth_token
refresh_token
company_code
principal_id
representative_id
```

Temporary during compatibility:

```text
legacy_driver_id
```

The old `driver_id` key may remain only while old field/offline consumers still need legacy Driver identity.

### 7.2 Same-company account switch isolation

The current safety rule clearing session/cache data when a different field user logs in must be preserved.

After canonical migration compare:

```text
old representative_id != new representative_id
```

not `principal_id` and not legacy `driver_id`.

Reason: field/offline cache belongs to the FieldRepresentative operational profile.

### 7.3 Auth state

Replace ambiguous:

```text
AuthAuthenticated(driverId: ...)
```

with an explicit field-auth state carrying at minimum:

```text
principalId
representativeId
```

or an equivalent typed field-session identity object.

No later Flutter code should need to guess which kind of ID `driverId` contains.

### 7.4 Offline payloads

Offline payload fields currently named `driver_id` must be migrated only together with the Backend endpoint/domain contract that owns them.

Until that workflow is migrated, keep the historical `legacy_driver_id` value for its old contract. Do not enqueue a new `principal_id` or `representative_id` under an old `driver_id` field.

When the owning workflow is cut over:

- FIELD_REPRESENTATIVE classification -> use `representative_id` with a new explicit contract field/name;
- PRINCIPAL_ACTOR classification -> use `principal_id` with an explicit actor contract;
- never rewrite queued historical payload semantics in place without a versioned migration.

---

## 8. Refresh-session client behavior

The existing silent-refresh concurrency/lost-response behavior remains valuable and must be preserved.

At identity cutover:

- legacy refresh sessions are invalidated rather than converted;
- one clean re-login is expected;
- newly issued refresh tokens have canonical `sub=principal_id`, `company_id`, and channel/type/revision binding;
- `/refresh` may rotate only within the same principal/company/channel;
- Dashboard refresh identity comparison may continue to compare signed token `sub + company_id`; after cutover that `sub` is `principal_id`.

Client refresh code must not inspect `role`, `is_admin`, or use token claims as capability authority.

---

## 9. Required cutover order

### Stage A — Backend dual-response readiness

- [ ] New identity backfill/bridge has passed Gate 4.
- [ ] New authentication/session persistence is ready.
- [ ] `/login` and `/driver/login` can authenticate new identities.
- [ ] canonical IDs/fields are returned.
- [ ] any temporary `legacy_driver_id`/`driver_id` maps to actual legacy `Driver.id` only.
- [ ] Backend authorization no longer trusts response compatibility booleans.

### Stage B — Dashboard client migration

- [ ] parse canonical Dashboard response.
- [ ] persist `principal_id` + `backoffice_user_id`.
- [ ] remove `is_admin` admission/navigation logic.
- [ ] use capability/Owner bootstrap for routing/actions.
- [ ] remove Dashboard dependence on stored `driver_id`.
- [ ] focused login/refresh/logout/session tests pass.

### Stage C — Flutter auth identity migration

- [ ] parse/store `principal_id` + `representative_id`.
- [ ] typed auth state no longer exposes ambiguous `driverId`.
- [ ] same-company account-switch protection compares representative identity.
- [ ] refresh/logout behavior preserved.
- [ ] legacy field ID retained separately only for workflows not yet cut over.

### Stage D — Field workflow contract/FK migration

- [ ] each old field `driver_id` request/offline payload is migrated according to the reviewed FK/endpoint classification.
- [ ] queued offline records are versioned/migrated safely where required.
- [ ] no new payload uses ambiguous `driver_id`.

### Stage E — Compatibility removal

Only after Backend + Dashboard + Flutter + field workflows are accepted:

- [ ] remove login-response `driver_id`.
- [ ] remove login-response `is_admin`.
- [ ] remove `dashboard_access` if redundant.
- [ ] remove Dashboard stored `driver_id`.
- [ ] remove Flutter stored legacy `driver_id` / `legacy_driver_id` after all old workflow contracts are gone.
- [ ] remove old parser/types/tests expecting legacy fields.
- [ ] verify no active client infers authority from role/is_admin.

---

## 10. Failure rules

- A client receiving the wrong channel must fail closed.
- Missing canonical profile ID fails login/session initialization after its client stage is enabled.
- A compatibility field with no deterministic legacy mapping fails closed; do not substitute another ID type.
- Company switch isolation must run before accepting cached operational state from another company.
- Field-user switch isolation must run before reusing field/offline cache from another representative.
- Refresh rejection with 401/403 follows existing session-clearing behavior; ordinary network/server failure must not unnecessarily destroy the session.

---

## 11. Definition of done

This client migration is complete only when:

- [ ] Dashboard stores/uses explicit Backoffice identity and no longer reads `is_admin` or ambiguous `driver_id`.
- [ ] Flutter stores/uses explicit principal + representative identity and its auth state has no ambiguous `driverId` meaning.
- [ ] all field offline/request contracts have explicit ID semantics.
- [ ] `driver_id` is not used as a generic authenticated-company-user identity.
- [ ] access/refresh token subject is CompanyPrincipal.
- [ ] no client treats JWT role/is_admin claims as authority.
- [ ] legacy compatibility response/storage fields are removed.
- [ ] legacy refresh sessions cannot rotate.
- [ ] account/company switch data-isolation behavior remains intact.
