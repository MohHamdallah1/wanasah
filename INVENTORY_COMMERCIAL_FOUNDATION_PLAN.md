# Inventory & Commercial Foundation Plan

**الحالة:** OWNER-APPROVED ARCHITECTURAL BASELINE — IMPLEMENTATION IN PROGRESS (STAGES 0–3 COMPLETE)

**تاريخ الاعتماد:** 2026-09-11

**النطاق:** تأسيس المستودعات والمنتجات ودورة حياتها، الدفعات والصلاحية، التسعير والعروض والضرائب، سياسات المخزون، التقييم المالي، عقود Dashboard وFlutter/Offline، والعزل متعدد الشركات.

**مرجعية التنفيذ:** هذا الملف هو المرجع الأساسي الملزم لهذه المرحلة. أي تعديل على قرار معماري أو Business Workflow وارد هنا يحتاج مناقشة مسبقة وموافقة صريحة من مالك المشروع. لا يجوز تفسير بند غامض بتغيير سير العمل بصمت.

---

## 1. دستور المرحلة

1. InventoryBalance هو المصدر الوحيد للحقيقة SSOT للأرصدة الحالية.
2. كل تغيير كمية أو حالة مخزنية يمر حصراً عبر Unified Inventory Movement Engine.
3. كل سجل تشغيلي أو مالي تابع لشركة يحمل company_id صريحاً، وتفرض قاعدة البيانات عزله بواسطة PostgreSQL RLS.
4. الـBackend هو السلطة النهائية للصلاحيات، الموقع، المخزون، السعر، العرض، الضريبة، التوقيت، وحالة المستند.
5. لا يملك الاسم أو الكود التجاري أي سلطة أمنية أو تشغيلية خاصة.
6. لا اختيار لأول مستودع ولا مستودع افتراضي ضمنياً في أي أمر مخزني.
7. كل حركة تحدد location_id أو source_location_id وdestination_location_id صراحة وفق عقدها.
8. بيانات المنتج Master Data مستقلة عن وجود مستودع أو رصيد أو سياسة مخزون.
9. البيانات المالية والمستندات المرحّلة immutable؛ التصحيح يتم بعكس أو مستند مقابل، وليس بتعديل التاريخ.
10. لا حذف لمنتج أو مستودع أو مستند مستخدم تاريخياً. الحذف مسموح فقط لكيان Draft لم يُستخدم ولم يُنشر وفق فحص صريح.
11. لا Workflow change أثناء التنفيذ إلا بعد تعديل هذا الملف بموافقة مالك المشروع.
12. قاعدة البيانات الحالية فارغة، ولذلك نبني المخطط الصحيح بلا Compatibility Shims أو Backfills لتاريخ غير موجود.
13. لا حذف لأي ملف أو مجلد من المشروع أثناء هذه الخطة إلا بأمر صريح من المالك وبعد التحقق من الهدف.

---

## 2. خط الأساس الحالي الذي يجب إعادة التحقق منه قبل التنفيذ

هذه الإشارات تصف مواضع معروفة وقت كتابة الخطة. قبل أي Patch يجب قراءة الملف الفعلي والتأكد من الـanchors وعدم الاعتماد على أرقام الأسطر وحدها:

- wa_backend/api/warehouse.py: مسار GET للمواقع ينشئ WH-MAIN ضمنياً تقريباً في النطاق 507–579.
- wa_backend/api/warehouse.py: إنشاء المنتج ينشئ مستودعاً وسياسات ضمنية تقريباً في النطاق 2857–2887.
- wa_backend/api/platform.py: إنشاء Company وHQ Branch وAdmin تقريباً في النطاق 173–235، من دون إنشاء مستودع.
- wa_backend/models.py: ProductVariant الحالي تقريباً في النطاق 282–313 ويحتوي حقول أسعار مباشرة.
- wa_backend/models.py: VisitItem وسجل السعر الحالي تقريباً في النطاق 704–731.
- wa_backend/models.py: InventoryStockPolicy تقريباً عند 1148.
- wa_backend/models.py: InventoryBalance تقريباً عند 1170، وهو SSOT.
- wa_backend/services.py: قفل الموقع advisory guard تقريباً عند 714.
- wa_backend/services.py: تقييم عجز المندوب بسعر حي تقريباً في النطاق 2592–2635.
- wa_backend/api/driver.py: احتساب السعر والعرض والضريبة الحالي تقريباً في النطاق 1026–1066.
- wa_backend/workers/app.py: منظومة Background Jobs الحالية تعتمد Procrastinate/PostgreSQL.
- VisitUpdateRequest.request_id موجود في العقود الحالية.
- OperationIdempotency وخدمة begin/complete موجودة في services.py ويجب توسيعها، لا استنساخ نظام موازٍ.

**قاعدة البداية:** إذا اختلف الملف الفعلي عن هذا الوصف، يتوقف Patch المعني قبل الكتابة ويُحدّث التحليل والخطة أولاً.

---

## 3. القرارات الثابتة

### 3.1 تهيئة المستودعات

- GET /warehouse/locations عملية قراءة خالصة وتعيد قائمة فارغة [] للشركة التي لم تنشئ مواقع.
- يحذف إنشاء WH-MAIN الضمني من GET ومن إنشاء المنتجات.
- إنشاء المنتج لا يتطلب وجود مستودع.
- أي عملية تشغيلية تتطلب مستودعاً ولا تجده تعيد HTTP 409 مع code ثابت:

        {
          "detail": {
            "code": "WAREHOUSE_SETUP_REQUIRED",
            "message": "Warehouse setup is required before this operation.",
            "context": {}
          }
        }

- لا يوجد معنى خاص لـWH-MAIN في Runtime. إذا اختارت شركة هذا الكود فهو كود عادي.
- لا تنشأ جميع المنتجات في جميع المستودعات، ولا تنشأ سياسات وهمية عند إنشاء منتج أو مستودع.
- يمكن للواجهة حفظ preferred location كتفضيل UX فقط. لا يستخدمه الـBackend كسلطة لحركة مخزون.

### 3.2 موقع النقل الداخلي TRANSIT

- TRANSIT-SYS موقع نظام داخلي من نوع IN_TRANSIT.
- يُنشأ خلال Tenant Provisioning أو بواسطة internal ensure idempotent داخل أمر POST يحتاجه.
- لا يجوز إنشاؤه من GET.
- يحمل system_role = TRANSIT وis_system_managed = true.
- يوجد قيد يضمن موقع TRANSIT واحداً للشركة.
- يكون مخفياً من قوائم التشغيل العادية، وغير قابل للتعديل أو التعطيل أو الإسناد لمستخدم.
- يتعرف النظام إليه بواسطة system_role وcompany_id، وليس الاسم أو الكود.
- لا ينشأ موقع SCRAP تلقائياً. مواقع الحجر أو الإتلاف يحددها العميل صراحة ضمن إعدادات معتمدة.

### 3.3 ProductLocation

- ProductLocation سجل ربط sparse بين Variant وموقع.
- لا يخزن رصيداً ولا Reserved ولا سعر بيع.
- المفتاح المنطقي الفريد:
  - company_id
  - location_id
  - product_variant_id
- ينشأ صراحة من الإدارة، أو تلقائياً داخل نفس معاملة أول Inbound ناجح للمستودع المختار؛ لا ينشأ لجميع المستودعات مسبقاً، ولا يتجاوز أي ربط موجود أو operational flags معطلة.
- غياب ProductLocation يعني أن المنتج غير مهيأ للموقع، وليس أن الرصيد صفر.
- InventoryStockPolicy كيان منفصل واختياري ولا ينشأ تلقائياً مع ProductLocation.

---

## 4. نموذج البيانات المستهدف

كل الجداول التابعة للمستأجر تحمل company_id NOT NULL، وتخضع لقواعد العزل في القسم 14.

### 4.1 Company وBranch وLocation

#### InventoryLocation

حقول أساسية:

- id
- company_id
- branch_id nullable وفق نوع الموقع
- code
- name
- location_type
- operational_status
- timezone
- system_role nullable
- is_system_managed
- version
- created_at / updated_at

قيود:

- Unique(company_id, code).
- Partial Unique(company_id, system_role) حيث system_role غير فارغ.
- system_role = TRANSIT يفرض is_system_managed = true ونوع IN_TRANSIT.
- Composite foreign keys تضمن أن branch_id تابع لنفس company_id.
- المواقع النظامية لا تعدل من واجهات Tenant Admin العامة.

#### TenantOperationalPolicy

حقول أساسية:

- id
- company_id
- policy_code
- schema_version
- revision
- effective_from / effective_to
- validated_payload JSONB
- status
- approved_by / approved_at
- created_by / created_at

القرار:

- JSONB يخزن قيماً ضمن Schema معروف فقط.
- أسماء السياسات ثابتة في الكود.
- لا يسمح بكود أو Script أو Expression ينفذه المستخدم.
- Business invariants تبقى Hardcoded ومركزية.
- Domain service يقرأ نسخة السياسة مرة واحدة لكل Business Command.
- Cache key هو company_id + policy_code + revision.

### 4.2 Product وVariant وUOM

#### Product

يمثل العائلة التجارية أو Master Product:

- id
- company_id
- code
- name
- description
- brand/category references
- lifecycle metadata
- audit metadata

#### ProductVariant

يمثل SKU قابل التعامل:

- id
- company_id
- product_id
- sku
- gtin nullable
- name
- base_uom_id
- quantity_scale
- quantity_step
- lot_control_mode
- expiry_control_mode
- lifecycle_status
- operational_hold
- lifecycle_revision
- published_at
- retired_at
- archived_at
- version
- audit metadata

يحذف من المخطط النظيف:

- price_per_carton
- price_per_pack
- أي سعر بيع حي داخل ProductVariant
- is_active بوصفه الممثل الوحيد لدورة الحياة
- is_uom_locked

قيود:

- Unique(company_id, sku).
- Composite FK إلى Product يضمن نفس company_id.
- quantity_scale ضمن مجال ثابت وآمن.
- quantity_step أكبر من صفر وقابل للتمثيل ضمن quantity_scale.
- الحقول البنيوية تصبح immutable بعد الانتقال من DRAFT إلى ACTIVE.
- أي عبوة أو Conversion جديد بعد النشر ينشأ Variant/SKU جديداً.

#### ProductUomConversion

- id
- company_id
- product_variant_id
- from_uom_id
- to_uom_id
- numerator
- denominator
- quantity_scale
- valid metadata

قيود:

- numerator > 0 وdenominator > 0.
- التحويل Exact Rational أو Decimal مضبوط، بلا FLOAT.
- Unique(company_id, product_variant_id, from_uom_id, to_uom_id).
- immutable بعد نشر Variant.

#### ProductBarcode

- id
- company_id
- product_variant_id
- uom_id
- barcode
- barcode_type
- is_primary
- valid_from / valid_to
- is_active
- created_at

قيود:

- لا يحذف Barcode مستخدم؛ تنتهي صلاحيته زمنياً.
- Unique tenant-safe للباركود الفعال.
- أكثر من Barcode يمكن أن يعود لنفس Variant/UOM.
- GS1 parser يعالج Application Identifiers:
  - 01 GTIN
  - 10 Lot
  - 17 Expiry
  - 21 Serial
- جدول Barcode يحدد Variant/UOM، بينما Lot/Expiry/Serial بيانات ديناميكية يستخرجها Parser ولا تخزن كهوية ثابتة للمنتج.

