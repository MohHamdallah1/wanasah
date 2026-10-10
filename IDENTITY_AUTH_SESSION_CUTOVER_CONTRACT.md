# Identity Auth / Session Cutover Contract

**Status:** CANONICAL FOR IDENTITY CUTOVER IMPLEMENTATION
**Date:** 2026-10-10
**Depends on:** `ARCHITECTURE.md`, `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md`, `IDENTITY_PHASE1_SEMANTIC_INVENTORY.md`, `IDENTITY_PHASE2_DECISION_FREEZE.md`, `IDENTITY_PHASE2_CAPABILITY_FREEZE.md`.

This freezes the lead-owned authentication, JWT, refresh-session and access-channel contract before Runtime cutover.

## 1. Security realms

- Platform authentication remains a separate security realm and token family.
- Company authentication uses `CompanyPrincipal` as the credential root.
- Dashboard and Flutter field access are explicit, mutually exclusive V1 channels.

Canonical company channels:

```text
DASHBOARD
FIELD
```

Canonical principal types:

```text
BACKOFFICE
FIELD_REPRESENTATIVE
```

Required pairing:
- `DASHBOARD` -> active `BACKOFFICE` principal + valid active Backoffice profile.
- `FIELD` -> active `FIELD_REPRESENTATIVE` principal + valid active FieldRepresentative profile.

Wrong-channel authentication fails closed even when username/password are correct.

## 2. Public login URLs

URLs remain stable:
- `/login` = Dashboard/Backoffice login.
- `/driver/login` = Flutter/FieldRepresentative login.

The URL name `driver` is a compatibility surface only; it does not make `Driver` the target identity model.

## 3. Access JWT

After cutover, access-token subject is:

```text
sub = CompanyPrincipal.id
```

Required trusted-structure claims:

```text
type = access
sub = principal id
company_id = tenant id
channel = DASHBOARD | FIELD
principal_type = BACKOFFICE | FIELD_REPRESENTATIVE
auth_revision = persisted principal auth/session revision
jti = token id
exp = expiry
```

Rules:
- capability/role lists are NOT trusted authorization claims;
- authorization is resolved from persisted principal/profile/Owner/role/scope state;
- `principal_type` and `channel` claims are checked against persisted identity and required endpoint/application channel;
- `auth_revision` must equal the current persisted revision so account/session invalidation can fail closed;
- tenant context is established only after validated company identity information is parsed and then verified against persisted principal/company state;
- existing signature/expiry/blacklist protections remain.

Legacy `role`, `is_admin`, `username` claims may exist only during an explicitly bounded compatibility window and must not authorize anything. They are removed after Dashboard/Flutter contract cutover.

## 4. Login response identity

New canonical response fields:

Dashboard:
```text
principal_id
backoffice_user_id
channel = DASHBOARD
is_company_owner
capabilities / capability bootstrap contract as approved by authorization layer
```

Field:
```text
principal_id
representative_id
channel = FIELD
```

Temporary legacy `driver_id` / `is_admin` response fields may remain only during the compatibility window required to migrate current Dashboard/Flutter consumers. They must be deleted before the identity migration is declared complete.

Never make `representative_id == principal_id` an invariant.

## 5. Refresh-session persistence

Target refresh persistence must bind all of:

```text
principal_id
company_id
channel
refresh token identity/hash/token value per existing design
expires_at
revoked state
replacement/successor relation
auth revision or equivalent persisted invalidation binding
```

Tenant-safe principal/company linkage is mandatory.

Refresh validation order must preserve current security behavior and add the new identity checks:
1. verify signed token structure/type/expiry;
2. parse principal/company/channel;
3. establish tenant context safely;
4. load exact stored refresh row under lock;
5. require stored principal/company/channel to equal decoded values;
6. require active CompanyPrincipal and active Company;
7. require persisted principal type/profile to match channel;
8. require auth revision validity;
9. preserve revoked/rotation-successor/lost-response grace behavior only for the same principal/company/channel;
10. issue successor bound to exactly the same identity/channel.

A successor must never change channel or principal type.

## 6. Legacy refresh cutover

Legacy refresh sessions are NOT converted or guessed.

At identity cutover:
- revoke/invalidate all legacy company refresh sessions;
- existing access tokens may be invalidated at the same cutover boundary via revision/blacklist/cutover policy;
- users perform one clean re-login through the correct channel;
- no legacy `role=Admin|Inventory|Driver` claim is used to infer the new principal/profile/channel.

This one-time re-login is an accepted V1 migration behavior.

## 7. HTTP dependency split

