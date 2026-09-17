# Wanasah Distribution ERP — Full Handoff
## نقطة الاستلام الحالية: Stage 7.4

> **هذا الملف مخصص لفتح محادثة جديدة ومتابعة العمل من نفس النقطة بدون فقدان السياق.**
>
> أول شيء في المحادثة الجديدة: اقرأ هذا الملف بالكامل، ثم راجع النسخ الحالية من `AGENTS.md` و`.rules` من GitHub عند الـHEAD الحالي قبل أي تعديل. إذا تعارض هذا الملف مع الكود الحالي أو ملفات القواعد، فالكود الحالي وملفات القواعد هما المصدر الأعلى.

---

# 1) حالة المستودع الحالية — مهم جدًا

- المستودع: `MohHamdallah1/wanasah`
- المسار المحلي المعتاد:
  `C:\Users\admin\Desktop\wanasah`
- آخر نسخة مرفوعة على GitHub:
  - Commit message: `stage 7.4`
  - SHA: `9f2cec60fdbf65316e47b166cfcc935e74dcbde5`
- النسخة السابقة:
  - `stage 7.3`
  - SHA: `e7115af398478e6bc3fc639ec958f0fa276fe458`
- Stage 7.2:
  - SHA: `b0312351ee74f92b343a61d3afe16fddbcac24fe`

المستخدم أكد أنه رفع الوضع الحالي إلى GitHub باسم:

```bash
git commit -m "stage 7.4"
```

عند بداية المحادثة الجديدة، لا تعتمد على نسخ قديمة من الملفات. افحص الملفات المطلوبة مباشرة من commit `stage 7.4` أو الـHEAD الحالي.

---

# 2) بروتوكول العمل الإلزامي

هذه قواعد غير قابلة للتفاوض:

- `NO_GUESSING`
- `NO_SHORTCUTS`
- `NO_TECH_DEBT`
- `NO_BUSINESS_FLOW_CHANGE_WITHOUT_APPROVAL`
- `TENANT_ISOLATION=ABSOLUTE`
- `FAIL_CLOSED`
- لا تعديل على GitHub بدون موافقة صريحة.
- لا `commit` أو `push` بدون موافقة صريحة.
- ممنوع `git add .`
- أي staging مستقبلي يكون للملفات المحددة فقط.
- افحص النسخة الحالية الفعلية من الملفات قبل أي باتش.
- افحص العقود بين الملفات، وليس الملف المنفرد فقط.
- لا تدعي أن اختبارًا تم محليًا إلا إذا المستخدم أعطى نتيجته أو تم تنفيذه فعليًا بأداة متاحة.
- نجاح الاختبارات وحده ليس إثباتًا كافيًا لجودة المنطق.
- التعديلات جراحية فقط ولا يوجد تنسيق عشوائي لملفات كاملة.
- إذا فشل باتش: شخّص السبب الحقيقي أولًا، ولا ترسل نسخًا عمياء متتابعة.
- الباتش المطلوب عادة:
  - Fail-closed
  - preflight واضح
  - anchors دقيقة
  - atomic writes
  - success marker واضح
- لا تغيّر منطق العمل الحالي دون نقاش وموافقة المستخدم.
- التعقيد يذهب للباك إند، والواجهة تبقى بسيطة جدًا.

## قبل أي تعديل جديد

**إجباري:**

1. اقرأ `AGENTS.md` الحالية.
2. اقرأ `.rules` الحالية.
3. افحص الملفات المعنية في GitHub عند HEAD الحالي.
4. افحص العقود المتقاطعة المطلوبة.
5. بعدها فقط اقترح أو أنشئ الباتش.

لا تعتمد على ما تتذكره من ملفات القواعد؛ يجب مراجعتها مجددًا قبل كل دفعة تعديلات حقيقية.

---

# 3) أسلوب المستخدم المطلوب

المستخدم أردني ويتكلم عربي مباشر.

يفضل:

- إجابة قصيرة وواضحة.
- لا إطالة ولا تنظير.
- لا تكثر المصطلحات الإنجليزية بلا حاجة.
- إذا اضطررت لمصطلح تقني، اشرحه ببساطة.
- في التعديلات:
  - أعطه الزبدة.
  - ثم الأمر/الباتش الجاهز.
  - ثم أوامر الاختبار الدقيقة.
- لا تخلط الإنجليزي والعربي في واجهة المستخدم.
- يريد منتجًا بمستوى إنتاج حقيقي وليس نموذجًا تجريبيًا.
- أهم قاعدة UX عنده:
  **"لوحة التحكم بدها تكون غبية"**
  أي أن المستخدم لا يرى التعقيد؛ الباك إند يتحمله.

---

# 4) المشروع

