# Wanasah — Purchase Cost Reference + Inbound Draft Closure

**Status:** RELEASE MERGED / LOCAL ONE-DASHBOARD RUNNING / Excel import cost extension and authenticated business field acceptance pending.
**Started:** 2026-10-21
**Local branch at handoff:** `sol/warehouse-empty-state-v2-note`
**Latest verified release:** main af05765c81644d6cbc1e9567dea03ec54bbb5368 (2026-10-21); original dirty worktree retained intentionally.
**Machine safety:** Never reset, clean, delete or overwrite the original dirty worktree. Owner-approved merges do not authorize destructive machine cleanup.

## 0. Scope and authority
- Owner-approved change: the **latest committed authorized purchase-cost entry**, whether from Product setup/edit or a successfully posted Inbound receipt, becomes **one company-wide, product-variant purchase-cost reference** shown in both screens.
- The reference is an operational suggestion for **the current/future receipt only**, NEVER historical or official financial inventory value.
- The actual supplier invoice line records the exact purchase UOM, entered actual unit cost and immutable receipt/cost evidence. Existing receipts/cost events are never retroactively rewritten.
- **Product sale prices / Price Book must remain independent**; no cost edit may change a sale price without a separate authorized pricing command.
- Inventory Costing is sole valuation and COGS authority (FIFO / MOVING_AVERAGE). No second accounting ledger, no cost-state edits via the new reference.
- Frontend and backend must stay i18n-ready, authorization-aware, company-scoped and precise with decimals; no cross-tenant leakage.
- Align V1 scope freeze and ARCHITECTURE with the approved bounded reference workflow before any cross-domain implementation, without broad V2 procurement features.

## 1. Canonical rules (contract freeze required before workers implement)
- [x] Model one canonical company/product-variant reference with explicit purchase UOM, currency, amount, revision, attribution, timestamp and source (Product edit vs posted purchase).
- [x] Use server-committed ordering, not client timestamps; protect concurrent manual edits vs receipts by revision/transactional ordering, with an explicit conflict policy.
- [x] Product create/edit: optional reference cost; a successful authorized save updates reference immediately (no stock valuation mutation).
- [x] Inbound: show reference cost prefilled for the selected purchase UOM, preserve an operator's own edits; pencil enables direct editing.
- [x] Inbound writes the reference and audit INSIDE the same transaction as the immutable actual purchase cost/receipt, before the single commit. All effects become visible only after successful commit. Abandoned/rejected/rolled-back receipts update nothing; a committed receipt with lost HTTP response legitimately retains its reference and idempotent replay must never rewrite it.
- [x] Transaction boundaries / retry replay must be idempotent: one receipt cannot update reference twice or overwrite a more recent edit on replay.
- [x] Preserve the price/receipt snapshot at posting time. No retroactive changes to receipts, costs, COGS, profit, or posted invoices.
- [x] Purchase UOM is mandatory context: convert deterministically based on authoritative product UOM factor and exact Decimal math, and never show a carton amount as if it were per piece.
- [x] Maintain explicit cost-read and cost-write permissions, company scoping, audit trails; no UI-only access decision.
- [x] Existing products/last-purchase records remain unchanged during migration; establish a safe read fallback without destructive backfill.
- [x] Resolve Product Excel-import parity explicitly against the **frozen template** before adding any new column or changing metadata/validation.

## 2. Local UI / draft data-loss regression
- [x] Root cause located: `parseInboundDrafts` rejected intentional empty quantity/unfinished input and returned an empty map for a single failed row.
- [x] Repair recovery to accept bounded incomplete text and preserve valid other rows; focused unit and remount tests PASS (2026-10-21).
- [x] Prove unmount/tab-switch/remount and browser refresh preserve quantity, cost, LOT/dates, supplier, invoice reference and notes.
- [x] Ensure draft isolation between company/actor/location, including switching warehouse and returning.
- [x] Saved products beyond first catalog page are resolved by their exact IDs, rendered with saved cost/quantity and purchase UOM, and can post without loading the whole catalog; targeted UI test PASS (2026-10-21).
- [~] Explicit Reset clears selected draft including supplier (automated PASS); confirmed posting clears posted draft by existing path, final end-to-end confirmation pending.
- [x] Failed/ambiguous POST must preserve draft and stable request ID; never duplicate a receipt or silently erase a pending command.
- [x] Recoverable corrupt rows must not destroy unaffected rows; reject unreasonable local storage payload size safely.

