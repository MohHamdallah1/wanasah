# Products P9 — Current-Behavior Baseline

**Status:** FROZEN REFERENCE BEFORE FRONTEND REFACTOR  
**Runtime checkpoint:** `3fdc702170a85b7808c220643430b76b283d7528`  
**Scope:** normal Products page, its page-owned Product components, and the backend authorities it consumes or may intentionally expose later.

This file is the behavioral reference for P9. Structural extraction must preserve these behaviors exactly unless a later P9 task explicitly changes behavior and adds its own tests.

---

## 1. Current frontend ownership

The route entry `dashboard/src/pages/ProductsDashboard.tsx` currently has about 5,490 lines and combines several unrelated responsibilities:

- page composition and layout;
- Product list query/pagination;
- search/filter/sort state;
- permission-derived capabilities;
- create-product state and validation;
- draft persistence;
- price editing;
- company tracking defaults;
- per-product tracking editing;
- import upload/mapping/poll/retry;
- display-preference coordination;
- opening Product details, families, barcodes, lifecycle, and advanced-unit flows.

Existing page-owned Product components already separate some responsibilities:

- `ProductDetailDrawer.tsx` — read/details + action launch points;
- `ProductTableRow.tsx` — desktop row presentation;
- `ProductMobileCard.tsx` — narrow-screen presentation;
- `ProductFamiliesManager.tsx` — family list/create/rename;
- `ProductBarcodeManager.tsx` — barcode history/create/deactivate;
- `ProductLifecycleManager.tsx` — resolves the authoritative Catalog variant then delegates lifecycle actions;
- `ProductTrackingEditor.tsx` — per-product tracking editor presentation;
- `ProductTrackingSettings.tsx` — company tracking-default presentation;
- `ProductTrackingFields.tsx` — shared tracking controls;
- `ProductDisplayPreferences.tsx` — user display preferences;
- `AdvancedUomDashboard.tsx` — advanced unit/conversion workflow;
- `contracts.ts` — strict runtime parsing for Product-facing API contracts.

P9 refactoring must reduce the responsibilities of `ProductsDashboard.tsx` without creating a new large multi-responsibility component or hook.

---

## 2. Frozen list/read behavior

### Main Product query

Current page query key:

`["simple-products", companyId, params]`

Current endpoint:

`GET /simple-products`

Current request behavior:

- page size: 100;
- server cursor pagination;
- search activates only after trimmed input reaches 2 characters;
- search debounce: 250 ms;
- changing search resets cursor/history;
- filters are sent to the backend before pagination;
- sort is server-side.

Current filters:

- family;
- lifecycle;
- tracking type;
- simple-compatible;
- has barcode;
- has price, only when pricing is visible to the current user;
- lot tracked;
- expiry tracked.

Current sort fields:

- id;
- name;
- family;
- SKU;
- lifecycle.

Sort direction:

- ascending;
- descending.

Current Product read contract includes:

- variant id;
- underlying family/product id;
- user-visible variant name;
- family name;
- SKU;
- package/unit shape;
- exact decimal prices when authorized;
- unit/package primary barcodes;
- version;
- lot tracking mode;
- expiry tracking mode;
- lifecycle state;
- operational hold;
- simple-workflow compatibility.

The page must continue failing closed if the runtime contract is malformed.

### Family queries

Current family filter/options queries are tenant-scoped and server-paginated.

- filter list page size: 50;
- create-product family suggestions page size: 20;
- family search debounce: 250 ms;
- family manager itself uses bounded cursor pagination.

### Package-unit references

`GET /simple-products/package-uoms`

Used to validate and render the supported simple package-unit choices.

### Tracking defaults

`GET /simple-products/tracking/defaults`

Used to initialize Product creation and new import sessions without rewriting existing Products.

---

## 3. Frozen permission behavior

Current page derives capabilities from backend-authorized permissions.

Normal Product read:

- catalog read authority is required by the backend.

Price visibility:

- company admin or `pricing.view`;
- hidden pricing must not leak through the Product response;
- price filters are cleared/disabled when pricing is not visible.

Simple Product creation/import currently requires:

- company admin, or
- `catalog.manage` + `catalog.publish` + `pricing.manage`.

Family management:

- company admin or `catalog.manage`.

Price editing:

- company admin or `pricing.manage`.

Lifecycle actions are individually controlled by:

- `catalog.retire`;
- `catalog.restore`;
- `catalog.archive`;
- `catalog.hold`;
- company admin override.

