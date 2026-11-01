import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WarehouseProduct } from "@/pages/inventory/liveStock/contracts";

const state = vi.hoisted(() => ({
  authFetch: vi.fn(),
  stablePermission: vi.fn<(code: string) => boolean>(),
  translate: (key: string) => key,
  scope: "1",
  principal: "75",
  actor: "75",
  locationPending: true,
  locationFetching: true,
  locationSuccess: false,
  locationError: false,
  errorStatus: 403,
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
      error: error ? Object.assign(new Error("authorization-check-failed"), { status: state.errorStatus }) : null,
      can: state.stablePermission,
      canAny: state.stablePermission,
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
    t: state.translate,
    i18n: { language: state.locale, resolvedLanguage: state.locale,
      dir: () => state.locale === "ar" ? "rtl" : "ltr" },
  }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), info: vi.fn() } }));
vi.mock("@/pages/inventory/InventoryTopDock", () => ({
  InventoryTopDock: () => <div data-testid="dock" />,
}));
vi.mock("@/pages/inventory/Tab1LiveStock", () => ({
  Tab1LiveStock: ({ products, stockTotal, onRefresh, onLocationChange }: {
    products: WarehouseProduct[]; stockTotal: number | null;
    onRefresh: () => void; onLocationChange: (id: string) => void;
  }) => <div data-testid="live-stock">
    {products.map(p => <span key={p.id}>{p.name}:{p.average_cost_display}</span>)}
    <span>total={stockTotal ?? "hidden"}</span>
    <button onClick={onRefresh}>Refresh witness</button>
    <button onClick={() => onLocationChange("102")}>Switch warehouse witness</button>
  </div>,
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

const item: WarehouseProduct = {
  id: 41, name: "PRIVATE_STOCK_ROW", sku: "SECRET-SKU", product_id: 1,
  family_name: "Private family", base_uom_id: 1, base_uom_code: "EA",
  base_uom_name: "Each", display_uom_id: 1, display_uom_code: "EA",
  display_uom_name: "Each", display_factor_to_base: "1", currency_code: "JOD",
  average_cost_display: "123.000000", last_purchase_cost: "123.000000",
  last_purchase_uom_code: "EA", last_purchase_date: "2026-10-15",
  quantity_scale: 6, quantity_step: "0.000001", on_hand_quantity: "10",
  reserved_quantity: "0", available_for_sale_quantity: "10",
  unavailable_quantity: "0", vehicle_quantity_scope: "COMPANY_WIDE" as const, vehicle_quantity: "0", recalled_quantity: "0",
  available_quantity: "10", blocked_quantity: "0", total_quantity_scope: "WAREHOUSE_PHYSICAL" as const, total_quantity: "10",
  damaged_quantity: "0", minimum_quantity: "0",
  is_low_stock: false,
};
const loc = { id: 101, name: "Warehouse 101", code: "W101" };
const shell = { locations: [loc], locationsTruncated: false,
  selectedLocationId: 101, setup: { warehouse_ready: true, active_warehouse_count: 1,
    accessible_warehouse_count: 1, can_create: false } };
const resultPage = { items: [] as WarehouseProduct[], next_cursor: null,
  has_more: false, total: null, alert_count: null, alert_samples: [] as string[] };
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
const fakeServer = (options: { page?: Promise<unknown>; summary?: Promise<unknown>; selection?: Promise<unknown> } = {}) => {
  state.authFetch.mockImplementation((url: string) => {
    const path = new URL(url, "https://localhost").pathname;
    if (path === "/warehouse/locations/selection") return options.selection ?? Promise.resolve(warehousePage);
    if (path === "/warehouse/inventory/cursor") return options.page ?? Promise.resolve(resultPage);
    if (path === "/warehouse/inventory/summary") return options.summary ?? Promise.resolve({ stock_total: 0, alert_count: 0 });
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
    locationError: false, errorStatus: 403, globalPending: false, globalFetching: false,
    globalSuccess: true, globalError: false, permission: true, locale: "en" });
  state.authFetch.mockReset();
  state.stablePermission.mockReset();
  state.stablePermission.mockImplementation(
    (code) => state.permission && code === "inventory.read",
  );
});
afterEach(() => { cleanup(); clearInventoryWarmScope("1:75:75"); clearInventoryWarmScope("1:75"); });

describe("UI-04: cache is never its own access authority", () => {
  it.each(["ar", "en"])("does not flash a technical verification notice on initial load or admission (%s)", async (locale) => {
    state.locale = locale;
    // Known warehouse selection but no admitted stock: user sees the existing
    // safe loading state, never the transient technical access banner.
    writeInventoryShellWarmSnapshot(inventoryWarmScopeKey("1", "75", "75"), shell);
    const page = deferred<unknown>();
    fakeServer({ page: page.promise });
    const view = mount();
    expect(document.querySelector('[data-live-authority="loadingVerification"]')).toBeNull();
    expect(screen.queryByTestId("live-stock")).not.toBeInTheDocument();

    grant();
    view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    await waitFor(() => expect(state.authFetch.mock.calls.some(([url]) =>
      String(url).includes("/warehouse/inventory/cursor"))).toBe(true));
    expect(document.querySelector('[data-live-authority="loadingVerification"]')).toBeNull();
    await act(async () => page.resolve(resultPage));
    expect(document.querySelector('[data-live-authority="loadingVerification"]')).toBeNull();
  });

  it.each(["ar", "en"])("re-entering inventory after navigation never flashes cached stock or warning (%s)", async (locale) => {
    state.locale = locale;
    grant();
    fakeServer({ page: Promise.resolve({ ...resultPage, items: [item] }) });
    const firstVisit = mount();
    await screen.findByText(/PRIVATE_STOCK_ROW/);
    expect(readLiveStockWarmSnapshot("1:75:75", 101)?.items[0].id).toBe(41);
    firstVisit.unmount(); // Leaving the inventory route.

    const pendingReturn = deferred<unknown>();
    fakeServer({ page: pendingReturn.promise });
    mount(); // Returning to the inventory route with the same session.
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(document.querySelector('[data-live-authority="warmUnverified"]')).toBeNull();
    await waitFor(() => expect(state.authFetch.mock.calls.some(([url]) =>
      String(url).includes("/warehouse/inventory/cursor"))).toBe(true));
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    await act(async () => pendingReturn.resolve({
      ...resultPage, items: [{ ...item, name: "FRESH_RETURN_ROW" }],
    }));
    await screen.findByText(/FRESH_RETURN_ROW/);
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(document.querySelector("[data-live-authority]")).toBeNull();
  });

  it("on manual refresh hides the previous list until the new authorized read succeeds", async () => {
    grant();
    const next = deferred<unknown>();
    let reads = 0;
    state.authFetch.mockImplementation((url: string) => {
      const path = new URL(url, "https://localhost").pathname;
      if (path === "/warehouse/locations/selection") return Promise.resolve(warehousePage);
      if (path === "/warehouse/inventory/summary") return Promise.resolve({ stock_total: 10, alert_count: 0 });
      if (path === "/warehouse/inventory/cursor") return ++reads === 1
        ? Promise.resolve({ ...resultPage, items: [item] })
        : next.promise;
      throw Error("Unexpected " + path);
    });
    mount();
    await screen.findByText(/PRIVATE_STOCK_ROW/);
    fireEvent.click(screen.getByRole("button", { name: "Refresh witness" }));
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(document.querySelector('[data-live-authority="warmUnverified"]')).toBeNull();
    await waitFor(() => expect(reads).toBe(2));
    await act(async () => next.resolve({ ...resultPage, items: [{ ...item, name: "AFTER_REFRESH" }] }));
    await screen.findByText(/AFTER_REFRESH/);
  });

  it("reproduces and blocks PRIVATE rows and costs before new access admission", async () => {
    seed();
    const selection = deferred<unknown>();
    fakeServer({ selection: selection.promise });
    mount();
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(screen.queryByText(/123.000000/)).not.toBeInTheDocument();
    expect(document.querySelector('[data-live-authority="warmUnverified"]')).toBeNull();
  });

  it("never mounts cached stock after same-scope admission; only a new read may display rows", async () => {
    seed();
    const response = deferred<unknown>();
    fakeServer({ page: response.promise });
    const view = mount();
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    grant(); view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    await waitFor(() => expect(state.authFetch.mock.calls.some(([url]) =>
      String(url).includes("/warehouse/inventory/cursor"))).toBe(true));
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(document.querySelector('[data-live-authority="warmUnverified"]')).toBeNull();
    await act(async () => response.resolve({
      ...resultPage, items: [{ ...item, name: "FRESH_VERIFIED_ROW" }],
    }));
    await screen.findByText(/FRESH_VERIFIED_ROW/);
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(document.querySelector("[data-live-authority]")).toBeNull();
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
    state.errorStatus = 0; // network failure, not an authorization denial
    state.locationError = true; state.locationSuccess = false;
    view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("inventoryShell.accessRefreshFailed");
    expect(screen.getAllByRole("button", { name: "inventoryShell.retry" }).length).toBeGreaterThan(0);
    grant();
    state.locationError = false;
    view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    await waitFor(() => expect(state.authFetch.mock.calls.some(([url]) =>
      String(url).includes("/warehouse/inventory/cursor"))).toBe(true));
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


describe("in-flight admission and independent response ordering", () => {
  it.each(["page", "summary"])("rejects delayed %s and cache writes after known warehouse revocation", async (reader) => {
    const old = deferred<unknown>();
    fakeServer(reader === "page" ? { page: old.promise } : { summary: old.promise });
    grant(); const view = mount();
    const path = reader === "page" ? "/cursor?" : "/summary?";
    await waitFor(() => expect(state.authFetch.mock.calls.some(([u]) => String(u).includes(path))).toBe(true));
    state.permission = false; state.locationError = true; state.locationSuccess = false;
    view.rerender(<MemoryRouter><MainInventory /></MemoryRouter>);
    await act(async () => old.resolve(reader === "page"
      ? { ...resultPage, items: [item] } : { stock_total: 123, alert_count: 2 }));
    expect(screen.queryByTestId("live-stock")).not.toBeInTheDocument();
    expect(readLiveStockWarmSnapshot("1:75:75", 101)).toBeNull();
  });

  it.each(["company_id", "principal_id", "backoffice_user_id"])("discards both outstanding readers after %s storage switch", async (key) => {
    seed(); grant();
    const page = deferred<unknown>(), summary = deferred<unknown>();
    fakeServer({ page: page.promise, summary: summary.promise }); mount();
    await waitFor(() => expect(state.authFetch.mock.calls.filter(([u]) => String(u).includes("/inventory/")).length).toBeGreaterThanOrEqual(2));
    act(() => {
      localStorage.setItem(key, "999");
      window.dispatchEvent(new StorageEvent("storage", { key, newValue: "999" }));
    });
    await act(async () => {
      page.resolve({ ...resultPage, items: [item] });
      summary.resolve({ stock_total: 123, alert_count: 2 });
    });
    expect(screen.queryByTestId("live-stock")).not.toBeInTheDocument();
    expect(readLiveStockWarmSnapshot("1:75:75", 101)).toBeNull();
    expect(localStorage.getItem(key)).toBe("999");
  });

  it("keeps the new warehouse after late old-warehouse page and summary completions", async () => {
    grant(); const page = deferred<unknown>(), summary = deferred<unknown>();
    const second = { id: 102, name: "Warehouse 102", code: "W102" };
    state.authFetch.mockImplementation((url: string) => {
      const u = new URL(url, "https://localhost");
      if (u.pathname === "/warehouse/locations/selection") return Promise.resolve({
        ...warehousePage, items: [loc, second], total: 2,
      });
      if (u.pathname === "/warehouse/inventory/cursor") return u.searchParams.get("location_id") === "101"
        ? page.promise : Promise.resolve({ ...resultPage, items: [{ ...item, id: 42, name: "WAREHOUSE_102" }] });
      if (u.pathname === "/warehouse/inventory/summary") return u.searchParams.get("location_id") === "101"
        ? summary.promise : Promise.resolve({ stock_total: 7, alert_count: 0 });
      throw Error("unexpected " + url);
    });
    mount();
    await screen.findByRole("button", { name: "Switch warehouse witness" });
    await waitFor(() => expect(state.authFetch.mock.calls.some(([u]) => String(u).includes("/summary?"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Switch warehouse witness" }));
    await screen.findByText(/WAREHOUSE_102/);
    await screen.findByText("total=7");
    await act(async () => { page.resolve({ ...resultPage, items: [item] }); summary.resolve({ stock_total: 123, alert_count: 2 }); });
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(screen.getByText("total=7")).toBeInTheDocument();
    expect(readLiveStockWarmSnapshot("1:75:75", 102)?.items[0].id).toBe(42);
  });

  it.each(["en", "ar"])("does not revive cached rows when the independent summary resolves before the page (%s)", async (locale) => {
    state.locale = locale; seed(); grant();
    const page = deferred<unknown>();
    fakeServer({ page: page.promise }); mount();
    await screen.findByText("total=0");
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    expect(document.querySelector('[data-live-authority="warmUnverified"]')).toBeNull();
    await act(async () => page.resolve(resultPage));
    await waitFor(() => expect(document.querySelector("[data-live-authority]")).toBeNull());
    expect(screen.getByText("total=0")).toBeInTheDocument();
  });

  it("never lets a delayed pre-revocation Vehicle value replace a newer NO_ACCESS/null page", async () => {
    grant(); let reads = 0;
    const old = deferred<unknown>();
    state.authFetch.mockImplementation((url: string) => {
      const path = new URL(url, "https://localhost").pathname;
      if (path === "/warehouse/locations/selection") return Promise.resolve(warehousePage);
      if (path === "/warehouse/inventory/summary") return Promise.resolve({ stock_total: 1, alert_count: 0 });
      if (path === "/warehouse/inventory/cursor") return ++reads === 1 ? old.promise : Promise.resolve({
        ...resultPage, items: [{ ...item, name: "WAREHOUSE_NO_VEHICLE_READ", vehicle_quantity_scope: "NO_ACCESS", vehicle_quantity: null }],
      });
      throw Error("unexpected " + url);
    });
    mount();
    await screen.findByRole("button", { name: "Refresh witness" });
    await waitFor(() => expect(reads).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "Refresh witness" }));
    await screen.findByText(/WAREHOUSE_NO_VEHICLE_READ/);
    await act(async () => old.resolve({ ...resultPage, items: [{ ...item, vehicle_quantity: "32" }] }));
    expect(screen.queryByText(/PRIVATE_STOCK_ROW/)).not.toBeInTheDocument();
    const current = readLiveStockWarmSnapshot("1:75:75", 101)!.items[0];
    expect(current.vehicle_quantity_scope).toBe("NO_ACCESS");
    expect(current.vehicle_quantity).toBeNull();
    expect(current.on_hand_quantity).toBe("10");
  });
});