## 3. Display / UX
- [~] Product create, table, display preferences and edit modal labels distinguish Sale Price explicitly (Arabic and English). Excel headers, parsing aliases, ten-column template and import wire contract are unchanged.
- [x] Product create/edit: optional clearly distinct **تكلفة الشراء المرجعية** field + source/UOM explanation.
- [x] Inbound: compact price + edit pencil, keyboard accessible, supports source and UOM clarity, no overwriting edits during catalog refresh.
- [x] No change to the existing hybrid date input, separate LOT/Production/Expiry columns, or keyboard-first single-row workflow.

## 4. Implementation ownership / dependencies
- **Lead:** contract freeze, plan, local draft repair, product price-label clarity, change-control, user visual acceptance, final integration.
- **Worker A (first):** read-only GitHub-based cross-domain cost authority audit, including immutable cost events, receipt transaction, permissions, UOM, concurrency, tests. NO writes.
- **Worker B (first):** read-only Product create/edit/import/Price Book contract audit and proposed minimal reference integration. NO writes.
- **Worker C (after contract freeze):** bounded Backend reference model/API + migration/tests on dedicated isolated GitHub branch; no overlap with local uncommitted Product search work.
- **Worker D (after Backend contract stable):** bounded Dashboard Product UI contract and tests on isolated branch; Inbound integration serialized with local branch edits.
- No worker may use or modify the user's existing main local repository/worktree, reset/clean it, or share write ownership. Preferred workers use GitHub-only branches after a frozen base snapshot is approved and available.
- Every handoff: exact base SHA, branch/PR, changes, checks, migration risk, known gaps. Lead independently reviews. NO MERGE.

## 5. Acceptance gates
- [x] Focused inbound draft recovery + navigation/reset + off-cursor product resolve + unsuccessful-post preservation tests PASS: 25/25 (2026-10-21).
- [x] Backend transactional/PostgreSQL acceptance: one UOM reference, revision conflict, cross-company denial, permission denial, source/author audit, migration safe.
- [x] Immutable posted costs and past receipts proven byte-for-byte unchanged by later reference edits.
- [x] FIFO / MOVING_AVERAGE financial inventory and COGS regressions PASS.
- [x] Supplier post retry/timeout/replay confirms one financial receipt and one reference update.
- [x] Purchase cost update never modifies Product Pricing / Price Book / sales price.
- [x] Product create/edit and receipt UX tests, Arabic/English, keyboard and UOM correctness PASS.
- [~] Dashboard production build PASS (2026-10-21, before final i18n label refinements); strict TS check PASS after edits; owner localhost visual acceptance PENDING.
- [x] Diff reviewed against all current local uncommitted work before commit/push; merge only with explicit owner approval.

## 6. STOP / escalation
Stop if new schema/domain ownership/permission semantics conflict with canonical architecture, a migration rewrites historical cost/receipts, implementation requires a new unapproved Excel column, or a branch overlaps uncommitted local work. Surface the exact risk to Owner/Lead before implementation.

## 7. Worker A audit accepted by Lead (2026-10-21) — NO COST IMPLEMENTATION YET

Audit source: GitHub commit `2be59f6066419ef1de0157c48adaf8c931bfbaf2`, read-only, with a separate lead check against the current local receipt handler, costing ADR and capability catalog. The worker did not examine uncommitted local changes or execute tests.