Tracking mutation:

- `catalog.manage`.

Advanced unit/conversion management:

- `catalog.manage`;
- read side uses `catalog.read`.

Product-location capabilities are separately protected by location-scoped:

- `product_location.read`;
- `product_location.manage`.

P9 must not replace these granular capabilities with one coarse "manage products" boolean.

---

## 4. Frozen persistence and recovery behavior

### Product draft

Current session key:

`wanasah:product-draft:v2:<company_id>:<driver_id>`

Behavior:

- draft is restored only inside the matching company/user scope;
- corrupt JSON is discarded;
- draft is updated in session storage as the user edits;
- successful create removes the draft;
- explicit cancel clears the draft and abandons the outstanding durable create operation.

### Import resume

Current session key:

`wanasah:product-import:v1:<company_id>:<driver_id>`

Behavior:

- accepted import stores the job id;
- reopening the page can resume the same import job;
- choosing a new file clears the previous job session;
- reset clears import state and the saved job id.

### Display preferences

Display preferences remain separate from business defaults.

They are versioned/scoped by authenticated company + user identity and cannot grant pricing permission or other business authority.

---

## 5. Frozen durable-operation identities

The following durable scopes are part of current behavior and must not change accidentally during extraction.

### Main Products page

- `product-tracking-defaults`;
- `product-tracking:<variant_id>`;
- `product-create`;
- `product-price:<variant_id>`;
- `product-import:<file fingerprint + tracking defaults>`.

### Families

- `family-create`;
- `family-rename:<family_id>`.

### Barcodes

- `catalog-barcode-create-v2:<variant_id>`;
- `catalog-barcode-update:<barcode_id>`.

### Lifecycle

- `catalog-lifecycle-command-v1:<variant_id>`.

### Advanced unit conversions

- create/update durable scopes remain owned by the Advanced-unit workflow and must preserve their existing request identity and optimistic-version behavior.

Rules preserved during refactor:

- the same ambiguous request must retry with the same durable request id and exact payload;
- a corrupt persisted durable command fails closed;
- a successful mutation completes the durable operation;
- only safe, non-ambiguous failures may abandon a pending operation.

---

## 6. Frozen mutation/cache behavior

### Company tracking defaults

`PUT /simple-products/tracking/defaults`

- durable request identity;
- runtime response parser;
- on success, closes settings and updates current import defaults when no import job is already in progress;
- invalidates `simple-product-tracking-defaults`.

### Product tracking

`PATCH /simple-products/tracking/variants/<variant_id>`

- sends `expected_version`;
- durable request identity;
- runtime response parser;
- invalidates `simple-products`.

### Create Product

`POST /simple-products`

Current simple-create contract includes:

- name;
- existing family id OR new family name;
- package-unit code or no package;
- units per package;
- package and/or unit price;
- unit barcode;
- package barcode;
- explicit lot tracking;
- explicit expiry tracking.

Behavior:

- exact-money derivation/validation remains exact decimal, not float-based;
- selected existing family is resolved from server family options;
- otherwise a non-empty family text becomes a new family name;
- package selection is validated against the server package-unit response;
- durable request identity;
- strict runtime parser;
- on success clears draft, closes create UI, resets list pagination, invalidates Product and family caches.

Important backend behavior:

- the Simple Products service creates the structure as DRAFT internally and publishes it in the same simple workflow;
- therefore ordinary Quick Create returns a published Product, not a user-managed draft.

### Price update

`PATCH /simple-products/<variant_id>/price`

- only the simple-compatible pricing path is used;
- exact decimal values;
- permission-gated;
- durable request identity;
- strict runtime parser;
- Product cache refresh after success.

### Product import

Create:

`POST /simple-products/imports`

- CSV/XLSX only;
- durable request scope includes file fingerprint and selected import tracking defaults;
- accepted job id is saved for resume.

Status:

`GET /simple-products/imports/<job_id>`

Polling behavior:

- active polling interval: about 1.5 seconds;
- offline/error retry interval: about 3 seconds;
- polling cleanup prevents state writes after effect disposal;
- completed import refreshes Product and family caches.

Mapping:

`PUT /simple-products/imports/<job_id>/mapping`

Retry:

`POST /simple-products/imports/<job_id>/retry`

Error download:

`GET /simple-products/imports/<job_id>/errors?after_row=...&limit=1000`

- error report is read in bounded pages;
- frontend localizes known stable error codes rather than relying on backend presentation text.

