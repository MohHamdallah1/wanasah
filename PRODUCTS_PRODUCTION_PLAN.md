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

**Execution-status source of truth:** Section **53 — Recommended execution order** is the canonical phase tracker (P0–P8).

Sections **4–52** are the detailed requirements, design constraints, audit observations, and release criteria. Their checkboxes are not separate execution phases and may intentionally repeat the same requirement in more than one context. During each phase close-out, synchronize only the detailed items that were actually verified; never infer completion from duplication alone.

Section **54 — Immediate next task** must always point to the next open phase in Section 53.

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

> **Downstream note:** the two unchecked items below are Inbound behavior requirements. Products now exposes the authoritative tracking modes; Inbound still has to consume them in its own phase.
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
- [x] Determine whether any transitions require a controlled migration workflow.
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

- [x] Product/SKU name.
- [x] Product family.
- [x] SKU/code strategy.
- [x] Base UOM.
- [x] Outer/package UOM.
- [x] Units per package.
- [x] Unit barcode.
- [x] Package barcode.
- [x] Shared barcode behavior where supported.
- [x] Lot tracking mode.
- [x] Expiry tracking mode.
- [ ] Initial lifecycle policy.
- [x] Initial pricing only when the user has pricing permission.

## 8.2 Quick Create vs Advanced

Default user experience:

### Quick Create
Keep ordinary creation easy.

- [x] Product name.
- [x] Family.
- [x] Package shape.
- [x] Units per package.
- [x] Price when authorized.
- [x] Tracking controls expressed in plain language.

### Advanced
Optional expandable section:

- [ ] SKU/code.
- [x] Barcodes.
- [x] tracking details.
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

- [x] Edit display name where allowed.
- [ ] Move/change family where allowed.
- [x] View SKU.
- [x] Edit/manage barcodes through authoritative barcode workflow.
- [x] View package/UOM structure.
- [ ] Manage simple-compatible package shape safely.
- [x] View tracking modes.
- [x] Edit tracking modes only when lifecycle/inventory rules allow.
- [x] View lifecycle status.
- [x] View operational hold.
- [x] View simple/advanced compatibility.
- [x] Explain why some fields are locked.

---

# 11. Product detail drawer

Do not make the main table carry every product fact.

Add a Product Detail Drawer / Side Panel.

Suggested sections:

## Identity
- [x] Name.
- [x] Family.
- [x] SKU.
- [ ] Product/variant IDs only when useful for support/admin.

## Packaging & UOM
- [ ] Base UOM.
- [x] Package UOM.
- [x] Units per package.
- [ ] Conversion information.

## Barcodes
- [x] Unit barcode.
- [x] Package barcode.
- [x] Primary/active state.

## Tracking
- [x] Lot tracking mode.
- [x] Expiry tracking mode.

## Lifecycle
- [x] ACTIVE / RETIRING / etc.
- [x] Operational hold.
- [x] Allowed lifecycle actions.

## Pricing
- [x] Current prices only when authorized.
- [ ] Advanced pricing link only when actually usable.

## Inventory relationship
Later:
- [ ] Assigned/used warehouses where useful.
- [ ] Current stock summary where useful.

---

# 12. Product lifecycle

Backend already contains product lifecycle authority.

UI must reflect it safely.

- [x] Show lifecycle status.
- [x] Translate lifecycle codes via i18n.
- [x] Show operational hold.
- [x] Provide permitted lifecycle actions.
- [x] Retire/disable/archive workflow must explain operational impact.
- [x] Do not expose transitions the backend does not authorize.
- [x] Preserve lifecycle revision/concurrency protection.
- [x] Preserve domain events/audit logging.
- [ ] Decide whether ordinary Quick Create auto-publishes or whether company policy can require review.
- [ ] If maker/checker exists, reflect it clearly in UI.

---

# 13. Product families

Current family management is useful but incomplete.

- [x] Preserve tenant-scoped family identity.
- [x] Preserve case-insensitive duplicate protection.
- [x] Preserve optimistic version check when renaming.
- [x] Add family search.
- [x] Add bounded pagination / keyset strategy for >200 families.
- [x] Never silently truncate family management at 200.
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

