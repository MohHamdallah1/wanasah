import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  canAny: vi.fn<(code: string) => boolean>(),
  canAt: vi.fn<(code: string) => boolean>(),
  can: vi.fn<(code: string) => boolean>(),
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));
vi.mock("@/hooks/useInventoryAccess", () => ({
  parseInventoryLocationCapabilities: vi.fn(),
  useInventoryAccess: (locationId: number | null = null) => ({
    isSuccess: true,
    isPending: false,
    isError: false,
    can: locationId === null ? mocks.can : mocks.canAt,
    canAny: mocks.canAny,
    isCompanyOwner: false,
    data: { is_company_owner: false },
    refetch: vi.fn(),
  }),
}));
vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: () => undefined },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en", resolvedLanguage: "en", dir: () => "ltr" },
  }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), info: vi.fn() } }));

vi.mock("@/pages/inventory/InventoryTopDock", () => ({
  InventoryTopDock: ({ items, onChange }: {
    items: Array<{ id: string; label: string }>;
    onChange: (id: string) => void;
  }) => <nav>{items.map((item) =>
    <button key={item.id} onClick={() => onChange(item.id)}>{item.label}</button>,
  )}</nav>,
}));
vi.mock("@/pages/inventory/Tab1LiveStock", () => ({
  Tab1LiveStock: ({ locationId, locations, onLocationChange }: {
    locationId: number;
    locations: Array<{ id: number; name: string }>;
    onLocationChange: (id: string) => void;
  }) => <div data-testid="live-selected" data-id={locationId}>
    <select aria-label="live-warehouse" value={locationId}
      onChange={(event) => onLocationChange(event.target.value)}>
      {locations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select>
  </div>,
}));
vi.mock("@/pages/inventory/TabBatches", () => ({ TabBatches: () => null }));
vi.mock("@/pages/inventory/Tab2Inbound", () => ({ Tab2Inbound: () => null }));
vi.mock("@/pages/inventory/Tab3Stocktake", () => ({ Tab3Stocktake: () => null }));
vi.mock("@/pages/inventory/Tab4Ledger", () => ({ Tab4Ledger: () => null }));
vi.mock("@/pages/inventory/TabWarehouseLocations", () => ({
  TabWarehouseLocations: () => <div data-testid="warehouse-management" />,
}));
vi.mock("@/pages/inventory/TabTransfers", () => ({ TabTransfers: () => null }));
vi.mock("@/pages/inventory/TabInventoryAccess", () => ({ TabInventoryAccess: () => null }));
vi.mock("@/pages/inventory/archive/ArchiveOwnerWorkspace", () => ({
  ArchiveOwnerWorkspace: () => null,
}));

import MainInventory from "@/pages/inventory/MainInventory";
import { clearInventoryWarmScope } from "@/pages/inventory/inventorySessionCache";

const option = (id: number) => ({ id, name: `Warehouse ${id}`, code: `WH-${id}` });
const page = (
  ids: number[],
  next_cursor: string | null = null,
  selected: ReturnType<typeof option> | null = null,
) => ({
  items: ids.map(option),
  next_cursor,
  has_more: next_cursor !== null,
  selected,
  total: null,
});
const setup = (count: number, canCreate = false) => ({
  warehouse_ready: count > 0,
  active_warehouse_count: count,
  accessible_warehouse_count: count,
  can_create: canCreate,
});
const renderInventory = () => render(<MemoryRouter><MainInventory /></MemoryRouter>);

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("company_id", "1");
  localStorage.setItem("backoffice_user_id", "75");
  localStorage.setItem("principal_id", "75");
  mocks.authFetch.mockReset();
  mocks.canAny.mockReset();
  mocks.canAt.mockReset();
  mocks.can.mockReset();
  mocks.canAny.mockImplementation((code) => code === "inventory.read");
  mocks.canAt.mockImplementation((code) => code === "inventory.read");
  mocks.can.mockReturnValue(false);
});

afterEach(() => {
  cleanup();
  clearInventoryWarmScope("1:75");
});