### 4.3 ProductLocation وInventoryStockPolicy

#### ProductLocation

- id
- company_id
- location_id
- product_variant_id
- operational_flags
- created_by / created_at

قيد فريد:

- Unique(company_id, location_id, product_variant_id).

#### InventoryStockPolicy

- id
- company_id
- product_location_id
- minimum_quantity
- target_quantity
- reorder_quantity nullable
- minimum_remaining_shelf_life_days
- monitoring_enabled
- policy_revision_id
- version
- audit metadata

قيود قاعدة البيانات:

- minimum_quantity >= 0.
- target_quantity >= minimum_quantity.
- reorder_quantity فارغ أو أكبر من صفر.
- minimum_remaining_shelf_life_days >= 0.
- Unique(company_id, product_location_id).
- كل الكميات NUMERIC(20,6) وتخضع لخطوة ودقة UOM.

دلالة الغياب:

- عدم وجود Policy = NOT_CONFIGURED / monitoring off.
- لا يفسر الغياب على أنه minimum = 0.

### 4.4 الرصيد والدفعات

#### InventoryBalance

يبقى SSOT ويحمل على الأقل:

- company_id
- location_id
- product_variant_id
- batch_id nullable حسب lot control
- stock_status
- on_hand_quantity
- reserved_quantity
- version

قيود:

- Unique بحسب مفتاح الرصيد الكامل للشركة والموقع والمنتج والدفعة والحالة.
- on_hand_quantity >= 0.
- reserved_quantity >= 0.
- reserved_quantity <= on_hand_quantity وفق دلالة المحرك الحالية وبعد مراجعة العقود الفعلية.
- كل تعديل يمر عبر Unified Inventory Movement Engine.

#### ProductBatch

- id
- company_id
- product_variant_id
- lot_number
- manufacture_date nullable
- expiry_date nullable
- disposition
- disposition_reason
- disposition_revision
- audit metadata

Batch disposition:

- RELEASED
- QUARANTINED
- BLOCKED
- RECALLED

الانتهاء:

- Expired حالة مشتقة حتمياً من expiry_date + Business Timezone.
- لا يعتمد منع البيع أو التحميل على Job يومي.
- Worker يمكن أن ينشئ Alerts أو Tasks، لكنه ليس سلطة صحة وقت الحركة.
- الرصيد المنتهي يبقى ظاهراً مادياً في Live Stock والجرد والدفتر.
- يجب فصل Batch disposition عن portion-level stock_status داخل InventoryBalance.

Stock status المستهدف يحتاج على الأقل:

- AVAILABLE
- QUARANTINED
- BLOCKED
- RECALLED
- DAMAGED
- DISPOSAL_PENDING عند الحاجة المعتمدة

لا تضاف قيمة قبل تحديد عمليات الدخول والخروج المسموحة لها في Capability Matrix والمحرك الموحد.

### 4.5 التسعير

هذا النموذج Effective-dated Temporal Pricing، وليس Event Sourcing.

#### PriceBook

- id
- company_id
- code
- name
- currency_code
- status
- channel/branch applicability metadata
- version

#### PricePublication

نسخة نشر immutable:

- id
- company_id
- price_book_id
- revision
- status: DRAFT / PENDING_APPROVAL / PUBLISHED / SUPERSEDED / CANCELLED
- effective_at
- created_by
- approved_by
- published_at
- request_id

#### PriceBookEntry

- id
- company_id
- price_book_id
- publication_id
- product_variant_id
- uom_id
- amount
- effectivity TSTZRANGE
- priority
- metadata

قيود:

- amount >= 0.
- العملة من PriceBook.
- PostgreSQL btree_gist extension ضمن Alembic baseline.
- Exclusion constraint منشور فقط يمنع تقاطع TSTZRANGE [) لنفس:
  - company_id
  - price_book_id
  - product_variant_id
  - uom_id
- Price amount وبدء الصلاحية لسجل منشور immutable.
- إغلاق المجال القديم ونشر الجديد يتمان في Transaction واحدة.
- يوجد فحص Application ودود قبل قيد قاعدة البيانات، لكن القيد هو الحارس النهائي.

#### PriceBookAssignment

- id
- company_id
- price_book_id
- scope_type
- scope_id
- priority
- effective range
- revision

ترتيب الحسم الثابت:

1. Customer contract.
2. Customer group.
3. Branch / channel.
4. Company default.

أي تعادل غير محسوم في الأولوية يرفض ولا يختار عشوائياً.

#### RouteCommercialContext

ينشأ ويقفل Atomically عند Launch للمسار:

- id
- company_id
- dispatch_route_id
- pricing_locked_at
- price_publication_revision
- assignment_revision
- offer_ruleset_version
- tax_ruleset_version
- transaction_currency_code
- functional_currency_code
- rounding_policy_version
- tenant_policy_revision
- created_at

قرارات:

- المسار PLANNED يمكن تعديل سياقه قبل Launch.
- عند Launch يقفل السياق ويورث WorkSession المرجع نفسه.
- لا تنسخ آلاف الأسعار لكل Route.
- حل الأسعار Bulk في Query واحدة للسياق المقفل.
- Variant يحمّل لاحقاً داخل المسار يحل بالسياق والتوقيت المقفلين نفسيهما.
- لا Repricing صامت لمسار مفتوح.
- أي Reprice اختياري مستقبلاً يسمح فقط قبل أول Sale، Online، وبصلاحية وسبب وAudit وبعد موافقة Workflow مستقلة.

### 4.6 العروض والضرائب

#### OfferDefinition / OfferVersion

محرك Typed وVersioned. الأنواع المسموحة أولياً:

- Percentage discount.
- Fixed discount.
- Buy X get Y.
- Free goods.
- Quantity tiers.
- Bundle.
- Caps.
- Priority.
- Exclusive / stackable.
- Product/customer/branch/channel/date scopes.

قواعد:

- لا JavaScript ولا SQL ولا Python ولا Expressions قابلة للتنفيذ من المستخدم.
- validated_payload وفق Schema لكل offer_type.
- كل Rule type جديد يحتاج Handler في الكود واختبارات Domain ضرورية.
- النسخة المنشورة immutable.

#### TaxRuleSet / TaxComponent

- قواعد Versioned وEffective-dated.
- تدعم أكثر من مكون ضريبي.
- تحل وفق Company/Jurisdiction/Product/Customer/Document context.
- النسخة المستخدمة تقفل ضمن RouteCommercialContext أو المستند المباشر.

ترتيب الحساب الثابت:

1. Base price.
2. Price adjustments.
3. Discounts and free goods.
4. Taxable base.
5. Tax components.
6. Currency rounding.
7. Header reconciliation.

#### SalesLine financial evidence

يحفظ سطر البيع:

- selected_price_entry_id
- price_publication_revision
- unit_price
- gross_amount
- discount_amount
- taxable_amount
- tax_amount
- net_amount
- transaction_currency_code
- functional_currency_code
- exchange_rate
- functional_amount
- offer_snapshot JSONB
- tax_snapshot JSONB
- commercial_context_id

وتوجد جداول typed:

#### SalesLineAdjustment

- company_id
- sales_line_id
- rule_type
- rule_id
- rule_version
- sequence
- basis_amount
- adjustment_amount
- metadata snapshot

#### SalesLineTaxComponent

- company_id
- sales_line_id
- tax_rule_id
- tax_rule_version
- tax_name
- rate
- taxable_amount
- tax_amount
- jurisdiction metadata

الـJSON snapshots دليل Versioned، لكنها ليست المصدر الوحيد لتقارير CFO.

### 4.7 الكميات والأموال

ممنوع:

- FLOAT
- REAL
- DOUBLE PRECISION

الكميات:

- NUMERIC(20,6) في قاعدة البيانات.
- Python Decimal في Backend.
- quantity_scale وquantity_step يفرضان قابلية القياس.
- القطع والكرتون غير القابل للتجزئة تكون scale = 0.
- الواجهة تحول UOM للعرض، والـBackend يتحقق من Quantization.

الأموال:

- Amounts: NUMERIC(20,6) داخلياً.
- Exchange rate: NUMERIC(24,12).
- التقريب النهائي وفق Currency precision وRounding policy.
- invariant: مجموع Header = مجموع Lines + rounding adjustment.

### 4.8 العملة والتقييم المالي

كل مستند مالي يحفظ:

- transaction_currency_code
- transaction_amount
- functional_currency_code
- exchange_rate
- exchange_rate_type
- exchange_rate_source
- exchange_rate_date
- functional_amount

العملة الثالثة:

- Reporting currency اختيارية لاحقاً ولا تفرض الآن على كل جدول.
- تغيير Functional currency حدث محاسبي Effective-dated مع انتقال فترة، وليس تعديل Setting يمحو معنى التاريخ.

لا توضع كل أعمدة الأموال في InventoryMovement. الدفاتر المالية تشير إلى الحركة أو المستند.

#### Inventory Valuation Subledger

منفصل عن Quantity Ledger:

- Cost layer.
- Inbound actual unit cost.
- Currency/rate.
- Cost consumption.
- Valuation posting.
- Reference to InventoryMovement/Document.

طرق التكلفة المدعومة:

- Moving weighted average.
- FIFO.
- Specific batch cost.
- Standard cost مؤجل.

تختار الشركة الطريقة قبل أول Inbound مقيّم. تغييرها بعد ذلك يخضع لفترة محاسبية وإجراء معتمد.

FEFO قاعدة تشغيل للصلاحية ولا تساوي طريقة FIFO المحاسبية تلقائياً.

#### Driver shortage and penalty

القيد المخزني عند العجز يكون بسعر التكلفة:

- Debit Inventory Shrinkage Expense.
- Credit Inventory Asset.

ذمة المندوب/الغرامة منفصلة:

- Debit Driver Receivable.
- Credit Loss Recovery أو Other Income وفق Chart/Jurisdiction/Approval.

الفرق لا يرحّل تلقائياً إلى حساب عام واحد.

لا يتغير Workflow اعتماد الغرامة الحالي حتى تتم مناقشة مرحلته صراحة. مؤقتاً، إذا بقيت دلالة السعر الحالية، يستخدم RouteCommercialContext المقفل ولا يستخدم سعر السوق اللحظي.

### 4.9 Audit وOutbox

#### DomainAuditEvent

- id BIGINT
- external_id UUID
- company_id
- event_type
- entity_type
- entity_id
- actor_user_id
- actor_role/context
- reason_code
- reason_text
- request_id
- before_snapshot JSONB
- after_snapshot JSONB
- schema_version
- occurred_at

#### TransactionalOutbox

- id BIGINT
- company_id
- event_type
- aggregate_type/id
- payload JSONB
- schema_version
- idempotency_key
- status
- attempts
- available_at
- processed_at

يكتب الحدث في Transaction نفسها مع التغيير، ثم يرسله Worker بمحاولات Idempotent.

أحداث إلزامية أولية:

- ProductPublished / Retired / Archived / Restored.
- ProductSalesHoldPlaced / Released.
- ProductRecallIssued.
- PricePublicationPublished.
- OfferVersionPublished.
- BatchExpiryAlert.
- StockPolicyBulkPublished.

---

## 5. Finite State Machines

### 5.1 Product Variant Lifecycle FSM

الحالات:

- DRAFT
- ACTIVE
- RETIRING
- ARCHIVED

الانتقالات المسموحة:

