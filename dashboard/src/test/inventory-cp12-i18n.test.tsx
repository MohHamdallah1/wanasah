import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { resolveAppLocale } from "@/lib/locale";
import {
  branchManagementCopy,
  formatInventoryDecimal,
  formatInventoryInteger,
  warehouseLocationsCopy,
} from "@/pages/inventory/warehouse-locations/i18n";

const ROOT = resolve(process.cwd(), "src/pages/inventory");

const forbiddenCp3 = new Set([
  "TabBatches.tsx",
  "batches/BatchDispositionManager.tsx",
  "batches/BatchFocusWorkspace.tsx",
  "batches/BatchQuantityActions.tsx",
  "batches/useBatchDispositionCommand.ts",
  "batches/useBatchTerminalAction.ts",
  "batches/BatchTerminalActionDialog.tsx",
  "batches/batchTerminalActionContract.ts",
]);

const resourceBasenames = new Set([
  "copy.ts",
  "i18n.ts",
  "ledgerI18n.ts",
]);

const collect = (directory: string): string[] =>
  readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return collect(path);
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });

const stripComments = (source: string) =>
  source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

const activeOwnedSources = () =>
  collect(ROOT)
    .filter((path) => !path.endsWith(".test.ts") && !path.endsWith(".test.tsx"))
    .filter((path) => !resourceBasenames.has(path.split(/[\\/]/).at(-1) ?? ""))
    .filter((path) => !forbiddenCp3.has(relative(ROOT, path).replaceAll("\\", "/")));

const read = (path: string) => readFileSync(path, "utf8");

const naturalLanguagePatterns = [
  /toast\.(?:error|success|info|warning)\(\s*["'`](?![A-Z0-9_:-]+["'`])[^"'`\n]*[A-Za-z\u0600-\u06ff][^"'`\n]*["'`]/g,
  /(?:aria-label|title|placeholder)\s*=\s*["'][^"']*[A-Za-z\u0600-\u06ff][^"']*["']/g,
  />\s*[A-Za-z\u0600-\u06ff][^<{\n]{2,}\s*</g,
];

describe("CP12 Inventory i18n closure", () => {
  it("keeps active owned Inventory implementation free of inline Arabic presentation prose", () => {
    const offenders = activeOwnedSources().flatMap((path) => {
      const source = stripComments(read(path));
      return /[\u0600-\u06ff]/.test(source)
        ? [relative(process.cwd(), path).replaceAll("\\", "/")]
        : [];
    });

    expect(offenders).toEqual([]);
  });

  it("keeps obvious user-facing natural-language literals out of active owned React implementation", () => {
    const offenders: Array<{ file: string; matches: string[] }> = [];

    for (const path of activeOwnedSources()) {
      if (!path.endsWith(".tsx")) continue;
      const source = stripComments(read(path));
      const matches = naturalLanguagePatterns.flatMap((pattern) => source.match(pattern) ?? []);
      const relevant = matches.filter((match) =>
        !/placeholder\s*=\s*["'](?:HQ|AMMAN-01|SKU|ABC|123)/i.test(match),
      );
      if (relevant.length) {
        offenders.push({
          file: relative(process.cwd(), path).replaceAll("\\", "/"),
          matches: relevant,
        });
      }
    }

    expect(offenders).toEqual([]);
  });

  it("never branches business decisions on translated backend message prose", () => {
    const offenders = activeOwnedSources().flatMap((path) => {
      const source = stripComments(read(path));
      const hasMessageComparison = /(?:message|detail|error\.message)\s*(?:===|!==|\.includes\(|\.startsWith\()/m.test(source);
      return hasMessageComparison
        ? [relative(process.cwd(), path).replaceAll("\\", "/")]
        : [];
    });

    expect(offenders).toEqual([]);
  });

  it("retains modular presentation resources for every major Inventory surface", () => {
    const requiredResources = [
      "src/i18n/resources.ts",
      "src/pages/inventory/liveStock/i18n.ts",
      "src/pages/inventory/transfers/i18n.ts",
      "src/pages/inventory/stocktake/copy.ts",
      "src/pages/inventory/ledger/ledgerI18n.ts",
      "src/pages/inventory/access/copy.ts",
      "src/pages/inventory/warehouse-locations/i18n.ts",
    ];

    for (const path of requiredResources) {
      expect(readFileSync(resolve(process.cwd(), path), "utf8").length, path).toBeGreaterThan(100);
    }

    const shared = readFileSync(resolve(process.cwd(), "src/i18n/resources.ts"), "utf8");
    expect(shared).toContain("inventoryShell:");
    expect(shared).toContain("inventoryLive:");
    expect(shared).toContain("inventoryInbound:");
  });

  it("uses Latin digits for Arabic presentation without losing exact decimal value", () => {
    expect(resolveAppLocale("ar")).toContain("nu-latn");
    const integer = formatInventoryInteger(123456, "ar");
    const decimal = formatInventoryDecimal(12.375, "ar");

    expect(integer).toMatch(/[0-9]/);
    expect(integer).not.toMatch(/[\u0660-\u0669\u06f0-\u06f9]/);
    expect(decimal.replace(/[^0-9]/g, "")).toContain("12375");
    expect(decimal).not.toMatch(/[\u0660-\u0669\u06f0-\u06f9]/);
  });

  it("provides equivalent Arabic and English Warehouse/Branch semantics", () => {
    const arWarehouse = warehouseLocationsCopy("ar");
    const enWarehouse = warehouseLocationsCopy("en");
    const arBranch = branchManagementCopy("ar");
    const enBranch = branchManagementCopy("en");

    expect(arWarehouse.title).not.toBe(enWarehouse.title);
    expect(arWarehouse.active).toBeTruthy();
    expect(enWarehouse.active).toBeTruthy();
    expect(arWarehouse.blockers.OPEN_STOCKTAKE).toBeTruthy();
    expect(enWarehouse.blockers.OPEN_STOCKTAKE).toBeTruthy();
    expect(arBranch.manage).not.toBe(enBranch.manage);
    expect(arBranch.reasonRequired).toBeTruthy();
    expect(enBranch.reasonRequired).toBeTruthy();
  });
});
