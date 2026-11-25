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
import { MemoryRouter } from "react-router-dom";

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
import { emptyProductStatusEvidence, packagedProductDefaults } from "./fixtures/productRows";

const product: SimpleProduct = {
  ...packagedProductDefaults,
  ...emptyProductStatusEvidence,
  id: 10,
  product_id: 4,
  name: "Precision Product",
  family_name:
    "Precision Family",
  sku: "SKU-PRECISION",
  package_price:
    "1000000000000.123456",
  unit_price:
    "20000000000.002469",
};

describe(
  "Products table exact presentation",
  () => {
    it("renders exact high-precision prices with Latin digits in Arabic UI", () => {
      render(
        <MemoryRouter>
          <table>
          <tbody>
            <ProductTableRow
              item={product}
              rowNumber={1}
              pricingVisible
              canEditPrice
              canEditTracking
              canReassignFamily={false}
              onOpenDetails={
                vi.fn()
              }
              onEditPrice={
                vi.fn()
              }
              onEditTracking={
                vi.fn()
              }
              onReassignFamily={vi.fn()}
            />
          </tbody>
          </table>
        </MemoryRouter>,
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
          "1,000,000,000,000.123456 د.أ.",
        ),
      ).toBeInTheDocument();
      expect(
        cells.getByText(
          "20,000,000,000.002469 د.أ.",
        ),
      ).toBeInTheDocument();
      expect(
        cells.getByText("50"),
      ).toBeInTheDocument();
      expect(
        cells.getByText(
          "Precision Family",
        ),
      ).toBeInTheDocument();
      expect(
        cells.queryByText(
          /SKU-PRECISION/,
        ),
      ).not.toBeInTheDocument();
      expect(
        cells.getByText("1"),
      ).toBeInTheDocument();
    });
  },
);