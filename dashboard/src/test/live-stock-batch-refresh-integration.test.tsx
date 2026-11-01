import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({
  fetch: vi.fn(),
  t: (value: string) => value,
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mock.fetch }));
vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: () => undefined },
  useTranslation: () => ({
    t: mock.t,
    i18n: { language: "en", resolvedLanguage: "en", dir: () => "ltr" },
  }),
}));
vi.mock("@/pages/inventory/liveStock/LiveStockFilters", () => ({
  LiveStockFilters: () => null,
}));
vi.mock("@/pages/inventory/liveStock/LiveStockWarehouseContext", () => ({
  LiveStockWarehouseContext: ({ onRefresh }: { onRefresh: () => void }) => (
    <button type="button" onClick={onRefresh}>Refresh list</button>
  ),
}));
vi.mock("@/pages/inventory/liveStock/LiveStockTable", () => ({
  LiveStockTable: ({ products, onOpen }: {
    products: Array<{ id: number }>;
    onOpen: (product: { id: number }) => void;
  }) => <button type="button" onClick={() => onOpen(products[0])}>Open selected batch</button>,
}));
vi.mock("@/pages/inventory/liveStock/LiveStockMobileCards", () => ({
  LiveStockMobileCards: () => null,
}));
vi.mock("@/pages/inventory/liveStock/BatchDetailPanel", () => ({
  BatchDetailPanel: ({ product, batches, error, sourceByBatch, onLoadSource }: {
    product: { id: number } | null;
    batches: Array<{ on_hand_quantity: string }>;
    error: { message: string } | null;
    sourceByBatch: Record<number, unknown>;
    onLoadSource: (id: number) => void;
  }) => product ? (
    <div data-testid="detail" data-product={product.id}>
      <span data-testid="detail-quantity">{batches[0]?.on_hand_quantity ?? "no-verified-batches"}</span>
      <span data-testid="source-count">{Object.keys(sourceByBatch).length}</span>
      <span data-testid="detail-error">{error?.message ?? "none"}</span>
      <button type="button" onClick={() => onLoadSource(71)}>Toggle source</button>
    </div>
  ) : null,
}));