### Confirmed evidence / non-negotiable frozen separation
- [x] Receipt handler ends with one transaction: financial inventory movement/costing, supplier evidence, idempotency completion, then `db.commit()`. A reference change must join THAT same transaction, before commit, never in a second transaction.
- [x] Receipt cost history and FIFO layers/allocations are independent from an editable reference. `InventoryCostEvent` is immutable evidence. `InventoryCostState` is valuation, not a reference default. Neither may be edited by Product reference changes.
- [x] The existing `last_purchase_cost` Live Stock read is latest historical `PURCHASE_IN` by event time/id and may be null when no stock exists. Retain its meaning; do not alias to mutable reference.
- [x] Product sale-price creation and `pricing.manage` are separate from purchase-reference writes.
- [x] Product identity requires company + product variant; the current company has no editable reference model.
- [x] Replaying a successful pre-feature receipt MUST NOT retroactively generate a new reference update.

### Transaction semantics clarified
- "Only after a successful receipt" means a reference write **inside the receipt transaction before its one final commit**, with visibility ONLY after successful commit. Any rollback also rolls back the reference and its audit.
- If the receipt committed but the HTTP response was lost, the committed reference is CORRECT and must remain current unless superseded by a later committed authorized entry. Retrying the SAME durable request returns prior result and MUST NOT write another revision or override a later manual edit.
- Future reference suggestions must never replace an operator's already-entered receipt actual cost. Submission sends explicit fixed amount + original purchase UOM to the backend.
- Manual Product reference entry creates no physical movement, InventoryCostEvent, InventoryCostLayer, change to InventoryCostState, official COGS, or sale-price publication.

### Open contract blockers — must close before write-worker assignments
- [x] Multi-line same-variant receipt with different costs/UOMs: avoid sorted-internal-line "last wins." Freeze deterministic single reference-selection business rule. Preserve all real invoice line costs even when selecting a different one as future reference.
- [x] Currency: choose company currency for V1 and persist explicit reference currency; verify whether company currency can change and historical provenance if it does. Never infer historical currency from today's setting.
- [x] UOM: reference display/edit must use exact authoritative unit conversion or require explicit chosen reference UOM; avoid round-trip rounding. Preserve raw receipt UOM/actual input.
- [x] Permissions: decide reference read/write company-scoped capability. Price Book permissions must NOT silently permit purchase cost access. Receiving a permitted receipt can update its company-wide reference only as the documented posting effect.
- [x] Concurrency: serialize by (company,variant), including first INSERT. Manual edit needs independent expected_reference_revision. Sort locks by variant, verify no inversion against existing receipt/movement/cost lock acquisition.
- [x] Product lifecycle/create/edit, explicit clearing vs omitted optional value, same-value mutation, last-write precedence and audit actor provenance frozen by the later merged Product CREATE/EDIT purchase-reference implementation and exact-head acceptance.
- [x] Retain unknown references as NULL/absent, never interpret zero as unknown and never synthesize a bulk historical backfill.

### Focused PostgreSQL gates for accounting safety
- [x] Manual edit does not change cost state, FIFO layers/allocations, historical events, previously posted receipts, COGS, or Product sale Price Book (before/after actual DB snapshots).
- [x] A reference update failure inserted before receipt COMMIT rolls back receipt movements, cost events, supplier link and idempotency record together.
- [x] Post-commit lost-response replay, old receipt replay after a newer edit, changed-payload request-ID conflict.
- [x] Two company/variant writers race: manual/manual, manual/receipt, receipt/receipt; first-write missing row, sorted multi-variant locks and no deadlock.
- [x] Different costs for same lot and multi-line/UOM same product preserve separate immutable actual-cost receipt evidence.
- [x] Company isolation, permission denial, audit provenance, safe additive migration/upgrade and old request replay compatibility.
- [x] FIFO and MOVING_AVERAGE continue to generate exactly their original accounting COGS, with no new accounting authority.

### Handoff status
- Worker A backend audit: [x] complete/read-only/lead accepted; full implementation still [ ] NOT STARTED.
- Worker B Product UI/Pricing/Import audit: [x] COMPLETE 2026-10-21, read-only GitHub SHA 2be59f6066419ef1de0157c48adaf8c931bfbaf2. Lead accepted with contract blockers retained.
- No worker implementation branch, migration, data mutation, or historical-cost change has been commissioned by this plan; local UI draft repair and sale-price labels are separate earlier edits.

