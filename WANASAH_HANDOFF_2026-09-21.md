# WANASAH — ملف تسليم كامل للمحادثة التالية
**التاريخ:** 2026-09-21  
**المشروع:** `MohHamdallah1/wanasah`  
**الغرض:** هذا الملف هو نقطة الاستمرار للمحادثة الجديدة. اقرأه كاملًا قبل اقتراح أي تعديل أو تنفيذ أي Patch.

---

## 1) قواعد العمل الصارمة

1. لا تخمّن. افحص الكود الحقيقي والملفات المرتبطة قبل أي استنتاج أو Patch.
2. لا تغيّر منطق العمل الحالي أو الـWorkflow إلا بعد شرح السبب والحصول على موافقة المستخدم إذا كان التغيير سلوكيًا.
3. لا حلول مؤقتة، لا shortcuts، ولا tech debt متعمد. المطلوب Production-grade من البداية.
4. لا تضعف الاختبارات حتى تمر. إذا فشل Test أصلح السبب الحقيقي.
5. لا تكبّر DB pool أو limits عشوائيًا لإخفاء مشاكل الأداء.
6. لا N+1، لا query amplification، ولا aggregate ثقيل قبل LIMIT في Live Stock.
7. أي تغيير مهم في مسار Query يجب أن يُراجع أداؤه بعد استقرار التصميم.
8. المستخدم يريد Patch جراحي وتحليل cross-file عند الحاجة.
9. لا تحذف Legacy/Dead code عشوائيًا الآن؛ التنظيف النهائي له مرحلة مستقلة لاحقًا.
10. الواجهة يجب أن تكون SaaS احترافية، نظيفة، بسيطة، مفهومة، وغير مزدحمة.
11. المصطلحات يجب أن تكون محاسبية/مخزنية واضحة ومهنية، وليس أسماء backend مبهمة.
12. كل UI جديد من الآن يجب أن يكون مؤسسًا لتعدد اللغات:
   - النصوص عبر `i18next` / `t(...)`
   - اتجاه RTL/LTR عبر `i18n.dir()`
   - التواريخ عبر `Intl`
   - العملات عبر `Intl.NumberFormat`
   - لا Hardcoded Arabic/English في حالات التحميل/الأخطاء/العناوين User-facing.
13. المستخدم يفضّل الرد المباشر والمختصر والأوامر Copy/Paste.
14. قبل الدمج في `main`: مراجعة + Tests/Gates.
15. لأي Batch جديد غير تافه: Branch جديدة من `main`، ولا دمج قبل الاعتماد.

---

## 2) حالة Git الحالية

تم دمج Live Stock UI Batch 1.

- PR: **#7**
- العنوان: `Live Stock UI batch 1`
- الحالة: merged
- Merge commit:
  `2a895bbce1d50bb8b6177c7781c35f3edafb6915`
- وقت الدمج: `2026-09-21T03:51:08Z`

آخر HEAD مؤكد لـ`main` وقت إنشاء هذا الملف:

```text
3767f8f19351873f85b66b4bc3aa3f36839096e1
```

آخر commit:

```text
Inventory i18n hardening
```

والـparent هو Merge commit أعلاه.

الفرع السابق:

```text
ui/live-stock-batch1
```

تم حذفه بعد الدمج. لذلك في المحادثة الجديدة ابدأ من:

```powershell
cd C:\Users\admin\Desktop\wanasah
git checkout main
git pull --ff-only origin main
git status
```

وأي شغل جديد غير تافه يُفضّل له Branch جديدة من `main`.

---

## 3) تفاصيل بيئة الشركة الحالية

هذه بيانات حساب التطوير الحالي التي أعطاها المستخدم صراحة:

```text
company_id: 38
company_code: DEV-01
driver_id: 26
user: مدير التطوير
selected_warehouse: 119
```

أي أوامر Demo/Inventory لهذه البيئة غالبًا تستخدم:

```text
--company-id 38
--location-id 119
```

للتحقق من المتصفح:

