# Phase 19.3–19.5: browser acceptance — 2026-10-01

الفرع: `hardening/v1-import-phase19-browser-acceptance-codex`.
المجلد الوحيد للتعديل: `C:\Users\admin\Desktop\wanasah-codex-D7S`.
الأساس: `origin/main 7a9fee93d50ed69e5aa82e26e14afe3327ad1d0e`.

## حدود الدليل

تم تشغيل **Edge الحقيقي** (النسخة المثبتة 154.0.4258.37)، بصفحة مستقلة
`http://127.0.0.1:5187/phase19-browser.html`، وبقياس هاتف 390×844 بالإضافة إلى سطح المكتب.
المكوّن المعروض هو **ProductsPage الأصلي**، مع Modal والقوائم وhooks والـCSS والترجمة
وuseAuthFetch وReact Query وdurableOperations الأصلية. لا توجد نسخة بديلة من محرر الصفوف.

استجابات HTTP **صناعية في الذاكرة** عبر Vite middleware محدود، وليست Backend Wanasah.
شركة A=91001، شركة B=91002، المستخدم=91011؛ أسماء وقيم وUUIDs صناعية فقط.
مدخل القبول يرفض التشغيل خارج المنفذ المحدد أو دون علم `VITE_BROWSER_ACCEPTANCE=synthetic-only`.
الخادم مربوط بـ127.0.0.1 مع strictPort، بلا Proxy أو قاعدة أو Queue أو Worker.
CSP يقصر الاتصالات على العنوان نفسه؛ API URL محدد للـfixture وSentry معطل.
المسارات غير المدعومة تفشل بـ501 ولا تُحوّل إلى خادم آخر. مدخل القبول ليس ضمن entry الإنتاج،
وفُحصت مخرجات البناء لغياب النصوص/حارس التشغيل الصناعي.

لم تُستخدم ملفات Excel الخاصة بالمستخدم، ولم يُرفع أي ملف، ولم تُستخدم قاعدة التطوير القديمة
أو الصفحة القائمة على المنفذ 8080، ولم يعمل اختبار 50 ألف أو D7-S أو Benchmark.
تبديل الهوية هنا يتم من أدوات fixture، دون إعادة تركيب ProductsPage عند تغيير الشركة؛
دخول الحساب الحقيقي واختيار الشركة من shell الإنتاج ليسا ضمن هذا الدليل.

## تحليل المصدر والإصلاحات المحدودة

| السبب المثبت | الدليل قبل الإصلاح | الإصلاح والأثر |
|---|---|---|
| ProductsAddMenu ينفذ onOpenImport في onSelect قبل انتهاء استرجاع Radix للتركيز | النافذة ظاهرة لكن activeElement هو زر Import file خلفها | تأجيل الفتح إلى microtask بعد onCloseAutoFocus، مثل النمط الموجود في CatalogToolsMenu. يدخل التركيز إلى Close ويعود إلى زر الاستيراد عند الإغلاق. |
| useDialogFocusTrap لا يحترم defaultPrevented | Escape على تلميح سبب الخطأ يغلق التلميح ونافذة الاستيراد معًا | احترام الحدث الذي عالجته الطبقة الداخلية في capture phase؛ Escape الأول يغلق التلميح/Popover فقط، والثاني يغلق النافذة. |
| ProductPackagingHelp يستخدم Tooltip لا يفتح بالنقر | النقر على شرح العبوة بقياس الهاتف لم يعرض الشرح | استخدام Popover الأصلي القابل للنقر وEnter، بالنصوص والمفاتيح نفسها واتجاه اللغة. |
| ارتفاع شرح العبوة أكبر من المساحة المتاحة أعلى زرّه | القياس الإنجليزي بعد اكتمال الحركة: top=-18px، height=450.6px | حد الارتفاع هو min(70vh, Radix available height) مع collisionPadding=8 وتمرير داخلي. بعد الإصلاح top=8px، height=424.4px، دون اقتطاع أول سطر. |
| إعادة ضبط الهوية الحالية تمس defaults ولا تمس job/status/open في الاستيراد | الشركة B تعرض إيصال 2 نجاح/1 رفض الخاص بالشركة A؛ GET الصفوف في B يفشل بأمان، والـACK المتأخر لا يغيّر B لكن الإيصال القديم يبقى | حجب open/job/status من أول render عند تغيّر company أو actor، ثم تصفير حالة النافذة قبل استعادة جلسة الهوية الجديدة. لا حذف لمسودات أو durable commands الخاصة بالهوية السابقة، ولا إلغاء صامت للمهمة على الخادم. |
| إشعار اكتمال polling غير مربوط بعمر عرض المهمة | بعد إغلاق نتيجة A أثناء تبديل الشركة بقي إشعارها ظاهرًا في B مؤقتًا | الاحتفاظ بمعرّف إشعار هذه المهمة وإزالته وحده عند تنظيف effect؛ لا إزالة لإشعارات المهام الأخرى. |