## 8. Worker B Product/Pricing/Import source audit accepted by Lead (2026-10-21)

Source: GitHub audited at exact `2be59f6066419ef1de0157c48adaf8c931bfbaf2`, READ-ONLY; latest uncommitted local files were not part of worker's audit. Existing Product local UI was separately inspected by Lead for change overlap.

### Confirmed Product authority boundaries
- [x] Product create `SimpleProductCreate` + Dashboard create draft/command currently contain sale-price data, not the new purchase reference. Add an optional reference + explicit purchase UOM to Product creation's **same idempotent/durable create business payload**, not a second uncoordinated request after Product creation.
- [x] Product 'Edit Price' UI (`PriceEditModal`, `usePriceEditWorkflow`, `/simple-products/{variant_id}/price`) is solely for Sale Price under `pricing.manage`. New Purchase Cost Reference editing must be separately named/authorized; do not send it through PriceBook or Sale Price endpoints.
- [x] Current Product actions are distinct (rename/family/tracking/barcode/lifecycle/pricing), not a universal Product editor. Fit the new bounded reference into the existing local Product surface after inspecting uncommitted working tree, not a competing new editor.
- [x] `GET /simple-products` currently masks sale prices without `pricing.view`. New purchase reference must be **server-masked** for unauthorized readers; React hiding is insufficient. `pricing.manage` does not imply purchase-cost access.
- [x] Current Product import template is precisely **10 columns** with positional `A1:J50001` and `_wanasah_meta` / `_wanasah_lists` / DataValidation / aliases/corrections. Do NOT add column 11, delete aliases, change `CANONICAL_IMPORT_FIELDS`, or change import correction/recovery as part of this work. Product create optional fields must default absent so legacy import callers keep working.
- [x] Keep wire fields `package_price`/`unit_price` stable; only user-facing AR/EN Sale Price labels need clarification across create/edit/table/mobile/actions/detail/filter/preferences. Earlier local create labels were changed; remaining labels pending.

### Specific integration/test checklist from second audit
- [x] Backend Product create accepts reference only when provided with proper cost authorization, and commits reference/audit atomically under same durable request.
- [x] Separate authorized reference edit for published Product variants; do not weaken draft-only structural edit restrictions.
- [x] Product list/detail and Inbound lookup must mask reference unless the exact caller has the approved cost-read authority; test unauthorized API reads.
- [x] Reference value includes amount, purchase UOM, currency, current revision, source/actor/updated_at (not inferred from PriceBook).
- [x] Product 'create' leaves `SimpleProductSpec`/import validation backward-compatible; 10-column template round-trip and correction/retry test remains green.
- [x] Product user-facing Sale Price labels in AR+EN disambiguated without changing existing API names or Excel header parser aliases.
- [x] Test existing Product P2 price masking, P3 table actions, P9 Product create/pricing, supplier inbound Postgres and immutable source-cost tests.
- [x] Compare latest uncommitted local Product UI and API edits before any worker implementation; do not overwrite exact-name search/tracking/expiry work.

### Source audit verdict
- Worker B: audit complete, accepted as constraints; **NOT** proof that new purchase reference has been implemented or tested.
- Backend risk worker A follow-up remains pending: multi-line same-product selection, currency, UOM, concurrent locking, permissions.
- Lead contract must freeze before coding; read-only audits alone do not satisfy accounting acceptance.

## 9. Final risk audit reviewed (2026-10-21) — move from audits to implementation

Worker A's final read-only GitHub audit is complete. NO need for more open-ended audits.
Lead check: receipt and Product costs MUST remain independent of financial valuation and Sale Pricing.

