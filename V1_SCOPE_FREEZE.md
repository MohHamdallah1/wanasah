# Wanasah V1 Scope Freeze

**Status:** FROZEN V1 PRODUCT SCOPE — CHANGE CONTROL REQUIRED
**Frozen on:** 2026-10-05
**Repository baseline:** `main` at `4c72da369e3c09e03cbf69432e67e0d441be2f38`
**Launch target:** the first real distribution company using Wanasah in production.

## 1. Purpose

This file defines **where Version 1 ends**. It is the canonical product-scope authority for V1.

- `ARCHITECTURE.md` defines **how the platform must be built and evolve**.
- `V1_SCOPE_FREEZE.md` defines **what must be finished before V1 is declared done**.
- `VERSION_2_FUTURE_FEATURES.md` is the canonical backlog for capabilities intentionally deferred beyond V1.
- Feature plans may define implementation details, but they must not silently expand V1 beyond this file.

A page, tab, endpoint, database table, or already-written backend capability does **not** automatically make a feature part of V1.

## 2. V1 product goal

V1 is complete when one real distribution company can replace the core WhatsApp / Word / Excel operating flow with Wanasah for the agreed daily workflow:

**company setup → users/access → products/prices → warehouses/stock → dispatch/routes/shops → field visits and commercial actions → returns/stock/financial evidence → essential reports.**

The first release is intentionally for **one company in production**. Multi-tenant isolation remains non-negotiable and must stay correct, but large multi-company scale qualification is not a V1 launch gate.

## 3. Scope classifications

Every new request or discovered gap must be classified before implementation:

- **V1 BLOCKER** — security, tenant/location isolation, data corruption, financial/inventory truth, broken required workflow, unrecoverable production failure, or release-blocking defect.
- **V1 REQUIRED** — necessary to complete one of the frozen business workflows below.
- **V1 POLISH** — only work that is necessary to make a required V1 workflow understandable and safely usable. Optional visual perfection is not a blocker.
- **V2** — useful capability or improvement that is not required for the frozen first-company workflow.

Unknown or ambiguous scope defaults to **V2 / STOP AND ASK**, not to V1.

## 4. Mandatory scope-change guard

An owner request such as **"نفذ"**, **"اعملها"**, **"كمل"**, or similar execution wording does **not** authorize expansion of V1 by itself.

If a requested task is outside this frozen scope, the assistant/agent must stop before implementation and state that it is outside V1. It may be recorded in `VERSION_2_FUTURE_FEATURES.md`.

V1 may be expanded only after explicit owner approval that clearly means:

> **I explicitly approve changing the frozen V1 scope and adding this capability to V1.**

Arabic equivalent is equally valid when equally explicit, for example:

> **أوافق صراحة على تغيير نطاق V1 المجمد وإضافة هذه الميزة إلى V1.**

After such approval, update this file **before** implementing the new capability. Never infer approval from urgency, repetition, ease of implementation, or the fact that code already exists.

## 5. Frozen V1 business scope

### 5.1 Identity, company setup, access and sessions — V1 REQUIRED

V1 includes only the administration needed to operate the first company safely:

- platform/company provisioning required to create and operate the company;
- company admin and operational user authentication/session handling;
- users, roles/permissions and required branch/location access;
- fail-closed company and warehouse/location isolation;
- safe logout/session recovery and traceable API failures.

Do not turn V1 into a general identity/IAM product.

### 5.2 Products / Catalog — V1 REQUIRED

V1 includes the normal distribution-product workflow:

- create, read, search, edit supported product fields, lifecycle/status, family/category behavior used by the current product flow;
- SKU and supported barcode management;
- simple base-unit + optional outer-package structure used by normal products;
- simple product price create/edit using Pricing as backend authority;
- tracking defaults/modes required by inventory and expiry workflows;
- CSV/XLSX Product Import, validation/correction/retry/cancel/recovery, using the accepted production pipeline;
- current import performance is considered sufficient for V1 once the accepted 50k workflow remains around the already-achieved ~4 minute class on the reference environment without correctness regression. Do not chase further throughput for V1 without a demonstrated regression or release blocker.

