import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const LOCATION = 55;
const BRANCH = 7;

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
  toastSuccess: vi.fn(),
  owner: false,
  companyCaps: new Set<string>(),
  anyCaps: new Set<string>(),
  locationCaps: new Map<number, Set<string>>(),
}));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: (locationId?: number | null) => ({
    isCompanyOwner: mocks.owner,
    can: (code: string) =>
      mocks.companyCaps.has(code) ||
      (locationId != null && mocks.locationCaps.get(locationId)?.has(code) === true),
    canAny: (code: string) =>
      mocks.companyCaps.has(code) || mocks.anyCaps.has(code),
  }),
  useLocationCapabilities: () => (locationId: number, code: string) =>
    mocks.locationCaps.get(locationId)?.has(code) === true,
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
  Modal: ({
    isOpen,
    title,
    children,
  }: {
    isOpen: boolean;
    title: string;
    children: React.ReactNode;
  }) => isOpen ? <div role="dialog" aria-label={title}>{children}</div> : null,
}));

vi.mock("@/pages/inventory/warehouse-locations/QualityHandlingDestinationsCard", () => ({
  QualityHandlingDestinationsCard: () => null,
}));

vi.mock("@/pages/inventory/StockMinimumManager", () => ({
  StockMinimumManager: () => <button type="button">minimum-stock-manager</button>,
}));

import { TabWarehouseLocations } from "@/pages/inventory/TabWarehouseLocations";
import { BranchManagementModal } from "@/pages/inventory/warehouse-locations/BranchManagementModal";
import { BranchSelector } from "@/pages/inventory/warehouse-locations/BranchSelector";

const branch = {
  id: BRANCH,
  name: "Amman Branch",
  code: "AMMAN",
  is_active: true,
  created_at: "2026-10-01T00:00:00Z",
};

