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
  translate: (
    key: string,
    options?: {
      defaultValue?: string;
      name?: string;
    },
  ) =>
    options?.defaultValue ??
    key,
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

vi.mock("@/hooks/useNetworkStatus", () => ({
  useNetworkStatus: () => true,
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

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
        t: mocks.translate,
        i18n: {
          language: "en",
          resolvedLanguage: "en",
          dir: () => "ltr",
        },
      }),
    };
  },
);

vi.mock("@/components/ui/modal", () => ({
  Modal: ({
    isOpen,
    title,
    children,
  }: {
    isOpen: boolean;
    title: string;
    children: React.ReactNode;
  }) =>
    isOpen ? (
      <div>
        <h1>{title}</h1>
        {children}
      </div>
    ) : null,
}));

import { ProductBarcodeManager } from "../pages/products/ProductBarcodeManager";
import type {
  ProductBarcodeRecord,
  SimpleProduct,
} from "../pages/products/contracts";

const product = (
  id: number,
  name: string,
): SimpleProduct => ({
  id,
  product_id: id + 100,
  name,
  family_name: name + " family",
  sku: "SKU-" + id,
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
  version: 1,
  lot_control_mode: "OPTIONAL",
  expiry_control_mode: "NONE",
  lifecycle_status: "ACTIVE",
  simple_compatible: true,
});

const barcode = (
  id: number,
  productId: number,
  value: string,
): ProductBarcodeRecord => ({
  id,
  product_variant_id: productId,
  uom: {
    id: 1,
    code: "EACH",
    name: "Each",
  },
  barcode: value,
  barcode_type: "INTERNAL",
  is_primary: true,
  valid_from:
    "2026-01-01T00:00:00",
  valid_to: null,
  is_active: true,
  version: 1,
});

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