نظام ERP / توزيع متعدد الشركات لشركات التوزيع الصغيرة والمتوسطة.

## التقنية

- Backend:
  - FastAPI
  - SQLAlchemy Async
  - PostgreSQL
  - Alembic
- Dashboard:
  - React
  - TypeScript
- تطبيق المندوب:
  - Flutter
- قاعدة البيانات:
  - Multi-company / multi-tenant
  - RLS وعزل الشركات مهم جدًا
- الأسعار والمخزون مبنيان بعقود دقيقة وتاريخ غير قابل للتلاعب.

الأولوية:

**الصحة المعمارية والمالية > سهولة تنفيذ الكود > التجميل.**

لكن الواجهة نفسها يجب أن تكون سهلة جدًا.

---

# 5) قواعد اللغات الدائمة — i18n

`i18n` = نظام دعم تعدد اللغات.

هذه قاعدة معمارية دائمة في المشروع، وليست خاصة بصفحة المنتجات.

كل ملف Frontend جديد أو يتم لمسه مستقبلًا:

- كل النصوص التي يراها المستخدم تستخدم مفاتيح ترجمة.
- لا نصوص hardcoded جديدة في React/TypeScript.
- العربية هي الافتراضية حاليًا.
- النظام يجب أن يدعم لغات أخرى دون إعادة كتابة منطق الأعمال.
- اتجاه RTL/LTR من اللغة الحالية.
- ممنوع `dir="rtl"` ثابت في الكود الجديد.
- الأرقام والعملات والتواريخ والأوقات عبر `Intl`.
- الأكواد والحالات ووحدات القياس داخل الباك إند تبقى محايدة لغويًا.
- أخطاء الباك إند تعتمد:
  - `code`
  - `context`
- الواجهة تترجم الخطأ.
- ممنوع أن يعتمد أي منطق على نص رسالة عربية أو إنجليزية.
- الاستيراد يمكن أن يقبل عناوين عربية/إنجليزية لكن يحولها لحقول Canonical.

هذه القواعد موجودة أيضًا في `.rules` و`AGENTS.md`.

---

# 6) قواعد الشبكة وعدم التكرار الدائمة

كل Mutation جديدة أو معدلة يجب أن تفترض أن:

> الخادم قد يكون نفذ العملية بالكامل لكن الرد ضاع بسبب انقطاع الشبكة.

لذلك:

- operation/request ID ثابت لكل عملية منطقية.
- نفس ID يُعاد عند:
  - timeout
  - انقطاع شبكة
  - refresh
  - ضياع الرد
- لا تنشئ ID جديدًا لمجرد أن الطلب فشل شبكيًا.
- إعادة نفس ID مع Payload مختلف = Fail Closed.
- لا queue صامتة في المتصفح لتنفيذ أوامر إدارة لاحقًا.
- المسودة تحفظ محليًا عند الحاجة.
- التنفيذ بعد عودة الشبكة يكون بإعادة محاولة صريحة من المستخدم.
- Background workers:
  - durable
  - resumable
  - bounded
  - tenant-safe
  - re-check authorization

---

# 7) خلفية التسعير التي يجب عدم كسرها

سعر البيع لم يعد موجودًا كحقل حي على `ProductVariant`.

المصدر الصحيح لسعر البيع هو:

- `PriceBook`
- `PriceBookEntry`
- Assignments / pricing resolver

## قرار تجربة المستخدم

المستخدم الطبيعي لا يجب أن يشعر أنه يتعامل مع Price Books.

شاشة إضافة المنتج تبقى:

- اسم المنتج
- العائلة
- نوع العبوة
- الكمية داخل العبوة
- سعر البيع
- الباركود
- إلخ

وخلف الكواليس السعر يذهب للـDefault Price Book.

## القرار النهائي حول الشركة الجديدة

عند إنشاء الشركة:

**ينشأ تلقائيًا Default Price Book فارغ.**

لا يتم إنشاء أسعار وهمية.

الفائدة:

- الشركة لديها مرجع سعر أساسي من البداية.
- أول منتج يُضاف بسعر، يجد مكانه تلقائيًا.
- المستخدم يرى فقط مفهوم:
  **السعر الأساسي**
  ولا يحتاج يفهم Price Book.

Stage 7.4 أضاف هذا في إنشاء الشركة.

الـGate الحالي يتأكد من وجود:

- `create_price_book`
- `create_assignment`
- `code="DEFAULT"`
- وعدم إنشاء fake `PriceBookEntry`.

## مستقبل التسعير المتقدم

قررنا مبدئيًا أن يكون هناك لاحقًا:

1. سعر أساسي للشركة.
2. سياسة مشتقة مثل:
   - كبار العملاء = خصم 10% عن السعر الأساسي.
