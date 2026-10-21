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
      t: (key: string) => key,
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
    localStorage.setItem("company_id", "77");
    localStorage.setItem("principal_id", "101");
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