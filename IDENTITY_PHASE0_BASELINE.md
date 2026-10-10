# Wanasah Identity Migration — Phase 0 Baseline

**Date:** 2026-10-10  
**Branch:** `sol/identity-phase0-baseline`  
**Purpose:** Record the known-good source/database/auth baseline before any identity schema or Runtime cutover work.

## Source baseline

- [x] Latest approved `main` verified from GitHub.
- [x] Baseline `main` SHA: `d0a15d770bbdac553d4f69a813ccd2761dfd8a48`.
- [x] No Runtime code was modified while collecting this baseline.
- [x] Local owner/generated changes were deliberately left untouched.

Observed local changes that are **out of scope and must not be reset/overwritten**:

- `.vscode/settings.json`
- `RUN.txt`
- Flutter generated plugin registrant/cmake files under Linux/macOS/Windows
- local `.worktrees/` created for parallel workers
- `Wanasah Arabic Representatives Dashboard.png`

## Database migration baseline

- [x] Alembic code head: `c6f1a4d8e203`.
- [x] Connected local development database current revision: `c6f1a4d8e203 (head)`.
- [x] Therefore no Alembic revision drift was present at baseline time.

No identity migration has been created yet.

## Current authentication authority observed

The following facts are confirmed from current `main` and are preservation constraints until the planned cutover deliberately replaces them:

- [x] `/driver/login` authenticates from legacy `Driver`.
- [x] `/login` also authenticates from legacy `Driver`.
- [x] Both access-token flows currently place legacy `driver.id` in JWT `sub`.
- [x] Access JWT currently includes legacy `is_admin` and a coarse `role` string.
- [x] Refresh-token persistence currently stores `driver_id`.
- [x] Refresh processing reloads `Driver` and derives/falls back to legacy role semantics.
- [x] `get_current_driver()` resolves JWT identity back to `Driver` and applies tenant + blacklist + active-account checks.
- [x] `get_current_admin()` is a centralized legacy `is_admin` gate.
- [x] `get_current_driver_owned()` also contains an `is_admin` bypass.
- [x] `token_identity.access_token_identity()` itself is narrow and currently validates only access-token type, positive subject id, and positive company id; it does not encode admin/field authorization.

## Security behavior that must survive migration

The migration must preserve or deliberately replace with equivalent/stronger behavior for:

- JWT signature and expiry validation.
- rejection of refresh tokens on access-only paths.
- tenant identity extraction before tenant-scoped DB access.
- PostgreSQL tenant/RLS context propagation.
- token blacklist enforcement.
- active-account enforcement.
- active-company enforcement on login/refresh.
- brute-force/login-attempt tracking behavior.
- constant/dummy password-hash verification path for missing identities.
- refresh-token rotation/revocation semantics.
- fail-closed behavior on malformed/missing identity.

## Test baseline

### Existing direct auth coverage

A focused source search under `wa_backend/tests/` found **no dedicated direct tests for `/login`, `/driver/login`, or `/refresh`** at baseline time.

Existing tests do exercise pieces around authorization/dependency usage, including tests that override `get_current_driver` and tests that assert legacy `get_current_admin` dependency placement, but these are not sufficient as a complete identity/authentication acceptance suite.

### Local pytest execution status

Attempted focused baseline execution:

```text
venv\Scripts\python.exe -m pytest ...
```

Result:

```text
No module named pytest
```

This is an **environment/tooling gap, not a code-test failure**. No package was installed automatically.

Before Runtime identity cutover, the implementation wave must establish a supported focused test execution path and add direct login/channel/refresh tests specified by the migration plan.

## Phase 0 remaining gates before schema mutation

The following are intentionally still open and must be closed before the first identity Alembic migration is applied to an important database:

- [ ] Phase 1 semantic inventory reviewed and accepted by the technical lead.
- [ ] Exact target identity contract frozen after Phase 1 evidence review.
- [ ] Database backup/recovery checkpoint taken immediately before schema mutation.
- [ ] Focused auth/session test execution path available.
- [ ] Clean-bootstrap migration path revalidated once the new expand migration exists.

## Parallel-work boundary

During the current first wave:

- Codex owns the exhaustive `is_admin` / `Driver` / FK semantic inventory only.
- Sol worker owns `driver.py` / `dispatch.py` seam inventory only.
- Primary ChatGPT lead owns this Phase 0 baseline and final review/architecture decisions.
- No worker is authorized to modify Runtime identity architecture before the inventories are reviewed.