3. Price Book مستقل فقط عندما تكون الأسعار مخصصة فعليًا لكل منتج.

لا تبنِ هذا الجزء المتقدم الآن دون قرار جديد من المستخدم.

---

# 8) Stage 7.3 — المنتجات المبسطة

Stage 7.3 سبق Stage 7.4 وهو مهم لفهم السياق.

## تجربة المنتج

داخل Products:

- إضافة منتج سريعة وبسيطة.
- SKU مخفي تمامًا.
- Product code داخلي مخفي.
- Product Family اختيار اختياري مع إمكانية إنشاء مباشرة.
- Families لها إدارة داخل Products.
- Advanced Pricing موجود داخل Products كخيار متقدم معطل/غير ظاهر كمسار طبيعي.
- ليس عنصر Sidebar مستقل.

## العبوات المدعومة

الأساس يبقى `EACH`.

Outer packages تشمل مثلًا:

- CARTON
- CASE
- PACK
- BAG
- SACK
- TRAY
- CRATE
- BUNDLE
- PALLET
- أو بدون عبوة خارجية.

## منطق سعر المنتج

إذا كان هناك عبوة:

- سعر العبوة فقط → اشتق سعر الوحدة.
- سعر الوحدة فقط → اشتق سعر العبوة.
- الاثنان موجودان → احفظهما كما أدخلهما المستخدم حتى لو لم يكونا متطابقين رياضيًا.
- الاثنان فارغان → Fail closed.

إذا بدون عبوة:

- unit price مطلوب.
- package price ممنوع.

## الباركود

- باركود الوحدة.
- باركود العبوة.
- زر يجعل باركود العبوة نفس باركود الوحدة.
- إذا كانا نفسهما لا تنشئ duplicate active barcode row.

## الاستيراد

- CSV/XLSX
- حتى 50,000 row معماريًا.
- Background worker.
- Durable jobs.
- Mapping مرن.
- عربي/إنجليزي.
- لا تخمين للأعمدة المبهمة.
- تقرير أخطاء CSV.
- retry/resume بدون إعادة الصفوف المنجزة.
- payload conflict guard على request ID.

---

# 9) Stage 7.4 — الهدف

Stage 7.4 بنى **منطق تكلفة المخزون** من قاعدة البيانات إلى الباك إند إلى شاشة التوريد.

أهم قرار:

**التكلفة لا توضع في صفحة تعريف المنتج.**

مكان التكلفة:

**التوريد / إدخال المخزون (Inbound)**

لأن تكلفة نفس المنتج قد تختلف بين كل شراء وآخر.

مثال:

- اليوم: 100 كرتونة × 10 دنانير.
- غدًا: 100 كرتونة × 12 دينار.

لا يجوز تعديل تكلفة قديمة.

يجب أن يحتفظ النظام بكل استلام وتكلفته تاريخيًا.

---

# 10) هوية الدفعة — نقطة مهمة جدًا

المستخدم كان مهتمًا بدقة الأرباح "بالملي".

## البصمة الحقيقية للدفعة

ليست `production_date`.

البصمة النظامية هي:

**`batch_id`**

ومعها بيانات مثل:

- batch number
- production date
- expiry date
- product variant

تاريخ الإنتاج مهم جدًا كمعلومة وتتبّع، لكنه ليس Identifier كافيًا وحده.

## عندما تنتقل البضاعة من المستودع إلى السيارة

المخزون الحالي يتتبع:

- الموقع
- المنتج
- الدفعة
- الحالة

لذلك عند نقل كمية من المستودع إلى السيارة تبقى الكمية مرتبطة بنفس `batch_id`.

## ماذا يحدث عند البيع؟

المندوب لا يختار دفعة.

ولا نريد Barcode scan لكل كرتونة.

الخادم يختار الدفعات من رصيد السيارة داخليًا حسب FEFO الفيزيائي.

مثال رصيد السيارة:

- Batch A: 6 كراتين.
- Batch B: 20 كرتونة.

المندوب يكتب فقط:

> بيع 10 كراتين.

الخادم يسجل Book Allocation:

- 6 من A
- 4 من B

لكن يجب فهم الحقيقة المهمة:

**بدون تسلسل/مسح لكل كرتونة أو فصل مادي صارم، لا نستطيع أن نثبت أن الكرتونة الفيزيائية التي أمسكها المندوب بيده كانت A أو B.**

النظام يضمن:

- دقة مخزنية
- دقة محاسبية
- توزيع Book Deterministic

ولا يدعي معرفة Physical Serial Identity غير الموجودة.

هذه قاعدة معمارية سجلناها أيضًا في `.rules` و`AGENTS.md`.

---

# 11) الفصل بين FEFO الفيزيائي والتكلفة المالية

