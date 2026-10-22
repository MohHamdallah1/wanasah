# Visit FIELD wiring

Pinned foundation: 7a7ee059cc2284cacbb219dbf63c18fe25fa7f96.
The accepted FIELD adapters and capability use-cases are unchanged.

Current seams:
- VisitCatalog keeps quantity entry; ReturnReasonQuantities adds typed Damaged,
  Expired and Factory_Defect labels and preserves carton/base-pack inputs.
- CompletedVisitRestorer and VisitCartPolicy retain their existing cached
  replacement-out behavior with the missing Damaged counters included.
- confirmVisitFieldSubmission sequences presentation decisions through the
  existing ReadCommercialReadiness, ReturnResolutionCoordinator and
  PreviewVisitInvoice use-cases.
- Returns resolves deterministic cases without a prompt. Ambiguity renders
  only requested human evidence and has no selected default. The chosen facts
  go back through submitEvidence; no candidate identity is synthesized.
- VisitSubmissionService retains mapVisitSubmissionLines for sale/sample
  mapping and the strict buildCanonicalVisitPayload serializer. A separate
  ResolvedVisitReturns binding validates the signed lines against the exact
  current visit, reason and quantities before durable staging.
- VisitSaleConfirmation binds the ready prerequisite and preview to the sold
  quantities the operator actually confirmed. Preview is never commit evidence.
- VisitBloc composes the existing authenticated data client and delegates
  orchestration. Screens/presentation make no ApiClient calls.
- SyncRepository.saveInvoice is unchanged. It remains the only owner of command
  identity, persist-before-send, immutable retry/body, correction staging and
  projection. No request ID is minted, replaced or replayed by this wiring.
- Existing pending-command reads distinguish queued/unresolved completion from
  confirmed completion because the existing saveInvoice API returns void for
  both. Unreadable sale evidence fails closed. Existing atomic staging remains
  the final correction guard; the early read is UX only.
- A confirmed Sale reads ReadCommittedVisitInvoice. Read failure is separate
  from mutation failure; the receipt can repeat only that read. Pending saves
  never read an older invoice or display preview as committed evidence.

All new FIELD copy is in VisitFieldStrings (Arabic/English); direction follows
the ambient locale. Invoice values retain exact strings, with decimal/group
separator localization at display only. No floating point pricing/tax/credit
decision is made. Cached totals are labeled estimates; Backend commit still
recalculates and may reject a previewed draft.

Compatibility boundaries:
- Existing cash/debt state and SQLite projection still use legacy doubles.
  New operator inputs and unresolved durable payload text bypass those values
  for the canonical submission; authoritative invoice evidence never enters
  that legacy projection. Historical local completed cash values cannot
  recover precision already lost before this slice.
- A new Sale needs live readiness/preview, and unresolved return provenance
  needs a live resolver. Failed preflight keeps the current screen draft;
  existing staged commands continue through the unchanged durable recovery.
- Pending/corrupt earlier commands are not editable replacements. Resolve them
  through the accepted Sync/Recovery workflow before a deliberate correction.
- Full device journey/Backend deployment acceptance remains separate from
  the focused GitHub analyze, widget and command regressions.
