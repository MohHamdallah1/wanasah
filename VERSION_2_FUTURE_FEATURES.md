# Wanasah Version 2 — Deferred Product Capabilities

**Status:** CANONICAL V2 BACKLOG — DO NOT DELETE OR ARCHIVE AS TEMPORARY NOTES  
**Scope:** Product capabilities intentionally deferred from Version 1  
**Last updated:** 2026-09-28

This file is the source of truth for Product capabilities that already have meaningful backend/domain foundations but are intentionally **not exposed as active Version 1 workflows**.

The rule for V1 is:

> Keep deferred capabilities visible where useful for product discoverability, but disabled and clearly labeled as future functionality. Do not delete their backend/domain foundations, migrations, tests, routes, or implementation work merely because the V1 UI is disabled.

---

## 1. Advanced Units of Measure / Advanced UOM

### V1 decision

**Deferred to Version 2.**

The Catalog Tools entry remains visible but disabled in Version 1.

Arabic UI label:
- **إدارة وحدات القياس المتقدمة**

English UI label:
- **Advanced units of measure**

Current route/code may remain in the repository, but the normal V1 Product workflow must not present this capability as ready for production use.

### Why it is deferred

The current Version 1 Product creation workflow is intentionally simple:

- the user selects an optional package type;
- the user enters the number of base units inside that package;
- the Simple Products backend automatically creates the package-to-base UOM conversion;
- the Simple Products workflow publishes the created Product Variant as part of the normal creation flow.

Example:

- Base unit: piece
- Package: carton
- Units per carton: 24

The backend automatically persists the equivalent conversion:

> 1 carton = 24 pieces

For this normal V1 case, the Advanced UOM page is unnecessary.

### Existing backend capability

The Catalog backend already contains broader UOM/catalog capabilities, including:

- UOM directory/listing;
- Product Variant creation in lifecycle status `DRAFT`;
- Product Variant structural update while still `DRAFT`;
- Variant structural fields including:
  - `base_uom_id`
  - `quantity_scale`
  - `quantity_step`
  - lot-control mode
  - expiry-control mode
- UOM conversion listing per Product Variant;
- creation/update of Product UOM conversions;
- conversion fields including:
  - `from_uom_id`
  - `to_uom_id`
  - `numerator`
  - `denominator`
  - `quantity_scale`
- optimistic version checks;
- tenant/company isolation;
- catalog permissions;
- idempotent mutation handling and audit behavior;
- structural locking after publication.

Catalog authority intentionally enforces:

> Variant structure and UOM conversions are editable only while the Product Variant is `DRAFT`.

After publication, structural UOM editing is locked.

### Existing frontend capability

The existing Advanced UOM page can:

- search Product Variants / SKUs;
- select a Product Variant;
- show its base UOM;
- load existing conversions;
- show conversion details;
- add/edit conversions when the selected Variant is editable;
- show a read-only/locked state for published Variants.

### The real V1 workflow gap

The Version 1 Products UI does **not** provide a coherent user workflow that creates and manages a draft Product Variant for advanced UOM configuration.

The ordinary **Add Product** flow uses the Simple Products path and publishes the normal product shape directly.

Therefore a Version 1 user can open the Advanced UOM page, select ordinary published products, and mostly encounter a locked/read-only state without ever having been given a clear workflow to:

1. intentionally choose an advanced UOM product flow;
2. create a Product Variant as a draft;
3. choose/edit its base UOM;
4. configure `quantity_scale` / `quantity_step`;
5. define multiple UOM conversions;
6. review the resulting structure;
7. publish the completed draft.

This is why the existing Advanced UOM page is not a complete production workflow even though important backend foundations already exist.

### Required Version 2 workflow

Version 2 must expose the capability as one coherent product journey, not as an isolated technical page.

Recommended flow:

1. **Normal/simple product remains the default**
   - package type + units per package;
   - no advanced terminology for ordinary users.

