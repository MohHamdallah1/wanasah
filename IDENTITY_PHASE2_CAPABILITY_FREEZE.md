# Identity Phase 2 Capability Freeze

**Status:** CANONICAL FOR IDENTITY AUTHORIZATION CUTOVER
**Date:** 2026-10-10
**Depends on:** `ARCHITECTURE.md`, `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md`, `IDENTITY_PHASE1_SEMANTIC_INVENTORY.md`, `IDENTITY_PHASE2_DECISION_FREEZE.md`.

This document closes the lead-owned authorization ambiguities required before endpoint cutover. It does not authorize weakening business, tenant, state, locking, inventory, settlement, password-confirmation, or separation-of-duties guards.

## 1. General rules

- Authentication/channel checks are not business capabilities.
- Company Owner receives the complete tenant capability set centrally, but never bypasses structural/business invariants.
- Backoffice permissions are explicit capability + applicable scope.
- FieldRepresentative authority comes from field channel + stored work ownership for field-only workflows; do not create Backoffice-style role grants for ordinary field ownership.
- Reuse existing capability codes whenever they already express the business action.
- New codes below are narrow additions; no `admin.*` shortcut is allowed.
- Location-scoped actions continue to use server-stored authoritative locations, never client-provided scope as authority.

## 2. Authentication/channel endpoints

No business capability is attached to:
- `POST /login`
- `POST /driver/login`
- `POST /refresh`

They are governed by the explicit principal/channel/session contract in `IDENTITY_AUTH_SESSION_CUTOVER_CONTRACT.md`.

## 3. Branch metadata and branch administration

Branch remains optional organizational metadata in V1, not tenant context.

Freeze these codes:
- `branch.read`
- `branch.create`
- `branch.update`
- `branch.state`

Mappings:
- branch management/list/options -> `branch.read`
- create -> `branch.create`
- edit -> `branch.update`
- activate/deactivate -> `branch.state`

`/warehouse/branches/options` requires `branch.read`. Location create/update forms that need branch options must receive `branch.read` through their role bundle rather than deriving branch visibility from branch membership.

## 4. Catalog archive blocker navigation

`catalog.archive` authorizes archive preflight itself.

Returned blocker/navigation targets are filtered by their target authority:
- shortage targets require `shortage.read`;
- custody/transfer targets require existing `transfer.read` or the exact current dispatch/transfer authority used by that target;
- absence of target capability hides/omits target navigation without weakening the archive blocker itself.

Do not restore an `is_admin` navigation bypass.

## 5. Work-session privileged operations

Freeze:
- `work_session.read`
- `work_session.authorize_sale`
- `work_session.reopen`

Rules:
- company-wide session listings/read models require `work_session.read`;
- sell authorization requires `work_session.authorize_sale`;
- undo/reopen requires `work_session.reopen`;
- self-authorization prohibition, closed/settled guards, route validity and reconciliation state remain mandatory;
- stored route/session/vehicle/location relationships remain the scope source.

## 6. Settlement

Freeze:
- `settlement.read`
- `settlement.execute`

Rules:
- settlement reports require `settlement.read`;
- settlement mutation requires `settlement.execute`;
- inventory reconciliation/snapshot seal, cash evidence, custody state, route/session state, password/confirmation rules where present, and audit remain mandatory;
- capability does not authorize settlement of a structurally unrelated or invalid tenant session.

## 7. Shortages

Freeze:
- `shortage.read`
- `shortage.create`
- `shortage.cancel`

Shortage authority is company operational authority over addressed tenant requests/representatives/products. Route/visit ownership resolution, product lifecycle rules, pending-visit concurrency, and any server-derived location/route constraints remain authoritative.

## 8. Visit detail

Freeze `visit.read` for Backoffice access.

Rules:
- FieldRepresentative may read a visit only through field channel + stored ownership rules.
- Backoffice access requires `visit.read` plus tenant/object visibility.
- Company Owner receives the capability but does not bypass object existence/tenant checks.

## 9. Minimum-stock administration

Freeze `inventory.minimum_stock.manage`.

Mappings:
- bulk preview -> `inventory.minimum_stock.manage` plus the existing inventory visibility needed for the selected warehouse/products;
- bulk apply -> `inventory.minimum_stock.manage`;
- single minimum-stock update -> `inventory.minimum_stock.manage`.

`inventory.read` alone is never sufficient mutation authority.

## 10. Reconciliation

Freeze `reconciliation.execute` for Backoffice override/operational reconciliation authority.

Rules:
- FieldRepresentative may reconcile only the owned valid session through field channel and stored route/vehicle custody context.
- Backoffice override requires `reconciliation.execute` plus the relevant stored operational scope.
- snapshot, vehicle reconciliation, stocktake and separation-of-duties rules remain intact.

## 11. Sales returns

Freeze `sales_return.create`.

Scope is derived from the original tenant sale/visit and the server-determined stock/custody location affected by the reversal. The caller must also satisfy the exact inventory/location authority required by the stored reversal path. Never use an arbitrary client location to widen authority.

## 12. Stocktake supervisor behavior

Do not add a new generic supervisor/admin capability.

Keep existing codes:
- `stocktake.review`
- `stocktake.approve`
- `stocktake.cancel`
- `stocktake.recount`

During cutover remove the extra legacy `is_admin` requirement only when the corresponding explicit capability is enforced. Preserve:
- password confirmation;
- independent/second actor rules;
- recount authorization;
- state guards;
- exact stored location/session scope;
- audit/provenance.

Posting/service internals must receive/verify explicit authority, not re-query `is_admin` as a hidden second permission system.

## 13. Dispatch WebSocket

Do not broaden `/ws/dispatch` to all `dispatch.read` holders in this migration.

Until topic/subscription scoping is explicitly designed:
- Company Owner is allowed;
- any additional Backoffice stream authority requires a future dedicated stream/subscription design;
- company/tenant binding, blacklist, active-account checks and revocation remain mandatory.

No new `dispatch.stream` code is introduced in the current cutover merely to preserve the legacy broad admin stream.

## 14. Platform provisioning

Platform company creation remains in the separate Platform security realm. Tenant capability names do not authorize it. No tenant Owner capability is introduced for `/platform/companies`.

## 15. Ambiguous legacy FKs

Still intentionally unresolved during expand/capability cutover:
- `Shop.added_by_driver_id`
- `InventoryDamageEvent.source_driver_id`
- `InventoryDamageEvent.receiving_admin_id`

Preserve them until a deterministic history/workflow mapping is available. Capability cutover must not be used to guess persistence semantics.

## 16. Structural-check rule

Legacy full-authority shortcuts that skipped structure are not carried forward.

Owner/full capability never bypasses:
- tenant/object existence;
- source warehouse validity;
- vehicle custody/location validity;
- route/session structural validity;
- inventory locks/batch/expiry/FEFO authority;
- closed/settled workflow state;
- separation-of-duties/password confirmation.

## 17. Capability additions frozen by this document

New tenant capability codes approved for the migration:

```text
branch.read
branch.create
branch.update
branch.state
work_session.read
work_session.authorize_sale
work_session.reopen
settlement.read
settlement.execute
shortage.read
shortage.create
shortage.cancel
visit.read
inventory.minimum_stock.manage
reconciliation.execute
sales_return.create
```

Any additional code requires lead review before implementation.