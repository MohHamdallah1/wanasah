# WANASAH Flutter V1 — Polish & UX Execution Plan

**Status:** ACTIVE  
**Owner-approved checkpoint:** 2026-10-24  
**Scope:** Flutter V1 representative app polish only. This is not a business-logic rewrite.

## 1. Purpose

This file is the canonical execution plan for the Flutter V1 polish wave.

The target is a deliberate mix of:

- **Clean Modern UI** — contemporary, restrained, coherent and visually distinctive.
- **High Usability** — fast field work, obvious next action, Arabic-first hierarchy, outdoor readability, one-handed operation where practical, and clear degraded/offline states.

Every polished screen must preserve the accepted FIELD functions frozen in:

- `design/wanasah_v1/FIELD_FUNCTION_SURFACE_MAP.md`
- `FLUTTER_V1_END_TO_END_CLOSURE_PLAN.md`
- `ARCHITECTURE.md` §12
- `.rules`
- `AGENTS.md`

## 2. Non-negotiable polish rules

- [x] Polish is **screen-by-screen**, not a full Flutter rewrite.
- [x] Structural cleanup happens in the same owned slice when it materially improves single responsibility or safe growth.
- [x] File count is not a quality metric. Split real responsibilities only; do not create files merely to reduce line counts.
- [x] Existing Backend/Flutter business contracts remain frozen unless a proven defect requires a narrow fix.
- [x] No approved FIELD action may disappear because a cleaner visual hierarchy hides it.
- [x] Figma and other external design tools are optional references only; no external design service may become a V1 delivery dependency.
- [x] Material visual-direction changes are reviewed before production implementation.
- [x] Connectivity, service failure, pending sync and blocked recovery are distinct operator states.

## 2A. Localization / multi-language foundation — APPROVED

The current production Flutter app is still Arabic-only at runtime, even though some newer presentation helpers already contain Arabic/English copy. Multi-language readiness must be fixed **before more UI polish spreads hard-coded text**.

- [x] Arabic remains the current V1 default/fallback language.
- [x] The architecture must allow adding another language without editing every screen/widget.
- [x] User-visible copy must not be hard-coded inside new polished widgets.
- [x] **All Flutter screens and all user-visible states are in scope for localization**, not only the shared shell or newly redesigned screens. Existing hard-coded Arabic is migrated as each screen enters its polish slice, and no screen is considered polish-complete while touched user-facing copy remains outside the canonical localization system.
- [x] Dialogs, validation messages, empty/loading/error states, tooltips, accessibility/semantics labels, sync/recovery copy and action confirmations are part of localization coverage just like visible page text.
- [x] Use one canonical Flutter localization system for production UI copy. Prefer Flutter generated localization (`gen_l10n` + ARB resources) or an equivalently centralized typed solution; do not keep growing parallel ad-hoc maps per feature.
- [x] Existing `AppCopy`, Visit string helpers and Recovery string maps are migration inputs, not justification for permanent competing localization systems.
- [x] RTL/LTR is part of the foundation:
  - use directional padding/alignment where direction matters;
  - directional navigation icons/actions must remain semantically correct;
  - layouts must survive both Arabic RTL and future LTR locales.
- [x] Dates, numbers and currency values must be formatted through locale-aware formatting rather than embedded language-specific text assumptions.
- [x] Adding a future locale should primarily mean adding translation resources + enabling the locale, not rewriting screen structure.
- [x] Do not globally switch the app to English until the touched V1 surfaces have complete translation coverage; mixed-language production UI is not acceptable.
- [x] Create the canonical localization resource structure and app-level locale wiring.
- [x] Migrate the shared shell/Home/Recovery copy introduced by the shell slice into that canonical system.
- [x] Add Arabic RTL + English LTR widget coverage for the shared shell before the next major polish slice.
- [x] Implementation proof: `gen_l10n` regenerates without localization drift; `flutter analyze` passes; focused Shell/Recovery/observability/bootstrap/composition tests pass **53/53** on the localization branch.
- [ ] Continue migration screen-by-screen as each surface is polished; no newly polished screen may introduce new hard-coded operator copy.
- [x] Home + Work Session presentation copy migrated into canonical ARB/gen_l10n resources as part of the Home polish slice.

