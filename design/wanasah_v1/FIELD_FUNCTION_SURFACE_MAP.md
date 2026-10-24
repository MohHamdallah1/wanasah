# WANASAH Flutter V1 — FIELD Function Surface Map

**Frozen audit date:** 2026-10-24  
**Source:** current `main` at `4b957d9b25725e2e3237344d79530d99ceb2b3e7` before this documentation-only audit commit.

## Purpose

This is the mandatory functional checklist for Flutter V1 polish. It answers one question:

> For every current V1 FIELD capability/route intended for the representative, where does the representative see or use it in Flutter?

The whole Wanasah Backend is **not** meant to appear in Flutter. Dashboard, warehouse, settlement and other Backoffice functions remain outside the representative app unless the V1 FIELD contract explicitly requires them.

## Audit result

**No currently approved V1 FIELD function intended for the representative was found without a Flutter operator path or supporting integration.**

Two Backend routes intentionally do **not** become standalone Flutter screens:

1. `GET /product_variants` — catalog/pricing support exists, but the current authoritative FIELD catalog projection used by the Visit flow is delivered through `GET /driver/visits`. Do not invent a duplicate catalog screen merely because this endpoint exists.
2. `POST /driver/session/{session_id}/reconcile` — end-of-session reconciliation/settlement is intentionally a Dashboard/Backoffice flow after the representative ends the Work Session. Flutter preserves the session/custody evidence; it does not own the physical receiving/financial close screen.

## 1. Startup / authentication

### Visible screen: Login

Representative functions:

- company code;
- username;
- password;
- login progress and failure feedback.

Backend/integration:

- `POST /driver/login` — visible login action.
- `POST /refresh` — supporting token lifecycle; no standalone screen.
- `POST /logout` — visible logout action from the app shell/home.
- canonical FIELD identity persists principal, representative, company and legacy operational locator identities separately.

**Polish rule:** login can be simplified visually, but company code + username + password remain explicit inputs unless the authentication contract later changes.

## 2. Home / representative workday

### Visible screen: Dashboard / Home

Representative functions/states already present:

- representative name;
- assigned region;
- current date;
- refresh;
- logout;
- Work Session status;
- start work;
- end work;
- start break;
- end break;
- active-session recovery after restart;
- visit summary: completed, successful sales, pending and offline/pending-sync visits;
- financial summary: cash sales, collected debt and total received cash;
- entry to today's visits;
- vehicle sellable inventory;
- non-sellable custody;
- local return-custody evidence waiting for sync/processing;
- pending transfer handshake surfaced for operator decision;
- Recovery/Sync pending/blocked evidence;
- distinct connectivity/service refresh degradation while cached data remains usable.

Backend/integration:

- `GET /driver/dashboard`
- `GET /driver/sessions/active`
- `POST /driver/sessions/start`
- `PUT /driver/sessions/end`
- `PUT /driver/sessions/break`
- `GET /driver/custody`
- `GET /driver/transfers/pending`
- `PUT /driver/transfers/{transfer_id}/respond`
- `PUT /driver/transfers/batch_respond`

Supporting local infrastructure:

- Recovery snapshot/read;
- durable pending/blocked command evidence;
- existing synchronization engine.

**Polish rule:** this screen should become task-first. Do not remove custody, transfer, recovery, session or degraded-service evidence simply because they are visually secondary in the current layout.

## 3. Today's route / Visit list

### Visible screen: Visit List

Representative functions/states already present:

- normal **today route** tab;
- **urgent requests** tab;
- filters: all / completed / remaining;
- statuses including completed, pending, attempted, postponed, no-sale and unknown fallback;
- customer balance display;
- open shop location in maps;
- refresh/sync list;
- open Visit;
- add new Shop;
- action gate while on break;
- authorization/unavailable-state feedback;
- local-data protection when unresolved offline work blocks remote replacement.

Backend/integration:

- `GET /driver/visits` — authoritative route/Visit projection and current FIELD catalog projection.
- Visit opening later reads `GET /visits/{visit_id}`.

**Polish rule:** route priority, next action, urgent work and remaining work must become easier to scan than in the current list. Map/open/add-shop actions remain reachable.

## 4. Add Shop

### Visible screen: Add Shop

Current representative inputs/actions:

- shop name — required;
- contact person — required;
- governorate / area / route — required;
- location link or current-location capture;
- phone — required and validated;
- notes — optional;
- save Shop;
- result feedback including commercial readiness returned by the accepted creation flow.

Backend/integration:

- `POST /shops`

**Polish rule:** reduce form friction without silently removing required fields or location capture.

## 5. Visit execution / commercial work

