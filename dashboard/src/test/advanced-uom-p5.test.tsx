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
  MemoryRouter,
} from "react-router-dom";
import {
  afterEach,
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
  canManage: true,
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

vi.mock("@/hooks/useNetworkStatus", () => ({
  useNetworkStatus: () => true,
}));

vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    isSuccess: true,
    isCompanyAdmin: false,
    data: {
      company_id: 1,
      driver_id: 2,
    },
    canAny: (permission: string) =>
      permission === "catalog.read" ||
      (
        permission === "catalog.manage" &&
        mocks.canManage
      ),
  }),
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
        t: (key: string) => key,
      }),
    };
  },
);

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

import {
  durableScope,
  getOrCreateDurableCommand,
} from "../lib/durableOperations";
import {
  parseConversionMutation,
} from "../pages/inventory/catalog/contracts";
import AdvancedUomDashboard from "../pages/products/AdvancedUomDashboard";

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
  lifecycle:
    | "DRAFT"
    | "ACTIVE"
    | "RETIRING"
    | "ARCHIVED",
) => ({
  id,
  product_id: 100 + id,
  sku: `SKU-${id}`,
  gtin: null,
  name: `Variant ${id}`,
  base_uom: uom(1, "EACH"),
  quantity_scale: 0,
  quantity_step: "1",
  lot_control_mode: "NONE",
  expiry_control_mode: "NONE",
  lifecycle_status: lifecycle,
  operational_hold: "NONE",
  lifecycle_revision: 1,
  version: 1,
  published_at:
    lifecycle === "DRAFT"
      ? null
      : "2026-01-01T00:00:00",
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

const renderPage = (
  initialEntry: string,
) => {
  const client =
    new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
        mutations: {
          retry: false,
        },
      },
    });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={[initialEntry]}
        future={{
          v7_startTransition: true,
          v7_relativeSplatPath: true,
        }}
      >
        <AdvancedUomDashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return {
    ...view,
    client,
  };
};

