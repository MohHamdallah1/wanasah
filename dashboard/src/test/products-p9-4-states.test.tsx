import {
  fireEvent,
  render,
  screen,
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
      t: (key: string) => key,
      i18n: {
        language: "ar",
        resolvedLanguage:
          "ar-JO",
        dir: () => "rtl",
      },
    }),
  }),
);

import {
  DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
} from "../lib/productDisplayPreferences";
import type {
  SimpleProduct,
} from "../pages/products/contracts";
import { ProductsListResults } from "../pages/products/list/ProductsListResults";

const product: SimpleProduct = {
  id: 10,
  product_id: 4,
  name: "Visible Product",
  family_name: "Family",
  sku: "SKU-10",
  units_per_package: 12,
  legacy_packs_per_carton: 12,
  base_uom_id: 1,
  package_uom_id: 2,
  package_uom_code: "CARTON",
  currency_code: "JOD",
  package_price: "12.000000",
  unit_price: "1.000000",
  unit_barcode: null,
  package_barcode: null,
  package_uses_base_barcode: false,
  version: 1,
  lot_control_mode: "NONE",
  expiry_control_mode: "NONE",
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  simple_compatible: true,
};

const httpError = (
  status: number,
  code: string,
) =>
  Object.assign(
    new Error(code),
    {
      status,
      code,
      data: null,
    },
  );

const baseProps = {
  items: [] as SimpleProduct[],
  isLoading: false,
  isError: false,
  isFetching: false,
  error: null as unknown,
  online: true,
  hasResultCriteria: false,
  isNarrowViewport: false,
  pricingVisible: true,
  canEditPrice: false,
  canEditTracking: false,
  columns:
    DEFAULT_PRODUCT_DISPLAY_PREFERENCES.columns,
  density:
    DEFAULT_PRODUCT_DISPLAY_PREFERENCES.density,
  tableHeaderSpacing: "px-4 py-2",
  tableColumnCount: 10,
  hasPrevious: false,
  hasNext: false,
  onRetry: vi.fn(),
  onClearCriteria: vi.fn(),
  onOpenDetails: vi.fn(),
  onEditPrice: vi.fn(),
  onEditTracking: vi.fn(),
  onPrevious: vi.fn(),
  onNext: vi.fn(),
};

describe(
  "Products P9.4 workspace states",
  () => {
    it("shows one shared loading state before Product rows exist", () => {
      render(
        <ProductsListResults
          {...baseProps}
          isLoading
        />,
      );

      expect(
        screen.getByText(
          "products.states.loadingTitle",
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("table"),
      ).not.toBeInTheDocument();
    });

    it("distinguishes a filtered empty result and clears only through the explicit callback", () => {
      const onClearCriteria =
        vi.fn();

      render(
        <ProductsListResults
          {...baseProps}
          hasResultCriteria
          onClearCriteria={
            onClearCriteria
          }
        />,
      );

      expect(
        screen.getByText(
          "products.states.filteredEmptyTitle",
        ),
      ).toBeInTheDocument();

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name: "products.states.clearCriteria",
          },
        ),
      );
      expect(
        onClearCriteria,
      ).toHaveBeenCalledTimes(1);
    });

    it("shows a retryable blocking failure when no successful rows exist", () => {
      const onRetry = vi.fn();

      render(
        <ProductsListResults
          {...baseProps}
          isError
          error={httpError(
            503,
            "INTERNAL_SERVER_ERROR",
          )}
          onRetry={onRetry}
        />,
      );

      expect(
        screen.getByRole("alert"),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          "products.errors.listLoadTitle",
        ),
      ).toBeInTheDocument();

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name: "common.retry",
          },
        ),
      );
      expect(
        onRetry,
      ).toHaveBeenCalledTimes(1);
    });

    it("keeps the last successful Product rows visible when refresh fails", () => {
      render(
        <ProductsListResults
          {...baseProps}
          items={[product]}
          isError
          error={httpError(
            503,
            "INTERNAL_SERVER_ERROR",
          )}
        />,
      );

      expect(
        screen.getByText(
          "Visible Product",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("status"),
      ).toBeInTheDocument();
    });

    it("keeps cached rows visible offline but blocks new pagination", () => {
      render(
        <ProductsListResults
          {...baseProps}
          items={[product]}
          online={false}
          hasNext
        />,
      );

      expect(
        screen.getByText(
          "Visible Product",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          "products.states.offlineCachedDescription",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole(
          "button",
          {
            name: "products.familyNext",
          },
        ),
      ).toBeDisabled();
    });

    it("fails closed on a permission denial instead of showing stale Product rows", () => {
      render(
        <ProductsListResults
          {...baseProps}
          items={[product]}
          isError
          error={httpError(
            403,
            "PERMISSION_DENIED",
          )}
        />,
      );

      expect(
        screen.getByText(
          "products.states.permissionTitle",
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(
          "Visible Product",
        ),
      ).not.toBeInTheDocument();
    });

    it("uses the same blocking state component for desktop and mobile presentation", () => {
      const { rerender } = render(
        <ProductsListResults
          {...baseProps}
          isLoading
        />,
      );

      expect(
        screen.getAllByText(
          "products.states.loadingTitle",
        ),
      ).toHaveLength(1);

      rerender(
        <ProductsListResults
          {...baseProps}
          isLoading
          isNarrowViewport
        />,
      );

      expect(
        screen.getAllByText(
          "products.states.loadingTitle",
        ),
      ).toHaveLength(1);
    });
  },
);
