# WANASAH PRODUCTS — HANDOFF P7 CURRENT
## Snapshot date: 2026-09-24

> هذا الملف مخصص لبدء محادثة ChatGPT جديدة ومتابعة مشروع Wanasah فورًا من نفس النقطة، بدون إعادة شرح التاريخ أو طريقة العمل.
> بعد رفع هذا الملف في المحادثة الجديدة، يجب قراءة الملف كاملًا أولًا ثم التحقق من GitHub قبل أي تعديل.

---

# 1) المشروع والمستودع

- GitHub repo: `MohHamdallah1/wanasah`
- Local root: `C:\Users\admin\Desktop\wanasah`
- Frontend: `dashboard`
  - React
  - TypeScript
  - Vite
  - Vitest
- Backend: `wa_backend`
  - FastAPI
  - SQLAlchemy
  - PostgreSQL
  - Alembic

## المرجع الرئيسي

الملف المرجعي والـsource of truth لخطة Products هو:

`PRODUCTS_PRODUCTION_PLAN.md`

قواعد الخطة:
- Section 53 — `Recommended execution order` هو الـcanonical phase tracker.
- Section 54 — `Immediate next task` يجب أن يعكس الخطوة التالية الفعلية.
- Sections 4–52 تفاصيل ومتطلبات وتغطية؛ لا نعلمها `[x]` إلا بدليل فعلي.
- الحالات الوحيدة:
  - `[ ]` لم يبدأ
  - `[~]` قيد التنفيذ
  - `[x]` مكتمل ومثبت
  - `[!]` blocked / يحتاج قرار
- ممنوع وضع `[x]` إلا بعد:
  1. اكتمال الكود،
  2. نجاح الاختبارات/gates المناسبة،
  3. regression review،
  4. diff مقصود ونظيف.

---

# 2) قواعد العمل الصارمة

## لا تخمين
- ممنوع الافتراض أو التخمين.
- الكود موجود على GitHub: افحصه قبل القرار.
- لا تسأل المستخدم عن شيء يمكن التحقق منه من repo.
- لا تعتمد على memory وحدها إذا GitHub يعطي الحقيقة الحالية.
- لا تقول إن بندًا انتهى قبل إثباته بالاختبارات.

## طريقة التعديل
المساعد نفسه يعدل GitHub مباشرة باستخدام GitHub connector.

المسار المعتاد:
1. افحص الملفات الدقيقة على الفرع الحالي.
2. افحص الخطة والعقود/tests ذات الصلة.
3. نفذ تعديلًا مركزًا، بدون shortcuts أو tech debt.
4. بعد **كل mutation على GitHub**:
   - خذ commit SHA الناتج.
   - اعمل exact compare:
     `base=<commit_sha>` مقابل `head=<branch>`
   - لا تقل إن الفرع current إلا إذا:
     `status: identical`, `ahead_by: 0`, `behind_by: 0`.
5. أعط المستخدم أوامر PowerShell الدقيقة ليعمل pull ويشغل الاختبارات محليًا.
6. إذا فشل test/gate واحد:
   - توقف.
   - شخّص سبب الفشل نفسه.
   - أصلح السبب فقط.
   - لا تنتقل للبند التالي.
7. إذا البند الحالي اكتمل بالكامل:
   - علم checkboxes المثبتة فقط.
   - **توقف وأخبر المستخدم**.
   - لا تبدأ البند الذي بعده في نفس الدفعة إلا إذا طلب المستخدم المتابعة.

## لا تضعف الاختبارات
- ممنوع تعديل test فقط ليمر إذا production فيه خلل.
- إذا failure سببه test stale بعد refactor مقصود، أثبت أولًا أن runtime behavior سليم، ثم حدث gate/test ليختبر العقد الجديد بدون إضعافه.
- runtime tests أفضل من source-string assertions عندما يكون ذلك ممكنًا.
- لا تضف `any`.
- unknown boundaries يجب runtime validation لها حيث يلزم.

