# XLSX Security — Issue #998 (parent #164)

**Exact base:** `main` `d49631fa907930ebf9de87a99b858f3fc9c60324`. Independent Draft PR; no merge. Issue #164 remains open for other advisories.

## Proven reachable risk and minimal repair

- **Untrusted workbook parse #1:** `dashboard/src/pages/products/import/productImportFilePreflight.ts` dynamically loads `xlsx` and calls `XLSX.read` for client-side product preflight. Important existing semantics: `_wanasah_meta` A1/A2; a valid declared visible sheet; external sole-visible-sheet or fail closed; tracking/lot/expiry preview.
- **Untrusted workbook parse #2 and template export:** `dashboard/src/components/dispatch/ShopBulkImportModal.tsx` calls `XLSX.read` and `sheet_to_json` for shop XLS/XLSX/CSV upload; `aoa_to_sheet`, `book_new`, `book_append_sheet`, `writeFile` for localized template generation.
- Product correction and inventory opening valuation use backend upload/download contracts; no additional Dashboard `xlsx` import.

**Actual replacement:** direct runtime dependency `xlsx@^0.18.5` from stale npm registry replaced by exact *official SheetJS upstream* `https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz`. `package-lock.json` pins version, URL and integrity: `sha512-oLDq3jw7AcLqKWH2AhCpVTZl8mf6X2YReP+Neh0SJUzV/BdZYjth94tG5toiMB1PPrYtxOCfaoUCkvtuH+3AJA==`. This includes vendor fixes: CVE-2023-30533 fixed in 0.19.3 and CVE-2024-22363 fixed in 0.20.2; current official version 0.20.3. No third-party fork or unreviewed framework upgrades.

Official: https://cdn.sheetjs.com/ ; https://cdn.sheetjs.com/advisories/CVE-2023-30533 ; https://cdn.sheetjs.com/advisories/CVE-2024-22363 .

All production callsite APIs, import/export semantics and backend-validated business rules are **unchanged**. Only one focused test file was extended with a pinned patched-version assertion, malformed truncated ZIP rejection (returns unknown/null instead of accepting rows), and a bounded legacy SpreadsheetML suspicious-attribute compatibility/no-prototype-leak probe. This synthetic probe is not claimed to reproduce either CVE exploit.

## Real checks (Windows local, Node 24.20.0, npm 11.19.0)

| Check | Observed result |
|---|---|
| `npm ci --ignore-scripts --no-audit --no-fund --prefer-offline` | **PASS**, 474 packages; installed xlsx **0.20.3** from pinned official source |
| `npm audit --omit=dev --json`, baseline | **6 advisories**: 3 high + 3 moderate; xlsx high, both CVE references |
| `npm audit --omit=dev --json`, changed lock | **5 advisories**: 2 high + 3 moderate; **xlsx entry absent** |
| Existing P9 + three new workbook tests | **PASS 8/8**, including hidden canonical metadata, external sole visible sheet, ambiguous external sheets and invalid marker fail-closed |
| D13 focused accessibility/template tests | **5/6 passed** initially; unrelated shortage-confirmation test exceeded existing 5,000 ms timeout |
| Single diagnostic re-run of only timed-out shortage test, `--testTimeout=20000` | **PASS** in **5,126 ms**, other 5 tests skipped. Does not erase first run timeout |
| `tsc --noEmit -p tsconfig.app.json` | **FAIL** on errors in unrelated, untouched app/tests (catalog, inventory, vehicles, settlement, etc); no diagnostic in the 3 modified project files. Cannot claim global TS green |
| `vite build` | **PASS**, 39.89 s; emitted `dist/assets/xlsx-B2eTCt_Q.js` (500,005 bytes) |

Remaining audit entries unrelated to XLSX: **high**: `zod`, `source-map-js`; **moderate**: `react-router`, `react-router-dom`, `postcss-selector-parser`. They remain open for their own scoped reviews; `npm audit` nonzero as expected. Security response excludes any claim to bound arbitrary ZIP bombs or prove every CVE exploit path.

No Backend, Flutter, Dispatch, other worker's files, build config or workflows touched. No PG16, signed browser, Flutter or broad Vitest reruns. LEAD owns acceptance and merge.
