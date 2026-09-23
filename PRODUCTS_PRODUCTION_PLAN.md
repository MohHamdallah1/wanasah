# Wanasah — Products Production-Readiness Plan
الخطة الرئيسية لصفحة المنتجات Products

> **Purpose**
>
> This file is the authoritative execution plan for taking the **Products** area of Wanasah from its current "Simple Products" experience to a production-ready product-management experience.
>
> It is intentionally standalone so a new ChatGPT conversation can continue the work without needing prior chat history.

---

# 1. Status convention

Use these markers only:

- `[ ]` Not started
- `[~]` In progress
- `[x]` Completed and verified
- `[!]` Blocked / requires an explicit product or engineering decision

**Rule:** Do not mark an implementation item `[x]` until:
1. code is complete,
2. relevant tests/gates pass,
3. regression review is complete,
4. Git diff is clean and intentional.

---

# 2. Non-negotiable engineering rules

## 2.1 Tenant / company isolation

- Every database read/write must be explicitly company-scoped where applicable.
- Product-related warehouse facts must also be explicitly location-scoped when applicable.
- RLS is defense-in-depth, not a substitute for explicit query scoping.
- Never build a global candidate set and tenant-filter afterward.
- Permission checks must occur before exposing protected data.
- Cross-company IDs must fail closed.

## 2.2 Correctness

- No guessing.
- No shortcuts.
- No silent fallbacks that weaken business rules.
- No duplicated business authority in React.
- Backend remains authoritative for:
  - lifecycle,
  - pricing,
  - UOM conversions,
  - product tracking,
  - barcodes,
  - warehouse eligibility,
  - inventory mutation rules.

## 2.3 Technical debt

- Do not introduce temporary workarounds that we already know must be replaced.
- Prefer a clean contract change over duplicating logic.
- Do not optimize query count just for a smaller number. Measure latency, DB work, bounded scale, and maintainability.
- Add indexes only from measured query-plan evidence.

## 2.4 UX

- Minimize user effort.
- Do not expose backend complexity unnecessarily.
- Do not hide important business consequences.
- Quick workflows and advanced workflows may coexist.
- Keep the default experience simple for ordinary companies and users.

## 2.5 Internationalization / localization

Every Products change must be i18n-ready from day one:

- no new user-facing hardcoded Arabic/English strings in React,
- stable translation keys,
- RTL + LTR support,
- no logic based on translated message text,
- backend contracts use stable codes/enums,
- dates/numbers/money rendered through locale-aware formatters,
- no binary `"ar" ? "ar-JO" : "en-US"` locale assumptions.

---

# 3. Architectural dependency order

The inventory product flow must be stabilized in this order:

1. **Products**
2. **Inbound / Goods Receipt**
3. **Batches & Expiry**

Reason:

- Products define whether a SKU uses lot tracking and/or expiry tracking.
- Inbound applies those rules when stock is received and creates/uses `ProductBatch`.
- Batches & Expiry consumes and manages the resulting batch/expiry data.

Do **not** finalize Inbound or Batches & Expiry before the Products tracking contract is frozen.

---

# 4. Current critical defect — fix first

## 4.1 Silent forced tracking

Current `domains/simple_products/service.py` creates every new product with:

```python
lot_control_mode="REQUIRED"
expiry_control_mode="REQUIRED"
```

The user is not told this and cannot choose another behavior in the simple Products UI.

This means the current UI silently treats every product as:

- requiring a lot/batch number,
- requiring an expiry date,

even when the product type does not logically require either.

Examples of products that may reasonably use no expiry tracking:

- spare parts,
- screws / hardware,
- stationery,
- reusable plasticware,
- packaging material,
- non-expiring accessories.

The current behavior is acceptable only accidentally for food-oriented companies. It is **not** acceptable as a multi-company product platform default.

### Required fix

- [x] Remove the silent hardcoded `REQUIRED / REQUIRED` assumption from the simple product creation authority.
- [x] Make lot tracking an explicit product property:
  - `NONE`
  - `OPTIONAL`
  - `REQUIRED`
- [x] Make expiry tracking an explicit product property:
  - `NONE`
  - `OPTIONAL`
  - `REQUIRED`
- [x] Let each company define sensible creation defaults.
- [x] Allow each product to override those defaults.
- [ ] Do not force a user to invent a lot number for a `lot_control_mode=NONE` product.
- [ ] Do not ask for expiry information for `expiry_control_mode=NONE`.
- [x] Preserve backend enum values as language-neutral codes.
- [x] Translate labels/descriptions only in the UI.

---

# 5. Tracking-mode product design

## 5.1 Lot tracking

Meaning of `lot_control_mode`:

### `NONE`
The user does not manage supplier/manufacturer lot numbers for the SKU.

- [x] UI does not require a lot number during product creation.
- [ ] Inbound does not require a user-entered lot number.
- [x] Define the safe internal batch identity strategy used by inventory storage.
- [x] Internal identity must not be exposed as if it were a real supplier batch number.

### `OPTIONAL`
Lot number may be captured when provided.

- [ ] Inbound accepts an empty lot.
- [ ] Inbound accepts a real lot.
- [ ] Existing-lot conflict behavior remains deterministic.
- [x] UX clearly explains that lot is optional.

### `REQUIRED`
Every received stock line requires a lot.

- [ ] Inbound rejects missing lot number.
- [x] UI marks lot clearly as required.
- [ ] Bulk import and integrations follow the same rule.

## 5.2 Expiry tracking