| من | إلى | الأمر | ملاحظات |
|---|---|---|---|
| DRAFT | ACTIVE | publish | يتحقق من الهوية وUOM وLot/Expiry وباقي الحقول الإلزامية |
| DRAFT | Deleted | delete-draft | فقط إذا لم يُنشر ولم يُستخدم ولا توجد References |
| ACTIVE | RETIRING | retire | سبب وصلاحية وexpected_version |
| RETIRING | ACTIVE | restore | يعيد التشغيل بعد Preflight وسياسات وتسعير صالح |
| RETIRING | ARCHIVED | archive | بعد فحص موانع نهائي Transactional |
| ARCHIVED | ACTIVE | restore | Endpoint صريح؛ تبقى الحقول البنيوية immutable ويتطلب Readiness preflight |

ممنوع:

- DRAFT إلى ARCHIVED مباشرة.
- ACTIVE إلى ARCHIVED مباشرة.
- تعديل status بواسطة PATCH عام.
- Hard delete بعد Publish.
- تعديل بنية UOM بعد DRAFT.

كل انتقال:

- Endpoint Command مستقل.
- request_id.
- reason.
- expected_version.
- Permission صريح.
- Audit event.
- Domain service مركزي.
- Shared/Exclusive advisory guards حسب العملية.

### 5.2 Operational Hold FSM

الحالات:

- NONE
- SALES_HOLD
- RECALL

الانتقالات:

| من | إلى | الأمر |
|---|---|---|
| NONE | SALES_HOLD | place-sales-hold |
| SALES_HOLD | NONE | release-sales-hold |
| NONE | RECALL | recall |
| SALES_HOLD | RECALL | recall |
| RECALL | NONE أو SALES_HOLD | close-recall بعد Completion وApproval |

RECALL أعلى أولوية من Lifecycle policy. لا يحذف المنتج ولا رصيده من أي شاشة تشغيلية.

### 5.3 Price Publication FSM

| من | إلى | الشرط |
|---|---|---|
| DRAFT | PENDING_APPROVAL | Validation كامل |
| DRAFT | PUBLISHED | إذا Maker/Checker غير مفعل |
| PENDING_APPROVAL | PUBLISHED | موافقة مستخدم مخول |
| PENDING_APPROVAL | CANCELLED | رفض/إلغاء مع سبب |
| PUBLISHED | SUPERSEDED | نشر Revision لاحقة |

إذا Separation of Duties مفعلة، لا يوافق المنشئ على نسخته.

### 5.4 Offer Version FSM

يتبع نفس نمط DRAFT / PENDING_APPROVAL / PUBLISHED / SUPERSEDED / CANCELLED، مع Validation خاص بنوع العرض.

---

## 6. Capability Matrix

### 6.1 Product lifecycle

| العملية | DRAFT | ACTIVE | RETIRING | ARCHIVED |
|---|---:|---:|---:|---:|
| تعديل الحقول البنيوية | نعم | لا | لا | لا |
| تعديل الاسم/الوصف/الصورة | نعم | نعم | نعم | لا، إلا Metadata مصرح |
| إنشاء Inbound جديد | لا | نعم | لا افتراضياً | لا |
| إكمال Inbound بدأ سابقاً | لا | نعم | نعم | فقط مسار إنهاء/عكس معتمد |
| Replenishment جديد | لا | نعم | لا | لا |
| Route load جديد | لا | نعم | حسب Tenant policy؛ الافتراضي لا | لا |
| بيع على Route مفتوح | لا | نعم | حسب Tenant policy؛ الافتراضي نعم | لا |
| Warehouse balancing | لا | نعم | مقيد بغرض واتجاه وصلاحية | لا |
| Route return | لا | نعم | نعم | فقط لإغلاق مستند سابق |
| Stocktake | لا | نعم | نعم | تاريخ فقط؛ أو إنهاء جرد سابق |
| Reconciliation | لا | نعم | نعم | إنهاء References سابقة فقط |
| Return / disposal | لا | نعم | نعم | إنهاء مستند سابق فقط |
| Archive | لا | لا مباشرة | بعد صفر موانع | لا |
| History/reporting | نعم | نعم | نعم | نعم |

### 6.2 Hold overlay

| العملية | NONE | SALES_HOLD | RECALL |
|---|---:|---:|---:|
| New sale | حسب Lifecycle | ممنوع | ممنوع |
| New route load | حسب Lifecycle | ممنوع | ممنوع |
| New replenishment | حسب Lifecycle | ممنوع | ممنوع |
| Safe receipt of in-flight document | نعم | نعم إلى حالة غير قابلة للبيع | نعم إلى RECALLED/QUARANTINED |
| Count/reconcile | نعم | نعم | نعم |
| Route return | نعم | نعم | نعم |
| Recall return | غير مطبق | غير مطبق | نعم |
| Quarantine/disposal | حسب السبب | نعم | نعم |
| Offline command | عادي | Refresh policy | Force recall command |

### 6.3 Batch disposition and derived expiry

| الحالة | Sell/Load | Transfer عادي | Count | Return/Disposition |
|---|---:|---:|---:|---:|
| RELEASED وغير منتهي | نعم | نعم | نعم | نعم حسب الغرض |
| QUARANTINED | لا | لا | نعم | Test/Release/Return/Disposal |
| BLOCKED | لا | لا | نعم | Return/Disposal |
| RECALLED | لا | لا | نعم | Recall return/Quarantine/Disposal |
| Expired derived | لا | لا | نعم | Return vendor/Quarantine/Disposal |
| أقل من minimum shelf life | Policy: منع أو تحذير | Policy | نعم | نعم |

كل Allocation/Load/Sale يعيد تقييم Expiry وMinimum Shelf Life لحظياً على السيرفر.

### 6.4 Transfer purpose and direction

الأغراض:

- REPLENISHMENT
- ROUTE_LOAD
- ROUTE_RETURN
- WAREHOUSE_BALANCING
- RETURN_TO_VENDOR
- QUARANTINE
- RECALL_RETURN
- DISPOSAL

القرار يتم من:

- transfer_purpose
- source/destination location types and capabilities
- product lifecycle
- operational hold
- batch disposition/expiry
- tenant policy revision
- user permission and location access

لا يستخدم اسم Main Warehouse.

Defaults في RETIRING:

- Van إلى disposition/return location: مسموح.
- Warehouse إلى Van: ممنوع افتراضياً.
- Warehouse إلى Warehouse: ممنوع افتراضياً إلا WAREHOUSE_BALANCING بصلاحية عليا وسياسة صريحة.
- Warehouse إلى Quarantine/Disposal: مسموح بالغرض الصحيح.

### 6.5 إكمال المستندات العالقة

المبدأ الملزم: المستند الذي بدأ صحيحاً يجب أن يملك طريقاً آمناً إلى حالة نهائية.

- يخزن المستند lifecycle_revision وcommercial_context وقت الإنشاء.
- إكمال المستند يفحص حالته وقت الإنشاء والحالة الحالية معاً.
- RETIRING لا يعلق المستند الجاري.
- SALES_HOLD يسمح بالاستلام الآمن ويمنع التصرف الجديد.
- RECALL يسمح بالاستلام إلى RECALLED/QUARANTINED ويمنع البيع أو التحميل.
- Reject/Cancel/Return/Reconciliation تبقى متاحة للوصول إلى Terminal state.
- لا تعاد البضاعة تلقائياً إلى مستودع مفترض.

---

## 7. الأقفال والمعاملات ومنع السباقات

### 7.1 Location guards

- الإبقاء على PostgreSQL pg_advisory_xact_lock الحالي.
- Shared guard لكل أمر ينشئ Open Reference على الموقع.
- Exclusive guard لتعطيل الموقع.
- عند وجود مصدر ووجهة، تقفل المعرفات بترتيب ثابت لتجنب Deadlock.
- لا نضيف Optimistic Lock بديلاً عن Advisory Lock لهذا السباق.
- Optimistic version يبقى مفيداً لتعارض تحرير الإعدادات.

العمليات التي يجب أن تأخذ Shared guards للمصدر والوجهة المعنيين:

- إنشاء/إرسال/قبول Transfer أو Handshake.
- Route launch وRoute load/return.
- Inbound يفتح التزاماً على الموقع.
- Stocktake lock/session.
- Reconciliation يفتح Reference.
- إنشاء أي مستند يبقى Open ويرتبط بالموقع.

تعطيل الموقع:

1. Begin transaction.
2. Exclusive advisory guard للموقع.
3. إعادة تحميل الموقع Tenant-scoped.
4. فحص جميع InventoryBalance statuses: on_hand = 0 وreserved = 0.
5. فحص Open inbound references.
6. فحص Transfer/Handshake بوصف الموقع مصدراً ووجهة.
7. فحص Routes/loads/returns المفتوحة.
8. فحص Stocktakes والLocks المفتوحة.
9. فحص Reconciliation/settlement references المفتوحة.
10. تحديث الحالة وversion وAudit داخل المعاملة.
11. Commit.

Terminal states تؤخذ من FSM الفعلي لكل مستند. لا يستخدم شرط عام من نوع status NOT IN (COMPLETED, CANCELLED). في Transfer الحالي تشمل الحالات النهائية المتوقعة POSTED وREJECTED وCANCELLED، لكن يجب قراءة Enum/Service الفعلي قبل كتابة الشرط.

### 7.2 Product lifecycle guards

- Shared product lifecycle guard لكل أمر ينشئ Reference جديداً.
- Exclusive product lifecycle guard لـarchive/recall والانتقالات التي تقفل عمليات جديدة.
- Archive preflight للعرض فقط وغير ملزم.
- Archive command يعيد فحص الموانع داخل Transaction تحت Exclusive guard.

موانع الأرشفة:

- أي on_hand أو reserved في كل statuses.
- Vehicle custody.
- Pending/in-transit/handshake/transfer.
- Open inbound.
- Active route/load plan.
- Open stocktake/lock.
- Shortage/reconciliation/settlement المفتوح.
- Active offer.
- Active price assignment/publication التي تجعل Variant قابلاً للبيع.
- Active InventoryStockPolicy/ProductLocation operational reference حسب العقد النهائي.

الفحص:

- Indexed EXISTS queries متوازية منطقياً داخل الخدمة حسب إمكان الاتصال.
- لا Materialized View كسلطة.
- لا Counters قابلة للانحراف كسلطة.
- Detailed background report اختياري كCache فقط.

### 7.3 Pricing publication

- Transaction واحدة تنشر Revision وتغلق المجالات السابقة وتثبت القيود.
- Exclusion constraint هو الحارس النهائي للتداخل.
- Route launch وPrice publish يملكان ترتيب أقفال واضحاً يمنع سياقاً نصف منشور.
- Route launch يقرأ Publication/Assignment/Offer/Tax revisions المتسقة في Snapshot واحد.

### 7.4 Inventory and financial atomicity

لكل Sale/Return/Transfer/Post/Reconciliation:

1. تحقق Tenant/permission/location.
2. Idempotency begin مع request hash.
3. تحميل Policy وCommercial context.
4. Locks المطلوبة.
5. Validation للحالة/الصلاحية/UOM.
6. Unified Inventory Movement Engine.
7. Financial document/valuation/adjustments.
8. Audit + Outbox.
9. Idempotency complete مع response snapshot.
10. Commit.

أي فشل يلغي الوحدة كلها.

---

## 8. API Contracts المستهدفة

الأسماء التالية Target contracts. قبل التنفيذ تقارن بالمسارات الحالية لتقليل Breaking changes، لكن لا نحافظ على عقد قديم يخرق الدستور.