**Not V1:** Advanced UOM, Advanced Pricing workspace, company-configurable unit/package catalog, additional ingestion channels, or richer catalog concepts already deferred in `VERSION_2_FUTURE_FEATURES.md`.

### 5.3 Inventory / Warehouses — V1 REQUIRED

V1 includes the stock workflows needed for real distribution operations:

- warehouse/location setup and access;
- product-location availability/assignment semantics;
- Live Stock as operational stock visibility;
- supplier inbound / goods receipt;
- lot/batch and expiry behavior required by configured products;
- Batches & Expiry visibility required to understand sellability and expiry state;
- warehouse transfers;
- stocktake / stock corrections through authoritative inventory movements;
- inventory ledger/history;
- minimum-stock policy only to the extent already used by the V1 operational workflow;
- inventory costing/COGS correctness for enabled V1 commercial actions.

`InventoryBalance` and the Unified Inventory Movement authority remain the truth. UI convenience never weakens inventory or location safety.

### 5.4 Dispatch, routes and shops — V1 REQUIRED

V1 must replace the old "Word region file + temporary WhatsApp group + copy/paste shop" operating pattern for the first company.

It includes:

- regions/territories and shops required by dispatch;
- assigning the required route/visit work to the correct field user;
- clear route/visit list and status visibility for administration;
- adding a shop from the supported field/admin workflow where already part of the operating model;
- recording visit outcomes as structured system data rather than WhatsApp replies;
- the current dispatch workflow required to send work from the dashboard to the field app.

Advanced route optimization, generalized fleet-management expansion, or unrelated logistics features are V2 unless explicitly promoted through the scope-change guard.

### 5.5 Flutter field application — V1 REQUIRED

Flutter is part of V1 even though it has not yet received the same current hardening pass as Products/Inventory.

The V1 field app boundary is:

- login/session;
- assigned work / route / visit list;
- shop details and supported shop creation;
- visit workflow and visit outcome;
- enabled sales/commercial actions already required by the backend V1 workflow;
- returns/samples/relevant stock effects only where they are part of the current supported visit workflow;
- offline-safe draft/work behavior and deterministic synchronization/retry sufficient for real field use;
- no cross-user/company data leakage;
- practical recovery from network interruption without duplicate business mutations.

Do not redesign Flutter into a new product before these required workflows are production-usable.

### 5.6 Commercial rules, offers and taxes — V1 REQUIRED only for enabled current workflows

V1 includes the offers/tax/commercial-policy behavior already consumed by V1 product/visit/sales calculations and the minimum administration needed to operate it.

Do not expand V1 into a general rule-builder, promotion platform, or advanced pricing engine.

### 5.7 Sales, returns and financial truth — V1 REQUIRED

V1 includes the commercial actions already required by the field/distribution workflow and their authoritative stock/financial consequences:

- sale evidence and price/tax/offer resolution through backend authority;
- returns required by the supported workflow;
- immutable financial/stock evidence where the architecture requires it;
- one official inventory valuation/COGS/profit authority;
- idempotent retry/reconciliation for ambiguous mutation results.

New accounting modules, full ERP accounting, supplier invoicing suites, and unrelated finance expansion are not V1.

### 5.8 Reports — V1 REQUIRED, minimal launch set only

The sidebar currently exposes Reports as not yet implemented. V1 requires only the reports necessary to operate the first company without returning to WhatsApp/Excel for the core daily flow:

- route/visit completion and visit-result reporting;
- sales/returns summary required by management;
- current stock / inventory movement visibility where existing operational pages do not already answer the need;
- field-user settlement/accountability information only to the extent already represented by the current business workflow.

No report-builder, BI platform, arbitrary dashboard designer, warehouse data platform, or broad analytics suite is part of V1.

### 5.9 Settings — V1 REQUIRED, minimal operational settings only

The sidebar currently exposes Settings as not yet implemented. V1 settings are limited to configuration required by the frozen workflows: company/user/access/branch/location and the specific operational policies already required by V1.