### Final implementation policy for the bounded V1 capability
1. Normal one-cost-per-variant receipt: upon successful DB commit, publish exactly that actual entered unit cost/UOM as the current reference. Product manual edits likewise publish the explicitly saved value. The canonical order is successful transactional serialization, never client clock time.
2. Multiple different actual prices for the SAME variant in ONE receipt are genuinely ambiguous relative to the Owner's "last explicitly entered purchase cost" requirement. DO NOT apply an automatic weighted average: that is a different business value and not Owner-approved. Have the operator explicitly designate which of the receipt's real entered purchase costs should be retained as the next reference before posting; all individual receipt lines still preserve their original actual costs. Identical logically equivalent amounts/UOM can resolve automatically. Do not reject otherwise valid multi-lot receipts for unrelated reasons.
3. V1 functional currency is company currency only (no FX); explicit currency stored with reference and audit; fail closed on mismatch. Company currency is provisioned initially. Source audit found that current DB grants may permit direct currency UPDATE despite no company currency-update API; this EXISTING FINANCIAL RISK requires DB-boundary immutability hardening with isolated tests and no historical-cost rewriting.
4. Company-scoped purchase-reference read/manage capability split; neither pricing.view/manage nor catalog.read/manage alone grants purchase-cost visibility/edit. Manual reference writes require manage. Inbound operator needs read to prefill; authorized posting may update reference atomically without standalone manual manage permission. Exact location/supplier checks remain.
5. ONE reference writer gate held before existing Product/Inbound locks and until commit; independent revision compare on manual edits; replay returned before new reference lock and write. One same-transaction change-audit record per actual committed update. Protect initial insertion; no historical backfill by assumption.
6. Product create reference is OPTIONAL in the same durable create payload and DB transaction, never post-create best effort. PriceBook remains sale-price only. Product import remains exactly ten columns with legacy aliases.
7. All backend financial gates from sections 5 and 7 must pass with real PostgreSQL and rollback/replay/concurrency tests. Do not call completed without evidence.

### Ownership / safe integration execution
- Backend implementation can be delegated now ONLY to an isolated GitHub branch with explicit write ownership. The uncommitted local `wa_backend/models.py`, `wa_backend/api/simple_products.py`, `wa_backend/api/catalog.py` must NOT be overwritten or assumed identical to GitHub in later integration.
- Start by implementing additive isolated Purchase Reference domain model/service, migration, and dedicated tests; keep existing local-touched files out of worker ownership. Receipt endpoint modifications on worker branch only after verifying no overlap.
- Lead will integrate with local Product/Inbound UI on current branch and review exact branch diffs. No reset/clean/stash/force-push; no automatic merges.
- Treat worker's weighted-reference proposal as a READ-ONLY suggestion, NOT an approved business rule.

## 10. Lead direct implementation checkpoint (2026-10-21)

Local working tree changes, no commit/push/merge:
- [x] Inbound tab restores draft variants not present in first cursor page by bounded `POST /catalog/variants/resolve`, keeping paginated browsing intact. Restored rows remain visible and receive their UOM choices even when the user searches elsewhere. Fetch batches <=200, server resolves only requested IDs.
- [x] Inbound posts only show success / clear draft when `useInboundPosting.post()` reports true, not false. Unconfirmed operations retain saved input.
- [x] Purchase/sale distinction clarified in Product create, list headers, view preferences and Sale Price modal using AR/EN i18n, without altering PriceBook API or ten-column Excel import contract.
- [x] Fixed unrelated existing Products table regression test setup: ProductStatusBadges navigation needs a MemoryRouter. The component runtime was not changed.
- [x] Focused Inbound Vitest 25/25 PASS. Focused Product pricing/table Vitest 5/5 PASS. Strict TypeScript noEmit PASS. Vite production build PASS before final labels; no production DB/financial cost writes executed.
- [x] Historical Backend/independent-acceptance dependency is closed by later merged exact-head PostgreSQL gates and current localhost release verification; the remaining authenticated owner UI/receipt click-through is tracked explicitly in the final closure section below.

Preserved all unrelated local Product, Backend, Flutter and database work. DO NOT blend these uncommitted local changes into an older GitHub branch without explicit diff reconciliation.

## 11. Purchase Reference implementation status — 2026-10-21 (Lead verified GitHub)