هذا من أهم قرارات Stage 7.4.

هناك سلطتان مختلفتان:

## 1. المخزون الفيزيائي

يقرر أي Batch يخرج من الموقع.

السياسة الحالية:

**FEFO — الأقرب انتهاءً أولًا.**

هذه مرتبطة بالمخزون الفعلي والدفعة.

## 2. التكلفة المحاسبية

تحدد كم تكلفة البضاعة الخارجة ماليًا.

السياسة تكون للشركة:

- `MOVING_AVERAGE`
- أو `FIFO`

ولا يجوز خلط الاثنين.

### مهم جدًا

**Financial FIFO لا يجب ربطه قسرًا بالـPhysical FEFO batch.**

أي:

- FEFO يقول من أي دفعة مخزنية خرجت البضاعة.
- FIFO المالي يستهلك طبقات تكلفة الشراء حسب ترتيب الاستحواذ المالي.

وهذا بالضبط سبب وجود طبقات تكلفة مستقلة.

---

# 12) طرق التكلفة

الشركة تختار قبل أول توريد فعلي مقيّم:

### Moving Average

متوسط التكلفة المتحرك.

مثال:

- 100 × 10
- 100 × 12

الرصيد:

- الكمية = 200
- القيمة = 2200
- المتوسط = 11

كل خروج بعد ذلك يأخذ متوسط التكلفة الحالي حسب السياسة.

### FIFO

الوارد أولًا يخرج أولًا ماليًا.

يتم الاحتفاظ بطبقات تكلفة لكل استلام.

كل خروج يستهلك أقدم طبقات التكلفة المتبقية.

## التثبيت

- الشركة تختار الطريقة قبل أول Costed Supplier Receipt.
- عند أول توريد مقيّم:
  - السياسة تصبح Active.
  - الطريقة تُقفل.
- لا تغيير عشوائي بعد وجود تاريخ مالي.

الافتراضي للشركة الجديدة:

**MOVING_AVERAGE**

Stage 7.4 يهيئ Default Cost Policy عند إنشاء الشركة.

---

# 13) جداول Stage 7.4 الجديدة

Stage 7.4 أضاف أساس التكلفة الدائمة، ومن ضمنه:

- `InventoryCostPolicy`
- `InventoryCostState`
- `InventoryCostEvent`
- `InventoryCostLayer`
- `InventoryCostAllocation`

Alembic migration:

`wa_backend/alembic/versions/fa7c9d3e1b24_stage74_inventory_costing.py`

Revision:

`fa7c9d3e1b24`

Parent:

`f9d2b4c6a8e1`

## الهدف

### InventoryCostPolicy
طريقة التكلفة للشركة وحالة القفل.

### InventoryCostState
الرصيد المالي الحي للصنف على مستوى الشركة:

- quantity
- inventory value
- average unit cost

### InventoryCostEvent
أثر مالي تاريخي مرتبط بحركة مخزون.

يجب أن يكون Append-only / immutable evidence.

### InventoryCostLayer
طبقات الشراء المستخدمة في FIFO.

### InventoryCostAllocation
تفصيل استهلاك أو استرجاع الطبقات.

---

# 14) عزل الشركات وحماية التاريخ

Stage 7.4 يجب أن يحافظ على:

- RLS
- FORCE RLS
- Foreign keys tenant-safe
- عدم تعديل التاريخ المالي.
- Runtime permissions مقيدة.
- لا cross-tenant access.

الـMigration تحتوي حماية تمنع تعديل/حذف تاريخ التكلفة.

المحرك يجب أن يفشل إذا رصيد التكلفة لا يتطابق مع الكمية الفيزيائية بدل أن يكمل بصمت.

Error code مهم:

`INVENTORY_COST_RECONCILIATION_FAILED`

---

# 15) التوريد بعد Stage 7.4

واجهة Inbound الآن تشمل:

- المنتج
- رقم الدفعة
- تاريخ الإنتاج
- تاريخ الصلاحية
- الكمية
- وحدة الشراء
- تكلفة الشراء للوحدة المختارة
- رقم الفاتورة/المرجع
- ملاحظات

مثال:

100 كرتونة × 10.250 د.أ

إذا الكرتونة 50 حبة:

- الإدخال يبقى مفهومًا للمستخدم بالكرتونة.
- الباك إند يحول الكمية للوحدة الأساسية.
- لكنه يحفظ:
  - وحدة الشراء
  - كمية الشراء
  - سعر وحدة الشراء
  - total actual cost
  - base quantity
  - cost evidence

لا تخزن تكلفة حية على `ProductVariant`.

---

# 16) نقطة تاريخ الإنتاج — Follow-up مهم

