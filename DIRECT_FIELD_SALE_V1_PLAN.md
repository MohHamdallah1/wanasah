# DIRECT FIELD SALE V1 PLAN

**Status:** OWNER-APPROVED V1 SCOPE — PLANNED, NOT IMPLEMENTED  
**Owner decision:** 2026-10-25  
**Scope:** Direct / walk-up cash sales by a field representative from vehicle custody without creating a fake Shop or fake Visit.  
**Canonical authorities:** `.rules`, `AGENTS.md`, `ARCHITECTURE.md`, `V1_SCOPE_FREEZE.md`, inventory/costing/pricing/field-operation contracts.

---

## 1. Business problem

A field representative may be stopped while working by a walk-up customer who wants to buy goods directly from the representative's vehicle.

This is a legitimate sale, but it is **not** a normal Shop Visit:
- the buyer may not be a registered Shop;
- the buyer may never buy again;
- creating a fake Shop or fake Visit would pollute customer, route, reporting, tax and commercial data;
- the sale still changes vehicle custody, cash, revenue, tax, offers, COGS and end-of-day accountability.

V1 therefore requires one explicit **Direct Sale / بيع مباشر** workflow in the field application.

---

## 2. User experience boundary

### Field application

Add one small, obvious action named:

**بيع مباشر**

The action is available only while the representative has an authorized active work context with an assigned vehicle custody source.

It does **not** require:
- selecting a Shop;
- creating a Shop;
- creating a fake Visit;
- exposing Batch IDs, cost layers, tax internals or pricing internals.

The representative selects products/quantities, reviews the resolved total, records the cash received, and confirms.

### V1 payment boundary

Direct Sale is **cash-only in V1**.

V1 does not add:
- customer debt;
- credit sales;
- old-debt collection;
- customer balance;
- cash refunds;
- generic anonymous-customer accounts.

If the buyer should become a recurring business customer, the representative uses the supported Shop creation workflow and future sales use normal Visit/Shop authority.

---

## 3. Pricing decision — same engine, not necessarily the same price

Direct Sale MUST use the same authoritative backend pricing engine as normal sales.

This does **not** mean Direct Sale must use the same price as a Shop.

V1 must support one company-controlled Direct Sale pricing profile with an explicit pricing audience/mode:

- **STANDARD / SHOP** — use the company's normal supported shop/base selling-price context; or
- **RETAIL / مفرق** — use the company's configured retail/direct-consumer price context.

Rules:

- The company chooses the Direct Sale pricing mode; the field representative does not choose it per sale.
- The representative must not manually invent or override a price unless an already-approved pricing permission/workflow explicitly supports that action.
- Do not create a second ad-hoc pricing engine.
- Reuse authoritative price publication/versioning, rounding, currency and commercial evidence.
- If the existing pricing domain does not yet have a clean retail audience/profile at implementation time, add the **smallest canonical pricing-context extension** needed by this V1 workflow rather than adding a Direct Sale-only price table.
- Missing required Direct Sale pricing configuration must fail closed with an actionable operator message; never guess a price.

---

## 4. Tax and offers

Direct Sale uses the same authoritative tax and offer engines, but with a Direct Sale commercial context rather than a fake Shop.

V1 requirements:

- one company-authorized Direct Sale tax/jurisdiction context sufficient for the supported deployment;
- no geographic or tax guess by the representative/device;
- deterministic backend resolution;
- offers/promotions are evaluated through the existing offer authority using the Direct Sale commercial profile;
- if the company policy excludes a promotion audience from Direct Sale, the backend must enforce that explicitly;
- missing mandatory tax/commercial configuration fails closed before posting.

The implementation must not fabricate a Shop merely to obtain tax, offer or price context.

---

## 5. Inventory, Batch and custody

The physical source is the representative's currently authorized **VEHICLE custody location**.

The representative never selects a technical inventory location or Batch ID.

Backend responsibilities:

- resolve the exact authorized work session / route / vehicle custody;
- revalidate that vehicle custody is operational and belongs to the current representative/work context;
- allocate inventory through the same FEFO/Batch authority used by supported field sales;
- reject unavailable, expired, recalled, blocked or otherwise non-sellable stock;
- create the authoritative outbound physical inventory movement;
- preserve Batch provenance and stock-status truth;
- never write InventoryBalance directly;
- never allow the sale to consume another representative's or vehicle's custody.

No Direct Sale may silently create stock or make negative vehicle inventory.

---

## 6. Product lifecycle and safety

Direct Sale is a **new sale**, so all normal new-sale lifecycle/safety gates apply.

A product/Batch that becomes:
- stopped for sale;
- SALES_HOLD;
- RECALL;
- blocked;
- quarantined/non-sellable;
- expired or below the authoritative sellability threshold

must not be newly sold through Direct Sale.

There is no Direct Sale-specific bypass.

---

## 7. Costing and financial truth

Direct Sale MUST use the existing authoritative inventory costing/COGS engine.

Required evidence includes:

- physical vehicle stock reduction;
- immutable sale evidence;
- authoritative resolved price;
- discounts/offers;
- tax;
- rounding/currency;
- COGS based on the active company costing method;
- gross/revenue evidence needed by the current reporting authority;
- exact linkage between the sale and inventory/cost evidence.

No Direct Sale-specific cost calculation is allowed in Flutter.

---

## 8. Cash and end-of-day settlement

Direct Sale cash belongs to the representative's active work-session cash accountability.

Therefore:

- confirmed Direct Sale cash increases the expected cash for that work session;
- end-of-day settlement includes normal Visit cash + debt collection where applicable + Direct Sale cash + other already-authorized session cash components;
- retry/replay must not double-count cash;
- the dashboard/settlement evidence must distinguish Direct Sale from Visit sale without requiring a fake customer.

V1 Direct Sale has no debt.

---

## 9. Commercial document / receipt

A confirmed Direct Sale must create a durable commercial document/evidence record.

User-facing buyer label may be:

**عميل نقدي**

This label is presentation, not a fake persistent Shop.

The receipt/document must retain the same authoritative commercial snapshots required by normal sale evidence.

A Direct Sale must remain independently auditable after:
- price changes;
- tax changes;
- offer changes;
- product rename;
- later route/session closure.

---

## 10. Identity, authorization and isolation

Required runtime authority:

authenticated FIELD principal  
+ FIELD access channel  
+ Direct Sale / sale execution capability  
+ current assigned work/session/vehicle custody  
+ company isolation  
→ decision.

Rules:

- no generic admin/driver boolean authority;
- no trust in IDs supplied by Flutter when backend can derive them;
- no cross-company or cross-vehicle access;
- direct API calls must enforce the same rules as the UI;
- the field representative must not choose another representative, vehicle, warehouse or company.

If a new capability code is necessary, it must be added to the canonical capability catalog and V1 FIELD-assignable contract deliberately; do not infer authority from role names.

---

## 11. Idempotency, offline and recovery

Direct Sale is a durable mutation and MUST satisfy the same failure model as Visit sale:

- one stable request/operation UUID per logical sale;
- same UUID + same body is replay-safe;
- same UUID + different body fails closed;
- timeout/lost response does not cause a fresh logical sale;
- Flutter preserves the pending command and local draft;
- offline submission/replay uses the existing exactly-once foundation;
- ambiguous outcome is reconciled from server evidence;
- no duplicate inventory, cash, sale or COGS effects.

Direct Sale must be included in existing recovery UX rather than inventing a second recovery system.

---

## 12. Proposed domain boundary

Direct Sale is a first-class field sales command/document, not a Shop Visit.

It should reuse shared public/domain authorities for:

- pricing;
- offers;
- tax;
- sales calculation;
- inventory allocation/movement;
- costing;
- idempotency;
- work-session/custody;
- immutable sales evidence.

Do not copy Visit business logic into a second giant handler.