### 8.1 Error envelope

كل Business error قابل للمعالجة في الواجهة:

        {
          "detail": {
            "code": "STABLE_MACHINE_CODE",
            "message": "Localized or displayable message",
            "context": {
              "entity_id": 123,
              "blockers": []
            }
          }
        }

أكواد أساسية:

- WAREHOUSE_SETUP_REQUIRED
- LOCATION_ACCESS_DENIED
- LOCATION_DEACTIVATION_BLOCKED
- PRODUCT_LOCATION_REQUIRED
- PRODUCT_NOT_OPERATIONAL
- PRODUCT_LIFECYCLE_CONFLICT
- PRODUCT_ARCHIVE_BLOCKED
- PRODUCT_SALES_HOLD
- PRODUCT_RECALLED
- BATCH_NOT_RELEASED
- BATCH_EXPIRED
- SHELF_LIFE_POLICY_BLOCKED
- PRICE_NOT_RESOLVED
- PRICE_EFFECTIVITY_CONFLICT
- COMMERCIAL_CONTEXT_LOCKED
- IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD
- OFFLINE_LEASE_EXPIRED
- RECALL_ACK_REQUIRED
- QUANTITY_STEP_VIOLATION

### 8.2 Warehouse

- GET /warehouse/locations: قراءة خالصة، Filters/Pagination، وقد يعيد [].
- GET /warehouse/setup-status: يوضح Readiness بلا Side effects.
- POST /warehouse/locations: إنشاء موقع صريح.
- PATCH /warehouse/locations/{id}: Metadata مسموحة فقط.
- POST /warehouse/locations/{id}/activate.
- POST /warehouse/locations/{id}/deactivate.

طلبات التعطيل تحمل request_id وreason وexpected_version.

### 8.3 Catalog

- GET /catalog/products.
- POST /catalog/products لإنشاء Draft.
- GET /catalog/products/{id}.
- PATCH /catalog/products/{id} للحقول المسموحة حسب الحالة.
- POST /catalog/variants.
- PATCH /catalog/variants/{id}.
- POST /catalog/variants/{id}/publish.
- POST /catalog/variants/{id}/retire.
- POST /catalog/variants/{id}/restore.
- GET /catalog/variants/{id}/archive-preflight.
- POST /catalog/variants/{id}/archive.
- POST /catalog/variants/{id}/sales-hold.
- POST /catalog/variants/{id}/release-sales-hold.
- POST /catalog/variants/{id}/recall.
- POST /catalog/variants/{id}/close-recall.
- CRUD Version-aware للـProductBarcode.

لا يوجد PATCH مباشر لـlifecycle_status أوoperational_hold.

### 8.4 ProductLocation

- GET /warehouse/product-locations مع location/product filters وKeyset pagination.
- POST /warehouse/product-locations.
- PATCH للـoperational flags المسموحة.
- DELETE فقط إذا لم توجد Policy/Balance/References، وإلا تعطيل/فصل منظم.

### 8.5 Pricing

- GET/POST /pricing/books.
- GET/POST /pricing/books/{id}/publications.
- POST /pricing/publications/{id}/submit.
- POST /pricing/publications/{id}/approve.
- POST /pricing/publications/{id}/publish.
- POST /pricing/publications/{id}/cancel.
- CRUD draft entries.
- GET/POST /pricing/assignments.
- POST /pricing/resolve-preview لشرح السعر المختار وأولوية Assignment.

جميع التعديلات تحمل expected_version، والنشر request_id وreason.

### 8.6 Offers and taxes

- CRUD OfferDefinition/Draft Version.
- Validate/submit/approve/publish/cancel command endpoints.
- Preview endpoint يعرض التطبيق على Basket تجريبي بلا كتابة.
- Tax rulesets لها Versioned management ونشر منفصل.

### 8.7 Stock policy

- GET/POST/PATCH InventoryStockPolicy.
- POST /stock-policies/bulk-preview.
- POST /stock-policies/bulk-apply.
- GET /stock-policies/jobs/{job_id}.
- POST /stock-policies/jobs/{job_id}/cancel عندما تكون الحالة قابلة للإلغاء.
- GET /stock-policies/replenishment مع Keyset pagination.

Bulk behavior:

- حجم صغير ينفذ Sync.
- فوق Threshold مضبوط يعيد 202 Accepted وjob_id.
- التنفيذ عبر Procrastinate/PostgreSQL الحالي.
- لا Celery/Redis stack جديد.

### 8.8 Route commercial context

Route launch response يتضمن:

- commercial_context_id
- pricing_locked_at
- price/assignment/offer/tax policy revisions
- currency/rounding metadata
- offline lease metadata عند إنشاء جلسة المندوب

DispatchRoute.source_location_id يبقى المصدر الصريح الذي تُسحب منه الحمولة.

### 8.9 Driver/Offline

العقود المستهدفة للمرحلة اللاحقة:

- POST /driver/offline/lease.
- GET /driver/sync/manifest.
- GET /driver/recall-commands?after_cursor=...
- POST /driver/recall-commands/{id}/ack.
- Sale sync الحالي يوسع ليقبل request_id وevent/device sequence وoccurred_at وVariant/UOM quantities.

العميل لا يحدد السعر كسلطة. إذا أرسله لعرض محلي، يتجاهله القرار المالي ويقارنه النظام فقط لأغراض كشف الاختلاف.

---

## 9. Offline وIdempotency وRecall

### 9.1 Sale sync envelope

الموبايل يرسل:

- request_id UUID ثابت للمحاولة المنطقية.
- authenticated company/driver/device/session context عبر Token، لا company_id موثوقاً من Body.
- route_id / work_session_id.
- client_document_id UUID.
- occurred_at.
- device_sequence.
- variant_id.
- uom_id.
- quantity.
- returns/samples payload وفق العقود المعتمدة.

الـBackend:

- يثبت أن Route/Session للسائق والشركة والجهاز.
- يحل السعر والعرض والضريبة من RouteCommercialContext.
- يتحقق من Lease وRecall cursor.
- ينفذ Inventory وFinancial writes Atomically.
- يعيد نفس الاستجابة عند Retry بنفس request_id/hash.
- يرفض استخدام request_id نفسه مع Payload مختلف.

### 9.2 Offline lease

Lease موقعة ومربوطة بـ:

- company_id
- driver_id
- device_id
- route_id/session_id
- issued_at
- expires_at
- tenant_policy_revision
- recall_cursor

القواعد:

- يوجد Platform maximum لا يستطيع Tenant تجاوزه.
- Tenant يستطيع اختيار مدة أقصر ضمن الحدود.
- القيمة الرقمية الافتراضية لا تثبت عشوائياً الآن؛ تحسم قبل Flutter وفق Risk profile.
- انتهاء Lease يمنع New Sales فقط.
- يبقى Sync وReturns وReconciliation وRecall actions متاحاً.

### 9.3 Recall command

- اسم المجال Recall Command، وليس Poison Pill.
- Versioned وIdempotent وله Scope: Variant أوBatch.
- يجب أن يقر الجهاز بالاستلام.
- التطبيق يحظر العنصر محلياً ولا يحذف Product أوStock.
- ينقل العرض المحلي إلى Recalled/Held bucket.
- إذا حدث بيع فعلي Offline بعد إصدار Recall وقبل استلام الجهاز، لا يحذف الحدث:
  - يسجل POST_RECALL_EXCEPTION.
  - يحافظ على حقيقة المخزون والمال.
  - يمنع الاعتماد التلقائي ويحول للمراجعة.

---

## 10. Stock Policy وReplenishment

### 10.1 Templates

- يمكن وجود Templates على Company أوBranch.
- Template لا ينشئ Records عند Product/Warehouse creation.
- المستخدم يطلب Preview ثم Apply صريحاً.
- Preview Paginated ويعرض Create/Update/Skip/Conflict.

### 10.2 النشر الجماعي

- Stage rows تحت Policy revision غير منشورة.
- الإدخال Set-based أو Batches مناسبة.
- Publish pointer واحد Atomically يمنع Half-visible policies.
- Progress وretry وcancel وaudit.
- Job idempotency بواسطة request_id.

### 10.3 Replenishment query

Query واحدة أو CTE:

1. تجمع InventoryBalance حسب company/location/variant وحالات الرصيد.
2. تحسب eligible_on_hand وeligible_reserved.
3. تستبعد Expired/Blocked/Quarantined/Recalled من Available.
4. تربط ProductLocation وInventoryStockPolicy.
5. تعرض فقط available_quantity < minimum_quantity.
6. تحسب suggested_quantity حتى target أو reorder rule.
7. تستخدم Keyset pagination.

Indexes:

- InventoryBalance(company_id, location_id, product_variant_id, stock_status).
- ProductLocation(company_id, location_id, product_variant_id).
- InventoryStockPolicy(company_id, product_location_id).
- Partial/indexes إضافية تثبتها EXPLAIN الفعلية.

لا Ledger scan، ولا Loop ORM، ولا N+1، ولا إنشاء Transfer تلقائياً. التقرير يقترح فقط، والإنسان ينشئ المستند.

---

## 11. الصلاحيات

Permissions مبدئية:

- warehouse.location.view
- warehouse.location.manage
- warehouse.location.deactivate
- warehouse.product_location.view
- warehouse.product_location.manage
- catalog.view
- catalog.manage
- catalog.product.publish
- catalog.product.retire
- catalog.product.archive
- catalog.product.hold
- catalog.product.recall
- pricing.view
- pricing.manage
- pricing.approve
- offers.view
- offers.manage
- offers.approve
- tax_rules.view
- tax_rules.manage
- tax_rules.approve
- stock_policy.view
- stock_policy.manage
- stock_policy.apply_bulk
- costing.view
- costing.manage
- costing.post
- recall.review_exception

القواعد:

- Admin الحالي يبقى Company administrator كامل الصلاحيات وفق قرار Stage 4D.
- مستخدم المستودع المحدود يدخل Dashboard بصلاحياته من دون اشتراط Driver.is_admin.
- UserLocationAccess يفرض الوصول إلى المواقع.
- Branch membership لا يمنح Location authority تلقائياً.
- إرسال/إلغاء Transfer يحتاج صلاحية المصدر.
- استلام/رفض Transfer يحتاج صلاحية الوجهة.
- Dispatch وVEHICLE_RECON يحتاجان صلاحية موقع السيارة الصريح.
- Product master permissions منفصلة عن warehouse operation permissions.
- Platform admins لا يمرون عبر Tenant data path العادي.

---

## 12. RLS والعزل بين الشركات

لكل جدول Tenant جديد:

1. company_id NOT NULL.
2. ENABLE ROW LEVEL SECURITY.
3. FORCE ROW LEVEL SECURITY.
4. Policies SELECT/INSERT/UPDATE/DELETE مرتبطة بـcurrent tenant context.
5. WITH CHECK يمنع إدخال company_id مختلف.
6. Composite FK يتضمن company_id عندما يشير إلى Parent tenant-scoped.
7. Unique constraints تبدأ بـcompany_id حيث يلزم.
8. كل Lookup في الخدمة يفلتر company_id حتى مع وجود RLS.
9. لا يعتمد العزل على الاسم أوCode أوبيانات العميل المرسلة.
10. Jobs تفتح tenant_session صريحاً لكل شركة.
11. App role ليس Superuser ولاBYPASSRLS.
12. Migration/Admin role منفصل ويستخدم فقط للتشغيل الإداري.