describe("ProductBarcodeManager runtime behavior", () => {
  beforeEach(() => {
    mocks.authFetch.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
    localStorage.clear();
  });

  it("ignores an older product response after the selected product changes", async () => {
    const first =
      deferred<{
        items: ProductBarcodeRecord[];
        next_cursor: string | null;
        has_more: boolean;
      }>();
    const second =
      deferred<{
        items: ProductBarcodeRecord[];
        next_cursor: string | null;
        has_more: boolean;
      }>();

    mocks.authFetch
      .mockImplementationOnce(
        () => first.promise,
      )
      .mockImplementationOnce(
        () => second.promise,
      );

    const onChanged = vi.fn();
    const { rerender } = render(
      <ProductBarcodeManager
        product={product(10, "A")}
        companyId={1}
        driverId={2}
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );

    expect(
      mocks.authFetch,
    ).toHaveBeenCalledTimes(1);

    rerender(
      <ProductBarcodeManager
        product={product(20, "B")}
        companyId={1}
        driverId={2}
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );

    expect(
      mocks.authFetch,
    ).toHaveBeenCalledTimes(2);

    await act(async () => {
      second.resolve({
        items: [
          barcode(
            200,
            20,
            "B-CODE",
          ),
        ],
        next_cursor: null,
        has_more: false,
      });
      await second.promise;
    });

    expect(
      await screen.findByText(
        "B-CODE",
      ),
    ).toBeInTheDocument();

    await act(async () => {
      first.resolve({
        items: [
          barcode(
            100,
            10,
            "A-CODE",
          ),
        ],
        next_cursor: null,
        has_more: false,
      });
      await first.promise;
    });

    await waitFor(() => {
      expect(
        screen.queryByText(
          "A-CODE",
        ),
      ).not.toBeInTheDocument();
    });
    expect(
      screen.getByText(
        "B-CODE",
      ),
    ).toBeInTheDocument();
  });

  it("does not present failed barcode loading as a confirmed empty state", async () => {
    mocks.authFetch.mockRejectedValueOnce(
      new Error("network"),
    );

    render(
      <ProductBarcodeManager
        product={product(10, "A")}
        companyId={1}
        driverId={2}
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(
      await screen.findByText(
        "products.barcodeManager.loadFailed",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "products.barcodeManager.none",
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "products.barcodeManager.add",
      ),
    ).not.toBeInTheDocument();
  });

  it("reuses the exact barcode request identity and payload after a lost response", async () => {
    const created = barcode(
      300,
      10,
      "ABC123",
    );

    mocks.authFetch
      .mockResolvedValueOnce({
        items: [],
        next_cursor: null,
        has_more: false,
      })
      .mockRejectedValueOnce(
        Object.assign(
          new Error("timeout"),
          {
            status: 408,
            code: "REQUEST_TIMEOUT",
          },
        ),
      )
      .mockResolvedValueOnce({
        message: "ignored backend copy",
        barcode: created,
      })
      .mockResolvedValueOnce({
        items: [created],
        next_cursor: null,
        has_more: false,
      });

    render(
      <ProductBarcodeManager
        product={product(10, "A")}
        companyId={1}
        driverId={2}
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    const input =
      await screen.findByLabelText(
        "products.barcodeManager.value",
      );
    fireEvent.change(input, {
      target: {
        value: "ABC123",
      },
    });

    const save = screen.getByRole(
      "button",
      {
        name: "products.barcodeManager.save",
      },
    );
    fireEvent.click(save);

    await waitFor(() => {
      expect(
        mocks.authFetch,
      ).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(save).not.toBeDisabled();
    });

    fireEvent.click(save);

    const mutationCalls = () =>
      mocks.authFetch.mock.calls.filter(
        ([url, options]) =>
          url ===
            "/catalog/variants/10/barcodes" &&
          options?.method === "POST",
      );

    await waitFor(() => {
      expect(
        mutationCalls(),
      ).toHaveLength(2);
    });

    const firstMutation =
      JSON.parse(
        String(
          mutationCalls()[0][1]?.body,
        ),
      );
    const retryMutation =
      JSON.parse(
        String(
          mutationCalls()[1][1]?.body,
        ),
      );

    expect(
      retryMutation,
    ).toEqual(firstMutation);
    expect(
      retryMutation.request_id,
    ).toBe(
      firstMutation.request_id,
    );
    expect(
      retryMutation.valid_from,
    ).toBeNull();
    expect(
      retryMutation.valid_to,
    ).toBeNull();
  });

  it("locks changed input after an ambiguous create and restores the exact pending command after remount", async () => {
    mocks.authFetch
      .mockResolvedValueOnce({
        items: [],
        next_cursor: null,
        has_more: false,
      })
      .mockRejectedValueOnce(
        Object.assign(
          new Error("timeout"),
          {
            status: 408,
            code: "REQUEST_TIMEOUT",
          },
        ),
      );

    const props = {
      product: product(10, "A"),
      companyId: 1,
      driverId: 2,
      onClose: vi.fn(),
      onChanged: vi.fn(),
    };

    const firstRender = render(
      <ProductBarcodeManager
        {...props}
      />,
    );
    const input =
      await screen.findByLabelText(
        "products.barcodeManager.value",
      );
    fireEvent.change(input, {
      target: {
        value: "LOCKED-CODE",
      },
    });
    fireEvent.click(
      screen.getByRole(
        "button",
        {
          name: "products.barcodeManager.save",
        },
      ),
    );

    expect(
      await screen.findByText(
        "products.barcodeManager.pendingRetry",
      ),
    ).toBeInTheDocument();
    expect(input).toBeDisabled();
    expect(input).toHaveValue(
      "LOCKED-CODE",
    );

    firstRender.unmount();

    mocks.authFetch
      .mockReset()
      .mockResolvedValueOnce({
        items: [],
        next_cursor: null,
        has_more: false,
      });

    render(
      <ProductBarcodeManager
        {...props}
      />,
    );

    const restored =
      await screen.findByLabelText(
        "products.barcodeManager.value",
      );
    expect(restored).toBeDisabled();
    expect(restored).toHaveValue(
      "LOCKED-CODE",
    );
    expect(
      screen.getByRole(
        "button",
        {
          name: "products.barcodeManager.retryPending",
        },
      ),
    ).toBeEnabled();
  });

  it("loads barcode history by bounded pages", async () => {
    const firstPage = barcode(
      1,
      10,
      "FIRST",
    );
    const secondPage = barcode(
      2,
      10,
      "SECOND",
    );
    mocks.authFetch
      .mockResolvedValueOnce({
        items: [firstPage],
        next_cursor: "Mg",
        has_more: true,
      })
      .mockResolvedValueOnce({
        items: [secondPage],
        next_cursor: null,
        has_more: false,
      });

    render(
      <ProductBarcodeManager
        product={product(10, "A")}
        companyId={1}
        driverId={2}
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(
      await screen.findByText(
        "FIRST",
      ),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole(
        "button",
        {
          name: "products.barcodeManager.loadMore",
        },
      ),
    );

    expect(
      await screen.findByText(
        "SECOND",
      ),
    ).toBeInTheDocument();
    expect(
      mocks.authFetch.mock.calls[1][0],
    ).toContain(
      "cursor=Mg",
    );
  });
});
