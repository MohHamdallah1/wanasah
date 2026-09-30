# Product / Variant Identity Audit — Phase A1

Date: 2026-09-29. Status: **historical A1 static snapshot, independently reviewed; NOT current implementation behavior after A2**.

> **Read the current contracts first:** [CATALOG_IDENTITY_GLOSSARY.md](CATALOG_IDENTITY_GLOSSARY.md) and `docs/archive/WANASAH_URGENT_CATALOG_INDEX_QUEUE_SCALING_PLAN_2026-09-29.md` (historical). A2 has since made Quick Create family intent explicit and extended master name length to 200; all source-line claims below describe the original audit baseline, not the current branch. Remaining full Gate A coverage is still open.
Workspace verified: `C:\Users\admin\Desktop\wanasah-hardening`.
Branch verified: `hardening/catalog-index-worker-fairness`; source baseline: `c66af5b192e12d4a422036b68fbd9d0dc953fc04`; initial working tree clean.
Read AGENTS.md, .rules, ARCHITECTURE.md, the workflow-protection rule, and the urgent plan's Phase A requirements and identity evidence. No application changes, database access, tests, builds, benchmarks, migrations, cleanup, or master-plan edits were performed. Phases B–G were not investigated.

## Finding

The inspected operational paths use **ProductVariant.id as the concrete item identity**. Product.id is the parent/master; no inspected stock, price, or cost path pools balances by that parent. Family is the current UI/API name for the master. Category is a nullable master string, not a separate classification entity in the inspected model. Packaging is a variant-specific unit conversion, not automatically another SKU.

One deterministic validation defect is established by source: a 151–200-character item name passes the create DTO but fails automatic parent resolution when family is omitted. Family intent also loses precision across the Dashboard/API boundary. Same-name parent reuse is proven behavior, but incorrect real-world grouping or accounting corruption was not established.

## Verified domain model and vocabulary

| Concept / suggested Arabic label | Actual authority | Evidence |
|---|---|---|
| Product master / أصل المنتج | `products`: company, code, name, description, brand, category, version. One parent can have many variants. Company+code is unique; name is not unique in this ORM declaration. | `wa_backend/models.py:244–263` |
| Family / عائلة المنتج | Simple Products family operations create/select Product rows; not a second Family table in this path. | `wa_backend/domains/simple_products/service.py:650–684`, `798–878` |
| Category / تصنيف المنتج | `Product.category` is nullable text; advanced catalog accepts it alongside brand/description. It is distinct from the family/master ID. | `wa_backend/models.py:256–258`; `wa_backend/api/catalog.py:288–304`, `570` |
| Variant / الصنف القابل للبيع; SKU / رمز الصنف | `product_variants.id` is the relational item identity; `sku` is its company-unique business code. `product_id` refers to the master. Lifecycle, tracking, base UOM and quantity precision live on the variant. | `wa_backend/models.py:265–342` |
| UOM / وحدة القياس | Global UOM ID/code; per-variant exact rational conversions. Simple Products uses EACH as base, with zero or one selected outer UOM. EACH does not prove that the physical base is a loose piece. | `wa_backend/models.py:38–43`, `349–383`; `wa_backend/domains/simple_products/service.py:58`, `906–924` |
| Outer packaging / التعبئة الخارجية | Conversion and barcode attached to the same variant. `packs_per_carton` is a compatibility quantity field; actual outer UOM can differ from CARTON. | `wa_backend/models.py:338–341`; `wa_backend/domains/simple_products/service.py:1024–1087` |
| Barcode / الرمز الشريطي | Variant+UOM presentation/scanning identity; active barcode uniqueness is company-wide. Separate base and outer barcodes do not create separate variants. | `wa_backend/models.py:385–418`; `wa_backend/domains/simple_products/service.py:1042–1087` |

These labels are recommendations for the glossary, not approved UI replacements or a schema migration. No independently tracked shipping-package identity was established in this bounded review.

## Critical identity and dependency map

All locators below refer to repository-relative source paths at the baseline. Ranges identify inspected evidence, not runtime verification.