2. **Explicit advanced entry point**
   - during Product creation, offer a clearly labeled option such as:
     - “Multiple units of measure”
     - “Advanced unit setup”
   - entering this mode must be intentional.

3. **Create as Draft**
   - create the Product Variant through the Catalog draft workflow;
   - make the draft state explicit to the user.

4. **Define structural quantity behavior**
   - base unit;
   - quantity precision/scale;
   - quantity step;
   - tracking settings that belong to the draft structure.

5. **Define conversions**
   - use user-facing language such as:
     - From unit
     - To unit
     - Equivalent quantity
   - avoid exposing numerator/denominator terminology unless an advanced mode genuinely requires it.

6. **Review before publish**
   - show a human-readable conversion summary;
   - validate the complete structure;
   - make publication an explicit final action.

7. **After publish**
   - structural UOM data becomes read-only according to backend authority;
   - the UI must explain why;
   - do not provide fake edit controls that will be rejected by the backend.

### UX direction for V2

Do not reuse the current large empty two-column screen as-is.

Preferred UX principles:

- explain the purpose with a concrete example such as `1 carton = 24 pieces`;
- keep ordinary users on the simple workflow;
- expose advanced UOM only when needed;
- make the Draft → Configure → Review → Publish lifecycle visible;
- show conversions visually and in plain business language;
- preserve full keyboard operation;
- support Arabic/RTL and English/LTR equally;
- do not duplicate backend business authority in React.

### Version 2 acceptance criteria

Advanced UOM is not considered complete until:

- a user can intentionally create an advanced-UOM Product from the Dashboard;
- the full Draft workflow is reachable without hidden/manual API work;
- all backend-editable structural fields required by that workflow have a deliberate UI owner;
- conversions can be safely created/edited before publication;
- publication and post-publication locking are clear;
- permissions/isolation/version/idempotency semantics remain backend-authoritative;
- Arabic/English, RTL/LTR, accessibility, and full keyboard operation pass;
- production gates cover the complete workflow.

---

## 2. Advanced Pricing

### V1 decision

**Deferred to Version 2.**

The Catalog Tools entry remains visible but disabled in Version 1.

Arabic UI label:
- **التسعير المتقدم**

English UI label:
- **Advanced pricing**

The existing simple Product pricing workflow remains the Version 1 supported experience.

### Why it is deferred

Version 1 intentionally keeps Product pricing simple and understandable:

- unit/package price during Product creation;
- supported Product price editing through the existing simple pricing workflow;
- backend Pricing domain remains authoritative.

An “Advanced Pricing” entry must not be enabled until there is a complete, understandable workflow for the advanced pricing concepts that Version 2 decides to expose.

A visible button that opens a partial or technical pricing surface would create the same product problem as Advanced UOM: backend capability without a coherent end-user journey.

### Version 2 requirements

Before enabling Advanced Pricing:

1. audit the current Pricing domain/contracts and document exactly which advanced capabilities are production-ready;
2. decide which capabilities belong in Product UI versus a dedicated Pricing workspace;
3. design business-language workflows rather than exposing internal publication/book mechanics directly;
4. preserve Pricing as the only backend authority;
5. define permission boundaries explicitly;
6. preserve effective-date/history semantics;
7. preserve idempotency/concurrency/audit guarantees;
8. provide Arabic/English, RTL/LTR, accessibility, and keyboard-first UX;
9. add focused production gates before enabling the menu item.

### UX direction for V2

Advanced Pricing should be introduced only around real business tasks, for example when the platform explicitly supports workflows that require richer price rules than the V1 simple price editor.

Do not enable it merely because backend pricing primitives exist.

---

## 3. Company-configurable unit / package catalog

### V2 decision

**Add a company-configurable Unit / Package Catalog in Version 2.**

Version 1 may continue using the current supported package/unit set in the simple Product workflow. Version 2 should let each company control which business-facing units and package types are available to its users, while starting from a safe platform-provided default set.

Examples of user-facing concepts include:

- piece / unit;
- pack;
- box;
- carton;
- bag;
- bottle;
- can;
- tray;
- pallet;
- other units that are appropriate to a company's business.