---

## 7. Frozen request-race and cancellation behavior

These protections must survive any file split.

- Product list/family/package/tracking queries use React Query cancellation signals where provided.
- Barcode manager uses `AbortController` + request-sequence validation so a response from Product A cannot overwrite Product B after selection changes.
- Advanced Catalog identity loading has an A→B stale-write regression gate.
- Import polling stops writes after disposal.
- Runtime responses are checked for scope mismatches before committing UI state.
- optimistic `expected_version` checks remain part of mutable Catalog/Tracking/Family workflows.

---

## 8. Current normal Products-page functions

Currently available to the user, subject to permissions:

- browse Products;
- search by Product/family/SKU/barcode;
- server filters and sorting;
- next/previous cursor navigation;
- Product details;
- Quick Create;
- package/no-package creation;
- exact price entry/derivation;
- unit/package barcodes during creation;
- per-Product tracking selection;
- company tracking defaults;
- Product tracking editing;
- family search;
- family creation;
- family rename;
- price editing;
- barcode history;
- barcode creation;
- barcode deactivation without erasing history;
- lifecycle/hold management for Products that the normal list can reach;
- advanced unit/conversion page for applicable Products;
- bulk import/mapping/status/retry/error export;
- user display preferences;
- responsive mobile cards;
- RTL/LTR, accessibility, translated Product UI.

---

## 9. Backend-to-frontend capability matrix

| Backend capability | Backend authority | Current normal Products page | P9 classification / decision |
| --- | --- | --- | --- |
| Product list/search/filter/sort | Simple Products | Present | Normal Products — keep |
| Family list/search | Simple Products | Present | Normal Products — keep |
| Family create | Simple Products | Present | Normal Products — keep |
| Family rename | Simple Products | Present | Normal Products — keep |
| Simple Product create | Simple Products facade | Present | Normal Products — keep |
| Simple price update | Simple Products + Pricing | Present | Normal Products — keep |
| Company lot/expiry defaults | Product Tracking | Present | Normal Products — keep |
| Per-Product lot/expiry update | Product Tracking | Present | Normal Products — keep |
| Import create/status/mapping/retry/errors | Simple Products | Present | Normal Products — keep |
| Barcode list/create/deactivate | Catalog | Present | Normal Products — keep |
| GS1 parse helper | Catalog | Not used | Advanced/convenience only unless final barcode UX needs scanner/parse preview |
| Lifecycle retire/restore-from-retiring/archive/hold/recall | Catalog | Present where listed state is reachable | Normal Products — keep |
| Restore an ARCHIVED Product | Catalog | Backend supports it; normal list does not return ARCHIVED | Functional gap/decision: normal page must intentionally expose archived Products or document an advanced-only restore path |
| Publish a DRAFT | Catalog | Not reachable from normal page | Advanced Catalog only unless P9 introduces a draft workflow; Quick Create already auto-publishes |
| Permanently delete unused DRAFT | Catalog | Not reachable from normal page | Advanced/draft-only. Backend already blocks deletion when operational references exist |
| Catalog Product/family code | Catalog Product | Not exposed by normal family manager | Decide in P9 family metadata UX |
| Catalog Product/family description | Catalog Product | Not exposed | Advanced/family metadata decision |
| Catalog Product/family brand/category | Catalog Product | Not exposed | Advanced/family metadata decision |
| Edit variant display name while DRAFT | Catalog Variant | Backend supports only DRAFT | Advanced/draft path |
| Edit published variant display name | No safe published-edit command today | Missing | **Real P9 backend + UI gap** — owner requires normal Product rename |
| Move DRAFT variant to another family | Catalog Variant | Backend supports only DRAFT | Advanced/draft path |
| Move published variant to another family | No safe published structural command today | Missing | **Real P9 decision/gap** — must define safe history behavior before exposing |
| Edit SKU/GTIN while DRAFT | Catalog Variant | Not in normal page | Advanced/draft path |
| Edit SKU/GTIN after publish | Catalog Variant explicitly locks structural edit | Not available | Keep locked unless a separate safe business command is designed |
| Edit base unit / quantity precision / quantity step while DRAFT | Catalog Variant | Not in normal page | Advanced/draft path |
| Read Product base unit in plain language | Catalog/Simple Product data | Normal contract currently exposes id, package code, conversion count/factor but Product Details does not fully explain base unit | **P9 presentation gap** |
| Edit simple package structure after publish | Existing Catalog conversion mutation is DRAFT-only | Incomplete | **P9 backend-policy/UI gap**; never bypass history locks |
| Advanced conversion list/create/update | Catalog | Advanced unit page exists | Advanced Products — keep separated |
| Full price books/publications/entries/assignments | Pricing | Not in normal Products page | Intentionally advanced Pricing administration; normal Products uses the simple price facade |
| Product-location list/create/update/delete | Product Locations | Not directly exposed in normal Products | P9 audit: advanced/read-only/operator action only where genuinely useful; remain location-scoped |
| Catalog raw Product/Variant list | Catalog | Used only by advanced/lifecycle support flows | Internal/Advanced; normal page should keep the simpler facade |
| Catalog raw Product/Variant creation | Catalog | Not normal page | Advanced Catalog only; do not duplicate Quick Create |
| Display preferences | Frontend user preference authority | Present | Normal Products — keep, never treat as business policy |