Target dependency concepts must be explicit and small; exact names may follow project conventions but semantics are frozen:

```text
get_current_principal
get_current_backoffice_principal
get_current_field_principal
require_capability(...)
require_company_owner (only where Owner-specific authority is truly required)
```

Rules:
- generic authenticated principal resolution verifies tenant, active state, token type/channel/type/revision and blacklist;
- Dashboard-only endpoints depend on Backoffice channel/profile;
- field endpoints depend on Field channel/profile;
- capability checks are separate from identity/channel checks;
- no new `get_current_admin` equivalent based on a boolean flag is allowed.

## 8. Field ownership vs authenticated actor

The authenticated token identifies `CompanyPrincipal`.

Field workflow ownership uses `FieldRepresentative.id` where the reviewed FK matrix classifies a relationship as `FIELD_REPRESENTATIVE`.

Therefore field request context must resolve both:

```text
principal -> FieldRepresentative profile
```

and pass the correct ID to route/session/visit/shortage/custody ownership rules.

Action/audit/idempotency fields classified `PRINCIPAL_ACTOR` continue to receive the principal ID after their FK cutover.

Do not substitute representative ID into generic actor history.

## 9. Dashboard roles and scopes

Dashboard authentication proves only Backoffice channel eligibility.

Actual authority comes from:
- CompanyOwner protected authority; or
- Backoffice role/capability grants; and
- exact applicable organizational/location scope where required.

A Backoffice account with no allowed Dashboard capability fails Dashboard admission except where an explicit minimal-account bootstrap policy is later approved.

Role names never authorize.

## 10. Flutter field authorization

FieldRepresentative login does not create Dashboard roles or `UserLocationAccess`.

Field operations use:
- authenticated FIELD principal;
- active FieldRepresentative profile;
- stored route/work-session/visit/vehicle/custody assignments;
- existing business/inventory guards.

A field account cannot use Dashboard endpoints by presenting the same token.

## 11. Logout, blacklist and revocation

Preserve current logout/blacklist behavior.

After cutover, explicit account/session invalidation increments or otherwise changes the persisted auth/session revision so previously issued access tokens fail closed even if not individually blacklisted.

Password reset, account deactivation, principal type/channel changes and security-sensitive credential reset must revoke active refresh sessions and invalidate relevant access sessions.

## 12. Realtime / WebSocket

Realtime access must parse the same company principal identity semantics as HTTP.

For `/ws/dispatch` during this migration:
- only Dashboard/Backoffice channel is eligible;
- CompanyOwner may subscribe;
- do not automatically admit every `dispatch.read` holder until topic/scope filtering exists;
- token blacklist, expiry, principal active state, company active state and revision are revalidated consistently;
- field-channel token is rejected.

## 13. Company Owner bootstrap / live-data rule

Owner backfill is a separate data decision, not inferred inside login code.

For each company during backfill:
- exactly one approved legacy owner candidate is required;
- zero candidates -> fail closed / explicit provisioning decision;
- multiple plausible candidates -> fail closed / explicit owner choice;
- dual-use legacy rows must be classified explicitly before creating channel profiles.

Development DB evidence on 2026-10-10:
- one company;
- one visible legacy `is_admin=true` row inside correct tenant context;
- zero visible legacy non-admin rows;
- zero role grants;
- zero location grants;
- eight refresh-session rows.

This development evidence is suitable for local migration validation only. It is not a production owner-selection rule.

## 14. Compatibility window

Allowed temporarily:
- legacy tables/FKs;
- compatibility response fields;
- compatibility adapters that map old Runtime to the new identity foundation.

Forbidden:
- new business logic depending on `Driver.is_admin`;
- new endpoints using Driver as generic identity;
- inferring field identity from `is_admin=false`;
- inferring Backoffice/Owner from token role strings;
- permanent dual authority systems.

The compatibility window ends only after Backend, Dashboard, Flutter, workers, realtime, FK migration and focused acceptance are cut over.

## 15. Final cleanup gate

Before identity migration closure:
- Runtime `is_admin` = 0;
- Runtime `get_current_admin` = 0;
- company auth uses CompanyPrincipal subject;
- Dashboard is Backoffice-only;
- Flutter is FieldRepresentative-only;
- refresh rows bind principal + company + channel;
- legacy refresh sessions cannot rotate;
- no authorization trusts JWT role/is_admin fields;
- compatibility `driver_id` / `is_admin` response fields are removed from active clients/contracts;
- action history uses principal semantics and field ownership uses representative semantics according to the reviewed FK matrix.