- [x] Foundation PR #406, HEAD 822732366b814beab0a6c1690dfcc2e2e249b4ec: exact-reference GET/PUT, audit, idempotency, independent revision and RLS. PostgreSQL 24 tests and clean bootstrap PASS; NOT MERGED.
- [x] Product EDIT UI PR #407, HEAD 66f080f99b98c67e60e0cda60e1b96486dd4ad56: separated purchase cost editor, permissions and durable retry. Focused UI tests and build PASS; NOT MERGED.
- [x] Supplier Inbound atomic backend PR #408, HEAD 10369fd67b88eb099e3374ef904e3a7cd19b8263: transaction-composed reference/audit, replay compatibility, mixed UOM/cost explicit choice. PostgreSQL 61 tests + 5 subtests, Supplier 50 backend + 43 frontend PASS; NOT MERGED.
- [x] Supplier Inbound UI PR #409, HEAD cf260322b37459dab09e06eb3cd85de6e94c4af4: suggestion for untouched draft, actual line cost remains editable, explicit mixed-line choice; 21 focused frontend tests, build and TypeScript PASS; NOT MERGED.
- [x] Isolated combined Product EDIT + Inbound UI PR #410, HEAD e77a5f09286eddcd1267e7cae1fe49f415a9b74b: UI integrations with 33 focused tests, TypeScript and production build PASS. NOT MERGED.
- [x] Product CREATE optional purchase reference, in same durable transaction as product creation: delegated to Codex on dedicated branch, NOT YET DONE.
- [x] Reconcile #410 feature logic with latest user LOCAL uncommitted redesigned Inventory Inbound UI before any user-machine update. The GitHub base Tab2Inbound is substantially older than local; local diff exceeds 1000 lines of UI layout/interaction changes. NEVER wholesale replace local Tab2Inbound.tsx from #410. Preserve local 25 passing tests, off-cursor draft restoration, supplier reset, and pricing label edits.
- [x] Verify permissions grants and company currency immutability policy in exact combined DB; do not change historical values.
- [x] Independent real-Postgres integrated acceptance for create/edit/inbound/replay/rollback completed on the later exact combined heads and merged release path; owner localhost visual acceptance remains tracked separately below.
- [x] Main divergence and full-file PR #406 diff must be reconciled from exact-base commits, not blindly merged.
All new implementation occurred via GitHub branches except this isolated local plan update. The local source code and database were NOT modified in this checkpoint.

## 12. Combined exact-head V1 candidate — 2026-10-21 verified (GitHub-only integration)
- [x] PR #411 optional Product CREATE purchase reference, exact HEAD 12aa9eee8ff342567c9c2e0da06739b4323d7f69 accepted in combined branch. Create + reference + audit share a single durable DB transaction; Product backend and quick-create UI; no new migration.
- [x] Combined PR #412, branch sol/purchase-cost-reference-full-integration-v1, exact HEAD ab6307086516483f9615e5b0a7a6c46a6c205110, integrating reference Foundation #406, Product EDIT #407, Supplier Inbound backend #408, Inbound UI #409/combined #410, Product CREATE #411. The overlapping purchase_reference/public.py seam retains BOTH Product CREATE and receipt exports. No main merge.
- [x] Resolved original combined TypeScript baseline regression: InboundVariantOptions.purchase_cost_reference is optional for legacy callers/fixtures; parser still enforces actual new wire values.
- [x] Fixed exact-base whitespace gate in test; all 7 GitHub exact-head CI workflows PASS on ab6307086516483f9615e5b0a7a6c46a6c205110: Product create atomic PostgreSQL + Dashboard, Supplier V1 acceptance, purchase-reference backend PostgreSQL, Product UI, Inbound UI, combined UI, clean PostgreSQL bootstrap. No operational DB was modified.
- [x] DO NOT call deployed/field-ready. Local uncommitted modern Inventory UI (Tab2Inbound.tsx ~1,163 lines) differs extensively from the committed older UI in PR #412. Must reconcile via bounded file-level merge, preserving all local Warehouse, Supplier, draft, UX, CSS and Product changes before deploying or pulling. NO wholesale replacement of user's local work.
- [x] Functional same-instance real PostgreSQL Product create -> manual edit -> Supplier receipt -> replay/rollback acceptance with strict cost/COGS invariants completed by the later exact-head release/E2E gates; user localhost UI acceptance remains tracked separately below.
- [x] Company currency immutability policy and main/wave branch divergence remain merge-readiness checks; main is 98 commits behind V1 candidate base 2be59f60, never blindly merge PR #406 into main.
Status: GitHub exact-head implementation accepted by automated gates; final local integration and release approval PENDING.

