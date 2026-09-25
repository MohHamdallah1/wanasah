import {
  existsSync,
  readFileSync,
} from "node:fs";

import {
  describe,
  expect,
  it,
} from "vitest";

import {
  deriveProductsCapabilities,
} from "@/pages/products/deriveProductsCapabilities";
import {
  isProductCreateCommandPayload,
  productCreateRequestBody,
  type ProductCreateCommandPayload,
} from "@/pages/products/create/productCreateCommand";

const readSource = (
  relativePath: string,
): string =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

const compact = (
  value: string,
): string =>
  value
    .replace(/\s+/g, " ")
    .trim();

const capabilities = (
  permissions: string[],
  admin = false,
) => {
  const set =
    new Set(permissions);
  return deriveProductsCapabilities({
    isCompanyAdmin: admin,
    can: (code) =>
      set.has(code),
    canAny: (code) =>
      set.has(code),
  });
};

describe(
  "Products P9.3 functional acceptance",
  () => {
    it("accepts both packaged and unit-only Quick Create contracts", () => {
      const packaged:
        ProductCreateCommandPayload = {
          name: "Packaged",
          family_mode: "none",
          family_id: null,
          family_name: null,
          family_label: "",
          package_uom_code:
            "CARTON",
          units_per_package: 24,
          package_price:
            "12.000",
          unit_price: null,
          unit_barcode: null,
          package_barcode: null,
          lot_control_mode:
            "OPTIONAL",
          expiry_control_mode:
            "REQUIRED",
        };
      const unitOnly:
        ProductCreateCommandPayload = {
          ...packaged,
          name: "Unit only",
          package_uom_code: null,
          units_per_package: 1,
          package_price: null,
          unit_price: "0.500",
        };

      expect(
        isProductCreateCommandPayload(
          packaged,
        ),
      ).toBe(true);
      expect(
        isProductCreateCommandPayload(
          unitOnly,
        ),
      ).toBe(true);
      expect(
        productCreateRequestBody(
          unitOnly,
        ),
      ).toMatchObject({
        package_uom_code: null,
        units_per_package: 1,
        package_price: null,
        unit_price: "0.500",
      });
    });

    it("keeps rename and family create/rename/reassignment as distinct safe workflows", () => {
      const page = compact(
        readSource(
          "../pages/products/ProductsPage.tsx",
        ),
      );
      const familyManager =
        compact(
          readSource(
            "../pages/products/family/ProductFamiliesManager.tsx",
          ),
        );
      const reassign =
        compact(
          readSource(
            "../pages/products/family/ProductFamilyReassignDialog.tsx",
          ),
        );
      const rename = compact(
        readSource(
          "../pages/products/rename/ProductRenameDialog.tsx",
        ),
      );

      expect(page).toContain(
        "<ProductRenameDialog",
      );
      expect(page).toContain(
        "<ProductFamilyReassignDialog",
      );
      expect(page).toContain(
        "<ProductFamiliesManager",
      );
      expect(rename).toContain(
        "expected_version",
      );
      expect(reassign).toContain(
        "/catalog/variants/${product.id}/family",
      );
      expect(reassign).toContain(
        "PRODUCT_FAMILY_REASSIGN_HISTORY_LOCKED",
      );
      expect(familyManager).toContain(
        "getOrCreateDurableCommand",
      );
    });

    it("keeps package structure readable while structural history locks stay authoritative", () => {
      const drawer = compact(
        readSource(
          "../pages/products/detail/ProductDetailDrawer.tsx",
        ),
      );
      const advanced = compact(
        readSource(
          "../pages/products/advanced-uom/AdvancedUomDashboard.tsx",
        ),
      );
      const lifecycle = compact(
        readSource(
          "../../../wa_backend/product_lifecycle.py",
        ),
      );

      expect(drawer).toContain(
        "product.base_uom_code",
      );
      expect(drawer).toContain(
        "product.units_per_package",
      );
      expect(drawer).toContain(
        "canManageAdvancedUom && !product.simple_compatible",
      );
      expect(advanced).toContain(
        "/catalog/variants/${selectedVariant!.id}/conversions",
      );
      expect(lifecycle).toContain(
        "UOM_STRUCTURE_LOCKED",
      );
    });

    it("keeps barcode, tracking, lifecycle/hold/recall, archive and archived restore reachable", () => {
      const page = compact(
        readSource(
          "../pages/products/ProductsPage.tsx",
        ),
      );
      const filters = compact(
        readSource(
          "../pages/products/list/ProductsFiltersPanel.tsx",
        ),
      );
      const lifecycle = compact(
        readSource(
          "../pages/inventory/catalog/CatalogLifecycleActions.tsx",
        ),
      );

      expect(page).toContain(
        "<ProductBarcodeManager",
      );
      expect(page).toContain(
        "<ProductTrackingOverlays",
      );
      expect(page).toContain(
        "<ProductLifecycleManager",
      );
      expect(filters).toContain(
        '<option value="ARCHIVED">',
      );
      for (const command of [
        '"retire"',
        '"restore"',
        '"archive"',
        '"sales-hold"',
        '"release-sales-hold"',
        '"recall"',
        '"close-recall"',
      ]) {
        expect(lifecycle).toContain(
          command,
        );
      }
      expect(lifecycle).toContain(
        '"ARCHIVED"',
      );
    });

    it("keeps identity, pricing visibility and mutation authorities granular", () => {
      const readOnly =
        capabilities([
          "catalog.read",
        ]);
      const priceViewer =
        capabilities([
          "catalog.read",
          "pricing.view",
        ]);
      const priceManager =
        capabilities([
          "catalog.read",
          "pricing.view",
          "pricing.manage",
        ]);
      const catalogManager =
        capabilities([
          "catalog.read",
          "catalog.manage",
          "catalog.publish",
        ]);
      const fullManager =
        capabilities([
          "catalog.read",
          "catalog.manage",
          "catalog.publish",
          "catalog.retire",
          "catalog.restore",
          "catalog.archive",
          "catalog.hold",
          "pricing.view",
          "pricing.manage",
        ]);

      expect(
        readOnly.canViewPricing,
      ).toBe(false);
      expect(
        readOnly.canEditSimplePrice,
      ).toBe(false);
      expect(
        priceViewer.canViewPricing,
      ).toBe(true);
      expect(
        priceViewer.canEditSimplePrice,
      ).toBe(false);
      expect(
        priceManager.canEditSimplePrice,
      ).toBe(true);
      expect(
        priceManager.canManageCatalog,
      ).toBe(false);
      expect(
        priceManager.canCreateSimpleProduct,
      ).toBe(false);
      expect(
        catalogManager.canManageFamilies,
      ).toBe(true);
      expect(
        catalogManager.canCreateSimpleProduct,
      ).toBe(false);
      expect(
        fullManager.canCreateSimpleProduct,
      ).toBe(true);
      expect(
        fullManager.canImportProducts,
      ).toBe(true);
      expect(
        fullManager.canManageLifecycle,
      ).toBe(true);
    });

    it("keeps import success/failure/retry/resume and bounded error pagination explicit", () => {
      const modal = compact(
        readSource(
          "../pages/products/import/ImportProductModal.tsx",
        ),
      );
      const resume = compact(
        readSource(
          "../pages/products/import/useImportSessionResume.ts",
        ),
      );
      const commands = compact(
        readSource(
          "../pages/products/import/useImportProductCommands.ts",
        ),
      );
      const downloads = compact(
        readSource(
          "../pages/products/import/createImportDownloads.ts",
        ),
      );

      for (const status of [
        "NEEDS_MAPPING",
        "VALIDATION_FAILED",
        "FAILED",
        "COMPLETED",
      ]) {
        expect(modal).toContain(
          `"${status}"`,
        );
      }
      expect(modal).toContain(
        "pollError",
      );
      expect(resume).toContain(
        "sessionStorage.getItem",
      );
      expect(resume).toContain(
        '"products.importResumed"',
      );
      expect(commands).toContain(
        "/retry",
      );
      expect(downloads).toContain(
        "after_row=${afterRow}&limit=1000",
      );
      expect(downloads).toContain(
        "result.next_after_row",
      );
    });

    it("keeps search, every server filter, stable sorting and cursor resets wired", () => {
      const params = compact(
        readSource(
          "../pages/products/list/useProductsListParams.ts",
        ),
      );
      const actions = compact(
        readSource(
          "../pages/products/list/createProductsListActions.ts",
        ),
      );
      const queries = compact(
        readSource(
          "../pages/products/list/useProductsListQueries.ts",
        ),
      );

      for (const parameter of [
        "search",
        "family_id",
        "lifecycle",
        "tracking_type",
        "simple_compatible",
        "has_barcode",
        "has_price",
        "lot_tracked",
        "expiry_tracked",
        "sort_by",
        "sort_dir",
        "cursor",
      ]) {
        expect(params).toContain(
          parameter,
        );
      }
      expect(
        actions.match(
          /resetProductPagination\(\)/g,
        )?.length ?? 0,
      ).toBeGreaterThanOrEqual(
        10,
      );
      expect(actions).toContain(
        "const goPrevious",
      );
      expect(actions).toContain(
        "const goNext",
      );
      expect(queries).toContain(
        'queryKey: [ "simple-products", companyId, params, ]',
      );
    });

    it("keeps advanced-only backend capabilities intentionally out of normal Products", () => {
      const page = compact(
        readSource(
          "../pages/products/ProductsPage.tsx",
        ),
      );
      const families = compact(
        readSource(
          "../pages/products/family/ProductFamiliesManager.tsx",
        ),
      );
      const barcode = compact(
        readSource(
          "../pages/products/barcode/ProductBarcodeManager.tsx",
        ),
      );
      const lifecycle = compact(
        readSource(
          "../pages/products/lifecycle/ProductLifecycleManager.tsx",
        ),
      );

      expect(page).not.toContain(
        "/warehouse/product-locations",
      );
      expect(page).not.toContain(
        "/catalog/products",
      );
      expect(lifecycle).not.toContain(
        "onVariantDeleted=",
      );
      expect(barcode).not.toContain(
        "/catalog/gs1/parse",
      );
      expect(families).not.toContain(
        "brand",
      );
      expect(families).not.toContain(
        "category",
      );
      expect(families).not.toContain(
        "description",
      );
      expect(
        existsSync(
          new URL(
            "../pages/ProductsDashboard.tsx",
            import.meta.url,
          ),
        ),
      ).toBe(false);
    });

    it("keeps DRAFT hidden from the normal list while archived restore is opt-in", () => {
      const backend = compact(
        readSource(
          "../../../wa_backend/api/simple_products.py",
        ),
      );
      const filters = compact(
        readSource(
          "../pages/products/list/ProductsFiltersPanel.tsx",
        ),
      );

      expect(backend).toContain(
        '_PRODUCT_LIFECYCLES = {"ACTIVE", "RETIRING", "ARCHIVED"}',
      );
      expect(backend).toContain(
        'if lifecycle_value is None: stmt = stmt.where( ProductVariant.lifecycle_status.in_( ("ACTIVE", "RETIRING") ), )',
      );
      expect(backend).not.toContain(
        '_PRODUCT_LIFECYCLES = {"DRAFT"',
      );
      expect(filters).toContain(
        '<option value="ARCHIVED">',
      );
      expect(filters).not.toContain(
        '<option value="DRAFT">',
      );
    });
  },
);