## 3. App shell and primary navigation — APPROVED

### 3.1 Bottom navigation

The representative shell uses **three persistent primary tabs**:

1. **الرئيسية — Home**
2. **خط السير — Route & Visits**
3. **العهدة — Custody**

- [x] These three tabs are the V1 primary navigation.
- [x] Do not add a fourth bottom-tab merely to expose every secondary function.
- [x] The bottom navigation is persistent on the three top-level sections.
- [x] Physical order is intentional and direction-aware: **Route on the leading side, Home in the center, Custody on the trailing side**. In Arabic RTL this renders **خط السير يمين — الرئيسية وسط — العهدة يسار**.
- [x] The primary navigation uses a **floating translucent/glass-inspired dock** with restrained blur, depth and rounded grouping; it must remain highly legible and field-usable rather than decorative glass for its own sake.
- [x] Home is the visually emphasized center destination. Route/Custody use quieter active surfaces; active state must be recognizable by icon/shape/weight, not color alone.
- [x] Because Route and Custody are persistent bottom destinations, Home must not repeat generic **"open Route"** or **"open Custody"** buttons. Home only keeps contextual next-action shortcuts when they add information beyond navigation.
- [x] Deep task flows such as Visit execution, Add Shop, confirmation dialogs and other mutation-heavy screens may hide the bottom navigation when doing so protects focus/unsaved work.
- [x] The persistent dock must never cover Route/Add Shop or other tab content. Shell layout reserves its vertical space; the dock stays visually floating but is not an overlay over tappable content.
- [x] Keep the dock compact and as low as the Android safe area permits; do not consume extra bottom whitespace beyond the system inset.
- [ ] Implement the shared shell and preserve existing navigation/back-safety behavior.

### 3.2 Global top-level utilities

- [x] **Synchronization status is not a bottom tab.**
- [x] A small persistent sync/system indicator lives in the top app chrome where practical and opens the Sync Center.
- [x] Profile/logout remains a small global utility rather than a primary bottom tab.
- [ ] Implement global top-level utilities consistently across the three primary sections.

## 4. Home — الرئيسية

### 4.1 Role of the screen

Home is the representative's **workday command center**, not a dumping ground for every detail.

The first question it should answer is:

> What is my current workday state, and what should I do next?

### 4.2 Required V1 content

- [x] Work Session controls remain visible and easy to understand:
  - start work;
  - end work;
  - start break;
  - end break.
- [x] Keep representative identity available in the global account utility; Home does **not** repeat a large greeting/name block. Show current assigned region and date compactly.
- [x] Show today's Visit progress in a compact visual form:
  - total/assigned;
  - completed;
  - remaining;
  - successful sales where useful.
- [x] Show financial summary without pretending to own accounting authority:
  - cash sales;
  - prior-debt collections;
  - total cash currently attributable to the representative/session from the accepted Backend state.
- [x] Show clear workday timing:
  - session start time;
  - elapsed time since start.
- [x] **Remaining shift time is shown only if an authoritative schedule/expected-end contract exists.** Do not invent a countdown from UI assumptions.
- [x] Important required-action evidence may interrupt the normal summary hierarchy:
  - pending transfer decision;
  - blocked Recovery item;
  - material sync problem;
  - session/custody prerequisite.
- [x] A compact end-of-day **read-only summary** may be shown before/after ending work:
  - current cash expected for handoff;
  - remaining custody;
  - pending returns;
  - unresolved sync/recovery evidence.
  This is not Backoffice settlement authority.
- [ ] Redesign the current Home around task priority and fast scanning.
- [ ] Owner visual acceptance pending for the first production Home polish candidate: day identity, Work Session command surface, route progress and financial pulse. Keep this open until reviewed on the owner's device.
- [x] Owner refinement 2026-10-24: the large greeting/name block is removed; inactive Work Session is reduced to status + primary action; redundant motivational/help copy is removed.
- [x] Work Session business refusals are transient operator notifications, not persistent inline panels. Safe Backend business detail may explain the refusal; HTTP codes/request ids stay diagnostic-only and are not rendered in the normal operator message.