```js
const companyId = localStorage.getItem("company_id");
({
  company_id: companyId,
  company_code: localStorage.getItem("company_code"),
  driver_id: localStorage.getItem("driver_id"),
  user: localStorage.getItem("admin_name"),
  selected_warehouse: localStorage.getItem(`inventory_selected_location:${companyId}`)
})
```

---

## 4) Stack المشروع

### Backend
- Python backend داخل `wa_backend`
- PostgreSQL
- SQLAlchemy Async
- Alembic
- Multi-tenant isolation بـ`company_id`
- RBAC وصلاحيات Inventory دقيقة
- Live Stock projection/read model

### Dashboard
- React
- TypeScript
- Vite
- TanStack Query
- Radix UI
- i18next
- Sonner
- CSS مخصص للمخزون

### Mobile
- Flutter
- Offline/sync logic
- لم يُغلق بعد، وسيعود في Stage 10.

---

## 5) الخطة الكبيرة للمشروع

المسار العام:

```text
models.py + schemas.py
→ services.py
→ إنهاء warehouse.py
→ driver.py + reconciliation.py
→ dispatch.py
→ Flutter/Offline
→ حذف الكود القديم
→ Baseline Alembic نظيف
→ الاختبارات النهائية
```

مرحليًا:
- Stage 6: إلى حد كبير منجز، مع Gates موجودة، لكن الإغلاق النهائي مرتبط أيضًا بعقود Dashboard والتدقيق النهائي.
- Stage 7: `Valuation, Penalty and Currency` لم يُغلق رسميًا بالكامل.
- Stage 10: Flutter/Offline لاحقًا.
- Stage 11: Legacy removal + clean Alembic baseline + freeze نهائي.

`warehouse.py` ضخم جدًا (كان تقريبًا 10k+ سطر). الاتفاق:
- لا نزيد تكديس المنطق فيه بلا نهاية.
- بعد استقرار Inventory UI نعمل modularization structure-only:
  - نفس routes
  - نفس contracts
  - نفس behavior
  - نفس gates
  - بدون تغيير Workflow.

---

## 6) Performance / Stage 8.2.3

نتائج سابقة ناجحة:

```text
LIVE_STOCK_SCALE_GATE=PASS
LIVE_STOCK_FULL_REGRESSION_SUITE=PASS
```

وسابقًا:

```text
29 tests OK
INVENTORY_AUDIT_V3_OFFLINE_OK
POSTGRESQL_CONCURRENCY_NOT_TESTED_BY_THIS_SCRIPT
```

قواعد الأداء:
- لا aggregate كامل قبل LIMIT.
- لا N+1.
- لا تحميل Bulk لكل المنتجات من أجل UI.
- Cursor pagination هو الأساس.
- UI يمكن أن يعمل continuous scroll، لكن backend يبقى batches محدودة.
- Performance C20 acceptance تقريبًا: 4 workers × pool 5 = 20، R100، p95 ~500ms في البيئة المعتمدة.
- WSL المحلي أعطى نتائج performance مضطربة أحيانًا بينما Windows نجح؛ لا ترجع الكود بسبب WSL غير مستقر.
- الاختبار النهائي يكون على Linux مستقر/بيئة capacity مع observability لاحقًا.

Gates مهمة:

```powershell
cd C:\Users\admin\Desktop\wanasah\wa_backend
python .\scripts\gate_live_stock_filter_contract.py
python .\scripts\gate_live_stock_minimum_policy.py
python .\scripts\gate_inventory_batches_page.py
python .\scripts\gate_stage823_mapper_startup.py
python .\scripts\gate_stage823_live_stock_read_model_core.py
```

وعند استقرار Query path:

```powershell
python .\scripts\gate_live_stock_scale.py
```

Dashboard:

```powershell
cd C:\Users\admin\Desktop\wanasah\dashboard
npm test
npx tsc --noEmit -p tsconfig.app.json
npm run build
```

Backend import sanity:

```powershell
cd C:\Users\admin\Desktop\wanasah\wa_backend
python -c "import main; print('MAIN_IMPORT_OK')"
```

