# Phase 19 — real isolated PostgreSQL Worker fault recovery

التاريخ: 2026-10-01. الفرع:
`hardening/v1-import-phase19-worker-failure-recovery-codex`.
المجلد: `C:\Users\admin\Desktop\wanasah-codex-D7S`.
الأساس: أحدث origin/main عند بدء المهمة:
`8c5d2478bdbedd5297f9cce40f0e1e6fed118401`.

## النتيجة

**الحالات الأربع المطلوبة PASS على PostgreSQL حقيقية وWorker حقيقيين.**
الأدلة موزعة على ثلاث جولات موضحة أدناه؛ لا ندّعي أن الجولة الأولى أو الثانية
نجحت بالكامل. لم يثبت خلل إنتاجي يستدعي تعديل Business Logic أو آليات التعافي،
لذلك لا توجد تعديلات في كود التطبيق/قاعدة البيانات/الصلاحيات/الخطة/Dashboard.
التغيير هو وضع fault acceptance محدود داخل الأداة المعزولة الموجودة، مع مراقبة
النقل اللازمة لإثبات فقد COMMIT فعليًا، وتقرير الأدلة.

## تحليل المصدر قبل التشغيل

- `application/source_service.py`: تحميل الحالة الدائمة أولًا، قراءة SourceStore
  بالـhash/size، ثم parsing/spool وstaging؛ تنظيف المصدر يأتي بعد نجاح staging.
  إعادة محاولة QUEUED/PARSING تعيد قراءة المصدر. VALIDATING/IMPORTING تتجاوز
  إعادة staging؛ NEEDS_MAPPING تعيد التنظيف فقط ولا تستبدل هوية الصفوف.
- `application/staging_service.py`: حذف/إدراج/مطابقة عدد الصفوف وتحديث الحالة
  ثم COMMIT واحد؛ فشل العملية يمر عبر ROLLBACK/close ولا يطلق تنظيف المصدر.
  فقد تأكيد COMMIT لا يثبت ROLLBACK؛ الحالة المحفوظة هي سلطة الاستئناف.
- `infrastructure/staging_io.py`: حد 120s لكل خطوة، و10s للتنظيف؛ إغلاق
  transport مملوك لهذه الجلسة فقط، ومسح الملكية عند checkin. هذه السياسة
  لم تتغير ولم نكرر اختبار watchdog القصير أو إلغاء HTTP بالقفل الناجحين.
- `database.py`: pool_pre_ping=True قبل checkout، ثم إعادة ضبط سياق RLS.
  pre-ping يعالج اتصالًا ميتًا في pool؛ لا ينقذ معاملة انقطع اتصالها بعد الاستعارة.
- `infrastructure/queue.py`: تصنيف الفشل غير المتوقع TRANSIENT_SYSTEM/JOB،
  لا تحويله إلى خطأ صف؛ نفس delivery يعاد وفق RetryStrategy الحالية (4 attempts).
  `state_machine.record_runtime_failure` يقرأ الحالة الدائمة تحت قفل المهمة.
- `application/execution_service.py`: Product/Pricing وآثار الصف وأعداده تحفظ
  في وحدة المعاملة نفسها؛ إعادة IMPORTING تختار VALID فقط وتتجاوز IMPORTED.
  لذلك فرضيتا COMMIT هما استئناف الحالة/الصفوف المحفوظة، دون إنشاء وحدة ثانية.

هذه فرضيات محددة عند الحدود الحقيقية؛ لم نضف محرك تحقق أو idempotency بديلًا.

## العزل وطريقة الحقن

استُخدمت `run_product_import_phase19_http_isolated_gate.py` كما في RUNBOOK:
عنقود PostgreSQL16 مؤقت جديد على 127.0.0.1:55446، قاعدة
`p19_http_synthetic`، API حقيقية على 18046، وأدوار control/maintenance/execution
الحقيقية. مخطط المصدر وfixture الشركة 2 المُسبقة الموافقة قرئا فقط من قاعدة
التطوير؛ لا Worker عليها، ولا schema/data writes عليها. فحص مصدر المخطط
أظهر revision `a42c9f17e6b3` مطابقًا للـhead، وفحص fixture خالٍ.

Python 3.12.10، SQLAlchemy 2.0.40، asyncpg 0.29.0، Psycopg 3.3.5؛
Windows SelectorEventLoop كما في worker_cli. استُخدم Python المكتبات الموجود
دون تعديل مجلد وناسة الأساسي؛ كود التطبيق الجاري من D7S.
execution يشغّل `worker_cli.main/run` الأصليين بعد test-only observer؛
نفس engine/pool/session وstartup recovery وqueue consumer والسلطات.
لا مسار عمل بديل أو fake commit أو direct invocation بدل Queue.

