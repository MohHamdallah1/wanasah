import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const MANAGE = "inventory.minimum_stock.manage";
const READ = "inventory.read";
const LOCATION_READ = "location.read";
const LOCATION = 55;

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  translate: (key: string) => key,
  toastError: vi.fn(),
  toastInfo: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({
      t: mocks.translate,
      i18n: {
        dir: () => "ltr",
        resolvedLanguage: "en",
        language: "en",
      },
    }),
  };
});

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    info: mocks.toastInfo,
    success: mocks.toastSuccess,
  },
}));

vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, children }: { isOpen: boolean; children: React.ReactNode }) =>
    isOpen ? <div>{children}</div> : null,
}));

vi.mock("@/pages/inventory/warehouse-locations/BranchManagementModal", () => ({
  BranchManagementModal: () => null,
}));

vi.mock("@/pages/inventory/warehouse-locations/BranchSelector", () => ({
  BranchSelector: () => null,
}));

vi.mock("@/pages/inventory/warehouse-locations/QualityHandlingDestinationsCard", () => ({
  QualityHandlingDestinationsCard: () => null,
}));

import { beginDashboardSession } from "@/lib/authStorage";
import { StockMinimumManager } from "@/pages/inventory/StockMinimumManager";
import { TabWarehouseLocations } from "@/pages/inventory/TabWarehouseLocations";

type AccessState = {
  owner: boolean;
  manage: boolean;
  readableLocations: Set<number>;
};

const accessState: AccessState = {
  owner: false,
  manage: true,
  readableLocations: new Set([LOCATION]),
};

const warehousePage = {
  items: [
    {
      id: LOCATION,
      name: "Main warehouse",
      code: "MAIN",
      address: null,
      location_link: null,
      latitude: null,
      longitude: null,
      branch_id: null,
      branch_name: null,
      is_active: true,
      version: 1,
      created_at: "2026-10-01T00:00:00Z",
      updated_at: "2026-10-01T00:00:00Z",
    },
  ],
  next_cursor: null,
  has_more: false,
  total: 1,
};

const accessPayload = (locationId: number | null) => ({
  company_id: 77,
  principal_id: 101,
  backoffice_user_id: 202,
  is_company_owner: accessState.owner,
  location_id: locationId,
  permissions: accessState.manage ? [MANAGE] : [],
  any_permissions: accessState.readableLocations.size > 0 ? [LOCATION_READ] : [],
  location_permissions:
    locationId !== null && accessState.readableLocations.has(locationId)
      ? [READ]
      : [],
});

const installWarehouseFetch = () => {
  mocks.authFetch.mockImplementation(async (url: string, opts?: RequestInit) => {
    if (url === "/inventory/access/me") return accessPayload(null);
    if (url.startsWith("/inventory/access/me?location_id=")) {
      const locationId = Number(new URLSearchParams(url.split("?")[1]).get("location_id"));
      return accessPayload(locationId);
    }
    if (url === "/inventory/access/locations/capabilities") {
      const ids = JSON.parse(String(opts?.body)).location_ids as number[];
      return {
        locations: Object.fromEntries(ids.map((id) => {
          const codes: string[] = [];
          if (accessState.manage) codes.push(MANAGE);
          if (accessState.readableLocations.has(id)) codes.push(READ);
          return [String(id), codes];
        })),
      };
    }
    if (url.startsWith("/warehouse/locations/manage?")) return warehousePage;
    throw new Error(`Unexpected request: ${url}`);
  });
};

const renderWarehouses = (selectedLocationId: number | null = LOCATION) => {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <TabWarehouseLocations
        selectedLocationId={selectedLocationId}
        onLocationsChanged={vi.fn()}
        onMinimumApplied={vi.fn()}
      />
    </QueryClientProvider>,
  );
};

const minimumResponse = {
  location_id: LOCATION,
  scope: "ALL",
  family_ids: [],
  product_variant_ids: [],
  minimum_quantity: "10",
  unit_mode: "DISPLAY_UOM_PER_PRODUCT",
  apply_mode: "OVERWRITE",
  matched_count: 1,
  affected_count: 0,
  skipped_existing_count: 0,
  inactive_conflict_count: 0,
  target_conflict_count: 0,
  invalid_quantity_count: 0,
  conflict_samples: {
    inactive: [],
    target: [],
    invalid_quantity: [],
  },
};

const applyCalls = () =>
  mocks.authFetch.mock.calls.filter(
    ([url]) => url === "/warehouse/inventory/minimum-stock/bulk",
  );