describe(
  "Advanced UOM P5 runtime",
  () => {
    beforeEach(() => {
      mocks.authFetch.mockReset();
      mocks.toastError.mockReset();
      mocks.toastSuccess.mockReset();
      mocks.canManage = true;
      localStorage.clear();
    });

    afterEach(() => {
      cleanup();
      localStorage.clear();
      vi.restoreAllMocks();
    });

    it("deep-links to a published SKU as read-only and loads authoritative conversions", async () => {
      mocks.authFetch.mockImplementation(
        async (
          url: string,
          options?: RequestInit,
        ) => {
          if (
            url.startsWith(
              "/catalog/variants?",
            )
          ) {
            return {
              items: [],
              next_cursor: null,
              has_more: false,
            };
          }
          if (
            url ===
            "/catalog/variants/resolve"
          ) {
            expect(
              options?.method,
            ).toBe("POST");
            expect(
              JSON.parse(
                String(options?.body),
              ),
            ).toEqual({
              ids: [20],
            });
            return {
              items: [
                variant(20, "ACTIVE"),
              ],
              next_cursor: null,
              has_more: false,
            };
          }
          if (
            url === "/catalog/uoms"
          ) {
            return {
              items: [
                uom(1, "EACH"),
                uom(2, "CARTON"),
              ],
            };
          }
          if (
            url ===
            "/catalog/variants/20/conversions"
          ) {
            return {
              items: [
                conversion(
                  200,
                  20,
                  "7",
                ),
              ],
            };
          }
          throw new Error(
            `Unexpected URL: ${url}`,
          );
        },
      );

      renderPage(
        "/products/advanced-uom?variant=20",
      );

      expect(
        await screen.findByText(
          "EACH × 7/1 → CARTON",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          "products.advancedUom.lockedAfterPublish",
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole(
          "button",
          {
            name:
              "products.advancedUom.addConversion",
          },
        ),
      ).not.toBeInTheDocument();
    });

    it("locks an ambiguous create and retries the exact same durable command", async () => {
      let conversionLoads = 0;
      const mutationBodies:
        Array<Record<string, unknown>> =
        [];
      let mutationAttempt = 0;

      mocks.authFetch.mockImplementation(
        async (
          url: string,
          options?: RequestInit,
        ) => {
          if (
            url.startsWith(
              "/catalog/variants?",
            )
          ) {
            return {
              items: [],
              next_cursor: null,
              has_more: false,
            };
          }
          if (
            url ===
            "/catalog/variants/resolve"
          ) {
            return {
              items: [
                variant(10, "DRAFT"),
              ],
              next_cursor: null,
              has_more: false,
            };
          }
          if (
            url === "/catalog/uoms"
          ) {
            return {
              items: [
                uom(1, "EACH"),
                uom(2, "CARTON"),
              ],
            };
          }
          if (
            url ===
            "/catalog/variants/10/conversions" &&
            options?.method === "POST"
          ) {
            mutationAttempt += 1;
            mutationBodies.push(
              JSON.parse(
                String(options.body),
              ),
            );
            if (
              mutationAttempt === 1
            ) {
              throw Object.assign(
                new Error("timeout"),
                {
                  status: 408,
                  code:
                    "REQUEST_TIMEOUT",
                },
              );
            }
            return {
              message: "saved",
              conversion: conversion(
                100,
                10,
                "3",
              ),
            };
          }
          if (
            url ===
            "/catalog/variants/10/conversions"
          ) {
            conversionLoads += 1;
            return {
              items:
                conversionLoads > 1
                  ? [
                      conversion(
                        100,
                        10,
                        "3",
                      ),
                    ]
                  : [],
            };
          }
          throw new Error(
            `Unexpected URL: ${url}`,
          );
        },
      );

      renderPage(
        "/products/advanced-uom?variant=10",
      );

      const from =
        await screen.findByLabelText(
          "products.advancedUom.from",
        );
      const to =
        screen.getByLabelText(
          "products.advancedUom.to",
        );
      const numerator =
        screen.getByLabelText(
          "products.advancedUom.numerator",
        );

      fireEvent.change(from, {
        target: {
          value: "1",
        },
      });
      fireEvent.change(to, {
        target: {
          value: "2",
        },
      });
      fireEvent.change(
        numerator,
        {
          target: {
            value: "3",
          },
        },
      );

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name:
              "products.advancedUom.addConversion",
          },
        ),
      );

      await waitFor(() => {
        expect(
          mutationBodies,
        ).toHaveLength(1);
      });
      expect(
        await screen.findByText(
          "products.advancedUom.pendingRetry",
        ),
      ).toBeInTheDocument();
      expect(from).toBeDisabled();
      expect(to).toBeDisabled();
      expect(numerator).toBeDisabled();

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name: "common.retry",
          },
        ),
      );

      await waitFor(() => {
        expect(
          mutationBodies,
        ).toHaveLength(2);
      });

      expect(
        mutationBodies[1],
      ).toEqual(
        mutationBodies[0],
      );
      expect(
        mutationBodies[0]
          .request_id,
      ).toEqual(
        expect.any(String),
      );

      await waitFor(() => {
        expect(
          mocks.toastSuccess,
        ).toHaveBeenCalledWith(
          "products.advancedUom.saved",
        );
      });

      expect(
        localStorage.getItem(
          "wanasah:durable:v1:1:2:catalog-uom-conversion-create:10",
        ),
      ).toBeNull();
    });

    it("restores a pending create after remount and retries its original request identity", async () => {
      const scope = durableScope(
        1,
        2,
        "catalog-uom-conversion-create",
        10,
      );
      const pending =
        await getOrCreateDurableCommand(
          scope,
          {
            from_uom_id: 1,
            to_uom_id: 2,
            numerator: "4",
            denominator: "1",
            quantity_scale: 0,
          },
        );
      const mutationBodies:
        Array<Record<string, unknown>> =
        [];

      mocks.authFetch.mockImplementation(
        async (
          url: string,
          options?: RequestInit,
        ) => {
          if (
            url.startsWith(
              "/catalog/variants?",
            )
          ) {
            return {
              items: [],
              next_cursor: null,
              has_more: false,
            };
          }
          if (
            url ===
            "/catalog/variants/resolve"
          ) {
            return {
              items: [
                variant(10, "DRAFT"),
              ],
              next_cursor: null,
              has_more: false,
            };
          }
          if (
            url === "/catalog/uoms"
          ) {
            return {
              items: [
                uom(1, "EACH"),
                uom(2, "CARTON"),
              ],
            };
          }
          if (
            url ===
              "/catalog/variants/10/conversions" &&
            options?.method === "POST"
          ) {
            const body =
              JSON.parse(
                String(options.body),
              ) as Record<
                string,
                unknown
              >;
            mutationBodies.push(body);
            return {
              message: "saved",
              conversion: conversion(
                101,
                10,
                "4",
              ),
            };
          }
          if (
            url ===
            "/catalog/variants/10/conversions"
          ) {
            return {
              items: [],
            };
          }
          throw new Error(
            `Unexpected URL: ${url}`,
          );
        },
      );

      renderPage(
        "/products/advanced-uom?variant=10",
      );

      expect(
        await screen.findByText(
          "products.advancedUom.pendingRetry",
        ),
      ).toBeInTheDocument();

      const numerator =
        screen.getByLabelText(
          "products.advancedUom.numerator",
        );
      expect(
        numerator,
      ).toHaveValue("4");
      expect(
        numerator,
      ).toBeDisabled();

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name: "common.retry",
          },
        ),
      );

      await waitFor(() => {
        expect(
          mutationBodies,
        ).toHaveLength(1);
      });
      expect(
        mutationBodies[0]
          .request_id,
      ).toBe(
        pending.requestId,
      );
      expect(
        mutationBodies[0]
          .numerator,
      ).toBe("4");

      await waitFor(() => {
        expect(
          localStorage.getItem(
            scope,
          ),
        ).toBeNull();
      });
    });

    it("updates a DRAFT conversion with exact values, expected version, and durable identity", async () => {
      let current = conversion(
        100,
        10,
        "3",
      );
      const patchBodies:
        Array<Record<string, unknown>> =
        [];

      mocks.authFetch.mockImplementation(
        async (
          url: string,
          options?: RequestInit,
        ) => {
          if (
            url.startsWith(
              "/catalog/variants?",
            )
          ) {
            return {
              items: [],
              next_cursor: null,
              has_more: false,
            };
          }
          if (
            url ===
            "/catalog/variants/resolve"
          ) {
            return {
              items: [
                variant(10, "DRAFT"),
              ],
              next_cursor: null,
              has_more: false,
            };
          }
          if (
            url === "/catalog/uoms"
          ) {
            return {
              items: [
                uom(1, "EACH"),
                uom(2, "CARTON"),
              ],
            };
          }
          if (
            url ===
              "/catalog/conversions/100" &&
            options?.method === "PATCH"
          ) {
            const body =
              JSON.parse(
                String(options.body),
              ) as Record<
                string,
                unknown
              >;
            patchBodies.push(body);
            current = {
              ...current,
              numerator: "5",
              version: 2,
            };
            return {
              message: "updated",
              conversion: current,
            };
          }
          if (
            url ===
            "/catalog/variants/10/conversions"
          ) {
            return {
              items: [current],
            };
          }
          throw new Error(
            `Unexpected URL: ${url}`,
          );
        },
      );

      renderPage(
        "/products/advanced-uom?variant=10",
      );

      expect(
        await screen.findByText(
          "EACH × 3/1 → CARTON",
        ),
      ).toBeInTheDocument();

      fireEvent.click(
        await screen.findByRole(
          "button",
          {
            name: "common.edit",
          },
        ),
      );

      const numerator =
        screen.getByLabelText(
          "products.advancedUom.numerator",
        );
      fireEvent.change(
        numerator,
        {
          target: {
            value: "5",
          },
        },
      );

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name: "common.save",
          },
        ),
      );

      await waitFor(() => {
        expect(
          patchBodies,
        ).toHaveLength(1);
      });

      expect(
        patchBodies[0],
      ).toMatchObject({
        from_uom_id: 1,
        to_uom_id: 2,
        numerator: "5",
        denominator: "1",
        quantity_scale: 0,
        expected_version: 1,
      });
      expect(
        patchBodies[0]
          .request_id,
      ).toEqual(
        expect.any(String),
      );

      await waitFor(() => {
        expect(
          screen.getByText(
            "EACH × 5/1 → CARTON",
          ),
        ).toBeInTheDocument();
      });

      expect(
        localStorage.getItem(
          "wanasah:durable:v1:1:2:catalog-uom-conversion-update:100",
        ),
      ).toBeNull();
    });

    it("keeps a draft read-only without catalog.manage", async () => {
      mocks.canManage = false;
      mocks.authFetch.mockImplementation(
        async (
          url: string,
        ) => {
          if (
            url.startsWith(
              "/catalog/variants?",
            )
          ) {
            return {
              items: [],
              next_cursor: null,
              has_more: false,
            };
          }
          if (
            url ===
            "/catalog/variants/resolve"
          ) {
            return {
              items: [
                variant(30, "DRAFT"),
              ],
              next_cursor: null,
              has_more: false,
            };
          }
          if (
            url === "/catalog/uoms"
          ) {
            return {
              items: [
                uom(1, "EACH"),
              ],
            };
          }
          if (
            url ===
            "/catalog/variants/30/conversions"
          ) {
            return {
              items: [],
            };
          }
          throw new Error(
            `Unexpected URL: ${url}`,
          );
        },
      );

      renderPage(
        "/products/advanced-uom?variant=30",
      );

      expect(
        await screen.findByText(
          "products.advancedUom.readOnly",
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole(
          "button",
          {
            name:
              "products.advancedUom.addConversion",
          },
        ),
      ).not.toBeInTheDocument();
    });

    it("fails closed on malformed conversion mutation responses", () => {
      expect(() =>
        parseConversionMutation({
          message: "saved",
        }),
      ).toThrow(
        "استجابة تحويل UOM غير صالحة.",
      );
    });
  },
);
