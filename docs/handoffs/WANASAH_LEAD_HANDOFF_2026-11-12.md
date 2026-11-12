# WANASAH — تسليم قيادة المشروع للمحادثة الجديدة | 2026-11-12

**هذه وثيقة استلام تنفيذية للمحادثة الجديدة.** أنت LEAD: تحقق من الواقع على GitHub وجهاز المالك أولًا، اقرأ دستور المشروع، ثم تابع الخطة النشطة دون إعادة إنجاز أو بحث متكرر. خاطب المالك بالعربية باختصار ووضوح. لا Codex، لا أعمال خلفية، لا تخمين في المال والمخزون والصلاحيات.

## 1. حالة التسليم ونقطة الانطلاق

- GitHub: https://github.com/MohHamdallah1/wanasah — `MohHamdallah1/wanasah`.
- جهاز المالك Windows عبر Remote Desktop Commander؛ جذر المشروع: `C:\Users\mohlo\Desktop\wanasah`.
- **آخر MAIN مُتحقق من تطابقه قبل PR التسليم:** `e664c381d89e07761f1854390852f80542d1b486` (دمج #932)، على GitHub والجهاز، و`git status --porcelain -uno` نظيف. **لا تفترض أن هذا هو MAIN الحالي بعد دمج ملف التسليم نفسه:** اعمل GitHub branch/main readback و`git fetch origin main` ثم قارن HEAD قبل أي مهمة.
- الخطة القديمة `docs/plans/DISPATCH_ZONES_SHOPS_V1_CLOSURE_PLAN.md`: D00–D14 كلها `[x]`، D15 قبول بصري أخير؛ تمت إصلاحات PR #929/#931 بواقع 26/26 CI لكل واحد، وقبل المالك التحسين وأذن بإغلاقها وحذف ملفها في هذا التسليم. **أُزيل الملف من الشجرة النشطة؛ أدلته التاريخية محفوظة في Git وIssue #831.** اقرأ حالة #831 وقت الاستلام: يجب أن يكون CLOSED بعد إجراءات تسليم LEAD؛ إذا لم يكن، أكمل إغلاقه بعد التحقق ولا تدّعِ إغلاقه دون نتيجة الأداة.
- `RUN.txt` بند **Dispatch + Zones + Shops operational closure** أصبح `[x]`؛ هذا **ليس** إعلانًا بأن V1 كله انتهى! في RUN المراحل التالية Main Dashboard وBackoffice Users وCompany Settings وCommercial/Returns وFlutter end-to-end وReports وProduction لا تزال لها بواباتها.
- **خطة التوزيع التشغيلية الوحيدة النشطة الآن:** `docs/plans/DISPATCH_MULTI_ROUTE_SESSION_CUSTODY_PLAN.md`، مراحل **M00–M06 كلها `[ ]` غير منفذة**. لا تعيد فتح D00–D15 دون تراجع مُثبت. المهمة التالية: **M00** مراجعة مصدر وعقود multi-route/day/vehicle custody قبل أي schema أو stock/finance write.
- ملف التسليم: `docs/handoffs/WANASAH_LEAD_HANDOFF_2026-11-12.md`. هذه وثيقة تاريخية؛ حقيقة GitHub MAIN وملف الخطة وRUN أعلى منها إذا تغيرت لاحقًا.

## 2. دستور المشروع — اقرأه بالترتيب قبل التنفيذ

1. **`.rules`** — الاسم الصحيح بصيغة الجمع، وليس `.rule`. فيه قواعد الأمان، Freeze، UX، i18n، والصلاحيات.
2. **`AGENTS.md`** ومعه **`.cursor/rules/business-workflow-protection.mdc`** — قواعد جميع العمال وحظر تعديل أي عقد عمل دون اتفاق المالك.
3. **`ARCHITECTURE.md`** — المصدر الأعلى للمعمارية: Strict Modular Monolith، حدود الملكية، فصل domain عن router/UI، Backend-owned complexity، منهج تجميع التشخيص والاختبار والترحيل.
4. **`V1_SCOPE_FREEZE.md`** — ما يجب إطلاقه في V1 وما لا يدخل فيه؛ **`VERSION_2_FUTURE_FEATURES.md`** للتأجيل. إنشاء خطة أو قول «نفّذ» لا يسمحان تلقائيًا بتوسيع نطاق V1. إذا أظهرت M00 قدرات جديدة خارج Freeze، اطلب موافقة المالك **الصريحة لتعديل V1_SCOPE_FREEZE** وحدّثه قبل أي تنفيذ M01+.
5. **`RUN.txt`** — ترتيب المشروع وعلامات [x] و[ ] ونقاط القبول.
6. **`docs/plans/DISPATCH_MULTI_ROUTE_SESSION_CUSTODY_PLAN.md`** — مصدر قرارات المالك الحالي وM00–M06.
7. **`DRIVER_DISPATCH_MODULARIZATION_PLAN.md`** و`DRIVER_DISPATCH_SEAM_INVENTORY.md` لرسم حدود الوحدة. **`INVENTORY_DAMAGED_GOODS_RETURNS_AND_REPRESENTATIVE_SETTLEMENT_PLAN.md`** ملزم قبل تغيير التسوية/العهدة/الفروقات/مسارات الجودة.

**ترتيب السلطة:** العقد التجاري الموافق عليه + دستور المستودع وV1 Freeze + الحقيقة الحالية في Backend/DB + evidence حقيقي، لا تعليقات PR قديمة وحدها، ولا نموذج frontend افتراضي.

## 3. قرارات المالك المعتمدة للمهمة الجديدة — لا تعيد السؤال عنها

- **المنطقة/الخط R1:** تأجيلها يحتفظ بها وبزيارات المحلات المنجزة وغير المنجزة، ويحجز **المنطقة** ضد إنشاء خط متزامن آخر؛ لكنه يحرّر **المندوب والسيارة** من حجز هذا الخط. الاستئناف مع نفس المندوب/السيارة أو تغيير أي منهما من قوائم «عرض المؤجل»؛ يمكن إغلاق المنطقة وإعادة جدولتها لمرة قادمة.
- **يوم عمل واحد S1 للمندوب:** خالد يبدأ العمل مرة واحدة، ويستطيع تأجيل/إغلاق R1 والانتقال إلى R2 والعودة بين خطوط أو سيارات خلال اليوم دون إنهاء دوامه أو تسوية مالية بعد كل تنقّل.
- **السيارتان A وB مخزونان فيزيائيان منفصلان:** تبديل خالد من A إلى B لا يحوّل أي كرتونة أو دفعة أو رصيد بينهما. أي نقل بضاعة فعلي عملية مستقلة صريحة ومصرح بها مع دليل تسليم واستلام؛ لا نختلق Vehicle→Vehicle عبر تحويل المستودعات العام.
- **مبيعات خالد خلال S1 تراكمية عبر جميع السيارات والخطوط:** النقد/تحصيل الديون/المبيعات/الزيارات لا تتصفر عند تغيير الخط أو السيارة أو التأجيل؛ تُعرض في Flutter ولوحة التحكم كإجمالي جلسة مع تفاصيل منفصلة حسب سيارة/خط/الفترة. التاريخ والهوية التجارية/المخزنية لكل عملية immutable.
- **آخر اليوم:** خالد ينهي الدوام، والإدارة تستلم مسؤولية العهدة، وتُجري جردًا فعليًا لمتبقي كل سيارة وتقره **والمتبقي يبقى داخل السيارة** (`COUNT_IN_PLACE`). لا نقل للمستودع إلا عند تسليم فعلي `PHYSICAL_HANDOFF`، والفروقات عبر Stocktake/Vehicle Recon معتمد. بعد تسوية مالية سليمة يبدأ S2 بإحصائيات/حسابات يوم جديد، لكن أرصدة السيارات الحقيقية ومبيعات S1 التاريخية لا تتصفر.
- **استكمال الغد:** قد يظل خط/منطقة مفتوحًا أو مؤجلًا وتبقى السيارة مشحونة؛ عند بدء اليوم الجديد يُستأنف الخط وينتقل سياق التنفيذ إلى S2، مع حفظ تقدم المحلات والرصيد المرحل من موقع السيارة نفسه.
- **تزويد حمولة السيارة:** من المتابعة أو المصافحة التشغيلية الموجودة، بحركات مخزون authoritative موثقة، لا أثر آلي لتغيير المندوب.
- **قوائم Launch:** قائمة واحدة لكل منطقة/مندوب/سيارة؛ المتاحون في الأعلى وغير المتاحين أسفلهم بحالة موجزة ومعطّلون، مع كشف الأسباب فقط لمن يملك صلاحية المشاهدة. المؤجل وحده لا يحجز driver/vehicle، لكن الجلسة والحيازة/العهدة والصلاحيات لا يجوز تجاهلها. الـBackend هو القرار النهائي، والتحذير القصير يبقى للتعارض المتزامن الحقيقي.
- **جدول المنتجات:** أول عرض يكون **حمولة السيارة + أول مجموعة من أصناف المستودع المؤهلة** في ظهور واحد، ثم pagination/virtual window خلال التمرير؛ لا تحميل 50k أصناف دفعة واحدة، ولا Flash عند الرجوع للصفحة. منتجات المستودع يجب أن تكون نشطة وصالحة ورصيدها الحر >0 مع Lot/expiry/FEFO/hold/recall/warehouse authority؛ حمولة السيارة الموجودة تظهر للمراجعة حتى لو لم يعد لها مخزون متاح إضافي بالمستودع.

## 4. الواقع الحالي — لا تدّعِ أن هذه المتطلبات منفذة

- `wa_backend/models.py` فيه indexes/ربط يحجز منطقة/مندوب/سيارة حتى للخط `postponed`؛ بينما المطلوب إبقاء **المنطقة فقط** محجوزة.
- `wa_backend/api/dispatch.py` إنشاء الخط/تغيير الحالة/حارس `WorkSession` يمنع إعادة الإسناد المرنة وفتح عدة خطوط بالمندوب نفسه أثناء جلسة مفتوحة؛ session↔route current assumptions. **ممنوع إسقاط constraints أو حذف 409 اعتباطًا**؛ بديل آمن أولًا.
- `dashboard/src/components/dispatch/PostponedRoutesModal.tsx` يختار مندوبًا عند الاستئناف **ولا يختار سيارة**، وينعكس session-bound على الحالة.
- `wa_backend/api/driver.py` بدء العمل في اليوم التالي مرتبط حاليًا بخط/تاريخ وإسناد الجلسة القديمة؛ تقرير بعض بيانات FIELD يقرأ سيارة وخطًا واحدًا مع أن aggregation by `Visit.work_session_id` يوفر أساسًا لتراكم اليوم.
- `wa_backend/api/representative_settlement.py`: المسار الحالي لاستلام عهدة المندوب **ينقل المتبقي فعليًا من Vehicle إلى Warehouse** قبل تسوية مالية؛ ليس عقد الجرد داخل السيارة المطلوب. لا تستخدمه كما لو كان COUNT_IN_PLACE؛ يجب بناء مسار مُعتمد منفصل مع سلامة التزامن والجرد والأدلة.
- `wa_backend/api/warehouse/transfers.py`: المسار العام للنقل يدعم WAREHOUSE→WAREHOUSE لغرضه؛ لا يوجد إقرار بأن Vehicle→Vehicle workflow مكتمل. `wa_backend/domains/inventory_vehicle_load/service.py` لعهدة/حمولة السيارة.
- العلاقة المطلوبة **route execution periods** و**vehicle custody epochs** وفصل هوية يوم المندوب عن خط المنطقة ما زالت تصميمًا في خطة M01 وليست جداول منفذة. ترحيل البيانات التاريخية لازم محافظ: لا تنسب زيارة قديمة لسيارة جديدة تخمينًا.

## 5. خطة التنفيذ الجديدة — سلّم كل مرحلة كاملة ثم ضع [x]

**الملف الوحيد لتأشير تقدّم التوزيع الجديد:** `docs/plans/DISPATCH_MULTI_ROUTE_SESSION_CUSTODY_PLAN.md`.

- [ ] **M00**: Source/API/DB/Flutter/Dashboard/settlement audit + freeze model/contracts؛ خريطة الهجرات والـrollback والحالات التاريخية، وتجارب A→B→A ضمن اختبار معزول. **NEXT**. لا تعدّل مخزون أو عقود بيع حقيقية في هذه المرحلة.
- [ ] **M01**: PostgreSQL16/Alembic periods لكل تشغيل خط وepochs لمسؤولية السيارة، tenant FK، partial unique guards، reconciliation/backfill محافظ، مع اختبارات RLS/Concurrency.
- [ ] **M02**: Atomic postpone/resume (driver+vehicle), close/re-schedule, releasing driver/car while preserving zone, status/authority/duplicate-request guard.
- [ ] **M03**: Multi-route daily WorkSession، مجموع مبيعات خالد عبر A+B دون ازدواج، next-day session، Flutter offline context isolation/fencing.
- [ ] **M04**: Vehicle in-place count/approval، custodian handoff، settlement عبر السيارات دون نقل مخزون كاذب، معالجة الفروقات المعتمدة.
- [ ] **M05**: لوحة التحكم + Flutter parity؛ قوائم المتاحين، اختيار السيارة والمندوب لاستئناف المؤجل، تسوية المندوب لاحقًا بالصفحة الرئيسية، ظهور المنتجات أول مرة ككتلة حقيقية واحدة.
- [ ] **M06**: Owner acceptance complete scenario: خالد R1/A → postpone → R2/B → R1/A أو إعادة إسناد → end work → count A+B in place → settle → start S2 tomorrow. لا تقفل قبل دلائل فعلية.

**قاعدة [x]:** لا تؤشر `[x]` لمجرد انتهاء عامل أو رفع PR أو نجاح Unit Test. بعد تنفيذ كامل البند بالمصدر والواجهة المطلوبة، اختبار الخطر المحدد، CI الأخضر على immutable HEAD، مراجعة LEAD، دمج في GitHub MAIN، وسحب نفس MAIN للجهاز مع تطابق readback، وثّق تحت البند: `Issue / PR / HEAD / merged MAIN / tests / PG16+Bearer or N/A / CI / decision`. الجزئي يبقى `[ ]` مع بيان ما تبقى.

## 6. قواعد العمارة والتقسيم والاختبارات غير القابلة للتنازل

1. **Strict Modular Monolith**، بلا Microservices أو Big Bang. Legacy mega-files `wa_backend/api/dispatch.py` و`wa_backend/api/driver.py` و`dashboard/src/pages/DispatchBoard.tsx` أسطح API/Composition **لا نقاط تراكم منطق أعمال جديد**. استخرج smallest cohesive seam إلى `wa_backend/domains/dispatch/<responsibility>/`، و`dashboard/src/features/dispatch/<responsibility>/`، وcomponents صغيرة في `dashboard/src/components/dispatch/`. لا God-hook، لا mega-file جديد، لا refactor شامل.
2. **Backend owns** eligibility/Batch/FEFO/cost/locks/idempotency/authorization/settlement؛ UI تعرض حقيقة backend ولا تستنتج رصيدًا أو صلاحية أو تضع ترحيل مخزون من عندها. لا تعديل تاريخ بيع/زيارة/تكلفة منشورة عند نقل مندوب.
3. **Security:** company+tenant RLS، company B/A1/A2 scopes، separate Backoffice capability/FIELD role وreal signed Bearer، warehouse+vehicle physical custody، 401/403/revocation، idempotent replay، fail closed. اختبارات مركزة PostgreSQL16 NOBYPASSRLS/FORCE RLS + HTTP عند تغيير مصدر أمني.
4. **Correctness:** لا حركة Stock لمجرد status/driver/vehicle change. `COUNT_IN_PLACE` ليس Physical Handoff. حفظ lot/status/UOM/delta_base/FEFO/Tax/Prices/COGS والـimmutable ledger. Request ID نفسه لكل إعادة محاولة، lock ordering ثابت، لا duplicate effect.
5. **Frontend:** لا جداول وهمية، لا صفر كاذب أثناء التحميل، لا Flash أو animation، ثبات البيانات المخوّلة بعد التنقل، إعادة التحقق الآمن عند تبديل الصلاحيات/الحساب، عدم تحميل DispatchBoard eager في كل صفحة؛ لا تضخيم Bootstrap. AR/EN RTL/LTR عبر translation keys وليس hardcoded جديد، سرعة سطح عمل واحد وموبايل/ديسكتوب.
6. **لا Codex إطلاقًا.** لا تستخدم أداة/عامل/مراجعة Codex، حتى لو اقترحها GitHub أو test. المالك يستخدم Codex لأعمال منفصلة ويرفض استهلاك حصته.
7. **لا اختبارات مكررة عشوائية**: تحليل مسار السبب أولًا، اختبار قبول مركّز واحد + التراجعات المتأثرة فقط؛ لا تعدّل CI لتخفي فشلًا؛ لا دمج مع red P0/P1. عند اختبارات توثيق فقط لا تعِد كل PG16 وFlutter من الصفر.
8. **لا تغييرات خطيرة جالسة نصف منجزة**؛ اعمل كل M بندًا كاملًا حتى يقبل، ثم فرع جديد نظيف. Owner policy "نصلح شيء ما نخرب الثاني" مطلقة.

## 7. GitHub + Remote Desktop Commander — طريقة العمل اليومية وتوفير التكلفة

**داخل chat أدوات connector متاحة via `functions.exec`:** اكتشف action schema من `ALL_TOOLS` عند الحاجة (لا تختلق اسم أداة)، ثم استدعِ `tools.mcp__GitHub__fetch/fetch_file/get_pr_info/fetch_issue/fetch_workflow_job_logs/... ` للقراءة، و`tools.mcp__Remote_Desktop_Commander__start_process/edit_block/write_file/read_file` للأوامر/التعديلات عبر PowerShell على Windows. GitHub للـsource والـPR/CI، وRemote للتعديل الفعلي والتحقق المحلي والمزامنة؛ لا إعادة نصوص يدوية قدر الإمكان.

**كل بداية:** GitHub main latest، وعلى الجهاز `git -C $repo branch --show-current`، `git -C $repo rev-parse HEAD`، `git -C $repo status --porcelain -uno`، و`git -C $repo fetch origin main`. إذا tracked dirty أو branch != main أو main diverged: لا `reset --hard`/لا stash قسري ولا force. صف السبب للمالك.

**فروع نظيفة:** أنشئ worktree منفصل من **أحدث origin/main** لمهمة واحدة:
```powershell
$repo = 'C:\Users\mohlo\Desktop\wanasah'
$wt = 'C:\Users\mohlo\AppData\Local\Temp\wanasah-M00-unique'
git -C $repo fetch origin main
git -C $repo worktree add -b feat/dispatch-M00-contract $wt origin/main
# عدّل فقط $wt، لا مجلد MAIN للمستخدم ولا ملفات Worktree عامل آخر
```
استعمل `git grep -n` batched مع paths محددة، وGitHub `fetch_file` بمقاطع خطوط بدل جلب ملفات Router كاملة مرارًا. اجمع أدوات GitHub في `Promise.all` داخل `functions.exec` بلا استخدام Function في parallel مع أدوات أخرى؛ على Windows ادمج أوامر PowerShell ذات الصلة في `start_process` واحد. اقرأ stdout بعد التنفيذ؛ لا تستهلك اتصال Remote بعشرات الطلبات الصغيرة أو تعيد فحوصًا ناجحة على SHA لم يتغير.

**التعديل والمراجعة:** تحديد owned files؛ `edit_block` لاستبدال صغير، `write_file` لملف جديد، `git diff --check`, `git diff --stat`, اختبارات مخاطر محددة، `git add -- <exact owned paths>`, `git commit`, `git push origin <branch>`. افتح PR مستقلًا NON-DRAFT بدون Codex، مع `EXACT MAIN / HEAD / CI / PG16+Bearer / UX / BLOCKERS`. لا خلط ملفات العامل الثاني مع الأول.

**الدمج والسحب:** بعد نجاح فحوص **آخر immutable HEAD** ومراجعة LEAD، ادمج PR عبر GitHub بأداة `merge_pull_request(expected_head_sha=...)` ثم على جهاز المالك:
```powershell
$repo = 'C:\Users\mohlo\Desktop\wanasah'
# قبله تحقق من branch main وtracked clean وreadback وorigin sha
git -C $repo fetch origin main
git -C $repo merge-base --is-ancestor HEAD origin/main
git -C $repo merge --ff-only origin/main
git -C $repo rev-parse HEAD
git -C $repo rev-parse origin/main
git -C $repo status --porcelain -uno
```
**لا تدعِ أن النسخ متطابقة قبل مطابقة EXACT GitHub SHA وlocal HEAD وorigin/main وtracked clean.** احفظ `wa_backend/backups`, `.worktrees`، والملفات غير المتتبعة.

**حذف فرع بعد نقطة استقرار:** فقط **فرعنا الذي دُمج فعلًا** وبعد فحص worktree clean وغير مستخدم:
```powershell
git -C $repo worktree remove $wt
git -C $repo branch -d feat/dispatch-M00-contract
git -C $repo push origin --delete feat/dispatch-M00-contract
```
لا `git branch -D`، لا `--force`، ولا `git worktree prune` جماعي، ولا حذف worktree/branch لعامل آخر أو Codex أو المستخدم. **بعد الإغلاق/الدمج/السحب/تنظيف فرعنا، افتح فرعًا جديدًا من MAIN المستقر للمهمة التالية.** إذا كان تنظيف الفرع سيؤثر على شغل غيرك، اتركه موثّقًا ولا تحذف.

**توزيع العمال عند الحاجة الفعلية:** عامل 1 Implementation في issue محدود، عامل 2 Independent read-only security/Chromium أو tests في ملفات منفصلة، وLEAD وحده يراجع ويقرر merge/sync. أعطِ `ISSUE / EXACT MAIN / scope / banned paths / acceptance / deliverables`. المحادثات الأخرى لا تعمل تلقائيًا بعد تعليق Github؛ إن احتجنا تشغيلها نعطي المالك الأمر. لا تعدّد عمال بلا فائدة ولا إعادة 30 Suite بعد تعديل نص.

## 8. ملفات ومداخل مهمة عند بدء M00

- Backend legacy: `wa_backend/api/dispatch.py`, `wa_backend/api/driver.py`, `wa_backend/models.py`. ابحث عن `DispatchRoute` و`WorkSession` وpartial indexes و`work_session_id` و`/driver/sessions/start`, `/driver/sessions/end`, `/dispatch/route/{id}/status`.
- Settlement/Inventory: `wa_backend/api/representative_settlement.py`, `wa_backend/api/warehouse/transfers.py`, `wa_backend/domains/inventory_vehicle_load/service.py`, canonical Inventory Movement/Stocktake/Vehicle Recon.
- Dashboard: `dashboard/src/pages/DispatchBoard.tsx`, `dashboard/src/components/dispatch/PostponedRoutesModal.tsx`, `dashboard/src/components/dispatch/RouteLoadProductTable.tsx`, `dashboard/src/features/dispatch/commercialPreflight/CommercialPreflightPanel.tsx`, `dashboard/src/features/dispatch/useDispatchAccessGate.ts`, `dashboard/src/features/dispatch/stableUi/DispatchChrome.tsx`.
- FIELD Flutter: `wanasah_frontend/`, durable offline/replay, route/session/custody identity; واجهات Dashboard/Flutter لازم تطابق Backend.
- Historical evidence: [#831](https://github.com/MohHamdallah1/wanasah/issues/831) D00–D15، PR #929 signed reentry CI 26/26، PR #931 launch UX CI 26/26، PR #932 plan. العدد 26/26 هو دليل **لتلك PRs فقط**، ليس قبولًا لمزايا M00–M06 المستقبلية.
- لا تعتبر كل Issue قديم مفتوح على GitHub مشكلة V1 مباشرة؛ راجع closed/merged code والأولوية الفعلية. بقية RUN مستقلة عن خطة M00–M06.

## 9. الأمر التنفيذي للمحادثة الجديدة

**أنت LEAD الجديد:**
1. افحص live GitHub main وWindows main/clean واطبع SHA، وتأكد وجود خطة M00–M06 وحالة Issue #831.
2. اقرأ الملفات الدستورية بالترتيب؛ لا تعدّل DB/UI قبل M00؛ حدّد نطاق V1/قرار scope change كما تقتضي `V1_SCOPE_FREEZE.md`.
3. ابدأ M00 كمهمة تدقيق/تجميد عقد صغيرة في فرع نظيف، مع أدلة مصدر لا تخمين. إذا ظهرت نقطة تجارية غير محسومة **اسأل المالك فقط عن تلك النقطة**؛ لا تعِد السؤال عن تسعة قرارات §3.
4. بعد اكتمال كل بند M وتحقق PR+CI+LEAD+MAIN sync ضع **[x]** في الخطة وسجّل SHA وproof، امسح **فرعنا** المدموج بأمان، وابدأ الفرع التالي من MAIN الجديد. لا Codex، لا أعمال غير منتهية، لا Regression مقبول.

**آخر شيء:** نظام تعدد الخطوط والجلسات والسيارات والتسوية في مكان السيارة **ما زال خطة غير منفذة**؛ إغلاق D15 لا يعني اكتمالها. الأمان والمخزون والمالية والعمليات هي الأولوية، والسرعة من تقليل الضوضاء وليس التنازل عن الحماية.
