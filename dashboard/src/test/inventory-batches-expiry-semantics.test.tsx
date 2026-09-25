
import {
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
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
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
        t: (key: string) => key,
        i18n: {
          language: "en",
          resolvedLanguage: "en",
          dir: () => "ltr",
        },
      }),
    };
  },
);

import { TabBatches } from "../pages/inventory/TabBatches";

describe("Inventory batch expiry semantics", () => {
  beforeEach(() => {
    mocks.authFetch.mockReset();
    mocks.toastError.mockReset();

    mocks.authFetch.mockImplementation(
      async (path: string) => {
        if (
          path.startsWith(
            "/warehouse/inventory/batch-products?",
          )
        ) {
          return {
            items: [
              {
                id: 211,
                name: "Expiry Product",
                sku: "SKU-211",
                family_name: "Expiry Family",
                base_uom_code: "EACH",
                display_uom_code: "EACH",
                display_factor_to_base: "1",
                currency_code: "JOD",
              },
            ],
            next_cursor: null,
            has_more: false,
          };
        }

        if (
          path.startsWith(
            "/warehouse/inventory/211/batches?",
          )
        ) {
          return {
            location_id: 119,
            product_variant_id: 211,
            currency_code: "JOD",
            batches: [
              {
                batch_id: 9001,
                batch_number: "EXP-001",
                production_date: "2026-01-01",
                expiry_date: "2026-09-24",
                disposition: "RELEASED",
                days_to_expiry: -1,
                on_hand_quantity: "10",
                reserved_quantity: "0",
                available_for_sale_quantity: "0",
                unavailable_quantity: "10",
                restricted_quantity: "10",
                expiry_unavailable_quantity: "10",
                quarantined_quantity: "0",
                blocked_quantity: "0",
                recalled_quantity: "0",
                damaged_quantity: "0",
                disposal_pending_quantity: "0",
                latest_purchase_cost: null,
                latest_purchase_uom_code: null,
                latest_purchase_date: null,
                purchase_event_count: 0,
              },
            ],
            next_cursor: null,
            has_more: false,
          };
        }

        throw new Error(
          "Unexpected request: " + path,
        );
      },
    );
  });

  it("shows expiry unavailability while keeping RELEASED as the operational batch status", async () => {
    render(<TabBatches locationId={119} />);

    await waitFor(() => {
      expect(
        screen.getByText(
          "inventoryLive.batchDisposition.RELEASED",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          /inventoryLive\.expiryUnavailable/,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          "inventoryLive.expiredSince",
        ),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByText(
        "inventoryLive.batchDisposition.BLOCKED",
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "inventoryLive.batchDisposition.QUARANTINED",
      ),
    ).not.toBeInTheDocument();
    expect(mocks.toastError).not.toHaveBeenCalled();
  });
});