## 13. LOCAL Inbound UX reconciliation actively implemented — 2026-10-21
- [x] Preserved latest uncommitted modern Inbound UI and Supplier/warehouse presentation; surgically integrated purchase_cost_reference options parser, currency/UOM validation, optional masked default, safe untouched-row prefill, explicit operator choice for mixed receipt costs/UOMs, no float financial averaging, cost reset on UOM change, selection invalidation on edit/delete/clear.
- [x] Added Arabic/English Inbound reference labels, and repaired preexisting missing commas in Product sale-price labels that blocked local module parsing.
- [x] New local reference contract test (5 PASS), existing local Inbound contracts (10 PASS), actual Inbound UI tests (17 PASS, including reference prefills and mixed line choice): total **32/32 PASS** on local dirty worktree.
- [x] Local strict TypeScript check PASS and Vite production build PASS after code integration.
- [x] Historical local source reconciliation blocker closed: read-only reconciliation on 2026-10-22 found every meaningful locally-added source line represented in current main, with no destructive reset/clean/delete of the original checkout.
- [x] Product Create/Backend dirty-file reconciliation and same-instance PostgreSQL accounting/retry acceptance are no longer release blockers; current main contains the reconciled source and later PostgreSQL acceptance evidence. Original dirty checkout remains preserved.
- [x] Reconcile scope with current main/V1 candidate and obtain explicit approval for final merges. KEEP this plan until acceptance actually closes.

## 14. E2E closure and consolidated release candidate — 2026-10-21
- [x] Codex PR #413 (42ab9c17ab1caa96788336c678616dcf950c916b), two new files only. Same-company real-PostgreSQL E2E: 2 tests PASS (13 stages each) for FIFO/MOVING_AVERAGE, create/edit/receipt/rollback/replay/permissions/tenant/races/UOM and canonical Excel headers. Historical value 232 JOD, COGS 12 JOD per acceptance company.
- [x] Reconciled CURRENT LOCAL Inbound UX, supplier selector, inventory shell, responsive inventory.css, Product cost and sale-price translations, draft preservation, and local exact Product search into isolated GitHub branch sol/purchase-reference-local-final-integration-v1. User's local branch, uncommitted changes, runtime DB were NOT reset/cleaned/switched/deleted.
- [x] Integrated release branch exact HEAD fe79792720404e72a51c790543a238ba82d7de4c: all 7 exact-head workflows PASS, including dedicated combined UI/Postgres gate, E2E PostgreSQL, Product create atomic, Supplier V1, Product UI, Inbound UI and overall reference integration.
- [x] Single consolidated review candidate PR #415 targets sol/inventory-v1-final-closure-candidate at exact base 2be59f6066419ef1de0157c48adaf8c931bfbaf2 (63 files, 33 commits); mergeable but DRAFT, NOT MERGED. Stacked local reconciliation PR #414 also exists.
- [x] Historical release prerequisites are reconciled: unrelated dirty source is accounted for without cleanup, approved release/migration is on current main/local release, and currency immutability/merge approval are evidenced. Remaining owner localhost authenticated acceptance and final deletion are tracked explicitly below.

- [x] Final consolidated review PR #415 verified on exact HEAD fe79792720404e72a51c790543a238ba82d7de4c: all 9 GitHub PR-triggered workflows PASS including complete same-instance E2E PostgreSQL, clean bootstrap, atomic Product CREATE, Supplier acceptance, Product EDIT UI, Inbound UI and final dashboard+Postgres release gate. PR remains DRAFT, unmerged; no real operational DB migration or local checkout has been done. Final release gates remain as listed above.