The exact starter set is a product decision for V2 and must not be hard-coded into frontend business logic.

### Why this belongs in V2

The current V1 workflow deliberately keeps Product creation simple:

- choose whether the Product has an outer package;
- choose the package type;
- enter the number of base units inside it.

That is enough for the normal distribution workflow.

A configurable catalog becomes valuable when different companies use different commercial vocabulary, package types, unit availability, or advanced conversion structures. Adding that flexibility safely requires a deliberate company-scoped model rather than a list of frontend-only labels.

### Required architecture

The V2 design must preserve Catalog/UOM backend authority.

Recommended direction:

1. **Platform starter catalog**
   - provide a curated default set of common units/package types;
   - a new company starts with a usable set without configuration work.

2. **Company-scoped availability/configuration**
   - each company can choose which units/package types are available in its workflows;
   - company configuration must never leak across tenants;
   - disabled entries should stop future selection, not corrupt historical Product references.

3. **Stable canonical identity**
   - business labels shown to users may be configurable/localized;
   - conversion identity and quantity math must remain canonical and backend-owned;
   - do not make free-text frontend labels the authority for conversion semantics.

4. **One source for all Product workflows**
   - simple Product creation;
   - imports;
   - Product details;
   - future Advanced UOM;
   - any future purchasing, warehouse, sales, or shipping workflow that consumes UOMs.
   All must resolve available units through the same approved Catalog contract.

5. **Safe lifecycle**
   - units already referenced by Products, inventory history, sales evidence, or other durable records must not be hard-deleted merely because a company no longer wants them selectable;
   - use an inactive/retired state for future selection where required.

6. **Localization and aliases**
   - Arabic/English labels and common business aliases may be presented per locale/company;
   - canonical codes remain language-neutral.

7. **Production gates**
   - tenant isolation;
   - duplicate/conflicting code protection;
   - referenced-unit retirement behavior;
   - conversion correctness;
   - import/create parity;
   - RTL/LTR and keyboard accessibility.

### Relationship to Advanced UOM

This catalog and Advanced UOM are related but not the same feature.

- **Unit / Package Catalog:** defines which units and package types the company can use.
- **Advanced UOM:** defines the structural relationships/conversions for a Product that needs more than the normal V1 package + units-per-package flow.

Advanced UOM in V2 must consume this company-configurable catalog rather than inventing a second UOM source.

---

## 4. External Product ingestion channels

### V1 decision

Version 1 keeps **CSV/XLSX file import** as the only external bulk Product-ingestion channel.

The current file-import pipeline remains the production authority for V1 and must be polished for non-technical users rather than diluted by adding partially finished integrations.

### Version 2 scope

Version 2 should add, in this order unless customer evidence changes the priority:

1. **B2B REST APIs** for companies with ERP/internal engineering teams.
2. **Data Feeds / Sync Links** for scheduled CSV/JSON/XML ingestion from approved HTTPS sources.
3. **SFTP / approved object-storage bulk drops** for enterprise scheduled file exchange.

All three must map into the same canonical Product ingestion authority and preserve the existing validation, permission, isolation, idempotency, audit, tracking, barcode, UOM, pricing, and lifecycle rules.

Native marketplace/commerce-platform connectors, vendor-specific ERP connectors, and EDI are intentionally treated as **Version 3 by default** because they introduce connector-specific authentication, reconciliation, rate-limit, support, and versioning costs.

The architecture source of truth for the complete channel roadmap is `ARCHITECTURE.md`.

---

## 5. Version 1 UI policy for deferred features

For both deferred capabilities:

- keep the Catalog Tools items visible;
- render them disabled;
- show a concise “planned for Version 2 / later stage” explanation;
- do not navigate to their routes from the normal V1 UI;
- do not delete existing routes, backend code, migrations, contracts, or gates;
- do not represent them as finished V1 functionality;
- any future re-enable must start from this document and reconcile it with the then-current backend and architecture.

