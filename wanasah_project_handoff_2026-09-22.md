# Wanasah Project Handoff — 2026-09-22

> هذا الملف مخصص لفتح محادثة جديدة ومتابعة العمل من نفس النقطة بدون فقدان أي سياق.
> المطلوب من المساعد في المحادثة الجديدة: اقرأ هذا الملف كاملًا قبل اقتراح أو تنفيذ أي تعديل.

---

# 1) هوية المشروع وسياق العمل

المشروع الرئيسي: **Wanasah / وناسة**  
Repository على GitHub:

```text
MohHamdallah1/wanasah
```

الـBackend:

```text
wa_backend
```

التقنيات الأساسية:

```text
FastAPI
SQLAlchemy Async
PostgreSQL
Alembic
React/TypeScript Dashboard
Flutter لاحقًا
```

المستخدم يريد نظام Production-grade وليس Demo، وقواعده صارمة جدًا:

- ممنوع التخمين.
- ممنوع الاختصارات الهندسية.
- ممنوع حل سريع يترك Tech Debt.
- ممنوع تعديل منطق قائم أو Workflow إلا بعد مناقشته وموافقة المستخدم.
- أي تحسين يجب أن يكون هندسيًا صحيحًا من البداية.
- لازم نمنع الأضرار الجانبية.
- لا نصلح ملف ونكسر ملف ثاني.
- لازم نفكر Cross-file وليس ملف واحد فقط.
- أي Patch لازم يكون جراحي، محدود، ومبرر.
- إذا ظهر Bug حقيقي نصلحه، لكن لا نغير Architecture أو Business Logic بلا داعٍ.
- لا نقول إن Runtime test نجح إلا إذا المستخدم نفسه شغّله وأرسل PASS.
- المستخدم يفضل نظام مراحل واضح + Gates + Benchmarks.
- المستخدم غالبًا يشغل الأوامر محليًا ويرسل النتائج.
- عند تعديل GitHub: نستخدم Branch منفصل، لا نعمل تعديلات تطويرية مباشرة على `main`.
- بعد اكتمال مرحلة واستقرارها: Merge إلى `main`، ثم مطابقة نسخة الجهاز مع `origin/main`.
- بعد ذلك نفتح Branch جديد للمرحلة التالية.
- لو Working Tree فيه ملفات معدلة أو untracked: **لا تعمل reset/clean أو تحذفها قبل فحصها والحصول على موافقة المستخدم**.

---

# 2) الخطة العامة القديمة للمشروع

خطة Backend audit/refactor الأصلية:

```text
models.py + schemas.py
→ services.py
→ warehouse.py
→ driver.py + reconciliation.py
→ dispatch.py
→ Flutter/Offline
→ حذف الكود القديم
→ Baseline Alembic
→ الاختبارات
```

لكن المستخدم قرر حاليًا:

> لا نريد تقسيم `driver.py` أو `dispatch.py` الآن.
> نريد إنجاز لوحة التحكم أولًا، ثم نعود لتقسيم الملفات لاحقًا.

هذا قرار مهم جدًا.

---

# 3) آخر مرحلة كبيرة مكتملة: تقسيم warehouse.py

كان لدينا ملف ضخم:

```text
wa_backend/api/warehouse.py
```

تم تقسيمه بالكامل إلى Package:

```text
wa_backend/api/warehouse/
├── __init__.py
├── _shared.py
├── locations.py
├── inbound.py
├── live_stock.py
├── ledger.py
├── status.py
├── inbound_adjustments.py
├── transfer_policy.py
├── transfers.py
└── stocktake.py
```

عدد ملفات Python داخل الـpackage = 11.

`main.py` بقي يحافظ على نفس Contract:

```python
from api import warehouse
app.include_router(warehouse.router, tags=["Warehouse & Inventory"])
```

وترتيب include داخل `api/warehouse/__init__.py` مقفول كما يلي:

```text
locations
inbound
live_stock
ledger
status
inbound_adjustments
transfer_policy
transfers
stocktake
```

---

# 4) Baseline تقسيم warehouse

الـStable pre-split baseline:

```text
6f437e7606210bb6328dc97da7f275ee52f5146a
```

Commit message:

```text
نسخة مستقرة قبل تقسيم ملف wearhous
```