المستخدم يرى أن كل Supplier Batch عمليًا يجب أن يكون له تاريخ إنتاج، ويريد استخدامه في التتبع.

لكن في commit `stage 7.4` الحالي، عقد Frontend يسمح:

`production_date: string | null`

أي أنه حاليًا ليس مفروضًا عالميًا من عقد الواجهة.

قبل اعتبار Stage 7.4 مغلقًا نهائيًا:

**راجع backend + product batch policy وحدد إن كان تاريخ الإنتاج يجب أن يصبح Required لكل Supplier Inbound أم يبقى حسب نوع المنتج/السياسة.**

لا تغيّر هذا بصمت.

ناقشه مع المستخدم إذا احتاج تغيير Business Rule.

تاريخ الإنتاج يبقى Metadata مهمًا، لكنه لا يحل وحده مشكلة Physical Carton Identity بدون scan/segregation.

---

# 17) البيع والعينات والمكافآت

تم اكتشاف قبل Stage 7.4 أن:

البيع والعينات كانا يجتمعان مخزنيًا داخل:

`VISIT_ITEM_OUT`

وهذا لا يكفي لتقارير الربح الدقيقة.

المستخدم وافق على الإصلاح.

## القرار

- البيع:
  `VISIT_ITEM_OUT`
- العينات:
  `VISIT_SAMPLE_OUT`
- المكافآت:
  `VISIT_REWARD_OUT`
- الاستبدال:
  له مرجعه المنفصل الموجود في التدفق.

المندوب لا يرى هذا التعقيد.

هو فقط يدخل العملية بطريقة بسيطة.

الانفصال داخل الباك إند لكي نستطيع التفريق بين:

- إيراد حقيقي
- Sample expense
- Offer/reward cost
- Exchange cost

---

# 18) سعر البيع مقابل تكلفة البيع

لا تربط الدفعة بسعر بيع ثابت.

نفس الدفعة يمكن أن تباع:

- اليوم بسعر 10
- غدًا 9.5 بسبب عرض
- لعميل آخر 11

لذلك يجب وجود سلطتين منفصلتين:

## Revenue evidence
سعر البيع الفعلي للعملية بعد تطبيق:

- Price resolution
- عروض
- خصومات
- ضرائب
- rounding

Stage 6 لديه Financial/Sales evidence immutable.

## Cost evidence
تكلفة البضاعة الخارجة من Stage 7.4.

بالتالي الربح:

**صافي البيع - تكلفة البضاعة المباعة**

والتقارير مستقبلًا يمكن أن تبني:

- ربح الفاتورة
- ربح المنتج
- ربح العميل
- ربح المندوب
- ربح اليوم
- ربح الدفعة/المخزون عند الحاجة

---

# 19) التحويلات الداخلية

نقل البضاعة:

- مستودع → سيارة
- مستودع → مستودع

لا يعتبر بيعًا.

ولا يجب أن ينشئ COGS.

ولا يغيّر قيمة مخزون الشركة.

هو فقط يحرك Physical Inventory مع الحفاظ على هوية الدفعة.

هذه قاعدة Stage 7.4 دائمة.

---

# 20) المرتجعات وعكس الحركات

إذا تم عكس خروج قديم:

لا تستخدم تكلفة اليوم.

يجب استرجاع:

**التكلفة التاريخية نفسها التي خرجت أصلًا.**

Stage 7.4 يربط reversal بالأثر المالي الأصلي.

مهم خصوصًا مع FIFO حتى تعود الطبقات الأصلية بشكل صحيح.

---

# 21) حالة عجز المندوب

هناك فرق يجب الحفاظ عليه مستقبلاً بين:

1. خسارة الشركة المحاسبية:
   - تقاس بالتكلفة.

2. المسؤولية التي قد تحمّل على المندوب:
   - حسب سياسة الشركة.
   - قد تكون بالتكلفة أو بسعر بيع أو قاعدة أخرى.

الحقل المالي التاريخي الموجود سابقًا لـ`DRIVER_SHORTAGE` ليس محرك التكلفة العام، ولا يجوز إعادة استخدامه ليحل محل Stage 7.4.

---

# 22) ملفات Stage 7.4 المعدلة

الباتش النهائي V2 طبق بنجاح وأعلن الملفات التالية:

```text
.rules
AGENTS.md
dashboard/src/i18n/resources.ts
dashboard/src/pages/inventory/Tab2Inbound.tsx
dashboard/src/pages/inventory/inbound/contracts.ts
wa_backend/alembic/versions/fa7c9d3e1b24_stage74_inventory_costing.py
wa_backend/api/dispatch.py
wa_backend/api/driver.py
wa_backend/api/platform_manager.py
wa_backend/api/warehouse.py
wa_backend/db_manager.py
wa_backend/domains/inventory_costing/__init__.py
wa_backend/domains/inventory_costing/service.py
wa_backend/inventory_access.py
wa_backend/models.py
wa_backend/schemas.py
wa_backend/scripts/gate_stage74_inventory_costing.py
wa_backend/services.py
```

