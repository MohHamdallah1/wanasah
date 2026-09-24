import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    can: () => true,
  }),
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

vi.mock("@/components/ui/modal", () => ({
  Modal: ({
    isOpen,
    title,
    onClose,
    children,
  }: {
    isOpen: boolean;
    title: string;
    onClose: () => void;
    children: React.ReactNode;
  }) =>
    isOpen ? (
      <div>
        <h1>{title}</h1>
        <button
          type="button"
          aria-label={`close-${title}`}
          onClick={onClose}
        >
          close
        </button>
        {children}
      </div>
    ) : null,
}));

vi.mock(
  "@/pages/inventory/catalog/CatalogLifecyclePanel",
  () => ({
    CatalogLifecyclePanel: () => (
      <div data-testid="lifecycle-panel" />
    ),
  }),
);

import { TabProductCatalog } from "../pages/inventory/TabProductCatalog";

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>(
    (res, rej) => {
      resolve = res;
      reject = rej;
    },
  );
  return {
    promise,
    resolve,
    reject,
  };
};

const uom = (
  id: number,
  code: string,
) => ({
  id,
  code,
  name: code,
});

const variant = (
  id: number,
  name: string,
) => ({
  id,
  product_id: 100 + id,
  sku: `SKU-${id}`,
  gtin: null,
  name,
  base_uom: uom(1, "EACH"),
  quantity_scale: 0,
  quantity_step: "1",
  lot_control_mode: "NONE",
  expiry_control_mode: "NONE",
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  lifecycle_revision: 1,
  version: 1,
  published_at:
    "2026-01-01T00:00:00",
  retired_at: null,
  archived_at: null,
});

const conversion = (
  id: number,
  variantId: number,
  numerator: string,
) => ({
  id,
  product_variant_id: variantId,
  from_uom: uom(1, "EACH"),
  to_uom: uom(2, "CARTON"),
  numerator,
  denominator: "1",
  quantity_scale: 0,
  version: 1,
});

const barcode = (
  id: number,
  variantId: number,
  value: string,
) => ({
  id,
  product_variant_id: variantId,
  uom: uom(1, "EACH"),
  barcode: value,
  barcode_type: "INTERNAL",
  is_primary: true,
  valid_from:
    "2026-01-01T00:00:00",
  valid_to: null,
  is_active: true,
  version: 1,
});

describe(
  "TabProductCatalog P5 identity race",
  () => {
    beforeEach(() => {
      mocks.authFetch.mockReset();
      mocks.toastError.mockReset();
      mocks.toastSuccess.mockReset();
    });

    it("aborts A and rejects its stale identity writes after B becomes current", async () => {
      const aConversions =
        deferred<{
          items: ReturnType<
            typeof conversion
          >[];
        }>();
      const aBarcodes =
        deferred<{
          items: ReturnType<
            typeof barcode
          >[];
        }>();

      mocks.authFetch.mockImplementation(
        (
          url: string,
          options?: RequestInit,
        ) => {
          if (
            url.startsWith(
              "/catalog/variants?",
            )
          ) {
            return Promise.resolve({
              items: [
                variant(
                  10,
                  "Variant A",
                ),
                variant(
                  20,
                  "Variant B",
                ),
              ],
              next_cursor: null,
              has_more: false,
            });
          }

          if (
            url ===
            "/catalog/products?limit=200"
          ) {
            return Promise.resolve({
              items: [],
              next_cursor: null,
              has_more: false,
            });
          }

          if (
            url === "/catalog/uoms"
          ) {
            return Promise.resolve({
              items: [
                uom(1, "EACH"),
                uom(2, "CARTON"),
              ],
            });
          }

          if (
            url ===
            "/catalog/variants/10/conversions"
          ) {
            expect(
              options?.signal,
            ).toBeInstanceOf(
              AbortSignal,
            );
            return aConversions.promise;
          }

          if (
            url ===
            "/catalog/variants/10/barcodes"
          ) {
            expect(
              options?.signal,
            ).toBeInstanceOf(
              AbortSignal,
            );
            return aBarcodes.promise;
          }

          if (
            url ===
            "/catalog/variants/20/conversions"
          ) {
            return Promise.resolve({
              items: [
                conversion(
                  220,
                  20,
                  "7",
                ),
              ],
            });
          }

          if (
            url ===
            "/catalog/variants/20/barcodes"
          ) {
            return Promise.resolve({
              items: [
                barcode(
                  220,
                  20,
                  "B-CODE",
                ),
              ],
            });
          }

          throw new Error(
            `Unexpected URL: ${url}`,
          );
        },
      );

      render(
        <TabProductCatalog
          locations={[]}
          onCatalogChanged={vi.fn()}
        />,
      );

      const manageButtons =
        await screen.findAllByRole(
          "button",
          {
            name: "إدارة الصنف",
          },
        );

      fireEvent.click(
        manageButtons[0],
      );

      await waitFor(() => {
        expect(
          mocks.authFetch.mock.calls.some(
            ([url]) =>
              url ===
              "/catalog/variants/10/barcodes",
          ),
        ).toBe(true);
      });

      const aConversionCall =
        mocks.authFetch.mock.calls.find(
          ([url]) =>
            url ===
            "/catalog/variants/10/conversions",
        );
      const aSignal =
        aConversionCall?.[1]
          ?.signal as
          | AbortSignal
          | undefined;
      expect(aSignal).toBeDefined();
      expect(
        aSignal?.aborted,
      ).toBe(false);

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name:
              "close-إدارة الصنف — Variant A",
          },
        ),
      );

      await waitFor(() => {
        expect(
          aSignal?.aborted,
        ).toBe(true);
      });

      fireEvent.click(
        (
          await screen.findAllByRole(
            "button",
            {
              name:
                "إدارة الصنف",
            },
          )
        )[1],
      );

      expect(
        await screen.findByText(
          "B-CODE",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          "EACH × 7/1 → CARTON",
        ),
      ).toBeInTheDocument();

      await act(async () => {
        aConversions.resolve({
          items: [
            conversion(
              110,
              10,
              "3",
            ),
          ],
        });
        aBarcodes.resolve({
          items: [
            barcode(
              110,
              10,
              "A-CODE",
            ),
          ],
        });
        await Promise.all([
          aConversions.promise,
          aBarcodes.promise,
        ]);
      });

      await waitFor(() => {
        expect(
          screen.queryByText(
            "A-CODE",
          ),
        ).not.toBeInTheDocument();
        expect(
          screen.queryByText(
            "EACH × 3/1 → CARTON",
          ),
        ).not.toBeInTheDocument();
      });

      expect(
        screen.getByText(
          "B-CODE",
        ),
      ).toBeInTheDocument();
      expect(
        mocks.toastError,
      ).not.toHaveBeenCalled();
    });
  },
);