الـold monolith baseline كان يحتوي 106 protected top-level symbols.

تم قفل التكامل بهذه الـGates:

```text
gate_warehouse_split_integrity.py
gate_warehouse_route_manifest.py
gate_warehouse_runtime_cutover.py
gate_warehouse_final_forensic.py
```

عدد Routes المقفول:

```text
45
```

---

# 5) نتائج الإغلاق النهائي لتقسيم warehouse

المستخدم شغّل آخر Gate وأرسل:

```text
WAREHOUSE_SPLIT_INTEGRITY=PASS (final package mode; protected=106)
WAREHOUSE_ROUTE_MANIFEST=PASS (baseline=45; package=45; exact_runtime_order=True; duplicates=0)
WAREHOUSE_RUNTIME_CUTOVER=PASS (package_origin=C:\Users\admin\Desktop\wanasah\wa_backend\api\warehouse\__init__.py; package_routes=45; main_routes=45; exact_runtime_order=True; duplicates=0)
WAREHOUSE_RUNTIME_LIFESPAN=PASS (FastAPI lifespan entered successfully)
WAREHOUSE_FINAL_FORENSIC=PASS (package_files=11; runtime_stale_imports=0; historical_stale_imports=1; historical_refs=3; split_gates=3)
```

النتيجة الرسمية:

```text
warehouse split = DONE 100%
Stage 8H = PASS
```

لا تعيد فتح موضوع تقسيم warehouse إلا لو ظهر Bug حقيقي جديد.

---

# 6) معنى historical_stale_imports=1

يوجد ملف Benchmark تاريخي:

```text
wa_backend/perf_reports/phase1_baseline/profile_live_stock_explain.py
```

فيه import قديم:

```python
from api.warehouse import ...
```

هذا **ليس Runtime code**.

هو Snapshot تاريخي مقصود يمثل Phase 1 baseline قبل تقسيم warehouse.

تم السماح له صراحة في:

```text
gate_warehouse_final_forensic.py
```

القرار الحالي:

- لا نعتبره Runtime Bug.
- لا نمسحه الآن.
- لا نعدل محتواه عشوائيًا لأن تعديل snapshot تاريخي يفسد قيمة الـbaseline.
- لاحقًا إذا أردنا Repository cleanup، يمكن تحويله لأثر أرشيفي أو توثيقه بوضوح، لكن ليس الآن.

---

# 7) Bug SCRAP الذي اكتُشف أثناء التقسيم

كان عندنا Bug حقيقي سابق للتقسيم:

- DISPOSAL يمكن أن يذهب إلى `SCRAP`.
- لكن `apply_live_stock_balance_impacts` كان يرفض `SCRAP`.

DB constraint يسمح:

```text
WAREHOUSE
VEHICLE
IN_TRANSIT
SCRAP
```

الإصلاح الصحيح:

```text
SCRAP = valid inventory location
لكن خارج warehouse-centric Live Stock read model
```

أي مثل `IN_TRANSIT`:

```python
if location_type in {"IN_TRANSIT", "SCRAP"}:
    continue
```

Runtime fix commit:

```text
4a729cf0d6b8fe951af319f2c8bc0820034f58ca
```

Regression gate أثبت:

```text
STAGE4_FINAL_RESULTS: 50/50 passed, 0 failed
BATCH_DISPOSITION_GATE=PASS
```

لا ترجع عن هذا الإصلاح.

---

# 8) Full Regression / Scale التي تمت

Benchmark dataset:

```text
companies: 1075
company_variants: 10000
global_variants: 120200
location_balances: 14785
location_policies: 10000
```

Scale gate النهائي:

```text
CHECKS=20
FAILURES=0
LIVE_STOCK_SCALE_GATE=PASS
```

Stress rerun:

```text
CHECKS=16
FAILURES=0
STAGE821_PROJECTOR_STRESS_GATE=PASS
```

آخر Stress كان مريحًا وليس Marginal:

```text
cross_tenant_mutation p95 ≈ 401.6ms
threshold = 900ms
throughput ≈ 208.2/s
```

لا يوجد دليل على Connection Leak.

---

# 9) Merge تقسيم warehouse إلى main

تم فتح PR:

```text
PR #9
Complete warehouse modularization
```

ثم Merge عادي للحفاظ على كل تاريخ الـcommits.

