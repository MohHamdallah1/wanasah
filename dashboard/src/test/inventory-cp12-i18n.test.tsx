import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import ts from "typescript";
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

const presentationResourceBasenames = new Set([
  "copy.ts",
  "i18n.ts",
  "ledgerI18n.ts",
  "uiCopy.ts",
  "branchSelectorI18n.ts",
  "permissionLabels.ts",
  "batchIndexI18n.ts",
  "batchActionsI18n.ts",
]);

const nonPresentationContractBasenames = new Set([
  "contracts.ts",
  "parsers.ts",
  "branchContracts.ts",
  "inventoryUtils.ts",
]);

const collect = (directory: string): string[] =>
  readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return collect(path);
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });

const activeOwnedSources = () =>
  collect(ROOT)
    .filter((path) => !path.endsWith(".test.ts") && !path.endsWith(".test.tsx"))
    .filter((path) => !presentationResourceBasenames.has(path.split(/[\\/]/).at(-1) ?? ""))
    .filter((path) => !nonPresentationContractBasenames.has(path.split(/[\\/]/).at(-1) ?? ""))
    .filter((path) => !forbiddenCp3.has(relative(ROOT, path).replaceAll("\\", "/")));

const read = (path: string) => readFileSync(path, "utf8");
const displayPath = (path: string) => relative(process.cwd(), path).replaceAll("\\", "/");
const containsArabic = (value: string) => /[\u0600-\u06ff]/.test(value);
const looksLikeNaturalLanguage = (value: string) => {
  const clean = value.replace(/\s+/g, " ").trim();
  if (!clean || !/[A-Za-z\u0600-\u06ff]/.test(clean)) return false;
  if (/^(?:SKU|FEFO|ID|V1|HQ|AMMAN-01|ABC)$/i.test(clean.replace(/[:.]$/, ""))) return false;
  return clean.length >= 3;
};
const isMachineCode = (value: string) => /^[A-Z][A-Z0-9_:-]+$/.test(value);

const parse = (path: string) => ts.createSourceFile(
  path,
  read(path),
  ts.ScriptTarget.Latest,
  true,
  path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
);

const literalText = (node: ts.Node): string | null => {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  return null;
};

const unwrapExpression = (node: ts.Expression): ts.Expression => {
  let current = node;
  while (
    ts.isParenthesizedExpression(current) ||
    ts.isAsExpression(current) ||
    ts.isTypeAssertionExpression(current) ||
    ts.isNonNullExpression(current)
  ) {
    current = current.expression;
  }
  return current;
};

const isMessageLikeExpression = (node: ts.Expression): boolean => {
  const expression = unwrapExpression(node);
  if (ts.isIdentifier(expression)) {
    return expression.text === "message" || expression.text === "detail";
  }
  if (ts.isPropertyAccessExpression(expression)) {
    return expression.name.text === "message" || expression.name.text === "detail";
  }
  if (ts.isElementAccessExpression(expression) && expression.argumentExpression) {
    const key = literalText(expression.argumentExpression);
    return key === "message" || key === "detail";
  }
  return false;
};

const expressionRootIdentifier = (node: ts.Expression): string | null => {
  const expression = unwrapExpression(node);
  if (ts.isIdentifier(expression)) return expression.text;
  if (ts.isPropertyAccessExpression(expression)) return expressionRootIdentifier(expression.expression);
  if (ts.isElementAccessExpression(expression)) return expressionRootIdentifier(expression.expression);
  return null;
};

const isTranslatedPresentationExpression = (node: ts.Expression): boolean => {
  const expression = unwrapExpression(node);
  const text = literalText(expression);
  if (text !== null) return looksLikeNaturalLanguage(text) && !isMachineCode(text);

  if (ts.isCallExpression(expression)) {
    const callee = unwrapExpression(expression.expression);
    if (ts.isIdentifier(callee) && ["t", "transferText", "ledgerText"].includes(callee.text)) return true;
  }

  return expressionRootIdentifier(expression) === "copy";
};

const isToastCall = (node: ts.CallExpression) =>
  ts.isPropertyAccessExpression(node.expression) &&
  ts.isIdentifier(node.expression.expression) &&
  node.expression.expression.text === "toast";

const isErrorConstruction = (node: ts.NewExpression) =>
  ts.isIdentifier(node.expression) && node.expression.text === "Error";

