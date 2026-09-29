# Catalog identity dictionary | قاموس هوية الكتالوج

**Scope:** Code/API review vocabulary for Wanasah. Not a database migration, UI rename, or new business classification. The same concepts apply across company boundaries, while each tenant's data is isolated.

| Arabic | English | Authoritative identity | Meaning |
| --- | --- | --- | --- |
| أصل المنتج | Product Master / Parent | `Product.id`, table `products` | Shared identity/description/brand/category of a product; it is **not** the sellable stock unit. |
| عائلة المنتجات (تسمية الواجهة الحالية) | Family (current Simple Products UI) | **Same** `Product.id` | The UI's family selector points to the Product master. It is **not** a separate `families` table or a marketing category. |
| الصنف القابل للبيع | Sellable Variant / SKU | `ProductVariant.id`, table `product_variants` | Actual item identity for inventory/valuation/sales/prices, subject to authoritative domain rules. The string `sku` is its company-scoped business code. |
| تصنيف تسويقي | Catalog Category | `Product.category` (currently optional text) | Optional classification, separate from Product master/family. No first-class category table is assumed. |
| وحدة القياس | Unit of Measure (UOM) | `UOM.id` and variant-specific conversion | EACH, CARTON, PACK, etc. Conversion is attached to a variant. |
| العبوة الخارجية | Outer Package | Variant UOM conversion and optional package barcode | A 24-piece carton of one SKU normally refers to the **same variant**, not 24 new SKUs or a new sellable variant. |
| دفعة / صلاحية | Batch / Expiry | `ProductBatch` tied to company + variant | Batch belongs to one SKU; an inventory balance cannot combine another variant's batch. |

## Concrete example

- Master: "Lolo chips" (`products.id = P`).
- SKU 1: "Lolo chips 20g" (`product_variants.id = V1`, `product_id=P`).
- SKU 2: "Lolo chips 50g" (`product_variants.id = V2`, `product_id=P`).
- Carton of 24 units for V1: UOM conversion/barcode of **V1**. It does not turn V1 into another SKU. V1 and V2 keep independent quantities/prices/cost identities.
- "Snacks": optional **category**, not an alias for P.

## Compatibility and naming traps

1. In the Simple Products list response, `id` identifies **Variant**, `product_id` identifies **Master**, and `family_name` is the master's name. A historical driver API may use the key `product_id` to identify a **Variant**. Always verify the named endpoint's contract; never infer type from the key alone. Prefer explicit `product_variant_id` for transactional interfaces when their compatibility contract allows it.
2. In the modern Quick Create request, `family_mode=none` means create an independent master for this new SKU, even if a master with the same name exists. `existing` requires `family_id`; `new` requires `family_name` and rejects a duplicate name in that company. This is implemented in Phase A2.
3. Older API clients and bulk-import rows omitting `family_mode` retain their historical name-based find-or-create parent behavior for compatibility. Do not silently change or migrate old histories; review the product-import contract and existing idempotent requests before changing this.
4. The ORM names `Product` and `ProductVariant` and physical tables `products`/`product_variants` remain **unchanged**. A rename touches composite FK/RLS, migrations, SQL, APIs and Flutter/offline; terminology should not be "fixed" via a blind table rename.
5. A master with 0 variants can be legitimate (separate master creation), but historical orphan classification requires creation audit evidence. A one-variant master is also valid; neither count indicates financial corruption by itself.
6. Check the tenant-safe composite keys and FORCE RLS at the database, not merely ORM intent. Pricing/costing/inventory writes are owned by their own domains, never by UI or import normalization.
7. The company costing-method selection before the first costed receipt is an independently governed business rule; this glossary makes no change to its current behavior.

**Related:** `ARCHITECTURE.md`; `wa_backend/domains/simple_products/imports/README.md`; `docs/architecture/PRODUCT_VARIANT_IDENTITY_AUDIT.md`; `WANASAH_URGENT_CATALOG_INDEX_QUEUE_SCALING_PLAN_2026-09-29.md`. Actual code and explicit business policy take precedence over narrative examples.
