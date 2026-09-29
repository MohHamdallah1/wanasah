# Product identity for Dashboard maintainers

Product list: `id` is the sellable SKU/Variant, while `product_id` is the Product Master. The `family` selector addresses that master and is not an independent category. Quick Create uses explicit `family_mode` (none, existing, new), unlike legacy/import inputs that omit that field. Stock, price, sales and costing must use the variant identity. Read `docs/architecture/CATALOG_IDENTITY_GLOSSARY.md` and preserve typed IDs, tenant isolation and durable request IDs.