const userFacingLiteralOffenders = (path: string) => {
  const sourceFile = parse(path);
  const matches: string[] = [];

  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node) && looksLikeNaturalLanguage(node.text)) {
      matches.push(node.text.replace(/\s+/g, " ").trim());
    }

    if (ts.isJsxAttribute(node) && ["aria-label", "title", "placeholder"].includes(node.name.getText(sourceFile))) {
      if (node.initializer && ts.isStringLiteral(node.initializer) && looksLikeNaturalLanguage(node.initializer.text)) {
        matches.push(`${node.name.getText(sourceFile)}=${node.initializer.text}`);
      }
    }

    if (ts.isCallExpression(node) && isToastCall(node)) {
      const text = node.arguments[0] ? literalText(node.arguments[0]) : null;
      if (text && looksLikeNaturalLanguage(text)) matches.push(`toast:${text}`);
    }

    if (ts.isNewExpression(node) && isErrorConstruction(node)) {
      const text = node.arguments?.[0] ? literalText(node.arguments[0]) : null;
      if (text && looksLikeNaturalLanguage(text) && !isMachineCode(text)) {
        matches.push(`Error:${text}`);
      }
    }

    ts.forEachChild(node, visit);
  };

  visit(sourceFile);
  return [...new Set(matches)];
};

const messageProseBranchingOffenders = (path: string) => {
  const sourceFile = parse(path);
  const matches: string[] = [];
  const comparisonOperators = new Set([
    ts.SyntaxKind.EqualsEqualsToken,
    ts.SyntaxKind.EqualsEqualsEqualsToken,
    ts.SyntaxKind.ExclamationEqualsToken,
    ts.SyntaxKind.ExclamationEqualsEqualsToken,
  ]);

  const visit = (node: ts.Node) => {
    if (ts.isBinaryExpression(node) && comparisonOperators.has(node.operatorToken.kind)) {
      const leftMessage = isMessageLikeExpression(node.left);
      const rightMessage = isMessageLikeExpression(node.right);
      if (
        (leftMessage && isTranslatedPresentationExpression(node.right)) ||
        (rightMessage && isTranslatedPresentationExpression(node.left))
      ) {
        matches.push(node.getText(sourceFile));
      }
    }

    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      ["includes", "startsWith"].includes(node.expression.name.text) &&
      isMessageLikeExpression(node.expression.expression) &&
      node.arguments.some((argument) => isTranslatedPresentationExpression(argument))
    ) {
      matches.push(node.getText(sourceFile));
    }

    ts.forEachChild(node, visit);
  };

  visit(sourceFile);
  return [...new Set(matches)];
};

describe("CP12 Inventory i18n closure", () => {
  it("keeps active owned implementation free of inline Arabic presentation literals", () => {
    const offenders = activeOwnedSources().flatMap((path) => {
      const sourceFile = parse(path);
      let found = false;
      const visit = (node: ts.Node) => {
        const text = literalText(node);
        if (text && containsArabic(text)) found = true;
        if (!found) ts.forEachChild(node, visit);
      };
      visit(sourceFile);
      return found ? [displayPath(path)] : [];
    });

    expect(offenders).toEqual([]);
  });

  it("keeps obvious user-facing natural-language literals out of owned React implementation", () => {
    const offenders = activeOwnedSources()
      .filter((path) => path.endsWith(".tsx"))
      .map((path) => ({ file: displayPath(path), matches: userFacingLiteralOffenders(path) }))
      .filter((entry) => entry.matches.length > 0);

    expect(offenders).toEqual([]);
  });

  it("never branches business decisions on translated backend message prose", () => {
    const offenders = activeOwnedSources()
      .map((path) => ({ file: displayPath(path), matches: messageProseBranchingOffenders(path) }))
      .filter((entry) => entry.matches.length > 0);

    expect(offenders).toEqual([]);
  });

  it("retains modular presentation resources for every major Inventory surface", () => {
    const requiredResources = [
      "src/i18n/resources.ts",
      "src/pages/inventory/liveStock/i18n.ts",
      "src/pages/inventory/transfers/i18n.ts",
      "src/pages/inventory/stocktake/copy.ts",
      "src/pages/inventory/stocktake/uiCopy.ts",
      "src/pages/inventory/ledger/ledgerI18n.ts",
      "src/pages/inventory/access/copy.ts",
      "src/pages/inventory/warehouse-locations/i18n.ts",
      "src/pages/inventory/warehouse-locations/branchSelectorI18n.ts",
      "src/pages/inventory/stock-policy/i18n.ts",
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