| Boundary | Verified identity / dependency | Source evidence |
|---|---|---|
| Advanced catalog | Master creation stores Product; variant creation validates tenant-scoped Product.id and stores it as parent. Separate operations permit a legitimate empty master. | `wa_backend/api/catalog.py:560–580`, `676–685` |
| Simple creation | Resolve/create master, create a new variant for each spec, attach conversion/barcodes, publish lifecycle and variant/UOM prices. Reusing a master does not reuse its variant. | `wa_backend/domains/simple_products/service.py:975–1087`, `1090–1116`, `1156–1192` |
| Import execution | `normalized_data` becomes SimpleProductSpec; delegates to the same creation authority; imported row and replay response retain `product_variant_id`. Durable batch UUID derives from job+row identities. | `wa_backend/domains/simple_products/imports/application/execution_service.py:57–74`, `207–234`, `349–469` |
| Import lineage FK | Import row's optional item link targets company+ProductVariant.id, not master. | `wa_backend/models.py:837–861` |
| Master FK | Variant `(company_id, product_id)` targets `products(company_id,id)`, RESTRICT. | `wa_backend/models.py:291–296` |
| UOM / barcode / assignment FKs | Conversion, barcode and ProductLocation target company+variant; ProductLocation is sparse operational permission/configuration, not quantity/value storage. | `wa_backend/models.py:349–394`, `909–925` |
| Physical stock | InventoryBalance key is company+location+variant+batch+status. Batch itself belongs to company+variant. Balance/movement composite batch FKs prevent linking another variant's batch in the declared model. | `wa_backend/models.py:2442–2460`, `2707–2736`, `2923–2927` |
| Supplier inbound | Tenant-scoped variants and selected UOM feed base quantity plus actual purchase cost/UOM evidence; movement carries variant+batch and calls the unified engine before commit. | `wa_backend/api/warehouse/inbound.py:502–526`, `734–745`, `830–881`; `wa_backend/schemas.py:1761–1765` |
| Movement → costing | Unified movement engine invokes costing with those movements and specs in the same session. Cost event copies variant/batch from the movement. | `wa_backend/services.py:3962–3970`; `wa_backend/domains/inventory_costing/service.py:403–440` |
| Valuation | CostState is unique per company+variant. Cost layers and events reference variant and its batch; allocation links cost event to layer within company. Parent is not the valuation key. | `wa_backend/models.py:467–492`, `501–523`, `595–609`, `653–672` |
| Financial FIFO vs physical FEFO | FIFO selects company/variant layers by created_at,id, independent of movement batch; moving average uses that variant's state. FEFO receives variant requests and location separately. Internal two-ended movements are excluded from cost changes. | `wa_backend/domains/inventory_costing/service.py:444–447`, `554–569`, `627–652`, `845–879`; `wa_backend/services.py:5223–5262` |
| Pricing | PriceBookEntry FK targets variant. Published overlap/resolution key includes company, book, variant, UOM and effectivity; resolver additionally applies publication/context limits. | `wa_backend/models.py:1412–1443`; `wa_backend/domains/pricing/resolver.py:247–270` |
| Sales | Driver requests resolve tenant-owned variants; VisitItem stores `product_variant_id`; sale and sample movements use the same variant with server-selected batches. Samples use VISIT_SAMPLE_OUT. | `wa_backend/api/driver.py:1092–1111`, `1552–1617`; `wa_backend/models.py:1894–1897` |
| Commercial evidence | VisitItem declares canonical quantity/base UOM, selected price entry/revisions and money snapshots; driver calls freeze_sales_evidence. Reward evidence FK also targets variant. The freeze implementation itself is outside coverage. | `wa_backend/models.py:1996–2017`; `wa_backend/api/driver.py:1638–1652`; `wa_backend/domains/sales_evidence/models.py:337–350` |
| Dashboard | Simple list `id` = variant; `product_id` = master; create response uses explicit `product_variant_id`. Client contracts preserve both meanings. | `wa_backend/api/simple_products.py:1817–1823`, `1981–1984`; `dashboard/src/pages/products/contracts.ts:223–227`, `268`, `509–512` |
| Flutter / offline | Driver inventory/catalog returns variant as `id`. ProductModel parses `id` or `product_variant_id`; cart uses productVariantId; visit submission serializes `product_variant_id`; local deduction uses that same identity. | `wa_backend/api/driver.py:3481`, `3644`; `wanasah_frontend/lib/models/product_model.dart:31–43`; `wanasah_frontend/lib/models/cart_item_model.dart:3–4`; `wanasah_frontend/lib/blocs/visit/visit_bloc.dart:226–246`, `455–473`; `wanasah_frontend/lib/core/db/local_database.dart:450–464` |