Merge commit على `main`:

```text
0d254b658b49a7ea8dc375eaa449b59f48192876
```

Commit message:

```text
Merge warehouse modularization

Complete warehouse.py modularization, regression verification, and final forensic closure.
```

GitHub `main` أصبح على:

```text
0d254b658b49a7ea8dc375eaa449b59f48192876
```

وكان merge tree مطابقًا لآخر branch tree.

---

# 10) مطابقة الجهاز مع main

المستخدم نفذ:

```powershell
git fetch origin
git switch main
git reset --hard origin/main
git status --short
git rev-parse HEAD
```

والـHEAD عنده أصبح:

```text
0d254b658b49a7ea8dc375eaa449b59f48192876
```

في وقتها بقي ملف Temporary غير tracked:

```text
wa_backend/stage821_stress_rerun.txt
```

ثم لاحقًا انتقلنا للعمل على Dashboard.

---

# 11) مهم جدًا: الحالة المحلية الحالية الآن

آخر Output من المستخدم قبل فتح هذه المحادثة الجديدة:

```text
(venv) PS C:\Users\admin\Desktop\wanasah> git status --short
 M dashboard/src/pages/inventory/inventory.css
?? dashboard/live_stock_ui_build.txt
?? dashboard/live_stock_ui_tests.txt
```

والـdiff الحالي الوحيد المعروف في CSS:

```diff
diff --git a/dashboard/src/pages/inventory/inventory.css b/dashboard/src/pages/inventory/inventory.css
index 6385a0f..f06d6e6 100644
--- a/dashboard/src/pages/inventory/inventory.css
+++ b/dashboard/src/pages/inventory/inventory.css
@@ -1212,7 +1212,7 @@
 .live-stock-search {
   position: relative;
   width: min(100%, 24rem);
-  flex: 0 1 24rem;
+  flex: 0 0 24rem;
   min-width: 12rem;
 }
```

وهناك ملفان untracked:

```text
dashboard/live_stock_ui_build.txt
dashboard/live_stock_ui_tests.txt
```

مهم جدًا:

- لا تعمل `git reset --hard`.
- لا تعمل `git clean`.
- لا تحذف هذه الملفات.
- لا تفترض أنها غير مهمة.
- أول خطوة في المحادثة الجديدة إذا سنعمل Git: افحصها واحفظ شغل المستخدم.
- لم يتم تأكيد أن Branch جديد قد تم إنشاؤه قبل توقفنا.
- آخر Branch مؤكد كان `main`.
- كان المساعد على وشك فتح Branch جديد، لكن المستخدم أوقف العمل وأرسل حالة الـWorking Tree.
- لذلك قبل أي تعديل: افحص `git branch --show-current` و`git status`.

---

# 12) مشكلة UX الحالية: Live Stock loading flicker

المستخدم لاحظ:

> عند فتح صفحة الرصيد الحي أو التنقل بين المستودعات، الصفحة تصبح فارغة للحظات وتظهر "جاري التحميل..." ثم تظهر البيانات.

تم فحص الكود، والسبب **ليس فقط سرعة API**.

في:

```text
dashboard/src/pages/inventory/MainInventory.tsx
```

يوجد Effect عند تغيير `selectedLocationId` يعمل فعليًا:

```text
setLoadingStock(...)
setStockItems([])
setStockTotal(null)
setStockMatchingTotal(null)
setStockAlertCount(null)
setStockSearch("")
setStockState("all")
setStockIndicators([])
setStockFamilyId(null)
setStockCursor(null)
setStockNextCursor(null)
setLastSync(null)
```

أي:

```text
غيّر المستودع
→ امسح البيانات فورًا
→ loading
→ انتظر الشبكة
→ اعرض البيانات الجديدة
```

لذلك المستخدم يرى blank/loading flicker.

هذا Behavior صحيح من ناحية عدم عرض بيانات مستودع A تحت اسم B، لكنه ليس أفضل UX.

---

# 13) الحل الهندسي المتفق عليه للـLive Stock UX

المستخدم وافق على تطبيق:

```text
cache per warehouse
+ stale-while-revalidate
```

لكن بشروط صارمة:

- ممنوع عرض بيانات مستودع مختلف ولو للحظة.
- كل Cache مربوط بالمستودع نفسه.
- لا نغير API contracts.
- لا نغير Business Logic.
- لا نكسر Pagination.
- لا نكسر Filters/Search.
- لا نكسر AbortController / request sequencing.
- لا نكسر permission/access behavior.
- لا نخزن بيانات شركة/مستودع تحت Key غير صحيح.
- لا نعمل persistent cache غير مضبوط.
- الأفضل في البداية Memory cache داخل صفحة Dashboard فقط.
- عند الرجوع لمستودع سبق فتحه:
  - تظهر آخر بياناته فورًا.
  - يعمل Refresh بالخلفية.
  - لا نمسح الجدول.
- عند فتح مستودع لأول مرة:
  - Skeleton/Loading محترم.
  - لا نظهر بيانات مستودع آخر.
- نحتفظ بالسلوك الحالي أن تغيير المستودع يعيد search/filters للوضع الافتراضي، إلا إذا ناقشنا خلاف ذلك.
- First-page cache فقط في البداية، لا نحاول Cache pagination كاملة بشكل معقد.
- Summary cache كذلك إن كان مناسبًا.
- Cache key لازم يشمل على الأقل:
  - company scope إن كان متاحًا محليًا.
  - locationId.
  - ويجب عدم خلط نتائج Filters/Search.
- إذا كانت الفلاتر تعود Default عند Location change، ممكن cache default first page per warehouse.
- Refresh background يجب أن يحترم request sequence وAbort.

الخطة المقترحة:

```text
MainInventory.tsx
↓
introduce bounded in-memory cache per warehouse
↓
hydrate UI immediately from matching warehouse cache
↓
background fetch latest data
↓
only replace if request still current
↓
new warehouse without cache → skeleton/loading
```

---

# 14) المشكلة التي ذكرها صديق المستخدم — مراجعة تقنية

شخص رأى `live_stock.py` وقال إن فيه "بلاوي" منها:

1. Projection وهمية لأنها تعمل joins مع ProductVariant/Product/UOM/Company.
2. N+1 في `get_warehouse_inventory_batches`.
3. Python Decimal loop يعمل Event Loop blocking.
4. LATERAL joins قاتلة.
5. النظام المحترم يجب أن يرجع JSON بـQuery واحدة.

بعد مراجعة الكود والBenchmarks كان الحكم:

## ادعاء Projection وهمية
**غير صحيح/مبالغ فيه.**

`InventoryLiveStockProjection` عبارة عن Sparse derived read model للحقائق المكلفة:

```text
warehouse_on_hand
warehouse_reserved
warehouse_sellable_on_hand
warehouse_sellable_reserved
blocked_status_packs
recalled_packs
damaged_packs
vehicle_packs
minimum_quantity
is_low_stock
has_warehouse_presence
has_vehicle_presence
next_transition_date
```

ووجود joins مع Master Data مثل:

```text
ProductVariant
Product
UOM
Company
```

لا يلغي كونها Projection.

## ادعاء N+1 في batches
المصطلح **غلط**.

لا يوجد Query داخل loop لكل batch.

لكن توجد **عدة sequential DB round-trips ثابتة العدد** وهذا Tech Debt حقيقي.

في `get_warehouse_inventory_batches` يوجد تقريبًا:

```text
permission/location checks
variant validation
company local date lookup
batch aggregate
latest purchase rows
purchase count rows
currency lookup
```

و`get_company_local_date` نفسه يعمل أكثر من DB trip.

المشكلة الحقيقية:
- Endpoint chatty أكثر من المطلوب.
- يمكن دمج بعض الاستعلامات.
- لا يوجد bounded pagination واضح للـbatches.
- لو Variant واحد عنده آلاف الدفعات، هذا endpoint قد يصبح ثقيلًا.

## ادعاء Python Decimal loop قاتل
**مبالغ فيه.**

عمليات Decimal البسيطة على عشرات/مئات الصفوف ليست "حلقة موت".

لكن إذا الـendpoint يرجع آلاف batches بلا pagination، حجم loop + JSON يصبح خطر scalability.

## ادعاء LATERAL قاتل
**غير مثبت، والأرقام الحالية تميل لصالح التنفيذ.**

هناك LATERAL bounded by page ids، max تقريبًا 200.

وموجود indexes مخصصة:

```text
ix_inventory_cost_event_purchase_latest
ix_product_uom_conversion_display_seek
```

Benchmarks:

```text
live_50 details_p95 ≈ 4.6ms
live_200 details_p95 ≈ 18.3ms
```

لا نغير الـLATERAL بدون `EXPLAIN (ANALYZE, BUFFERS)` يثبت أنها hotspot.

## "Query واحدة أفضل دائمًا"
**قاعدة خاطئة.**

المهم:
- latency
- throughput
- bounded query count
- CPU
- I/O
- pool occupancy
- correctness
- maintainability

---

# 15) المشاكل الحقيقية المسجلة للـLive Stock

بعد مراجعة كلام الصديق والBenchmarks، المشاكل التي نريد حلها:

## A) `get_warehouse_inventory_batches`
الأولوية الأولى بعد UX.

المشاكل:

- عدة DB round-trips متتالية.
- يمكن غالبًا دمج:
  - latest purchase
  - purchase event count
- يمكن تحسين timezone/currency/date retrieval.
- يجب فحص duplication في validation/access.
- أهم نقطة: لا يوجد pagination/hard safe limit واضح للدفعات.

المطلوب:
- Baseline benchmark قبل أي تعديل.
- لا تغير semantics.
- لا تغير error codes.
- لا تغير tenant isolation.
- لا تغير cost evidence correctness.
- Patch تدريجي + Gate.
- قارن before/after.

## B) Search
بعد batches.

الكود يستخدم:

```sql
lower(name) LIKE '%token%'
lower(sku) LIKE '%token%'
```

Benchmark:

```text
search_50 p95 ≈ 75.4ms
candidate_p95 ≈ 63.5ms
sql_p95 ≈ 69.7ms
```

هذا يستحق Audit للفهارس/pg_trgm أو strategy بديلة.

لا تضف index عشوائيًا قبل `EXPLAIN ANALYZE`.

---

# 16) ملاحظات Scale/Pool السابقة

في Scale output ظهر:

```text
pool_wait_p95_ms ≈ 12.08ms
auth_blacklist ≈ 15.1ms
details ≈ 44.5ms تحت ASGI diagnostic
outside_sql_p95 ≈ 35.5ms
```

الحكم السابق:

- لا يوجد دليل على Connection Leak.
- لا يوجد دليل N+1 في Live Stock list؛ `sql_statements=3..3`.
- `auth_blacklist` حاليًا مدمج مع Driver auth query باستخدام EXISTS وليس query منفصلة في المسار الطبيعي.
- `TokenBlacklist.token` عليه unique index.
- `outside_sql` لا يثبت Pydantic/serialization وحدها.
- Worker variance لا يثبت Event Loop blocking وحده.
- `search_50` كان hotspot أوضح من LATERAL.

---

# 17) Cross-tenant / SaaS resource note

نفس endpoint يخدم كل الشركات، لكن RLS/company_id يعزل البيانات.

شركة ضخمة لا تجعل الشركة الصغيرة تحمل بياناتها.

لكن موارد السيرفر مشتركة:

```text
PostgreSQL
Connection Pool
CPU
RAM
Disk I/O
```

شركة ضخمة بضغط عالٍ قد تنافس الصغيرة على الموارد بشكل غير مباشر.

لاحقًا عند SaaS Billing يمكن عمل metering per company عبر:

```text
API requests
DB time
storage
active users
warehouses
product variants
inventory movements
background jobs
```

لكن هذه ليست أولوية الآن.

---

# 18) قرار الأولويات الحالي — مهم جدًا

آخر قرار من المستخدم:

```text
1. نصلح Live Stock UX loading flicker بالطريقة الهندسية الاحترافية.
2. فور الانتهاء ندخل على مشكلة الصديق:
   a. batches performance
   b. search performance
3. بعدها نرجع نكمل لوحة التحكم.
4. لا تقسيم driver/dispatch الآن.
5. تقسيم الملفات الأخرى لاحقًا بعد إنجاز Dashboard.
```

لا تغير هذا الترتيب إلا إذا ظهر Bug حرج.

---

# 19) ملفات كبيرة لاحقًا — فقط للتسجيل، ليس للعمل الآن

تم فحص أحجام:

```text
wa_backend/api/dispatch.py
~225 KB
~5494 lines
27 routes
50 funcs

wa_backend/api/driver.py
~153 KB
~3776 lines
13 routes
24 funcs

wa_backend/api/reconciliation.py
~18 KB
~425 lines
1 route

wa_backend/services.py
~253 KB
~6517 lines

wa_backend/models.py
~194 KB
~3440 lines
69 classes

wa_backend/schemas.py
~89 KB
~2409 lines
143 classes
```

القرار الحالي:

- `dispatch.py` يستحق التقسيم لاحقًا.
- `driver.py` يستحق التقسيم لاحقًا.
- `reconciliation.py` صغير نسبيًا.
- `services.py` يحتاج تنظيم لاحقًا.
- لا تفتح هذه الجبهة الآن.

---

# 20) قاعدة العمل على GitHub من هذه اللحظة

الـmain الحالي المرجعي:

```text
0d254b658b49a7ea8dc375eaa449b59f48192876
```

لكن Working Tree المحلي حاليًا فيه تعديل CSS وملفين untracked.

قبل Branch جديد:

1. افحص:
   ```powershell
   git branch --show-current
   git status --short
   git diff
   ```

2. لا تعمل Reset/Clean.

3. افهم إذا تعديل CSS:
   ```text
   flex: 0 1 24rem
   →
   flex: 0 0 24rem
   ```
   مقصود ضمن UI work حالي.

4. افحص محتوى:
   ```text
   dashboard/live_stock_ui_build.txt
   dashboard/live_stock_ui_tests.txt
   ```
   غالبًا outputs لاختبارات/build، لكن لا تفترض.

5. بعد حفظ/تثبيت الحالة، افتح Branch جديد لمرحلة Live Stock UX.
   اسم مقترح:
   ```text
   fix/live-stock-instant-switching
   ```

6. لا تعدل `main` مباشرة.

---

# 21) طريقة العمل المطلوبة في التعديل القادم

## المرحلة الأولى: Live Stock UX

قبل أي Patch:

- اقرأ `MainInventory.tsx` كاملًا حول:
  - stock state
  - fetchStock
  - fetchStockSummary
  - location change effect
  - resetStockPagination
  - filters/search
  - AbortController
  - request sequence refs
- اقرأ `Tab1LiveStock.tsx`.
- اقرأ contracts/parsers الخاصة بـLive Stock.
- اقرأ tests الموجودة:
  ```text
  dashboard/src/test/live-stock-minimum.test.ts
  ```
  وابحث عن tests أخرى تخص inventory/live stock.
- افحص package.json test/build scripts.

ثم صمم cache بدون تغيير API.

## قواعد الـCache:

- لا cache عالمي غير scoped.
- لا localStorage للبيانات الحساسة في النسخة الأولى.
- Memory cache فقط.
- keyed by location + state context الضروري.
- لا تعرض stale data لمستودع آخر.
- Background refresh فقط للـmatching location.
- request sequence يجب أن يظل authority لمنع race.
- Abort old request عند switching.
- Pagination:
  - cache first page فقط.
  - لا تحفظ cursor chain بشكل معقد من أول Patch.
  - load more يبقى network-driven.
- تغيير filter/search:
  - reset الحالية تبقى كما هي.
  - لا تعرض cached default page إذا filter/search active.
- refresh manually:
  - يجب أن يعمل revalidate.
- summary:
  - cache منفصل أو same entry لكن type-safe.
- عند fetch failure:
  - إذا عندك cached data matching نفس المستودع، الأفضل تحافظ عليها مع error indicator/toast بدل مسحها.
  - إذا لا cache: السلوك الحالي error state.
- cache must be bounded:
  - لأن عدد المستودعات قد يزيد.
  - يمكن limit بسيط LRU/Map eviction أو عدد reasonable.
- لا تجعل cache يخفي bugs أو data correctness issues.

## UX هدفنا:

```text
Switch to previously visited warehouse
→ instant cached display
→ subtle refreshing indicator
→ new data replaces old
```

ولأول مرة:

```text
Switch to unseen warehouse
→ skeleton/loading
→ real data
```

---

# 22) Stage بعد UX مباشرة: Batches Performance Hardening

بعد ما UX يمر Build/Tests ويثبت:

قبل التعديل:
- Benchmark endpoint الحالي.
- Count DB statements.
- Capture latency.
- Analyze query plans.
- لا تغير semantics.

