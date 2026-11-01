import { cleanup, render } from "@testing-library/react";
import { afterAll, beforeAll, describe, it, vi } from "vitest";

import type {
  LiveStockStockState,
  WarehouseProduct,
} from "@/pages/inventory/liveStock/contracts";
import { Tab1LiveStock } from "@/pages/inventory/Tab1LiveStock";

const mocks = vi.hoisted(() => ({
  language: "en",
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: string; defaultValue?: string }) =>
      options?.defaultValue ?? (options?.count ? `${key}:${options.count}` : key),
    i18n: {
      language: mocks.language,
      resolvedLanguage: mocks.language,
      dir: () => "ltr",
    },
  }),
}));

vi.mock("@/pages/inventory/liveStock/LiveStockFilters", () => ({
  LiveStockFilters: () => null,
}));

vi.mock("@/pages/inventory/liveStock/LiveStockWarehouseContext", () => ({
  LiveStockWarehouseContext: () => null,
}));

vi.mock("@/pages/inventory/liveStock/BatchDetailPanel", () => ({
  BatchDetailPanel: () => null,
}));

vi.mock("@/pages/inventory/liveStock/useLiveStockBatchDetail", () => ({
  useLiveStockBatchDetail: () => ({
    product: null,
    page: null,
    loading: false,
    loadError: null,
    sourceByBatch: {},
    sourceOpenId: null,
    sourceLoadingId: null,
    sourceErrorId: null,
    open: vi.fn(),
    close: vi.fn(),
    retry: vi.fn(),
    loadMore: vi.fn(),
    loadSource: vi.fn(),
    retrySource: vi.fn(),
    refresh: vi.fn(),
    invalidate: vi.fn(),
  }),
}));

class IntersectionObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
}

const noop = () => {};

function product(index: number): WarehouseProduct {
  const id = index + 1;
  return {
    id,
    name: `Product ${id.toString().padStart(5, "0")}`,
    sku: `SKU-${id}`,
    product_id: 1,
    family_name: "Benchmark Family",
    base_uom_id: 1,
    base_uom_code: "EA",
    base_uom_name: "Each",
    display_uom_id: 1,
    display_uom_code: "EA",
    display_uom_name: "Each",
    display_factor_to_base: "1",
    currency_code: "JOD",
    average_cost_display: "1.250000",
    last_purchase_cost: "1.500000",
    last_purchase_uom_code: "EA",
    last_purchase_date: "2026-10-30",
    quantity_scale: 6,
    quantity_step: "0.000001",
    on_hand_quantity: "10.000000",
    reserved_quantity: "1.000000",
    available_for_sale_quantity: "9.000000",
    unavailable_quantity: "0.000000",
    vehicle_quantity_scope: "COMPANY_WIDE" as const, vehicle_quantity: "2.000000",
    recalled_quantity: "0.000000",
    available_quantity: "9.000000",
    blocked_quantity: "0.000000",
    total_quantity_scope: "WAREHOUSE_PHYSICAL" as const, total_quantity: "10.000000",
    damaged_quantity: "0.000000",
    minimum_quantity: "2.000000",
  is_low_stock: false,
  };
}

const rows = Array.from({ length: 5000 }, (_, index) => product(index));

function installMatchMedia(desktop: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("max-width") ? !desktop : desktop,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

function props(products: WarehouseProduct[]) {
  return {
    locationId: 11,
    locations: [{ id: 11, name: "Benchmark Warehouse" }],
    stockTotal: products.length,
    lastSync: new Date("2026-10-30T00:00:00Z"),
    isAuditLocked: false,
    products,
    loading: false,
    pageReady: true,
    pageError: null,
    summaryError: null,
    alertCount: 0,
    matchingTotal: null,
    hasMore: false,
    stockState: "all" as LiveStockStockState,
    sort: "stock_first" as const,
    onSortChange: noop,
    view: "warehouse" as const,
    onViewChange: noop,
    indicators: [],
    familyId: null,
    onLocationChange: noop,
    onRefresh: noop,
    onRetryPage: noop,
    onSearchChange: noop,
    onStockStateChange: noop,
    onIndicatorsChange: noop,
    onFamilyChange: noop,
    onLoadMore: noop,
  };
}

function snapshot(container: HTMLElement, viewport: "desktop" | "mobile", loadedRows: number, renderMs: number) {
  const payload = {
    phase: process.env.LIVE_STOCK_RENDER_PHASE ?? "unknown",
    viewport,
    loadedRows,
    renderMs: Number(renderMs.toFixed(2)),
    totalDomNodes: container.querySelectorAll("*").length,
    desktopRows: container.querySelectorAll("[data-cp13-stock-row]").length,
    mobileCards: container.querySelectorAll("[data-cp13-stock-card]").length,
    detailButtons: container.querySelectorAll(
      'button[aria-label^="Open batch details"], button[aria-label^="inventoryLive"]',
    ).length,
  };
  console.log("LIVE_STOCK_RENDER_METRIC " + JSON.stringify(payload));
}

function runViewport(viewport: "desktop" | "mobile") {
  installMatchMedia(viewport === "desktop");
  const started = performance.now();
  const result = render(<Tab1LiveStock {...props(rows.slice(0, 50))} />);
  snapshot(result.container, viewport, 50, performance.now() - started);

  for (const loadedRows of [500, 5000]) {
    const updateStarted = performance.now();
    result.rerender(<Tab1LiveStock {...props(rows.slice(0, loadedRows))} />);
    snapshot(
      result.container,
      viewport,
      loadedRows,
      performance.now() - updateStarted,
    );
  }

  result.unmount();
}

describe("NEW-01 Live Stock render benchmark", () => {
  beforeAll(() => {
    vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);
  });

  afterAll(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it(
    "measures accumulated cursor rendering at 50, 500 and 5000 rows",
    () => {
      runViewport("desktop");
      runViewport("mobile");
    },
    120_000,
  );
});
