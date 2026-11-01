import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";

import { resources } from "@/i18n/resources";
import type { WarehouseProduct } from "@/pages/inventory/liveStock/contracts";

const state = vi.hoisted(() => ({ language: "en" as "en" | "ar" }));
vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: () => undefined },
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      const dictionary: unknown = resources[state.language].translation;
      const value = key.split(".").reduce<unknown>(
        (entry, name) =>
          entry && typeof entry === "object"
            ? (entry as Record<string, unknown>)[name]
            : undefined,
        dictionary,
      );
      if (typeof value !== "string") return key;
      return value.replace(/\{\{([a-zA-Z]+)\}\}/g,
        (_, name: string) => String(params?.[name] ?? ""));
    },
    i18n: {
      language: state.language,
      resolvedLanguage: state.language,
      dir: () => state.language === "ar" ? "rtl" : "ltr",
    },
  }),
}));
vi.mock("@/pages/inventory/liveStock/LiveStockFilters", () => ({
  LiveStockFilters: () => null,
}));
vi.mock("@/pages/inventory/liveStock/LiveStockTable", () => ({
  LiveStockTable: ({ products }: { products: WarehouseProduct[] }) => (
    <div data-testid="stock-rows">{products.map(p => <span key={p.id}>{p.name}</span>)}</div>
  ),
}));
vi.mock("@/pages/inventory/liveStock/LiveStockMobileCards", () => ({
  LiveStockMobileCards: () => null,
}));
vi.mock("@/pages/inventory/liveStock/BatchDetailPanel", () => ({
  BatchDetailPanel: () => null,
}));
vi.mock("@/pages/inventory/liveStock/useLiveStockBatchDetail", () => ({
  useLiveStockBatchDetail: () => ({
    product: null, page: null, loading: false, loadError: null,
    sourceByBatch: {}, sourceOpenId: null, sourceLoadingId: null,
    sourceErrorId: null, open: vi.fn(), close: vi.fn(),
    retry: vi.fn(), loadMore: vi.fn(), loadSource: vi.fn(),
    retrySource: vi.fn(), refresh: vi.fn(), invalidate: vi.fn(),
  }),
}));

class Observer {
  observe() {}
  disconnect() {}
  unobserve() {}
}
vi.stubGlobal("IntersectionObserver", Observer);

import { Tab1LiveStock } from "@/pages/inventory/Tab1LiveStock";
import { LiveStockWarehouseContext } from "@/pages/inventory/liveStock/LiveStockWarehouseContext";

const items = (count: number): WarehouseProduct[] =>
  Array.from({ length: count }, (_, i) =>
    ({ id: i + 1, name: `Variant ${i + 1}` } as WarehouseProduct));

const base: ComponentProps<typeof Tab1LiveStock> = {
  locationId: 10,
  locations: [{ id: 10, name: "Warehouse A" }],
  stockTotal: null,
  lastSync: null,
  isAuditLocked: false,
  products: [],
  loading: false,
  pageReady: false,
  pageError: null,
  summaryError: null,
  alertCount: null,
  matchingTotal: null,
  hasMore: false,
  stockState: "all",
  sort: "stock_first",
  onSortChange: vi.fn(),
  view: "warehouse",
  onViewChange: vi.fn(),
  indicators: [],
  familyId: null,
  onLocationChange: vi.fn(),
  onRefresh: vi.fn(),
  onRetryPage: vi.fn(),
  onSearchChange: vi.fn(),
  onStockStateChange: vi.fn(),
  onIndicatorsChange: vi.fn(),
  onFamilyChange: vi.fn(),
  onLoadMore: vi.fn(),
};
const draw = (overrides: Partial<typeof base> = {}) => render(
  <Tab1LiveStock {...base} {...overrides} />,
);
const timestamp = new Date("2026-10-30T09:42:03Z");

beforeEach(() => { state.language = "en"; });
afterEach(cleanup);