**SQL/DDL spot checks:** import barcode conflict SQL joins existing barcode by company+barcode and scopes staged updates by company+job+row (`wa_backend/domains/simple_products/imports/infrastructure/repository.py:533–561`). Costing DDL explicitly references product_variants, not products (`wa_backend/alembic/versions/fa7c9d3e1b24_stage74_inventory_costing.py:132–133`, `172–176`, `230–238`); its RLS helper enables and forces tenant RLS (`29–44`) and declares append-only triggers for cost events/allocations (`285–302`). This is source intent, not proof of deployed schema, trigger effectiveness, or later migration parity.

## _resolve_family: exact behavior

| Input / collision | Actual result | Evidence in `wa_backend/domains/simple_products/service.py` |
|---|---|---|
| Both ID and non-null name | Reject SIMPLE_PRODUCT_FAMILY_AMBIGUOUS; ID does not silently override name. | `806–811` |
| Explicit family ID | Lookup Product by authenticated company and ID; missing/foreign-company master gives NOT_FOUND. | `813–826` |
| Explicit nonblank name | Strip surrounding whitespace, validate <=150 characters, company-scoped case-insensitive exact-name lookup. | `828–859`; normalization `118–151` |
| Omitted/blank name | Use spec.name as parent name, again with a 150-character bound; this is a default master, not a category. | `828–843` |
| No existing match | Create Product(company, generated FAM code, name); brand/category/description are unset by this path. | `871–878` |
| Exactly one match | Reuse it, regardless of its brand/category/description, for either explicit-name or omitted-family input. | `850–869` |
| At least two matches | Reject SIMPLE_PRODUCT_FAMILY_NAME_AMBIGUOUS; caller must choose ID. | `858–867` |
| Repeated same-name specs | Reuse master, create a distinct SKU variant for each spec, subject to barcode and other validation. | `975–1040` |

Name lookup is protected by a transaction advisory lock scoped by company and stripped/lowercased name (`324–339`, `845–849`). It is not fuzzy matching: no size, brand, Unicode normalization, or internal-whitespace equivalence is checked. Stored names are compared with SQL lower(name), not SQL trim(name).

Different sizes explicitly assigned to one family become separate variants. With family omitted, different size-bearing names normally create different masters; identical names with different packaging can share one master but still create separate variants. This does not make those variants UOM aliases automatically.

Standalone create_family rejects an existing same-name master (`650–675`), whereas _resolve_family reuses one. Advanced Product creation accepts name+code and does not perform the same name lock/check (`wa_backend/api/catalog.py:560–580`); ORM uniqueness is company+code (`wa_backend/models.py:247–250`). Thus duplicate names are representable in the inspected source, and ambiguity handling is necessary. Actual duplicate populations/concurrent behavior were not measured.

## Confirmed problems, distinct from unproven impact