Meaning of `expiry_control_mode`:

### `NONE`
The product is not expiration-tracked.

- [ ] Inbound hides or disables expiry date.
- [ ] Backend rejects expiry date if the contract requires strict NONE semantics.
- [ ] Batches/expiry page does not misleadingly show a required expiry state.

### `OPTIONAL`
Expiry can be captured when known.

- [ ] Inbound permits missing expiry.
- [ ] Inbound permits valid expiry.
- [ ] Batches page clearly distinguishes "no expiry supplied" from "expired".

### `REQUIRED`
Every relevant received batch requires expiry.

- [ ] Inbound rejects missing expiry.
- [x] UI marks expiry required.
- [ ] Bulk import follows the same rule.

## 5.3 Company defaults

- [x] Add a safe company-level default for lot tracking.
- [x] Add a safe company-level default for expiry tracking.
- [x] Product creation starts from company defaults.
- [x] User can override defaults per SKU when authorized.
- [x] Defaults affect future product creation only unless an explicit migration workflow is used.
- [x] Defaults never silently rewrite existing products.

---

# 6. Editing tracking settings after inventory exists

Tracking configuration is not an ordinary cosmetic field.

Changing:

- `REQUIRED → NONE`
- `NONE → REQUIRED`
- `OPTIONAL → REQUIRED`

after inventory/history exists can affect inbound, batch identity, allocation, FEFO, and audit semantics.

Required design:

- [x] Determine which tracking-mode transitions are safe before first inventory activity.
- [x] Determine which transitions are blocked after first inventory activity.
- [ ] Determine whether any transitions require a controlled migration workflow.
- [x] Add backend validation that enforces the rule, not only frontend disabling.
- [x] UI explains why a tracking option becomes locked.
- [x] Never allow a destructive tracking change through a normal PATCH.

---

# 7. Products page scope

Current user-facing page:
`dashboard/src/pages/ProductsDashboard.tsx`

Current backend facade:
- `wa_backend/api/simple_products.py`
- `wa_backend/domains/simple_products/service.py`

Deeper catalog authority already exists:
- `wa_backend/api/catalog.py`
- catalog lifecycle / UOM / barcode authorities

**Goal:** keep the normal Products page easy to use while surfacing the important backend capabilities safely.

Do not simply expose the technical Catalog page to ordinary users.

---

# 8. Product creation — contract foundation

## 8.1 Product identity

Product creation must support, as appropriate:

- [ ] Product/SKU name.
- [ ] Product family.
- [ ] SKU/code strategy.
- [ ] Base UOM.
- [ ] Outer/package UOM.
- [ ] Units per package.
- [ ] Unit barcode.
- [ ] Package barcode.
- [ ] Shared barcode behavior where supported.
- [ ] Lot tracking mode.
- [ ] Expiry tracking mode.
- [ ] Initial lifecycle policy.
- [ ] Initial pricing only when the user has pricing permission.

## 8.2 Quick Create vs Advanced

Default user experience:

### Quick Create
Keep ordinary creation easy.

- [ ] Product name.
- [ ] Family.
- [ ] Package shape.
- [ ] Units per package.
- [ ] Price when authorized.
- [x] Tracking controls expressed in plain language.

### Advanced
Optional expandable section:

- [ ] SKU/code.
- [ ] Barcodes.
- [ ] tracking details.
- [ ] UOM details.
- [ ] lifecycle behavior.
- [ ] other future product policies.

No user should be forced through 20 fields to create a simple product.

---

# 9. Product tracking UX

Do not expose technical names such as `lot_control_mode` to ordinary users.

Suggested UX wording:

**Batch/Lot tracking**
- Does not use batch numbers
- Batch number is optional
- Batch number is required

**Expiry tracking**
- No expiry tracking
- Expiry date is optional
- Expiry date is required

Required:

- [x] Explanatory helper text.
- [x] Clear consequences for Inbound.
- [x] Sensible company default preselection.
- [x] No hidden system choice.
- [x] Fully translated labels/options.

---

# 10. Product editing after creation

The current normal Products page mainly exposes price editing.

Production-ready Products must provide safe identity management.

- [ ] Edit display name where allowed.
- [ ] Move/change family where allowed.
- [ ] View SKU.
- [ ] Edit/manage barcodes through authoritative barcode workflow.
- [ ] View package/UOM structure.
- [ ] Manage simple-compatible package shape safely.
- [x] View tracking modes.
- [x] Edit tracking modes only when lifecycle/inventory rules allow.
- [ ] View lifecycle status.
- [ ] View operational hold.
- [ ] View simple/advanced compatibility.
- [x] Explain why some fields are locked.

---

# 11. Product detail drawer

Do not make the main table carry every product fact.

Add a Product Detail Drawer / Side Panel.

Suggested sections:

## Identity
- [ ] Name.
- [ ] Family.
- [ ] SKU.
- [ ] Product/variant IDs only when useful for support/admin.

## Packaging & UOM
- [ ] Base UOM.
- [ ] Package UOM.
- [ ] Units per package.
- [ ] Conversion information.

## Barcodes
- [ ] Unit barcode.
- [ ] Package barcode.
- [ ] Primary/active state.

## Tracking
- [ ] Lot tracking mode.
- [ ] Expiry tracking mode.

## Lifecycle
- [ ] ACTIVE / RETIRING / etc.
- [ ] Operational hold.
- [ ] Allowed lifecycle actions.

