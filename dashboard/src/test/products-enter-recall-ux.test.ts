import {
  readFileSync,
} from "node:fs";
import { resolve } from "node:path";
import {
  describe,
  expect,
  it,
} from "vitest";

const read = (relativePath: string) =>
  readFileSync(
    resolve(
      process.cwd(),
      "src/test",
      relativePath,
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
    const reasonField = read(
      "../components/forms/ReasonPresetField.tsx",
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

    expect(reasonField).toContain(
      'event.key === "Enter"',
    );
    expect(reasonField).toContain(
      "onSubmit();",
    );
    expect(lifecycle).toContain(
      "onSubmit={onConfirm}",
    );
    expect(lifecycle).toContain(
      '{t("common.back")}',
    );
    expect(lifecycle).toContain(
      "onClick={onCancel}",
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
    expect(panel).toContain('item.code !== "INVENTORY_BALANCE"');
    expect(panel).toContain('catalogLifecycle.simple.manageConfirmedIssue');
  });

  it("keeps V1 archival visible but disabled and deferred", () => {
    const panel = read(
      "../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx",
    );
    const resources = read("../i18n/resources.ts");

    expect(panel).toContain(
      "catalogLifecycle.simple.actionHints.archiveDeferred",
    );
    expect(panel).toContain(
      "onClick={() => undefined}",
    );
    expect(resources).toContain(
      "الأرشفة محفوظة لنسخة V2",
    );
    expect(resources).toContain(
      "Archiving is deferred to Version 2",
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
    for (const oldTerm of [
      "سحب المنتج بالكامل بسبب مشكلة",
      "إنهاء السحب بعد إرجاع الكميات",
      "سحب الدفعة من جميع المواقع",
      "إرجاع الكمية ضمن السحب",
      "Withdraw the whole product for an issue",
      "Complete withdrawal after quantities return",
      "Withdraw batch from all locations",
      "Return quantity through withdrawal",
    ]) {
      expect(resources).not.toContain(oldTerm);
    }
    for (const term of [
      "إيقاف دائم للمنتج",
      "Stop product permanently",
      "متاح للبيع",
      "موقوف",
      "خارج الاستخدام",
      "مؤرشف",
      "إيقاف البيع مؤقتًا",
      "مشكلة جودة أو سلامة",
      "أين توجد المشكلة؟",
      "دفعة محددة",
      "المنتج بالكامل",
      "معالجة الكميات المتأثرة",
      "إغلاق المشكلة وإعادة البيع",
      "منع بيع الدفعة",
      "استبعاد الدفعة من البيع نهائيًا",
      "نقل الكمية المتأثرة",
      "Handle affected quantities",
      "Close issue and resume sales",
      "Permanently exclude batch from sale",
    ]) {
      expect(resources).toContain(term);
    }
  });
});
