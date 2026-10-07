import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (relativePath: string) =>
  readFileSync(resolve(process.cwd(), "src/test", relativePath), "utf8");

describe("V1 quality and safety workflow closure", () => {
  it("records the whole-product issue in Products then opens handling after the recall succeeds", () => {
    const actions = read("../features/catalog/lifecycle/CatalogLifecycleActions.tsx");
    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");
    expect(actions).toContain('payload.command === "recall"');
    expect(actions).toContain("onManageWholeProductIssue?.();");
    expect(manager).toContain("<WholeProductQualityActionsPanel");
    expect(manager).toContain("onManageWholeProductIssue={() => setQualityOpen(true)}");
    expect(manager).not.toContain("createInventoryWholeProductIssueNavigationState");
  });

  it("prevents a whole-product safety issue until positive stock is proven", () => {
    const actions = read("../features/catalog/lifecycle/CatalogLifecycleActions.tsx");
    const panel = read("../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx");
    expect(actions).toContain("/recall-preflight");
    expect(actions).toContain("has_current_stock");
    expect(panel).toContain("recallHasCurrentStock !== true");
    expect(panel).toContain("catalogLifecycle.simple.qualityIssueNoStock");
    expect(panel).toContain("disabledReason");
    expect(panel).toContain("recallHasCurrentStock === false");
  });

  it("sends batch issues directly to Inventory batches without the intermediate picker", () => {
    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");
    const workspaceFocus = read("../features/inventory/workspaceFocusNavigation.ts");
    const inventoryPage = read("../pages/inventory/InventoryPage.tsx");
    expect(manager).toContain("createInventoryBatchFocusNavigationState");
    expect(workspaceFocus).not.toContain("batch-picker");
    expect(inventoryPage).not.toContain("QualityBatchPickerWorkspace");
  });

  it("keeps whole-product commands global and hides inventory implementation detail", () => {
    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");
    const commands = read("../features/inventory/quality/useProductQualityCommands.ts");
    const previewHook = read("../features/inventory/quality/useWholeProductQualityPreview.ts");
    expect(previewHook).toContain("/resolve-preview");
    expect(inline).toContain('openAction("DISPOSE")');
    expect(inline).toContain('openAction("RETURN_TO_VENDOR")');
    expect(inline).not.toContain("preview.data.locations");
    expect(inline).not.toContain("preview.data.batches");
    expect(inline).not.toContain("valuationLines");
    expect(inline).not.toContain("formatMoneyDisplay");
    expect(commands).not.toContain("source_location_id");
    expect(commands).not.toContain("batch_id");
    expect(commands).not.toContain("transfer_purpose");
  });

  it("shows the product package as the primary quantity and explains blocked actions", () => {
    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");
    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");
    expect(manager).toContain("product.package_uom_code");
    expect(manager).toContain("product.units_per_package");
    expect(inline).toContain("displayFactorToBase");
    expect(inline).toContain("WHOLE_PRODUCT_QUALITY_RESERVED_STOCK");
    expect(inline).toContain("blockerText");
    expect(inline).toContain("totalBaseQuantity");
  });

  it("reuses the saved issue reason and uses Supplier identity instead of manual recipient text", () => {
    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");
    const commands = read("../features/inventory/quality/useProductQualityCommands.ts");
    expect(inline).toContain("preview.data.issueReason");
    expect(inline).toContain("<SupplierSelector");
    expect(inline).not.toContain("recipientName");
    expect(inline).not.toContain("handoverReference");
    expect(inline).not.toContain("evidenceReference");
    expect(inline).not.toContain("disposalMethod");
    expect(commands).toContain("supplier_id");
    expect(commands).toContain("SYSTEM-${durable.requestId}");
  });

  it("uses a separate final password confirmation and never persists the credential", () => {
    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");
    const commands = read("../features/inventory/quality/useProductQualityCommands.ts");
    const passwordField = read("../features/inventory/quality/SupervisorPasswordField.tsx");
    expect(inline).toContain("finalConfirmOpen");
    expect(inline).toContain("<SupervisorPasswordField");
    expect(inline).toContain("postResolutionHold");
    expect(inline).toContain('setPostResolutionHold("NONE")');
    expect(inline).toContain('setPostResolutionHold("SALES_HOLD")');
    expect(passwordField).toContain('type="password"');
    expect(passwordField).toContain('autoComplete="off"');
    expect(passwordField).toContain('readOnly={!editable}');
    expect(passwordField).toContain('data-lpignore="true"');
    expect(commands).toContain("post_resolution_hold");
    expect(commands).toContain("confirmation_password: confirmationPassword");
    const durablePayload = commands.slice(
      commands.indexOf("const payload: QualityPayload"),
      commands.indexOf("const scope ="),
    );
    expect(durablePayload).not.toContain("confirmation_password");
  });

  it("keeps retry password-only while replay identity stays in durable storage", () => {
    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");
    const commands = read("../features/inventory/quality/useProductQualityCommands.ts");
    expect(commands).toContain("whole-product-quality-resolve-v3");
    expect(commands).toContain("whole-product-quality-resolve-v2");
    expect(commands).toContain("retryPending");
    expect(inline).toContain("commands.retryPending(password)");
  });

  it("uses short business wording for the operator flow", () => {
    const resources = read("../i18n/resources.ts");
    const translations = read("../i18n/productQualityInline.ts");
    expect(resources).toContain('manageConfirmedIssue: "معالجة"');
    expect(resources).toContain('qualityIssueNoStock: "رصيد المنتج الحالي صفر؛ لا توجد كمية يمكن تطبيق مشكلة جودة أو سلامة عليها."');
    expect(translations).toContain('disposeAll: "إتلاف الكمية"');
    expect(translations).toContain('returnAll: "إرجاع للمورد"');
    expect(translations).toContain('title: "التأكيد النهائي"');
    expect(translations).toContain('reactivate: "إعادة تفعيل المنتج"');
    expect(translations).toContain('keepStopped: "إبقاء المنتج متوقفًا"');
    expect(translations).not.toContain("إجمالي القيمة الدفترية");
    expect(translations).not.toContain("FIFO");
  });
});