أي تدقيق Stage 7.4 يجب أن يبدأ بهذه الملفات وعقودها.

---

# 23) الصلاحية الجديدة

Stage 7.4 أضاف:

`inventory.costing.manage`

وهي Company-level permission.

في commit `stage 7.4` الحالي، `inventory_access.py` يحتويها فعلًا في:

- `PERMISSIONS`
- `COMPANY_ONLY`

---

# 24) تاريخ مشاكل باتش Stage 7.4 — لا تعيدها

عدة مشاكل حصلت أثناء تطبيق Stage 7.4 وتم إصلاحها.

## المشكلة 1 — Baseline hash

الباتش الأول خلط بين:

- Git blob SHA-1
- SHA-256 / working tree
- واختلاف CRLF على Windows

فشل عند `.rules`.

تم لاحقًا إنتاج V2 يستخدم committed Git baseline بطريقة آمنة.

**لا تعيد مصححات baseline القديمة.**

## المشكلة 2 — Driver range anchor

المرساة:

`if resolved_sale is not None:`

كانت موجودة أكثر من مرة.

الباتش الأول فشل:

`driver sale/sample split: range anchors are not unique`

V2 استخدم سياقًا فريدًا حول immutable sales evidence.

**لا تعيد مصحح driver anchors القديم.**

## المشكلة 3 — Cost permission gate

أول تشغيل للـStage 7.4 gate أعطى:

```text
CHECKS=48
FAILURES=1
FAIL: cost method permission
STAGE74_INVENTORY_COSTING_GATE=FAIL
```

السبب كان False Negative في الـGate:

كان الفحص يبحث عن quoting محدد بدل مجرد وجود:

`inventory.costing.manage`

تم تعديل الـGate.

في commit `stage 7.4` الحالي، الفحص أصبح:

```python
check("inventory.costing.manage" in access, "cost method permission")
```

و`inventory_access.py` فعلًا يحتوي الصلاحية.

**إذن لا تعيد إصلاح gate قديم؛ فقط أعد تشغيله على commit Stage 7.4 الحالي.**

---

# 25) حالة الاختبارات الحالية

المستخدم شغل الباتش النهائي:

```powershell
python .\apply_stage74_inventory_costing_v2.py
```

والناتج:

```text
STAGE74_INVENTORY_COSTING_APPLIED_OK
```

ثم بدأ تسلسل الفحوصات.

المستخدم وصل إلى Stage 7.4 gate، ما يعني أن الخطوات السابقة حتى هذه النقطة مرّت حسب تقريره، ومنها:

- `git diff --check`
- Dashboard build
- Python compile checks
- Alembic upgrade head

ثم Stage 7.4 gate فشل بفحص واحد فقط كما ورد أعلاه.

بعدها تم إصلاح الـGate ورفع الوضع الحالي كله على GitHub في commit:

`9f2cec60fdbf65316e47b166cfcc935e74dcbde5`

## نقطة الاستئناف الدقيقة في المحادثة الجديدة

أول أمر تنفيذي يجب أن يكون:

```powershell
cd C:\Users\admin\Desktop\wanasah\wa_backend
python .\scripts\gate_stage74_inventory_costing.py
```

المتوقع:

```text
CHECKS=48
FAILURES=0
STAGE74_INVENTORY_COSTING_GATE=PASS
```

إذا فشل:
- توقف.
- افحص النسخة الحالية من الملف من GitHub.
- لا تخمّن.
- لا تكمل باقي الاختبارات.

---

# 26) الاختبارات التالية بعد PASS لـStage 7.4

إذا Stage 7.4 gate أصبح PASS، شغل regression gates:

```powershell
python .\scripts\gate_stage4_batch_expiry.py
python .\scripts\gate_stage4_final.py
python .\scripts\gate_stage6_return_reversal.py
python .\scripts\gate_stage6_financial_snapshots.py
python .\scripts\gate_stage6_offer_tax_snapshot.py
python .\scripts\gate_pricing_offer_interaction.py
python .\scripts\gate_stage7_simple_products.py
python .\scripts\gate_stage73_product_ux_i18n_network.py
```

عند أول فشل:
- توقف.
- شخّص السبب.
- لا تعتبره تلقائيًا خطأ حقيقيًا؛ قد يكون Gate stale مثل ما حدث سابقًا.
- لكن لا تعدل gate إلا بعد إثبات أنه false negative.

بعدها:

```powershell
cd ..
git diff --check
git status --short
```