لم يتغير Backend أو Business Logic أو الأسعار أو صلاحيات الخادم أو التدقيق أو RLS أو SourceStore.
خدمة التصحيح وآلية request_id الأصلية لم تتغير. Tooltip أسباب أخطاء الصفوف بقي كما هو،
والرسائل المرئية المرتبطة بالحقول بقيت ظاهرة دون Hover.
القيم المرسلة ما زالت patches للخلايا المعدلة فقط، مع job/row versions وهوية الصف الأصلية.

ملاحظة مصدر لم تتحول إلى إصلاح تخميني: محدد حبس التركيز يجمع عناصر مخفية ولا يضم summary؛
لم يثبت هذا الفحص خللًا إضافيًا منه في حدود Tab/Shift+Tab المطلوبة، ولذلك لم يُعاد بناؤه.

## سجل القبول في Edge

PASS هنا يعني سلوك الواجهة الحقيقية على الاستجابات الصناعية فقط.

| الحالة | النتيجة النهائية | الدليل |
|---|---|---|
| العربية RTL على سطح المكتب والهاتف | PASS | html lang=ar وdir=rtl؛ الصف 14 ورسالة «اسم المنتج مطلوب» مرئيان، باركود 000123 محفوظ. [صورة RTL](PHASE19_BROWSER_RTL_MOBILE.png) |
| الإنجليزية LTR على سطح المكتب والهاتف | PASS | lang=en وdir=ltr؛ الشرح والجدول داخل حدود الشاشة. [صورة LTR](PHASE19_BROWSER_LTR_MOBILE.png) |
| الهاتف 390×844 | PASS للعرض المتجاوب | scrollWidth=375 ≤ innerWidth=390؛ نافذة التصحيح x=8, width=359.2, top=8, bottom=836؛ عرض البطاقات بدل جدول سطح المكتب. ليس دليل جهاز لمس فعلي. |
| فتح القائمة بلوحة المفاتيح | PASS بعد الإصلاح | ArrowDown ينقل التركيز إلى عنصر القائمة؛ Enter يفتح الاستيراد ويركز Close. |
| Escape وإرجاع التركيز | PASS بعد الإصلاح | Escape من عنصر قائمة Catalog tools يعيد التركيز إلى الزر؛ Escape من نافذة الاستيراد يعيده إلى Import file. |
| Tab وShift+Tab | PASS | Catalog tools → Tab → Refresh → Shift+Tab → Catalog tools. داخل الاستيراد: Shift+Tab من Close يصل إلى اختيار ملف التصحيح؛ Tab منه يعود إلى Close، دون الخروج إلى الخلفية. |
| سبب الخطأ دون Hover | PASS | رسالة الخطأ ظاهرة في summary المغلق وفي حقل الاسم المفتوح، والتلميح يُفتح بالتركيز. Escape يغلق التلميح ويبقي النافذة. |
| تحرير صف واحد بالعربية | PASS | استعادة «منتج معدل 000123» بعد reload ثم إرسال patch واحد لنفس job؛ request_id=eae7532a-272f-4faa-acf3-147969fd2a61. |
| تحرير 25 صفًا | PASS | 25 details للصفوف 14–38، تم تحرير أسماء جميع الصفوف ثم إرسال POST واحد، 25 patches، job_version=7 وrow_version=3. لا إرسال للباركود أو السعر غير المعدل. [دليل HTTP](PHASE19_BROWSER_HTTP_EVIDENCE.json) |
| تجاوز 25: عدد رفض 26 | PASS لتحويل الواجهة | لا details أو حقول تحرير مباشرة ولا زر حفظ مباشر؛ شرح التصحيح المجمع وزر Excel موجودان. [صورة الحد](PHASE19_BROWSER_EXCEL_BOUNDARY.png) |
| حفظ المسودة واستعادتها | PASS | reload حقيقي للمتصفح، استعادة المهمة ثم القيمة العربية والعدد «1 صف معدل» قبل الإرسال. |
| تبديل الشركة أثناء POST معلّق | PASS بعد الإصلاح | تعليق الرد، A→B دون remount للصفحة، اختفاء نافذة A ونتيجتها، وإشعارها، ثم release للرد دون إحيائها. أُثبت pending=1 قبل التبديل وpending=0 بعد الرد؛ لا POST في B ولا قراءة لمهمة A من B في إعادة الفحص النهائية. [قبل](PHASE19_BROWSER_COMPANY_BEFORE.png)، [بعد](PHASE19_BROWSER_COMPANY_AFTER.png) |
| عرض الصلاحيات والأسعار | PASS للعقد الصناعي | admin: الاستيراد والأسعار؛ restricted: لا إضافة/استيراد ولا أسعار، وأدواته Customize view فقط؛ viewer: الأسعار دون استيراد؛ operator (manage/publish/pricing.manage دون pricing.view): الاستيراد دون أعمدة الأسعار. لم تتغير deriveProductsCapabilities. |
| إرشادات التعبئة | PASS بعد الإصلاح | النقر بالعربية وEnter بالإنجليزية يفتحان معنى الوحدة الأساسية والتجميع الخارجي وبدون عبوة والأمثلة الثلاثة؛ Escape يعيد التركيز إلى زر الشرح ويبقي الاستيراد. |
| إيصال نتائج الاستيراد | PASS للعرض | 2 محفوظة مقابل 1/25/26 مرفوضة، ثم بعد ACK صناعي وpolling: 3/27 بنجاح؛ العودة للقائمة تعرض Last import result مع إرشاد الفلاتر. هذه أرقام fixture وليست إثبات حفظ DB. |

