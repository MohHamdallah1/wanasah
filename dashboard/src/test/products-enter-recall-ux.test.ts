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

describe("Products fast Enter and sales-status UX", () => {
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
      "../pages/inventory/catalog/CatalogLifecycleSimplePanel.tsx",
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

  it("shows the operational difference between sales pause and withdrawal", () => {
    const source = read(
      "../pages/inventory/catalog/CatalogLifecycleSimplePanel.tsx",
    );

    expect(source).toContain(
      "catalogLifecycle.simple.salesHoldDifference",
    );
    expect(source).toContain(
      "catalogLifecycle.simple.recallDifference",
    );
    expect(source).toContain(
      "catalogLifecycle.simple.actionHints.salesHold",
    );
    expect(source).toContain(
      "catalogLifecycle.simple.actionHints.recall",
    );
    expect(source).toContain(
      "catalogLifecycle.simple.actionHints.closeRecall",
    );
  });

  it("preserves and displays backend recall-completion blockers", () => {
    const actions = read(
      "../pages/inventory/catalog/CatalogLifecycleActions.tsx",
    );
    const panel = read(
      "../pages/inventory/catalog/CatalogLifecycleSimplePanel.tsx",
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
  it("keeps user-facing wording commercial", () => {
    const resources = read("../i18n/resources.ts");
    for (const oldTerm of ["سحب المنتج من التداول", "مسحوب من التداول", "إعادة المنتج للتداول", "Withdraw product from circulation", "Withdrawn from circulation", "Return product to circulation"]) expect(resources).not.toContain(oldTerm);
    for (const term of ["إيقاف البيع بسبب مشكلة", "موقوف لحين المعالجة", "إعادة إتاحة البيع", "حالة المنتج", "حالة البيع"]) expect(resources).toContain(term);
  });

});