---

## 6. Distinct capabilities: advanced UOM is not a catch-all

**Important:** enabling the existing Advanced UOM menu entry does **not** automatically
complete the following independent business workflows.

- **Multiple units for one SKU (Advanced UOM):** the backend has a tenant-scoped
  product conversion graph, rational conversion factors, quantity precision/step,
  and conflict checks. V2 still needs the complete draft → configure → review →
  publish journey, transaction integration, and acceptance gates. Example:
  1 carton = 10 packs and 1 pack = 6 base units.
- **Variable-weight / catch-weight products:** a fixed UOM conversion and a
  decimal quantity scale do not implement a measured-versus-nominal weight
  workflow. A future separate design must cover actual weight per received
  unit/batch, tolerances, price/cost basis, reconciliation, and downstream
  purchasing, warehouse, and sales behavior. Do not advertise it as supported
  merely because the UOM authority accepts fractional quantities.
- **Mixed-product kits / bundles / assemblies:** one outer package containing
  different SKUs needs constituent-product and inventory semantics, e.g. a
  BOM/kit authority. A one-SKU conversion factor cannot represent it.
- **Physical shipping packages and nested handling units:** pallets/cartons
  containing heterogeneous goods or nested shipping containers are logistics
  objects, not synonyms for a saleable UOM. Their IDs, locations, dimensions,
  weight and nested contents need their own warehouse workflow.
- **Company-defined terminology:** business display labels and translations
  must remain distinct from canonical UOM identity and exact conversion
  factors. A company catalog must be a single authority, not independent
  free-text selectors in importer and dashboard.

Each of these capabilities needs a separate scope decision and verified
end-to-end gates before it is exposed as available. Keeping its planning
here does not expand the V1 Product Import contract.

---

## 7. ERP-derived V2 roadmap — scope-separated, company-adaptive workflows

**Product design principle (permanent):** Do **not** copy enterprise ERP
screens. Build the canonical data/authority model to represent the necessary
business cases, then expose **only the capabilities a company needs**. A
distributor selling cartons of juice should not have to configure industrial
weight tolerances, nested shipping containers or assembly BOMs to create an
ordinary Product. Simple flows remain the default; advanced paths are
intentional, discoverable and separately permissioned.

These are reference-driven **backlog items, not present V1 features**. Do not
enable a menu because a database table, endpoint, or unit-conversion graph
exists; require a complete end-to-end workflow and verified gates.

### 7.1 Company-facing unit and package catalog (extends section 3)

- [ ] Maintain stable language-neutral unit identity separately from
  business labels, aliases, translations and company-specific availability.
  Supply safe platform defaults with company-level enable/retire choices;
  referenced historical identities cannot be hard-deleted.
- [ ] Evaluate separate **stock / purchase / sale unit defaults**, as in
  NetSuite, but do not conflate defaults with the canonical stock quantity.
  Explicitly define conversions, prices, rounding, purchase/receipt/stock/
  sale behavior, and audit on every consuming workflow.
- [ ] Design product-specific **commercial packaging** separately from
  physical logistic handling units. In Odoo, a saleable packaging has a
  product-specific contained quantity and barcode, while a physical package
  may contain multiple goods and is used for storage/shipping.
- [ ] Keep units that measure dimension (mass/length/volume), quantity
  precision/step, display localization, and business-packaging names
  semantically distinct.

### 7.2 Multiple commercial packaging levels (Advanced UOM)

- [ ] Expose an intentional advanced Product Draft -> Configure ->
  Review -> Publish workflow that connects the existing conversion graph
  and Catalog authority to Product, Pricing, Barcode, Sales and Warehouse.
- [ ] Define one exact, non-ambiguous conversion graph per variant; for
  example **1 box = 10 pieces, 1 layer = 8 boxes, 1 pallet = 4 layers**
  (SAP packaging hierarchy). Guard against conflicting routes, precision
  loss, cycles with inconsistent factors, and incompatible quantity steps.