اختبارات العزل الإلزامية:

- Tenant A لا يرى/يعدل Product أوVariant أوBarcode لدى B.
- لا يمكن ربط Location من A بBranch أوProduct من B.
- لا يمكن PriceBookAssignment عابر للشركات.
- لا يمكن Transfer/Route/Stocktake بSource/Destination من شركة أخرى.
- لا يمكن Background Job معالجة company_id خاطئ.
- Composite FKs ترفض Cross-tenant references حتى عند تشغيل Migration role.
- تحديث RLS catalog audit ليشمل كل جدول جديد.

مرجع Gate الحالي:

- TENANT_TABLES_CHECKED=41
- RLS_CATALOG_GAPS=NONE
- APP_SUPERUSER=False
- APP_BYPASSRLS=False
- ROLE_GRANTS_VISIBLE_WITHOUT_TENANT=0
- STAGE4D_RLS_CATALOG_AUDIT=PASS

يزداد عدد الجداول المفحوصة بعد هذه الخطة، ويبقى GAPS=NONE.

---

## 13. Jobs

يستخدم المشروع Procrastinate/PostgreSQL الموجود.

Jobs المخططة:

- StockPolicyBulkApplyJob.
- BatchExpiryProjectionJob.
- NearExpiryAlertJob.
- RecallNotificationRelayJob.
- OutboxRelayJob.
- OptionalArchiveBlockerDetailJob.
- Price/Offer publication notification jobs.

قواعد Jobs:

- ليست سلطة صحة لحظية للبيع أو التحميل.
- Idempotency key إلزامي.
- company_id إلزامي.
- tenant_session لكل Job execution.
- Progress/checkpoint للمهام الكبيرة.
- Retry آمن.
- Dead-letter/error state ظاهر للإدارة.
- لا تعديل مباشر لـInventoryBalance؛ أي حركة تمر بالمحرك الموحد.
- لا Job شامل لجميع الشركات داخل Transaction واحدة.

---

## 14. Dashboard contracts

هذه المرحلة Functional/API أولاً، والتصميم البصري الشامل يبقى لاحقاً.

### 14.1 Warehouse setup

- قائمة المواقع تعرض Empty State حقيقياً عند [].
- العمليات التي تستقبل WAREHOUSE_SETUP_REQUIRED تفتح CTA لإعداد مستودع أو توجه لصفحة المواقع وفق صلاحية المستخدم.
- لا تنشئ الواجهة WH-MAIN تلقائياً.
- لا تختار أول مستودع لحركة.

### 14.2 Catalog

- فصل Product family عنVariants.
- Draft editor.
- Publish/Retire/Restore/Archive commands واضحة.
- Archive preflight يعرض Blockers وروابطها.
- Hold/Recall إجراءات ذات سبب وصلاحية.
- Lifecycle/Hold/Batch badges منفصلة.
- المنتجات المتقاعدة أوالموقوفة تبقى ظاهرة في Live Stock وLedger وStocktake.
- Barcode/UOM management.
- ProductLocation assignment مستقل.

### 14.3 Pricing

- Price Books list.
- Draft Publication editor.
- Effective ranges مع كشف overlap قبل الإرسال.
- Assignments/precedence viewer.
- Resolve Preview يشرح سبب اختيار السعر.
- Maker/Checker UI عند تفعيل السياسة.
- Route context يظهر Locked revision/time ولا يعرض Live price كأنه سعر المسار.

### 14.4 Offers/taxes

- Typed forms حسب offer_type.
- Preview حسابي.
- Version history وPublish workflow.
- Invoice/settlement details تعرض typed adjustments/taxes والسجلات Snapshot.

### 14.5 Stock policies

- ProductLocation-scoped CRUD.
- Template preview/apply.
- Async job progress.
- Replenishment report Paginated.
- لا Auto-transfer.

### 14.6 Permissions and errors

- Buttons تختفي أوتعطل لتحسين UX، لكن Backend يبقى السلطة.
- Stable error codes تترجم إلى رسائل وإجراءات واضحة.
- 409 لا يعرض كخطأ تقني غامض.
- Location scope يظهر للمستخدم ولا يسمح بتجاوز ID يدوياً.

---

## 15. Flutter/Offline contracts

تنفيذ Flutter مؤجل، لكن Backend contract يثبت في هذه المرحلة:

- Local catalog manifest Versioned.
- RouteCommercialContext محفوظ محلياً وموقع/متحقق منه.
- Local price display مشتق من Manifest المقفل.
- كل Offline command يحمل client UUID وتسلسل.
- Queue لا تحذف الحدث قبل Ack نهائي.
- Retry يكرر UUID نفسه.
- Lease countdown مبني على Server timestamp مع معالجة Clock skew.
- Recall cursor وCommands محفوظان محلياً.
- Recall يحظر البيع ولا يحذف الرصيد.
- Expired Lease يمنع New Sale ويسمح Sync/Return/Reconciliation.
- Conflict/exception states ظاهرة وقابلة للمراجعة.
- لا يملك Flutter حق تحديد company_id أوprice أوtax كسلطة.

---

## 16. ترتيب التنفيذ الملزم

### Stage 0 — Contract Freeze and Empty Database Verification

- [x] قراءة الملفات الفعلية والEnums والعقود الحالية.
- [x] حفظ Schema inventory.
- [x] التأكد من أن قاعدة التطوير المستهدفة فارغة فعلياً قبل أي Reset.
- [x] تثبيت أسماء الجداول والEnums النهائية.
- [x] توثيق Breaking API changes.

Gate:

- [x] FOUNDATION_CONTRACT_FREEZE_GATE=PASS

**Stage status:** COMPLETE — 2026-09-11.

#### Stage 0 frozen baseline

##### قاعدة التطوير

- Target database: velotrack_db.
- PostgreSQL: 16.9.
- Migration role المستخدم في التدقيق: postgres.
- تم التأكد من الهدف بالاسم داخل المعاملة قبل المسح.
- حذف مالك المشروع بيانات Tenant التجريبية صراحةً من النطاق، ونُفذ TRUNCATE للشركات مع CASCADE داخل Transaction واحدة.
- نتيجة ما بعد المسح: companies = 0.
- عدد الجداول الحالية التي تحمل company_id: 41.
- مجموع صفوف جداول Tenant بعد المسح: 0.
- RLS catalog gaps الحالية: 0.
- Trigger حماية SystemAuditLog append-only عاد Enabled بعد المعاملة.
- لا يوجد جدول alembic_version حالياً، بما يطابق أن Clean Baseline مؤجل إلى Stage 11.
- btree_gist غير مثبت حالياً؛ يضاف في Baseline قبل قيد منع تداخل الأسعار.
- لم تُحذف بيانات الجداول السيادية غير التابعة لشركة مثل PlatformAdmin وUOM وCountries.

##### الاعتماديات المثبتة في Backend contract

- FastAPI 0.111.0.
- SQLAlchemy Async 2.0.40.
- asyncpg 0.29.0.
- Pydantic 2.7.1.
- pydantic-settings 2.2.1.
- Procrastinate 3.9.0.
- psycopg 3.3.5 لأعمال Migration/Admin.
- Alembic يستخدم DATABASE_URL_MIGRATION أولاً ثم DATABASE_URL للتوافق المحلي فقط.
- الـvenv المحلي الحالي يشير إلى Python 3.12 غير موجود على الجهاز. لم يُصلح ضمن Stage 0 لأنه قيد بيئي لا يغيّر العقود؛ يجب إعادة بنائه قبل أول Gate يحتاج Python imports/tests.

##### Schema inventory الحالي

الجداول السيادية الحالية:

- platform_admins
- uom
- countries
- governorates
- permissions
- login_attempts
- token_blacklist

الجداول الأساسية للمستأجر:

- companies
- branches
- drivers
- roles
- role_permissions
- user_roles
- user_location_access
- system_settings
- zones
- shops
- vehicles

جداول المنتج والتجارة الحالية:

- products
- product_variants
- uom_conversions
- offer_rules

جداول Dispatch/Visits الحالية:

- work_sessions
- session_inventory_snapshots
- dispatch_routes
- dispatch_load_plan_lines
- visits
- visit_items
- visit_returns
- shortage_requests
- work_break_logs

جداول المخزون الحالية:

- product_batches
- inventory_locations
- inventory_stock_policies
- inventory_balances
- inventory_movements
- inventory_movement_impacts
- inventory_damage_events
- inventory_transfer_headers
- inventory_transfer_lines
- stocktake_sessions
- stocktake_lines
- stocktake_count_attempts
- stocktake_count_attempt_lines
- inventory_locks
- override_reasons

جداول التشغيل والتدقيق الحالية:

- operation_idempotency
- system_audit_logs
- import_logs
- refresh_tokens

الحقائق الحالية المجمدة:

- ProductVariant يحتوي price_per_carton وprice_per_pack وis_active، وسيستبدلها النموذج المعتمد في Stages 2 و5.
- كل Quantity مخزنية حالياً Integer، وسيتم تحويلها وفق قرار NUMERIC/Decimal في Stage 2.
- InventoryBalance هو SSOT ومفتاحه الحالي company/location/variant/batch/stock_status.
- Inventory stock statuses الحالية هي AVAILABLE وDAMAGED.
- Inventory movement kinds الحالية هي PHYSICAL وRESERVATION وSTATUS_CHANGE.
- Inventory location types الحالية هي WAREHOUSE وVEHICLE وIN_TRANSIT وSCRAP.
- Transfer workflow types الحالية هي DIRECT وHANDSHAKE وTRANSIT.
- Transfer statuses الحالية هي DRAFT وPENDING وIN_TRANSIT وACCEPTED وREJECTED وPOSTED وCANCELLED.
- Stocktake types الحالية هي FULL_COUNT وCYCLE_COUNT وVEHICLE_RECON.
- Stocktake statuses الحالية هي DRAFT وCOUNTING وPENDING_REVIEW وRECOUNT_REQUIRED وAPPROVED وPOSTED وCANCELLED.
- DispatchRoute statuses الحالية هي active وwaiting وpostponed وclosed، وتبقى دون تغيير في هذه الخطة.
- DispatchRoute.source_location_id موجود وصريح.
- OperationIdempotency الحالي Tenant-scoped بمفتاح company/operation/request_id ويحفظ Request hash وResponse replay.
- ProductBatch الحالي Tenant-scoped وBatch-aware مع production_date وexpiry_date.
- InventoryLocation الحالي يدعم branch_id وvehicle_id وقيود Tenant composite.
- InventoryStockPolicy الحالي فريد حسب company/location/variant ويفرض minimum >= 0 وtarget فارغاً أو >= minimum.

##### أسماء الجداول الجديدة أوالمستبدلة

الأسماء التالية هي الأسماء الفيزيائية المعتمدة للمخطط النظيف:

