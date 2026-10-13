# Wanasah Identity & Authorization — `is_admin` Final Closure

**Status:** CLOSED — FINAL ACCEPTANCE PASSED  
**Closure date:** 2026-10-13  
**Verified product baseline:** `535c98390774e4bdb06710cbaf1769f7556b1777`  
**Supersedes as current status:** `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md`

The original migration plan is retained as the historical execution plan. Its old `PLANNED — NOT YET IMPLEMENTED` header and unchecked planning boxes are no longer the current implementation status. This closure record is the authoritative completion status for the `is_admin` / canonical identity migration.

## Final result

The Identity / Authorization migration is accepted as complete for this scope.

- Legacy `Driver.is_admin` is no longer runtime authorization authority.
- Canonical tenant authority is the authenticated canonical subject/access context and `access.company_id` where applicable.
- Backoffice and Field Representative identities are separated; principal/profile/legacy Driver IDs are not assumed equal.
- Company Owner authority comes from canonical owner state, not a generic admin boolean or role-name shortcut.
- Backoffice authorization is capability/scope based.
- Legacy Driver access remains only where genuine legacy operational provenance/compatibility fields still require an existing `Driver.id`; it is not tenant or permission authority.
- Dashboard canonical identity storage uses canonical principal/backoffice identity and retires legacy `driver_id` identity storage.
- Post-cutover migration/evidence tooling fails closed instead of reconstructing authority from removed legacy `is_admin` evidence.

## Merged closure work

The final closure sequence included:

- PR #273 — backend post-drop compatibility and PostgreSQL post-cutover acceptance.
- PR #275 — clean Dashboard canonical identity consumer/storage cutover.
- PR #276 — final Login retirement contract aligned with canonical Dashboard identity.

The verified product baseline after those merges is:

`535c98390774e4bdb06710cbaf1769f7556b1777`

## Final unified acceptance gate

GitHub Actions run:

`38373984226` — `TEMP identity authorization final unified gate`

Result: **SUCCESS**.

All three final jobs passed:

1. **backend-runtime**
   - current-schema retirement contracts pass;
   - physical `Driver.is_admin` compatibility/retirement checks pass;
   - canonical runtime/post-drop suites pass;
   - runtime Python compile census passes;
   - fixture/source census passes;
   - gate leaves a clean diff.

2. **client**
   - Dashboard canonical inventory identity tests pass;
   - Login canonical identity contract tests pass;
   - production Dashboard build passes;
   - Dashboard runtime source census passes;
   - Flutter runtime source census passes;
   - client post-drop blocker census is zero;
   - gate leaves a clean diff.

3. **postgres-schema**
   - PostgreSQL 16 clean Alembic upgrade passes;
   - canonical Backoffice capability gate passes;
   - physical schema contains no `drivers.is_admin` column or dependent schema objects;
   - downgrade to the parent revision restores only the intended historical structural boolean;
   - re-upgrade removes it again;
   - independent clean-from-zero database upgrade passes;
   - isolated post-cutover identity backfill/tooling gate passes;
   - gate leaves a clean diff.

## Schema acceptance

Final Alembic head verified by the unified gate:

`f2c7a9d4e611`

Accepted invariants:

- clean upgrade reaches one Alembic head;
- `drivers.is_admin` is physically absent at the current head;
- there are no current dependent indexes, constraints, defaults, generated expressions, or functions relying on that column;
- downgrade/re-upgrade behavior is deterministic;
- a clean database can migrate from zero to the current head successfully.

## Client acceptance

Accepted Dashboard contract:

- no canonical Dashboard identity depends on `driver_id`;
- canonical storage persists `principal_id` and `backoffice_user_id`;
- legacy Dashboard `driver_id` storage is removed/migrated;
- Dashboard channel/type guards remain explicit;
- production build passes after the cutover.

## Legacy compatibility boundary

The word `Driver` / `driver_id` may still exist where it represents a real legacy domain/provenance reference that has not been redefined by this migration. That is not evidence of surviving `is_admin` authority.

The closed rule is:

> No `Driver.is_admin`, generic admin shortcut, or legacy Driver/company identity may serve as current authorization or tenant authority.

Historical Alembic revisions and historical planning text may still contain the literal token `is_admin`; immutable migration history is not rewritten merely to erase text.

## Temporary evidence branches

Temporary leadership/CI branches used during closure are not product authority and are not required by `main` after acceptance. Their purpose was evidence generation only. Any later branch cleanup is repository housekeeping, not remaining Identity / Authorization implementation work.

## Closure decision

**Identity / Authorization / `is_admin` migration: CLOSED.**

New feature or architecture work must build on the canonical identity/capability model. Reintroducing `is_admin` authorization, Driver-ID equality assumptions, generic admin bypasses, or Driver-company tenant authority is a regression.