class Observer {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("IntersectionObserver", Observer);

import { Tab1LiveStock } from "@/pages/inventory/Tab1LiveStock";
import type { WarehouseProduct } from "@/pages/inventory/liveStock/contracts";

const selected = (onHand = "2.500001") => ({
  id: 41, product_id: 4, name: "Selected", sku: "S41",
  family_name: "Family", currency_code: "JOD",
  base_uom_code: "EA", display_uom_code: "EA",
  display_factor_to_base: "1", on_hand_quantity: onHand,
}) as WarehouseProduct;
const batchPage = (qty: string) => ({
  location_id: 11, product_variant_id: 41, currency_code: "JOD",
  next_cursor: null, has_more: false,
  batches: [{
    batch_id: 71, batch_number: null, production_date: null, expiry_date: null,
    disposition: "RELEASED", disposition_revision: 1, disposition_reason: null,
    allowed_disposition_targets: [], days_to_expiry: null,
    on_hand_quantity: qty, reserved_quantity: "0", available_for_sale_quantity: qty,
    unavailable_quantity: "0", restricted_quantity: "0",
    expiry_unavailable_quantity: "0", quarantined_quantity: "0",
    blocked_quantity: "0", recalled_quantity: "0", damaged_quantity: "0",
    disposal_pending_quantity: "0", latest_purchase_cost: null,
    latest_purchase_uom_code: null, latest_purchase_date: null, purchase_event_count: 0,
  }],
});
const source = () => ({
  location_id: 11, product_variant_id: 41, batch_id: 71, location_name: "Warehouse 11",
  statuses: [{
    stock_status: "AVAILABLE", on_hand_quantity: "2.500001", reserved_quantity: "0",
    movable_quantity: "2.500001",
    reservation_evidence: { coverage: "NONE", owners: [],
      unattributed_quantity: "0", owners_truncated: false },
  }],
});
const defaults = {
  locationId: 11, locations: [{ id: 11, name: "Warehouse 11" }],
  stockTotal: 1, isAuditLocked: false,
  loading: false, pageReady: true,
  pageError: null, summaryError: null,
  alertCount: 0, matchingTotal: null, hasMore: false,
  stockState: "all" as const, sort: "stock_first" as const,
  onSortChange: vi.fn(), indicators: [], familyId: null,
  onLocationChange: vi.fn(), onRefresh: vi.fn(), onRetryPage: vi.fn(),
  onSearchChange: vi.fn(), onStockStateChange: vi.fn(),
  onIndicatorsChange: vi.fn(), onFamilyChange: vi.fn(), onLoadMore: vi.fn(),
};
const countDetailReads = () => mock.fetch.mock.calls.filter(([url]) =>
  String(url).includes("/batches?")).length;
beforeEach(() => { mock.fetch.mockReset(); });
afterEach(cleanup);

describe("L-02 list/detail coupling without batch-wide eager reads", () => {
  it("invalidates immediately on Refresh, rechecks only after list completion and resets source", async () => {
    let calls = 0;
    mock.fetch.mockImplementation((url: string) =>
      url.includes("/source?") ? Promise.resolve(source()) :
        Promise.resolve(batchPage(++calls === 1 ? "2.500001" : "3.500001")));
    const first = selected();
    const { rerender } = render(
      <Tab1LiveStock {...defaults} products={[first]} lastSync={new Date(1000)} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open selected batch" }));
    await waitFor(() =>
      expect(screen.getByTestId("detail-quantity")).toHaveTextContent("2.500001"));

    fireEvent.click(screen.getByRole("button", { name: "Toggle source" }));
    await waitFor(() => expect(screen.getByTestId("source-count")).toHaveTextContent("1"));

    fireEvent.click(screen.getByRole("button", { name: "Refresh list" }));
    expect(defaults.onRefresh).toHaveBeenCalled();
    expect(screen.getByTestId("detail-quantity")).toHaveTextContent("no-verified-batches");
    expect(screen.getByTestId("source-count")).toHaveTextContent("0");
    expect(screen.getByTestId("detail-error")).toHaveTextContent("Previous batch details are no longer verified after refresh. Retry to check.");
    expect(countDetailReads()).toBe(1);

    rerender(<Tab1LiveStock {...defaults} products={[first]} lastSync={new Date(1000)} loading pageReady />);
    rerender(<Tab1LiveStock {...defaults} products={[selected("3.500001")]} lastSync={new Date(2000)} />);
    await waitFor(() =>
      expect(screen.getByTestId("detail-quantity")).toHaveTextContent("3.500001"));
    expect(countDetailReads()).toBe(2);
    expect(screen.getByTestId("source-count")).toHaveTextContent("0");
  });

  it("does not reload the open selected batch when infinite-scroll appends unrelated rows", async () => {
    mock.fetch.mockResolvedValue(batchPage("2.500001"));
    const first = selected();
    const { rerender } = render(
      <Tab1LiveStock {...defaults} products={[first]} lastSync={new Date(1000)} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open selected batch" }));
    await waitFor(() => expect(screen.getByTestId("detail-quantity")).toHaveTextContent("2.500001"));
    rerender(<Tab1LiveStock {...defaults} products={[first, selected("10")]} lastSync={new Date(2000)} />);
    expect(countDetailReads()).toBe(1);
  });


  it("revalidates once when a newly refreshed list drops the selected product", async () => {
    let count = 0;
    mock.fetch.mockImplementation((url: string) =>
      url.includes("/source?") ? Promise.resolve(source())
        : Promise.resolve(batchPage(++count === 1 ? "2.500001" : "0")));
    const first = selected();
    const { rerender } = render(
      <Tab1LiveStock {...defaults} products={[first]} lastSync={new Date(1000)} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open selected batch" }));
    await waitFor(() => expect(screen.getByTestId("detail-quantity")).toHaveTextContent("2.500001"));

    rerender(<Tab1LiveStock {...defaults} products={[]} lastSync={new Date(2000)} />);
    await waitFor(() => expect(countDetailReads()).toBe(2));
    expect(screen.getByTestId("detail-quantity")).toHaveTextContent("0");
    rerender(<Tab1LiveStock {...defaults} products={[]} lastSync={new Date(3000)} />);
    expect(countDetailReads()).toBe(2);
  });

  it("does not present invalidated detail as verified after list refresh fails", async () => {
    mock.fetch.mockResolvedValue(batchPage("2.500001"));
    const first = selected();
    const { rerender } = render(
      <Tab1LiveStock {...defaults} products={[first]} lastSync={new Date(1000)} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open selected batch" }));
    await waitFor(() => expect(screen.getByTestId("detail-quantity")).toHaveTextContent("2.500001"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh list" }));
    rerender(<Tab1LiveStock {...defaults} products={[first]} lastSync={new Date(1000)}
      pageError="list unavailable" loading={false} />);
    expect(screen.getByTestId("detail-quantity")).toHaveTextContent("no-verified-batches");
    expect(screen.getByTestId("detail-error")).toHaveTextContent("Previous batch details are no longer verified after refresh. Retry to check.");
    expect(countDetailReads()).toBe(1);
  });
});