لا يوجد GitHub Actions run مؤكد لآخر `main` وقت كتابة الملف؛ لا تفترض أن آخر HEAD مُختبر محليًا إلا إذا أعطى المستخدم النتائج.

---

## 7) Live Stock — الوضع الحالي

الشريط العلوي يحتوي على:
- بحث
- فلترة
- عائلة المنتج
- الحد الأدنى للمخزون
- المستودع المحدد
- عدد الرصيد الحي
- آخر تحديث + Refresh

### مشكلة Initial load السابقة
كان يظهر `لا توجد بيانات مطابقة` عند أول فتح، ثم تظهر البيانات بعد تبديل المستودع.

السبب الحقيقي:
- `Tab1LiveStock` كان يرسل Search فارغ بعد debounce.
- الـparent يعمل reset للـpagination حتى لو القيمة أصلًا فارغة.
- هذا كان يمسح البيانات التي وصلت للتو بدون state change جديد يعيد fetch.

الإصلاح:
- عدم reset إذا البحث لم يتغير.
- child لا يعيد emit نفس البحث.
- auto-select أول مستودع متاح إذا لا يوجد saved valid warehouse.
- loading/reset behavior عُدل.

---

## 8) Search behavior الحالي

البحث صار **مرن token-based** في backend.

في `wa_backend/api/warehouse.py`:
- `clean_search.split()`
- كل token يجب أن يوجد في اسم المنتج **أو** SKU.
- كل token يعمل contains: `%token%`.
- ترتيب الكلمات ليس شرطًا.

مثال، اسم المنتج:

```text
شيبس لولو جبنة كبير
```

البحث:

```text
شيبس كبير
```

يظهر المنتج، وكذلك:

```text
كبير شيبس
```

لأن كل token مستقل وAND بينهم.

SKU يبقى قابلًا للبحث حتى لو لا يظهر في Live Stock row.

---

## 9) SKU

المستخدم لا يريد SKU تحت اسم المنتج في Live Stock.

أمثلة Demo قديمة:

```text
SKU-3739CD6D86B34C79-00001
PERF-LIVE-000001
```

SKU يبقى ضروريًا داخليًا من أجل:
- uniqueness
- barcode/integration
- search
- تقارير
- تمييز المنتجات المتشابهة

لكن لا يظهر داخل صف Live Stock. يظهر فقط حيث يحتاجه المستخدم مثل اختيار منتج محدد/إدارة المنتجات/تفاصيل مفيدة.

---

## 10) عرض الكميات والوحدات

المنطق الحالي يدعم mixed units عبر:

```text
formatCommercialQuantity(...)
```

مثال Demo متعمد:

```text
2520 حبة
factor = 50
=> 50 كرتونة + 20 حبة
```

قرار UX:
- لا نستخدم `102 ك + 25 ح` لأنها مبهمة.
- لا نستخدم `CTN / EA` في الواجهة العربية العادية.
- نستخدم:

```text
102 كرتونة + 25 حبة
```

لكن بسطر واحد، no-wrap، خط أصغر، وpadding أقل للحفاظ على صف مضغوط.

---

## 11) حجم صف Live Stock

تم تصغير:
- row intrinsic size
- padding
- minimum line
- رقم الصف
- منع التفاف quantity cells

الهدف: صفوف أكثر على الشاشة بدون إخفاء معلومات.

---

## 12) أعمدة المنتج والعائلة

تم فصل:
- `#`
- المنتج
- العائلة

وتم:
- توسيط Header المنتج والعائلة
- إضافة فاصل واضح
- تقليل عمود المنتج قليلًا
- توسيع العائلة

آخر نسب معروفة:

```css
live-product-heading: 16%
live-family-heading: 13%
```

---

## 13) Family filter

- منفصل عن الفلاتر الرئيسية.
- لا يوجد `كل العائلات` كخيار داخل القائمة.
- زر Clear يظهر عند وجود اختيار.
- القائمة أضيق عرضًا وأطول، تقريبًا 6 عائلات ثم Scroll.
- family = `Product` parent، وليس category.
- `Product.category` شيء مختلف.

---

## 14) Filters الحالية

