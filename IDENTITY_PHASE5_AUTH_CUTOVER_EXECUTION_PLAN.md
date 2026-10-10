# Identity Phase 5 — Auth Cutover Execution Plan

**Status:** LEAD-OWNED EXECUTION PLAN  
**Date:** 2026-10-10  
**Depends on:** `IDENTITY_AUTH_SESSION_CUTOVER_CONTRACT.md`, `IDENTITY_CLIENT_LOGIN_CUTOVER_CONTRACT.md`, `IDENTITY_PHASE34_BACKFILL_CONTRACT.md`.

## 1. Goal

Cut company authentication from legacy `Driver` identity to `CompanyPrincipal` without changing business workflow ownership accidentally, without turning `api/auth.py` into a larger monolith, and without making compatibility fields into new authority.

Target ownership:

```text
wa_backend/api/auth.py
  HTTP parsing/status/response compatibility only

wa_backend/domains/identity/
  credential authentication
  channel/profile validation
  principal/profile repository

wa_backend/domains/auth_sessions/
  JWT claims/codec
  persisted request context
  refresh-session persistence and rotation
  logout/revocation/session invalidation

wa_backend/domains/authorization/
  persisted capabilities/scopes/owner authority
```

No capability decision belongs in token codec or credential authentication.
No credential verification belongs in API route bodies after cutover.
No field-work ownership ID may be replaced with `principal_id` by convenience.

## 2. Current legacy seams that must be removed from `api/auth.py`

Current `api/auth.py` mixes these responsibilities:

1. login-attempt / brute-force policy;
2. tenant/company lookup and tenant context seeding;
3. password verification against `Driver`;
4. Dashboard admission through legacy `InventoryAccess`;
5. access JWT creation;
6. refresh JWT creation and persistence;
7. refresh rotation and lost-response grace;
8. legacy role/is_admin transport claims;
9. logout blacklist and refresh deletion;
10. HTTP response compatibility.

Phase 5 must not replace this with one giant service function.

## 3. Cutover order

The cutover is sequential at the contract boundary even when implementation preparation is parallel.

### Slice A — foundations already prepared

Required before Runtime mutation:

- [x] `CompanyPrincipal` / Backoffice / FieldRepresentative schema.
- [x] channel-explicit credential authentication foundation.
- [x] canonical JWT claims/codec.
- [ ] principal request-context persistence validation.
- [x] deterministic legacy backfill + temporary bridge.
- [ ] principal-bound refresh-session persistence.

Do not cut Runtime login until all six are on `main` and the local stability gate passes.

### Slice B — login-attempt policy extraction

Move brute-force/login-attempt behavior out of route bodies into a small session-security component.

Must preserve:

- current IP-based attempt window and limit;
- company-code attempt recording;
- success/failure audit semantics;
- generic credential failure behavior;
- no password/token logging.

This slice is behavior-preserving. It does not decide identity type or capability.

### Slice C — Dashboard `/login`

Route becomes thin orchestration:

1. resolve active company from company code;
2. establish tenant context;
3. call canonical identity authentication with `DASHBOARD`;
4. require Backoffice profile;
5. evaluate Dashboard admission from persisted Owner/capability state, never role name or `is_admin`;
6. issue canonical access + refresh session for same principal/company/channel;
7. return canonical Dashboard identity fields;
8. during bounded compatibility window only, add legacy response fields resolved through the reviewed bridge.

Canonical fields:

```text
principal_id
backoffice_user_id
channel = DASHBOARD
is_company_owner
company_id
company_code
token
refresh_token
```

Compatibility fields are presentation/transition only:

```text
driver_id      -> reviewed legacy_driver_id, NEVER principal_id alias
is_admin       -> legacy compatibility response only, NEVER authority
driver_name    -> compatibility naming only
```

`dashboard_access` may remain temporarily for current client admission checks, but server authority is persisted Owner/capability state.

### Slice D — Field `/driver/login`

The URL remains stable temporarily, but semantics change to FieldRepresentative authentication.

Flow:

1. resolve active company;
2. establish tenant context;
3. call canonical identity authentication with `FIELD`;
4. require FieldRepresentative profile;
5. issue canonical FIELD access + refresh session;
6. return canonical `principal_id` + `representative_id`;
7. during bounded compatibility only return `driver_id = reviewed legacy_driver_id` from the bridge.

Never return `driver_id = representative_id` unless they happen to match by accident; no equality invariant exists.
Never infer field eligibility from `is_admin=false`.

### Slice E — refresh cutover

`/refresh` switches from legacy `RefreshToken` + Driver identity to principal refresh sessions.

Required validation order:

1. verify signed refresh structure/type/expiry;
2. parse principal/company/channel/revision;
3. establish tenant context;
4. lock exact persisted principal refresh row;
5. exact persisted principal/company/channel/revision match;
6. active company + active principal;
7. persisted principal type/profile matches channel;
8. revoked/rotation-successor/grace checks;
9. issue successor for identical principal/company/channel/type only;
10. revoke predecessor and link successor atomically.

Lost-response grace must never permit identity or channel switching.

Legacy refresh rows are not converted. At the approved cutover boundary they are invalidated/revoked and users perform one clean re-login.

### Slice F — logout/revocation