1. **Validation defect — implicit 150-character limit on a 200-character item name.** `wa_backend/api/simple_products.py:90–94` accepts 200 characters; `wa_backend/domains/simple_products/service.py:977` also validates 200, but omitted family reaches `838–842` and validates the same name at 150. A 151–200-character name with otherwise valid inputs fails with SIMPLE_PRODUCT_FIELD_INVALID; the same item name can pass with an explicit valid family ID/short name. Source-proven branch behavior; no test executed. Import execution shares this authority, but whether import validation blocks such a row earlier was not inspected.
2. **Family-intent contract mismatch.** Dashboard distinguishes `none` and `new` (`dashboard/src/pages/products/create/createProductFamilyIntent.ts:30–59`), but its request serializer transmits only family_id/family_name (`dashboard/src/pages/products/create/productCreateCommand.ts:215–220`). Server cannot enforce “create a new master” separately from “find or create by name”; the name branch reuses an existing master. `none` still resolves a mandatory master, which can be shared. This is a confirmed loss of intent/semantic precision, not proof that an existing accounting transaction is wrong. Choosing the desired behavior requires owner approval.
3. **Naming ambiguity — product_id has different meanings across APIs.** Simple Products uses product_id for master (`wa_backend/api/simple_products.py:1820`); driver dashboard inventory uses product_id for variant (`wa_backend/api/driver.py:2595–2597`); a request schema aliases productId to product_variant_id (`wa_backend/schemas.py:1328`). The inspected Flutter sale path uses the correct variant identity. No wrong-ID stock operation was demonstrated; broad renaming would risk existing clients.

**Not established as defects:** fewer Product rows than ProductVariant rows; a one-variant master; empty masters; two barcodes for one variant; or financial FIFO consuming a cost layer from a different physical FEFO batch. Those can all follow the current model. The plan's earlier import counts (34,999 variant links / 7,510 parents) are prior evidence, not measurements repeated here, and do not by themselves show lost products.

## Recommended commercial/accounting model and minimal proposals

Preserve the plan's four concepts: optional classification, Product master/shared identity, concrete Variant/SKU, and UOM/outer packaging. Catalog owns identity and conversions; Inventory owns base-unit quantities by SKU/location/batch/status; Pricing owns variant+UOM commercial prices; Costing owns company+SKU valuation; Sales retains transaction evidence. Do not create a new SKU solely for another barcode or fixed-count outer package unless independent stocking/tracking is an explicitly approved requirement.

Preserve immutable purchase unit-cost/UOM evidence and independent acquisition-order FIFO; physical FEFO remains deterministic book allocation, not proof of exact carton identity. Preserve MOVING_AVERAGE/FIFO selection and locking on first costed receipt, no value/COGS changes for internal transfers, and external-exit cost evidence. The inspected service activates/locks policy at `wa_backend/domains/inventory_costing/service.py:275–315`; it defaults to MOVING_AVERAGE if no policy exists, so this review does not prove the operator explicitly selected a method before activation.

| Minimal proposed work, subject to review | Risk / decision |
|---|---|
| Agree a canonical glossary and document existing endpoint ID meanings first; add explicit typed/aliased master_id and variant_id in a compatible contract if needed. | Preserve old fields and persisted Flutter/durable-command payloads; do not rename tables as a cosmetic fix. |
| Resolve the 150/200 mismatch in the owning catalog contract and import validation together. | Owner must choose whether default-master naming supports full item names or the accepted input is constrained; do not silently truncate or change name-based grouping. |
| Specify an explicit family/master resolution policy: choose existing ID, explicitly create, or approved default-master behavior. | No blind automatic regrouping. New intent fields affect idempotency hashes, imports and retries; preserve stable operation IDs and reject different-input reuse. |
| Decide whether same-name reuse is intended when brand/shared identity differs; if not, prefer explicit master identity or approved unique default masters. | Existing descendants and category/brand interpretation must be assessed before reassignment; names alone cannot establish identity. |
| Treat a first-class category dimension as a separate future requirement only if the nullable string is insufficient. | Category migration, hierarchy and tenant ownership are not authorized by this audit. |
| Have ChatGPT verify the cited branches and later run focused negative/compatibility tests. | Suggested cases: 150/151/200-character names; omitted/explicit/duplicate family names; same-name distinct brands; mismatched master/variant IDs; cross-company and wrong-variant batch links; two SKUs with independent prices/costs; lost-response import replay; Flutter offline round-trip. None run here. |

## Unverified concerns and coverage gaps