---

## 10. Critical identity mapping discovered by P9.0

The Simple Products facade uses two different records:

- **variant name** = the user-visible Product/SKU name shown in the normal Product list;
- **underlying Catalog Product name** = the family name exposed by the Simple Products facade.

Therefore:

- renaming a family is **not** the same operation as renaming the user-visible Product;
- calling the Catalog Product update route to "rename the Product" would actually rename the family identity in the Simple Products model;
- moving a Product to another family means changing the variant's `product_id`, not renaming the family;
- P9 must preserve this distinction in code, UI copy, and tests.

This is a release-critical refactor invariant.

---

## 11. Confirmed functional gaps before visual redesign

P9 currently has these real functional/decision gaps:

1. Safe rename of a published user-visible Product is missing.
2. Safe family reassignment for a published Product is missing and requires explicit history/lifecycle policy.
3. Archived Products are not reachable from the normal list, even though backend restore supports ARCHIVED.
4. Normal Product Details does not explain the base unit/package conversion clearly enough.
5. Safe post-publication package-structure editing is incomplete; existing Catalog structural editing is intentionally DRAFT-only.
6. Family-level Catalog metadata (code/description/brand/category) exists but has no final normal/advanced UX decision.
7. Product-location capabilities exist but are not intentionally represented in the normal Product experience.
8. Draft publish/delete capabilities exist in backend but are intentionally unreachable from Quick Create; final P9 must document whether they remain advanced-only.
9. GS1 parsing exists as a backend helper but is not used by the current barcode UI; final barcode UX must intentionally keep or ignore it.
10. `ProductsDashboard.tsx` itself remains a high-risk multi-responsibility change surface and requires behavior-preserving extraction before the final visual rebuild.

No visual redesign should begin until the functional gaps selected for normal Products are resolved.

---

## 12. Test baseline frozen before structural extraction

Current Product-specific frontend regression inventory contains 16 Product-focused test files with 94 declared tests covering:

- runtime Product read contracts;
- Product search/family pagination;
- Product table exact-number formatting;
- Product details/permission-aware actions;
- tracking defaults/create/edit/import;
- family durable create/rename;
- barcode race protection and durable retries;
- Catalog identity A→B stale-write protection;
- import localization;
- accessibility;
- RTL/LTR;
- responsive behavior;
- display preferences;
- production mutation contracts and lifecycle wiring.

Latest verified full Dashboard baseline before P9 structural work:

- 31 test files passed;
- 188 tests passed;
- production build passed;
- TypeScript passed in the aggregate gate;
- lint passed with zero warnings in the aggregate gate.

Latest verified Product aggregate production gate:

- 17 checks;
- 0 failures;
- `PRODUCTS_P8_PRODUCTION_GATE=PASS`.

Backend aggregate gate includes 13 Product-related backend gates covering:

- error/runtime contracts;
- Product UX/i18n/network;
- read contract;
- search/families;
- package/unit safety;
- import localization;
- Product tracking;
- lifecycle;
- performance;
- price-publication scale;
- isolation;
- concurrency/idempotency;
- existing-Product audit.

These are the minimum regression floor. P9 may add tests, but structural extraction must not weaken or remove this coverage.

---

## 13. P9.0 completion rule

P9.0 is complete when this file and the active plan agree that:

- current behavior is frozen;
- current tests are recorded;
- backend capabilities are classified;
- missing Product-page functions are explicit;
- no runtime behavior or visual design was changed during the audit.

The next step after P9.0 is **P9.1 functional completion**, not visual redesign and not file splitting by guesswork.
