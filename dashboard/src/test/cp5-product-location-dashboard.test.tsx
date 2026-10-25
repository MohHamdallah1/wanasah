import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CatalogVariant } from "@/features/catalog/contracts";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  navigate: vi.fn(),
  access: {
    permissions: new Set<string>(),
    isCompanyOwner: false,
  },
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  t: (key: string) => key,
  i18n: {
    language: "en",
    resolvedLanguage: "en",
    dir: () => "ltr" as const,
  },
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

vi.mock("@/hooks/useNetworkStatus", () => ({
  useNetworkStatus: () => true,
}));

vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    data: {
      company_id: 7,
      backoffice_user_id: 9,
      is_company_owner: mocks.access.isCompanyOwner,
    },
    isSuccess: true,
    isError: false,
    isCompanyOwner: mocks.access.isCompanyOwner,
    can: (code: string) => mocks.access.permissions.has(code),
    canAny: (code: string) => mocks.access.permissions.has(code),
  }),
}));

vi.mock("@/lib/durableOperations", () => ({
  durableScope: (...parts: unknown[]) => parts.join(":"),
  readDurableCommand: vi.fn(async () => null),
  getOrCreateDurableCommand: vi.fn(async (_scope: string, payload: unknown) => ({
    requestId: "11111111-1111-4111-8111-111111111111",
    payload,
    createdAt: 1,
  })),
  completeDurableOperation: vi.fn(),
  abandonDurableOperation: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

vi.mock("react-i18next", () => ({
  initReactI18next: {
    type: "3rdParty",
    init: () => undefined,
  },
  useTranslation: () => ({
    t: mocks.t,
    i18n: mocks.i18n,
  }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("@/pages/inventory/TabTransfers", () => ({ TabTransfers: () => null }));
vi.mock("@/pages/inventory/Tab3Stocktake", () => ({ Tab3Stocktake: () => null }));
vi.mock("@/pages/inventory/TabBatches", () => ({ TabBatches: () => null }));

import { ProductLocationManager } from "@/features/inventory/productLocations/ProductLocationManager";
import { ArchiveOwnerWorkspace } from "@/pages/inventory/archive/ArchiveOwnerWorkspace";

const variant = {
  id: 41,
  product_id: 4,
  sku: "SKU-41",
  gtin: null,
  name: "Product 41",
  base_uom: { id: 1, code: "EA", name: "Each" },
  quantity_scale: 0,
  quantity_step: "1",
  lot_control_mode: "OPTIONAL",
  expiry_control_mode: "OPTIONAL",
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  lifecycle_revision: 1,
  version: 2,
  published_at: null,
  retired_at: null,
  archived_at: null,
} as CatalogVariant;

const assignment = (overrides: Record<string, unknown> = {}) => ({
  id: 61,
  location: {
    id: 21,
    code: "WH-A",
    name: "Main Warehouse",
    location_type: "WAREHOUSE",
  },
  product_variant: {
    id: 41,
    sku: "SKU-41",
    name: "Product 41",
    lifecycle_status: "ACTIVE",
  },
  operational_flags: {
    inbound_enabled: true,
    outbound_enabled: true,
  },
  version: 3,
  created_by: 9,
  created_at: "2026-10-16T10:00:00Z",
  updated_at: "2026-10-16T10:00:00Z",
  ...overrides,
});

const page = (items: unknown[]) => ({
  items,
  next_cursor: null,
  has_more: false,
});

beforeEach(() => {
  mocks.authFetch.mockReset();
  mocks.navigate.mockReset();
  mocks.toastError.mockReset();
  mocks.toastSuccess.mockReset();
  mocks.access.permissions = new Set();
  mocks.access.isCompanyOwner = false;
});

afterEach(() => cleanup());

describe("CP5 ProductLocation capability closure", () => {
  it("lets a non-owner with read view assignments without mutation controls", async () => {
    mocks.access.permissions = new Set(["product_location.read"]);
    mocks.authFetch.mockResolvedValue(page([assignment()]));

    render(<ProductLocationManager variant={variant} locations={[]} />);
    expect(await screen.findByText("Main Warehouse")).toBeInTheDocument();
    const checks = screen.getAllByRole("checkbox");
    expect(checks).toHaveLength(2);
    expect(checks.every((item) => item.hasAttribute("disabled"))).toBe(true);
    expect(
      screen.queryByRole("button", {
        name: "catalogLifecycle.assignments.remove",
      }),
    ).not.toBeInTheDocument();
  });

  it("does not expose management when manage exists without read", async () => {
    mocks.access.permissions = new Set(["product_location.manage", "location.read"]);
    render(
      <ProductLocationManager
        variant={variant}
        locations={[{ id: 22, code: "WH-B", name: "Second Warehouse" }]}
      />,
    );
    expect(
      screen.queryByText("catalogLifecycle.assignments.title"),
    ).not.toBeInTheDocument();
    expect(mocks.authFetch).not.toHaveBeenCalled();
  });

  it("allows read plus manage to edit flags but requires location.read for candidate discovery", async () => {
    mocks.access.permissions = new Set([
      "product_location.read",
      "product_location.manage",
    ]);
    mocks.authFetch.mockResolvedValue(page([assignment()]));
    const { rerender } = render(
      <ProductLocationManager
        variant={variant}
        locations={[{ id: 22, code: "WH-B", name: "Second Warehouse" }]}
      />,
    );
    const inbound = (await screen.findAllByRole("checkbox"))[0];
    expect(inbound).not.toBeDisabled();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();

    mocks.access.permissions.add("location.read");
    mocks.authFetch.mockResolvedValue(page([]));
    rerender(
      <ProductLocationManager
        variant={variant}
        locations={[{ id: 22, code: "WH-B", name: "Second Warehouse" }]}
      />,
    );
    await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
  });

  it("uses canonical capabilities even when canonical Owner state is true", async () => {
    mocks.access.isCompanyOwner = true;
    mocks.access.permissions = new Set(["product_location.read"]);
    mocks.authFetch.mockResolvedValue(page([assignment()]));
    render(<ProductLocationManager variant={variant} locations={[]} />);
    const checks = await screen.findAllByRole("checkbox");
    expect(checks.every((item) => item.hasAttribute("disabled"))).toBe(true);
  });

  it("reloads after an authorized flag update, calls onChanged, and ignores refresh callback failure", async () => {
    mocks.access.permissions = new Set([
      "product_location.read",
      "product_location.manage",
    ]);
    const current = assignment();
    const changed = assignment({
      operational_flags: { inbound_enabled: false, outbound_enabled: true },
      version: 4,
    });
    mocks.authFetch
      .mockResolvedValueOnce(page([current]))
      .mockResolvedValueOnce({ message: "ok", product_location: changed })
      .mockResolvedValueOnce(page([changed]));
    const onChanged = vi.fn(async () => {
      throw new Error("parent refresh failed");
    });

    render(
      <ProductLocationManager
        variant={variant}
        locations={[]}
        onChanged={onChanged}
      />,
    );
    const inbound = (await screen.findAllByRole("checkbox"))[0];
    fireEvent.click(inbound);

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(mocks.authFetch).toHaveBeenCalledTimes(3);
    const patchCall = mocks.authFetch.mock.calls.find(
      ([path, options]) =>
        path === "/warehouse/product-locations/61" &&
        (options as RequestInit | undefined)?.method === "PATCH",
    );
    expect(patchCall).toBeTruthy();
    expect(JSON.parse(String((patchCall?.[1] as RequestInit).body))).toMatchObject({
      expected_version: 3,
      operational_flags: { inbound_enabled: false, outbound_enabled: true },
    });
    expect(mocks.toastError).not.toHaveBeenCalled();
  });

  it("preserves delete reason and expected version", async () => {
    mocks.access.permissions = new Set([
      "product_location.read",
      "product_location.manage",
    ]);
    mocks.authFetch
      .mockResolvedValueOnce(page([assignment()]))
      .mockResolvedValueOnce({
        message: "deleted",
        product_location_id: 61,
        location_id: 21,
      })
      .mockResolvedValueOnce(page([]));

    render(<ProductLocationManager variant={variant} locations={[]} />);
    const reason = await screen.findByPlaceholderText(
      "catalogLifecycle.assignments.removeReasonPlaceholder",
    );
    fireEvent.change(reason, { target: { value: "No longer stocked here" } });
    fireEvent.click(
      screen.getByRole("button", {
        name: "catalogLifecycle.assignments.remove",
      }),
    );

    await waitFor(() => {
      const deleteCall = mocks.authFetch.mock.calls.find(
        ([path, options]) =>
          path === "/warehouse/product-locations/61" &&
          (options as RequestInit | undefined)?.method === "DELETE",
      );
      expect(deleteCall).toBeTruthy();
      expect(JSON.parse(String((deleteCall?.[1] as RequestInit).body))).toMatchObject({
        expected_version: 3,
        location_id: 21,
        reason: "No longer stocked here",
      });
    });
  });

  it("keeps ProductLocation visible but disabled in the V1 Products row menu", () => {
    const actions = readFileSync(
      resolve(process.cwd(), "src/pages/products/list/ProductRowActions.tsx"),
      "utf8",
    );

    expect(actions).toContain("canViewProductLocations");
    expect(actions).toContain("catalogLifecycle.assignments.title");
    expect(actions).toContain("products.productLocationsV1Disabled");
    expect(actions).toContain("<DropdownMenuItem");
    expect(actions).toContain("disabled");
    expect(actions).not.toContain("onManageProductLocations(");
    expect(actions).toContain("<DropdownMenuTrigger asChild>");
    expect(actions).toContain("loop");
  });

  it("removes Inventory mutation UI and hands ProductLocation focus to Products", async () => {
    mocks.access.permissions = new Set(["product_location.read"]);
    render(
      <ArchiveOwnerWorkspace
        intent={{
          version: 1,
          kind: "owner-focus",
          tab: "warehouses",
          flow: "product-location",
          variantId: 41,
          operationId: 61,
          locationId: 21,
          reference: "assignment",
        }}
        onClose={vi.fn()}
        onOpenTransfers={vi.fn()}
        onOpenReservationOwner={vi.fn()}
        onInventoryChanged={vi.fn()}
      />,
    );
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "archiveOwners.actions.product-location",
      }),
    );
    expect(mocks.navigate).toHaveBeenCalledWith(
      "/products?productLocationVariantId=41&productLocationLocationId=21&productLocationAssignmentId=61",
    );
  });
});
