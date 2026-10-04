import {
  readFileSync,
} from "node:fs";
import {
  describe,
  expect,
  it,
} from "vitest";

const read = (relativePath: string) =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

describe("Products fast Enter and commercial-status UX", () => {
  it("keeps Enter-to-save across text-entry product actions", () => {
    const price = read(
      "../pages/products/pricing/PriceEditModal.tsx",
    );
    const rename = read(
      "../pages/products/rename/ProductRenameDialog.tsx",
    );
    const family = read(
      "../pages/products/family/ProductFamilyReassignDialog.tsx",
    );
    const barcode = read(
      "../pages/products/barcode/ProductBarcodeSimplePanel.tsx",
    );
    const lifecycle = read(
      "../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx",
    );

    expect(price).toContain(
      'event.key === "Enter"',
    );
    expect(price).toContain(
      "onSubmit();",
    );

    expect(rename).toContain(
      'event.key === "Enter"',
    );
    expect(rename).toContain(
      "void save();",
    );

    expect(family).toContain(
      'event.key !== "Enter"',
    );
    expect(family).toContain(
      "void save(familyId);",
    );

    expect(barcode).toContain(
      '"Enter"',
    );
    expect(barcode).toContain(
      "void save();",
    );

    expect(lifecycle).toContain(
      '"Enter"',
    );
    expect(lifecycle).toContain(
      "onConfirm();",
    );
  });

  it("separates ordinary product actions from quality-issue scope", () => {
    const source = read(
      "../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx",
    );

    expect(source).toContain(
      "catalogLifecycle.simple.qualityIssueTitle",
    );
    expect(source).toContain(
      "catalogLifecycle.simple.issueScopeQuestion",
    );
    expect(source).toContain(
      "catalogLifecycle.simple.issueScopes.batch.label",
    );
    expect(source).toContain(
      "catalogLifecycle.simple.issueScopes.product.label",
    );
    expect(source).toContain(
      "onManageBatchIssue();",
    );
    expect(source).toContain(
      'onChooseCommand("recall")',
    );
    expect(source).toContain(
      "showTemporaryRecovery",
    );
    expect(source).toContain(
      "showProblemRecovery",
    );
  });

  it("preserves and displays backend issue-completion blockers", () => {
    const actions = read(
      "../features/catalog/lifecycle/CatalogLifecycleActions.tsx",
    );
    const panel = read(
      "../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx",
    );

    expect(actions).toContain(
      "apiErrorContext",
    );
    expect(actions).toContain(
      '"PRODUCT_RECALL_COMPLETION_REQUIRED"',
    );
    expect(actions).toContain(
      "readRecallCompletionBlockers",
    );
    expect(actions).toContain(
      "recallCompletionBlockers={",
    );

    expect(panel).toContain(
      "recallCompletionBlockers.length > 0",
    );
    expect(panel).toContain(
      "catalogLifecycle.simple.recallCompletionTitle",
    );
    expect(panel).toContain(
      "catalogLifecycle.simple.recallCompletionHint",
    );
    expect(panel).toContain(
      "catalogLifecycle.blockers.",
    );
  });

  it("keeps user-facing wording commercial and unified", () => {
    const resources = read("../i18n/resources.ts");
    for (const oldTerm of [
      "سحب المنتج من التداول",
      "مسحوب من التداول",
      "إعادة المنتج للتداول",
      "Withdraw product from circulation",
      "Withdrawn from circulation",
      "Return product to circulation",
      "حالة المنتج والبيع",
      "Product & sales status",
      "قيد الأرشفة",
      "قيد الإنهاء",
    ]) {
      expect(resources).not.toContain(oldTerm);
    }
    for (const term of [
      "متاح للبيع",
      "موقوف",
      "خارج الاستخدام",
      "مؤرشف",
      "إيقاف البيع مؤقتًا",
      "مشكلة جودة أو سلامة",
      "أين توجد المشكلة؟",
      "دفعة محددة",
      "المنتج بالكامل",
      "استدعاء المنتج بالكامل",
      "إعادة البيع",
    ]) {
      expect(resources).toContain(term);
    }
  });
});