- [ ] Decide unit-specific barcode/GTIN ownership, ordering/receiving/
  picking unit defaults and display before allowing more than one outer
  package to be sold. This is more than enabling a second dropdown.
- [ ] Product variants may have distinct conversion ratios (Dynamics
  example: the same shirt boxed 5-to-a-box for one size, 4-to-a-box for
  another). Resolve conversion authority per variant, not by display label.
- [ ] Preserve structural locking after publication until a separately
  approved versioned Product-change/migration workflow exists.

### 7.3 Independent business domains — do not hide behind Advanced UOM

- [ ] **Catch-weight / variable-weight:** nominal vs actual measured
  quantities, capture at receipt/pick/count/transfer, tolerance bands,
  cost/price basis and stock-value reconciliation. Decimal quantities and
  UOM scale alone are not implementation proof.
- [ ] **Mixed SKU packs / kits / assemblies (BOM):** component identities,
  quantity/cost/inventory accounting, assembly/disassembly, stock
  reservation and sales semantics. A single-product conversion factor
  cannot represent mixed goods.
- [ ] **Physical packages / shipping handling units:** package identity,
  nesting, mixed contents, pallet locations, gross/net weights,
  dimensions, scanners and shipping-label workflows. A commercial
  "carton of 24" is not automatically a tracked physical carton.
- [ ] Treat all of the above as **separate capability decisions**. Do not
  promise them as soon as Advanced UOM is enabled.

### 7.4 ERP comparison — take the pattern, not the UI

- **Odoo:** separate units of measure, product-specific packaging, and
  physical packages; do not name all three simply "package".
- **SAP:** use explicit multi-level packaging hierarchies and
  deterministic unit conversions; keep the current single-level V1 flow.
- **NetSuite:** consider purchase, stock and sale UOM defaults and their
  lifecycle constraints; avoid three unrelated measures of inventory truth.
- **Dynamics 365:** separate localized unit labels, product-/variant-level
  conversion factors, and catch-weight processing.
- **ERPNext / import UX pattern:** use human-readable field guidance,
  original source-row numbers and deterministic correction artifacts.
  V1 import UX/inline repair tasks live in
  `docs/operations/PRODUCT_IMPORT_FINAL_ACCEPTANCE_2026-10-02.md`; only deferred V2 scale work belongs here.

**Authoritative source examples:**
- Odoo product packaging: https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/product_management/configure/packaging.html
- Odoo physical packages: https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/product_management/configure/package.html
- SAP packaging hierarchy: https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9905622a5c1f49ba84e9076fc83a9c2c/6289c4535cdeb44ce10000000a174cb4.html
- NetSuite item UOM defaults: https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2212390.html
- Dynamics unit/localization setup: https://learn.microsoft.com/en-us/dynamics365/supply-chain/pim/tasks/manage-unit-measure
- Dynamics per-variant conversions: https://learn.microsoft.com/en-us/dynamics365/supply-chain/pim/uom-conversion-per-product-variant
- Dynamics catch weight: https://learn.microsoft.com/en-us/dynamics365/supply-chain/warehousing/catch-weight-processing
- ERPNext data-import UX: https://docs.frappe.io/erpnext/data-import

---

## 8. Multi-company high-scale qualification — deferred from the V1 import audit

**Owner decision (2026-09-30):** V1 launches for **one company**. The goal of
1,000 *simultaneously active* real HTTP clients, large multi-tenant staging,
independent external load generators, production-like hardware profiling and
horizontal autoscaling is not the launch gate for that first company. These
items are **deferred, not implemented or tested**. The original source-first
The closed V1 engineering baseline, final real-Dashboard evidence, D3 health and D4 recovery closure are summarized in [`docs/operations/PRODUCT_IMPORT_FINAL_ACCEPTANCE_2026-10-02.md`](docs/operations/PRODUCT_IMPORT_FINAL_ACCEPTANCE_2026-10-02.md). The preserved opt-in external scale tool and operator constraints remain in [`docs/operations/WANASAH_D7S_MIXED_LOAD_TOOL.md`](docs/operations/WANASAH_D7S_MIXED_LOAD_TOOL.md).
Do not reinterpret the historical 1,000 *arrivals* with a 10/20-client
ASGI semaphore as 1,000 simultaneously open real TCP connections.