## سلطة الـbackend
Backend هو authority في:
- lifecycle
- pricing
- UOM conversions
- tracking
- barcodes
- warehouse eligibility
- inventory mutation rules

لا ننسخ business authority إلى React.

## Tenant / security
- company scope صريح.
- location scope صريح عند الحاجة.
- RLS defense-in-depth وليس بديلًا عن scoping.
- cross-company IDs fail closed.
- permission checks قبل كشف protected data.

## Money
- لا نستخدم JS floating point كauthority للمال.
- monetary APIs تبقى strings/exact decimals.
- frontend derived prices preview فقط.
- backend authoritative.

## Git المحلي
المستخدم لديه ملف handoff قديم غير متتبع غالبًا:
`WANASAH_PRODUCTS_HANDOFF_P4_CURRENT.md`

لا تستخدم:
`git add .`

حتى لا يدخل الملف بالغلط.

---

# 3) نظام الفروع والإغلاق

كل Phase له branch مستقل من `main` المستقر.

عند إغلاق phase:
1. كل gates/tests المطلوبة تنجح محليًا.
2. تحديث `PRODUCTS_PRODUCTION_PLAN.md`.
3. مراجعة final diff.
4. فتح PR.
5. squash merge إلى `main`.
6. التحقق أن merge SHA يطابق `main` حرفيًا.
7. حذف remote phase branch.
8. إنشاء next phase branch من merge SHA نفسه.
9. المستخدم:
   - `git fetch --prune origin`
   - `git switch main`
   - `git pull --ff-only origin main`
   - switch/track next branch
   - حذف local old phase branch.
10. لا تستخدم merge/rebase/reset محليًا إلا بعد تشخيص صريح.

---

# 4) المراحل المستقرة السابقة

## P4 — Search / families
- PR #19
- merged main:
  `43b88b2de2adcd2b02a8bc3bba1f12a61308f561`

## P5 — Exact pricing / UOM
- PR #20
- merged main:
  `dfb0fc32f451419c0ec9182abc5499af90a4d87f`

## React Router v7 future flags compatibility chore
- PR #21
- merged main:
  `8d3b51717fcc1888de93aae4a80ef5402ce8ed2a`
- enabled:
  - `v7_startTransition: true`
  - `v7_relativeSplatPath: true`
- regression:
  `dashboard/src/test/react-router-v7-future-flags.test.ts`

## P6 — Bulk import
- PR #22
- merged main:
  `2262e56c948f6b2b88a0163805ad149c04a3d12a`
- all P6 phase tracker items `[x]`
- backend gates:
  - `PRODUCT_IMPORT_TRACKING_GATE`: 20/20 PASS
  - `PRODUCTS_P6_IMPORT_LOCALIZATION_GATE`: 16/16 PASS

---

# 5) الحالة الحالية — P7

## الفرع الحالي
`feat/products-i18n-accessibility-p7`

## قاعدة الفرع
P7 بدأ من main المستقر:
`2262e56c948f6b2b88a0163805ad149c04a3d12a`

## HEAD الحالي على GitHub
`0a480e91b46452e1a4d0d2e24f043c096fc278eb`

آخر commit:
`Close P7 generic locale resolver checkpoint`

تم التحقق:
- exact commit → branch:
  `status: identical`
- branch vs main:
  - `ahead_by: 37`
  - `behind_by: 0`

**P7 لم يُفتح له PR بعد ولم يُدمج.**
لا تدمج P7 قبل إكمال كل P7.

---

# 6) P7 tracker الحالي

```md
## Phase P7 — i18n / accessibility / polish

- [x] Generic locale resolver.
- [ ] all translation keys.
- [ ] RTL/LTR.
- [ ] accessibility.
- [ ] responsive polish.
- [ ] configurable display preferences.
```

المطلوب عند استئناف العمل:
ابدأ فقط بالبند التالي:

`all translation keys`

ولا تدخل RTL/LTR قبل إكمال translation keys بالكامل واختبارها وإغلاقها.

---

# 7) ما تم إنجازه في P7 — Generic locale resolver