### Visible screen: Visit

This is the densest FIELD screen and must be treated as several clear interaction sections while preserving one Visit workflow.

### Visit/customer context

- shop name;
- current balance/debt context;
- Visit status;
- cached/durable draft restoration;
- unsaved-change protection;
- committed Visit/invoice re-read where applicable.

Backend/integration:

- `GET /visits/{visit_id}`

### Product catalog / quantities

- search products;
- sale quantity by cartons and packs;
- current vehicle/catalog projection;
- confirm quantities and return to invoice/work area.

Catalog source:

- current Visit catalog comes from the authoritative `GET /driver/visits` projection.
- `GET /product_variants` is not a missing standalone Flutter feature.

### Samples

- sample cartons/packs;
- sample reason;
- predefined reasons plus free-text “other”.

### Returns

The UI supports all approved V1 return reasons, each with cartons/packs:

- damaged;
- expired;
- factory defect.

Where Backend resolution needs ambiguity evidence, Flutter presents the evidence chooser rather than guessing.

Backend/integration:

- `POST /visits/{visit_id}/return-resolution`

### Money / debt / notes

- cash collected;
- prior debt collected;
- safe numeric validation;
- notes.

### Visit outcome

Submission supports:

- `Sale`;
- `NoSale`;
- `Postponed`.

Sale/NoSale is not inferred only from visual state; the accepted action validation remains authoritative.

### Commercial readiness and invoice

For a sale:

- commercial readiness check;
- invoice preview;
- explicit confirmation;
- committed invoice read/display after mutation.

Backend/integration:

- `GET /visits/{visit_id}/commercial-state`
- `POST /visits/{visit_id}/invoice-preview`
- `GET /visits/{visit_id}/invoice`

### Final Visit mutation / offline durability

Backend/integration:

- `PUT /visits/{visit_id}`

Flutter already owns:

- durable local command identity;
- offline save;
- restart recovery;
- exact replay/reconciliation behavior;
- pending/blocked evidence instead of silent loss.

**Polish rule:** do not present this as one giant form. The visual/interaction redesign should expose the operator's current step clearly while preserving Sale, NoSale, Postponed, collection, samples, three return reasons, readiness, invoice and offline evidence.

## 6. Custody and transfers

### Visible surfaces

Currently surfaced primarily from Home:

- sellable vehicle inventory;
- sold/remaining quantities;
- non-sellable custody;
- pending local return custody;
- blocked/pending custody evidence;
- management transfer dialog;
- per-transfer accept/reject;
- rejection reason;
- batch submission;
- defer/close without fabricating a decision.

Backend/integration:

- `GET /driver/custody`
- `GET /driver/transfers/pending`
- `PUT /driver/transfers/{transfer_id}/respond`
- `PUT /driver/transfers/batch_respond`

**Polish rule:** custody can move into a cleaner expandable/secondary surface if appropriate, but transfer decisions and blocked evidence must remain impossible to miss when action is required.

## 7. Recovery / synchronization

This is a cross-screen concern, not a separate business module the representative must understand technically.

Visible operator states include:

- nothing pending;
- pending synchronization;
- blocked evidence needing attention;
- read unavailable;
- sync in progress;
- success;
- ambiguous transport result;
- deterministic failure.

**Polish rule:** translate these into practical operator language. Never collapse “device/network unavailable”, “service failure” and “pending local work” into one generic offline banner.

## 8. Backend FIELD routes that are supporting rather than standalone screens

| Backend route | Flutter treatment |
| --- | --- |
| `GET /driver/dashboard` | Supplies Home state; not a separate feature by itself. |
| `GET /driver/sessions/active` | Restores Work Session state; no separate screen. |
| `POST /refresh` | Authentication lifecycle only. |
| `GET /product_variants` | No standalone screen; Visit catalog currently comes from `GET /driver/visits`. |
| `POST /driver/session/{session_id}/reconcile` | Intentionally Backoffice/Dashboard settlement, not Flutter. |

## 9. Screen order for polish

Recommended order because later screens reuse decisions from earlier ones:

1. Login / app shell basics.
2. Home / Work Session / Recovery / transfer alert hierarchy.
3. Visit List / route execution.
4. Visit execution — split visually into clear steps/sections.
5. Add Shop.
6. Custody/transfer detailed surfaces and dialogs.
7. Cross-screen empty/loading/error/offline/service/pending-sync states.
8. Final consistency pass across typography, spacing, controls and interaction feedback.

Each screen is polished **with its existing functional checklist open**. A function may be reorganized, collapsed, surfaced contextually or moved to a better owned component, but may not disappear.