وسيط loopback على 55447 يمرر asyncpg فقط إلى العنقود المملوك؛ Psycopg/Queue/API
تبقى على 55446. لا SQL أو parameters أو passwords تسجل بواسطة الوسيط.
يقرأ BackendKeyData لتحديد PID الحقيقي؛ ويرصد Parse **وBind** لأن asyncpg
يعيد استخدام Prepared Statements. في حالتي COMMIT يستقبل
CommandComplete=COMMIT من PostgreSQL، **ولا يرسله ولا ReadyForQuery إلى العميل**،
ويتيح قراءة الحالة من اتصال مستقل قبل إغلاق النقل. ليست محاكاة Exception
بعد عودة db.commit() بنجاح.

الحقن/الواجهة يرفضان غياب opt-in أو أي host/port/database آخرين.
الاتصال بلا TLS محصور بهذا العنقود المحلي الصناعي، دون تغيير TLS الإنتاج.
لا ملفات Excel للمستخدم، لا 5k/50k/D7-S/Benchmark أو إعادة بوابات سابقة.

## النتائج الفعلية

| الحالة | النتيجة والدليل |
|---|---|
| اتصال ميت عند الاستعارة / pre-ping | **PASS، الجولة الأولى فقط.** اتصال العامل أعيد إلى pool ثم أُنهي PID=1432 في العنقود المملوك؛ رُصد do_ping مرة وInvalidatePoolError. استعارة الشركة 3 استبدلته بـPID=22312؛ app.current_tenant=3 وقراءة Products الشركة 2=0. لم يُكرر الفحص. |
| قطع النقل أثناء INSERT في Staging | **PASS، الجولة الثانية.** PID=4568 كان فعلًا في PgSleep داخل INSERT؛ قُطع TCP، وانتظر الفحص تحرير advisory lock الفعلي. بقي SourceStore الأصلي 940 bytes/hash/chunk/reference في PARSING، وصفوف staging الملتزمة=0. ثم Queue retry للـjob نفسه أكمل 6/6 في 9.547s من admission، attempts=2/succeeded. لا INVALID أو IMPORT_FAILED. |
| فقد تأكيد COMMIT لـStaging | **PASS، الجولة الثالثة.** PostgreSQL أرسل COMMIT ولم يصل إلى asyncpg؛ اتصال مستقل قرأ VALIDATING و6 صفوف بهوياتها وخلاياها الأصلية، والمصدر ما زال محفوظًا. بعد قطع النقل: نفس الهويات/الأرقام/raw_data دون restaging، 6/6، attempts=2/succeeded، 6.797s. |
| فقد تأكيد COMMIT لوحدة Product/Pricing | **PASS، الجولة الثالثة.** قبل إسقاط الرد قرأ اتصال مستقل IMPORTING و6 صفوف IMPORTED وProduct/Variant/Price/Audit/Outbox المحفوظة. بعد retry بقيت معرفاتها ونسخ Product/Variant/Price/publication وآثار Audit/Outbox نفسها، وكل إجماليات جداول الشركة نفسها؛ 6/6، attempts=2/succeeded، 6.203s. |

في كل حالة مهمة مثبتة: الزيادة **6 Products + 6 Variants + 11 Price entries**
(6 أسعار وحدة + 5 أسعار عبوة)، و**6 Audit + 6 Outbox**.
الـhelper الأصلي أثبت 6 distinct price variants، لا تكرار لنفس
variant/UOM/effectivity، وAudit/Outbox فريدين. العد الكلي لـProducts/Variants
يثبت عدم وجود نسخ زائدة غير مرتبطة بالصفوف. المقارنة بعد execution COMMIT تشمل
كل إجماليات الجداول أيضًا، فلا تُخفي آثارًا ثانية غير مرتبطة.

عند النهاية في كل حالة: لا TODO/DOING لهذه المهمة، والـWorker لم يخرج أثناء retry،
ومؤشر تنظيف SourceStore مكتوب. SELECT FOR UPDATE NOWAIT للمهمة وكل صفوفها نجح
ثم ROLLBACK للفحص نفسه. advisory lock الذي أخذه INSERT المتعطل أصبح متاحًا
قبل الاستئناف. لم يتطلب التعافي تحرير أقفال تطبيق يدويًا أو إعادة إنشاء queue jobs.

حقل `durable_row_identity_unchanged=false` في سجل staging_abort يعني
**غير منطبق قبل COMMIT**: لم تكن هناك هويات صفوف ملتزمة لنقارن بها؛ المقارنة
هناك هي المصدر الكامل + صفر صفوف جزئية. في حالتي COMMIT المقارنة true فعلًا.
الأزمنة قياسات مفردة للحقن/التعافي، تشمل انتظار retry والانتظار الاصطناعي؛
ليست benchmark أو p95 أو توقيت SQL خالصًا.

## الجولات والفشل المعلن

1. [الجولة الأولى](PRODUCT_IMPORT_P19_WORKER_FAULT_INITIAL_OUTPUT.txt):
   pre-ping PASS، لكن اختبار تحرير PID بعد قطع Staging فشل عند 35s.
   سبب حقن مثبت: pg_sleep(8) كان يطبق على **كل الصفوف الستة** (حتى 48s).
   PostgreSQL قد يستمر في تنفيذ SQL بعد TCP EOF قبل أن يلاحظ الانقطاع؛
   لا يجوز استنتاج تحرير قفل فوري من إنهاء transport. تنظيف الفشل مر عبر
   /cancel الرسمي وqueue drain قبل إيقاف العمليات المملوكة، ثم أزيل العنقود.
