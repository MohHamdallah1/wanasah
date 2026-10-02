import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { ProductBarcodeHistoryPanel } from "../pages/products/barcode/ProductBarcodeHistoryPanel";
import { ProductBarcodeSimplePanel } from "../pages/products/barcode/ProductBarcodeSimplePanel";
import type {
  ProductBarcodeRecord,
  SimpleProduct,
} from "../pages/products/contracts";

vi.mock(
  "react-i18next",
  () => ({
    useTranslation: () => ({
      t: (
        key: string,
      ) => key,
      i18n: {
        language: "ar",
        dir: () => "rtl",
      },
    }),
  }),
);

vi.mock(
  "@/lib/locale",
  () => ({
    resolveI18nLocale: () =>
      "ar-JO",
  }),
);

const product = (
  overrides: Partial<SimpleProduct> = {},
): SimpleProduct => ({
  id: 7,
  product_id: 70,
  name: "Test product",
  family_name: "Family",
  sku: "SKU-7",
  units_per_package: 50,
  legacy_packs_per_carton: 50,
  base_uom_id: 1,
  base_uom_code: "PIECE",
  package_uom_id: 2,
  package_uom_code: "CARTON",
  currency_code: "JOD",
  package_price: null,
  unit_price: null,
  unit_barcode: "123",
  package_barcode: "123",
  package_uses_base_barcode: true,
  version: 4,
  lot_control_mode: "REQUIRED",
  expiry_control_mode:
    "REQUIRED",
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  simple_compatible: true,
  ...overrides,
});

const barcode = (
  overrides: Partial<ProductBarcodeRecord> = {},
): ProductBarcodeRecord => ({
  id: 10,
  product_variant_id: 7,
  uom: {
    id: 1,
    code: "PIECE",
    name: "Piece",
  },
  barcode: "123",
  barcode_type: "INTERNAL",
  is_primary: true,
  valid_from:
    "2026-10-01T10:00:00",
  valid_to: null,
  is_active: true,
  version: 1,
  ...overrides,
});

describe(
  "Product barcode simple workflow",
  () => {
    it(
      "keeps old barcodes out of the everyday view and separates a shared package in one action",
      async () => {
        const onReplace =
          vi
            .fn()
            .mockResolvedValue(
              true,
            );
        const onAssign =
          vi
            .fn()
            .mockResolvedValue(
              true,
            );

        render(
          <ProductBarcodeSimplePanel
            product={product()}
            items={[
              barcode(),
              barcode({
                id: 9,
                barcode: "111",
                is_primary: false,
                is_active: false,
                valid_to:
                  "2026-09-30T10:00:00",
              }),
            ]}
            canMutate
            busy={false}
            onReplace={
              onReplace
            }
            onAssignIndependentPackage={
              onAssign
            }
          />,
        );

        expect(
          screen.getAllByText(
            "123",
          ).length,
        ).toBeGreaterThan(0);
        expect(
          screen.queryByText(
            "111",
          ),
        ).toBeNull();

        fireEvent.click(
          screen.getByRole(
            "button",
            {
              name:
                "products.barcodeManager.makePackageIndependent",
            },
          ),
        );

        const input =
          screen.getByRole(
            "textbox",
          );
        fireEvent.change(
          input,
          {
            target: {
              value:
                "999",
            },
          },
        );
        fireEvent.keyDown(
          input,
          {
            key: "Enter",
          },
        );

        await waitFor(() =>
          expect(
            onAssign,
          ).toHaveBeenCalledWith(
            "999",
          ),
        );
        expect(
          onReplace,
        ).not.toHaveBeenCalled();
      },
    );

    it(
      "changes an independent package barcode with keyboard-only editing",
      async () => {
        const onReplace =
          vi
            .fn()
            .mockResolvedValue(
              true,
            );

        render(
          <ProductBarcodeSimplePanel
            product={product({
              package_barcode:
                "456",
              package_uses_base_barcode:
                false,
            })}
            items={[
              barcode(),
              barcode({
                id: 11,
                uom: {
                  id: 2,
                  code: "CARTON",
                  name: "Carton",
                },
                barcode: "456",
              }),
            ]}
            canMutate
            busy={false}
            onReplace={
              onReplace
            }
            onAssignIndependentPackage={
              vi.fn()
            }
          />,
        );

        const changeButtons =
          screen.getAllByRole(
            "button",
            {
              name:
                "products.barcodeManager.change",
            },
          );
        fireEvent.click(
          changeButtons[1],
        );

        let input =
          screen.getByRole(
            "textbox",
          );
        expect(
          input,
        ).toHaveValue("456");

        fireEvent.keyDown(
          input,
          {
            key: "Escape",
          },
        );
        expect(
          screen.queryByRole(
            "textbox",
          ),
        ).toBeNull();

        fireEvent.click(
          screen.getAllByRole(
            "button",
            {
              name:
                "products.barcodeManager.change",
            },
          )[1],
        );
        input =
          screen.getByRole(
            "textbox",
          );
        fireEvent.change(
          input,
          {
            target: {
              value:
                "789",
            },
          },
        );
        fireEvent.keyDown(
          input,
          {
            key: "Enter",
          },
        );

        await waitFor(() =>
          expect(
            onReplace,
          ).toHaveBeenCalledWith(
            "package",
            "789",
          ),
        );
      },
    );

    it(
      "keeps remove/reuse actions inside history and explains removal before applying it",
      async () => {
        const current =
          barcode();
        const previous =
          barcode({
            id: 9,
            barcode: "111",
            is_primary: false,
            is_active: false,
            valid_to:
              "2026-09-30T10:00:00",
          });
        const onReuse =
          vi
            .fn()
            .mockResolvedValue(
              true,
            );
        const onRemove =
          vi
            .fn()
            .mockResolvedValue(
              true,
            );

        render(
          <ProductBarcodeHistoryPanel
            product={product()}
            items={[
              current,
              previous,
            ]}
            canMutate
            busy={false}
            hasMore={false}
            loadingMore={
              false
            }
            onClose={vi.fn()}
            onLoadMore={
              vi.fn()
            }
            onReuse={
              onReuse
            }
            onRemove={
              onRemove
            }
          />,
        );

        expect(
          screen.getByText(
            "111",
          ),
        ).toBeInTheDocument();

        fireEvent.click(
          screen.getByRole(
            "button",
            {
              name:
                "products.barcodeManager.useAgain",
            },
          ),
        );
        await waitFor(() =>
          expect(
            onReuse,
          ).toHaveBeenCalledWith(
            "base",
            "111",
          ),
        );

        fireEvent.click(
          screen.getByRole(
            "button",
            {
              name:
                "products.barcodeManager.removeFromProduct",
            },
          ),
        );
        expect(
          screen.getByText(
            "products.barcodeManager.removeConfirm",
          ),
        ).toBeInTheDocument();

        fireEvent.click(
          screen.getByRole(
            "button",
            {
              name:
                "products.barcodeManager.confirmRemove",
            },
          ),
        );
        await waitFor(() =>
          expect(
            onRemove,
          ).toHaveBeenCalledWith(
            current,
          ),
        );
      },
    );
  },
);