describe("UI-07/UI-08: distinct summary, row and fetch-time semantics", () => {
  it("represents unverified summary, list and fetch time as unknown, not zero", () => {
    draw({ loading: true, pageReady: false, stockTotal: null, lastSync: null });
    expect(screen.getByLabelText("Count not currently verified")).toBeInTheDocument();
    expect(screen.getByLabelText("Last successful fetch time unknown")).toBeInTheDocument();
    expect(screen.getByTestId("live-count-unverified"))
      .toHaveTextContent("List variant count has not been verified yet.");
    expect(screen.queryByTestId("live-loaded-count")).not.toBeInTheDocument();
    expect(screen.getByText(/Last successful stock-list fetch/).textContent)
      .toContain("—");
  });

  it("displays genuine verified zero for both independent counts", () => {
    draw({ pageReady: true, stockTotal: 0, products: [],
      matchingTotal: null, hasMore: false, lastSync: timestamp, alertCount: 0 });
    const heading = screen.getByText("Variants in stock summary");
    expect(within(heading.parentElement as HTMLElement).getByText("0"))
      .toBeInTheDocument();
    expect(screen.getByTestId("live-loaded-count"))
      .toHaveTextContent("Variants loaded from the list: 0");
    expect(screen.queryByTestId("live-unknown-total")).not.toBeInTheDocument();
    expect(screen.getByText(/Last successful stock-list fetch/).textContent)
      .not.toContain("—");
  });

  it("never presents a summary of 600 variants as the matching count for 50 loaded rows", () => {
    draw({ pageReady: true, stockTotal: 600, products: items(50),
      hasMore: true, matchingTotal: null, lastSync: timestamp });
    expect(screen.getByTestId("live-loaded-count"))
      .toHaveTextContent("Variants loaded from the list: 50");
    expect(screen.getByTestId("live-unknown-total"))
      .toHaveTextContent("the total matching count is unknown");
    expect(screen.queryByTestId("live-matching-total")).not.toBeInTheDocument();
    expect(screen.getByText("Variants in stock summary").parentElement)
      .toHaveTextContent("600");
  });

  it("describes filtered and partially loaded cursor pages without inventing COUNT(*)", () => {
    const filtered = { pageReady: true, stockTotal: 900, products: items(2),
      hasMore: true, matchingTotal: null, stockState: "sellable" as const,
      loading: true, lastSync: timestamp };
    draw(filtered);
    expect(screen.getByTestId("live-loaded-count"))
      .toHaveTextContent("Variants loaded from the list: 2");
    expect(screen.getByTestId("live-unknown-total")).toBeInTheDocument();
    expect(screen.queryByTestId("live-matching-total")).not.toBeInTheDocument();
  });

  it("reports real exact totals only when a non-null server total exists", () => {
    draw({ pageReady: true, products: items(2), matchingTotal: 15, hasMore: true });
    expect(screen.getByTestId("live-loaded-count")).toHaveTextContent("2");
    expect(screen.getByTestId("live-matching-total"))
      .toHaveTextContent("Verified total matching variants: 15");
  });

  it("keeps previously fetched rows labelled as loaded during refresh failure", () => {
    draw({ pageReady: true, products: items(2), matchingTotal: null,
      hasMore: true, pageError: "NETWORK_UNAVAILABLE", lastSync: timestamp });
    expect(screen.getByTestId("live-loaded-count"))
      .toHaveTextContent("Variants loaded from the list: 2");
    expect(screen.getByText(/Last successful stock-list fetch/)).toBeInTheDocument();
    expect(screen.getByText(/The latest data could not be fetched/)).toBeInTheDocument();
    expect(screen.queryByTestId("live-matching-total")).not.toBeInTheDocument();
  });

  it("keeps physical-stock wording out of summary and fetch-time labels in Arabic RTL", () => {
    state.language = "ar";
    draw({ stockTotal: 0, pageReady: true, products: items(1),
      hasMore: true, lastSync: timestamp });
    expect(screen.getByText("أصناف ملخص الرصيد")).toBeInTheDocument();
    expect(screen.getByTestId("live-loaded-count"))
      .toHaveTextContent("الأصناف المحمّلة من القائمة: 1");
    expect(screen.getByTestId("live-unknown-total"))
      .toHaveTextContent("العدد الكلي للمطابقات غير معروف");
    expect(screen.getByText(/آخر جلب ناجح لقائمة الأصناف/)).toBeInTheDocument();
    expect(screen.getByTestId("live-loaded-count").closest('[dir="rtl"]')).not.toBeNull();
  });

  it("explicitly names summary as a distinct-variant scope and not an on-hand quantity", () => {
    const { container } = render(
      <LiveStockWarehouseContext locationId={10}
        locations={[{ id: 10, name: "Warehouse A" }]}
        stockTotal={8} lastSync={timestamp}
        isAuditLocked={false} loading={false}
        onLocationChange={vi.fn()} onRefresh={vi.fn()} />,
    );
    expect(container.querySelector("[title*='Distinct variants in the summary scope']")).not.toBeNull();
    expect(screen.getByText("Variants in stock summary").parentElement)
      .toHaveTextContent("8");
  });
});
