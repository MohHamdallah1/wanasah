# Wanasah V1 Product Import — UX acceptance findings

**Recorded:** 2026-10-01. **Scope:** owner-reported questions/confusion and
source-confirmed implementation responses; NOT a completed manual browser
or production-customer acceptance. A real browser/permission/RTL/LTR run
and the release owner’s visual approval remain OPEN in Phase 19.4–19.5.

A user question about a workflow is a V1 acceptance observation, not
permission to silently move its correctness to VERSION_2_FUTURE_FEATURES.md.

| Owner-visible finding / potential acceptance failure | V1 decision and source of truth | Evidence status |
| --- | --- | --- |
| **15,000 rejected products:** users must not get an enormous editable dashboard table, and page size is not total eligible count. | At **1–25 total** rejected rows, offer the inline value editor; at **26+** display a bounded explanatory message and official **same-job** correction XLSX. The backend's 100-row transport limit is independent of the UI cutoff. `ImportProductStatusPanel.tsx`, `inlineCorrectionContracts.ts`. | Code/tests passed; **real browser and large rejected-job verification OPEN**. |
| **Why an error was rejected:** hover-only explanation is inaccessible on touch/keyboard. | Field error has a visible text message, `aria-invalid` and `aria-describedby`; a separate keyboard-focusable icon opens the same explanation in a Tooltip. The first failed row expands automatically. `ImportInlineCorrectionRow.tsx`. | Static/component behavior exists; **mobile, keyboard and screen-reader manual run OPEN**. |
| **Is correcting the Excel a new import?** Re-uploading the unchanged source duplicates/rejects previous good rows. | The diagnostic error CSV is **not** the correction file. Download `GET /imports/{job}/correction?format=xlsx` and upload to the same `job_id`; previously imported rows are not editable, and the original job UUID remains unchanged. `ImportCorrectionPanel.tsx`, `correction_repository.py`. | Historical 54-row application/DB correction done; **current authenticated HTTP/Worker acceptance OPEN**. |
| **Does “saved” mean all products now exist?** A 202 ACK only queues validation, and another error may become visible after fixing the first. | The accepted correction response is `status=VALIDATING`; resume the job watcher and display the resulting imported/rejected counts only after the worker reports a terminal outcome. Show field/row reasons without promising exhaustiveness. `useImportInlineCorrection.ts`, `useImportProductWorkflow.ts`, `ImportProductStatusPanel.tsx`. | Code/component gates passed; **live worker confirmation OPEN**. |
| **50,000 input lines, empty rows and Product count:** physical source rows can exceed the number of product rows, and one Product parent can own several imported Variants. | Source row numbers stay physical; imported row/Variant identity is the reconciliation authority, **not** a guessed count of new Product parents. The offline synthetic 50k CSV has 50,000 records, 1,612 empty physical lines and physical last row 51,613. `phase19_fixture.py`, `parsers.py`, Phase 19.1 lineage section. | Offline parser and historical 54-row DB evidence; **latest real HTTP→50k persisted readback OPEN**. |
| **Barcode that starts with 0, numerical Excel cell or formula:** incorrect interpretation may silently alter identifiers. | Official template treats barcode as literal text. The correction-file adapter now retains original cell metadata so the existing validator rejects unsafe numeric/formula barcodes; leading zeros remain text. `correction_service.py`, `normalization.py`. | Source/parser tests passed; **real XLSX upload/browser acceptance OPEN**. |
| **Lost response / draft changes / switching routes:** users may accidentally retry with a different operation ID, lose edits, or submit two correction methods concurrently. | Reuse the same scoped durable request on ambiguous response, preserve session draft, confirm destructive discard and prohibit overlapping Excel/inline mutations for the same job. `correctionRouteGate.ts`, `useImportCorrection.ts`, `useImportInlineCorrection.ts`. | Focused tests passed; **live network disconnect/replay and tenant-switch run OPEN**. |

## Acceptance procedure — still OPEN

Use the real browser with the **approved synthetic development tenant and
authorized actor** to walk the cases above in Arabic/RTL and English/LTR,
including narrow touch viewport and Tab/Shift+Tab/Escape behavior. Verify
non-authorized roles cannot see/edit prices or bypass backend permissions,
confirm post-import Products search/filter/receipt freshness, and read
Product/Variant/Price/Audit lineage back from the approved PostgreSQL target.
Record each PASS/FAIL with an actual run timestamp and evidence in the Phase
19 checklist. **Do not check Phase 19.4 manual verification or the entire
V1 release based on this register.**

The separate first-company customer-deployment signoff remains in
`docs/operations/PRODUCT_IMPORT_V1_RELEASE_RUNBOOK_2026-09-30.md`.