بما أن المستخدم رفع `stage 7.4` بالفعل، قد يكون status نظيفًا حاليًا ما لم تحصل تعديلات جديدة بعد commit.

---

# 27) E2E المطلوبة بعد الـGates

لا تعتبر Stage 7.4 منتهية بمجرد مرور الاختبارات النصية.

نحتاج اختبار واقعي.

## Company provisioning

- إنشاء شركة جديدة.
- التأكد أن Default Price Book الفارغ ينشأ.
- التأكد أن Default Cost Policy ينشأ.
- لا fake price entries.

## Product + price

- إنشاء منتج.
- إدخال سعر بيع.
- التأكد أنه يذهب للسعر الأساسي الداخلي.

## Inbound — Moving Average

مثال:

1. توريد 100 كرتونة بسعر 10.
2. توريد 100 كرتونة بسعر 12.
3. تحقق من:
   - الكمية
   - إجمالي قيمة المخزون
   - المتوسط
4. المتوقع حسابيًا:
   - الرصيد = 200
   - القيمة = 2200
   - المتوسط = 11
   بعد توحيد الوحدات بالشكل الصحيح.

## وحدات الشراء

اختبر:

- EACH
- CARTON/CASE أو أي UOM مسموحة للصنف.

وتأكد أن:

- المستخدم يدخل تكلفة وحدة الشراء.
- الخادم يحول الكمية للـBase UOM.
- التاريخ المالي يحتفظ بوحدة الشراء الأصلية.

## Batch identity

- توريد نفس المنتج بأكثر من Batch.
- نقل أجزاء من الدفعتين للسيارة.
- تحقق أن السيارة تحتفظ بأرصدة الدفعات.
- بيع بدون أن يختار المندوب Batch.
- تأكد أن FEFO الداخلي يقسم الخروج حسب الرصيد.

## Sale vs Sample

عملية فيها:

- بيع
- عينة

تأكد أن:

- البيع يخرج `VISIT_ITEM_OUT`
- العينة تخرج `VISIT_SAMPLE_OUT`
- التكلفة المالية لكل خروج موجودة.
- Sales evidence يبقى صحيحًا.
- لا تُعامل العينة كإيراد.

## Rewards

اختبر عرض فيه مكافأة:

- `VISIT_REWARD_OUT`
- Cost evidence موجود.
- لا يوجد Revenue وهمي للمكافأة.

## Internal transfer

- مستودع → سيارة.
- لا COGS.
- لا تغيير لقيمة الشركة.
- Batch identity محفوظة.

## Reversal

- بيع ثم Correction/Reversal.
- يجب أن تعود التكلفة التاريخية الأصلية.
- FIFO layers تعود كما يجب.

## FIFO scenario

شركة جديدة أو بيئة اختبار قبل أول توريد:

- اختر FIFO.
- توريد بتكلفة 10.
- توريد بتكلفة 12.
- بيع جزء.
- تحقق أن الطبقات الأقدم تُستهلك ماليًا أولًا.
- لا تربط Financial FIFO بالـPhysical FEFO batch قسرًا.

## Network/idempotency

- أرسل توريد بنفس `request_id` ونفس payload مرتين:
  - لا duplicate.
- نفس `request_id` مع payload مختلف:
  - Fail Closed.
- simulate lost response:
  - retry بنفس request ID.

## Tenant isolation

- شركة A لا ترى/تعدل Cost policy أو layers أو events لشركة B.

---

# 28) ملاحظات Stage 7.3 التي يجب الحفاظ عليها أثناء Stage 7.4

لا تخرب:

- Simple Products facade.
- UOM behavior.
- shared barcodes.
- import jobs.
- family management.
- durable product drafts.
- active import recovery.
- i18n.
- network error semantics.
- `ACCOUNT_DISABLED` stable code.
- no browser mutation queue.

Stage 7.4 لم يكن تصريحًا لإعادة تصميم المنتجات.

---

# 29) Stage 6 — أساس مالي لا يجوز كسره

Stage 6 بنى:

- Typed offer engine.
- Tax versions.
- calculation order.
- line evidence.
- immutable financial snapshots.
- return reversal evidence.

ترتيب الحساب:

```text
base/resolved price
→ offers/discounts/rewards
→ taxable base/tax
→ currency rounding
→ tax component reconciliation
→ header reconciliation
```

الأموال الحساسة تستخدم دقة عالية داخليًا (`NUMERIC(20,6)` في الأجزاء المعنية).

Stage 7.4 يجب أن يضيف COGS/cost evidence، لا أن يعيد اختراع Revenue calculation.

---

# 30) مفهوم الربح المستقبلي

المطلوب مستقبلًا:

```text
Gross Profit = Net Revenue - COGS
```

لكن:

- Revenue يأتي من Sales/Financial Evidence.
- COGS يأتي من Inventory Cost Events.
- العينات والمكافآت ليست Revenue.
- Internal transfers ليست COGS.
- Driver shortage له سياسة مسؤولية منفصلة عن قيمة خسارة المخزون.

لا تخلط هذه السلطات.

---

# 31) الأشياء غير المطلوبة حاليًا

لا تضف من نفسك:

- Serial لكل كرتونة.
- Barcode scan إجباري عند البيع.
- اختيار Batch يدوي للمندوب.
- تكلفة داخل Product page.
- تكلفة داخل `ProductVariant`.
- تغيير سياسة التكلفة بعد أول توريد.
- Queue متصفح خفية.
- Price list UI معقد للمستخدم الطبيعي.
- KG/L driver-sale contract بدون إعادة تصميم واعتماد واضح.

---

# 32) موضوع KG/L

في Stage 7.3 تم تأجيل KG/L الحقيقي لأن Driver mobile contract ما زال يعتمد كميات صحيحة carton/pack/base.

لا تدّع دعم weighted/liquid sale end-to-end ما لم يتم تعميم:

- driver sale input
- Flutter
- inventory quantity
- UOM conversions
- sales calculation

هذا لم يكن جزءًا من Stage 7.4.

---

# 33) ماذا تفعل المحادثة الجديدة فورًا؟

التسلسل الصحيح:

1. اقرأ هذا الملف كاملًا.
2. افتح GitHub repo `MohHamdallah1/wanasah`.
3. تأكد من HEAD:
   `9f2cec60fdbf65316e47b166cfcc935e74dcbde5`
   أو أحدث إذا المستخدم قال إنه رفع نسخة جديدة.
4. اقرأ:
   - `AGENTS.md`
   - `.rules`
5. افحص:
   - `wa_backend/scripts/gate_stage74_inventory_costing.py`
   - `wa_backend/inventory_access.py`
6. لا تعدل شيئًا.
7. اطلب/استخدم نتيجة إعادة تشغيل:
   ```powershell
   python .\scripts\gate_stage74_inventory_costing.py
   ```
8. إذا PASS:
   أكمل regression gates المحددة أعلاه.
9. بعدها E2E.
10. لا commit/push جديد إلا بعد موافقة المستخدم.

---

# 34) تذكير خاص بالمحادثة الجديدة

المستخدم يريد الاستمرار فورًا، وليس إعادة نقاش القرارات من الصفر.

لا تسأله مجددًا:

- أين نضع التكلفة؟
- هل السعر الافتراضي يحتاج Price Book؟
- هل المندوب يختار Batch؟
- هل نستخدم Scan؟
- Moving Average أم FIFO؟
- هل العينات تنفصل عن البيع؟

القرارات الحالية:

- التكلفة في Inbound.
- Default empty price book عند إنشاء الشركة.
- المندوب لا يختار Batch.
- لا Scan إجباري.
- Physical FEFO داخلي.
- Company costing method = Moving Average أو FIFO قبل أول توريد.
- Default = Moving Average.
- الطريقة تقفل بعد أول costed receipt.
- بيع وعينات منفصلان ماليًا/مخزنيًا.
- Financial FIFO منفصل عن Physical FEFO.
- Internal transfer لا ينشئ COGS.
- كل الاستلامات تحتفظ بتكلفتها التاريخية.

---

# 35) آخر نقطة كلامية وصلنا لها

المستخدم سأل عن معنى `i18n` وتم توضيح أنه دعم تعدد اللغات.

ثم نتيجة الاختبار كانت:

```text
CHECKS=48
FAILURES=1
FAIL: cost method permission
STAGE74_INVENTORY_COSTING_GATE=FAIL
```

تم تشخيصها False Negative في الـGate نفسه.

النسخة الحالية المرفوعة `stage 7.4` تحتوي الفحص المصحح:

```python
check("inventory.costing.manage" in access, "cost method permission")
```

و`inventory_access.py` يحتوي:

```python
'inventory.costing.manage'
```

لذلك **نقطة العمل التالية ليست باتشًا جديدًا**.

نقطة العمل التالية:

**إعادة تشغيل Stage 7.4 gate على commit الحالي.**

---

# 36) قاعدة أخيرة

إذا ظهر أي فشل جديد:

- لا تفترض أنه حقيقي.
- لا تفترض أنه Gate stale.
- افحص الاثنين.
- اربط الخطأ بالكود الحالي.
- شخّص الأثر الجانبي.
- أصلح السبب الحقيقي فقط.
- لا تضف دين تقني.
- لا تغيّر Business Flow بدون موافقة.

هذا المشروع يُعامل كنظام إنتاج حقيقي.