- [ ] Ensure the current financial/Visit/custody data remains semantically identical after the visual restructure.

## 5. Route & Visits — خط السير

### 5.1 Approved navigation move

- [x] The current **"عرض قائمة زيارات اليوم"** entry is promoted from a Home button into the dedicated bottom tab **خط السير**.
- [x] The existing Visit List behavior remains the functional base; polish may reorganize it but must preserve its accepted actions.

### 5.2 Required V1 content

- [x] Today's normal route.
- [x] Urgent requests.
- [x] All / completed / remaining filters.
- [x] Visit statuses: pending, attempted, postponed, no-sale, completed and safe unknown fallback.
- [x] Shop/customer balance context.
- [x] Open shop location in maps.
- [x] Open Visit.
- [x] Add Shop.
- [x] Refresh/sync route data with existing offline/local protection.
- [x] Break/authorization gates remain enforced and understandable.

### 5.3 Completed Visit / invoice access

- [x] Completed Visit details and committed invoice remain reachable **from the original Visit/route record**.
- [x] Any legitimate correction starts from the original completed Visit context and existing `visit.execute`/business guards; there is no generic financial-history edit button.
- [x] A list/history view in V1 is read-oriented. It must never invent a new correction authority.
- [ ] Polish route priority, next-stop clarity, urgent work and completed-history readability.
- [x] First production Route & Visits candidate implemented without changing Backend ordering or authority: modern route/urgent switch, compact counts/filters, field-scannable Visit rows, visual `التالي` marker for the first Backend-ordered Pending normal Visit, restrained urgent accent, and extended Add Shop action.
- [x] Route & Visits presentation copy migrated from manual Arabic/English maps to the canonical ARB/gen_l10n source; the existing helper is now only a typed adapter.
- [x] Visit-list operator feedback no longer appends request IDs to normal SnackBars; request identity remains diagnostic/support evidence.
- [ ] Owner visual acceptance pending for the first Route & Visits polish candidate after on-device review.

## 6. Custody — العهدة

### 6.1 Role of the screen

Custody is the representative's **live physical responsibility view**.

### 6.2 Required V1 content

- [x] Vehicle sellable inventory.
- [x] Starting/received quantities where currently available.
- [x] Sold quantities.
- [x] Remaining quantities.
- [x] Non-sellable custody.
- [x] Pending local return custody.
- [x] Damaged/expired/factory-defect custody evidence where applicable.
- [x] Pending management transfers.
- [x] Accept/reject transfer decision flows and required rejection reason.
- [x] Batch transfer handling remains supported.
- [x] If an actual receipt/transfer-in event exists in the accepted current contract, surface it here; do not invent a new receiving workflow during polish.
- [ ] Move the current long Home inventory section into the dedicated Custody tab while preserving all accepted evidence and actions.
- [ ] Make required-action transfer/custody states impossible to miss.

## 7. Sync Center — مركز المزامنة والنظام

### 7.1 V1 decision

- [x] Sync Center is **V1** because visible durable/offline evidence is important for representative trust.
- [x] It is opened from the small persistent top sync/system indicator, not from a fourth bottom tab.

### 7.2 Indicator states

The compact global indicator should distinguish, at minimum:

- [x] synchronized / no pending work;
- [x] pending synchronization;
- [x] blocked evidence needing attention;
- [x] service/reachability degradation where cached data remains usable.

### 7.3 Center content

- [x] Show pending durable work in operator language and, where safely derivable, grouped/countable by business type such as:
  - Visits/invoices;
  - new Shops;
  - transfer responses;
  - other supported durable FIELD commands.
- [x] Show that local data is preserved when that statement is true.
- [x] Show blocked/rejected evidence separately from ordinary pending sync.
- [x] Show request/tracking identity only as support detail, not as the main operator message.
- [x] Safe actions may include:
  - retry/recovery through the existing canonical engine;
  - navigate to the original Visit/entity when a correction belongs there;
  - refresh/re-read;
  - explain that Backoffice/admin intervention is required.