التحسينات المرشحة:
- دمج latest purchase + purchase count.
- تقليل sequential lookups.
- دمج company timezone/currency fetch حيث منطقي.
- فحص access/location validation duplication.
- إضافة pagination أو hard safe limit للbatches.
- إضافة Gate correctness.
- Benchmark before/after.

---

# 23) Stage بعد batches: Search Performance

اعمل:

```text
EXPLAIN (ANALYZE, BUFFERS)
```

على search query.

افحص:
- current indexes
- `lower(name) LIKE '%...%'`
- `lower(sku) LIKE '%...%'`
- إمكانية `pg_trgm`
- tenant-scoped composite/trigram strategy

لا تضف Index قبل إثبات الحاجة.

الهدف:
- خفض candidate latency.
- الحفاظ على نفس search semantics.
- الحفاظ على escaping behavior.
- الحفاظ على tenant isolation.

---

# 24) ملف inventory.css الحالي

التعديل المحلي الحالي:

```css
.live-stock-search {
  position: relative;
  width: min(100%, 24rem);
  flex: 0 0 24rem;
  min-width: 12rem;
}
```

كان سابقًا:

```css
flex: 0 1 24rem;
```

لا تلمسه بدون فهم السبب.

هذا قد يكون جزءًا من تحسين Layout سابق ولا علاقة له مباشرة بـcache.

---

# 25) لا تنسى

- المستخدم لا يريد شرح طويل إذا طلب تنفيذ مباشر.
- المستخدم يريد دقة أكثر من السرعة.
- لا تدافع عن الكود لمجرد أنه كودنا.
- إذا مراجعة خارجية صحيحة قل إنها صحيحة.
- إذا مبالغ فيها وضح السبب بالأرقام.
- أي تغيير Performance لازم يثبت بـBenchmark.
- لا نكسر business logic مقابل milliseconds.
- لا نغير thresholds لكي تمر الاختبارات.
- لا نضع TODO ونتركه إن كان Critical.
- لا نفتح 5 جبهات بنفس الوقت.
- الهدف الحالي: **إنجاز Dashboard بجودة Production**.

---

# 26) نقطة البداية المطلوبة في المحادثة الجديدة

بعد قراءة هذا الملف، أول رد عملي يجب أن يكون تقريبًا:

1. تأكيد أن `warehouse` مغلق ومندمج على main.
2. التنبيه أن Working Tree الحالي غير نظيف:
   ```text
   M dashboard/src/pages/inventory/inventory.css
   ?? dashboard/live_stock_ui_build.txt
   ?? dashboard/live_stock_ui_tests.txt
   ```
3. لا تعمل reset.
4. افحص الملفات المحلية أولًا.
5. بعد حفظها، افتح Branch جديد من main.
6. ابدأ فقط بـLive Stock instant warehouse switching.
7. لا تبدأ batches قبل إغلاق UX.
8. بعد UX مباشرة: batches، ثم search، ثم العودة للDashboard.

---

# 27) Summary شديد الاختصار

```text
WAREHOUSE SPLIT = DONE ✅
MAIN = 0d254b658b49a7ea8dc375eaa449b59f48192876 ✅
FINAL FORENSIC = PASS ✅

CURRENT LOCAL TREE:
M  dashboard/src/pages/inventory/inventory.css
?? dashboard/live_stock_ui_build.txt
?? dashboard/live_stock_ui_tests.txt

CURRENT TASK:
Live Stock UX instant switching:
cache per warehouse + stale-while-revalidate
without cross-warehouse leakage or breaking filters/pagination.

NEXT:
1) batches performance hardening
2) search performance hardening
3) continue Dashboard

NOT NOW:
driver/dispatch/services splitting
Flutter work
billing/metering
```

---

# 28) آخر توجيه للمساعد الجديد

عامل هذا الملف كـProject Handoff موثوق.

لا تبدأ تعديل مباشرة قبل التحقق من الحالة المحلية الحالية.

لا تتجاوز قواعد الـGit ولا قواعد الـPatch.

أي خطوة جديدة يجب أن تبني على:

```text
main baseline:
0d254b658b49a7ea8dc375eaa449b59f48192876
```

مع الحفاظ على أي local changes موجودة الآن.