### Stock state — اختيار واحد
- all
- on_hand
- sellable
- out_of_stock
- low_stock

المعاني:
- `on_hand`: يوجد رصيد مادي داخل المستودع حتى لو جزء محجوز/غير متاح.
- `sellable`: available_for_sale > 0
- `out_of_stock`: available_for_sale <= 0
- `low_stock`: projection is_low_stock

### Indicators — Multi-select وAND
- reserved
- unavailable
- damaged
- recalled
- vehicle
- minimum_unset

`vehicle` permission-aware.

---

## 15) Continuous scroll

تم إلغاء Previous/Next UI.

الآن:
- backend cursor batch ~50
- frontend append
- IntersectionObserver قرب النهاية
- dedupe بالـid
- `content-visibility:auto`

لا نحمل 10k rows من backend دفعة واحدة.

إذا صار memory issue مستقبلًا: proper virtualization، وليس الرجوع لحل backend سيئ.

---

## 16) Available for sale emphasis

آخر طلب قبل الانتقال للمحادثة الجديدة: خلفية خفيفة برتقالي/أصفر فقط خلف القيمة نفسها.

تم تنفيذ Wrapper:

```tsx
<span className="live-stock-sellable-chip">
  {available.primary}
</span>
```

راجع CSS بصريًا إذا احتاج اللون ضبطًا، لكن المطلوب:
- الخلفية فقط حول الرقم/الكمية
- خفيفة
- لا تلون الخلية كاملة.

---

## 17) مصطلحات التكلفة

المستخدم رفض:

```text
آخر شراء للشركة
متوسط الشركة
```

وتم تغييرها إلى:

```text
تكلفة آخر شراء
متوسط التكلفة
```

والإنجليزية:

```text
Latest purchase cost
Average cost
```

المعنى الفني بقي نفسه:
- آخر تكلفة شراء فعلية مسجلة للمنتج على مستوى الشركة، بوحدة الشراء.
- متوسط التكلفة المالي الحالي للمنتج على مستوى الشركة.

---

## 18) العملة — Dynamic وليست Hardcoded JOD في Live Stock

ظهور `د.أ.` ليس نصًا ثابتًا داخل الخلية.

المسار:
- backend يرجع `currency_code` من `Company.currency_code`.
- `Company` model حاليًا يحتوي:

```python
currency_code = default 'JOD'
timezone = default 'Asia/Amman'
```

- frontend يستخدم `formatMoneyDisplay` و`formatMoneyExact`.
- داخلهما `Intl.NumberFormat` مع `currencyDisplay: "narrowSymbol"`.
- لذلك العربية + JOD قد تظهر `د.أ.` تلقائيًا.

إذًا display layer مهيأة multi-currency وليست hardcoded JOD.

---

## 19) Country + Currency — قرار التصميم القادم

الوضع الحالي:
- `Company` يحتوي `currency_code` و`timezone`.
- لا يوجد `country_id` أو `country_code` مباشر على Company.
- يوجد `Country` model ضمن هرم التوزيع الجغرافي `Country → Governorate → Zone`.

التوصية عند التنفيذ:
مكان إعداد:
- بلد الشركة
- العملة
- المنطقة الزمنية

هو:

```text
الإعدادات → إعدادات الشركة / الملف التجاري / الإعدادات الإقليمية
```

وليس داخل Inventory ولا Warehouse ولا User.

المبدأ:
- country = company-level regional/legal setting
- currency_code = company-level financial setting
- timezone = company-level operational setting

قبل إضافة country على Company لا تعيد استخدام `Country` الجغرافي عشوائيًا؛ قرر هل Company.country_id FK لنفس جدول countries أم ISO country code مستقل، ثم افحص migration/contracts.

---

## 20) i18n — شرط أساسي من الآن

المستخدم سيحوّل اللوحة لدعم عدة لغات، وهذا ضروري.

الوضع الحالي:
- `i18next`
- Arabic + English resources موجودة
- تم عمل Pass أخير على Inventory: `Inventory i18n hardening`
- تم Localize حالات loading/error المهمة في inventory
- بعض contract failures أصبحت stable error codes بدل Hardcoded UI messages