| Model | Table |
|---|---|
| ProductUomConversion | product_uom_conversions |
| ProductBarcode | product_barcodes |
| ProductLocation | product_locations |
| TenantOperationalPolicy | tenant_operational_policies |
| PriceBook | price_books |
| PricePublication | price_publications |
| PriceBookEntry | price_book_entries |
| PriceBookAssignment | price_book_assignments |
| RouteCommercialContext | route_commercial_contexts |
| OfferDefinition | offer_definitions |
| OfferVersion | offer_versions |
| TaxRuleSet | tax_rule_sets |
| TaxRuleSetVersion | tax_rule_set_versions |
| SalesLineAdjustment | sales_line_adjustments |
| SalesLineTaxComponent | sales_line_tax_components |
| InventoryCostLayer | inventory_cost_layers |
| InventoryValuationEntry | inventory_valuation_entries |
| DriverPenaltyEntry | driver_penalty_entries |
| InventoryStockPolicyTemplate | inventory_stock_policy_templates |
| InventoryStockPolicyRevision | inventory_stock_policy_revisions |
| InventoryStockPolicyStageRow | inventory_stock_policy_stage_rows |
| DomainAuditEvent | domain_audit_events |
| TransactionalOutbox | transactional_outbox |
| OfflineLease | offline_leases |
| RecallCommand | recall_commands |
| RecallCommandAcknowledgement | recall_command_acknowledgements |

قرارات التسمية:

- يستبدل uom_conversions بـproduct_uom_conversions في Clean schema لأن التحويل تابع لـVariant.
- يستبدل offer_rules تدريجياً بـoffer_definitions وoffer_versions.
- يبقى system_audit_logs لسجل الأمن والإدارة، ويضاف domain_audit_events لأحداث المجال. لا يدمجان بلا Migration design صريح.
- sales_line_adjustments وsales_line_tax_components يرتبطان في المخطط الحالي بـvisit_items مع Composite tenant guard.
- الجداول عالية الحجم Append-only تستخدم BIGINT identity داخلياً وUUID خارجياً للمستندات/الأحداث Offline.

##### Enum contract النهائي

تنفذ القيم كـPython StrEnum مركزي مع VARCHAR وnamed database CHECK constraints، لتجنب تكرار Strings داخل الخدمات مع إبقاء Migration الإضافات واضحة. لا تستخدم قيم يرسلها العميل من دون Validation.

| Enum | القيم المعتمدة |
|---|---|
| InventoryLocationType | WAREHOUSE, VEHICLE, IN_TRANSIT, SCRAP |
| InventoryLocationSystemRole | TRANSIT |
| ProductLifecycleStatus | DRAFT, ACTIVE, RETIRING, ARCHIVED |
| ProductOperationalHold | NONE, SALES_HOLD, RECALL |
| BatchDisposition | RELEASED, QUARANTINED, BLOCKED, RECALLED |
| InventoryStockStatus | AVAILABLE, QUARANTINED, BLOCKED, RECALLED, DAMAGED |
| InventoryMovementKind | PHYSICAL, RESERVATION, STATUS_CHANGE |
| InventoryReservationAction | RESERVE, RELEASE |
| TransferWorkflowType | DIRECT, HANDSHAKE, TRANSIT |
| TransferStatus | DRAFT, PENDING, IN_TRANSIT, ACCEPTED, REJECTED, POSTED, CANCELLED |
| TransferPurpose | REPLENISHMENT, ROUTE_LOAD, ROUTE_RETURN, WAREHOUSE_BALANCING, RETURN_TO_VENDOR, QUARANTINE, RECALL_RETURN, DISPOSAL |
| StocktakeType | FULL_COUNT, CYCLE_COUNT, VEHICLE_RECON |
| StocktakeStatus | DRAFT, COUNTING, PENDING_REVIEW, RECOUNT_REQUIRED, APPROVED, POSTED, CANCELLED |
| PricePublicationStatus | DRAFT, PENDING_APPROVAL, PUBLISHED, SUPERSEDED, CANCELLED |
| OfferVersionStatus | DRAFT, PENDING_APPROVAL, PUBLISHED, SUPERSEDED, CANCELLED |
| CostMethod | MOVING_WEIGHTED_AVERAGE, FIFO, SPECIFIC_BATCH |
| PolicyRevisionStatus | DRAFT, APPLYING, PUBLISHED, CANCELLED, FAILED |
| OutboxStatus | PENDING, PROCESSING, PUBLISHED, FAILED |
| RecallCommandScope | VARIANT, BATCH |
| RecallCommandStatus | PENDING, DELIVERED, ACKNOWLEDGED, CLOSED |
| OfflineExceptionType | POST_RECALL_EXCEPTION |

DISPOSAL_PENDING ليس Stock status في الإصدار الأول؛ المستند ذو TransferPurpose = DISPOSAL يتتبع العملية، بينما الرصيد يبقى BLOCKED أوQUARANTINED أوRECALLED حتى ترحيل الإتلاف عبر Unified Engine. هذا يمنع تضخم حالات الرصيد بلا حاجة.

Enums التشغيل الحالية للـTransfer وStocktake وDispatch لا تتغير أثناء إدخال الجداول الجديدة. أي تغيير فيها يحتاج قرار Workflow منفصلاً.

##### API wire conventions المجمدة

- IDs الداخلية أعداد صحيحة موجبة، وrequest_id/client_document_id UUID.
- الكميات والأموال الجديدة تُرسل وتُعاد كسلاسل Decimal canonical عند إمكان وجود كسور، لمنع تحويل JavaScript إلىBinary float.
- التواريخ الزمنية ISO-8601 مع Offset؛ التخزين TIMESTAMPTZ UTC.
- Business date وExpiry يعتمدان Company/Location timezone.
- القوائم الكبيرة تستخدم Keyset cursor، limit افتراضي 50 وأقصى 200 ما لم يتطلب Contract موثق قيمة أخرى.
- Mutating commands تستخدم request_id، وتستخدم expected_version للكيانات القابلة للتحرير المتزامن.
- Business errors تستخدم detail.code الثابت وdetail.message وdetail.context.
- company_id لا يؤخذ من Body كسلطة.

##### Breaking API changes المعتمدة

| العقد الحالي | العقد المستهدف | نوع الكسر وتوقيت التنفيذ |
|---|---|---|
| GET /warehouse/locations ينشئ WH-MAIN ويعيد Array | قراءة خالصة Cursor page وتعيد items فارغة | Stage 1؛ تحديث مستهلكي Dashboard في المرحلة نفسها |
| POST /warehouse/product_variants ينشئ Active Variant مع سعر وسياسات لكل المستودعات | POST /catalog/products وPOST /catalog/variants ينشئان Draft بلا سعر أوPolicy | Stage 2/3؛ إزالة العقد القديم بعد انتقال Dashboard |
| AddProductVariantRequest يحمل price_per_carton وprice_per_pack وmin_threshold_packs | التسعير عبر Price Publication والسياسة عبر ProductLocation/StockPolicy | Stages 2 و5 و8 |
| Warehouse quantities حقول Integer باسم packs | Decimal base quantity + UOM identifiers | Stage 2؛ تحديث Backend contracts أولاً ثم Dashboard |
| InventoryBalance statuses AVAILABLE/DAMAGED فقط | خمس حالات الرصيد المعتمدة | Stage 4 مع تحديث المحرك والجرد والتقارير معاً |
| TRANSIT-SYS يكتشف بالكود ويُنشأ داخل Dispatch | system_role=TRANSIT وis_system_managed=true | Stage 1 |
| Location state request بلا expected_version وreason اختياري | request_id + expected_version + reason حسب الأمر | Stage 1 |
| Live ProductVariant prices تستخدم في Driver sale/shortage | RouteCommercialContext + immutable Price entry/version | Stages 5 و7 |
| OfferRule mutable/current | OfferDefinition + immutable OfferVersion/Publication | Stage 6 |
| VisitItem snapshots المالية محدودة | Typed line adjustments/taxes + immutable totals/snapshots | Stage 6 |
| InventoryStockPolicy مرتبط مباشرة location/variant وبInteger | ProductLocation-scoped Decimal policy وRevision | Stage 8 |
| Driver sync يرسل الكمية ضمن العقد الحالي فقط | UUID/device sequence/occurred_at/locked commercial context/lease | Backend contract في Stages 5–7، Flutter في Stage 10 |

سياسة الانتقال:

- لا يحافظ النظام النهائي على Legacy aliases أوDual-write لأن قاعدة البيانات فارغة.
- كل Breaking change ينفذ Backend وDashboard المستهلك له داخل Stage المعني أوCheckpoint متصل يمنع عقداً نصف محدث.
- لا يحذف Endpoint قديم قبل البحث الفعلي عن كل مستهلكيه.
- Flutter لم يبدأ، لذلك يثبت العقد النهائي قبل تنفيذه ولا يبنى Compatibility layer غير مستخدم.

### Stage 1 — Warehouse Provisioning and Location Race Repair ✅

- [x] إزالة Side effects من GET /warehouse/locations.
- [x] إزالة إنشاء WH-MAIN وسياسات المخزون من Product create.
- [x] WAREHOUSE_SETUP_REQUIRED.
- [x] TRANSIT system role/provisioning.
- [x] تغطية Shared guards للمصدر والوجهة.
- [x] إكمال Deactivation blockers والـstable errors.
- [x] Dashboard empty/setup handling.

Gate:

- [x] WAREHOUSE_PROVISIONING_GATE=PASS

### Stage 2 — Quantity, UOM, Product and Variant Foundation

- [x] تحويل كميات مخزون المستودعات والمحرك الموحد إلى NUMERIC(20,6)/Decimal exact.
- [x] فصل Product العائلة عن ProductVariant/SKU بعقد Tenant-scoped.
- [x] تأسيس UOM والتحويلات الدقيقة، وقصر تعديل البنية على DRAFT.
- [x] تأسيس Barcodes one-to-many وGS1 parsing.
- [x] إزالة السعر من عقود Catalog وDashboard الجديدة.
- [x] تحديث عقود Unified Inventory Movement Engine وInbound/Live Stock/Ledger/Transfers/Stocktake.

حدود الانتقال المعتمدة أثناء التنفيذ:

- تبقى حقول `price_per_carton` و`price_per_pack` القديمة nullable داخل `ProductVariant` مؤقتاً فقط حتى يستبدل Stage 5 مستهلكي التسعير الحي في Driver وVEHICLE_RECON ثم يحذفها من المخطط في نفس الـcheckpoint؛ لا تعرضها عقود Catalog الجديدة ولا تعتمد عليها واجهات Inventory الجديدة.
- تبقى عقود الكراتين/الحبات التجارية القديمة في Visit/Offer/Driver إلى مراحل التسعير والعروض والتقييم 5–7، لأن تحويل شكلها قبل تثبيت Commercial Context يغيّر عقد البيع القائم جزئياً. يمنع أي `int()` أو Float في مسارات مخزون المستودعات والمحرك الموحد المنجزة هنا.

Gate:

- [x] PRODUCT_FOUNDATION_GATE=PASS

### Stage 3 — ProductLocation, Lifecycle, Holds and Archive ✅

- [x] ProductLocation sparse.
- [x] FSM commands.
- [x] Capability evaluator.
- [x] Archive preflight/final locking.
- [x] Permissions/Audit/Outbox.
- [x] Dashboard lifecycle surfaces.

Gate:

- [x] PRODUCT_LIFECYCLE_GATE=PASS

**Stage status:** COMPLETE — 2026-09-12.

### Stage 4 — Batch Disposition, Expiry and Transfer Purposes ✅
- [x] Batch disposition.
- [x] Portion stock statuses.
- [x] Synchronous expiry/shelf-life validation.
- [x] Jobs للتنبيه فقط.
- [x] Transfer purposes/directional constraints.
- [x] In-flight completion rules.

Gate:

- [x] `BATCH_DISPOSITION_GATE=PASS` (Automated)

**Stage status:** COMPLETE — 2026-09-12.

### Stage 5 — Temporal Pricing and Route Commercial Context