هذا البند **أُغلق رسميًا**.

## القرار المعماري
رغم أن P7 أصله Products-focused، فإن locale authority لو بقي داخل Products فقط سيخلق مصدر حقيقة ثانيًا لأن المشروع كله كان فيه hardcoded locales.

لذلك تم بناء:
- shared project-level locale authority
- ثم ربط Products وباقي production formatting المباشر به
- بدون refactor عشوائي لباقي business logic

## الملف الجديد
`dashboard/src/lib/locale.ts`

سلوكه:
- `DEFAULT_APP_LOCALE = "en-US"`
- bare `ar` → `ar-JO`
- bare `en` → `en-US`
- explicit `ar-EG` يبقى `ar-EG`
- explicit `en-GB` يبقى `en-GB`
- `fr-FR` يبقى `fr-FR`
- bare `fr` يبقى `fr`
- bare `de` يبقى `de`
- `pt_BR` → `pt-BR`
- invalid/missing locale → safe fallback
- `resolveI18nLocale()` يفضل `resolvedLanguage` ثم `language`

## i18n
`dashboard/src/i18n/index.ts`

`currentLocale()` صار:
```ts
export const currentLocale = () =>
  resolveI18nLocale(i18n);
```

---

# 8) P7 locale regression gate

الاختبار:
`dashboard/src/test/locale-resolver-p7.test.ts`

الحالة الأخيرة:
**8/8 passed**

يغطي:
1. bare Arabic/English defaults.
2. explicit regional locales.
3. future bare languages لا تسقط إلى English.
4. underscore canonicalization.
5. `resolvedLanguage` priority.
6. invalid/missing fallback.
7. `currentLocale()` delegates to shared resolver.
8. recursive production source gate.

الـsource gate يمنع:
- hardcoded locale مباشرة داخل `Intl.NumberFormat`
- hardcoded locale مباشرة داخل `Intl.DateTimeFormat`
- hardcoded locale في `toLocaleString/DateString/TimeString`
- `i18n.language.startsWith("ar")`
- regional locale literals مثل:
  - `ar-JO`
  - `ar-EG`
  - `en-US`
  خارج authority المسموح
- direct:
  `i18n.resolvedLanguage || i18n.language`
  أو `??`
- raw i18n locale داخل Intl/toLocale methods

---

# 9) مشاكل ظهرت وتم إصلاحها في P7

## TopBar TypeScript error
ظهر:
```text
src/components/operations/TopBar.tsx:15:23 - error TS2554:
Expected 2 arguments, but got 1.
```

السبب:
`formatTenantDate()` أصبح:
```ts
formatTenantDate(
  timezone: string | undefined,
  locale: string
)
```

الإصلاح الحالي في:
`dashboard/src/components/operations/TopBar.tsx`

- `useTranslation()`
- `resolveI18nLocale(i18n)`
- تمرير `locale` إلى `formatTenantDate`

والـcontract:
`dashboard/src/features/tenantIdentity/contracts.ts`
يستخدم `resolveAppLocale(locale)` داخليًا.

## Vitest file URL failure
ظهر:
```text
TypeError: The URL must be of scheme file
```

السبب:
`new URL(..., import.meta.url)` داخل source-scanning test.

الإصلاح الحالي:
- `process.cwd()`
- `resolve`
- `join`
- `readFileSync`
- `readdirSync`

لا تعيد `new URL(..., import.meta.url)` لهذا الاختبار.

---

# 10) نتائج الاختبارات الأخيرة

```text
Test Files  1 passed (1)
Tests       8 passed (8)
```

```text
Test Files  3 passed (3)
Tests       13 passed (13)
```

```text
Test Files  25 passed (25)
Tests       157 passed (157)
```

```text
✓ built in 17.96s
```

بناءً على ذلك:
`[x] Generic locale resolver`

---

# 11) checkboxes التي تم إغلاقها مع locale resolver

Section 27:

```md
- [x] Central locale resolver.
- [x] Arabic may use an Arabic locale.
- [x] English may use an English locale.
- [x] French/German/etc. use their own locale instead of silently falling to `en-US`.
- [x] `Intl.NumberFormat` uses resolved locale.
- [x] `Intl.DateTimeFormat` uses resolved locale.
```

ما زالت مفتوحة:

```md
- [ ] Currency formatting uses correct currency + locale.
- [ ] RTL/LTR is derived from i18n configuration.
- [ ] Long translated labels tested.
- [ ] Translation keys for all tracking/lifecycle/UOM labels.
```

Coverage map:

```md
- [x] 39. Replace binary Arabic-vs-English locale fallback with generic locale resolution.
- [x] 40. Make all new number/date/money rendering language-agnostic.
```

لا تغلق تلقائيًا:
- `i18n architecture is language-agnostic`
- `RTL + LTR pass`

لأن P7 لم يكتمل.

---

# 12) Section 54 الحالي

الخطوة التالية داخل P7:

**all translation keys**

الترتيب:
1. Audit Products user-facing text and translation keys.
2. إكمال translation-key item بالكامل.
3. targeted + full regression.
4. تعليم البنود المثبتة فقط.
5. **التوقف وإخبار المستخدم**.
6. بعد موافقة المستخدم فقط:
   `RTL/LTR`
7. ثم:
   - accessibility
   - responsive polish
   - configurable display preferences
8. لا تبدأ P8 قبل إغلاق P7 ودمجه.

---

# 13) ملفات P7 locale checkpoint المتغيرة مقابل main

```text
PRODUCTS_PRODUCTION_PLAN.md

dashboard/src/components/dashboard/HeroSettlement.tsx
dashboard/src/components/dispatch/PendingRoutesTable.tsx
dashboard/src/components/dispatch/ShortageModal.tsx
dashboard/src/components/dispatch/TransfersRadarModal.tsx

dashboard/src/components/operations/CommandCenter.tsx
dashboard/src/components/operations/FleetRadar.tsx
dashboard/src/components/operations/OperationsSidebar.tsx
dashboard/src/components/operations/PulseBar.tsx
dashboard/src/components/operations/SettlementModal.tsx
dashboard/src/components/operations/TopBar.tsx

dashboard/src/features/tenantIdentity/contracts.ts

dashboard/src/i18n/index.ts

dashboard/src/lib/locale.ts
dashboard/src/lib/localeNumbers.ts
dashboard/src/lib/money.ts

dashboard/src/pages/Login.tsx
dashboard/src/pages/PlatformDashboard.tsx
dashboard/src/pages/PricingDashboard.tsx
dashboard/src/pages/SalesReturnsDashboard.tsx

dashboard/src/pages/inventory/MainInventory.tsx
dashboard/src/pages/inventory/Tab1LiveStock.tsx
dashboard/src/pages/inventory/Tab4Ledger.tsx
dashboard/src/pages/inventory/TabBatches.tsx
dashboard/src/pages/inventory/TabWarehouseLocations.tsx
dashboard/src/pages/inventory/transfers/utils.ts
dashboard/src/pages/inventory/warehouse-locations/BranchManagementModal.tsx

dashboard/src/pages/products/ProductDetailDrawer.tsx
dashboard/src/pages/products/ProductTableRow.tsx

dashboard/src/test/locale-resolver-p7.test.ts
```

---

# 14) أول شيء في المحادثة الجديدة

بعد رفع هذا الملف:
- لا تطلب من المستخدم إعادة الشرح.
- تحقق من GitHub مباشرة.

Expected:
- repo: `MohHamdallah1/wanasah`
- branch:
  `feat/products-i18n-accessibility-p7`
- HEAD:
  `0a480e91b46452e1a4d0d2e24f043c096fc278eb`

وتحقق أن:
- behind main = 0
- الخطة فيها:
  - `[x] Generic locale resolver`
  - `[ ] all translation keys`

## أول أوامر محلية متوقعة

```powershell
cd C:\Users\admin\Desktop\wanasah

git pull --ff-only origin feat/products-i18n-accessibility-p7

git log -1 --oneline --decorate
git status --short
```