قواعد كل كود جديد:

ممنوع User-facing hardcode مثل:

```tsx
<div>جارٍ التحميل...</div>
toast.error("تعذر...")
```

الصحيح:
- UI: `t("...")`
- Contract/parser: stable code ثم localized mapping/fallback في UI
- direction: `dir={i18n.dir()}`
- locale: `i18n.resolvedLanguage || i18n.language`

لا تفترض أن كل المشروع i18n-clean؛ الـInventory حصل عليه Hardening Pass، لكن يلزم Repo-wide audit قبل إطلاق تعدد اللغات.

---

## 21) Minimum Stock — التصميم الحالي

المصطلح المعتمد:

```text
الحد الأدنى للمخزون
```

وليس `حدود التخزين` ولا `حد إعادة الطلب` لأن Reorder Point مفهوم أوسع.

تم إزالة زر تعديل صغير من كل صف. يوجد زر أعلى الصفحة:

```text
الحد الأدنى للمخزون
```

يفتح Dialog مركزي.

### Scopes
- كل المنتجات
- عائلات محددة
- منتجات محددة

### Multi-select
- العائلات Multi-select
- المنتجات Multi-select
- زر مسح التحديد
- عداد عدد المحددات

### Preview
كانت إجبارية ثم المستخدم رفض ذلك. الآن:

```text
معاينة (اختياري)
```

ويمكن الضغط `تطبيق` مباشرة.

### Default behavior
الافتراضي الحالي backend mode:

```text
OVERWRITE
```

لكن UI لا تعرض الاسم التقني.

الخيارات UI أصبحت أوضح:

الخيار الأساسي:

```text
تحديث العناصر المحددة
```

المعنى: يضع الرقم الجديد على كامل النطاق المختار، ويستبدل الحد السابق إن وجد.

الخيار الثاني:

```text
إضافة للمنتجات بدون حد
```

المعنى: لا يغير أي حد موجود مسبقًا؛ يضبط فقط المنتجات التي لم يُحدد لها حد.

### مشكلة 0 products
سابقًا كان يظهر Success مضلل مثل:

```text
تم تعديل الحد الأدنى إلى 0 منتج
```

تم تعديل السلوك:
- لا Success مضلل إذا `affected_count == 0`.
- إذا السبب أن المنتجات لديها حدود سابقة، Toast يشرح ذلك ويوجه إلى `تحديث العناصر المحددة`.
- إذا القيمة نفسها أصلًا، Toast يقول لا يوجد تغيير.

---

## 22) Minimum Stock dialog UX

المستخدم اشتكى من:
- العنوان العربي مزاح لليسار
- النص تحته غير مضبوط
- Dialog يصغر/يكبر عند التنقل بين All/Family/Product
- flicker/انكماش أثناء loading

تم عمل:
- `dir={i18n.dir()}`
- `inventory-minimum-header` مع `text-align:start`
- نقل زر close للجهة الصحيحة RTL
- fixed/stable dialog dimensions
- target area بارتفاع ثابت
- ALL scope يأخذ مساحة مساوية تقريبًا
- family/product pickers بارتفاع ثابت
- loading يبدأ فورًا قبل debounce لتجنب flash blank
- body scroll داخلي عند الحاجة

إذا أرسل المستخدم Screenshot جديد: راجع بصريًا ولا تفترض أنه مثالي.

---

## 23) Minimum Stock backend

ملف:

```text
wa_backend/api/inventory_stock_policy.py
```

Single product endpoint القديم ما زال موجودًا:

```text
PUT /warehouse/inventory/{product_variant_id}/minimum-stock
```

Bulk preview:

```text
POST /warehouse/inventory/minimum-stock/bulk/preview
```

Bulk apply:

```text
PUT /warehouse/inventory/minimum-stock/bulk
```

Scopes:

```text
ALL
FAMILY
PRODUCT
```

يدعم:

```text
family_ids: list[int]
product_variant_ids: list[int]
```

تقريبًا:
- family ids max 100
- product ids max 200

Backend apply modes:

```text
ONLY_UNSET
OVERWRITE
```

لا تعرضها للمستخدم بهذه الأسماء.

الأمان:
- company admin only
- warehouse access
- ProductLocation required
- quantity validation
- exact display/base UOM conversion
- idempotency
- advisory locking
- row locking
- audit log
- target_quantity invariant
- projection refresh
- bulk refresh keys chunks ~5000
- conflicts fail safely

Audit:

```text
LIVE_STOCK_MINIMUM_UPDATED
LIVE_STOCK_MINIMUM_BULK_UPDATED
```

Operation:

```text
LIVE_STOCK_MINIMUM_BULK_UPDATE
```

---

## 24) Low stock semantics

Alert:

```text
minimum_quantity > 0
AND
available_for_sale_quantity <= minimum_quantity
```

`0` = no minimum/disable this alert behavior.

الحد تابع:
- company
- location
- product_variant

---

## 25) صفحة الدفعات والصلاحية

المستخدم رفض عرض عشرات الدفعات تحت صف Live Stock.

تم:
- إزالة expand arrow/details من Live Stock
- عدم حذف backend batch logic
- إنشاء Tab مستقل `الدفعات والصلاحية`

ملف:

```text
dashboard/src/pages/inventory/TabBatches.tsx
```

يعرض:
- Product search
- SKU حيث يكون مفيدًا
- قائمة المنتجات
- دفعات المنتج
- batch number
- production date
- expiry
- days remaining/expired
- disposition
- on hand
- reserved
- available
- unavailable
- restricted/quarantined/blocked/recalled/damaged/disposal pending
- latest purchase cost
- purchase event count

Endpoint:

```text
GET /warehouse/inventory/{product_variant_id}/batches?location_id=...
```

Contract parser:

```text
parseBatchDetailResponse
```

Gate:

```text
wa_backend/scripts/gate_inventory_batches_page.py
```

قاعدة: لا تعيد تفاصيل الدفعات إلى Live Stock rows. إذا احتجنا indicator مستقبلًا يكون مختصرًا مع انتقال للصفحة المخصصة.

---

## 26) Demo / Seed data

ملف:

```text
wa_backend/scripts/seed_live_stock_demo.py
```

تم توسيعه لبيانات متنوعة:
- عائلات متعددة
- carton factors: 50 / 24 / 12 / 6
- base-unit-only products أحيانًا
- loose remainders
- 1–3 batches
- expiry variety
- reserved
- blocked
- recalled
- quarantined
- damaged
- products بدون minimum stock
- alert products

أول منتج Demo مقصود:

```text
2520 EACH
=> 50 CARTON + 20 EACH
```

أوامر البيئة الحالية:

```powershell
cd C:\Users\admin\Desktop\wanasah\wa_backend
python .\scripts\seed_live_stock_demo.py --list
```

Cleanup Demo:

```powershell
python .\scripts\seed_live_stock_demo.py --cleanup --company-id 38 --confirm-dev
```

Seed:

```powershell
python .\scripts\seed_live_stock_demo.py --company-id 38 --location-id 119 --count 120 --alerts 18 --confirm-dev
```

الـDemo cleanup يستهدف prefix الخاص بالـDemo الجديد فقط.

---

## 27) PERF-LIVE data

البيانات مثل:

```text
PERF-LIVE-000001
```

قادمة من:

```text
wa_backend/scripts/seed_live_stock_scale.py
```

وليس من Demo seeder الجديد.

قاعدة التطوير الحالية تجريبية، لكن لا تنفذ تنظيفًا ضخمًا تلقائيًا. اعرض للمستخدم ماذا سيُحذف أولًا.

---

## 28) Topbar / Sidebar seam

المستخدم يريد Top Inventory dock يندمج بصريًا مع Sidebar بدون خط أو shadow.

تم سابقًا:
- إزالة border/shadow من Sidebar desktop
- تعديل gradient
- Sidebar full height

إذا عاد seam، راجع DOM/CSS فعليًا. مشتبه سابق كان `column-gap` بين Sidebar/main.

---

## 29) مصطلحات Inventory الحالية