- [x]PriceBook/Publication/Entry/Assignment.
- [x] إزالة حقول السعر القديمة من ProductVariant بعد تحويل آخر مستهلك حي لها.
- [x] btree_gist exclusion.
- [x] Publish workflow.
- [x] Deterministic precedence.
- [x] Route launch lock.
- [x] Driver sync price authority.
- [x] Dashboard pricing.

Gate:

- [x] COMMERCIAL_PRICING_GATE=PASS

### Stage 6 — Offers, Taxes and Immutable Sales Evidence

- [x] Typed offer engine.
- [x] Tax rule versions.
- [x] Calculation order.
- [x] SalesLineAdjustment/TaxComponent.
- [x] Financial snapshots.
- [x] Return reversal from original lines.

Gate:

- [x] OFFER_TAX_SNAPSHOT_GATE=PASS

### Stage 7 — Valuation, Penalty and Currency

- Cost layers/subledger.
- Tenant costing method.
- Shortage posting at cost.
- Separate driver receivable/penalty.
- Dual currency.
- Accounting period controls.

لا يغير Penalty approval workflow قبل مناقشته واعتماده.

Gate:

- VALUATION_PENALTY_GATE=PASS

### Stage 8 — InventoryStockPolicy

- Policy CRUD.
- Templates.
- Bulk preview/apply via Procrastinate.
- Atomic publish.
- Set-based replenishment report.
- Dashboard policy/report.

Gate:

- STOCK_POLICY_GATE=PASS

### Stage 9 — Dashboard Functional Alignment

- إغلاق كل Backend contract في Dashboard.
- إزالة العقود القديمة ذات السعر الحي أوالمستودع الواحد.
- Pagination/Error handling/permissions.
- لا Visual redesign شامل ضمن هذه المرحلة.

Gate:

- DASHBOARD_COMMERCIAL_ALIGNMENT_GATE=PASS

### Stage 10 — Flutter/Offline Implementation

- تنفيذ العقود المقفلة.
- Lease/recall/idempotency/local manifests.
- Offline sales/returns/reconciliation.

Gate:

- FLUTTER_OFFLINE_CONTRACT_GATE=PASS

### Stage 11 — Legacy Removal and Clean Baseline

- البحث عن بقايا single-warehouse/live-price/is_active legacy.
- إزالة الحقول والمسارات القديمة بعد إثبات عدم استخدامها.
- إعادة بناء قاعدة التطوير الفارغة.
- Alembic clean baseline واحد بعد استقرار Backend schema.
- لا create_all في Production.
- Regression/E2E.
- Dashboard freeze.

Gate:

- LEGACY_REMOVAL_CLEAN_BASELINE_GATE=PASS

### Stage 12 — Architecture Foundation / Modulith Hardening

الهدف ليس Microservices ولا Big-Bang Rewrite. الهدف نقل النظام تدريجياً من Monolith ذي فصل Domains متنامٍ إلى **Strict Modular Monolith (Modulith)** وفق `ARCHITECTURE.md`، مع الحفاظ على سرعة وبساطة التشغيل داخل Monolith وفرض حدود بمستوى Microservices.

#### 12.1 Dependency and ownership map

- استخراج Dependency graph فعلي لكل Backend domain/module.
- إعلان Owner واضح لكل جدول/Business authority.
- تحديد Public contracts لكل Module.
- توثيق Legacy cross-module dependencies بدلاً من إخفائها.

#### 12.2 Strict boundaries

- منع أي Module جديد من الكتابة مباشرة في جداول يملكها Module آخر.
- منع imports إلى internals الخاصة بموديول آخر.
- التواصل بين Modules عبر Application/Public contracts أوEvents معتمدة.
- منع Circular domain dependencies.
- إضافة Architecture CI gate يفشل عند خرق dependency rules.
- أي Exception مؤقتة تكون مسجلة ومحددة بتاريخ إزالة.

#### 12.3 Progressive extraction from globals

- تفكيك `models.py` تدريجياً حسب Ownership بدون إعادة كتابة شاملة.
- تفكيك `services.py` والـAPI files الكبيرة تدريجياً إلى Application/Domain services مملوكة للموديولات.
- عدم نقل كود لمجرد التنظيم؛ كل نقل يجب أن يحسن Authority/Boundary ويملك Regression coverage.
- لا تغيير Business Workflow ضمن هذه المرحلة إلا بموافقة منفصلة.

#### 12.4 Module migrations and upgrades

- كل Schema change يحمل Module ownership واضح.
- يبقى Alembic revision graph واحداً ومضبوطاً ما لم يثبت سبب قوي لتغييره.
- العقود العامة/API/Event contracts تكون Versioned عندما تتطلب Backward compatibility.
- إضافة Upgrade tests من حالات/إصدارات مدعومة إلى Head للموديولات الحرجة.
- Destructive migrations تتطلب Expand/Contract أوخطة Rollout صريحة.

#### 12.5 Isolation architecture — Priority #1

- Tenant/company isolation يبقى Fail-closed ومطلقاً.
- RLS + Composite tenant FKs + Backend authorization + negative tests تبقى Defense in Depth.
- كل Job/Event/Cache/WebSocket/Import/Export يحمل Tenant context صريحاً.
- Location/Warehouse scope يفرض في Backend على المصدر والوجهة.
- Staff/Driver/Vehicle/Route scopes تبنى كPolicy مرنة للشركة: Company / Branch / Location / Route / Vehicle / Team حسب الحاجة، بدون implicit access.
- Platform admin يبقى Security boundary منفصل عن Tenant identities.

#### 12.6 Events and asynchronous boundaries

- In-process synchronous calls هي Default عندما تكون أفضل للاتساق والأداء.
- Domain/Application events تستخدم فقط عندما تحقق Decoupling حقيقي.
- Side effects غير المتزامنة الحرجة تستخدم Transactional Outbox أوPattern مكافئ.
- Handlers Tenant-safe وIdempotent وObservable وbounded.

#### 12.7 Microservice extraction rule

لا يفصل أي Module إلى Microservice إلا بوجود دليل على واحد أوأكثر من:

- Scaling مستقل فعلي.
- Failure isolation مختلف جوهرياً.
- Security/Compliance boundary صلب.
- Runtime/Workload مختلف.
- Deployment/team ownership مستقل يبرر التكلفة.

قبل الفصل يجب أن يكون الموديول نظيف الحدود داخل الـModulith أولاً.

Gate:

- ARCHITECTURE_MODULITH_GATE=PASS

Final gate:

- INVENTORY_COMMERCIAL_FOUNDATION_FINAL_GATE=PASS

---

## 17. Gates والاختبارات

### 17.1 قواعد التحقق

- لا اختبار بعد كل تعديل صغير.
- نستخدم Targeted tests فقط عندما يحمي الاختبار Invariant أوRace أوConstraint مهم.
- Full checks عند Checkpoint منطقي أوإغلاق Stage.
- لا ننشئ اختبارات تطابق التنفيذ بلا قيمة.
- أي ملفات مؤقتة تنشأ خارج Source tree أوتحذف فور انتهاء الحاجة بعد التحقق الصريح من مسارها.
- لا يحذف أي Project file أوDirectory.

### 17.2 بوابة Backend

- Python syntax/import.
- Targeted domain tests.
- API contract tests للـstable codes.
- Database constraints.
- Tenant/RLS catalog audit.
- Transaction/idempotency tests.
- Unified Inventory Movement invariants.

### 17.3 بوابة Frontend

عند إغلاق Stage واجهية:

- ESLint.
- npx tsc --noEmit -p tsconfig.app.json.
- Vite build.
- React tests الضرورية فقط للعقود الحرجة.

### 17.4 Concurrency gates

- Warehouse deactivation مقابل إنشاء Handshake.
- Warehouse deactivation مقابل Transfer/Route launch/Stocktake.
- Product archive مقابل Inbound/Transfer/Route open reference.
- Price publish مقابل Route launch.
- Price overlap concurrent publish.
- Recall/expiry مقابل Sale/Load.
- Retry للفاتورة نفسها بعد Commit وقبل استلام Response.
- request_id نفسه مع Payload مختلف.

### 17.5 Performance gates

تستخدم بيانات تمثيلية عند Checkpoint النهائي للمرحلة فقط:

- EXPLAIN ANALYZE لفحص Archive blockers.
- EXPLAIN ANALYZE لحل أسعار Route Bulk.
- EXPLAIN ANALYZE لتقرير Replenishment.
- إثبات عدم N+1.
- إثبات Keyset pagination على القوائم الكبيرة.
- Bulk write عبر INSERT ... SELECT أوBatches مدروسة.
- عدم وجود Unpaginated endpoints في Hot paths.

---

## 18. معايير القبول لكل محور

### Warehouse

- [ ] GET locations لا يكتب إلى DB.
- [ ] إنشاء Product لا ينشئ Location أوPolicy.
- [ ] لا يوجد First warehouse fallback.
- [ ] TRANSIT يعرف بدور نظامي Tenant-scoped.
- [ ] Deactivation يفشل بأكواد واضحة عند أي Reference أوStock.
- [ ] Race tests تمر.

### Product/UOM

- [x] لا أسعار في عقود Catalog الجديدة؛ الحذف الفيزيائي لحقول الانتقال القديمة ملزم في Stage 5.
- [x] DRAFT وحده يسمح بتعديل البنية.
- [x] كل Quantity في مخزون المستودعات والمحرك الموحد يستخدم Decimal/NUMERIC بلاFloat.
- [x] UOM step/scale مفروضان.
- [x] Barcodes one-to-many وGS1 parsing.
- [ ] تحويل عقود Quantity التجارية القديمة وحذف carton/pack compatibility fields ضمن Stages 5–7.

### Lifecycle/Holds

- [x] لا direct status patch.
- [x] FSM مركزي.
- [x] Capability Matrix مركزي ومستخدم من الأوامر.
- [x] Archive preflight يعرض Blockers.
- [x] Final archive يعيد الفحص تحت Lock.
- [x] الرصيد لا يختفي بسبب Lifecycle/Hold.

### Batch/Expiry

- [ ] Synchronous expiry check في Allocation/Load/Sale.
- [ ] Minimum shelf life policy.
- [ ] Expired stock ظاهر في InventoryBalance/Live Stock.
- [ ] Jobs ليست سلطة correctness.
- [ ] Recall/Quarantine/Blocked statuses لها عمليات واضحة.

### Pricing

- [ ] Temporal Price Books منشورة immutable.
- [ ] DB تمنع overlap.
- [ ] Precedence deterministic.
- [ ] Route context يقفل عند Launch.
- [ ] لا Live repricing لمسار مفتوح.
- [ ] Driver sync لا يثق بسعر العميل.

### Offers/Tax

- [ ] Typed schemas بلا executable rules.
- [ ] Versioned publication.
- [ ] Calculation order ثابت.
- [ ] Typed line adjustments/tax components.
- [ ] Returns تعكس Original line.
- [ ] Posted documents immutable.

### Cost/Currency

- [ ] Quantity ledger منفصل عن Valuation.
- [ ] Cost method يثبت قبل أول Costed inbound.
- [ ] Shortage يخرج المخزون بالتكلفة.
- [ ] Driver penalty ledger منفصل.
- [ ] Dual currency fields كاملة.
- [ ] Functional currency change ليس تعديل Setting بسيط.

### Stock policy

- [ ] Sparse ProductLocation/Policy.
- [ ] DB checks وUnique tenant-safe.
- [ ] Template preview قبل Apply.
- [ ] Large apply يعيد 202/job_id.
- [ ] Atomic publish.
- [ ] Replenishment Set-based ولا ينشئ Transfer.

