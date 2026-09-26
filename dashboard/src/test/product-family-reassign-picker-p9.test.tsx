import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import type {
  SimpleProduct,
} from "@/pages/products/contracts";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
}));

vi.mock(
  "@/hooks/useAuthFetch",
  () => ({
    useAuthFetch: () =>
      mocks.authFetch,
  }),
);

vi.mock(
  "@/hooks/useNetworkStatus",
  () => ({
    useNetworkStatus: () => true,
  }),
);

vi.mock(
  "react-i18next",
  async (importOriginal) => {
    const actual =
      await importOriginal<
        typeof import("react-i18next")
      >();

    return {
      ...actual,
      useTranslation: () => ({
        t: (
          key: string,
          values?: Record<
            string,
            unknown
          >,
        ) =>
          values?.id
            ? `${key} ${values.id}`
            : key,
        i18n: {
          language: "ar",
          resolvedLanguage: "ar",
          dir: () => "rtl",
        },
      }),
    };
  },
);

vi.mock(
  "sonner",
  () => ({
    toast: {
      error: vi.fn(),
      success: vi.fn(),
    },
  }),
);

vi.mock(
  "@/components/ui/modal",
  () => ({
    Modal: ({
      isOpen,
      children,
    }: {
      isOpen: boolean;
      children: React.ReactNode;
    }) =>
      isOpen ? (
        <div>{children}</div>
      ) : null,
  }),
);

vi.mock(
  "@/lib/durableOperations",
  async (importOriginal) => {
    const actual =
      await importOriginal<
        typeof import("@/lib/durableOperations")
      >();

    return {
      ...actual,
      readDurableCommand:
        vi.fn().mockResolvedValue(
          null,
        ),
    };
  },
);

import { ProductFamilyReassignDialog } from "@/pages/products/family/ProductFamilyReassignDialog";

const product: SimpleProduct = {
  id: 10,
  product_id: 1,
  name: "Cola 330ml",
  family_name: "Cola",
  sku: "SKU-10",
  units_per_package: 1,
  legacy_packs_per_carton: 1,
  base_uom_id: 1,
  package_uom_id: null,
  package_uom_code: null,
  currency_code: "JOD",
  package_price: null,
  unit_price: null,
  unit_barcode: null,
  package_barcode: null,
  package_uses_base_barcode: false,
  version: 3,
  lot_control_mode: "NONE",
  expiry_control_mode: "NONE",
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  simple_compatible: true,
};

describe(
  "Product family reassign picker",
  () => {
    let queryClient: QueryClient;
    const originalResizeObserver =
      globalThis.ResizeObserver;

    beforeAll(() => {
      class ResizeObserverMock {
        observe() {}
        unobserve() {}
        disconnect() {}
      }

      globalThis.ResizeObserver =
        ResizeObserverMock as typeof ResizeObserver;
    });

    afterAll(() => {
      globalThis.ResizeObserver =
        originalResizeObserver;
    });

    beforeEach(() => {
      mocks.authFetch.mockReset();
      queryClient =
        new QueryClient({
          defaultOptions: {
            queries: {
              retry: false,
            },
          },
        });
    });

    afterEach(() => {
      cleanup();
      queryClient.clear();
    });

    it("searches the family endpoint and renders matching options in the same picker", async () => {
      mocks.authFetch.mockImplementation(
        async (url: string) => {
          if (
            url.includes(
              "search=Snacks",
            )
          ) {
            return {
              items: [
                {
                  id: 3,
                  name: "Snacks",
                  version: 1,
                  variant_count: 4,
                },
              ],
              next_cursor: null,
              has_more: false,
            };
          }

          return {
            items: [
              {
                id: 1,
                name: "Cola",
                version: 1,
                variant_count: 2,
              },
              {
                id: 2,
                name: "Water",
                version: 1,
                variant_count: 3,
              },
            ],
            next_cursor: null,
            has_more: false,
          };
        },
      );

      render(
        <QueryClientProvider
          client={queryClient}
        >
          <ProductFamilyReassignDialog
            product={product}
            companyId={1}
            driverId={2}
            onClose={vi.fn()}
            onReassigned={vi.fn()}
          />
        </QueryClientProvider>,
      );

      const search =
        await screen.findByPlaceholderText(
          "products.familyReassign.searchPlaceholder",
        );

      fireEvent.change(search, {
        target: {
          value: "Snacks",
        },
      });

      await waitFor(() => {
        expect(
          mocks.authFetch,
        ).toHaveBeenCalledWith(
          expect.stringContaining(
            "search=Snacks",
          ),
          expect.any(Object),
        );
      });

      const option =
        await screen.findByRole(
          "option",
          {
            name: /Snacks/,
          },
        );
      expect(
        option,
      ).toBeInTheDocument();

      fireEvent.click(option);

      await waitFor(() => {
        expect(
          screen.getByRole(
            "option",
            {
              name: /Snacks/,
            },
          ),
        ).toHaveAttribute(
          "aria-selected",
          "true",
        );
      });
    });
  },
);
