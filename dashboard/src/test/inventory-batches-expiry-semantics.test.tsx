import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

vi.mock("sonner", () => ({
  toast: { error: mocks.toastError },
}));

vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, options?: Record<string, unknown>) =>
        typeof options?.defaultValue === "string" ? options.defaultValue : key,
      i18n: {
        language: "en",
        resolvedLanguage: "en",
        dir: () => "ltr",
      },
    }),
  };
});

import { TabBatches } from "../pages/inventory/TabBatches";

describe("Inventory batch expiry semantics", () => {
  beforeEach(() => {
    mocks.authFetch.mockReset();
    mocks.toastError.mockReset();
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "7");

    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path === "/inventory/access/me") {
        return {
          company_id: 1,
          principal_id: 7,
          backoffice_user_id: 17,
          is_company_owner: true,
          location_id: null,
          permissions: ["inventory.read", "batch.disposition"],
          any_permissions: [],
          location_permissions: [],
        };
      }

      if (path.startsWith("/warehouse/inventory/batches/cursor?")) {
        return {
          location_id: 119,
          as_of_date: "2026-10-16",
          items: [
            {
              batch_id: 9001,
              batch_number: "EXP-001",
              production_date: "2026-01-01",
              expiry_date: "2026-09-24",
              disposition: "RELEASED",
              disposition_reason: null,
              disposition_revision: 1,
              allowed_disposition_targets: ["QUARANTINED", "BLOCKED", "RECALLED"],
              days_to_expiry: -22,
              product_id: 21,
              product_variant_id: 211,
              product_name: "Expiry Product",
              sku: "SKU-211",
              family_name: "Expiry Family",
              lot_control_mode: "REQUIRED",
              expiry_control_mode: "REQUIRED",
              minimum_remaining_shelf_life_days: 0,
              sellability_state: "NOT_SELLABLE",
              sellability_reason_codes: ["EXPIRED"],
              base_uom_id: 1,
              base_uom_code: "EACH",
              base_uom_name: "Each",
              display_uom_id: 1,
              display_uom_code: "EACH",
              display_uom_name: "Each",
              display_factor_to_base: "1",
              quantity_scale: 0,
              quantity_step: "1",
              on_hand_quantity: "10",
              reserved_quantity: "0",
              available_for_sale_quantity: "0",
              unavailable_quantity: "10",
              available_status_quantity: "10",
              quarantined_quantity: "0",
              blocked_quantity: "0",
              recalled_quantity: "0",
              damaged_quantity: "0",
              disposal_pending_quantity: "0",
            },
          ],
          next_cursor: null,
          has_more: false,
        };
      }

      if (path.startsWith("/warehouse/inventory/batches/summary?")) {
        return {
          location_id: 119,
          as_of_date: "2026-10-16",
          total_relevant_batches: 1,
          expired_count: 1,
          expiring_soon_count: 0,
          non_sellable_count: 1,
          quarantined_count: 0,
          blocked_count: 0,
          recalled_count: 0,
          damaged_or_disposal_attention_count: 0,
        };
      }

      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it("keeps RELEASED disposition distinct from backend EXPIRED sellability", async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <TabBatches
          locationId={119}
          onFocusConsumed={() => undefined}
          onOpenTransfers={() => undefined}
          onOpenReservationOwner={() => undefined}
        />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Released").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Expired").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Not sellable").length).toBeGreaterThan(0);
    });
    const desktopRow = screen.getAllByText("Expiry Product")[0].closest("tr");
    expect(desktopRow).not.toBeNull();
    expect(within(desktopRow as HTMLElement).getByText("Released")).toBeInTheDocument();
    expect(within(desktopRow as HTMLElement).queryByText("Blocked")).not.toBeInTheDocument();
    expect(within(desktopRow as HTMLElement).queryByText("Quarantined")).not.toBeInTheDocument();
    expect(mocks.toastError).not.toHaveBeenCalled();
  });
});