## Pricing
- [ ] Current prices only when authorized.
- [ ] Advanced pricing link only when actually usable.

## Inventory relationship
Later:
- [ ] Assigned/used warehouses where useful.
- [ ] Current stock summary where useful.

---

# 12. Product lifecycle

Backend already contains product lifecycle authority.

UI must reflect it safely.

- [ ] Show lifecycle status.
- [ ] Translate lifecycle codes via i18n.
- [ ] Show operational hold.
- [ ] Provide permitted lifecycle actions.
- [ ] Retire/disable/archive workflow must explain operational impact.
- [ ] Do not expose transitions the backend does not authorize.
- [ ] Preserve lifecycle revision/concurrency protection.
- [ ] Preserve domain events/audit logging.
- [ ] Decide whether ordinary Quick Create auto-publishes or whether company policy can require review.
- [ ] If maker/checker exists, reflect it clearly in UI.

---

# 13. Product families

Current family management is useful but incomplete.

- [ ] Preserve tenant-scoped family identity.
- [ ] Preserve case-insensitive duplicate protection.
- [ ] Preserve optimistic version check when renaming.
- [ ] Add family search.
- [ ] Add bounded pagination / keyset strategy for >200 families.
- [ ] Never silently truncate family management at 200.
- [ ] Product creation must visibly distinguish:
  - selecting an existing family,
  - creating a new family.
- [ ] Reconsider automatic "product name becomes family name" behavior.
- [ ] If auto-family behavior remains, explain it explicitly.
- [ ] Consider company preference for automatic family creation.

---

# 14. SKU and search

Current simple product list searches product/variant name and family name only.

Required:

- [ ] Search by product name.
- [ ] Search by family.
- [ ] Search by SKU.
- [ ] Search by unit barcode.
- [ ] Search by package barcode.
- [ ] Define multi-token semantics.
- [ ] Escape `%`, `_`, and `\`.
- [ ] Search is company-scoped from the beginning.
- [ ] Search filters before pagination.
- [ ] Run a measured performance audit before declaring production-ready.
- [ ] Add search index only if EXPLAIN/benchmark evidence justifies it.

---

# 15. Pagination / cursor robustness

Current simple product list uses id-based keyset pagination.

Keep the bounded keyset approach, but harden the contract.

- [ ] Preserve hard page-size bound.
- [ ] Preserve no-offset pagination.
- [ ] Cursor must encode enough scope to reject reuse under a different search/filter state.
- [ ] Invalid cursor returns a stable error code.
- [ ] Tampered cursor fails closed.
- [ ] Search/filter changes reset cursor history.
- [ ] Tests cover first/next/previous flows.
- [ ] Do not convert the Products page to unbounded "load all".

---

# 16. Product list table

Current default columns:

- product,
- package,
- units/package,
- package price,
- unit price,
- action.

Production design should keep the main list compact.

Recommended default columns:

- [ ] Product.
- [ ] Family.
- [ ] SKU or compact identity hint.
- [ ] Package/UOM.
- [ ] Tracking summary.
- [ ] Lifecycle status.
- [ ] Pricing only when authorized.
- [ ] Actions.

Optional columns:

- [ ] Unit barcode.
- [ ] Package barcode.
- [ ] Unit price.
- [ ] Package price.
- [ ] Units/package.
- [ ] Other company-specific display preferences.

- [ ] Add configurable visible columns.
- [ ] Use drawer for secondary details.
- [ ] Keep sticky header.
- [ ] RTL/LTR safe.
- [ ] Avoid widths tied to Arabic only.

---

# 17. Error / loading / empty states

Current defect:
`productsQuery.isError` does not have a dedicated table state.

Required:

- [ ] Separate loading from empty.
- [ ] Separate first-load failure from "no products".
- [ ] Add in-page retry action.
- [ ] Preserve previous successful data during harmless background refetch when appropriate.
- [ ] Do not replace server failure with an empty-state message.
- [ ] Family load errors have distinct UI.
- [ ] Package-UOM load errors have distinct UI.
- [ ] Import polling errors are understandable.
- [ ] Abort stale requests.
- [ ] Avoid stale response races.

---

# 18. Runtime frontend contracts

Current Products page often casts raw API responses with TypeScript `as`.

This is not enough.

Add runtime parsers for:

- [ ] Product page.
- [ ] Product item.
- [ ] Families.
- [ ] Package UOMs.
- [ ] Create response.
- [ ] Price update response.
- [ ] Import creation response.
- [ ] Import status.
- [ ] Import error pagination.
- [ ] Tracking settings.
- [ ] Lifecycle detail.
- [ ] Product detail drawer response if a dedicated endpoint is created.

Malformed backend payload must fail explicitly and safely.

---

# 19. Permissions

Current frontend `canManage` is too coarse:

```text
catalog.manage
AND catalog.publish
AND pricing.manage
```

This can hide actions a user is actually allowed to perform.

Split UI capability checks.

- [ ] `catalog.read`
- [ ] `catalog.manage`
- [ ] `catalog.publish`
- [ ] `pricing.view`
- [ ] `pricing.manage`
- [ ] import permission if separated later
- [ ] lifecycle permission if separated
- [ ] barcode/UOM management if separated

Required:

- [ ] Family management follows `catalog.manage`.
- [ ] Price editing follows `pricing.manage`.
- [ ] Price display follows `pricing.view`.
- [ ] Product identity can be viewed without price permission where appropriate.
- [ ] Product list must not require `pricing.view` merely to see product identity.
- [ ] Backend, not React, remains final permission authority.

---

# 20. Decouple Products read from Pricing read

Current `GET /simple-products` requires:

- `catalog.read`
- `pricing.view`

This prevents a user from viewing products when they are not allowed to view prices.

Required redesign:

- [ ] Product identity read is governed by catalog permission.
- [ ] Pricing fields are permission-aware.
- [ ] Either:
  - server omits/nulls price fields when unauthorized, or
  - split pricing into a separate request.
- [ ] UI does not infer secret pricing from hidden data.
- [ ] Tests prove a catalog-only user can view products without price leakage.

---

# 21. Money correctness

Backend correctly uses `Decimal`.

Frontend currently converts monetary values with `Number(...)` in places such as price preview/formatting.

Required:

- [ ] Do not treat JS floating-point as monetary authority.
- [ ] Keep API money values as decimal strings.
- [ ] Use exact decimal/string helpers for calculations.
- [ ] Derived frontend price is preview only.
- [ ] Backend remains final authority for derived prices.
- [ ] Locale formatting must not mutate numeric truth.
- [ ] Never parse localized display strings back into business values.
- [ ] Test large and high-precision allowed values.

---

# 22. UOM / packaging

Backend UOM authority is much stronger than the simple UI.

Required:

- [ ] Preserve `domains/uom_authority.py` as authority.
- [ ] Do not duplicate conversion graph logic in React.
- [ ] Keep simple workflow for common EACH + one outer package.
- [ ] Explain when a product is not `simple_compatible`.
- [ ] Provide a route to advanced UOM management for complex products.
- [ ] Do not show only `—` when advanced management is required.
- [ ] Changing package/UOM after operational use must follow safe business rules.
- [ ] Determine which UOM fields become immutable after inventory/pricing history exists.

---

# 23. Barcodes

Backend already supports proper barcode records.

Required:

- [ ] Show active primary barcode(s) in product detail.
- [ ] Search by barcode.
- [ ] Manage barcodes through backend authority.
- [ ] Preserve company-scoped barcode uniqueness.
- [ ] Preserve UOM association.
- [ ] Preserve effective/active semantics.
- [ ] Handle shared base/package barcode safely.
- [ ] Do not allow arbitrary client-only barcode replacement.

---

# 24. Simple vs advanced product compatibility

Current backend computes `simple_compatible`.

Required:

- [ ] Explain `simple_compatible=false` in UI.
- [ ] Show "Advanced product setup required" or equivalent translated wording.
- [ ] Do not leave a silent `—` action cell.
- [ ] Advanced management entry point appears only when implemented and authorized.
- [ ] Hide/remove permanently disabled Advanced Pricing button until the destination is actually usable, or connect it properly.

---

# 25. Bulk product import

Existing bulk import is a strong foundation:

- async queue,
- CSV/XLSX,
- durable request identity,
- resume,
- idempotency,
- bounded file/row limits,
- archive safety,
- execution-time permission recheck.

Preserve these.

Required additions:

- [x] Add lot-tracking input/mapping.
- [x] Add expiry-tracking input/mapping.
- [x] Support file-wide defaults for tracking settings to reduce repeated work.
- [x] Allow per-row override where authorized.
- [x] Import template includes tracking columns or a documented default policy.
- [x] Import validation uses the same backend product authority as manual creation.
- [x] Imported products must not silently become REQUIRED/REQUIRED unless that is an explicit selected default.
- [ ] Error report uses stable codes.
- [x] Retry/resume semantics remain durable.

---

# 26. Import internationalization

Current worker recognizes a hardcoded set of Arabic/English aliases.

This is useful but not enough for arbitrary future languages.

Required:

- [ ] Mapping UI remains primary fallback when automatic detection does not understand a header.
- [ ] Canonical field IDs stay language-neutral.
- [ ] Downloaded template uses current UI language.
- [ ] New languages can add alias packs without changing business logic.
- [ ] Unknown-language headers do not cause guessing.
- [ ] User can explicitly map unknown headers.
- [ ] Error report is translated on download/display from stable error codes.

---

# 27. i18n / locale architecture

Current Products page already uses `useTranslation()` and `dir={i18n.dir()}` in many places — preserve this good foundation.

Fix this pattern:

```ts
i18n.language.startsWith("ar")
  ? "ar-JO"
  : "en-US"
