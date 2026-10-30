import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  LiveStockStockState,
  WarehouseProduct,
} from "@/pages/inventory/liveStock/contracts";
import { Tab1LiveStock } from "@/pages/inventory/Tab1LiveStock";

const mocks = vi.hoisted(() => ({
  language: "en",
  open: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: string; defaultValue?: string }) =>
      options?.defaultValue ?? (options?.count ? `${key}:${options.count}` : key),
    i18n: {
      language: mocks.language,
      resolvedLanguage: mocks.language,
      dir: () => (mocks.language === "ar" ? "rtl" : "ltr"),
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
    open: mocks.open,
    close: vi.fn(),
    retry: vi.fn(),
    loadMore: vi.fn(),
    loadSource: vi.fn(),
    retrySource: vi.fn(),
    refresh: vi.fn(),
    invalidate: vi.fn(),
  }),
}));

let intersectionCallback:
  | ((entries: Array<{ isIntersecting: boolean }>) => void)
  | null = null;

class IntersectionObserverStub {
  constructor(
    callback: (entries: Array<{ isIntersecting: boolean }>) => void,
  ) {
    intersectionCallback = callback;
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
}

function createMediaController(initialNarrow: boolean) {
  let narrow = initialNarrow;
  const listeners = new Set<(event: MediaQueryListEvent) => void>();

  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      get matches() {
        return query.includes("max-width") ? narrow : !narrow;
      },
      media: query,
      onchange: null,
      addEventListener: (
        type: string,
        listener: (event: MediaQueryListEvent) => void,
      ) => {
        if (type === "change") listeners.add(listener);
      },
      removeEventListener: (
        type: string,
        listener: (event: MediaQueryListEvent) => void,
      ) => {
        if (type === "change") listeners.delete(listener);
      },
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  return {
    setNarrow(next: boolean) {
      narrow = next;
      const event = {
        matches: next,
        media: "(max-width: 767px)",
      } as MediaQueryListEvent;
      for (const listener of listeners) listener(event);
    },
  };
}

function product(index: number): WarehouseProduct {
  const id = index + 1;
  return {
    id,
    name: `Product ${id}`,
    sku: `SKU-${id}`,
    product_id: 1,
    family_name: "Family",
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
    on_hand_quantity: "10",
    reserved_quantity: "1",
    available_for_sale_quantity: "9",
    unavailable_quantity: "0",
    vehicle_quantity: "2",
    recalled_quantity: "0",
    available_quantity: "9",
    blocked_quantity: "0",
    total_quantity: "12",
    damaged_quantity: "0",
    minimum_quantity: "2",
  is_low_stock: false,
  };
}

const products = Array.from({ length: 5000 }, (_, index) => product(index));

function tabProps(onLoadMore = vi.fn()) {
  return {
    locationId: 11,
    locations: [{ id: 11, name: "Warehouse" }],
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
    hasMore: true,
    stockState: "all" as LiveStockStockState,
    indicators: [],
    familyId: null,
    onLocationChange: vi.fn(),
    onRefresh: vi.fn(),
    onRetryPage: vi.fn(),
    onSearchChange: vi.fn(),
    onStockStateChange: vi.fn(),
    onIndicatorsChange: vi.fn(),
    onFamilyChange: vi.fn(),
    onLoadMore,
  };
}

beforeEach(() => {
  mocks.language = "en";
  mocks.open.mockReset();
  intersectionCallback = null;
  vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);
  vi.stubGlobal("ResizeObserver", undefined);
  vi.stubGlobal(
    "requestAnimationFrame",
    (callback: FrameRequestCallback) => {
      callback(performance.now());
      return 1;
    },
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("NEW-01 Live Stock bounded responsive rendering", () => {
  it("mounts one bounded presentation, preserves focus across breakpoint changes, and keeps exact detail identity", async () => {
    const media = createMediaController(false);
    const onLoadMore = vi.fn();
    const { container } = render(<Tab1LiveStock {...tabProps(onLoadMore)} />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByTestId("live-stock-mobile-cards")).not.toBeInTheDocument();
    expect(container.querySelectorAll("[data-cp13-stock-row]").length).toBeLessThanOrEqual(40);
    expect(container.querySelectorAll("[data-cp13-stock-card]")).toHaveLength(0);
    expect(screen.getByRole("table")).toHaveAttribute("aria-rowcount", "5001");

    const desktopOpen = container.querySelector<HTMLButtonElement>(
      '[data-live-stock-product-open="1"]',
    );
    expect(desktopOpen).not.toBeNull();
    desktopOpen!.focus();
    expect(desktopOpen).toHaveFocus();
    fireEvent.click(desktopOpen!);
    expect(mocks.open).toHaveBeenCalledWith(products[0]);

    act(() => media.setNarrow(true));

    await waitFor(() => {
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(screen.getByTestId("live-stock-mobile-cards")).toBeInTheDocument();
    });
    expect(container.querySelectorAll("[data-cp13-stock-card]").length).toBeLessThanOrEqual(40);
    expect(container.querySelectorAll("[data-cp13-stock-row]")).toHaveLength(0);

    const mobileOpen = container.querySelector<HTMLButtonElement>(
      '[data-live-stock-product-open="1"]',
    );
    expect(mobileOpen).not.toBeNull();
    await waitFor(() => expect(mobileOpen).toHaveFocus());
    fireEvent.click(mobileOpen!);
    expect(mocks.open).toHaveBeenLastCalledWith(products[0]);

    expect(
      container.querySelector('[data-cp13-continuation="cursor"]'),
    ).toBeInTheDocument();
    act(() => intersectionCallback?.([{ isIntersecting: true }]));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it("preserves locale-driven direction while the list is windowed", () => {
    mocks.language = "ar";
    createMediaController(true);
    const { container } = render(<Tab1LiveStock {...tabProps()} />);
    expect(container.querySelector('[role="status"]')).toHaveAttribute("dir", "rtl");
    expect(screen.getByTestId("live-stock-mobile-cards")).toBeInTheDocument();
  });
});