```text
الرصيد الحي
الدفعات والصلاحية
توريد بضاعة
الحوالات
سجل الحركات
جرد وتسوية
إدارة المستودعات
الصلاحيات
```

Live Stock:

```text
إجمالي الموجود
محجوز لعملية
المتاح للبيع
غير متاح للبيع
مع المركبات
تكلفة آخر شراء
متوسط التكلفة
الحد الأدنى للمخزون
```

لا تستخدم:

```text
متوسط الشركة
آخر شراء للشركة
حدود التخزين
```

إلا إذا صار لها معنى خاص ومفسر.

---

## 30) Inventory data semantics

داخل المستودع:

```text
إجمالي الموجود
= reserved + available for sale + unavailable
```

Vehicle stock منفصل.

`available for sale` = المخزون الذي يسمح النظام بصرفه الآن بعد الاستبعادات.

`on_hand` = وجود مادي في المستودع، وقد يشمل غير القابل للبيع.

Costs = بيانات مالية على مستوى الشركة، وليست Cost per warehouse.

---

## 31) أهم الملفات التي تغيرت في Batch الأخيرة

```text
dashboard/src/components/operations/dashboard.css
dashboard/src/features/commercialRules/OfferManagement.tsx
dashboard/src/i18n/resources.ts
dashboard/src/pages/DispatchBoard.tsx
dashboard/src/pages/inventory/MainInventory.tsx
dashboard/src/pages/inventory/StockMinimumManager.tsx
dashboard/src/pages/inventory/Tab1LiveStock.tsx
dashboard/src/pages/inventory/TabBatches.tsx
dashboard/src/pages/inventory/TabInventoryAccess.tsx
dashboard/src/pages/inventory/inventory.css
dashboard/src/pages/inventory/ledger/contracts.ts
dashboard/src/pages/inventory/liveStock/contracts.ts
dashboard/src/pages/inventory/quantity.ts
dashboard/src/test/inventory-access.test.ts
dashboard/src/test/live-stock-minimum.test.ts
wa_backend/api/inventory_stock_policy.py
wa_backend/api/warehouse.py
wa_backend/main.py
wa_backend/schemas.py
wa_backend/scripts/gate_inventory_batches_page.py
wa_backend/scripts/gate_live_stock_filter_contract.py
wa_backend/scripts/gate_live_stock_minimum_policy.py
wa_backend/scripts/seed_live_stock_demo.py
```

بعد الدمج يوجد Follow-up:

```text
Inventory i18n hardening
```

---

## 32) TypeScript fixes الجانبية

### OfferManagement
`replaceAll` لم يكن مدعومًا حسب TS target:

```ts
replace(/_/g, " ")
```

### DispatchBoard
`data: unknown` لم يعد يُقرأ منه `shop_id` blindly؛ تم runtime validation.

### ledger/contracts.ts
تم تثبيت Literal types مثل:
- `balance_scope`
- `cost_method`

### TabInventoryAccess
`useQuery` كان يرجع unknown. تم إضافة parsing/validation لعقود:
- Roles
- Users
- Locations
- Catalog
- Grants

---

## 33) Multi-tenant identity/session

Login response يحتوي:

```text
company_id
company_code
driver_id
driver_name
...
```

ويحفظ:

```text
localStorage.company_id
localStorage.company_code
localStorage.driver_id
localStorage.admin_name
```

عند تبديل Company يتم تنظيف tenant-scoped local storage keys.

Inventory access query key مقسّم حسب:

```text
company_id
driver_id
location_id
```

Server يبقى authority الحقيقي؛ localStorage ليس security boundary.

---

## 34) العمل القادم مباشرة في المحادثة الجديدة

1. اقرأ هذا الملف كاملًا.
2. تأكد من `main HEAD` و`git status`.
3. لا ترجع للعمل على branch القديمة؛ ابدأ Branch جديدة إذا احتجنا edits.

المسارات المرجحة:

### A) مراجعة نهائية بصرية لـLive Stock
- sellable chip
- row density
- family/product widths
- minimum dialog
- RTL
- filtering
- mixed units