describe("CP6 minimum-stock Dashboard parity", () => {
  beforeEach(() => {
    localStorage.clear();
    beginDashboardSession();
    localStorage.setItem("admin_token", "cp6-test-access");
    localStorage.setItem("company_id", "77");
    localStorage.setItem("principal_id", "101");
    localStorage.setItem("backoffice_user_id", "202");
    accessState.owner = false;
    accessState.manage = true;
    accessState.readableLocations = new Set([LOCATION]);
    mocks.authFetch.mockReset();
    mocks.toastError.mockReset();
    mocks.toastInfo.mockReset();
    mocks.toastSuccess.mockReset();
  });

  it("allows a non-owner only with manage plus read at the exact selected warehouse and reflects revocation", async () => {
    installWarehouseFetch();
    renderWarehouses();

    expect(
      await screen.findByRole("button", { name: "inventoryMinimum.button" }),
    ).toBeTruthy();
    expect(accessState.owner).toBe(false);

    accessState.readableLocations = new Set([56]);
    act(() => window.dispatchEvent(new Event("inventory-permission-denied")));
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "inventoryMinimum.button" }),
      ).toBeNull();
    });

    accessState.readableLocations = new Set([LOCATION]);
    accessState.manage = false;
    act(() => window.dispatchEvent(new Event("inventory-permission-denied")));
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "inventoryMinimum.button" }),
      ).toBeNull();
    });

    accessState.owner = true;
    act(() => window.dispatchEvent(new Event("inventory-permission-denied")));
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "inventoryMinimum.button" }),
      ).toBeNull();
    });

    accessState.manage = true;
    act(() => window.dispatchEvent(new Event("inventory-permission-denied")));
    expect(
      await screen.findByRole("button", { name: "inventoryMinimum.button" }),
    ).toBeTruthy();
  });

  it("does not falsely call zero active catalog products 'already configured'", async () => {
    mocks.authFetch.mockResolvedValue({ ...minimumResponse, matched_count: 0, affected_count: 0 });
    const onApplied = vi.fn();
    render(
      <StockMinimumManager
        locations={[{ id: LOCATION, name: "Main warehouse", code: "MAIN" }]}
        preferredLocationId={LOCATION}
        onApplied={onApplied}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "inventoryMinimum.button" }));
    expect(screen.getByText("inventoryMinimum.scopeAllHint")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "inventoryMinimum.apply" }));
    await waitFor(() => expect(applyCalls()).toHaveLength(1));
    expect(mocks.toastError).toHaveBeenCalledWith("inventoryMinimum.noActiveProducts");
    expect(mocks.toastInfo).not.toHaveBeenCalledWith("inventoryMinimum.noChangesSame");
    expect(mocks.toastSuccess).not.toHaveBeenCalled();
    expect(onApplied).not.toHaveBeenCalled();
  });

  it("distinguishes truly unchanged catalog products from zero matches", async () => {
    mocks.authFetch.mockResolvedValue(minimumResponse);
    render(
      <StockMinimumManager
        locations={[{ id: LOCATION, name: "Main warehouse", code: "MAIN" }]}
        preferredLocationId={LOCATION}
        onApplied={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "inventoryMinimum.button" }));
    fireEvent.click(screen.getByRole("button", { name: "inventoryMinimum.apply" }));
    await waitFor(() => expect(mocks.toastInfo).toHaveBeenCalledWith("inventoryMinimum.noChangesSame"));
    expect(mocks.toastError).not.toHaveBeenCalled();
  });

  it("retries an ambiguous apply with the same payload and request_id, then rotates the id after confirmed success", async () => {
    let attempt = 0;
    mocks.authFetch.mockImplementation(async (url: string) => {
      if (url !== "/warehouse/inventory/minimum-stock/bulk") {
        throw new Error(`Unexpected request: ${url}`);
      }
      attempt += 1;
      if (attempt === 1) throw new TypeError("simulated lost response");
      return minimumResponse;
    });

    render(
      <StockMinimumManager
        locations={[{ id: LOCATION, name: "Main warehouse", code: "MAIN" }]}
        preferredLocationId={LOCATION}
        onApplied={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "inventoryMinimum.button" }));

    const applyButton = await screen.findByRole("button", {
      name: "inventoryMinimum.apply",
    });
    fireEvent.click(applyButton);
    await waitFor(() => expect(applyCalls()).toHaveLength(1));

    fireEvent.click(applyButton);
    await waitFor(() => expect(applyCalls()).toHaveLength(2));

    const firstBody = JSON.parse(String(applyCalls()[0][1]?.body));
    const retryBody = JSON.parse(String(applyCalls()[1][1]?.body));
    expect(retryBody).toEqual(firstBody);
    expect(firstBody).toMatchObject({
      location_id: LOCATION,
      scope: "ALL",
      family_ids: [],
      product_variant_ids: [],
      minimum_quantity: "10",
      apply_mode: "OVERWRITE",
    });

    fireEvent.click(applyButton);
    await waitFor(() => expect(applyCalls()).toHaveLength(3));
    const nextBody = JSON.parse(String(applyCalls()[2][1]?.body));
    expect(nextBody.request_id).not.toBe(retryBody.request_id);
    expect({ ...nextBody, request_id: retryBody.request_id }).toEqual(retryBody);
  });

  it("keeps the manager simple: scope, UOM hint, safe overwrite contract, and business-error path", () => {
    const read = (path: string) =>
      readFileSync(resolve(process.cwd(), "src", path), "utf8");
    const manager = read("pages/inventory/StockMinimumManager.tsx");
    const warehouses = read("pages/inventory/TabWarehouseLocations.tsx");
    const live = read("pages/inventory/Tab1LiveStock.tsx");

    expect(manager.match(/export function StockMinimumManager/g)).toHaveLength(1);
    expect(warehouses).toContain('import { StockMinimumManager } from "./StockMinimumManager"');
    expect(live).not.toContain("StockMinimumManager");
    expect(manager).toContain('["ALL", "scopeAll"]');
    expect(manager).toContain('["FAMILY", "scopeFamily"]');
    expect(manager).toContain('["PRODUCT", "scopeProduct"]');
    expect(manager).toContain('apply_mode: "OVERWRITE" as const');
    expect(manager).not.toContain("applyMode");
    expect(manager).toContain('t("inventoryMinimum.unitHint")');
    expect(manager).toContain("apiErrorMessage(");
    expect(warehouses).toContain('canAt(item.id, "inventory.minimum_stock.manage")');
    expect(warehouses).toContain('canAt(item.id, "inventory.read")');
  });
});
describe("minimum picker physical-custody contract", () => {
  const row = {
    "id": 7,
    "name": "Warehouse-only stock",
    "sku": "PHYSICAL-7",
    "product_id": 3,
    "family_name": "Family",
    "base_uom_id": 1,
    "base_uom_code": "EA",
    "base_uom_name": "Each",
    "display_uom_id": 1,
    "display_uom_code": "EA",
    "display_uom_name": "Each",
    "display_factor_to_base": "1",
    "currency_code": "JOD",
    "average_cost_display": null,
    "last_purchase_cost": null,
    "last_purchase_uom_code": null,
    "last_purchase_date": null,
    "quantity_scale": 0,
    "quantity_step": "1",
    "on_hand_quantity": "32",
    "reserved_quantity": "3",
    "available_for_sale_quantity": "27",
    "unavailable_quantity": "2",
    "vehicle_quantity_scope": "NO_ACCESS",
    "vehicle_quantity": null,
    "recalled_quantity": "0",
    "available_quantity": "27",
    "blocked_quantity": "2",
    "total_quantity_scope": "WAREHOUSE_PHYSICAL",
    "total_quantity": "32",
    "damaged_quantity": "1",
    "minimum_quantity": "10",
    "is_low_stock": false
  };
  const renderPicker = async () => {
    render(<StockMinimumManager locations={[{ id: LOCATION, name: "Main warehouse", code: "MAIN" }]}
      preferredLocationId={LOCATION} onApplied={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "inventoryMinimum.button" }));
    fireEvent.click(await screen.findByRole("button", { name: "inventoryMinimum.scopeProduct" }));
  };
  it("keeps warehouse-only product selection available with NO_ACCESS/null", async () => {
    mocks.authFetch.mockResolvedValue({ items: [row], has_more: false, next_cursor: null, total: 1, alert_count: 0, alert_samples: [] });
    await renderPicker();
    const option = await screen.findByRole("button", { name: /Warehouse-only stock/ });
    fireEvent.click(option);
    expect(option).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("shows a real contract error instead of no-results and recovers on explicit retry", async () => {
    let malformed = true;
    mocks.authFetch.mockImplementation(async () => ({
      items: [{ ...row, vehicle_quantity: malformed ? "0" : null }],
      has_more: false, next_cursor: null, total: 1, alert_count: 0, alert_samples: [],
    }));
    await renderPicker();
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.queryByText("inventoryMinimum.noResults")).toBeNull();
    malformed = false;
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(await screen.findByRole("button", { name: /Warehouse-only stock/ })).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