```

Required:

- [ ] Central locale resolver.
- [ ] Arabic may use an Arabic locale.
- [ ] English may use an English locale.
- [ ] French/German/etc. use their own locale instead of silently falling to `en-US`.
- [ ] `Intl.NumberFormat` uses resolved locale.
- [ ] `Intl.DateTimeFormat` uses resolved locale.
- [ ] Currency formatting uses correct currency + locale.
- [ ] RTL/LTR is derived from i18n configuration.
- [ ] Long translated labels tested.
- [ ] Translation keys for all tracking/lifecycle/UOM labels.

---

# 28. Backend error contracts

Backend includes good stable domain codes in many places, but Pydantic/framework errors can still expose generic English text.

Required:

- [ ] Product APIs return stable business error codes.
- [ ] UI maps known codes to translations.
- [ ] UI never branches on Arabic/English `message`.
- [ ] FastAPI validation errors are normalized or mapped into a consistent presentation layer.
- [ ] Backend messages may remain diagnostic but are not the localization contract.

---

# 29. Product creation + publication policy

Current simple creation effectively creates a DRAFT and publishes it to ACTIVE inside the same workflow.

Required decision:

- [ ] Keep instant publish as the default for simple companies if desired.
- [ ] Determine whether company policy may require review/maker-checker.
- [ ] If review is enabled:
  - creator can save draft,
  - authorized publisher approves,
  - UI shows pending state.
- [ ] Do not force enterprise workflow on small companies.
- [ ] Do not remove lifecycle authority just to make the UI simple.

---

# 30. Product creation draft recovery

Current product draft uses sessionStorage scoped by company + driver.

Preserve and harden:

- [ ] No cross-company draft leakage.
- [ ] No cross-user draft leakage.
- [x] Tracking settings included in saved draft.
- [x] Draft version incremented when schema changes.
- [ ] Invalid old draft safely discarded or migrated.
- [ ] User is informed when a draft is restored.
- [ ] Explicit cancel removes abandoned durable operation safely.

---

# 31. Company customization

Company-level configurable defaults/preferences should include, where appropriate:

Business defaults:
- [x] default lot tracking mode,
- [x] default expiry tracking mode,
- [ ] default package UOM,
- [ ] default units/package if useful,
- [ ] product publication workflow policy.

Display preferences:
- [ ] visible product columns,
- [ ] table density,
- [ ] default sort,
- [ ] optional detail sections.

Keep business truth separate from display preference.

---

# 32. Product table filtering and sorting

Add operational filters only when useful:

- [ ] Family.
- [ ] Lifecycle.
- [ ] Tracking type.
- [ ] Simple-compatible / advanced.
- [ ] Has barcode / missing barcode.
- [ ] Has price / missing price only when authorized.
- [ ] Lot-tracked.
- [ ] Expiry-tracked.

Sorting:
- [ ] Product name.
- [ ] Family.
- [ ] SKU.
- [ ] Lifecycle.
- [ ] Recently created/updated if required.

All server-side filters occur before pagination.

---

# 33. Accessibility / operator UX

- [ ] Keyboard accessible search.
- [ ] Keyboard accessible dialogs.
- [ ] Visible focus states.
- [ ] Buttons/icons have translated aria-labels.
- [ ] Status is not communicated by color only.
- [ ] Form errors associate with exact field.
- [ ] First invalid field receives focus.
- [ ] Drawer is keyboard accessible.
- [ ] RTL/LTR keyboard and layout smoke tests.

---

# 34. Performance audit

Before Production Ready:

## Product list
- [ ] Measure normal unfiltered page.
- [ ] Measure name search.
- [ ] Measure family search.
- [ ] Measure SKU search.
- [ ] Measure barcode search.
- [ ] Measure common filters.
- [ ] Measure page continuation.

Metrics:
- [ ] SQL count.
- [ ] DB execution time.
- [ ] endpoint p50.
- [ ] endpoint p95.
- [ ] endpoint p99 where practical.
- [ ] payload size.

Review:
- [ ] No N+1.
- [ ] No unbounded `.all()`.
- [ ] Stable query count.
- [ ] Bounded enrichment.
- [ ] EXPLAIN reviewed.
- [ ] Indexes justified by evidence.
- [ ] Permanent regression gate.

---

# 35. Backend isolation tests

- [ ] Cross-company product ID lookup fails closed.
- [ ] Cross-company family ID fails closed.
- [ ] Cross-company barcode cannot be read/modified.
- [ ] Cross-company UOM conversion cannot be read/modified.
- [ ] Search never leaks foreign product names.
- [ ] Import worker sets and enforces tenant context.
- [ ] Import job RLS remains ENABLE + FORCE.
- [ ] Product import rows remain tenant-isolated.

---

# 36. Concurrency / idempotency

Preserve existing strong foundations.

Required tests:

- [ ] Product create replay is idempotent.
- [ ] Changed payload with reused request ID fails.
- [ ] Family create/rename concurrency.
- [ ] Family version conflict.
- [ ] Price update idempotency.
- [ ] Barcode uniqueness race.
- [x] Tracking-mode update concurrency.
- [ ] Lifecycle transition revision conflict.
- [x] Import replay/resume remains safe.

---

# 37. Product data migration / backward compatibility

Existing products have already been created under the forced:

```text
REQUIRED / REQUIRED
```

Do **not** silently change them.

Required:

- [ ] Inventory existing products and their tracking modes.
- [x] Do not assume existing REQUIRED values were intentional.
- [x] Provide a safe review/migration strategy if the company wants to correct them.
- [x] Products with operational inventory/history require controlled change rules.
- [x] Avoid mass automatic downgrade of tracking rules.
- [x] Migration/audit record required for any bulk correction.

### Approved legacy tracking review policy

- Existing `REQUIRED / REQUIRED` values are treated as **review candidates**, not automatically incorrect data.
- Never mass-change existing SKUs automatically.
- A SKU with no batch/inventory history may be corrected explicitly through the normal tracking authority, preserving optimistic version checks, tenant scope, request identity, and audit evidence.
- A SKU with batch/inventory history remains blocked from the normal tracking editor through `PRODUCT_TRACKING_LOCKED`.
- Any future correction for a history-bearing SKU requires a separate controlled migration workflow; it must be explicit, authorized, tenant-scoped, reasoned, idempotent, concurrency-safe, and preserve historical truth.
- Any future bulk correction must orchestrate explicit per-SKU reviewed decisions and record before/after audit evidence; it must never become a blind SQL downgrade.


---

# 38. Products → Inbound contract freeze

Products is complete only when Inbound can rely on a stable product contract.

Inbound needs at minimum:

- [ ] `product_variant_id`
- [ ] base UOM
- [ ] valid purchase/receipt UOM options
- [ ] quantity scale/step
- [ ] `lot_control_mode`
- [ ] `expiry_control_mode`
- [ ] lifecycle/capability state
- [ ] warehouse-specific operational permission/flags where applicable

Once these are stable:
- [ ] freeze the Products tracking contract,
- [ ] move to Inbound audit.

---

# 39. Frontend architecture cleanup

`ProductsDashboard.tsx` is large and carries many responsibilities.

Before it becomes harder to maintain:

- [ ] Separate runtime contracts/parsers.
- [ ] Separate product list/table component.
- [ ] Separate create/edit drawer/modal.
- [ ] Separate families manager.
- [ ] Separate import workflow.
- [ ] Separate pricing editor.
- [ ] Shared product tracking controls.
- [ ] Shared permission capability helpers.
- [ ] Avoid one giant component becoming the new technical debt hotspot.

Do not split files purely for aesthetics; split by clear responsibilities/contracts.

---

# 40. Product API shape

Evaluate whether `simple_products.py` should remain a facade or grow too large.

Preferred principle:

- Simple Products remains the easy SMB facade.
- Deep catalog authorities remain reusable underneath.
- Avoid duplicating catalog rules.

Required:

- [ ] Simple endpoint delegates to authoritative services.
- [ ] No second lifecycle implementation.
- [ ] No second barcode authority.
- [ ] No second UOM authority.
- [ ] No second pricing authority.
- [x] No second tracking-mode authority.

---

# 41. Products page visual UX

Target quality: same clarity as the completed Live Stock page.

- [ ] Clear page title/subtitle.
- [ ] Search prominent but not oversized.
- [ ] Main actions grouped by frequency.
- [ ] "Add product" primary.
- [ ] Import secondary.
- [ ] Families tertiary.
- [ ] Advanced functions do not overwhelm ordinary users.
- [ ] Consistent rounded surfaces / spacing with dashboard design language.
- [ ] Empty state gives useful next action.
- [ ] Error state gives retry.
- [ ] Product row hover/selection opens detail cleanly.
- [ ] No giant unused whitespace.
- [ ] Mobile/narrow screens degrade gracefully.

---

# 42. Tracking configuration in the UI

Recommended create flow:

**Section: Inventory tracking**

Question 1:
"Does this product use a batch/lot number?"
- No
- Optional
- Required

Question 2:
"Does this product have an expiry date?"
- No
- Optional
- Required

- [ ] Add short helper text.
- [ ] Company default shown/preselected.
- [ ] User can change before save.
- [ ] Permission-aware.
- [ ] Stored values visible later in Product Details.
- [ ] Changing after stock exists follows controlled rules.

---

# 43. Product type presets — optional later enhancement

To reduce user effort without hiding truth, consider presets:

Examples:
- Food / beverage
- General merchandise
- Spare parts
- Packaging material

A preset could suggest:
- lot tracking default,
- expiry tracking default,
- package defaults.

Rules:

- [ ] Presets are convenience only.
- [ ] Presets never become hidden business authority.
- [ ] User can inspect/change the resulting explicit settings.
- [ ] Do not implement until core tracking controls are correct.

---

# 44. Pricing UX

Existing simple pricing is useful.

Required:

- [ ] Product identity can exist without visible pricing permission.
- [ ] Price edit only for authorized users.
- [ ] Distinguish derived vs explicit package/unit price.
- [ ] Explain independent prices when both supplied.
- [ ] Exact decimal preview.
- [ ] Advanced pricing button only shown when usable.
- [ ] Pricing changes preserve publication/audit authority.

---

# 45. Product family / variant terminology

The backend has Product + ProductVariant concepts.

The ordinary UI should not force technical terminology on non-technical users unless needed.

- [ ] Decide user-facing naming for "family".
- [ ] Decide when SKU/variant concept is necessary.
- [ ] Keep backend identity untouched.
- [ ] Make terminology consistent across Products, Inbound, Live Stock, and Batches.
- [ ] Translation keys use stable semantic identifiers.

---

# 46. Product-location relationship

Backend intentionally uses sparse/lazy `ProductLocation`.

Existing design:
first successful inbound may create the needed warehouse product-location relation.

Preserve:

- [ ] Do not mass-provision every product to every warehouse.
- [ ] Product identity remains company-wide.
- [ ] Warehouse operational settings remain location-specific.
- [ ] Products page should not imply a product must be manually assigned to every warehouse before receiving it.
- [ ] If showing warehouse availability later, distinguish company product from location assignment.

---

# 47. Auditability

Product changes must be auditable.

- [ ] Product creation audit.
- [ ] Family creation/rename audit.
- [ ] Barcode changes audit.
- [x] Tracking-mode changes audit.
- [ ] Lifecycle changes audit.
- [ ] Pricing changes remain auditable.
- [ ] Bulk import maintains job/row history.
- [ ] Reason required for sensitive changes where appropriate.

---

# 48. Product deletion policy

Do not add a simple Delete button without lifecycle rules.

Required decision:

- [ ] Can a never-used draft be deleted?
- [ ] Can an active/used product only be archived?
- [ ] What happens when product has stock/history/orders?
- [ ] Preserve referential/audit history.
- [ ] UI uses lifecycle/archive semantics instead of unsafe hard delete where appropriate.

---

# 49. Test suite

## Backend

- [ ] create product with lot NONE/OPTIONAL/REQUIRED.
- [ ] create product with expiry NONE/OPTIONAL/REQUIRED.
- [x] company default application.
- [x] per-product override.
- [ ] cross-tenant create/read/update tests.
- [ ] product list permission tests.
- [ ] catalog-only user without pricing permission.
- [ ] barcode conflict tests.
- [ ] family conflict/version tests.
- [ ] lifecycle transition tests.
- [x] tracking change after inventory tests.
- [ ] exact money tests.
- [ ] cursor scope/tamper tests.
- [x] import tracking-mode tests.
- [x] import RLS/idempotency tests.

## Frontend

- [ ] runtime parser tests.
- [x] create form tracking-mode behavior.
- [x] translated enum labels.
- [ ] error vs empty state.
- [ ] permission-specific action visibility.
- [ ] pricing hidden without permission.
- [ ] search reset/cursor behavior.
- [ ] family search/pagination.
- [ ] Product Detail Drawer.
- [x] import mapping.
- [ ] restored draft versioning.
- [ ] RTL smoke test.
- [ ] LTR smoke test.
- [x] build.

---

# 50. Production release gate

Products can be declared **Production Ready** only when:

- [x] Critical silent REQUIRED/REQUIRED defect is fixed.
- [x] Tracking modes are explicit end-to-end.
- [ ] Existing products are handled safely.
- [ ] Product read is decoupled from mandatory price access.
- [ ] Permissions are granular and correct.
- [ ] Runtime frontend contracts are strict.
- [ ] Money handling is exact.
- [ ] Product search includes identity fields users actually use.
- [ ] Error states are distinct.
- [ ] Families no longer silently truncate.
- [ ] Product detail management reflects the important backend authorities.
- [ ] Lifecycle is visible/manageable safely.
- [x] Bulk import supports tracking configuration.
- [ ] i18n architecture is language-agnostic.
- [ ] RTL + LTR pass.
- [ ] Performance audit passes.
- [ ] Security/isolation tests pass.
- [x] Relevant backend gates pass.
- [x] Frontend tests/build pass.
- [ ] No unresolved blocker/TODO in touched production path.
- [x] PR review complete.
- [x] merged to `main`.
- [x] local `main == origin/main`.

---

# 51. Original 50 audit observations — coverage map

This section preserves every point from the initial Products review so none are lost.

- [x] 1. Fix silent `lot_control_mode=REQUIRED` and `expiry_control_mode=REQUIRED` for every new simple product.
- [x] 2. Bulk import currently inherits the same silent forced tracking behavior.
- [x] 3. Add an explicit "Inventory tracking" section to product creation.
- [x] 4. Support company-level defaults instead of one global hardcoded tracking policy.
- [ ] 5. Add real post-create product identity management beyond price editing.
- [ ] 6. Surface and manage barcodes after creation.
- [ ] 7. Show SKU in the normal product experience.
- [ ] 8. Search by SKU and barcode, not only product/family name.
- [ ] 9. Improve list information hierarchy without turning it into a giant table.
- [ ] 10. Surface product lifecycle state.
- [ ] 11. Make instant DRAFT→ACTIVE behavior explicit/configurable where appropriate.
- [ ] 12. Add safe retire/archive/hold workflows.
- [ ] 13. Split coarse frontend `canManage` into capability-specific permissions.
- [ ] 14. Stop requiring `pricing.view` just to read product identity.
- [ ] 15. Decouple catalog/product read from pricing visibility.
- [ ] 16. Add distinct `productsQuery.isError` UI instead of showing empty state.
- [ ] 17. Add in-page retry for list failure.
- [ ] 18. Fix family management's silent 200-item limit with search/pagination.
- [ ] 19. Preserve id-based keyset pagination.
- [ ] 20. Scope/harden cursors against reuse across different searches/filters.
- [ ] 21. Performance-audit `%LIKE%` search before production signoff.
- [ ] 22. Preserve batched enrichment / avoid N+1.
- [ ] 23. Explain `simple_compatible=false` rather than showing an unexplained dash.
- [ ] 24. Connect or hide the permanently disabled Advanced Pricing control.
- [ ] 25. Replace TypeScript-only raw-response casts with runtime parsers.
- [ ] 26. Runtime-validate families/UOM/import/mutation contracts too.
- [ ] 27. Remove JS floating-point money authority (`Number(...)`) from price calculations/formatting.
- [ ] 28. Keep frontend derived prices as preview; backend remains authoritative.
- [ ] 29. Integer package quantity use of Number is acceptable within bounded validation.
- [ ] 30. Make existing-family vs new-family creation explicit in UX.
- [ ] 31. Reconsider/clarify automatic product-name-as-family behavior.
- [ ] 32. Add search/pagination inside family manager.
- [ ] 33. Preserve backend case-insensitive family duplicate locking.
- [ ] 34. Surface existing barcode authority in normal product UX.
- [x] 35. Preserve strong async/durable import architecture.
- [x] 36. Add lot/expiry configuration to bulk import/template/defaults.
- [ ] 37. Generalize import header localization beyond Arabic/English-only alias assumptions.
- [x] 38. Preserve good existing `t(...)` and `dir={i18n.dir()}` foundation.
- [ ] 39. Replace binary Arabic-vs-English locale fallback with generic locale resolution.
- [ ] 40. Make all new number/date/money rendering language-agnostic.
- [x] 41. Keep API enums stable and translate only in UI.
- [ ] 42. Normalize framework/Pydantic validation presentation so untranslated English does not leak.
- [ ] 43. Separate Quick Create from optional enterprise review/maker-checker policy.
- [ ] 44. Add a Product Detail Drawer instead of adding too many list columns.
- [ ] 45. Keep ordinary creation simple and move complexity to Advanced settings.
- [x] 46. Present lot/expiry tracking in plain user language, not backend field names.
- [ ] 47. Products tracking policy must drive Inbound field requirements.
- [x] 48. Block/guard unsafe tracking-mode changes after inventory exists.
- [ ] 49. Guard unsafe UOM/package changes after operational history exists.
- [ ] 50. Visually distinguish freely editable, restricted, and workflow-controlled product properties.

---

# 52. Additional findings / requirements beyond the original 50

- [x] 51. Add company defaults for lot/expiry tracking without rewriting existing SKUs.
- [x] 52. Define internal batch identity for `lot_control_mode=NONE`.
- [ ] 53. Create a migration/review strategy for existing products that were silently created REQUIRED/REQUIRED.
- [x] 54. Version the saved product draft schema when tracking fields are added.
- [ ] 55. Separate business defaults from user display preferences.
- [ ] 56. Add Product page performance map and permanent regression gate.
- [ ] 57. Add accessibility/keyboard requirements to release gate.
- [ ] 58. Define safe product deletion/archive semantics.
- [ ] 59. Ensure normal Products does not duplicate Catalog lifecycle/UOM/barcode authorities.
- [x] 60. Freeze the product tracking contract before beginning final Inbound work.

---

# 53. Recommended execution order

Do not work on all items randomly.

## Phase P0 — Baseline / safety

- [x] Audit current user-facing Products page.
- [x] Confirm forced REQUIRED/REQUIRED behavior.
- [x] Confirm Simple Products is a facade over deeper catalog/pricing authorities.
- [x] Confirm current family list hard-bounds at 200.
- [x] Confirm current product list requires both `catalog.read` and `pricing.view`.
- [x] Confirm current list has no explicit error state.
- [x] Confirm current import does not carry lot/expiry modes.
- [x] Confirm current locale formatting assumes Arabic vs English only.

## Phase P1 — Product tracking authority

- [x] Define company defaults.
- [x] Extend SimpleProduct creation contract.
- [x] Extend service authority.
- [x] Add backend validation.
- [x] Define safe transitions after inventory exists.
- [x] Define existing-product migration/review plan.
- [x] Add tests.

### Product tracking — five-stage implementation checkpoint

- [x] Stage 1/5 — Product tracking authority.
- [x] Stage 2/5 — Backend defaults + Product tracking mutation contracts.
- [x] Stage 3/5 — Bulk Import + Simple Products tracking integration.
- [x] Stage 4/5 — Translated Dashboard tracking UX.
- [x] Stage 5/5 — Isolation / compatibility / migration tests + Production Gate.

## Phase P2 — Read contract and permissions

- [x] Decouple catalog read from price view.
- [x] Add SKU/tracking/lifecycle identity to product read contract.
- [x] Add permission-aware pricing.
- [x] Add runtime parsers.
- [x] Harden cursor scope.
- [x] Add tests.

## Phase P3 — Product UX foundation

- [ ] Product Detail Drawer.
- [ ] Quick Create + Advanced.
- [x] Tracking controls.
- [ ] Error/retry states.
- [ ] granular permissions.
- [ ] lifecycle visibility.
- [ ] barcode visibility/management.
- [ ] simple-compatible explanation.

## Phase P4 — Search / families

- [ ] Search name/family/SKU/barcode.
- [ ] Family search/pagination.
- [ ] Filters/sorting.
- [ ] performance audit.

## Phase P5 — Exact pricing / UOM

- [ ] Replace float-based money handling.
- [ ] Review package/UOM edit safety.
- [ ] Connect advanced management where appropriate.

## Phase P6 — Bulk import

- [x] Tracking columns/defaults.
- [ ] Generic localization mapping.
- [x] Runtime contracts.
- [x] regression tests.

## Phase P7 — i18n / accessibility / polish

- [ ] Generic locale resolver.
- [ ] all translation keys.
- [ ] RTL/LTR.
- [ ] accessibility.
- [ ] responsive polish.
- [ ] configurable display preferences.

## Phase P8 — Performance / security / release

- [ ] query benchmark.
- [ ] EXPLAIN.
- [ ] isolation tests.
- [ ] concurrency/idempotency tests.
- [ ] production gate.
- [ ] PR + merge.
- [ ] local/GitHub alignment.
- [ ] declare Products Production Ready.

---

# 54. Immediate next task

Proceed to **Phase P3 — Product UX foundation**.

Current P3 state:

- [ ] Product Detail Drawer.
- [ ] Quick Create + Advanced.
- [x] Tracking controls.
- [ ] Error/retry states.
- [ ] granular permissions.
- [ ] lifecycle visibility.
- [ ] barcode visibility/management.
- [ ] simple-compatible explanation.

Implementation order for P3:

1. Establish the Product Detail Drawer as the canonical detailed product view.
2. Preserve Quick Create for the common path and move advanced controls into the appropriate detailed/advanced surface.
3. Surface lifecycle, tracking, barcode, compatibility, and permission state without duplicating backend authority.
4. Add explicit loading/error/retry states and regression coverage.
5. Complete P3 gates/review before moving to Phase P4.

Do not start Phase P4 until P3 is complete, reviewed, and merged to `main`.
