import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WarehouseProduct } from "@/pages/inventory/liveStock/contracts";

const state = vi.hoisted(() => ({
  authFetch: vi.fn(),
  scope: "1",
  principal: "75",
  actor: "75",
  locationPending: true,
  locationFetching: true,
  locationSuccess: false,
  locationError: false,
  globalPending: false,
  globalFetching: false,
  globalSuccess: true,
  globalError: false,
  permission: true,
  locale: "en",
}));

vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => state.authFetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  parseInventoryLocationCapabilities: vi.fn(),
  useInventoryAccess: (id: number | null = null) => {
    const location = id !== null;
    const permitted = state.permission;
    const success = location ? state.locationSuccess : state.globalSuccess;
    const pending = location ? state.locationPending : state.globalPending;
    const fetching = location ? state.locationFetching : state.globalFetching;
    const error = location ? state.locationError : state.globalError;
    return {
      isSuccess: success, isPending: pending, isFetching: fetching,
      isError: error, isFetchedAfterMount: success && !pending && !fetching,
      error: error ? Object.assign(new Error("denied"), { status: 403 }) : null,
      can: (code: string) => permitted && code === "inventory.read",
      canAny: (code: string) => permitted && code === "inventory.read",
      isCompanyOwner: false, refetch: vi.fn(),
      data: success ? {
        company_id: Number(state.scope), principal_id: Number(state.principal),
        backoffice_user_id: Number(state.actor), location_id: id,
        is_company_owner: false, permissions: [],
        any_permissions: permitted ? ["inventory.read"] : [],
        location_permissions: location && permitted ? ["inventory.read"] : [],
      } : undefined,
    };
  },
}));
vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: () => undefined },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: state.locale, resolvedLanguage: state.locale,
      dir: () => state.locale === "ar" ? "rtl" : "ltr" },
  }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), info: vi.fn() } }));
vi.mock("@/pages/inventory/InventoryTopDock", () => ({
  InventoryTopDock: () => <div data-testid="dock" />,
}));
vi.mock("@/pages/inventory/Tab1LiveStock", () => ({
  Tab1LiveStock: ({ products, stockTotal }: { products: WarehouseProduct[]; stockTotal: number | null }) =>
    <div data-testid="live-stock">{products.map(p => <span key={p.id}>{p.name}:{p.average_cost_display}</span>)}<span>total={stockTotal ?? "hidden"}</span></div>,
}));
vi.mock("@/pages/inventory/TabBatches", () => ({ TabBatches: () => null }));
vi.mock("@/pages/inventory/Tab2Inbound", () => ({ Tab2Inbound: () => null }));
vi.mock("@/pages/inventory/Tab3Stocktake", () => ({ Tab3Stocktake: () => null }));
vi.mock("@/pages/inventory/Tab4Ledger", () => ({ Tab4Ledger: () => null }));
vi.mock("@/pages/inventory/TabWarehouseLocations", () => ({ TabWarehouseLocations: () => null }));
vi.mock("@/pages/inventory/TabTransfers", () => ({ TabTransfers: () => null }));
vi.mock("@/pages/inventory/TabInventoryAccess", () => ({ TabInventoryAccess: () => null }));
vi.mock("@/pages/inventory/archive/ArchiveOwnerWorkspace", () => ({ ArchiveOwnerWorkspace: () => null }));

import MainInventory from "@/pages/inventory/MainInventory";
import {
  clearInventoryWarmScope, inventoryWarmScopeKey,
  patchLiveStockWarmSnapshot, readLiveStockWarmSnapshot,
  writeInventoryShellWarmSnapshot,
} from "@/pages/inventory/inventorySessionCache";

const item = { id: 41, name: "PRIVATE_STOCK_ROW", average_cost_display: "SECRET_COST_123" } as WarehouseProduct;
const loc = { id: 101, name: "Warehouse 101", code: "W101" };
const shell = { locations: [loc], locationsTruncated: false,
  selectedLocationId: 101, setup: { warehouse_ready: true, active_warehouse_count: 1,
    accessible_warehouse_count: 1, can_create: false } };