Preserve access-token blacklist behavior while switching refresh-session destruction to principal refresh storage.

Rules:

- logout remains idempotent where practical;
- supplied refresh token may only affect its exact stored session;
- password/security reset and account deactivation must invalidate principal sessions via `auth_revision` and refresh revocation policy;
- no token or DB credential is logged.

### Slice G — HTTP dependencies

Only after canonical tokens + refresh are live:

- introduce principal-aware FastAPI dependency;
- explicit Backoffice dependency;
- explicit FieldRepresentative dependency;
- capability guard remains separate;
- no `get_current_admin` replacement based on boolean state.

Field context exposes both `principal_id` and `representative_id`.
Dashboard context exposes both `principal_id` and `backoffice_user_id`.

## 4. Compatibility bridge rules

The temporary `identity_legacy_driver_map` is the only approved mapping bridge between new identity rows and legacy Driver IDs during this window.

Compatibility code may use it to return the old ID expected by Dashboard/Flutter while clients are being migrated.

Forbidden:

- `driver_id = principal_id` aliasing;
- `driver_id = representative_id` aliasing;
- using bridge classification as Runtime authorization;
- selecting a generic actor target from a dual-split row;
- adding new workflow ownership to legacy Driver.

Compatibility adapters must be isolated under explicitly named compatibility code and deleted at final contract cleanup.

## 5. Client migration boundary

Backend dual-response comes before client key removal.

Order:

1. backend returns canonical + temporary compatibility fields;
2. Dashboard stores/uses `principal_id` and `backoffice_user_id` and stops authorizing/routing from `is_admin`;
3. Flutter stores `principal_id` + `representative_id` while keeping legacy `driver_id` only for not-yet-migrated offline payload/cache boundaries;
4. field/offline workflows migrate from legacy Driver ID to the correct semantic ID one by one;
5. compatibility response fields are removed only after source audit shows zero production consumers.

## 6. Files and modularity guard

`api/auth.py` stays a router surface; it must shrink, not grow.

Do not place substantial new logic in:

- `api/auth.py`
- `api/dependencies.py`
- legacy `models.py`

Prefer responsibility-specific modules under existing identity/session domains. Do not create a generic `helpers.py`, `utils.py`, or `auth_service.py` dumping ground.

A function that simultaneously authenticates credentials, decides capabilities, persists refresh rotation, writes audit, and formats HTTP response is prohibited.

## 7. Transaction boundaries

Login transaction must keep together only writes that must commit together:

- successful login-attempt record;
- new refresh-session persistence;
- any explicit session-security state required by current behavior.

Credential/password verification and capability reads occur before issuing session material.

Refresh rotation predecessor revoke + successor insert/link are atomic.

Failed authentication must not leave a valid refresh session.

## 8. Security invariants

Every Phase 5 implementation must preserve:

- tenant isolation before tenant-scoped identity reads;
- wrong-channel credentials fail closed;
- inactive company/principal fails closed;
- missing profile fails closed;
- token `sub` = CompanyPrincipal ID;
- persisted revision is authoritative;
- JWT role/is_admin/capabilities never authorize;
- Owner is persisted relation, not legacy flag;
- capability resolution remains persisted server-side;
- field representative workflow ownership uses representative ID, not principal ID;
- audit/idempotency actor migration remains a later reviewed FK phase.

## 9. Focused acceptance before Phase 5 gate

Required focused evidence:

- Dashboard login succeeds for valid Owner.
- Dashboard login succeeds only for an ordinary Backoffice identity with approved Dashboard authority.
- Field-only credentials are denied Dashboard login.
- Backoffice-only credentials are denied field login.
- Field login returns stable canonical `representative_id`.
- compatibility `driver_id` resolves from the bridge and is never fabricated from a new ID.
- access claims contain no authoritative legacy `role`/`is_admin` dependency.
- refresh cannot change company/principal/channel/type.
- disabled principal/company cannot refresh.
- exact rotation/lost-response grace behavior stays bounded to same identity/channel.
- logout revokes/destroys the correct session.
- legacy refresh cutover forces one clean re-login.
- no credential/token secret appears in logs/errors.

## 10. Stop conditions

Stop and escalate before implementation if any of these occurs:

- a legacy Driver has no approved bridge mapping at cutover;
- a dual-split compatibility response cannot determine the exact legacy row;
- Dashboard admission requires a capability not frozen in the capability contract;
- a client still treats canonical principal ID as field workflow ownership;
- refresh successor semantics would require changing channel/principal;
- a migration attempts to rewrite historical actor FKs during Phase 5.

## 11. Phase 5 completion gate

Phase 5 is complete only when:

- Runtime login authenticates `CompanyPrincipal` by explicit channel;
- Runtime access/refresh sessions use canonical principal identity;
- request dependencies revalidate persisted identity/revision/channel/profile;
- no authentication authority depends on `Driver.is_admin` or JWT role strings;
- legacy company refresh sessions are invalidated at cutover;
- compatibility fields remain only where a tracked client consumer still requires them;
- focused cross-channel/refresh/logout/disabled-account acceptance passes;
- `api/auth.py` is materially thinner and responsibility-separated.

This gate does not authorize Phase 8/9 FK rewrites by itself.