Theme customization, generic workflow builders, deep company personalization, and settings with no V1 consumer are V2.

### 5.10 Production readiness — V1 REQUIRED

Before V1 is done:

- no known blocker in tenant/company/location isolation;
- no known blocker that can corrupt stock, prices, sales, returns, cost/COGS, audit or idempotent command truth;
- required workers/jobs recover safely from restart/failure;
- actual deployment backup/restore path is proven at the V1 deployment level;
- critical 5xx/network failures are traceable and do not expose unsafe internals;
- required dashboard and Flutter workflows pass focused acceptance gates;
- no release-critical unbounded query/transaction/resource leak is known.

V1 does **not** require production-like proof of 1,000 simultaneous real HTTP/TLS clients, large multi-company scale, horizontal autoscaling, or every long-term Modulith boundary to be fully migrated.

## 6. Explicit V2 / not-a-V1-blocker boundary

The following must not delay V1 unless a later explicit scope change promotes them:

- Advanced UOM and multi-level commercial packaging;
- Advanced Pricing workspace/rules;
- company-configurable unit/package catalog;
- REST/data-feed/SFTP product-ingestion channels beyond V1 file import;
- marketplace/ERP-specific connectors and EDI;
- catch-weight/variable-weight products;
- mixed-SKU kits/BOM/assemblies;
- tracked physical handling units / nested shipping packages;
- large multi-company and 1,000-simultaneous-client qualification;
- throughput optimization beyond already accepted V1 performance without measured regression;
- refactoring stable legacy code only because a cleaner long-term structure exists;
- completing every target described in `ARCHITECTURE.md` before launch;
- optional animations, cosmetic redesigns, extra dashboards, configurable BI, or polish that does not block safe comprehension/use.

## 7. Stop rule — when V1 is DONE

**V1 is DONE and feature expansion stops when all of the following are true:**

1. Every section marked V1 REQUIRED above has a complete usable end-to-end workflow for the first company.
2. Required Dashboard + Flutter paths work together in the real operating flow.
3. All known V1 BLOCKER items are closed.
4. Focused release gates for security/isolation, stock/financial truth, idempotency/recovery and required workflows pass.
5. Reports and Settings meet only the minimal boundaries defined above.
6. Deployment/backup/worker/observability readiness for the first company is accepted.

At that point, remaining ideas, cleanup, optimizations and capabilities are **V2 by default**. "It could be better" is not a V1 blocker.

## 8. Working rule for all future tasks

Before editing code, answer internally and, when scope is not obvious, state explicitly:

**Which frozen V1 workflow does this task unblock?**

If there is no concrete answer, do not implement it as V1. Record it in V2 or leave it alone.

For a completed V1 item, use `[x]`. Do not reopen a completed item merely for speculative optimization or architectural perfection unless a real regression, broken invariant, security issue, data-integrity issue, or required-workflow gap is demonstrated.

## 9. Audit snapshot used for this freeze

The 2026-10-05 scope audit confirmed:

- Dashboard active routed surfaces include Operations, Dispatch, Inventory, Products, Commercial Rules and Sales/Returns; Reports and Settings are visible but currently "coming soon" in navigation.
- Inventory currently contains Live Stock, Inbound, Stocktake, Ledger, Batches, Transfers, Warehouse Locations and Inventory Access surfaces.
- Products already has structured page-level modules including create/list/detail/family/barcode/import/lifecycle/display preferences plus a disabled/deferred Advanced UOM path.
- Flutter currently contains login, dashboard, visit list, visit workflow and add-shop screens and therefore is not an empty future application; it requires its V1 audit/hardening rather than invention from zero.
- The backend already spans auth, catalog, dispatch, driver, inventory, pricing, offers/commercial policy, product-location/tracking and related authorities.
- Existing plans retain open V1 correctness work around inventory/commercial financial truth and inbound/batch-expiry hardening; those open correctness items remain V1 when they directly support the frozen workflows above.

This snapshot is evidence for the boundary, not permission to add every discovered code path to V1.