- [x] Do **not** provide arbitrary payload editing or a generic "fix server conflict" editor.
- [x] A rejected Visit that legitimately needs correction returns the representative to the original Visit workflow; correction authority does not move into Sync Center.
- [ ] Design and implement the Center on top of existing Recovery/Sync evidence without creating a second sync engine.

## 8. Deferred fourth tab — NOT V1

A standalone bottom tab for:

**المالية / الحركات / التسوية — Transactions & Ledger / Settlement**

is **not part of Flutter V1**.

V2 may consider a representative financial/history workspace for:

- today's invoices and returns;
- read-only movement/history views;
- re-opening/viewing committed invoice details;
- print/share/reprint support when a real printing contract exists;
- navigation back to the original Visit for an authorized correction;
- read-only end-of-day handoff summary.

Actual physical receiving, representative settlement/reconciliation and financial close remain Backoffice authority unless a later explicit architectural decision changes that boundary.

Canonical V2 entry: `VERSION_2_FUTURE_FEATURES.md`.

## 9. Screen polish order

Execute in this order unless a proven dependency requires a narrow adjustment:

1. [ ] Shared shell: bottom navigation + top utilities + theme/foundation.
2. [ ] Home.
3. [ ] Route & Visits.
4. [ ] Custody.
5. [ ] Sync Center.
6. [ ] Visit execution and its commercial subflows.
7. [ ] Add Shop.
8. [ ] Login and startup surfaces.
9. [ ] Cross-screen empty/loading/error/degraded/recovery consistency pass.
10. [ ] Final visual/interaction consistency pass.

## 9A. Proportional test gates — APPROVED

Testing depth follows **behavioral risk**, not visual file count.

### Tier A — visual-only polish

Examples: spacing, typography, color, shape, hierarchy, icon placement, non-behavioral responsive layout.

Required before merge:
- [ ] `flutter analyze`
- [ ] focused widget/golden/layout tests for the touched surface
- [ ] RTL/LTR coverage when localized layout is touched

A full 500+ test suite and Android APK rebuild are **not automatically required for every visual-only iteration** unless CI policy or a discovered regression justifies them.

### Tier B — interaction / navigation / state wiring

Examples: bottom navigation, tab persistence, dialogs, Work Session controls, Recovery/Sync state wiring, route transitions, state-preservation behavior.

Required:
- [ ] `flutter analyze`
- [ ] focused behavioral tests
- [ ] relevant regression suites
- [ ] broader/full Flutter suite before integration when the changed shared boundary can affect multiple flows

### Tier C — business/offline/authority/release boundary

Examples: durable commands, replay, authorization, Visit mutation, Custody/transfer business behavior, Backend contract changes, final release checkpoint.

Required:
- [ ] focused domain tests
- [ ] full Flutter regression suite
- [ ] Android debug build when applicable
- [ ] Backend/integration evidence where applicable

**Model usage is separate from CI testing.** Expensive reasoning models are reserved for genuinely difficult architecture/design review, not routine implementation or repetitive visual iteration.

## 10. Per-slice execution contract

For every slice:

1. [ ] Re-read the exact function checklist in `FIELD_FUNCTION_SURFACE_MAP.md`.
2. [ ] Freeze the slice's current business behavior before editing.
3. [ ] Decide the visual/interaction hierarchy.
4. [ ] Perform only the useful structural cleanup needed in that owned area.
5. [ ] Implement without moving Backend authority into Flutter.
6. [ ] Add/update focused tests for changed behavior/state wiring.
7. [ ] Run `flutter analyze`.
8. [ ] Run focused Flutter tests.
9. [ ] Run the required broader Flutter gate before merge.
10. [ ] Independent review before merge.
11. [ ] Mark implementation checkbox `[x]` only with evidence.
12. [ ] Merge to `main`, remove the completed branch, and fast-forward the owner checkout.

## 11. Final V1 exit

After the polish wave and launch-critical Dashboard work are ready:

- [ ] run comprehensive physical Android acceptance against the current Backend;
- [ ] verify Flutter actions against Backend/Dashboard evidence;
- [ ] fix only proven release blockers;
- [ ] complete final P1–P9 / FIELD acceptance sign-off;
- [ ] declare Flutter V1 complete.
