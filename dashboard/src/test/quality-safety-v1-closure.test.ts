import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (relativePath: string) =>
  readFileSync(resolve(process.cwd(), "src/test", relativePath), "utf8");

describe("V1 quality and safety workflow closure", () => {
  it("records a whole-product issue without forcing immediate navigation", () => {
    const actions = read(
      "../features/catalog/lifecycle/CatalogLifecycleActions.tsx",
    );
    expect(actions).not.toContain('payload.command === "recall"');
    expect(actions).toContain("onManageWholeProductIssue");
  });

  it("keeps one primary affected-quantity action instead of duplicating inventory balance navigation", () => {
    const panel = read(
      "../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx",
    );
    expect(panel).toContain("recallReadyToClose ?");
    expect(panel).toContain('catalogLifecycle.simple.manageConfirmedIssue');
    expect(panel).toContain("productQualityWorkspace.affectedStockTitle");
    expect(panel).not.toContain('item.code !== "INVENTORY_BALANCE"');
  });

  it("does not present a released batch historical reason as the current whole-product issue", () => {
    const section = read(
      "../pages/inventory/quality/WholeProductIssueBatchSection.tsx",
    );
    const resources = read("../i18n/resources.ts");
    expect(section).toContain('batch.batch.disposition !== "RELEASED"');
    expect(resources).toContain(
      "لا يوجد قيد مستقل على هذه الدفعة؛ منع البيع الحالي سببه إيقاف المنتج بالكامل",
    );
  });

  it("exposes server-owned handling destination setup from warehouse management", () => {
    const card = read(
      "../pages/inventory/warehouse-locations/QualityHandlingDestinationsCard.tsx",
    );
    const warehouses = read("../pages/inventory/TabWarehouseLocations.tsx");
    const workspace = read(
      "../pages/inventory/quality/WholeProductIssueWorkspace.tsx",
    );
    expect(card).toContain('access.can("inventory.transfer_policy.manage")');
    expect(card).toContain('/warehouse/operational-policy/transfer-destinations"');
    expect(card).toContain('/warehouse/operational-policy/transfer-destinations/draft"');
    expect(card).toContain("/publish`");
    expect(warehouses).toContain("<QualityHandlingDestinationsCard />");
    expect(workspace).toContain("productQualityWorkspace.configureDestinations");
    expect(workspace).toContain("needsDestinationSetup");
    expect(workspace).not.toContain("ProductQualityReadiness");
    expect(workspace).not.toContain("common.refresh");
  });

  it("uses plain business wording for the post-stop handling journey", () => {
    const resources = read("../i18n/resources.ts");
    expect(resources).toContain('manageConfirmedIssue: "معالجة الكميات المتأثرة"');
    expect(resources).toContain('closeRecall: "إغلاق المشكلة وإعادة البيع"');
    expect(resources).toContain('manageConfirmedIssue: "Handle affected quantities"');
    expect(resources).toContain('closeRecall: "Close issue and resume sales"');
  });
});