- No live database reads: deployed FKs/RLS/triggers, migration head, actual catalog collisions, and the plan's eight company-38 masters without variants remain unverified. Separate master creation makes emptiness possible; it does not classify those eight rows.
- Inspected ORM constraints are not a complete SQL dependency inventory. Only one costing migration was read; no historical migration sweep, views/functions inventory, full raw-SQL inventory, or execution plans. Later guards may strengthen the declarations described here.
- CostEvent has separate company-safe movement and variant/batch FKs, not a declared FK tying the movement's SKU to the event's SKU (`wa_backend/models.py:507–523`). Allocation separately references event and layer (`662–672`). The reviewed application derives consistent IDs; bypass-write resistance and any additional database guards remain unverified, not a proven reachable corruption path.
- Likewise VisitItem's selected price entry FK is company-safe but does not itself prove matching SKU/UOM (`wa_backend/models.py:1896`, `1914–1918`). Resolver identity is correct in inspected code; exhaustive sales evidence/return/revision enforcement was outside the cap.
- No exhaustive reports, taxation, offers, sales returns, dispatch, stocktake, reconciliation, transfer, lifecycle/reassignment, audit/outbox consumer or legacy endpoint review. Reward schema and driver movement branches were sampled, not all external exits.
- Dashboard review covered identity DTOs and creation intent only. Flutter review covered model, visit serialization, sync parsing and local deduction identity; not every screen/repository, cache tenant boundary, or offline recovery behavior. Carton/pack compatibility is explicitly resolved to a variant-specific UOM by `wa_backend/domains/sales_calculation/driver_sale.py:70–158`; advanced UOM end-to-end support was not proven.
- Import parser/validation services and standalone idempotency authority were not read. Execution lineage/replay was traced, but no proof of every validation, retry, hash-conflict or transaction failure scenario is claimed.
- Stock/purchase/sale UOM defaults, catch weight, kits, physical handling units, independent packaging SKUs and a richer category model remain scope/design questions, not defects inferred from missing fields in this sample.
- A1/Gate A remains open pending independent review and the owner's decisions. No implementation or workflow change is authorized by this report.

## Source coverage register — exactly 25 files

Targeted sections/searches only; repository instructions and the plan are additional governance documents, not source files in this cap.

1. `wa_backend/models.py`
2. `wa_backend/domains/simple_products/service.py`
3. `wa_backend/domains/simple_products/imports/application/execution_service.py`
4. `wa_backend/api/simple_products.py`
5. `wa_backend/domains/inventory_costing/service.py`
6. `wa_backend/services.py`
7. `wa_backend/domains/pricing/resolver.py`
8. `wa_backend/domains/uom_authority.py` — variant-scoped loading and exact conversion (`96–140`, `218–271`).
9. `wa_backend/api/driver.py`
10. `wa_backend/api/warehouse/inbound.py`
11. `wa_backend/domains/sales_calculation/driver_sale.py`
12. `wa_backend/domains/sales_evidence/models.py`
13. `dashboard/src/pages/products/contracts.ts`
14. `dashboard/src/pages/products/create/productCreateCommand.ts`
15. `dashboard/src/pages/products/create/createProductFamilyIntent.ts`
16. `wanasah_frontend/lib/models/product_model.dart`
17. `wanasah_frontend/lib/models/cart_item_model.dart`
18. `wanasah_frontend/lib/repositories/sync_repository.dart` — inventory parsing (`93–108`, `477–478`).
19. `wa_backend/api/catalog.py`
20. `wa_backend/schemas.py`
21. `wa_backend/alembic/versions/fa7c9d3e1b24_stage74_inventory_costing.py`
22. `wanasah_frontend/lib/blocs/visit/visit_bloc.dart`
23. `wanasah_frontend/lib/core/db/local_database.dart`
24. `wa_backend/domains/simple_products/imports/infrastructure/repository.py`
25. `dashboard/src/pages/products/create/useCreateProductMutation.ts` — family intent in durable command and serialized request (`230–257`, `310`).