النتائج الأولية FAIL للتركيز، Escape، فتح الشرح بالنقر، اقتطاع الشرح، وبقاء نتيجة الشركة السابقة وإشعارها
أعيد فحصها بعد إصلاح المصدر وأصبحت PASS ضمن الحدود أعلاه.

## الفحوص المركزة

- Vitest: **4/4 PASS** في `product-import-browser-regressions-p19.test.tsx`، مدة 6.03 ثانية.
  عقد Escape المعالج مسبقًا ثم إغلاق النافذة واستعادة التركيز؛ تنظيف إشعار المهمة وحده عند تبديل الشركة؛ تبديل الشركة؛ تبديل المستخدم،
  والحفاظ على مفاتيح المسودة والطلب القديم واستعادة جلسة الهوية الجديدة فقط.
- TypeScript `tsconfig.app.json --noEmit`: PASS.
- ESLint للملفات المعدلة فقط مع `--max-warnings=0`: PASS.
- بناء Vite للإنتاج: PASS، 2765 modules؛ آخر بناء 15.20 ثانية.
- `git diff --check`: PASS؛ لا تغييرات في خطة الاستيراد أو Backend.

محاولات تركيب قائمة Radix مع dialog في JSDOM تجاوزت المهلة ولم تُحتسب PASS.
اختبارات الرجوع النهائية تعزل عقد hook/الهوية، بينما القوائم وModal وPopover الأصلية
فُحصت في Edge. لم تُستبدل أدلة المتصفح بمحاكاة DOM.

