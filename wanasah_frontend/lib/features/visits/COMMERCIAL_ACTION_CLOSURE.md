# Visit commercial action correctness

Frozen workflow: field Visit sale / no sale / samples / exchange / prior-debt
collection / postponement / completed correction. No new business capability.
Audited immutable base: c0c02bc450d0043ad86d242f4ceea2c1c886fc23.

## Current Backend contract matrix

Source authority: wa_backend/schemas.py VisitItemInput, ResolvedVisitReturnInput,
VisitUpdateRequest; wa_backend/api/driver.py update_visit; domains/field_operations/
invoice.py. The FIELD CI executes the current schema matrix, plus existing
test_field_return_resolution.py and test_field_read_contracts.py.

| Action | Canonical contract |
| --- | --- |
| Sale | Completed; at least one positive sold carton or pack. Samples/returns alone cannot constitute Sale. |
| NoSale | Completed; no sold quantity and no sale cash. Samples, all three return reasons and prior-debt collection can coexist. Without samples/returns, notes are required, including collection-only. |
| Postponed | Pending; no cart, returns, cash or debt collection. Notes optional. |
| Samples | Nonnegative integer cartons/base packs, positive combined quantity when no sale quantity; nonblank reason required only when samples are positive, maximum 255 characters. |
| Returns | Damaged / Expired / Factory_Defect; positive combined carton/pack quantity; signed resolution revalidated by Backend. UI never supplies raw Batch locator. |
| Debt | Nonnegative exact decimal input; Backend checks actual prior balance, credit policy and bounds. Flutter never validates against cached balance. |
| Bonus/reward | Backend resolves offers and reward quantities; nonzero client bonus rejected by schema. |
| Prices/tax/invoice | Strict cart rejects price fields; existing calculator owns prices/offers/taxes/rounding/currency. Preview is not reservation/credit approval/commit. Frozen invoice uses immutable revision. |
| FEFO | Backend allocates AVAILABLE stock internally after locks and provenance checks; no client sale Batch selection. |
| Correction | Completed Visit reverses prior evidence and applies replacement in one Backend transaction. Same UUID/body replays before reversal; new correction only after previous result resolved. |

Backend tests inspected: test_field_contracts_postgres.py (real invoice, all three
returns, custody and lost-response replay), test_costed_driver_sale_correction_real_c2_db.py
(real Sale to NoSale correction with one reversal for FIFO and moving average),
test_field_read_contracts.py (calculator/exact frozen evidence/lock order),
test_field_return_resolution.py (signed proof, ambiguity, provenance).

## Already satisfied at the base

Canonical status mapping, price-free payloads, Backend FEFO and reward authority,
exact money transport, readiness/preview/frozen separation, all three return
reasons, opaque return evidence, staged UUID before first send, blocked/unresolved
correction guard, draft restoration after rejection and durable old-to-new
projection were already implemented. They remain in the regression suite.
Cached line/footer totals already say estimate; no price/debt comparison gates
submission. Exact frozen/preview evidence remains separate from legacy doubles.

## Actual fixes

- VisitSubmissionService validates canonical action shape before its existing
  save port. NoSale cash and Postponed actions previously disappeared through the
  compatibility serializer; they now produce typed refusal before staging.
- Positive sold quantity and sample reason checks apply to application callers,
  including callers bypassing presentation. Invalid/duplicate quantities and
  schema note/reason limits fail closed. No stock, credit or pricing engine added.
- Confirmation uses the same policy before Backend reads and no longer invents
  a NoSale reason or infers shop closure from Postponed.
- Completed collection-only recovery restores money and notes regardless of cart
  JSON presence. The false instruction to refund all old cash was replaced with
  a neutral correction notice; Backend acceptance remains authoritative.

No SyncRepository, local database, projection, identity, Session, Transfer,
Custody, Visit List, design-system/theme, Dashboard web or Backend production
changes. Screen changes only correct recovery/input behavior and existing text;
no visual redesign. The closure plan is unchanged.

## Validation

The existing FIELD workflow checks out the exact PR head and runs flutter analyze,
all Visit FIELD tests, Custody regressions, Offline durable/owner regressions,
Visit correction/decomposition and pending-return/local-projection regressions.
Additional Backend job is read-only: existing tests plus 9 accepted and 17 rejected
schema cases, with no database or Backend source mutation.

New focused coverage includes action combinations, no silent input stripping,
zero Sale quantity, sample quantities/reasons, exact debt, cache price independence
(including zero/NaN/infinity), server rejection/no retry, blocked correction,
human NoSale reason and Postponed behavior. Existing ambiguity/opaque-token,
preview/frozen, replay and projection tests remain required.
