# Phase 19 — full Dashboard source regression and release build

**Date:** 2026-10-01. **Scope:** the entire `dashboard/src/test` Vitest suite on the current development checkout, no HTTP/DB writes or worker launch.

## Source-first findings

The first full Dashboard test run found four failures: one real missing bilingual error-page translation, and three outdated source-string expectations after the accepted, browser-verified refactor.

- **Actual UI bug:** `errors.codes.PRODUCT_IMPORT_ERROR_PAGE_INVALID` was missing from both Arabic and English. It now provides localized safe feedback for invalid rejected-error pages.
- **Focus contract:** legacy P8 and P9.4 tests assumed `DropdownMenuItem.onSelect` synchronously opens import. Codex's real Edge test proved that approach stole focus; the approved source now defers opening in `onCloseAutoFocus` via `queueMicrotask(onOpenImport)`. The legacy tests now assert the deferred focus-safe contract rather than requiring its bug.
- **Artifact contract:** P9.4 source test expected `content_base64` inside `createImportDownloads.ts`. Actual server artifact decode and filename-validation authority was already centralized in `productImportFileDownload.ts`. The test now follows that helper and verifies the ownership boundary rather than forcing duplicated decoding.
- **Completed-close guard:** P8 test expected a direct `completeImport` callback. The approved source routes it via `guardInlineDraft` so a pending same-job correction draft cannot be silently discarded. The test now verifies this protection.

## Actual gates

| Step | Result |
| --- | --- |
| Focused four test files after source repair | **21/21 PASS** |
| Complete Dashboard Vitest, all source tests (73 files) | **388/388 PASS** |
| TypeScript `tsc --noEmit -p tsconfig.app.json` | **PASS** |
| Targeted ESLint on all changed source/test files, `--max-warnings=0` | **PASS** |
| Vite production build | **PASS** |

The full-suite PowerShell runner was invoked with `ErrorActionPreference=Continue` around native test output only; otherwise the runner incorrectly treats benign stderr React/test warnings as a terminating PowerShell `NativeCommandError` before Vitest finishes. Vitest's own process exit 0 was checked independently.

## Limitations and release boundary

These are **full Dashboard code-source tests**, not a manually operated screen-reader, mobile touch hardware or live account-shell acceptance. All backend changes already had source/real isolated integration gates recorded separately. The final Phase 19.5 combined release rule remains dependent on its other explicit browser/tenant/Worker/performance checklist items. This evidence must not be relabeled as real 50k or real HTTP acceptance (which have distinct reports).