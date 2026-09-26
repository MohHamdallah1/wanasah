import {
  render,
  screen,
  within,
} from "@testing-library/react";
import {
  describe,
  expect,
  it,
  vi,
} from "vitest";

vi.mock(
  "react-i18next",
  () => ({
    useTranslation: () => ({
      t: (
        key: string,
        options?: {
          defaultValue?: string;
        },
      ) =>
        options?.defaultValue ??
        key,
      i18n: {
        language: "ar",
        resolvedLanguage:
          "ar-JO",
        dir: () => "rtl",
      },
    }),
  }),
);

import { ProductTableRow } from "../pages/products/list/ProductTableRow";
import type {
  SimpleProduct,
} from "../pages/products/contracts";

const product: SimpleProduct = {
  id: 10,
  product_id: 4,
  name: "Precision Product",
  family_name:
    "Precision Family",
  sku: "SKU-PRECISION",
  units_per_package: 50,
  legacy_packs_per_carton: 50,
  base_uom_id: 1,
  package_uom_id: 2,
  package_uom_code:
    "CARTON",
  currency_code: "JOD",
  package_price:
    "1000000000000.123456",
  unit_price:
    "20000000000.002469",
  unit_barcode: null,
  package_barcode: null,
  package_uses_base_barcode:
    false,
  version: 3,
  lot_control_mode:
    "OPTIONAL",
  expiry_control_mode:
    "NONE",
  lifecycle_status:
    "ACTIVE",
  operational_hold:
    "NONE",
  simple_compatible: true,
};

describe(
  "Products table exact presentation",
  () => {
    it("renders exact high-precision prices with Latin digits in Arabic UI", () => {
      render(
        <table>
          <tbody>
            <ProductTableRow
              item={product}
              pricingVisible
              canEditPrice
              canEditTracking
              onOpenDetails={
                vi.fn()
              }
              onEditPrice={
                vi.fn()
              }
              onEditTracking={
                vi.fn()
              }
            />
          </tbody>
        </table>,
      );

      const row =
        screen
          .getByText(
            "Precision Product",
          )
          .closest("tr");
      expect(row).not.toBeNull();

      const cells = within(
        row as HTMLTableRowElement,
      );

      expect(
        cells.getByText(
          "1,000,000,000,000.123456 JOD",
        ),
      ).toBeInTheDocument();
      expect(
        cells.getByText(
          "20,000,000,000.002469 JOD",
        ),
      ).toBeInTheDocument();
      expect(
        cells.getByText("50"),
      ).toBeInTheDocument();
      expect(
        cells.queryByText(
          "Precision Family",
        ),
      ).not.toBeInTheDocument();
    });
  },
);