The implementation should extract/reuse canonical sales application/domain services where necessary while preserving existing Visit contracts.

---

## 13. Dashboard/reporting minimum

V1 does not require a new large Dashboard page just for Direct Sale.

Minimum integration:

- session/representative totals include Direct Sale;
- sales reporting can distinguish Direct Sale from Shop Visit sale;
- settlement shows the cash contribution correctly;
- audit/recovery can identify the Direct Sale document;
- normal inventory ledger shows the physical sale movement through canonical evidence.

Any advanced anonymous-customer analytics are V2.

---

## 14. Flutter minimum UX

V1 target:

1. representative is in an active authorized work context;
2. taps **بيع مباشر**;
3. searches/selects saleable products from current vehicle custody;
4. enters quantities using supported UOM behavior;
5. backend-authoritative preview shows price, offers, tax and final total using the company's Direct Sale pricing profile;
6. representative enters/confirms cash received;
7. confirms once;
8. success shows a simple receipt/confirmation and updates local custody/cash projection;
9. offline/ambiguous outcomes use the existing recovery model.

The workflow must remain fast and usable with one hand in the field.

---

## 15. Explicit V1 non-goals

Direct Sale V1 does not include:

- anonymous-customer debt;
- credit terms;
- customer account creation;
- loyalty/customer CRM;
- arbitrary representative price negotiation;
- manual tax selection;
- manual Batch selection;
- separate Direct Sale inventory;
- fake Shop creation;
- fake Visit creation;
- cash refund;
- generalized POS/storefront module;
- receipt printer ecosystem beyond existing supported output capabilities;
- advanced retail analytics.

---

## 16. Implementation phase and order

This feature is **approved for V1 but intentionally deferred from the current Inventory Transfers task**.

Implement it when work returns to the **FIELD / Flutter sales closure** and before final Flutter/V1 production acceptance.

Required implementation tracks:

### Backend
- [ ] finalize Direct Sale command/document contract;
- [ ] add/extend canonical Direct Sale commercial pricing profile (STANDARD/SHOP vs RETAIL);
- [ ] resolve tax/offer context without a fake Shop;
- [ ] reuse field work-session and vehicle custody authority;
- [ ] reuse authoritative sale calculation and immutable evidence;
- [ ] post FEFO inventory movement + COGS atomically;
- [ ] include Direct Sale cash in session settlement;
- [ ] add idempotent replay/reconciliation;
- [ ] add authorization/isolation/negative tests;
- [ ] add costing/pricing/tax/offer/inventory acceptance evidence.

### Flutter
- [ ] add small **بيع مباشر** entry action;
- [ ] product selection from current vehicle custody;
- [ ] authoritative commercial preview;
- [ ] cash-only confirmation;
- [ ] offline draft/queue/replay/recovery;
- [ ] update local vehicle-custody and cash projections;
- [ ] receipt/confirmation UI;
- [ ] Arabic/English localization and keyboard/accessibility equivalents where applicable.

### Acceptance
- [ ] STANDARD/SHOP pricing company works correctly;
- [ ] RETAIL pricing company works correctly;
- [ ] same product can resolve different Shop vs Direct Sale prices according to company policy without duplicating pricing authority;
- [ ] offers/tax are authoritative;
- [ ] exact vehicle Batch stock decreases once;
- [ ] COGS posts once under active costing method;
- [ ] cash settlement includes the sale once;
- [ ] same-request replay is no-op business-wise;
- [ ] lost-response/offline recovery does not duplicate;
- [ ] recalled/held/expired/non-sellable stock is blocked;
- [ ] cross-user/cross-company/cross-vehicle attempts fail closed;
- [ ] no fake Shop or Visit is created.

---

## 17. Completion rule

This plan is not complete merely because a Flutter button exists.

Direct Sale V1 is complete only when Backend + Flutter + inventory + pricing + tax + offers + costing + cash settlement + idempotency/recovery are proven end-to-end with authoritative evidence.

Every completed checklist item must be changed to `[x]` only after real evidence exists.
