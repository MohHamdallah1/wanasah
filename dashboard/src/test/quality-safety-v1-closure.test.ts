import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (relativePath: string) =>
  readFileSync(resolve(process.cwd(), "src/test", relativePath), "utf8");

describe("V1 quality and safety workflow closure", () => {
  it("records a whole-product issue without forcing navigation away from Products", () => {
    const actions = read("../features/catalog/lifecycle/CatalogLifecycleActions.tsx");
    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");
    expect(actions).not.toContain('payload.command === "recall"');
    expect(actions).toContain("onManageWholeProductIssue");
    expect(manager).toContain("<WholeProductQualityActionsPanel");
    expect(manager).toContain("onManageWholeProductIssue={() => setQualityOpen(true)}");
    expect(manager).not.toContain("createInventoryWholeProductIssueNavigationState");
  });

  it("keeps whole-product handling global while Inventory remains backend authority", () => {
    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");
    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");
    const commands = read("../features/inventory/quality/useProductQualityCommands.ts");
    expect(manager).toContain("WholeProductQualityActionsPanel");
    expect(manager).not.toContain("@/pages/inventory/");
    expect(inline).toContain('openAction("DISPOSE")');
    expect(inline).toContain('openAction("RETURN_TO_VENDOR")');
    expect(inline).toContain("productQualityInline.actions.disposeAll");
    expect(inline).toContain("productQualityInline.actions.returnAll");
    expect(inline).not.toContain("QualityHandlingDestinationsCard");
    expect(inline).not.toContain("setupRequired");
    expect(inline).not.toContain("batchId");
    expect(commands).toContain("/resolve-all");
    expect(commands).not.toContain("source_location_id");
    expect(commands).not.toContain("batch_id");
    expect(commands).not.toContain("transfer_purpose");
  });

  it("keeps configurable handling destinations available only to workflows that need them", () => {
    const sharedCard = read("../features/inventory/quality/QualityHandlingDestinationsCard.tsx");
    const wrapper = read("../pages/inventory/warehouse-locations/QualityHandlingDestinationsCard.tsx");
    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");
    const warehouses = read("../pages/inventory/TabWarehouseLocations.tsx");
    expect(sharedCard).toContain('access.can("inventory.transfer_policy.manage")');
    expect(sharedCard).toContain("/warehouse/operational-policy/transfer-destinations");
    expect(wrapper).toContain("@/features/inventory/quality/QualityHandlingDestinationsCard");
    expect(warehouses).toContain("<QualityHandlingDestinationsCard />");
    expect(inline).not.toContain("QualityHandlingDestinationsCard");
  });

  it("uses plain business wording for one global decision", () => {
    const resources = read("../i18n/resources.ts");
    const translations = read("../i18n/productQualityInline.ts");
    expect(resources).toContain('manageConfirmedIssue: "معالجة الكميات المتأثرة"');
    expect(resources).toContain('closeRecall: "إغلاق المشكلة وإعادة البيع"');
    expect(translations).toContain('disposeAll: "إتلاف المنتج بالكامل"');
    expect(translations).toContain('returnAll: "إرجاع المنتج بالكامل للمورد / المصنع"');
    expect(translations).toContain('disposeButton: "تأكيد إتلاف جميع الكميات"');
    expect(translations).toContain('returnButton: "تأكيد تسليم جميع الكميات"');
    expect(translations).not.toContain("setupRequired");
  });
});