### Security

- [ ] company_id NOT NULL في كل Tenant table.
- [ ] RLS ENABLE + FORCE.
- [ ] Composite tenant FKs.
- [ ] Jobs تستخدم tenant_session.
- [ ] App role بلاSuperuser/BYPASSRLS.
- [ ] Cross-tenant negative tests تمر.
- [ ] Location scope مفروض في Backend.

### Dashboard/Flutter

- [ ] Dashboard يعالج Empty warehouse وstable errors.
- [ ] كل Contract جديد له Surface إدارية مطلوبة.
- [ ] لا بقايا اختيار أول مستودع.
- [ ] لا بقايا Live price في عمليات Route.
- [ ] Offline contract Versioned وIdempotent.
- [ ] Recall لا يحذف Local stock.
- [ ] Lease expiry لا يمنع الإغلاق الآمن للمستندات.

---

## 19. سجل القرارات المرفوضة وأسبابها

| الاقتراح | القرار | السبب |
|---|---|---|
| GET ينشئ WH-MAIN | مرفوض | Side effect، تخطي صلاحيات، وخلط Master/Operational data |
| اسم WH-MAIN أوTRANSIT-SYS كسلطة | مرفوض | غير آمن وغير قابل للتخصيص؛ نستخدم system_role Tenant-scoped |
| إنشاء Policy لكل Product×Warehouse | مرفوض | تضخم وبيانات وهمية وكتابة غير ضرورية |
| is_uom_locked Boolean | مرفوض | حالة مشتقة قابلة للانحراف؛ Lifecycle transition يقفل البنية |
| Archive بواسطة Worker كسلطة نهائية | مرفوض | سباق زمني؛ القرار النهائي Synchronous تحت Lock |
| Materialized view/counter كحارس Archive | مرفوض | قابل للقدم أوالانحراف؛ يستخدم فقط للعرض إن لزم |
| Cron هو الذي يمنع بيع المنتهي | مرفوض | Job قد يتأخر؛ التحقق Synchronous في كل أمر |
| Expired = DAMAGED دائماً | مرفوض | الانتهاء والتلف مفهومان مختلفان |
| locked_price_list_id فقط | مرفوض | القائمة قد تتغير وتوجد Assignments متعددة؛ نستخدم Commercial Context revisions |
| تسمية التسعير Event Sourcing | مرفوض | النموذج Effective-dated temporal history |
| نسخ كل أسعار Route | مرفوض | تضخم؛ Context immutable + bulk resolve |
| JSONB executable policy engine | مرفوض | خطر أمني وصعوبة اختبار؛ Typed strategies |
| INTEGER لكل الكميات عالمياً | مرفوض | لا يدعم الوزن/الحجم؛ NUMERIC exact مع scale/step |
| FLOAT للكميات أوالمال | مرفوض | أخطاء تقريب |
| JSON snapshots وحدها للتقارير | مرفوض | نحتاج typed immutable child rows |
| Celery/Redis جديد للBulk | مرفوض | Procrastinate/PostgreSQL موجود ويكفي |
| Auto-transfer من تقرير النقص | مرفوض | تغيير تشغيل خطر؛ التقرير يقترح فقط |
| حذف Local recalled product | مرفوض | يخفي الحقيقة؛ نحظر ونبقي العهدة ظاهرة |
| رفض Offline post-recall sale وحذفه | مرفوض | يفقد الحقيقة؛ يسجل Exception للمراجعة |
| Branch يمنح كل Locations ضمنياً | مرفوض | Location authority صريحة |

---

## 20. نقاط مؤجلة عمداً وليست منسية

1. **مدة Offline Lease الرقمية:** تحسم قبل Flutter عبر Risk profile، مع Platform maximum وTenant shorter override.
2. **طريقة تكلفة كل Tenant:** يختارها Onboarding قبل أول Costed inbound من FIFO أوMoving Average أوSpecific Batch.
3. **Standard Cost:** مرحلة مستقبلية.
4. **Reporting currency الثالثة:** تضاف عندما تتطلبها تقارير Multi-currency؛ النموذج الحالي يحفظ Transaction + Functional.
5. **إجراء Reprice لمسار قبل أول Sale:** لا ينفذ إلا بعد مناقشة Workflow منفصلة.
6. **Penalty approval workflow:** لا يتغير ضمن هذه الخطة بلا موافقة منفصلة.
7. **Visual/UX redesign الشامل:** بعد الإغلاق الوظيفي، Regression/E2E وDashboard Freeze.
8. **SCRAP location provisioning:** لا إنشاء تلقائياً؛ يحدد Tenant مواقع Disposition صراحة.

---

## 21. طريقة تنفيذ كل Stage

1. قراءة الملفات الفعلية وAGENTS.md و.rules وقاعدة حماية Workflow.
2. تحديد CURRENT / GAP / TARGET / PATCH PLAN للمرحلة.
3. التأكد من أن التعديل لا يغير Workflow غير معتمد.
4. التعديلات الصغيرة تستخدم ابحث واستبدل حرفياً بعد تطابق Anchor.
5. التعديلات الكبيرة متعددة الملفات تستخدم Python patch ذاتي التحقق:
   - يفحص الـbaseline والـanchors.
   - يفشل قبل الكتابة عند الاختلاف.
   - يكتب Atomically قدر الإمكان.
   - يتحقق من كل ملف بعد الكتابة.
6. لا Blind patch.
7. لا ترك TODO يخفي Data integrity أوSecurity gap.
8. تشغيل تحقق Targeted أثناء التطوير عند الضرورة فقط.
9. تشغيل Gate كامل مرة واحدة عند إغلاق Stage.
10. مراجعة Git diff والتأكد من عدم وجود ملفات مؤقتة أوتعديلات غير مقصودة.
11. Checkpoint/Push منطقي، لا Push لكل تعديل صغير.
12. تحديث هذا الملف فقط عند قرار جديد وافق عليه المالك.

---

## 22. Definition of Done

تكتمل هذه الخطة عندما:

- تنفذ جميع Stages 0–11.
- لا يبقى أي مسار يختار مستودعاً ضمنياً.
- لا يوجد سعر حي داخل ProductVariant أوبيع يعاد تسعيره خارج Commercial Context.
- كل Quantity/Stock mutation يمر بالمحرك الموحد.
- InventoryBalance يبقى SSOT.
- Lifecycle/Hold/Batch disposition منفصلة ومطبقة مركزياً.
- كل مستند مالي منشور Immutable وقابل للعكس.
- RLS وComposite FKs تمنع أي Cross-tenant leak.
- Location scopes تطبق في Backend.
- Dashboard يعكس جميع Admin contracts وظيفياً.
- Flutter contract يثبت ثم ينفذ Offline بأمان.
- Hot queries مثبتة بخطط تنفيذ مناسبة.
- جميع Stage gates وFinal gate تمر.
- ينشأ Alembic baseline نظيف بعد استقرار المخطط.
- لا تبقى حقول أوEndpoints Legacy مستخدمة.
- لا يتغير أي Business Workflow خارج القرارات الموثقة هنا.

---

## 23. قائمة منع النسيان النهائية

- [ ] Pure GETs.
- [ ] Explicit locations.
- [ ] System-managed transit identity.
- [ ] Sparse ProductLocation.
- [ ] InventoryBalance SSOT.
- [ ] Unified Inventory Movement Engine only.
- [ ] Decimal quantities and money.
- [ ] Immutable UOM after publish.
- [ ] One-to-many barcodes and GS1.
- [ ] Product lifecycle FSM.
- [ ] Operational holds.
- [ ] Batch dispositions and synchronous expiry.
- [ ] Minimum remaining shelf life.
- [ ] Transfer purposes and directional rules.
- [ ] Safe terminal path for in-flight documents.
- [ ] Archive blockers under exclusive lock.
- [ ] Temporal pricing with no overlap.
- [ ] Immutable route commercial context.
- [ ] Deterministic price precedence.
- [ ] Typed offers and tax components.
- [ ] Immutable sales line evidence and returns reversal.
- [ ] Cost valuation separate from driver penalty.
- [ ] Dual currency ledger.
- [ ] Stock policy templates/bulk/replenishment.
- [ ] Procrastinate jobs with tenant_session.
- [ ] Audit and transactional outbox.
- [ ] Request idempotency.
- [ ] Offline lease and recall acknowledgements.
- [ ] RLS ENABLE/FORCE and tenant composite FKs.
- [ ] Location-scoped permissions.
- [ ] Dashboard functional/API alignment.
- [ ] Flutter/offline implementation later.
- [ ] Performance and concurrency gates.
- [ ] Minimal meaningful tests at checkpoints.
- [ ] Strict module ownership and public contracts.
- [ ] Architecture dependency/boundary gate.
- [ ] Versioned module contracts where compatibility matters.
- [ ] Module-owned migration changes + upgrade tests for critical upgrades.
- [ ] Tenant/company isolation remains fail-closed across sync/async/cache/events/websockets.
- [ ] Flexible but explicit branch/location/route/vehicle/team scope with no implicit access.
- [ ] No premature Microservices; extraction requires evidence.
- [ ] No temporary artifacts.
- [ ] No project file or directory deletion.
- [ ] No unapproved Business Workflow change.

---

## 24. Change Control

أي تعديل على هذا المرجع يسجل أسفل هذا القسم:

| التاريخ | القسم | القرار السابق | القرار الجديد | سبب التغيير | موافقة المالك |
|---|---|---|---|---|---|
| 2026-09-11 | جميع الأقسام | لا يوجد مرجع جامع | اعتماد هذا الملف كخطة المرحلة | تثبيت القرارات ومنع النسيان | Approved |
| 2026-09-11 | Stage 0 | Baseline غير مثبت وقاعدة التطوير تحمل بيانات اختبار | تثبيت Schema/API/Enum contracts ومسح بيانات Tenant التجريبية المصرح بها | إغلاق Contract Freeze على قاعدة Tenant فارغة | Approved in conversation |
| 2026-09-12 | Stage 3 | PRODUCT_LIFECYCLE_GATE غير مغلق | اكتمال Stage 3: ProductLocation + FSM + Capability + Archive + Audit/Outbox + Dashboard lifecycle + PRODUCT_LIFECYCLE_GATE=PASS (13/13) | إغلاق gate_stage3_lifecycle.py مع مزامنة advisory lock عبر pg_locks | Approved — gate passed |
| 2026-09-12 | Stage 4 | Batch Disposition | Completed Stage 4 (Transfer Purposes, Batch Disposition, FEFO min shelf life) | Passed gate_stage4_batch_expiry.py (7/7) | Approved - gate passed |
| 2026-09-24 | Architecture | Monolith مع فصل Domains جزئي بلا دستور حدود جامع | اعتماد `ARCHITECTURE.md` والهدف Strict Modular Monolith وإضافة Stage 12 — Architecture Foundation / Modulith Hardening | تثبيت أساس توسع SaaS طويل الأمد مع عزل صارم وقابلية إضافة Modules بدون Premature Microservices | Approved in conversation |

لا يعد تنفيذ الكود موافقة ضمنية على تغيير الخطة. عند اكتشاف تعارض حقيقي بين الخطة والكود الحالي، يتوقف الجزء المتعارض ويعرض CURRENT / GAP / OPTIONS / RECOMMENDATION على مالك المشروع قبل تغيير Workflow.