## البنود OPEN

| البند | سبب بقائه مفتوحًا |
|---|---|
| التصحيح عبر Backend فعلي وحفظ Product/Variant/Price/Audit | هذا تشغيل واجهة صناعية، بلا PostgreSQL أو Queue/Worker؛ استجابة COMPLETED مولّدة وليست إثبات حفظ. |
| تنزيل/تعديل/رفع ملف Excel الرسمي فعليًا | ثُبت تحويل الواجهة إلى مسار Excel فقط. artifact/download/upload غير مقلدة داخل fixture؛ تتطلب Backend معزولًا حقيقيًا. |
| صلاحيات JWT وRLS وتكرار request_id/تعارض النسخ من الخادم | fixture لا يحقق السلطات أو ledger؛ إثباتها يحتاج بيئة قبول Backend منفصلة. |
| جلسة realtime مصادق عليها واختيار الشركة من shell الإنتاج | HTTP polling/الهوية الصناعية فُحصا؛ WebSocket الحقيقي وshell لم يُشغلا. |
| جهاز هاتف لمس فعلي ومتصفحات/مقاسات أخرى | الدليل الحالي Edge الحقيقي بقياس viewport 390×844 فقط. |
| إغلاق بوابة إصدار Phase 19.5 كاملة أو قبول 50 ألف | لم يُنفذا ولم تُعدل علاماتهما في الخطة. |

## الملفات وطريقة إعادة الفحص

الكود الإنتاجي المعدل (خمسة ملفات فقط):
`dashboard/src/hooks/useDialogFocusTrap.ts`،
`dashboard/src/pages/products/header/ProductsAddMenu.tsx`،
`dashboard/src/pages/products/import/useImportProductWorkflow.ts`،
`dashboard/src/pages/products/import/useImportProductPolling.ts`،
`dashboard/src/pages/products/shared/ProductPackagingHelp.tsx`.

القبول المعزول:
`dashboard/phase19-browser.html`،
`dashboard/vite.browser-acceptance.config.ts`،
`dashboard/src/test/phase19-browser-fixture.tsx`.
الاختبارات: `dashboard/src/test/product-import-browser-regressions-p19.test.tsx`.
هذا التقرير وستة ملفات PNG وملف أدلة HTTP في `docs/operations/`.

من dashboard في هذا الفرع:
`node node_modules/vite/bin/vite.js --config vite.browser-acceptance.config.ts`.
افتح العنوان المحدد في Edge، اختر اللغة والدور وعدد الرفض 1/25/26، ثم Start scenario.
استخدم قائمة Import file الأصلية. Start guide يمسح مؤشر جلسة fixture فقط لعرض دليل الرفع.
شريط fixture قابل للطي حتى لا يغطي النافذة عند التقاط الصور.
للتزامن، فعّل Hold correction response، حرر صفًا واحفظ، ثم اختر B، وبعد اختفاء النافذة
اضغط Release response. تحقق من pending=1 في HTTP evidence قبل التبديل؛ بعد التحرير يجب أن يصبح 0 دون نافذة/إيصال/إشعار قديم أو طلب لمهمة A من B. HTTP evidence يعرض سجل الطلبات الصناعية.
حالة fixture ومسوداته محصورة بهذا origin؛ ليست بيانات تطوير أو إنتاج.

أُوقِف خادم Vite الخاص بهذه المهمة بعد حفظ الأدلة وأُعيد قياس المتصفح الطبيعي.
لا Commit/Push إلى main ولا Merge.