const resultPage = { items: [], next_cursor: null, has_more: false, total: null };
const warehousePage = { items: [loc], next_cursor: null, has_more: false, selected: loc, total: 1 };
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};
const mount = () => render(<MemoryRouter><MainInventory /></MemoryRouter>);
const seed = () => {
  const key = inventoryWarmScopeKey("1", "75", "75");
  writeInventoryShellWarmSnapshot(key, shell);
  patchLiveStockWarmSnapshot(key, 101, { hasPage: true, items: [item],
    nextCursor: null, matchingTotal: 1, hasSummary: true,
    stockTotal: 123, alertCount: 2, lastSyncMs: Date.now() - 60_000 });
};
const grant = () => {
  state.locationPending = false;
  state.locationFetching = false;
  state.locationSuccess = true;
};
const fakeServer = (options: { page?: Promise<unknown>; selection?: Promise<unknown> } = {}) => {
  state.authFetch.mockImplementation((url: string) => {
    const path = new URL(url, "https://localhost").pathname;
    if (path === "/warehouse/locations/selection") return options.selection ?? Promise.resolve(warehousePage);
    if (path === "/warehouse/inventory/cursor") return options.page ?? Promise.resolve(resultPage);
    if (path === "/warehouse/inventory/summary") return Promise.resolve({ stock_total: 0, alert_count: 0 });
    throw Error("Unexpected " + path);
  });
};

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("company_id", "1");
  localStorage.setItem("principal_id", "75");
  localStorage.setItem("backoffice_user_id", "75");
  localStorage.setItem("admin_token", "synthetic-for-unit-test-only");
  Object.assign(state, { scope: "1", principal: "75", actor: "75",
    locationPending: true, locationFetching: true, locationSuccess: false,
    locationError: false, globalPending: false, globalFetching: false,
    globalSuccess: true, globalError: false, permission: true, locale: "en" });
  state.authFetch.mockReset();
});
afterEach(() => { cleanup(); clearInventoryWarmScope("1:75:75"); clearInventoryWarmScope("1:75"); });

describe("UI-04: cache is never its own access authority", () => {
  it("reproduces and blocks PRIVATE rows and costs before new access admission", async () => {
    seed();
    const selection = deferred<unknown>();
    fakeServer({ selection: selection.promise });
    mount();
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(screen.queryByText(/SECRET_COST_123/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("inventoryShell.warmUnverified");
  });

  it("shows explicitly stale warm data only after same-scope access and server selection, then fresh data", async () => {
    seed();
    const response = deferred<unknown>();
    fakeServer({ page: response.promise });
    const view = mount();
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    grant(); view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("inventoryShell.warmUnverified"));
    // The previously stored row is visible only with a stale label, never as current.
    await waitFor(() => expect(screen.getByText(/PRIVATE_STOCK_ROW/)).toBeInTheDocument());
    await act(async () => response.resolve(resultPage));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("inventoryShell.verifiedFresh"));
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
  });

  it("fails closed when the same-location permission is revoked on revalidation", async () => {
    seed(); fakeServer(); const view = mount();
    state.permission = false; state.locationPending = false; state.locationFetching = false;
    state.locationSuccess = false; state.locationError = true;
    view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("inventoryShell.accessChanged");
    await waitFor(() => expect(readLiveStockWarmSnapshot(inventoryWarmScopeKey("1","75","75"),101)).toBeNull());
  });

  it("does not disclose cached rows on a switched principal or company", async () => {
    seed(); fakeServer(); const view = mount();
    localStorage.setItem("principal_id", "999");
    state.principal = "999";
    view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    localStorage.setItem("company_id", "2");
    state.scope = "2";
    view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
  });

  it("distinguishes offline verification failure, keeps sensitive data redacted, and supports retry", async () => {
    seed(); fakeServer(); const view = mount();
    state.locationPending = false; state.locationFetching = false;
    state.locationError = true; state.locationSuccess = false;
    view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("does not revive a revoked scope with a delayed inventory page response", async () => {
    const response = deferred<unknown>();
    fakeServer({ page: response.promise }); grant();
    const view = mount();
    await waitFor(() => expect(state.authFetch.mock.calls.some(([url]) => String(url).includes("/warehouse/inventory/cursor"))).toBe(true));
    state.permission = false; state.locationSuccess = false; state.locationError = true;
    view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    await act(async () => response.resolve({ ...resultPage, items: [item] }));
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(readLiveStockWarmSnapshot(inventoryWarmScopeKey("1","75","75"),101)?.items.some(p=>p.id===41)).not.toBe(true);
  });
});