const warehouse = {
  id: LOCATION,
  name: "Main warehouse",
  code: "MAIN",
  branch_id: BRANCH,
  branch_name: branch.name,
  is_active: true,
  version: 1,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const branchPage = {
  items: [branch],
  next_cursor: null,
  has_more: false,
  total: 1,
};

const warehousePage = {
  items: [warehouse],
  next_cursor: null,
  has_more: false,
  total: 1,
};

const installFetch = () => {
  mocks.authFetch.mockImplementation(async (url: string, opts?: RequestInit) => {
    if (url.startsWith("/warehouse/branches/manage?")) return branchPage;
    if (url.startsWith("/warehouse/branches/options?")) return branchPage;
    if (url.startsWith("/warehouse/locations/manage?")) return warehousePage;

    if (url === "/warehouse/branches" && opts?.method === "POST") {
      return { message: "created", branch };
    }
    if (url === `/warehouse/branches/${BRANCH}` && opts?.method === "PATCH") {
      return { message: "updated", branch: { ...branch, name: "Amman Branch 2" } };
    }
    if (url === `/warehouse/branches/${BRANCH}/deactivate` && opts?.method === "POST") {
      return { message: "deactivated", branch: { ...branch, is_active: false } };
    }
    if (url === "/warehouse/locations" && opts?.method === "POST") {
      return {
        message: "created",
        location: { ...warehouse, branch_id: null, branch_name: null },
      };
    }
    if (url === `/warehouse/locations/${LOCATION}` && opts?.method === "PATCH") {
      return {
        message: "updated",
        location: { ...warehouse, name: "Renamed warehouse" },
      };
    }
    throw new Error(`Unexpected request: ${url}`);
  });
};

const branchCalls = (prefix: string) =>
  mocks.authFetch.mock.calls.filter(([url]) => String(url).startsWith(prefix));

const renderBranchModal = () => render(
  <BranchManagementModal
    isOpen
    onClose={vi.fn()}
    onBranchesChanged={vi.fn()}
  />,
);

const renderWarehouses = (selectedLocationId: number | null = null) => render(
  <TabWarehouseLocations
    selectedLocationId={selectedLocationId}
    onLocationsChanged={vi.fn()}
    onMinimumApplied={vi.fn()}
  />,
);

describe("CP4 Branch Dashboard capability parity", () => {
  beforeEach(() => {
    mocks.owner = false;
    mocks.companyCaps.clear();
    mocks.anyCaps.clear();
    mocks.locationCaps.clear();
    mocks.authFetch.mockReset();
    mocks.toastError.mockReset();
    mocks.toastInfo.mockReset();
    mocks.toastSuccess.mockReset();
    installFetch();
  });

  it("lets a non-owner with branch.read reach and list branch management without location.read", async () => {
    mocks.companyCaps.add("branch.read");
    renderWarehouses();

    const manage = screen.getByRole("button", { name: "إدارة الفروع" });
    expect(manage).toBeTruthy();
    expect(mocks.owner).toBe(false);
    expect(branchCalls("/warehouse/locations/manage?")).toHaveLength(0);

    fireEvent.click(manage);
    expect(await screen.findByText(branch.name)).toBeTruthy();
    expect(branchCalls("/warehouse/branches/manage?")).toHaveLength(1);
  });

  it("does not treat CompanyOwner status as branch authority", () => {
    mocks.owner = true;
    renderWarehouses();
    expect(screen.queryByRole("button", { name: "إدارة الفروع" })).toBeNull();
  });

  it("keeps branch.read read-only when create/update/state are absent", async () => {
    mocks.companyCaps.add("branch.read");
    renderBranchModal();
    await screen.findByText(branch.name);

    expect(screen.getByRole("button", { name: "فرع جديد" })).toBeDisabled();
    expect(screen.getByTitle("تعديل")).toBeDisabled();
    expect(screen.getByTitle("تعطيل")).toBeDisabled();
  });

  it("branch.create controls create only", async () => {
    mocks.companyCaps.add("branch.read");
    mocks.companyCaps.add("branch.create");
    renderBranchModal();
    await screen.findByText(branch.name);

    expect(screen.getByRole("button", { name: "فرع جديد" })).toBeEnabled();
    expect(screen.getByTitle("تعديل")).toBeDisabled();
    expect(screen.getByTitle("تعطيل")).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "فرع جديد" }));
    const inputs = screen.getAllByRole("textbox");
    fireEvent.change(inputs[0], { target: { value: "New Branch" } });
    fireEvent.change(inputs[1], { target: { value: "NEW" } });
    fireEvent.click(screen.getByRole("button", { name: "حفظ" }));

    await waitFor(() =>
      expect(
        mocks.authFetch.mock.calls.some(
          ([url, opts]) => url === "/warehouse/branches" && opts?.method === "POST",
        ),
      ).toBe(true),
    );
    const call = mocks.authFetch.mock.calls.find(
      ([url, opts]) => url === "/warehouse/branches" && opts?.method === "POST",
    );
    expect(call).toBeTruthy();
    expect(call?.[1]?.method).toBe("POST");
  });

  it("branch.update controls edit only", async () => {
    mocks.companyCaps.add("branch.read");
    mocks.companyCaps.add("branch.update");
    renderBranchModal();
    await screen.findByText(branch.name);

    expect(screen.getByRole("button", { name: "فرع جديد" })).toBeDisabled();
    expect(screen.getByTitle("تعديل")).toBeEnabled();
    expect(screen.getByTitle("تعطيل")).toBeDisabled();

    fireEvent.click(screen.getByTitle("تعديل"));
    const inputs = screen.getAllByRole("textbox");
    fireEvent.change(inputs[0], { target: { value: "Amman Branch 2" } });
    fireEvent.click(screen.getByRole("button", { name: "حفظ" }));

    await waitFor(() =>
      expect(branchCalls(`/warehouse/branches/${BRANCH}`)).toHaveLength(1),
    );
    expect(branchCalls(`/warehouse/branches/${BRANCH}`)[0][1]?.method).toBe("PATCH");
  });

  it("branch.state controls activate/deactivate only", async () => {
    mocks.companyCaps.add("branch.read");
    mocks.companyCaps.add("branch.state");
    renderBranchModal();
    await screen.findByText(branch.name);

    expect(screen.getByRole("button", { name: "فرع جديد" })).toBeDisabled();
    expect(screen.getByTitle("تعديل")).toBeDisabled();
    expect(screen.getByTitle("تعطيل")).toBeEnabled();

    fireEvent.click(screen.getByTitle("تعطيل"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "audit reason" } });
    fireEvent.click(screen.getByRole("button", { name: "تأكيد التعطيل" }));

    await waitFor(() =>
      expect(branchCalls(`/warehouse/branches/${BRANCH}/deactivate`)).toHaveLength(1),
    );
    expect(branchCalls(`/warehouse/branches/${BRANCH}/deactivate`)[0][1]?.method).toBe("POST");
  });

  it("BranchSelector never discovers branches without branch.read and discovers them with it", async () => {
    const view = render(
      <BranchSelector
        value={BRANCH}
        currentLabel={branch.name}
        disabled={false}
        refreshKey={0}
        canReadBranches={false}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText(branch.name)).toBeTruthy();
    await waitFor(() => expect(branchCalls("/warehouse/branches/options?")).toHaveLength(0));

    view.rerender(
      <BranchSelector
        value={BRANCH}
        currentLabel={branch.name}
        disabled={false}
        refreshKey={0}
        canReadBranches
        onChange={vi.fn()}
      />,
    );
    await waitFor(() => expect(branchCalls("/warehouse/branches/options?")).toHaveLength(1));
    expect(screen.getByRole("combobox")).toBeTruthy();
  });

  it("warehouse create works without branch.read and keeps branch association null", async () => {
    mocks.companyCaps.add("location.create");
    renderWarehouses();

    fireEvent.click(screen.getByRole("button", { name: "مستودع جديد" }));
    expect(screen.getByText("غير مرتبط بفرع")).toBeTruthy();
    const dialog = screen.getByRole("dialog", { name: "إضافة مستودع" });
    const inputs = dialog.querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "New warehouse" } });
    fireEvent.change(inputs[1], { target: { value: "NEW-WH" } });
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));

    await waitFor(() => expect(branchCalls("/warehouse/locations")).toHaveLength(1));
    const create = mocks.authFetch.mock.calls.find(
      ([url, opts]) => url === "/warehouse/locations" && opts?.method === "POST",
    );
    expect(create).toBeTruthy();
    expect(JSON.parse(String(create?.[1]?.body))).toMatchObject({ branch_id: null });
    expect(branchCalls("/warehouse/branches/options?")).toHaveLength(0);
  });

  it("warehouse edit preserves its existing branch without branch.read", async () => {
    mocks.anyCaps.add("location.read");
    mocks.locationCaps.set(LOCATION, new Set(["location.update"]));
    renderWarehouses(LOCATION);

    expect(await screen.findByText("Main warehouse")).toBeTruthy();
    fireEvent.click(screen.getByTitle("تعديل"));
    expect(screen.getByText(branch.name)).toBeTruthy();
    expect(branchCalls("/warehouse/branches/options?")).toHaveLength(0);

    const dialog = screen.getByRole("dialog", { name: "تعديل المستودع" });
    const inputs = dialog.querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "Renamed warehouse" } });
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));

    await waitFor(() =>
      expect(
        mocks.authFetch.mock.calls.some(
          ([url, opts]) => url === `/warehouse/locations/${LOCATION}` && opts?.method === "PATCH",
        ),
      ).toBe(true),
    );
    const update = mocks.authFetch.mock.calls.find(
      ([url, opts]) => url === `/warehouse/locations/${LOCATION}` && opts?.method === "PATCH",
    );
    expect(JSON.parse(String(update?.[1]?.body))).not.toHaveProperty("branch_id");
  });

  it("keeps branch-only MainInventory reachability and CP6 minimum-stock gating exact", () => {
    const read = (path: string) => readFileSync(resolve(process.cwd(), "src", path), "utf8");
    const main = read("pages/inventory/MainInventory.tsx");
    const warehouses = read("pages/inventory/TabWarehouseLocations.tsx");
    const branchModal = read("pages/inventory/warehouse-locations/BranchManagementModal.tsx");

    expect(main).toContain("if (id === 'warehouses') return canAny('location.read') || can('branch.read');");
    expect(main).toContain("if (!canAny('location.read')) return;");
    expect(warehouses).toContain('const canReadBranches = access.can("branch.read")');
    expect(warehouses).not.toContain("access.isCompanyOwner && selectedLocationId");
    expect(branchModal).not.toContain("isCompanyOwner");

    expect(warehouses).toContain('access.can("inventory.minimum_stock.manage")');
    expect(warehouses).toContain('minimumStockAccess.can("inventory.read")');
  });
});
