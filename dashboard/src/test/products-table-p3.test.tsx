import {
  render,
  screen,
} from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const mocks = vi.hoisted(() => ({
  refetch: vi.fn(),
  invalidateQueries: vi.fn(),
  mutation: {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    reset: vi.fn(),
    isPending: false,
  },
}));

vi.mock(
  "@tanstack/react-query",
  () => ({
    useQuery: (options: {
      queryKey: unknown[];
    }) => {
      const key =
        options.queryKey[0];
      if (
        key === "simple-products"
      ) {
        return {
          data: {
            currency_code: "JOD",
            pricing_visible: true,
            items: [
              {
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
                simple_compatible: true,
              },
            ],
            next_cursor: null,
            has_more: false,
          },
          isLoading: false,
          isError: false,
          isFetching: false,
          refetch: mocks.refetch,
        };
      }

      return {
        data: undefined,
        isLoading: false,
        isError: false,
        isFetching: false,
        refetch: mocks.refetch,
      };
    },
    useMutation: () =>
      mocks.mutation,
    useQueryClient: () => ({
      invalidateQueries:
        mocks.invalidateQueries,
    }),
  }),
);

vi.mock(
  "@/hooks/useAuthFetch",
  () => ({
    useAuthFetch: () =>
      vi.fn(),
  }),
);

vi.mock(
  "@/hooks/useNetworkStatus",
  () => ({
    useNetworkStatus: () => true,
  }),
);

vi.mock(
  "@/hooks/useInventoryAccess",
  () => ({
    useInventoryAccess: () => ({
      data: {
        company_id: 1,
        driver_id: 2,
      },
      isCompanyAdmin: true,
      canAny: () => true,
    }),
  }),
);

import i18n from "../i18n";
import {
  formatLocaleDecimal,
} from "../lib/localeNumbers";
import ProductsDashboard from "../pages/ProductsDashboard";

describe(
  "Products table exact presentation",
  () => {
    beforeEach(async () => {
      mocks.refetch.mockReset();
      mocks.invalidateQueries.mockReset();
      localStorage.clear();
      sessionStorage.clear();
      await i18n.changeLanguage(
        "ar",
      );
    });

    afterEach(async () => {
      await i18n.changeLanguage(
        "en",
      );
    });

    it("renders high-precision prices exactly and localizes package units in Arabic", () => {
      render(
        <ProductsDashboard />,
      );

      const locale =
        i18n.resolvedLanguage ??
        i18n.language;
      const packagePrice =
        formatLocaleDecimal(
          "1000000000000.123456",
          locale,
          3,
          6,
        );
      const unitPrice =
        formatLocaleDecimal(
          "20000000000.002469",
          locale,
          3,
          6,
        );
      const units =
        formatLocaleDecimal(
          "50",
          locale,
          0,
          0,
        );

      expect(
        screen.getByText(
          `${packagePrice} JOD`,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          `${unitPrice} JOD`,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(units),
      ).toBeInTheDocument();

      expect(packagePrice).toContain(
        "١٢٣٤٥٦",
      );
      expect(unitPrice).toContain(
        "٠٠٢٤٦٩",
      );
      expect(units).toBe("٥٠");
    });
  },
);