- [x] Search by product name.
- [x] Search by family.
- [x] Search by SKU.
- [x] Search by unit barcode.
- [x] Search by package barcode.
- [x] Define multi-token semantics.
- [x] Escape `%`, `_`, and `\`.
- [x] Search is company-scoped from the beginning.
- [x] Search filters before pagination.
- [x] Run a measured performance audit before declaring production-ready.
- [x] Add search index only if EXPLAIN/benchmark evidence justifies it.

---

# 15. Pagination / cursor robustness

Current simple product list uses id-based keyset pagination.

Keep the bounded keyset approach, but harden the contract.

- [x] Preserve hard page-size bound.
- [x] Preserve no-offset pagination.
- [x] Cursor must encode enough scope to reject reuse under a different search/filter state.
- [x] Invalid cursor returns a stable error code.
- [x] Tampered cursor fails closed.
- [x] Search/filter changes reset cursor history.
- [x] Tests cover first/next/previous flows.
- [x] Do not convert the Products page to unbounded "load all".

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

- [x] Product.
- [x] Family.
- [x] SKU or compact identity hint.
- [x] Package/UOM.
- [x] Tracking summary.
- [x] Lifecycle status.
- [x] Pricing only when authorized.
- [x] Actions.

Optional columns:

- [x] Unit barcode.
- [x] Package barcode.
- [x] Unit price.
- [x] Package price.
- [x] Units/package.
- [ ] Other company-specific display preferences.

- [x] Add configurable visible columns.
- [x] Use drawer for secondary details.
- [x] Keep sticky header.
- [x] RTL/LTR safe.
- [x] Avoid widths tied to Arabic only.

---

# 17. Error / loading / empty states

Current defect:
`productsQuery.isError` does not have a dedicated table state.

Required:

- [x] Separate loading from empty.
- [x] Separate first-load failure from "no products".
- [x] Add in-page retry action.
- [ ] Preserve previous successful data during harmless background refetch when appropriate.
- [x] Do not replace server failure with an empty-state message.
- [x] Family load errors have distinct UI.
- [x] Package-UOM load errors have distinct UI.
- [x] Import polling errors are understandable.
- [x] Abort stale requests.
- [x] Avoid stale response races.

---

# 18. Runtime frontend contracts

Current Products page often casts raw API responses with TypeScript `as`.

This is not enough.

Add runtime parsers for:

- [x] Product page.
- [x] Product item.
- [x] Families.
- [x] Package UOMs.
- [x] Create response.
- [x] Price update response.
- [x] Import creation response.
- [x] Import status.
- [x] Import error pagination.
- [x] Tracking settings.
- [x] Lifecycle detail.
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

- [x] `catalog.read`
- [x] `catalog.manage`
- [x] `catalog.publish`
- [x] `pricing.view`
- [x] `pricing.manage`
- [ ] import permission if separated later
- [x] lifecycle permission if separated
- [ ] barcode/UOM management if separated

Required:

- [x] Family management follows `catalog.manage`.
- [x] Price editing follows `pricing.manage`.
- [x] Price display follows `pricing.view`.
- [x] Product identity can be viewed without price permission where appropriate.
- [x] Product list must not require `pricing.view` merely to see product identity.
- [x] Backend, not React, remains final permission authority.

---

# 20. Decouple Products read from Pricing read

Current `GET /simple-products` requires:

- `catalog.read`
- `pricing.view`

This prevents a user from viewing products when they are not allowed to view prices.

Required redesign:

- [x] Product identity read is governed by catalog permission.
- [x] Pricing fields are permission-aware.
- [x] Chosen design: keep one Product request and return pricing fields only when the caller is authorized; unauthorized catalog readers receive no price leakage.
  - server omits/nulls price fields when unauthorized, or
  - split pricing into a separate request.
- [x] UI does not infer secret pricing from hidden data.
- [x] Tests prove a catalog-only user can view products without price leakage.

---

# 21. Money correctness

Backend correctly uses `Decimal`.

Frontend currently converts monetary values with `Number(...)` in places such as price preview/formatting.

Required:

- [x] Do not treat JS floating-point as monetary authority.
- [x] Keep API money values as decimal strings.
- [x] Use exact decimal/string helpers for calculations.
- [x] Derived frontend price is preview only.
- [x] Backend remains final authority for derived prices.
- [x] Locale formatting must not mutate numeric truth.
- [x] Never parse localized display strings back into business values.
- [x] Test large and high-precision allowed values.

---

# 22. UOM / packaging

Backend UOM authority is much stronger than the simple UI.

Required:

- [x] Preserve `domains/uom_authority.py` as authority.
- [x] Do not duplicate conversion graph logic in React.
- [x] Keep simple workflow for common EACH + one outer package.
- [x] Explain when a product is not `simple_compatible`.
- [x] Provide a route to advanced UOM management for complex products.
- [x] Do not show only `—` when advanced management is required.
- [x] Changing package/UOM after operational use must follow safe business rules.
- [x] Determine which UOM fields become immutable after inventory/pricing history exists.

---

# 23. Barcodes

Backend already supports proper barcode records.

Required:

- [x] Show active primary barcode(s) in product detail.
- [x] Search by barcode.
- [x] Manage barcodes through backend authority.
- [x] Preserve company-scoped barcode uniqueness.
- [x] Preserve UOM association.
- [x] Preserve effective/active semantics.
- [x] Handle shared base/package barcode safely.
- [x] Do not allow arbitrary client-only barcode replacement.

---

# 24. Simple vs advanced product compatibility

Current backend computes `simple_compatible`.

Required:

- [x] Explain `simple_compatible=false` in UI.
- [x] Show "Advanced product setup required" or equivalent translated wording.
- [x] Do not leave a silent `—` action cell.
- [x] Advanced management entry point appears only when implemented and authorized.
- [x] Preserve the Advanced Pricing roadmap control as visibly disabled until the destination is explicitly activated.

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
- [x] Error report uses stable codes.
- [x] Retry/resume semantics remain durable.

---

# 26. Import internationalization

P6 moved import header/value localization out of the business worker into validated locale packs while preserving explicit mapping as the fail-safe fallback.

Additional languages can extend alias coverage without changing product import workflow logic.

Required:

- [x] Mapping UI remains primary fallback when automatic detection does not understand a header.
- [x] Canonical field IDs stay language-neutral.
- [x] Downloaded template uses current UI language.
- [x] New languages can add alias packs without changing business logic.
- [x] Unknown-language headers do not cause guessing.
- [x] User can explicitly map unknown headers.
- [x] Error report is translated on download/display from stable error codes.

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

- [x] Central locale resolver.
- [x] Arabic may use an Arabic locale.
- [x] English may use an English locale.
- [x] French/German/etc. use their own locale instead of silently falling to `en-US`.
- [x] `Intl.NumberFormat` uses resolved locale.
- [x] `Intl.DateTimeFormat` uses resolved locale.
- [x] Currency formatting uses correct currency + locale.
- [x] RTL/LTR is derived from i18n configuration.
- [x] Long translated labels tested.
- [x] Translation keys for all tracking/lifecycle/UOM labels.

---

# 28. Backend error contracts

Backend includes good stable domain codes in many places, but Pydantic/framework errors can still expose generic English text.

Required:

- [x] Product APIs return stable business error codes.
- [x] UI maps known codes to translations.
- [x] UI never branches on Arabic/English `message`.
- [x] FastAPI validation errors are normalized or mapped into a consistent presentation layer.
- [x] Backend messages may remain diagnostic but are not the localization contract.

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

- [x] No cross-company draft leakage.
- [x] No cross-user draft leakage.
- [x] Tracking settings included in saved draft.
- [x] Draft version incremented when schema changes.
- [x] Invalid old draft safely discarded or migrated.
- [x] User is informed when a draft is restored.
- [x] Explicit cancel removes abandoned durable operation safely.

---

# 31. Company customization

Configuration must keep company-level business defaults separate from user-scoped display preferences:

Business defaults:
- [x] default lot tracking mode,
- [x] default expiry tracking mode,
- [ ] default package UOM,
- [ ] default units/package if useful,
- [ ] product publication workflow policy.

Display preferences:
- [x] visible product columns,
- [x] table density,
- [x] default sort,
- [x] optional detail sections.

Keep business truth separate from display preference.

---

# 32. Product table filtering and sorting

Add operational filters only when useful:

- [x] Family.
- [x] Lifecycle.
- [x] Tracking type.
- [x] Simple-compatible / advanced.
- [x] Has barcode / missing barcode.
- [x] Has price / missing price only when authorized.
- [x] Lot-tracked.
- [x] Expiry-tracked.

Sorting:
- [x] Product name.
- [x] Family.
- [x] SKU.
- [x] Lifecycle.
- [ ] Recently created/updated if required.

All server-side filters occur before pagination.

---

# 33. Accessibility / operator UX

- [x] Keyboard accessible search.
- [x] Keyboard accessible dialogs.
- [x] Visible focus states.
- [x] Buttons/icons have translated aria-labels.
- [x] Status is not communicated by color only.
- [x] Form errors associate with exact field.
- [x] First invalid field receives focus.
- [x] Drawer is keyboard accessible.
- [x] RTL/LTR keyboard and layout smoke tests.

---

# 34. Performance audit

Before Production Ready:

## Product list
- [x] Measure normal unfiltered page.
- [x] Measure name search.
- [x] Measure family search.
- [x] Measure SKU search.
- [x] Measure barcode search.
- [x] Measure common filters.
- [x] Measure page continuation.

Metrics:
- [x] SQL count.
- [x] DB execution time.
- [x] endpoint p50.
- [x] endpoint p95.
- [x] endpoint p99 where practical.
- [x] payload size.

Review:
- [x] No N+1.
- [x] No unbounded `.all()`.
- [x] Stable query count.
- [x] Bounded enrichment.
- [x] EXPLAIN reviewed.
- [x] Indexes justified by evidence.
- [x] Permanent regression gate.

---

# 35. Backend isolation tests

- [x] Cross-company product ID lookup fails closed.
- [x] Cross-company family ID fails closed.
- [x] Cross-company barcode cannot be read/modified.
- [x] Cross-company UOM conversion cannot be read/modified.
- [x] Search never leaks foreign product names.
- [x] Import worker sets and enforces tenant context.
- [x] Import job RLS remains ENABLE + FORCE.
- [x] Product import rows remain tenant-isolated.

---

# 36. Concurrency / idempotency

Preserve existing strong foundations.

Required tests:

- [x] Product create replay is idempotent.
- [x] Changed payload with reused request ID fails.
- [x] Family create/rename concurrency.
- [x] Family version conflict.
- [x] Price update idempotency.
- [x] Barcode uniqueness race.
- [x] Tracking-mode update concurrency.
- [x] Lifecycle transition revision conflict.
- [x] Import replay/resume remains safe.

---

# 37. Product data migration / backward compatibility

Existing products have already been created under the forced:

```text
REQUIRED / REQUIRED
```

Do **not** silently change them.

Required:

- [x] Inventory existing products and their tracking modes.
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

- [x] `product_variant_id`
- [x] base UOM
- [x] valid purchase/receipt UOM options
- [x] quantity scale/step
- [x] `lot_control_mode`
- [x] `expiry_control_mode`
- [x] lifecycle/capability state
- [x] warehouse-specific operational permission/flags where applicable

Once these are stable:
- [x] freeze the Products tracking contract,
- [x] move to Inbound audit.

---

# 39. Frontend architecture cleanup

`ProductsDashboard.tsx` is large and carries many responsibilities.
> **Close-out note:** the remaining unchecked items in this section are non-blocking maintainability refactors. Runtime contracts, table-row/card responsibilities, family management, and shared tracking controls are already separated; the remaining large-form/import/pricing extraction can be done only when it reduces real maintenance cost.

Before it becomes harder to maintain:

- [x] Separate runtime contracts/parsers.
- [ ] Separate product list/table component.
- [ ] Separate create/edit drawer/modal.
- [x] Separate families manager.
- [ ] Separate import workflow.
- [ ] Separate pricing editor.
- [x] Shared product tracking controls.
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

- [x] Simple endpoint delegates to authoritative services.
- [x] No second lifecycle implementation.
- [x] No second barcode authority.
- [x] No second UOM authority.
- [x] No second pricing authority.
- [x] No second tracking-mode authority.

---

# 41. Products page visual UX

Target quality: same clarity as the completed Live Stock page.

- [x] Clear page title/subtitle.
- [x] Search prominent but not oversized.
- [x] Main actions grouped by frequency.
- [x] "Add product" primary.
- [x] Import secondary.
- [x] Families tertiary.
- [x] Advanced functions do not overwhelm ordinary users.
- [x] Consistent rounded surfaces / spacing with dashboard design language.
- [x] Empty state gives useful next action.
- [x] Error state gives retry.
- [x] Product row hover/selection opens detail cleanly.
- [x] No giant unused whitespace.
- [x] Mobile/narrow screens degrade gracefully.

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

- [x] Add short helper text.
- [x] Company default shown/preselected.
- [x] User can change before save.
- [x] Permission-aware.
- [x] Stored values visible later in Product Details.
- [x] Changing after stock exists follows controlled rules.

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

- [x] Product identity can exist without visible pricing permission.
- [x] Price edit only for authorized users.
- [x] Distinguish derived vs explicit package/unit price.
- [x] Explain independent prices when both supplied.
- [x] Exact decimal preview.
- [x] Advanced pricing roadmap control remains disabled/non-navigable until its destination is explicitly usable.
- [x] Pricing changes preserve publication/audit authority.

---

# 45. Product family / variant terminology

The backend has Product + ProductVariant concepts.

The ordinary UI should not force technical terminology on non-technical users unless needed.

- [x] Decide user-facing naming for "family".
- [x] Decide when SKU/variant concept is necessary.
- [x] Keep backend identity untouched.
- [ ] Make terminology consistent across Products, Inbound, Live Stock, and Batches.
- [x] Translation keys use stable semantic identifiers.

---

# 46. Product-location relationship

Backend intentionally uses sparse/lazy `ProductLocation`.

Existing design:
first successful inbound may create the needed warehouse product-location relation.

Preserve:

- [x] Do not mass-provision every product to every warehouse.
- [x] Product identity remains company-wide.
- [x] Warehouse operational settings remain location-specific.
- [x] Products page should not imply a product must be manually assigned to every warehouse before receiving it.
- [ ] If showing warehouse availability later, distinguish company product from location assignment.

---

# 47. Auditability

Product changes must be auditable.

- [x] Product creation audit.
- [x] Family creation/rename audit.
- [x] Barcode changes audit.
- [x] Tracking-mode changes audit.
- [x] Lifecycle changes audit.
- [x] Pricing changes remain auditable.
- [x] Bulk import maintains job/row history.
- [x] Reason required for sensitive changes where appropriate.

---

# 48. Product deletion policy

Do not add a simple Delete button without lifecycle rules.
> **Deferred policy:** current Products does not expose an unsafe hard-delete action. The unchecked items below are a future deletion-policy decision, not a blocker for the current archive/lifecycle-based release.

Required decision:

- [ ] Can a never-used draft be deleted?
- [ ] Can an active/used product only be archived?
- [ ] What happens when product has stock/history/orders?
- [ ] Preserve referential/audit history.
- [ ] UI uses lifecycle/archive semantics instead of unsafe hard delete where appropriate.

---

# 49. Test suite

## Backend

- [x] create product with lot NONE/OPTIONAL/REQUIRED.
- [x] create product with expiry NONE/OPTIONAL/REQUIRED.
- [x] company default application.
- [x] per-product override.
- [x] cross-tenant create/read/update tests.
- [x] product list permission tests.
- [x] catalog-only user without pricing permission.
- [x] barcode conflict tests.
- [x] family conflict/version tests.
- [x] lifecycle transition tests.
- [x] tracking change after inventory tests.
- [x] exact money tests.
- [x] cursor scope/tamper tests.
- [x] import tracking-mode tests.
- [x] import RLS/idempotency tests.

## Frontend

- [x] runtime parser tests.
- [x] create form tracking-mode behavior.
- [x] translated enum labels.
- [x] error vs empty state.
- [x] permission-specific action visibility.
- [x] pricing hidden without permission.
- [x] search reset/cursor behavior.
- [x] family search/pagination.
- [x] Product Detail Drawer.
- [x] import mapping.
- [x] restored draft versioning.
- [x] RTL smoke test.
- [x] LTR smoke test.
- [x] build.

---

# 50. Production release gate

Products can be declared **Production Ready** only when:

- [x] Critical silent REQUIRED/REQUIRED defect is fixed.
- [x] Tracking modes are explicit end-to-end.
- [x] Existing products are handled safely.
- [x] Product read is decoupled from mandatory price access.
- [x] Permissions are granular and correct.
- [x] Runtime frontend contracts are strict.
- [x] Money handling is exact.
- [x] Product search includes identity fields users actually use.
- [x] Error states are distinct.
- [x] Families no longer silently truncate.
- [x] Product detail management reflects the important backend authorities.
- [x] Lifecycle is visible/manageable safely.
- [x] Bulk import supports tracking configuration.
- [x] i18n architecture is language-agnostic.
- [x] RTL + LTR pass.
- [x] Performance audit passes.
- [x] Security/isolation tests pass.
- [x] Relevant backend gates pass.
- [x] Frontend tests/build pass.
- [x] No unresolved blocker/TODO in touched production path.
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
- [x] 5. Add real post-create product identity management beyond price editing.
- [x] 6. Surface and manage barcodes after creation.
- [x] 7. Show SKU in the normal product experience.
- [x] 8. Search by SKU and barcode, not only product/family name.
- [x] 9. Improve list information hierarchy without turning it into a giant table.
- [x] 10. Surface product lifecycle state.
- [ ] 11. Make instant DRAFT→ACTIVE behavior explicit/configurable where appropriate.
- [x] 12. Add safe retire/archive/hold workflows.
- [x] 13. Split coarse frontend `canManage` into capability-specific permissions.
- [x] 14. Stop requiring `pricing.view` just to read product identity.
- [x] 15. Decouple catalog/product read from pricing visibility.
- [x] 16. Add distinct `productsQuery.isError` UI instead of showing empty state.
- [x] 17. Add in-page retry for list failure.
- [x] 18. Fix family management's silent 200-item limit with search/pagination.
- [x] 19. Preserve id-based keyset pagination.
- [x] 20. Scope/harden cursors against reuse across different searches/filters.
- [x] 21. Performance-audit `%LIKE%` search before production signoff.
- [x] 22. Preserve batched enrichment / avoid N+1.
- [x] 23. Explain `simple_compatible=false` rather than showing an unexplained dash.
- [x] 24. Preserve the Advanced Pricing roadmap control as visibly disabled until the destination is explicitly activated.
- [x] 25. Replace TypeScript-only raw-response casts with runtime parsers.
- [x] 26. Runtime-validate families/UOM/import/mutation contracts too.
- [x] 27. Remove JS floating-point money authority (`Number(...)`) from price calculations/formatting.
- [x] 28. Keep frontend derived prices as preview; backend remains authoritative.
- [x] 29. Integer package quantity use of Number is acceptable within bounded validation.
- [ ] 30. Make existing-family vs new-family creation explicit in UX.
- [ ] 31. Reconsider/clarify automatic product-name-as-family behavior.
- [x] 32. Add search/pagination inside family manager.
- [x] 33. Preserve backend case-insensitive family duplicate locking.
- [x] 34. Surface existing barcode authority in normal product UX.
- [x] 35. Preserve strong async/durable import architecture.
- [x] 36. Add lot/expiry configuration to bulk import/template/defaults.
- [x] 37. Generalize import header localization beyond Arabic/English-only alias assumptions.
- [x] 38. Preserve good existing `t(...)` and `dir={i18n.dir()}` foundation.
- [x] 39. Replace binary Arabic-vs-English locale fallback with generic locale resolution.
- [x] 40. Make all new number/date/money rendering language-agnostic.
- [x] 41. Keep API enums stable and translate only in UI.
- [x] 42. Normalize framework/Pydantic validation presentation so untranslated English does not leak.
- [ ] 43. Separate Quick Create from optional enterprise review/maker-checker policy.
- [x] 44. Add a Product Detail Drawer instead of adding too many list columns.
- [x] 45. Keep ordinary creation simple and move complexity to Advanced settings.
- [x] 46. Present lot/expiry tracking in plain user language, not backend field names.
- [ ] 47. Products tracking policy must drive Inbound field requirements.
- [x] 48. Block/guard unsafe tracking-mode changes after inventory exists.
- [x] 49. Guard unsafe UOM/package changes after operational history exists.
- [x] 50. Visually distinguish freely editable, restricted, and workflow-controlled product properties.

---

# 52. Additional findings / requirements beyond the original 50

- [x] 51. Add company defaults for lot/expiry tracking without rewriting existing SKUs.
- [x] 52. Define internal batch identity for `lot_control_mode=NONE`.
- [x] 53. Create a migration/review strategy for existing products that were silently created REQUIRED/REQUIRED.
- [x] 54. Version the saved product draft schema when tracking fields are added.
- [x] 55. Separate business defaults from user display preferences.
- [x] 56. Add Product page performance map and permanent regression gate.
- [x] 57. Add accessibility/keyboard requirements to release gate.
- [ ] 58. Define safe product deletion/archive semantics.
- [x] 59. Ensure normal Products does not duplicate Catalog lifecycle/UOM/barcode authorities.
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

- [x] Product Detail Drawer.
- [x] Quick Create + Advanced.
- [x] Tracking controls.
- [x] Error/retry states.
- [x] granular permissions.
- [x] lifecycle visibility.
- [x] barcode visibility/management.
- [x] simple-compatible explanation.

## Phase P4 — Search / families

- [x] Search name/family/SKU/barcode.
- [x] Family search/pagination.
- [x] Filters/sorting.
- [x] performance audit.

## Phase P5 — Exact pricing / UOM

- [x] Replace float-based money handling.
- [x] Review package/UOM edit safety.
- [x] Connect advanced management where appropriate.
- [x] Before retaining or reconnecting the legacy advanced catalog surface, harden `TabProductCatalog.loadIdentity` against cross-variant stale writes with AbortController plus request-sequence revalidation, and add a runtime A→B race regression test. Decide in P5 whether that surface is retained/split or removed rather than reconnecting it unchanged.

## Phase P6 — Bulk import

- [x] Tracking columns/defaults.
- [x] Generic localization mapping.
- [x] Runtime contracts.
- [x] regression tests.

## Phase P7 — i18n / accessibility / polish

- [x] Generic locale resolver.
- [x] all translation keys.
- [x] RTL/LTR.
- [x] accessibility.
- [x] responsive polish.
- [x] configurable display preferences.

## Phase P8 — Performance / security / release

- [x] query benchmark.
- [x] EXPLAIN.
- [x] isolation tests.
- [x] concurrency/idempotency tests.
- [x] production gate.
- [x] PR + merge.
- [x] local/GitHub alignment.
- [x] declare Products Production Ready.

---

# 54. Products page completion — P9 (active)

P0–P8 hardened the Products backend contracts, security, performance, durability, and release gates. That work is preserved. It does **not** mean the normal Products page is functionally or visually finished.

**Owner requirement:** do not leave Products for another page until the Products experience is functionally complete, every relevant backend capability is intentionally represented or intentionally withheld with a documented reason, avoidable frontend technical debt is removed safely, the final visual redesign is approved, and all regression gates pass again.

## P9.0 — Freeze the current behavior before any refactor

Reference: `docs/products/PRODUCTS_P9_BEHAVIOR_BASELINE.md`

- [x] Record the exact current behavior of the Products page before structural work: queries, mutations, permissions, durable operation scopes, request IDs, retry behavior, cancellation/request-sequence guards, cache invalidation, saved-draft keys, pagination/cursor behavior, and runtime contracts.
- [x] Record a targeted test baseline for every current Product workflow before moving code.
- [x] Create a backend-to-frontend capability matrix covering Simple Products, Catalog, Pricing, lifecycle/hold, barcodes, package/unit structure, families, import, and Product-location/warehouse capabilities.
- [x] For every backend capability, classify it as:
  - normal Products action,
  - advanced Products action,
  - read-only information,
  - intentionally admin/internal only, with the reason documented.
- [x] Identify every Product behavior that currently exists in backend authority but is missing or incomplete in the normal Products page.
- [x] Do not change page behavior or visual design while establishing this baseline.

**P9.0 result:** behavior is frozen at the documented checkpoint. The first functional gaps to resolve in P9.1 are published Product rename, safe family reassignment policy, archived-Product reachability/restore, plain-language unit/package detail, safe package-structure policy, and intentional treatment of family metadata/Product-location/GS1/draft-only capabilities.

## P9.1 — Finish the Product functions before visual polish

### Product identity and family

- [x] Add safe editing of the user-visible product name from the normal Products experience.
- [x] Confirm exactly which underlying identity is being renamed (product family identity vs SKU/variant display identity) so the UI never edits the wrong record.
- [x] Keep family creation and family rename available.
- [x] Make choosing an existing family versus creating a new family unmistakable during product creation.
- [x] Add safe movement of an existing product/SKU to another family only where backend lifecycle/history rules allow it.
- [x] Expose product code/SKU editing only in states where backend authority permits it; otherwise show it as locked with a clear reason.
- [x] Audit backend Product fields such as description/brand/category and decide which belong in the normal or advanced Product experience.
- [x] Preserve optimistic-version/concurrency protection for every identity edit.

### P9.1 Product identity / family closure evidence — 2026-09-25

- Normal Product rename remains variant-display-name editing through the published identity authority; family identity rename remains owned by the family manager.
- Family create/rename remains available with durable request identity; family rename uses `expected_version`.
- Quick Create now makes family intent explicit: no family, select an existing family, or deliberately create a new family. Existing-family typos never silently create a new family.
- Existing published Product/SKU family reassignment is exposed through `PATCH /catalog/variants/{variant_id}/family` and remains backend-authoritative: only ACTIVE/RETIRING may move, real moves are blocked once batch history exists, same-family is a no-op, target family is tenant-scoped, and `expected_version` is required.
- Product Details shows published SKU as intentionally locked. Generic SKU/variant structural editing remains available only to DRAFT variants in advanced Catalog authority; the normal Products read contract contains ACTIVE/RETIRING only, so it does not expose a misleading published-SKU editor.
- Backend `ProductCreate/ProductUpdate` owns `description`, `brand`, and `category` at the catalog Product/family identity level. The Simple Products create/read contracts do not expose them. Decision: keep these fields out of normal Quick Create/details for now and treat them as advanced catalog-level identity fields until a deliberate Simple Products contract is added.
- Optimistic-version protection is retained on every exposed identity mutation: Product rename, family rename, and Product-family reassignment.
- Backend family-reassignment gate: 18 checks / 0 failures / `PRODUCTS_P9_FAMILY_REASSIGNMENT_GATE=PASS`.
- Focused frontend identity/family verification: 8 test files / 53 tests PASS, TypeScript PASS, ESLint PASS, production build PASS.
- Full Dashboard verification after the identity/family batch: ESLint 0 warnings/errors, 34 test files / 205 tests PASS, production build PASS.

### Package and unit structure

- [x] Show clearly what the base stock/selling unit is in plain user language (piece, carton, box, bag, etc.).
- [x] Show package conversion clearly, for example: "1 carton = 50 pieces".
- [x] Complete safe editing of simple package structure where history/lifecycle rules allow it.
- [x] Clearly lock structural edits that would corrupt existing operational history.
- [x] Keep advanced unit/conversion management reachable without forcing ordinary users through technical catalog screens.
- [x] Ensure package/barcode relationships remain authoritative and never create duplicate conversion logic in React.

### P9.1 Package / unit structure closure evidence — 2026-09-25

- Simple Products read contract now exposes authoritative `base_uom_code` from the existing resolved SaleShape for simple-compatible products; no extra query and no frontend guesswork were introduced.
- Product Details shows the base stock/selling unit in user language and renders package conversion in plain language, for example `1 carton = 50 pieces`; unit-only products explicitly explain that no outer package exists.
- Quick Create continues to reveal package-only fields only when `has_package=true`, preserving the simple unit-only path and exact price derivation/override behavior.
- Structural UOM editing remains backend-authoritative and DRAFT-only. Published ACTIVE/RETIRING Products show the structure read-only with a clear lock reason; Advanced UOM remains the specialized route and enforces `UOM_STRUCTURE_LOCKED` outside DRAFT.
- Advanced UOM remains reachable from Products without forcing ordinary Product users through technical catalog internals.
- Simple Product creation continues to send one authoritative package/barcode spec through `/simple-products`; React does not write UOM conversions independently or duplicate backend conversion logic.
- Backend P2 read-contract gate: 11 checks / 0 failures / `PRODUCTS_READ_CONTRACT_P2_GATE=PASS`.
- Backend UOM safety gate: 7 checks / 0 failures / `PRODUCTS_P5_UOM_SAFETY_GATE=PASS`.
- Focused package/unit frontend verification: 9 test files / 60 tests PASS, TypeScript PASS, ESLint PASS, production build PASS.
- Full Dashboard verification after package/unit work: 35 test files / 211 tests PASS, ESLint 0 warnings/errors, production build PASS.
- Aggregate Products production gate: 19 checks / 0 failures / `PRODUCTS_P8_PRODUCTION_GATE=PASS`.

### Tracking, barcodes, lifecycle, hold, and pricing

- [x] Keep lot/batch-number tracking and expiry tracking visible in plain language.
- [x] Keep safe tracking-mode editing and its history lock behavior.
- [x] Keep barcode add/deactivate/manage workflows reachable from Product Details.
- [x] Keep lifecycle actions and operational hold/recall actions reachable and understandable.
- [x] Keep price visibility permission-aware and price editing permission-aware.
- [x] Explain derived versus directly entered package/unit prices in the UI where relevant.
- [x] Ensure all sensitive mutations retain durable request identity, retry safety, auditability, and concurrency protection.

### P9.1 Tracking / barcode / lifecycle / hold / pricing closure evidence — 2026-09-25

- Product Details keeps lot/batch and expiry tracking visible through localized plain-language mode labels and keeps the tracking editor reachable with explicit backend-owned history/lifecycle lock guidance.
- Tracking defaults and Product tracking edits remain tenant-scoped and backend-authoritative. Product tracking writes retain optimistic `expected_version`, exact audit/outbox evidence, and runtime history locking through `PRODUCT_TRACKING_LOCKED`.
- Barcode management remains reachable from Product Details. Create/deactivate/update workflows preserve durable command identity; barcode updates retain `expected_version`, backend uniqueness authority, and catalog audit evidence.
- Lifecycle management remains reachable from Product Details and delegates to the shared Catalog lifecycle authority for publish/retire/restore/archive plus sales hold/release and recall/close-recall. Those commands retain durable request identity, `expected_version`, lifecycle guards, domain audit/outbox events, and tenant isolation.
- Pricing remains permission-separated: `pricing.view` controls visibility while `pricing.manage` controls editing. The UI explains that one entered package/unit price derives the other, while entering both stores them independently.
- Price and tracking workflows were hardened from request-ID-only persistence to full durable-command persistence. After an ambiguous result they restore and replay the exact original payload/request identity; changed payloads cannot silently create a new logical retry, while deterministic failures may abandon the stale command.
- Price backend authority remains idempotent, locks the tenant Product row, records `SIMPLE_PRODUCT_PRICE_UPDATED_V3` audit evidence, and delegates price publication rules to the pricing service.
- Permanent focused P9 frontend regression added in `dashboard/src/test/products-tracking-lifecycle-pricing-p9.test.ts`.
- Focused frontend verification after hardening: 6 test files / 50 tests PASS, TypeScript PASS, touched-file ESLint PASS.
- Backend focused verification: `PRODUCT_TRACKING_PRODUCTION_GATE=PASS` (4/4), `PRODUCT_LIFECYCLE_GATE=PASS` (14/14), and `PRODUCTS_P8_CONCURRENCY_IDEMPOTENCY_GATE=PASS` (10/10).
- During the full release gate, P2 exposed a non-canonical Base64URL cursor-alias edge case. Cursor decoding was hardened to reject non-canonical encodings across Simple/Product/Family cursors and a permanent regression was added; corrected `PRODUCTS_READ_CONTRACT_P2_GATE=PASS` is 12/12 and P4 search/family pagination remains 47/47 PASS.
- Final Dashboard verification: 36 test files / 216 tests PASS, TypeScript PASS, ESLint 0 warnings/errors, production build PASS.
- Final aggregate Products production gate: 19 checks / 0 failures / `PRODUCTS_P8_PRODUCTION_GATE=PASS`.

**Next P9.1 group:** Product-location / warehouse relationship.

### Product-location / warehouse relationship

- [x] Audit existing warehouse-specific Product-location capabilities.
- [x] Expose only useful operator actions; do not imply every product must be manually assigned to every warehouse.
- [x] If warehouse availability/assignment is shown, distinguish company-wide product identity from warehouse-specific operational state.
- [x] Preserve lazy/sparse Product-location behavior unless a measured business requirement justifies changing it.

### P9.1 Product-location / warehouse relationship closure evidence — 2026-09-25

- Product catalog identity remains company-wide. Warehouse-specific operational state remains owned by the separate `ProductLocation` authority and its granular location-scoped `product_location.read` / `product_location.manage` permissions.
- Normal `ProductsPage` and Product Details intentionally do not call `/warehouse/product-locations` and do not require Product-location permissions. This prevents the normal Products experience from implying that every Product must be manually assigned to every warehouse.
- Useful explicit operator actions already exist in the advanced Inventory/Catalog lifecycle surface: list/create/update/delete Product-location assignments, including inbound/outbound operational flags, durable commands, optimistic versions, and safe retry recovery.
- Assignment copy explicitly states that creating a warehouse assignment does not create stock or a stock policy, keeping company Product identity distinct from location-specific operational setup.
- First successful Inbound to a selected warehouse lazily creates only missing Product-location rows with default operational flags. Existing explicit flags are never overwritten; the helper uses the tenant-safe unique assignment constraint and emits `ProductLocationAssigned` audit/outbox evidence with reason `AUTO_FIRST_INBOUND`.
- The Inbound workflow checks exact warehouse permission before lazy assignment, excludes system-managed/inactive targets, keeps Product lookup company-scoped, and fails closed on missing/cross-tenant Products.
- Product-location delete remains history-safe through `product_location_delete_blockers`, location-scoped authorization, idempotency, lifecycle guards, and `expected_version`.
- The detailed Section 46 future checkbox about displaying warehouse availability remains intentionally open: normal Products does not currently display warehouse availability/assignment, so no misleading company-vs-location availability UI is introduced.
- Permanent Product-location regression gate was strengthened to cover the frontend ownership boundary and granular permissions: `STAGE75_PRODUCT_LOCATION_INBOUND_GATE=PASS` — 26 checks / 0 failures.
- The Product-location gate is now part of the aggregate Products release gate.
- Final Dashboard verification: 36 test files / 216 tests PASS, TypeScript PASS, ESLint 0 warnings/errors, production build PASS.
- Final aggregate Products production gate: 20 checks / 0 failures / `PRODUCTS_P8_PRODUCTION_GATE=PASS`.

**Next P9.1 group:** Delete/archive policy.

### Delete/archive policy

- [x] Decide whether a never-used draft product may be physically deleted.
- [x] Decide when a used/published product must be retired or archived instead of deleted.
- [x] Preserve all stock, sales, audit, import, pricing, and historical references.
- [x] Do not expose a hard-delete action until the backend policy is explicitly safe.
- [x] Ensure the UI explains why delete is unavailable when history exists.

### P9.1 Delete/archive policy closure evidence — 2026-09-25

- Final policy: physical delete is allowed only for an unpublished, never-used `DRAFT` with no operational hold and no preserved business/history references. Any Product that has been published or used follows the lifecycle path (`ACTIVE -> RETIRING -> ARCHIVED`) and is never hard-deleted.
- Draft hard-delete policy is centralized in `product_lifecycle.py`. The schema audit found 28 company-scoped `ProductVariant` reference surfaces; all 28 are now explicitly classified with no missing/stale references.
- Only three draft-owned/derived references may disappear with a clean draft: `product_barcodes`, `product_uom_conversions`, and the derived `inventory_live_stock_projection`. The remaining 25 reference surfaces are explicit hard-delete blockers.
- Blockers are grouped into operator-readable categories covering warehouse/stock history, sales/returns/visits, imports, pricing, offers, and tax references. Audit/outbox history remains append-only and the successful draft deletion itself emits `ProductDraftDeleted` evidence.
- Backend now exposes `GET /catalog/variants/{variant_id}/delete-draft-preflight`; the destructive endpoint independently rechecks lifecycle state, publish/retire/archive timestamps, optimistic version, and all business blockers inside the protected mutation path.
- The advanced Catalog lifecycle UI no longer exposes the permanent delete command immediately. It first runs the backend preflight, shows translated blockers when deletion is unsafe, and exposes `Permanently delete draft` only after a current safe preflight.
- Normal Product Details intentionally still does not pass `onVariantDeleted`, so hard delete remains absent from the normal Products lifecycle surface.
- Permanent frontend regression: `dashboard/src/test/products-delete-archive-policy-p9.test.ts` — 4 tests PASS.
- Permanent backend policy/runtime gate: `PRODUCTS_P9_DELETE_ARCHIVE_POLICY_GATE=PASS` — 16 checks / 0 failures. Runtime evidence verifies a clean draft passes preflight, a draft with batch history is blocked, the backend rechecks blockers even after UI preflight, a clean never-used draft can be deleted with audit evidence, and a published Product is rejected from hard delete.
- Existing lifecycle protection remains green: `PRODUCT_LIFECYCLE_GATE=PASS` — 14/14.
- Final Dashboard verification: 37 test files / 220 tests PASS, TypeScript PASS, ESLint 0 warnings/errors, production build PASS.
- Final aggregate Products production gate: 21 checks / 0 failures / `PRODUCTS_P8_PRODUCTION_GATE=PASS`.

**Next P9.1 group:** Create/import/detail completeness.

### Create/import/detail completeness

- [x] Audit Create Product against the final capability matrix so no required backend property is accidentally omitted.
- [x] Keep Quick Create simple while exposing advanced fields only when useful.
- [x] Audit bulk import against the same final Product contract.
- [x] Complete Product Details so important identity, family, package structure, tracking, barcodes, lifecycle/hold, pricing, and available actions are visible without technical jargon.
- [x] Keep loading, error, retry, empty, stale-data, and offline states explicit and non-misleading.
- [x] Keep permissions granular: viewing identity must not accidentally grant pricing or mutation authority.

### P9.1 Create/import/detail completeness closure evidence — 2026-09-25

- Quick Create was audited against the authoritative `SimpleProductCreate` request contract. It sends the complete normal Product contract: name, explicit family intent, optional package UOM, units per package, package/unit prices, unit/package barcodes, and explicit lot/expiry tracking modes. No required backend property is omitted.
- Quick Create remains intentionally compact. Ordinary identity/family/package/price fields stay in the primary flow; per-Product tracking overrides and barcodes stay inside the deliberate Advanced section. Backend-managed SKU/base-unit/lifecycle internals are not duplicated as ordinary user inputs.
- Quick Create retry identity was hardened from request-ID-only persistence to a full durable command. An ambiguous create now restores the exact original form intent and request identity across reopen/remount; changed payloads fail closed with `DURABLE_OPERATION_PENDING` instead of silently creating a second logical Product request. Deterministic coded failures may clear the stale command, while ambiguous/contract-uncertain results retain it.
- Bulk import was audited against `CANONICAL_IMPORT_FIELDS`. Frontend mapping and backend canonical import authority contain the same 10 fields: `name`, `family`, `package_uom`, `units_per_package`, `package_price`, `unit_price`, `unit_barcode`, `package_barcode`, `lot_control_mode`, and `expiry_control_mode`. Import-wide tracking defaults and per-row overrides remain explicit.
- Import upload keeps its file-content/name/type/size fingerprint plus tracking defaults in durable identity; status/mapping/retry/resume/error-report flows remain asynchronous and backend-authoritative.
- Product Details now covers ordinary Product identity and family, SKU, base unit and package conversion in plain language, tracking, barcodes, lifecycle/operational hold, permission-aware pricing, simple/advanced compatibility, and the available rename/family/price/tracking/barcode/lifecycle/advanced-UOM actions without exposing raw catalog internals.
- Loading/error/retry/empty/offline behavior remains explicit: Product list has distinct loading/error/retry/empty states; Create disables mutation offline and explains local draft retention; Import distinguishes tracking-default load errors, queued/poll errors, mapping, validation failure, retryable failure, progress, completion, and offline-disabled mutations. Product list does not use cross-query previous-data placeholders; same-query refetch is signaled by `isFetching` in the header and pagination is disabled while refreshing.
- Permission authority remains granular. Catalog identity/read/manage/publish capabilities are separate from `pricing.view` and `pricing.manage`; catalog-only reads continue to hide real prices, while mutation buttons are derived from their action-specific capabilities.
- Permanent focused regression added in `dashboard/src/test/products-create-import-detail-completeness-p9.test.ts` — 5 tests PASS. Existing P3/P8 regressions continue to cover list states and action-specific permission wiring.
- Focused verification after Quick Create hardening: 4 test files / 26 tests PASS, TypeScript PASS, touched-file ESLint PASS.
- Stage 7.3 gate was updated from its obsolete request-ID-only source assertion to require the stronger full-command/restore behavior: `STAGE73_PRODUCT_UX_I18N_NETWORK_GATE=PASS` — 18/18.
- Final Dashboard verification: 38 test files / 225 tests PASS, TypeScript PASS, ESLint 0 warnings/errors, production build PASS.
- Final aggregate Products production gate: 21 checks / 0 failures / `PRODUCTS_P8_PRODUCTION_GATE=PASS`.

**P9.1 status:** complete. The next unfinished Products phase is **P9.3 — Functional Product-page acceptance before redesign**; P9.2 is already closed.

## P9.2 — Decide and execute the Products frontend split safely

Current `ProductsDashboard.tsx` is a high-risk change surface because it combines page composition, many state variables, queries, mutations, create/import/pricing workflows, filtering, durable-operation recovery, and substantial markup.

**No split is authorized merely because the file is large. The split starts only after P9.0 establishes the behavioral baseline and the owner approves the extraction sequence.**

### Approved P9.2 extraction sequence — 2026-09-25

The Products page will use the repository-wide vertical feature-slice rule in `ARCHITECTURE.md`. Structural checkpoints must preserve behavior exactly and may not introduce P9.1 functionality or visual redesign.

1. Extract pure leaf/presentational page pieces first, leaving state, queries, mutations, durable commands, query keys, storage keys, and callbacks owned by the current route entry.
2. Establish feature-owned folders for the major workflows as they are extracted: `list/`, `create/`, `import/`, `pricing/`, and later `family/`; existing page-owned barcode/tracking/lifecycle/display-preference/advanced-UOM boundaries remain intact until their own safe move is justified.
3. Extract search/filter/sort/pagination presentation and then its state/query orchestration as a separate checkpoint.
4. Extract Create Product presentation first, then its validation/draft/durable workflow owner without changing the create contract.
5. Extract Import presentation first, then upload/mapping/poll/retry/resume orchestration while preserving request sequencing, abort/cancellation, durable identity, and pagination.
6. Extract price-edit presentation first, then its exact-money derivation and mutation workflow while preserving pricing permissions and cache invalidation.
7. Move only genuinely page-level composition state back into the thin route entry; do not create a replacement god hook/component.
8. After every checkpoint run focused tests and TypeScript; after each completed workflow boundary run the relevant Product regression set; before closing P9.2 run full Dashboard tests/lint/build and the Product aggregate gate.
9. Only after behavioral equivalence is proven, remove stale duplicate code and perform the final dependency/dead-code review.

- [x] Approve the exact extraction sequence before touching runtime code.
- [x] Give Products its own clean page folder ownership under `dashboard/src/pages/products/`; the route entry becomes a thin composition/orchestration layer.
- [x] Separate by responsibility, not arbitrary line count.
- [x] Extract pure visual/leaf components first without moving state or network logic.
- [x] Extract Create/Edit Product workflow into its own component/workflow boundary.
- [x] Extract search/filter/sort/pagination controls into their own page-owned boundary.
- [x] Extract import workflow into its own page-owned boundary.
- [x] Extract price-edit workflow into its own page-owned boundary.
- [x] Extract display-preference modal/state/save ownership into `products/display-preferences/` with behavior parity preserved.
- [x] Keep family, barcode, tracking, lifecycle, display-preference, and advanced-unit flows page-owned and clearly separated.
- [x] Move queries/mutations/state into dedicated hooks/workflow owners only when doing so reduces coupling; never duplicate authority merely to reduce file size.
- [x] No single function or component may become a new "god function" that performs unrelated workflows.
- [x] Preserve exact query keys, cursor resets, cache invalidation, durable-operation scopes, storage keys, error codes, abort/request-sequence behavior, permissions, and retry semantics.
- [x] Structural refactor commits must not include behavior changes or visual redesign.
- [x] Run focused tests/type checks after every extraction checkpoint; stop immediately on any behavioral difference.
- [x] After the split, run the full Product tests/build gates before beginning visual redesign.
- [x] Review for dead/stale duplicate code after equivalence is proven.

### P9.2 closure evidence — 2026-09-25

- Final route entry is `dashboard/src/pages/products/ProductsPage.tsx`; legacy `dashboard/src/pages/ProductsDashboard.tsx` was removed after route/source-test migration.
- Product feature ownership is split into page-owned vertical folders including `advanced-uom/`, `barcode/`, `create/`, `detail/`, `display-preferences/`, `family/`, `import/`, `lifecycle/`, `list/`, `pricing/`, `rename/`, and `tracking/`.
- Legacy duplicate Product component locations were removed only after path migration and regression proof; final old-path audit reported `OLD_PRODUCT_PATHS=0`.
- Product aggregate regression after final folder cleanup: 20 test files / 117 tests PASS.
- Final Dashboard closure gate: ESLint 0 warnings / 0 errors, 32 test files / 194 tests PASS, production build PASS.
- No intentional Product behavior or visual redesign was included in P9.2.

## P9.3 — Functional Product-page acceptance before redesign

- [x] Walk through creating a product with and without packaging.
- [x] Walk through editing product name/identity where allowed.
- [x] Walk through creating, renaming, selecting, and safely changing family.
- [x] Walk through package/unit structure and locked-history behavior.
- [x] Walk through barcodes.
- [x] Walk through tracking settings.
- [x] Walk through lifecycle, archive/retire, operational hold, and recall where authorized.
- [x] Walk through prices with and without pricing permission.
- [x] Walk through import success, validation failure, retry, resume, and error pagination.
- [x] Walk through search by name/family/SKU/barcode, all filters, sorting, next/previous pagination, and cursor resets.
- [x] Walk through catalog-only, pricing-only where applicable, manager, and read-only permission combinations.
- [x] Confirm every backend capability in the P9.0 matrix is either reachable, visible read-only, or intentionally hidden with a documented reason.
- [x] No unresolved functional gap remains before visual redesign.

### P9.3 functional acceptance closure evidence — 2026-09-25

- The remaining P9.0 lifecycle reachability gap was resolved without redesign: normal Products still defaults to `ACTIVE` / `RETIRING`, but the lifecycle filter now explicitly supports `ARCHIVED`, so authorized operators can locate an archived Product and use the existing backend-authoritative Restore flow. `DRAFT` remains intentionally absent from the normal Products list.
- Runtime regression proves both sides of that boundary: archived Products stay hidden from the default normal list and `lifecycle=ARCHIVED` returns the archived restore target. `PRODUCTS_SEARCH_FAMILIES_P4_GATE=PASS` now contains 49 checks.
- Create acceptance covers packaged and unit-only Products. The Simple Products backend still proves package-only price derivation, unit-only price derivation, independent explicit prices, and unit-only creation without an outer package.
- Published Product identity editing remains split correctly: Product rename is distinct from family rename/reassignment, preserves optimistic versioning and audit/outbox evidence, and cannot mutate structural identity indirectly. `PRODUCTS_P9_RENAME_GATE=PASS` — 17/17.
- Family acceptance covers create, rename, select/search, and published family reassignment. History-bearing moves fail closed while safe history-free moves remain available. `PRODUCTS_P9_FAMILY_REASSIGNMENT_GATE=PASS` — 18/18.
- Package/unit structure remains readable in normal Product Details. Structural UOM/conversion mutation remains DRAFT-only and separated in Advanced UOM; published structure continues to fail closed with `UOM_STRUCTURE_LOCKED`. `PRODUCTS_P5_UOM_SAFETY_GATE=PASS` — 7/7.
- Barcode acceptance retains list/create/deactivate/history behavior, pagination, strict Product scope, race protection, durable retry recovery, optimistic versions, and uniqueness authority. Barcode GS1 parsing remains intentionally unexposed as an optional advanced/convenience helper; no scanner/parse workflow is required for normal Products.
- Tracking acceptance covers company defaults, per-Product edits, import snapshots/overrides, history locking, tenant isolation, optimistic versions, audit/outbox, and durable retry identity. `PRODUCT_TRACKING_PRODUCTION_GATE=PASS` — 4/4.
- Lifecycle acceptance covers retire, restore, archive preflight/archive, sales hold/release, recall/close-recall, and the newly reachable ARCHIVED restore path. Hard delete remains intentionally excluded from normal Products and is available only through the protected advanced DRAFT preflight policy. `PRODUCT_LIFECYCLE_GATE=PASS` — 14/14 and `PRODUCTS_P9_DELETE_ARCHIVE_POLICY_GATE=PASS` — 16/16.
- Pricing acceptance keeps Product identity independent from pricing authority: `catalog.read` can read identity without real prices, `pricing.view` controls visibility/filtering, and `pricing.manage` controls simple-price mutation. Full price-book/publication/assignment administration remains intentionally outside normal Products.
- Import acceptance covers upload, tracking defaults and per-row overrides, mapping, validation failure, retryable failure, durable retry, session resume, completion, and bounded error pagination/export. Existing import gates remain green, including Stage 7 Simple Products, P6 localization, and Product Import Tracking.
- Search acceptance covers Product name, family, SKU, effective barcode, all server filters, stable sorting, signed cursor scope, next/previous pagination, cursor resets, and tenant isolation. P4 remains 49/49 PASS after the ARCHIVED extension.
- Permission acceptance was exercised across read-only/catalog-only, pricing-view, pricing-manage, catalog-manage/publish, lifecycle-authorized, and full-manager combinations. Creation/import still requires its combined catalog/publish/pricing authority; pricing-only authority does not grant catalog mutation.
- Final P9.0 matrix decisions are explicit: raw Catalog Product/Variant creation, DRAFT publish/delete, family metadata fields (code/description/brand/category), published SKU/GTIN/base-UOM structural edits, Product-location administration, GS1 parse helper, and full Pricing administration remain intentionally advanced/internal rather than duplicated into normal Products.
- Product-location administration remains location-scoped in Inventory/Catalog, while normal Product identity remains company-wide. Advanced UOM remains a separate Product-owned advanced surface. Display preferences remain user presentation state only.
- Permanent frontend acceptance regression added in `dashboard/src/test/products-functional-acceptance-p9.test.ts` — 9/9 PASS. The focused P9.3 acceptance set finished 4 files / 26 tests PASS, and the updated family regression plus acceptance set finished 15/15 PASS.
- Final Dashboard verification: 39 test files / 234 tests PASS, TypeScript PASS, ESLint 0 warnings/errors, production build PASS.
- Final aggregate Products production gate: 21 checks / 0 failures / `PRODUCTS_P8_PRODUCTION_GATE=PASS`.

**P9.3 status:** complete. **STOP before P9.4.** No P9.4 visual/usability implementation is authorized or included in this closure.

## P9.4 — Full Products visual and usability rebuild

- [x] Agree on the final information hierarchy before cosmetic coding.
- [x] Redesign the page header and action priority.
- [ ] Redesign search, filters, sorting, and active-filter visibility.
- [x] Redesign desktop product list/table for fast scanning without excessive columns.
- [ ] Redesign mobile Product cards independently where needed instead of shrinking the desktop table.
- [ ] Redesign Product Details so ordinary users understand the product without backend terminology.
- [ ] Redesign Create/Edit Product for a fast ordinary flow plus a clear advanced section.
- [ ] Redesign Families management.
- [ ] Redesign Barcode management.
- [ ] Redesign Tracking settings.
- [ ] Redesign Lifecycle/Hold actions.
- [ ] Redesign Pricing interaction.
- [ ] Redesign Import workflow.
- [ ] Redesign loading, empty, failure, retry, offline, and permission-denied states.
- [ ] Remove awkward whitespace, clutter, duplicated controls, and unclear action hierarchy.
- [ ] Icons are presentation-only and must be changeable without touching unrelated business workflows.
- [ ] Preserve RTL/LTR, translation safety, keyboard navigation, focus management, accessibility, responsive behavior, and configurable display preferences.
- [ ] Owner visual acceptance is mandatory; automated tests alone do not close the design.

## P9.5 — Final production verification

- [ ] Re-run targeted Product frontend tests.
- [ ] Re-run the full Dashboard test suite.
- [ ] TypeScript PASS.
- [ ] ESLint PASS with zero warnings.
- [ ] Production build PASS.
- [ ] Re-run relevant backend Product gates.
- [ ] Re-run the aggregate Products production gate.
- [ ] Re-run performance/security/isolation/concurrency gates affected by any new Product mutation/read path.
- [ ] Review final diff for duplicated business authority.
- [ ] Review final diff for stale/legacy Product UI paths and dead code.
- [ ] Review final folder/file ownership against `ARCHITECTURE.md`.
- [ ] Verify no new large multi-responsibility file/function replaced `ProductsDashboard.tsx`.
- [ ] Final manual owner walkthrough and visual approval.
- [ ] PR review complete.
- [ ] PR merged to `main`.
- [ ] Local `main == origin/main`.
- [ ] Only then declare the **Products page itself** fully complete and archive this plan again.

---

# 55. Historical P0–P8 release evidence


Products P0–P8 is closed and **Production Ready** on `main`.

Release history:
- PR #24 merged the original P8 performance / EXPLAIN / isolation / concurrency checkpoint.
- PR #25 merged the main P8 production-gate hardening.
- PR #26 merged zero-warning/deprecation/performance-evidence cleanup.
- PR #27 merged the measured 250,000-row common-filter growth fix at `5be3843032d183d1074d6fcb87c9f6925768f946`.
- The user then pulled the merged `main`, made the intentional local housekeeping edit, and pushed current `main` commit `3fa2e59a650e9b93c17fa276e5fd5a1cff839cb8` (`edit local file`).

Production-gate evidence completed on this branch:

- Runtime mutation contracts are strict for Product create, price update, import mapping, and import retry.
- Package-UOM and import-polling failures are distinct from loading/empty states and are retryable.
- Normal Products lifecycle management reuses the authoritative Catalog lifecycle implementation instead of creating a second authority.
- Lifecycle commands use durable request identity, optimistic versioning, archive preflight, existing backend permissions, audit/outbox, and the existing lifecycle lock/idempotency authorities.
- `operational_hold` is a strict Simple Products read-contract field and is visible in Product table/card/detail surfaces.
- Full Dashboard verification after release cleanup passed: 31 files / 188 tests, TypeScript PASS, ESLint 0 errors / 0 warnings with `--max-warnings=0`, and production build PASS.
- Corrected Product read-contract runtime gate passed: 11 checks / 0 failures / `PRODUCTS_READ_CONTRACT_P2_GATE=PASS`.
- Permanent read-only existing-product audit added: `wa_backend/scripts/gate_products_p8_existing_products.py`.
- Real database inventory classified 120,212 Product variants: 120,173 history-bearing and 39 history-free.
- 120,154 REQUIRED/REQUIRED review candidates were safely classified: 120,133 `HISTORY_LOCKED`, 21 `REVIEWABLE_NOW`, 0 `LIFECYCLE_BLOCKED`.
- Existing-product audit ran with `transaction_read_only=on`, found no invalid tracking/lifecycle states, no orphan/cross-tenant batch history, and matched the real `PRODUCT_TRACKING_LOCKED` authority.
- Existing-product result: 8 checks / 0 failures / `PRODUCTS_P8_EXISTING_PRODUCTS_GATE=PASS`.
- No TODO/FIXME/HACK/XXX marker remains in the reviewed touched Product production path.

Final aggregate P8 production gate is complete:

- Dashboard TypeScript PASS.
- Dashboard full suite PASS: 31 files / 188 tests.
- ESLint PASS with 0 errors / 0 warnings; the release gate rejects warnings with `--max-warnings=0`.
- Production build PASS in 13.43s.
- All 13 backend release gates included by `gate_products_p8_production.py` passed after stale source-layout assertions were updated to the current component architecture.
- Aggregate result: 17 checks / 0 failures / `PRODUCTS_P8_PRODUCTION_GATE=PASS`.
- The stale-gate repair changed only release-gate assertions; it did not change Product runtime/business logic.

PR review found two governance blockers after the successful aggregate gate:

- The modified legacy `CatalogLifecyclePanel.tsx` still contained hardcoded Arabic user-facing copy and non-durable ProductLocation mutation request IDs.
- ProductLocation DELETE idempotency checked the source row before replay lookup, so an ambiguous successful delete could not replay after the row was gone.

The review fixes now localize the touched ProductLocation surface, persist full ProductLocation commands with durable request identity, retain unresolved commands on ambiguous/invalid responses, and make ProductLocation DELETE replay-safe after the source row is removed. The Stage 3 lifecycle gate now contains an exact runtime replay regression for this case.

The post-review hardening passed targeted verification and the complete aggregate release gate again:

- Dashboard full suite: 31 files / 188 tests PASS.
- Stage 3 lifecycle/ProductLocation runtime verification PASS, including exact DELETE replay after source-row removal.
- Release-cleanup branch `fix/products-release-cleanup` removed all seven React Fast Refresh warnings by separating non-component exports; the aggregate gate now rejects any lint warning with `--max-warnings=0`.
- Deprecated `datetime.utcnow()` usage in the P8 isolation gate was replaced while preserving the project UTC-naive database contract; every backend production gate now runs with `-W error::DeprecationWarning`.
- The P4 performance gate now sizes the benchmark from the largest current tenant (bounded by a 250,000-row safety cap), records PostgreSQL cost-based planner decisions, validates installed trigram-index shape, and verifies barcode GIN planner capability with an isolated temporary exact-DDL probe so competing validity indexes cannot create false evidence.
- Targeted performance verification passed: 25 checks / 0 failures / `PRODUCTS_P4_PERFORMANCE_AUDIT=PASS` / `PRODUCTS_P8_PERFORMANCE_GATE=PASS`.
- Final full aggregate after all three release-cleanup fixes: 17 checks / 0 failures / `PRODUCTS_P8_PRODUCTION_GATE=PASS`.
- A dedicated 250,000-variant growth certification exposed a real `common_filters` seek problem: the prior ACTIVE-name index removed 175,001 rows and the main plan executed in roughly 365 ms.
- A measured partial seek index, `ix_product_variant_simple_common_filters_seek`, now targets the proven filter shape without changing endpoint or business semantics. On the same 250,000-variant probe the planner used the new index, removed only 1 row, and the main SQL plan executed in roughly 0.4 ms.
- The permanent P4 performance gate now verifies that the common-filter seek index is installed, ready, valid, and structurally correct.
- The 250,000-row growth probe passed with 20 runs and cleanup PASS. Its endpoint wall-time is recorded as diagnostic evidence only; no arbitrary latency SLA was introduced because the main SQL seek regression was independently proven fixed and the project has no agreed fixed-environment latency budget.
- Post-index regression verification passed: Dashboard 31 files / 188 tests, production build PASS, and the complete aggregate production gate again returned 17 checks / 0 failures / `PRODUCTS_P8_PRODUCTION_GATE=PASS`.
- No endpoint, pricing, filtering, lifecycle, tenant-isolation, or other business behavior was changed by the growth fix; the branch diff is limited to the migration/model index metadata, performance-gate index verification, and the dedicated growth-certification script.
- PR #27 is merged, the post-index aggregate gate passed again at 17 checks / 0 failures, and the local/GitHub transition was completed before the user's current `main` commit.

**Historical P0–P8 close-out:** backend/release hardening was completed, but the Products page was reopened by owner decision for functional completeness and final redesign. P9 above is now the active source of truth before leaving Products.

Current P7 state:

- [x] Generic locale resolver.
- [x] all translation keys.
- [x] RTL/LTR.
- [x] accessibility.
- [x] responsive polish.
- [x] configurable display preferences.

Verified P7 locale-resolver checkpoint:

- shared project-level locale authority exists in `dashboard/src/lib/locale.ts`;
- `currentLocale()` delegates to the shared resolver;
- production formatting is gated against hardcoded regional locales, binary Arabic/English fallbacks, and direct raw i18n locale bypasses;
- bare `ar` / `en` use app regional defaults while explicit/future locales remain language-correct;
- TypeScript passed;
- locale resolver tests passed: 8/8;
- targeted P7 tests passed: 3 files / 13 tests;
- full dashboard suite passed: 25 files / 157 tests;
- production build passed in 17.96s.

Verified P7 translation-key checkpoint:

- Product translation resources are Arabic/English key-parity gated.
- Static Products translation references and bounded dynamic lifecycle/tracking/UOM/barcode label families are bilingually covered.
- Product-facing stable error codes are gated against translation resources.
- FastAPI/Pydantic validation arrays normalize to stable `VALIDATION_ERROR` presentation.
- Coded backend diagnostic messages are not used as localized UI copy when a stable code is present.
- TypeScript passed with no output.
- Targeted P7 translation/error/UOM/barcode tests passed: 6 files / 44 tests.
- Full dashboard suite passed: 26 files / 164 tests.
- Production build passed in 25.54s.

Verified P7 Products RTL/LTR checkpoint:

- Product root, Product detail drawer, and shared Product modal direction follow `i18n.dir()`.
- Product UI uses logical edge utilities instead of physical left/right spacing utilities.
- Product pagination arrows and Advanced UOM back navigation mirror correctly by direction.
- Permanent RTL/LTR source gate added in `dashboard/src/test/product-rtl-ltr-p7.test.ts`.
- TypeScript passed with no output.
- RTL/LTR gate passed: 1 file / 4 tests.
- Related Product tests passed: 16 files / 103 tests.
- Full dashboard suite passed: 27 files / 168 tests.
- Production build passed in 24.20s.
- Scope is Products P7; this checkpoint does not claim every non-Product dashboard surface has been audited for RTL/LTR.

Verified P7 Products accessibility checkpoint:

- Product search controls are keyboard reachable and have translated accessible names.
- Shared Product modal and Product detail drawer use a reusable focus trap with Tab/Shift+Tab containment, Escape close, initial focus, and opener-focus restoration.
- Product surfaces expose visible `focus-visible` styling.
- Product icon-only controls covered in this scope have translated `aria-label` values.
- Product status/lock/compatibility meaning is conveyed with text, not color alone.
- Client-side Product, pricing, family, and Advanced UOM validation errors use `aria-invalid` / `aria-describedby` and inline alert text.
- First invalid Product form field receives focus.
- Permanent accessibility gate added in `dashboard/src/test/product-accessibility-p7.test.tsx`.
- TypeScript passed with no output.
- Accessibility gate passed: 1 file / 4 tests.
- Related Product tests passed: 17 files / 107 tests.
- Full dashboard suite passed: 28 files / 172 tests.
- Production build passed in 12.13s.
- Scope is Products P7; this checkpoint does not claim every non-Product dashboard surface has been audited for accessibility.

Verified P7 Products responsive checkpoint:

- Products switches from the wide data table to dedicated Product cards below 768px; the desktop table remains unchanged for wider screens.
- Product header actions, search controls, filters, pagination, modal footers, drawer actions, family rows, barcode rows, and Advanced UOM layout degrade without horizontal UI dependence on narrow screens.
- Shared Product modals use dynamic viewport height and stacked narrow-screen actions.
- Long Product/family/SKU values and synthetic long translated labels are wrap-safe on narrow surfaces.
- Permanent responsive gate added in `dashboard/src/test/product-responsive-p7.test.tsx`.
- Runtime media-query test proves breakpoint changes react without reload.
- TypeScript passed with no output.
- Responsive gate passed: 1 file / 5 tests.
- Related Product tests passed: 18 files / 112 tests.
- Full dashboard suite passed: 29 files / 177 tests.
- Production build passed in 12.19s.
- Scope is Products P7; this checkpoint does not claim every non-Product dashboard surface has been audited for responsive behavior.

Verified P7 Products configurable display-preferences checkpoint:

- Product display preferences are explicitly separated from company business defaults.
- Preferences are versioned and scoped by authenticated `company_id + driver_id`; one company/user cannot reuse another scope's saved view.
- Unsupported/corrupt preference schemas fail safely to current defaults.
- Visible Product columns are configurable for package, units/package, tracking, lifecycle, unit barcode, package barcode, package price, and unit price while Product identity/actions remain fixed.
- Pricing columns and the pricing detail section remain subordinate to pricing permission; display preference cannot grant pricing visibility.
- Desktop table and mobile Product cards consume the same visible-column and density preferences.
- Table density supports comfortable and compact modes.
- Default sort field/direction are configurable and become the reset baseline for Product list filters.
- Product detail drawer sections are configurable for package, tracking, barcodes, pricing, and compatibility.
- Preferences persist across normal logout while session credentials and tenant/session identifiers are cleared.
- Dynamic preference labels are covered by the bilingual translation gate.
- Permanent regression gate added in `dashboard/src/test/product-display-preferences-p7.test.tsx`.
- Focused verification passed: 6 files / 30 tests.
- Corrected P2 read-contract gate passed independently: 1 file / 10 tests.
- TypeScript passed with no output.
- Related Product tests passed: 19 files / 117 tests.
- Full dashboard suite passed: 30 files / 182 tests.
- Production build passed in 13.63s.
- Scope is Products P7; these are user-scoped display preferences, not company-wide business policy.

Verified P7 close-out review checkpoint:

- `feat/products-i18n-accessibility-p7` is based directly on current `main` with no behind commits at close-out review time.
- Branch compare at review: 131 commits ahead / 0 behind, with 59 changed files.
- Product P7 implementation trackers are all complete: locale resolver, translation keys, RTL/LTR, accessibility, responsive polish, and configurable display preferences.
- No `[~]` implementation item remains in the Products plan; the only `[~]` text left is the legend definition.
- No TODO/FIXME/HACK/XXX marker exists in the reviewed touched Product production files; the plan's release-gate checklist text itself still contains the word TODO by design.
- Non-Product frontend changes in this branch were reviewed: they are the generic locale-resolver rollout needed to remove hardcoded regional formatting assumptions.
- Catalog-contract changes were reviewed as stable coded-error normalization supporting bilingual Product error presentation.
- Login/TopBar/Sidebar storage changes were reviewed as the intentional company-code hint and user-scoped display-preference persistence behavior.
- Repository governance additions (`ARCHITECTURE.md`, `.rules`, `AGENTS.md`, and Foundation Stage 12) are intentional changes requested during this branch and must be called out explicitly in the P7 PR.
- Latest verified local gate before close-out: TypeScript PASS; Product targeted 19 files / 117 tests; full dashboard 30 files / 182 tests; production build PASS in 13.63s.
- Historical P7 checkpoint note: P8 was unopened at that time; P8 is now complete and Production Ready.

Next implementation order:

1. Translation-key audit is complete and verified.
2. RTL/LTR is complete and verified for Products surfaces.
3. Accessibility is complete and verified for Products surfaces.
4. Responsive polish is complete and verified for Products surfaces.
5. Configurable display preferences are complete and verified.
6. P7 implementation is complete.
7. P7 close-out review / gate synchronization is complete.
8. P7 PR merged and local/GitHub transition prerequisite satisfied.
9. P8 order: final query benchmark → EXPLAIN review → isolation tests → concurrency/idempotency tests → production gate → PR/merge → local/GitHub alignment → Production Ready declaration.

P8 is now active. Do not skip forward past a failing gate.

Verified P8 Product performance / EXPLAIN checkpoint:

- Final Product performance gate ran with 5,000 seeded Product rows and 20 measured runs per scenario.
- All 21 performance checks passed; `PRODUCTS_P4_PERFORMANCE_AUDIT=PASS` and `PRODUCTS_P8_PERFORMANCE_GATE=PASS`.
- Measured scenarios include unfiltered page, name/family/SKU/barcode search, common filters, has-price filter, page continuation, and page-size scaling.
- SQL query count remained stable; 10-row and 100-row pages both executed 17 queries, proving no page-size N+1 growth.
- Product-list enrichment remained page-bounded and there is no unbounded list materialization.
- Endpoint/application+DB p50/p95/p99, payload bytes, SQL profiles, and DB EXPLAIN execution were captured.
- Search trigram indexes were present and valid. PostgreSQL did not select them at the measured 5,000-row cardinality; forced-index plans were not faster, so no additional search index change is justified.
- The initial has-price EXPLAIN used a repeated Seq Scan on the very small `price_publications` test table. This was treated as a scale-evidence question rather than as an automatic index defect.
- A permanent `gate_products_p8_price_publication_scale.py` regression gate now seeds 10,000 additional Product-publication rows, runs ANALYZE, executes the real has-price Product query, and fails on a repeated full-table Seq Scan.
- At 10,001 tenant publications PostgreSQL selected `Index Scan` on `uq_price_publication_company_id_book`, with 501 loops, one row per loop, zero rows removed, and Product-plan execution of 2.963 ms.
- Scale gate result: `PRICE_PUBLICATION_SCALE_DECISION=NO_REPEATED_FULL_SCAN`, cleanup PASS, statistics restoration PASS, and `PRODUCTS_P8_PRICE_PUBLICATION_SCALE_GATE=PASS`.
- No new `price_publications` index is justified by the measured evidence.
- The temporary failed scale fixture exposed the immutable published-history trigger as designed; the fixture was changed to deletable DRAFT rows and the guarded one-time residue cleanup recovered the synthetic 10,000-row tenant successfully.
- Performance and EXPLAIN are closed; P8 proceeds to backend isolation tests.

Verified P8 backend isolation checkpoint:

- Permanent gate added: `wa_backend/scripts/gate_products_p8_isolation.py`.
- Final PostgreSQL isolation run passed: 15 checks / 0 failures / `PRODUCTS_P8_ISOLATION_GATE=PASS`.
- Foreign Product IDs and foreign Family IDs fail closed through the real Product APIs.
- Foreign barcode and UOM-conversion reads and modifications fail closed.
- Direct RLS reads hide foreign barcode and UOM-conversion rows.
- Product search returns no foreign-tenant Product/family identity.
- `product_import_jobs` and `product_import_rows` both retain ENABLE + FORCE RLS.
- Product-import worker sessions set the exact `app.current_tenant` value before tenant-owned reads.
- Foreign import jobs and rows remain invisible inside the worker tenant session.
- Gate cleanup completed successfully; no synthetic isolation fixture residue remains.
- Isolation is closed; P8 proceeds to concurrency/idempotency verification.

Verified P8 concurrency / idempotency checkpoint:

- Permanent runtime gate: `wa_backend/scripts/gate_products_p8_concurrency_idempotency.py`.
- Final PostgreSQL run passed: 10 checks / 0 failures / `PRODUCTS_P8_CONCURRENCY_IDEMPOTENCY_GATE=PASS`.
- Exact Product-create replay returns the original response and persists exactly one idempotency record.
- Reusing a Product-create request ID with a changed payload fails closed.
- Price-update replay returns the original response and does not publish a duplicate price revision.
- Concurrent family creation with the same normalized name serializes correctly and produces one winner.
- Concurrent family rename to the same target name serializes correctly and rejects the conflicting contender.
- Stale family versions fail with `SIMPLE_PRODUCT_FAMILY_VERSION_CONFLICT`.
- Concurrent barcode creation with the same active barcode produces one winner and one `BARCODE_CONFLICT`.
- Lifecycle mutation increments Product version/lifecycle revision once and a stale expected version fails with `VARIANT_VERSION_CONFLICT`.
- Existing tracking-mode concurrency and import replay/resume gates remain part of the accepted foundation.
- Gate cleanup completed successfully after guarded cleanup of synthetic pricing, idempotency, outbox, and append-only audit evidence.
- One-time residue cleanup support is guarded to synthetic `P2 Read Contract Gate A/B` companies with `P2READ-*` codes and fails closed outside that scope.
- Concurrency/idempotency is closed. Production-gate work is intentionally not started in this checkpoint.
