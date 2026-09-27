# Wanasah Version 2 — Deferred Product Capabilities

**Status:** CANONICAL V2 BACKLOG — DO NOT DELETE OR ARCHIVE AS TEMPORARY NOTES  
**Scope:** Product capabilities intentionally deferred from Version 1  
**Last updated:** 2026-09-27

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

## 4. Version 1 UI policy for deferred features

For both deferred capabilities:

- keep the Catalog Tools items visible;
- render them disabled;
- show a concise “planned for Version 2 / later stage” explanation;
- do not navigate to their routes from the normal V1 UI;
- do not delete existing routes, backend code, migrations, contracts, or gates;
- do not represent them as finished V1 functionality;
- any future re-enable must start from this document and reconcile it with the then-current backend and architecture.

---

## 5. Preservation rule

This file is intentional product/architecture scope, not a temporary handoff note.

**Do not delete, archive, rename ambiguously, or mark these items complete unless the Version 2 workflows have actually been implemented and verified.**