- [ ] **V2-SCALE-1 / original D7-S and L:** On an independently approved
  production-like multi-company environment, measure 1,000 actually
  simultaneous HTTP/TLS connections and a separate 1,000-arrival burst.
  Verify *server-observed* active connections, real admission/429/retry-after,
  p50/p95/p99 including ingress queues, max DB clients, CPU, RAM, WAL,
  backlog age, per-company fairness, cross-company RLS denial and all
  Product/Price/Audit/Outbox + Sale/COGS + stock + route invariants.
  Load must be bounded and synthetically owned, not pointed at customers.
  The isolated mixed-load-driver task is GitHub issue **#38**; its implementation
  alone does NOT mean the environment-dependent gate passed.
  The preserved, named optional operator tool is
  `wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py`, documented in
  `docs/operations/WANASAH_D7S_MIXED_LOAD_TOOL.md`. Its mock contract tests pass,
  but this does **not** close the real ingress/DB/finance acceptance gate.
- [ ] **V2-SCALE-2 / original B:** Use the already-installed opt-in per-batch
  SQLAlchemy/ORM/flush profiler under 50k realistic XLSX and DB cardinality.
  Identify real dominant cost before considering bulk ORM/flush rewrites;
  preserve draft-to-active lifecycle, generated IDs, barcode/UOM, price,
  audit, outbox and crash-safe idempotent replay. No mass bulk shortcut
  based only on estimated flush counts.
- [ ] **V2-SCALE-3 / original G:** Quantify B-tree/GIN/TRGM/GiST growth,
  pending lists, page utilization and autovacuum/WAL under sustained
  realistic churn. Retain SKU uniqueness, effective price exclusion,
  barcode indexes, tenant-aware planner/search contracts and append-only
  historical evidence. No unsafe index drops or blind REINDEX.
- [ ] **V2-SCALE-4 / original I:** Correlate instrumented Python CPU,
  ORM object changes, cursor/driver latency, server-side SQL,
  lock-wait duration, WAL, network, validation, transaction commits and
  queue/ingress wait under comparable production-sized fixture loads.
  Do not equate client cursor wall time to database CPU, nor subtract
  wall time to guess Python CPU.
- [ ] **V2-SCALE-5 / original D/E scale extensions:** Measure Live Stock
  summary lock/blocker durations, pool lifetimes and lock order under
  sustained *multi-company* burst/worker scaling, establish host-specific
  total PostgreSQL connection budget, then consider throughput-only
  scheduling, batching, partitioning or horizontal scaling. Never remove
  transaction/tenant/location locks merely for a throughput target.
- [ ] **V2-SCALE-6 / original large-deployment D8 extension:** Full-size
  anonymized staging restore times, sustained multi-worker rolling deploy,
  remote ingress/CDN throughput tuning and tested scale rollback.
  Do not claim the current local synthetic three-row backup test proves
  this environment-specific qualification.

**Not deferred:** first-company Product Import correctness, tenant/company
isolation, pricing/COGS/stock integrity, permissions, durable retry/cancel/
worker crash behavior, no unbounded transactions or leaks, basic lock-order
safety, real browser network behavior, valid backup/restore of the actual
deployment and minimal operational monitoring. These remain V1 deployment
checks in `docs/operations/PRODUCT_IMPORT_V1_RELEASE_RUNBOOK_2026-09-30.md`.
A passing unit/smoke test does not replace business evidence or deployment
sign-off. Deferral is an honest scope decision, not a green test result.

---

## 9. Preservation rule

This file is intentional product/architecture scope, not a temporary handoff note.

**Do not delete, archive, rename ambiguously, or mark these items complete unless the Version 2 workflows have actually been implemented and verified.**