2. [الجولة الثانية](PRODUCT_IMPORT_P19_WORKER_FAULT_SECOND_OUTPUT.txt):
   إصلاح حقن الانتظار إلى الصف الأول فقط، وطلب advisory lock قبل بدء retry
   لقراءة المصدر دون سباق؛ staging_abort PASS. حالتا COMMIT لم تثبتا في هذه
   الجولة لأن observer كان يرصد Parse وحده وافتقد INSERT المعاد عبر Bind.
   لم يُنسب فشل الرصد إلى كود الإنتاج؛ صفوف هذه المحاولة لا تُعد دليل COMMIT.
3. [الجولة الثالثة](PRODUCT_IMPORT_P19_WORKER_FAULT_GATE_OUTPUT.txt):
   بعد إصلاح observer لتمييز Prepared Statement reuse، شُغلت حالتا COMMIT
   فقط ونجحتا؛ لم يُكرر pre-ping أو staging_abort الناجحان.
   `PRODUCT_IMPORT_P19_REAL_WORKER_FAULTS=PASS` يخص الحالات المختارة في هذه الجولة.
   `ORIGINAL_DEV_TENANT_UNMODIFIED=PASS` و
   `P19_HTTP_DISPOSABLE_CLUSTER_REMOVED=PASS` صدرا بعد النهاية.

الإجمالي خمس مهام قبول صغيرة، كل منها 6 صفوف (30 صفًا صناعيًا عبر محاولات
التجهيز الثلاث)، منها ثلاث مهام أثبتت حالات الفشل/التعافي المستهدفة.
لا نجاح شامل للجولات الفاشلة ولا mock PASS.

## الفحوص والحدود

- AST لجميع ملفات التغيير: PASS.
- حارسا التشغيل دون opt-in ومع DSN قاعدة التطوير: PASS؛ رفض قبل فتح اتصال.
- git diff --check: PASS.
- فحص المنافذ 55446/55447/18046 بعد النهاية: مغلقة؛ الخدمات المملوكة أوقفت.
  فحص عمليات Python بهوية WANASAH_P19_HTTP_CASE=workerfaults أعاد قائمة فارغة، دون إيقاف أي عملية أخرى.
- لا تعديلات/اختبارات Dashboard أو migrations جديدة أو تغيير الخطة.
  bootstrap/migrations الموجودة في runner نُفذت على العنقود المؤقت فقط.

**OPEN خارج هذا الدليل:** السبب الداخلي لتعليق ClientRead التاريخي في سبتمبر،
وسلوك فشل/إعادة تشغيل خادم PostgreSQL أو فقد fsync/قرص، أو توقف SQL إلى أجل
غير محدد، ومهل 120s الفعلية، وسلوك الشبكة/TLS في نشر العميل. قطع TCP لا يَعِد
بمقاطعة حساب PostgreSQL فورًا؛ تحرير القفل هنا مثبت بعد انتهاء الانتظار
الاصطناعي المحدود وملاحظة الانقطاع. لا نغيّر السياسة بناءً على trigger اختباري.

## الملفات وإعادة الفحص المحدود

- `wa_backend/scripts/run_product_import_phase19_http_isolated_gate.py`:
  إضافة workerfaults فقط إلى dispatcher/opt-in/marker، دون إعادة بناء bootstrap.
- `wa_backend/scripts/product_import_phase19_worker_fault_child.py`:
  الحالات الأربع، readback/lock proofs، واستعمال أدوات HTTP/fixture/business evidence الموجودة.
- `wa_backend/scripts/product_import_phase19_pg_wire_fault.py`:
  مراقبة/قطع transport المملوك، بما فيها حجب تأكيد COMMIT الحقيقي.
- هذا التقرير وثلاثة سجلات نتائج نصية أعلاه.

من wa_backend وبـPython المثبت، فقط عند الموافقة على جولة جديدة معزولة:
```powershell
$env:WANASAH_P19_HTTP_LOCAL_GATE='1'
$env:WANASAH_P19_HTTP_SOURCE_ENV_FILE='<read-only developer .env>'
$env:WANASAH_P19_HTTP_CASE='workerfaults'
$env:WANASAH_P19_WORKER_FAULT_CONFIRM='ISOLATED_SYNTHETIC_ONLY'
# حذف المتغير التالي من البيئة يشغل الأربع؛ اختَر المتأثر فقط لتجنب التكرار.
$env:WANASAH_P19_WORKER_FAULT_CASES='staging_commit,execution_commit'
python -m scripts.run_product_import_phase19_http_isolated_gate
```

الحالات المسموحة فقط: pre_ping، staging_abort، staging_commit، execution_commit؛
كل مصدر ثابت عند ستة صفوف، لا متغير لرفع الحمل. الفرع مستقل، دون Merge.