### B) Country/Currency settings
تصميم Settings احترافي:
- company country
- currency
- timezone
- locale defaults ربما
مع migration/contracts/validation وعدم hardcoding.

### C) استكمال Inventory tabs
بعد Live Stock + Batches.

### D) Modularize warehouse.py
Structure-only قبل زيادة backend فيه.

### E) الرجوع Stage 7
Valuation / Penalty / Currency audit والإغلاق.

---

## 35) أمور لم تُغلق Production-wise

حتى لو UI ممتاز:
- Stable Linux capacity test
- production observability
- runbook
- recovery
- full PostgreSQL concurrency proof
- final Stage 7 closure
- Flutter/offline
- legacy removal
- clean Alembic baseline
- final freeze

لا تقل إن المشروع Production-ready بالكامل قبل هذه النقاط.

---

## 36) أسلوب التعامل مع المستخدم

- المستخدم يتابع التفاصيل ويكتشف التناقضات بسرعة.
- لا تقل `كله جاهز` بدون Evidence.
- إذا وجدت bug: حدد root cause، لا تخمّن، أصلح المصدر، وأضف gate/test إذا المشكلة قابلة للرجوع.
- UX: اجعل Default هو الأكثر توقعًا، والخيارات الحافظة/المتقدمة Secondary.
- لا تعرض أسماء backend مثل `OVERWRITE` و`ONLY_UNSET` للمستخدم.
- إذا قال `خفف حكي`: أعط الزبدة + الأوامر.
- إذا طلب رأيًا: أعط توصية واضحة وسببًا عمليًا.

---

## 37) أوامر بداية أي Session جديدة

### Sync main

```powershell
cd C:\Users\admin\Desktop\wanasah
git checkout main
git pull --ff-only origin main
git status
```

### Backend gates

```powershell
cd .\wa_backend
python .\scripts\gate_live_stock_filter_contract.py
python .\scripts\gate_live_stock_minimum_policy.py
python .\scripts\gate_inventory_batches_page.py
python .\scripts\gate_stage823_mapper_startup.py
python .\scripts\gate_stage823_live_stock_read_model_core.py
python -c "import main; print('MAIN_IMPORT_OK')"
```

### Dashboard

```powershell
cd ..\dashboard
npm test
npx tsc --noEmit -p tsconfig.app.json
npm run build
```

### Demo dataset

```powershell
cd ..\wa_backend
python .\scripts\seed_live_stock_demo.py --list
python .\scripts\seed_live_stock_demo.py --cleanup --company-id 38 --confirm-dev
python .\scripts\seed_live_stock_demo.py --company-id 38 --location-id 119 --count 120 --alerts 18 --confirm-dev
```

---

## 38) Current source-of-truth summary

```text
Repo: MohHamdallah1/wanasah
Branch to continue from: main
Main HEAD at handoff creation:
3767f8f19351873f85b66b4bc3aa3f36839096e1

Live Stock PR #7: merged
Merge commit:
2a895bbce1d50bb8b6177c7781c35f3edafb6915

Current dev tenant:
company_id=38
company_code=DEV-01
driver_id=26
user=مدير التطوير
warehouse_id=119
```

Live Stock batch يتضمن:

```text
- compact Live Stock UI
- tokenized flexible search
- cursor/infinite scroll
- family filter
- multi-filter
- mixed carton + each display
- SKU hidden in Live Stock
- dedicated Batches & Expiry page
- centralized bulk minimum-stock manager
- multi-family/product selection
- optional preview
- intuitive default update behavior
- RTL-stable minimum dialog
- improved terminology
- dynamic company currency display
- inventory i18n hardening
- rich demo data
- contract gates/tests
```

---

## 39) أهم شيء لا تنساه

لا تبدأ من ذاكرة عامة أو تخمين. هذا الملف يعطي السياق، لكن قبل أي Patch:

1. اسحب `main`.
2. افتح الملف الحقيقي.
3. افهم dependencies.
4. حدد root cause.
5. نفذ أصغر Patch صحيح.
6. اختبر.
7. لا تكسر Workflow الحالي.