## 15. Closure reconciliation against actual merged evidence (2026-10-21)
- [x] #417 unified Inventory V1 main; #418 immutable company currency trigger; #420 read-only cost pencil/F2. Company owner is authorized without separate manual role configuration.
- [x] One dashboard is now served on http://localhost:8080/products by main release worktree. The obsolete 8184 dashboard listener was stopped; backend 8183 health/CORS verified.
- [x] 33 focused Product/Inbound frontend tests and TypeScript pass locally after #420, previous PostgreSQL FIFO/MOVING_AVERAGE end-to-end cost/reference accounting passed, and company-currency trigger verified.
- [x] Base Excel Import columns A:J (10 old fields), hidden meta/list sheets, old import aliases, validation/staging limits and execution batches remain unchanged in the additive cost extension candidate.
- [x] Owner-approved import extension PR #421 (MERGED main be2ddbf4): optional K column for cost of ONE base unit (EACH) plus exact 6-decimal normalization, bulk atomic reference and audit. PostgreSQL/rollback/retry gates passed; performance is tracked by the dedicated post-#423 acceptance item below.
- [x] Post-#423 fair 50,000-row PostgreSQL A/B acceptance completed and merged via PR #425: legacy 54.93s vs purchase-cost 47.93s on matched disposable PostgreSQL conditions; old ~58% penalty is gone, counts/invariants passed, no runtime optimization required. Merge commit 3b4bdc36c8d40c3be7603742d6f7e08eebeba329.
- [ ] Authenticated owner field acceptance on the unified 8080 UI: create Product with purchase reference, manually edit it, post a Supplier receipt and verify the exact reference update without unintended financial changes; also download/use the current K-column Product Import template for a tiny controlled import and verify Product + reference + audit.
- [x] Original dirty checkout reconciled read-only (49 current items): all modified source additions and all untracked source-file content are represented in current main; Flutter/generated and local-only plan/run/temp artifacts were preserved without reset/clean/delete.
- [ ] Delete this plan only after every substantively open functional acceptance is completed, evidenced and final product/import/Inbound workflow matches approved UX.

Note: earlier historical checkpoint text uses phrases such as NOT MERGED; the checkboxes above are reconciled to subsequent PR evidence and do not rewrite what was true at those old checkpoints.

## 16. Product Import optional Purchase Cost ? RELEASED to local working release (2026-10-21)
- [x] PR #421 merged into main at be2ddbf4d24085d34727dc6fd339bf6c5997590d. Clean working release fast-forwarded with original 48-file dirty checkout preserved.
- [x] Optional column K per base unit (EACH) in AR/EN template, original A:J columns, meta/list sheets and aliases preserved; old 10-column uploads supported.
- [x] Real PostgreSQL 200-row import + immutable history + replay after newer manual edit passed, and 5,000 old-vs-new worker performance passed: legacy 6.90s, with cost 10.78s, no inventory COGS edits.
- [x] Fifty-thousand-row streaming CSV baseline measured: legacy 1.023s vs optional-cost 1.228s; 500/500/200 batch limits unchanged; old no-cost path has no reference write.
- [x] Rejected-row correction and stable identity PostgreSQL tests, reference FIFO/MA integration, clean DB bootstrap, TypeScript, Dashboard build passed. Two pre-existing Inventory CP1/CP2 unrelated baseline checks remain red.
- [x] Original local DB backed up to backups/wanasah-local-before-import-cost-v1-20261021.dump, verified clone migration and parity, then original migrated to e5a7c1d9f042; 501 variants and business counts unchanged.
- [x] Single newest Dashboard accessible on http://localhost:8080/products with new backend health 8183. Product cost editor accepts PRODUCT_IMPORT source.
- [x] Duplicate historical owner-acceptance line retired; the single authoritative authenticated localhost acceptance checkbox is maintained in the final closure section above.
- [x] Original dirty worktree source reconciliation completed read-only; final plan retirement is tracked separately by the final deletion checkbox after the remaining open acceptance items close.
