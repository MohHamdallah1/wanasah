import {
  readFileSync,
} from "node:fs";
import { fileURLToPath } from "node:url";

import {
  describe,
  expect,
  it,
} from "vitest";

const read = (relativePath: string) =>
  readFileSync(
    fileURLToPath(
      new URL(
        `../${relativePath}`,
        import.meta.url,
      ),
    ),
    "utf8",
  );

describe("Products P7 translation coverage", () => {
  it("keeps Product UI copy behind translations instead of raw language or enums", () => {
    const productFiles = [
      "src/pages/products/ProductsPage.tsx",
      "src/pages/products/ProductsPageHeader.tsx",
      "src/pages/products/list/ProductsListSection.tsx",
      "src/pages/products/list/ProductsListResults.tsx",
      "src/pages/products/list/ProductTableRow.tsx",
      "src/pages/products/list/ProductMobileCard.tsx",
      "src/pages/products/list/ProductRowActions.tsx",
      "src/pages/products/create/CreateProductBarcodeSection.tsx",
      "src/pages/products/create/CreateProductPricingSection.tsx",
      "src/pages/products/create/CreateProductTrackingSection.tsx",
      "src/pages/products/create/CreateProductPackagingSection.tsx",
      "src/pages/products/create/CreateProductIdentitySection.tsx",
      "src/pages/products/create/ProductFamilyField.tsx",
      "src/pages/products/create/ProductFamilyModeSelector.tsx",
      "src/pages/products/pricing/PriceEditModal.tsx",
      "src/pages/products/tracking/ProductTrackingEditor.tsx",
      "src/pages/products/tracking/ProductTrackingModePicker.tsx",
      "src/pages/products/tracking/ProductTrackingSimpleControls.tsx",
      "src/pages/products/rename/ProductRenameDialog.tsx",
      "src/pages/products/family/ProductFamilyReassignDialog.tsx",
      "src/pages/products/barcode/ProductBarcodeManager.tsx",
      "src/pages/products/barcode/ProductBarcodeSimplePanel.tsx",
      "src/pages/products/barcode/ProductBarcodeHistoryPanel.tsx",
      "src/pages/products/lifecycle/ProductLifecycleManager.tsx",
    ].map(read);

    for (const source of productFiles) {
      expect(source).not.toMatch(
        /[\u0600-\u06FF]{3,}/,
      );
    }

    const page = read(
      "src/pages/products/ProductsPage.tsx",
    );
    expect(page).toContain(
      "products.title",
    );
    expect(page).toContain(
      "products.add",
    );

    const header = read(
      "src/pages/products/ProductsPageHeader.tsx",
    );
    expect(header).toContain(
      "products.catalogTools",
    );

    const listSection = read(
      "src/pages/products/list/ProductsListSection.tsx",
    );
    expect(listSection).toContain(
      "products.searchPlaceholder",
    );

    const listResults = read(
      "src/pages/products/list/ProductsListResults.tsx",
    );
    expect(listResults).toContain(
      "products.columns.product",
    );

    const priceModal = read(
      "src/pages/products/pricing/PriceEditModal.tsx",
    );
    expect(priceModal).toContain(
      "products.priceEditor.title",
    );

    const trackingEditor = read(
      "src/pages/products/tracking/ProductTrackingEditor.tsx",
    );
    expect(trackingEditor).toContain(
      "products.trackingEditor.title",
    );

    const renameDialog = read(
      "src/pages/products/rename/ProductRenameDialog.tsx",
    );
    expect(renameDialog).toContain(
      "products.rename.title",
    );

    const familyDialog = read(
      "src/pages/products/family/ProductFamilyReassignDialog.tsx",
    );
    expect(familyDialog).toContain(
      "products.familyReassign.title",
    );

    const barcodeManager = read(
      "src/pages/products/barcode/ProductBarcodeManager.tsx",
    );
    expect(barcodeManager).toContain(
      "products.barcodeManager.title",
    );

    const lifecycleManager = read(
      "src/pages/products/lifecycle/ProductLifecycleManager.tsx",
    );
    expect(lifecycleManager).toContain(
      "products.lifecycleManager.title",
    );

    const advancedUom = read(
      "src/pages/products/advanced-uom/AdvancedUomDashboard.tsx",
    );
    expect(advancedUom).toContain(
      "products.details.lifecycleModes.${item.lifecycle_status}",
    );
    expect(
      /(^|[^$])\{item\.lifecycle_status\}/m.test(
        advancedUom,
      ),
    ).toBe(false);

    const tableRow = read(
      "src/pages/products/list/ProductTableRow.tsx",
    );
    const statusBadges = read(
      "src/pages/products/list/ProductStatusBadges.tsx",
    );
    expect(tableRow).toContain(
      "<ProductStatusBadges",
    );
    expect(statusBadges).toContain(
      "productTableStatus(item)",
    );
    expect(statusBadges).toContain(
      "t(status.valueKey)",
    );
    expect(statusBadges).toContain(
      "t(reason.valueKey)",
    );
    expect(
      /(^|[^$])\{item\.operational_hold\}/m.test(
        tableRow,
      ),
    ).toBe(false);

    const barcodeList = read(
      "src/pages/products/barcode/ProductBarcodeList.tsx",
    );
    const barcodeCreate = read(
      "src/pages/products/barcode/ProductBarcodeCreatePanel.tsx",
    );
    expect(barcodeList).toContain(
      "products.barcodeManager.types.${item.barcode_type}",
    );
    expect(barcodeCreate).toContain(
      "products.barcodeManager.types.${value}",
    );
  });
});
