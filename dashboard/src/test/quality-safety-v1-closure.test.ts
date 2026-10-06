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
    const mainInventory = read("../pages/inventory/MainInventory.tsx");
    const navigation = read("../features/inventory/navigation.ts");
    expect(mainInventory).not.toContain("WholeProductIssueManager");
    expect(navigation).not.toContain('kind: "quality-issue"');
  });

  it("keeps one primary affected-quantity action and hosts Inventory-owned commands through a shared feature", () => {
    const panel = read("../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx");
    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");
    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");
    expect(panel).toContain("recallReadyToClose ?");
    expect(panel).toContain('catalogLifecycle.simple.manageConfirmedIssue');
    expect(manager).toContain("WholeProductQualityActionsPanel");
    expect(manager).not.toContain("@/pages/inventory/");
    expect(inline).toContain("useProductQualityCommands");
    expect(inline).toContain("products.qualityInline.actions.dispose");
    expect(inline).toContain("products.qualityInline.actions.returnVendor");
    expect(inline).toContain("products.qualityInline.actions.confirmDisposal");
    expect(inline).toContain("products.qualityInline.actions.confirmVendor");
  });

  it("keeps handling-destination setup inline instead of redirecting the operator", () => {
    const sharedCard = read("../features/inventory/quality/QualityHandlingDestinationsCard.tsx");
    const wrapper = read("../pages/inventory/warehouse-locations/QualityHandlingDestinationsCard.tsx");
    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");
    const warehouses = read("../pages/inventory/TabWarehouseLocations.tsx");
    expect(sharedCard).toContain('access.can("inventory.transfer_policy.manage")');
    expect(sharedCard).toContain("/warehouse/operational-policy/transfer-destinations");
    expect(wrapper).toContain("@/features/inventory/quality/QualityHandlingDestinationsCard");
    expect(warehouses).toContain("<QualityHandlingDestinationsCard />");
    expect(inline).toContain("<QualityHandlingDestinationsCard compact");
    expect(inline).not.toContain('navigate("/inventory"');
  });

  it("uses plain business wording for the post-stop handling journey", () => {
    const resources = read("../i18n/resources.ts");
    const inlineTranslations = read("../i18n/productQualityInline.ts");
    expect(resources).toContain('manageConfirmedIssue: "معالجة الكميات المتأثرة"');
    expect(resources).toContain('closeRecall: "إغلاق المشكلة وإعادة البيع"');
    expect(inlineTranslations).toContain('dispose: "إتلاف"');
    expect(inlineTranslations).toContain('returnVendor: "إرجاع للمورد / المصنع"');
    expect(inlineTranslations).toContain('confirmDisposal: "تأكيد الإتلاف"');
    expect(inlineTranslations).toContain('confirmVendor: "تأكيد التسليم"');
  });
});
