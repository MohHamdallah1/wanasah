import { readFileSync } from "node:fs";

import {
  beforeEach,
  describe,
  expect,
  it,
} from "vitest";

import {
  durableScope,
  getOrCreateDurableCommand,
  readDurableCommand,
} from "@/lib/durableOperations";
import {
  isProductCreateCommandPayload,
  productCreateRequestBody,
  productDraftFromCreateCommand,
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
  value.replace(/\s+/g, " ").trim();

const command:
  ProductCreateCommandPayload = {
    name: "Test Product",
    family_mode: "existing",
    family_id: 7,
    family_name: null,
    family_label: "Snacks",
    package_uom_code:
      "CARTON",
    units_per_package: 50,
    package_price:
      "13.500",
    unit_price: null,
    unit_barcode:
      "UNIT-123",
    package_barcode:
      "PACK-123",
    lot_control_mode:
      "OPTIONAL",
    expiry_control_mode:
      "REQUIRED",
  };

describe(
  "Products P9 create/import/detail completeness",
  () => {
    beforeEach(() => {
      localStorage.clear();
    });

    it("keeps Quick Create exactly aligned with the final SimpleProductCreate contract", () => {
      const backend = compact(
        readSource(
          "../../../wa_backend/api/simple_products.py",
        ),
      );
      const mutation = compact(
        readSource(
          "../pages/products/create/useCreateProductMutation.ts",
        ),
      );

      for (const field of [
        "name",
        "family_id",
        "family_name",
        "package_uom_code",
        "units_per_package",
        "package_price",
        "unit_price",
        "unit_barcode",
        "package_barcode",
        "lot_control_mode",
        "expiry_control_mode",
      ]) {
        expect(backend).toContain(
          field,
        );
        expect(mutation).toContain(
          field,
        );
      }
      expect(mutation).toContain(
        "productCreateRequestBody( command.payload )",
      );
    });

    it("keeps ordinary create compact while advanced tracking and barcodes stay deliberate", () => {
      const modal = compact(
        readSource(
          "../pages/products/create/CreateProductModal.tsx",
        ),
      );
      const advanced = compact(
        readSource(
          "../pages/products/create/CreateProductAdvancedSection.tsx",
        ),
      );
      const commerce = compact(
        readSource(
          "../pages/products/create/CreateProductCommerceSection.tsx",
        ),
      );

      expect(modal).toContain(
        "createAdvancedExpanded",
      );
      expect(advanced).toContain(
        '"products.quickCreate.advancedTitle"',
      );
      expect(advanced).toContain(
        '"products.tracking.createChange"',
      );
      expect(advanced).toContain(
        '"products.barcodeSection"',
      );
      expect(commerce).toContain(
        "draft.has_package",
      );
    });

    it("matches the frontend import mapping to the backend canonical import contract", () => {
      const importFields = compact(
        readSource(
          "../pages/products/import/importFields.ts",
        ),
      );
      const backend = compact(
        readSource(
          "../../../wa_backend/product_import_localization.py",
        ),
      );
      const fields = [
        "name",
        "family",
        "package_uom",
        "units_per_package",
        "package_price",
        "unit_price",
        "unit_barcode",
        "package_barcode",
        "lot_control_mode",
        "expiry_control_mode",
      ];

      for (const field of fields) {
        expect(importFields).toContain(
          `"${field}"`,
        );
        expect(backend).toContain(
          `"${field}"`,
        );
      }
    });

    it("keeps Product Details complete without exposing technical catalog internals", () => {
      const drawer = compact(
        readSource(
          "../pages/products/detail/ProductDetailDrawer.tsx",
        ),
      );
      const hero = compact(
        readSource(
          "../pages/products/detail/ProductDetailHero.tsx",
        ),
      );
      const detailSurface =
        `${drawer} ${hero}`;

      for (const evidence of [
        "product.name",
        "product.family_name",
        "product.sku",
        "product.base_uom_code",
        "product.package_uom_code",
        "product.units_per_package",
        "product.lot_control_mode",
        "product.expiry_control_mode",
        "product.unit_barcode",
        "product.package_barcode",
        "product.lifecycle_status",
        "product.operational_hold",
        "pricingVisible",
        "canRenameProduct",
        "canReassignFamily",
        "canEditPrice",
        "canEditTracking",
        "canManageBarcodes",
        "canManageLifecycle",
        "canManageAdvancedUom",
      ]) {
        expect(detailSurface).toContain(
          evidence,
        );
      }
      expect(detailSurface).not.toContain(
        "product_location",
      );
    });

    it("restores the exact unresolved create command and blocks changed payloads", async () => {
      expect(
        isProductCreateCommandPayload(
          command,
        ),
      ).toBe(true);
      expect(
        productCreateRequestBody(
          command,
        ),
      ).toEqual({
        name: "Test Product",
        family_id: 7,
        family_name: null,
        package_uom_code:
          "CARTON",
        units_per_package: 50,
        package_price:
          "13.500",
        unit_price: null,
        unit_barcode:
          "UNIT-123",
        package_barcode:
          "PACK-123",
        lot_control_mode:
          "OPTIONAL",
        expiry_control_mode:
          "REQUIRED",
      });
      expect(
        productDraftFromCreateCommand(
          command,
        ),
      ).toMatchObject({
        name: "Test Product",
        family_mode:
          "existing",
        family_id: 7,
        family: "Snacks",
        has_package: true,
        units_per_package:
          "50",
      });

      const scope =
        durableScope(
          1,
          2,
          "product-create",
        );
      const first =
        await getOrCreateDurableCommand(
          scope,
          command,
        );
      const restored =
        await readDurableCommand<
          ProductCreateCommandPayload
        >(scope);

      expect(restored).toEqual(
        first,
      );
      await expect(
        getOrCreateDurableCommand(
          scope,
          {
            ...command,
            name:
              "Changed Product",
          },
        ),
      ).rejects.toMatchObject({
        code:
          "DURABLE_OPERATION_PENDING",
      });
    });
  },
);