وجود handoff markdown كـuntracked file ليس failure.

لا تعمل:
```powershell
git add .
```

---

# 15) كيف نبدأ البند التالي: all translation keys

لا تبدأ بتعديل translations عشوائي.

ابدأ بـaudit:

1. `dashboard/src/pages/ProductsDashboard.tsx`
2. كل:
   `dashboard/src/pages/products/*.tsx`
3. Products-related shared helpers/contracts التي تعرض نصًا للمستخدم.
4. `dashboard/src/i18n/resources.ts`
5. known backend/API error codes التي تصل Products UI.
6. lifecycle labels.
7. UOM labels.
8. tracking labels.
9. advanced UOM.
10. barcode manager.
11. family manager.
12. import surface.
13. empty/loading/error/retry states.
14. aria labels/tooltips/title strings المرتبطة Products.

المطلوب:
- لا user-facing hardcoded Arabic/English جديد.
- translation keys مستقرة.
- Arabic + English coverage.
- لا branching على translated message.
- known error codes → translations.
- unknown technical diagnostics لا تتحول لعقد localization.
- لا تلمس RTL/LTR قبل إغلاق translation keys.

يفضل permanent gate لاكتشاف:
- missing bilingual Product keys
- references لمفاتيح غير موجودة
- hardcoded Products user-facing strings إذا أمكن كشفها بدون gate هش

---

# 16) التعامل مع أي failure

إذا أرسل المستخدم failure:
1. لا تكمل باقي الأوامر.
2. افتح exact file + exact test.
3. حدد السبب:
   - production bug
   - stale test
   - environment
   - contract mismatch
4. أصلح السبب فقط.
5. exact compare commit vs branch.
6. أعط إعادة الاختبار الفاشل فقط.
7. بعد نجاحه أكمل gates المتبقية.

---

# 17) أسلوب التواصل المطلوب

- عربي أردني.
- مباشر ومختصر نسبيًا.
- بدون حكي إنشائي.
- لا تقل "بنقدر" إذا المطلوب تنفيذ؛ نفذ.
- لا تعط وعود مستقبلية بدون tool action.
- لا تسأل سؤالًا إذا repo inspection يحسمه.
- أثناء tool work الطويل:
  update قصير كل عدة calls.
- بعد نجاح بند كامل:
  سكره بالخطة، ثم **توقف** ولا تدخل البند التالي تلقائيًا.

---

# 18) GitHub workflow reminder

استخدم GitHub connector مباشرة:
- fetch file
- update file
- create file
- compare commits
- branch operations
- PR
- squash merge

لا تستخدم web search لقراءة repo إذا GitHub connector متوفر.

بعد mutation:
**mandatory exact compare**.

عند phase close:
- PR
- squash merge
- verify exact main SHA
- delete phase branch
- next branch from stable main

---

# 19) ما لا يجب فعله الآن

- لا تفتح PR لـP7 الآن.
- لا تدمج P7 الآن.
- لا تبدأ P8.
- لا تعيد Generic locale resolver.
- لا تعيد React Router flags.
- لا تعلّم RTL/LTR/accessibility/responsive/preferences `[x]` قبل تنفيذها واختبارها.
- لا تعلّم `Currency formatting uses correct currency + locale` بدون دليل إضافي.
- لا تعمل `git add .`.

---

# 20) snapshot النهائي

```text
Repo:
MohHamdallah1/wanasah

Stable main:
2262e56c948f6b2b88a0163805ad149c04a3d12a

Current branch:
feat/products-i18n-accessibility-p7

Current remote HEAD:
0a480e91b46452e1a4d0d2e24f043c096fc278eb

Branch vs main:
ahead 37
behind 0

Current phase:
P7 — i18n / accessibility / polish

Completed current P7 item:
[x] Generic locale resolver

Next item:
[ ] all translation keys

Important:
When all translation keys is complete, stop and report before RTL/LTR.
```

هذه هي نقطة الاستئناف الصحيحة.
