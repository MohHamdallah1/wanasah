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

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn().mockResolvedValue({
    items: [],
    next_cursor: null,
    has_more: false,
  }),
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
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

class IntersectionObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal(
  "IntersectionObserver",
  IntersectionObserverStub,
);

import { Tab1LiveStock } from "../pages/inventory/Tab1LiveStock";
import type { WarehouseProduct } from "../pages/inventory/liveStock/contracts";

const product: WarehouseProduct = {
  id: 11,
  name: "Preserved Product",
  sku: "SKU-11",
  product_id: 5,
  family_name: "Preserved Family",
  base_uom_id: 1,
  base_uom_code: "EACH",
  base_uom_name: "Each",
  display_uom_id: 1,
  display_uom_code: "EACH",
  display_uom_name: "Each",
  display_factor_to_base: "1",
  currency_code: "JOD",
  average_cost_display: null,
  last_purchase_cost: null,
  last_purchase_uom_code: null,
  last_purchase_date: null,
  quantity_scale: 0,
  quantity_step: "1",
  on_hand_quantity: "10",
  reserved_quantity: "1",
  available_for_sale_quantity: "8",
  unavailable_quantity: "1",
  vehicle_quantity: "0",
  recalled_quantity: "0",
  available_quantity: "8",
  blocked_quantity: "0",
  total_quantity: "10",
  damaged_quantity: "0",
  minimum_quantity: "2",
};

const baseProps = {
  locationId: 119,
  locations: [{ id: 119, name: "Warehouse 119" }],
  stockTotal: 1,
  lastSync: new Date("2026-09-25T12:00:00Z"),
  isAuditLocked: false,
  loading: false,
  alertCount: 0,
  matchingTotal: 1,
  hasMore: false,
  stockState: "all" as const,
  indicators: [],
  familyId: null,
  canManageMinimum: false,
  onLocationChange: vi.fn(),
  onRefresh: vi.fn(),
  onSearchChange: vi.fn(),
  onStockStateChange: vi.fn(),
  onIndicatorsChange: vi.fn(),
  onFamilyChange: vi.fn(),
  onLoadMore: vi.fn(),
};

describe("Live Stock local failure states", () => {
  it("shows a local first-load failure instead of an empty-data message", () => {
    const onRefresh = vi.fn();

    render(
      <Tab1LiveStock
        {...baseProps}
        products={[]}
        pageReady={false}
        pageError="reference: REQ-123"
        summaryError={null}
        onRefresh={onRefresh}
      />,
    );

    expect(
      screen.getByText("inventoryLive.errors.updateTitle"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("inventoryLive.errors.noData"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("reference: REQ-123"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("inventoryLive.noMatches"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("common.retry"));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("keeps the last successful rows visible when refresh fails", () => {
    render(
      <Tab1LiveStock
        {...baseProps}
        products={[product]}
        pageReady
        pageError="reference: REQ-STALE"
        summaryError={null}
      />,
    );

    expect(
      screen.getByText("Preserved Product"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("inventoryLive.errors.staleData"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("reference: REQ-STALE"),
    ).toBeInTheDocument();
  });

  it("keeps the product table available when only the summary fails", () => {
    render(
      <Tab1LiveStock
        {...baseProps}
        products={[product]}
        pageReady
        pageError={null}
        summaryError="reference: REQ-SUMMARY"
      />,
    );

    expect(
      screen.getByText("Preserved Product"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("inventoryLive.errors.summaryTitle"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("inventoryLive.errors.summaryUnavailable"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("reference: REQ-SUMMARY"),
    ).toBeInTheDocument();
  });
});