describe("inventory scoped warehouse discovery integration", () => {
  it("allows inventory-only users to select warehouse 201 without requesting location management", async () => {
    mocks.authFetch.mockImplementation((url: string) => {
      const parsed = new URL(url, "http://test.local");
      if (parsed.pathname === "/warehouse/locations/selection") {
        const cursor = parsed.searchParams.get("cursor");
        const selected = parsed.searchParams.get("selected_location_id");
        const verified = selected ? option(Number(selected)) : null;
        if (cursor === "next2") return Promise.resolve(page([201], null, verified));
        if (cursor === "next1") return Promise.resolve(page([101, 102], "next2", verified));
        return Promise.resolve(page([1, 2], "next1", verified));
      }
      if (parsed.pathname === "/warehouse/inventory/cursor") {
        return Promise.resolve({ items: [], next_cursor: null, has_more: false, total: null });
      }
      if (parsed.pathname === "/warehouse/inventory/summary") {
        return Promise.resolve({ stock_total: 0, alert_count: 0 });
      }
      throw Error(`unexpected endpoint ${parsed.pathname}`);
    });

    renderInventory();
    const selector = await screen.findByRole("combobox", { name: "live-warehouse" });
    expect(selector).toHaveValue("1");
    fireEvent.click(screen.getByRole("button", { name: "inventoryShell.nextWarehouses" }));
    await screen.findByRole("option", { name: "Warehouse 101" });
    expect(selector).toHaveValue("1");
    fireEvent.click(screen.getByRole("button", { name: "inventoryShell.nextWarehouses" }));
    await waitFor(() => expect(screen.getByRole("option", { name: "Warehouse 201" })).toBeInTheDocument());
    fireEvent.change(selector, { target: { value: "201" } });
    expect(selector).toHaveValue("201");
    expect(localStorage.getItem("inventory_selected_location:1")).toBe("201");

    expect(mocks.authFetch.mock.calls.map(([url]) => String(url))).not.toEqual(
      expect.arrayContaining([expect.stringContaining("/warehouse/locations?")]),
    );
    expect(mocks.authFetch.mock.calls.map(([url]) => String(url))).not.toEqual(
      expect.arrayContaining([expect.stringContaining("/warehouse/setup-status")]),
    );
  });

  it("restores a far-page selection only when the backend returns it as authorized", async () => {
    localStorage.setItem("inventory_selected_location:1", "201");
    mocks.authFetch.mockImplementation((url: string) => {
      const parsed = new URL(url, "http://test.local");
      if (parsed.pathname === "/warehouse/locations/selection") {
        return Promise.resolve(page([1, 2], "next1", option(201)));
      }
      if (parsed.pathname === "/warehouse/inventory/cursor") {
        return Promise.resolve({ items: [], next_cursor: null, has_more: false, total: null });
      }
      if (parsed.pathname === "/warehouse/inventory/summary") {
        return Promise.resolve({ stock_total: 0, alert_count: 0 });
      }
      throw Error(`unexpected endpoint ${parsed.pathname}`);
    });
    renderInventory();
    expect(await screen.findByRole("combobox", { name: "live-warehouse" })).toHaveValue("201");
    expect(screen.getByRole("option", { name: "Warehouse 201" })).toBeInTheDocument();
    expect(mocks.authFetch.mock.calls.some(([url]) =>
      String(url).includes("selected_location_id=201"),
    )).toBe(true);
  });

  it("removes a revoked selection after a server rejection", async () => {
    let authorized = true;
    mocks.authFetch.mockImplementation((url: string) => {
      const parsed = new URL(url, "http://test.local");
      if (parsed.pathname === "/warehouse/locations/selection") {
        return authorized
          ? Promise.resolve(page([1], "next1"))
          : Promise.reject(Object.assign(new Error("revoked"), { status: 403 }));
      }
      if (parsed.pathname === "/warehouse/inventory/cursor") {
        return Promise.resolve({ items: [], next_cursor: null, has_more: false, total: null });
      }
      if (parsed.pathname === "/warehouse/inventory/summary") {
        return Promise.resolve({ stock_total: 0, alert_count: 0 });
      }
      throw Error("unexpected endpoint");
    });
    renderInventory();
    expect(await screen.findByRole("combobox", { name: "live-warehouse" })).toHaveValue("1");
    authorized = false;
    fireEvent.click(screen.getByRole("button", { name: "inventoryShell.nextWarehouses" }));
    await waitFor(() =>
      expect(screen.getByText("inventoryShell.locationsLoadTitle")).toBeInTheDocument(),
    );
    expect(localStorage.getItem("inventory_selected_location:1")).toBeNull();
    expect(screen.queryByRole("option", { name: "Warehouse 1" })).not.toBeInTheDocument();
  });

  it("preserves warehouse setup for location.read-only users", async () => {
    mocks.canAny.mockImplementation((code) => code === "location.read");
    mocks.canAt.mockImplementation((code) => code === "location.read");
    mocks.authFetch.mockImplementation((url: string) => {
      const path = new URL(url, "http://test.local").pathname;
      if (path === "/warehouse/locations/selection") return Promise.resolve(page([], null));
      if (path === "/warehouse/setup-status") return Promise.resolve(setup(0, true));
      throw Error("unpermitted inventory endpoint");
    });
    renderInventory();
    expect(await screen.findByTestId("warehouse-management")).toBeInTheDocument();
    expect(mocks.authFetch.mock.calls.some(([url]) =>
      String(url).includes("/warehouse/inventory/"),
    )).toBe(false);
    expect(mocks.authFetch.mock.calls.some(([url]) =>
      String(url).includes("/warehouse/setup-status"),
    )).toBe(true);
  });
});
