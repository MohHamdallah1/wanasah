import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const LOCATION = 55;
const BRANCH = 7;
const OTHER_BRANCH = 8;

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
  toastSuccess: vi.fn(),
  owner: false,
  language: "ar",
  companyCaps: new Set<string>(),
  anyCaps: new Set<string>(),
  locationCaps: new Map<number, Set<string>>(),
}));

vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.authFetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: (locationId?: number | null) => ({
    isCompanyOwner: mocks.owner,
    can: (code: string) =>
      mocks.companyCaps.has(code) ||
      (locationId != null && mocks.locationCaps.get(locationId)?.has(code) === true),
    canAny: (code: string) => mocks.companyCaps.has(code) || mocks.anyCaps.has(code),
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
        dir: () => mocks.language === "ar" ? "rtl" : "ltr",
        resolvedLanguage: mocks.language,
        language: mocks.language,
      },
    }),
  };
});
vi.mock("sonner", () => ({
  toast: { error: mocks.toastError, info: mocks.toastInfo, success: mocks.toastSuccess },
}));
vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: React.ReactNode }) =>
    isOpen ? <div role="dialog" aria-label={title}>{children}</div> : null,
}));
vi.mock("@/pages/inventory/warehouse-locations/QualityHandlingDestinationsCard", () => ({
  QualityHandlingDestinationsCard: () => <div data-testid="quality-destinations-view">quality-destinations-view</div>,
}));
vi.mock("@/pages/inventory/StockMinimumManager", () => ({
  StockMinimumManager: () => <button type="button">minimum-stock-manager</button>,
}));

import { TabWarehouseLocations } from "@/pages/inventory/TabWarehouseLocations";
import { BranchManagementModal } from "@/pages/inventory/warehouse-locations/BranchManagementModal";
import { BranchSelector } from "@/pages/inventory/warehouse-locations/BranchSelector";

const branch = { id: BRANCH, name: "Amman Branch", code: "AMMAN", is_active: true, created_at: "2026-10-01T00:00:00Z" };
const otherBranch = { id: OTHER_BRANCH, name: "Irbid Branch", code: "IRBID", is_active: true, created_at: "2026-10-01T00:00:00Z" };
const warehouse = {
  id: LOCATION, name: "Main warehouse", code: "MAIN", branch_id: BRANCH, branch_name: branch.name,
  is_active: true, version: 1, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
};
const branchPage = { items: [branch], next_cursor: null, has_more: false, total: 1 };
const warehousePage = { items: [warehouse], next_cursor: null, has_more: false, total: 1 };

const installFetch = () => {
  mocks.authFetch.mockImplementation(async (url: string, opts?: RequestInit) => {
    if (url.startsWith("/warehouse/branches/manage?")) return branchPage;
    if (url.startsWith("/warehouse/branches/options?")) return branchPage;
    if (url.startsWith("/warehouse/locations/manage?")) return warehousePage;
    if (url === "/warehouse/branches" && opts?.method === "POST") return { message: "created", branch };
    if (url === `/warehouse/branches/${BRANCH}` && opts?.method === "PATCH") return { message: "updated", branch: { ...branch, name: "Amman Branch 2" } };
    if (url === `/warehouse/branches/${BRANCH}/deactivate` && opts?.method === "POST") return { message: "deactivated", branch: { ...branch, is_active: false } };
    if (url === "/warehouse/locations" && opts?.method === "POST") return { message: "created", location: { ...warehouse, branch_id: null, branch_name: null } };
    if (url === `/warehouse/locations/${LOCATION}` && opts?.method === "PATCH") return { message: "updated", location: { ...warehouse, name: "Renamed warehouse", version: 2 } };
    if (url === `/warehouse/locations/${LOCATION}/deactivate` && opts?.method === "POST") return { message: "deactivated", location: { ...warehouse, is_active: false, version: 2 } };
    throw new Error(`Unexpected request: ${url}`);
  });
};
const calls = (prefix: string) => mocks.authFetch.mock.calls.filter(([url]) => String(url).startsWith(prefix));
const exactCalls = (url: string, method?: string) => mocks.authFetch.mock.calls.filter(([calledUrl, opts]) =>
  calledUrl === url && (!method || opts?.method === method),
);
const renderBranchModal = () => render(<BranchManagementModal isOpen onClose={vi.fn()} onBranchesChanged={vi.fn()} />);
const renderWarehouses = (selectedLocationId: number | null = null) => render(
  <TabWarehouseLocations selectedLocationId={selectedLocationId} onLocationsChanged={vi.fn()} onMinimumApplied={vi.fn()} />,
);

const structuredError = (code: string, context: Record<string, unknown>) => Object.assign(
  new Error(code),
  { code, context, status: 409 },
);

describe("CP4 Warehouse/Branch Dashboard closure", () => {
  beforeEach(() => {
    mocks.owner = false;
    mocks.language = "ar";
    mocks.companyCaps.clear();
    mocks.anyCaps.clear();
    mocks.locationCaps.clear();
    mocks.authFetch.mockReset();
    mocks.toastError.mockReset();
    mocks.toastInfo.mockReset();
    mocks.toastSuccess.mockReset();
    installFetch();
  });

  it("keeps branch administration out of the warehouse page while preserving canonical branch gates", async () => {
    mocks.companyCaps.add("branch.read");
    const view = renderWarehouses();
    expect(screen.queryByRole("button", { name: "إدارة الفروع" })).toBeNull();
    expect(calls("/warehouse/branches/manage?")).toHaveLength(0);
    view.unmount();

    const readOnlyModal = renderBranchModal();
    await screen.findByText(branch.name);
    expect(screen.getByRole("button", { name: "فرع جديد" })).toBeDisabled();
    expect(screen.getByTitle("تعديل")).toBeDisabled();
    expect(screen.getByTitle("تعطيل")).toBeDisabled();
    readOnlyModal.unmount();

    mocks.companyCaps.add("branch.create");
    const modal = renderBranchModal();
    await screen.findByText(branch.name);
    expect(screen.getByRole("button", { name: "فرع جديد" })).toBeEnabled();
    expect(screen.getByTitle("تعديل")).toBeDisabled();
    modal.unmount();
  });

  it("shows only the first-warehouse start experience when the company has no warehouses", async () => {
    mocks.companyCaps.add("location.read");
    mocks.companyCaps.add("location.create");
    mocks.authFetch.mockImplementation(async (url: string) => {
      if (url.startsWith("/warehouse/locations/manage?")) {
        return { items: [], next_cursor: null, has_more: false, total: 0 };
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    renderWarehouses();
    const start = await screen.findByTestId("warehouse-first-empty");
    expect(start).toHaveTextContent("أنشئ أول مستودع");
    expect(start).toHaveTextContent("بعد إنشاء المستودع تصبح عمليات المستودع جاهزة للعمل.");
    expect(screen.queryByLabelText("بحث بالاسم أو الكود (حرفان على الأقل)")).toBeNull();
    expect(screen.queryByRole("button", { name: "إدارة الفروع" })).toBeNull();
    expect(screen.queryByRole("button", { name: "تحديث" })).toBeNull();
    expect(screen.queryByText("minimum-stock-manager")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "إنشاء أول مستودع" }));
    expect(screen.getByRole("dialog", { name: "إضافة مستودع" })).toBeTruthy();
  });

  it("opens quality destinations as a dedicated warehouse setup view and returns to warehouses", async () => {
    mocks.companyCaps.add("location.read");
    mocks.companyCaps.add("inventory.transfer_policy.manage");
    renderWarehouses();
    await screen.findByText("Main warehouse");

    expect(screen.queryByTestId("quality-destinations-view")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "وجهات الجودة" }));
    expect(screen.getByTestId("quality-destinations-view")).toBeTruthy();
    expect(screen.queryByLabelText("بحث بالاسم أو الكود (حرفان على الأقل)")).toBeNull();
    expect(screen.queryByRole("button", { name: "مستودع جديد" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "المستودعات" }));
    expect(screen.queryByTestId("quality-destinations-view")).toBeNull();
    expect(screen.getByLabelText("بحث بالاسم أو الكود (حرفان على الأقل)")).toBeTruthy();
  });

  it("never treats CompanyOwner as branch authority", () => {
    mocks.owner = true;
    renderWarehouses();
    expect(screen.queryByRole("button", { name: "إدارة الفروع" })).toBeNull();
  });

  it("supports keyboard submit and first useful focus in branch create", async () => {
    mocks.companyCaps.add("branch.read");
    mocks.companyCaps.add("branch.create");
    renderBranchModal();
    await screen.findByText(branch.name);
    fireEvent.click(screen.getByRole("button", { name: "فرع جديد" }));
    const inputs = screen.getAllByRole("textbox");
    expect(document.activeElement).toBe(inputs[0]);
    fireEvent.change(inputs[0], { target: { value: "New Branch" } });
    fireEvent.change(inputs[1], { target: { value: "NEW" } });
    fireEvent.submit(inputs[0].closest("form")!);
    await waitFor(() => expect(exactCalls("/warehouse/branches", "POST")).toHaveLength(1));
  });

  it("keeps BranchSelector discovery gated and preserves but cannot reselect an inactive current relation", async () => {
    const onChange = vi.fn();
    const view = render(
      <BranchSelector value={99} currentLabel="Inactive legacy branch" disabled={false} refreshKey={0} canReadBranches={false} onChange={onChange} />,
    );
    expect(screen.getByText("Inactive legacy branch")).toBeTruthy();
    expect(calls("/warehouse/branches/options?")).toHaveLength(0);

    view.rerender(
      <BranchSelector value={99} currentLabel="Inactive legacy branch" disabled={false} refreshKey={0} canReadBranches onChange={onChange} />,
    );
    await waitFor(() => expect(calls("/warehouse/branches/options?")).toHaveLength(1));
    const currentOption = screen.getByRole("option", { name: /Inactive legacy branch/ });
    expect(currentOption).toBeEnabled();

    view.rerender(
      <BranchSelector value={BRANCH} currentLabel="Inactive legacy branch" disabled={false} refreshKey={0} canReadBranches onChange={onChange} />,
    );
    expect(screen.getByRole("option", { name: /Inactive legacy branch/ })).toBeDisabled();
  });

  it("preserves existing branch on warehouse edit when branch.read is absent", async () => {
    mocks.anyCaps.add("location.read");
    mocks.locationCaps.set(LOCATION, new Set(["location.update"]));
    renderWarehouses(LOCATION);
    await screen.findByText("Main warehouse");
    fireEvent.click(screen.getByTitle("تعديل"));
    expect(calls("/warehouse/branches/options?")).toHaveLength(0);
    const dialog = screen.getByRole("dialog", { name: "تعديل المستودع" });
    const inputs = dialog.querySelectorAll("input");
    expect(document.activeElement).toBe(inputs[0]);
    fireEvent.change(inputs[0], { target: { value: "Renamed warehouse" } });
    fireEvent.submit(inputs[0].closest("form")!);
    await waitFor(() => expect(exactCalls(`/warehouse/locations/${LOCATION}`, "PATCH")).toHaveLength(1));
    const update = exactCalls(`/warehouse/locations/${LOCATION}`, "PATCH")[0];
    expect(JSON.parse(String(update[1]?.body))).not.toHaveProperty("branch_id");
  });

  it("surfaces deactivation blocker evidence without collapsing it to a generic failure", async () => {
    mocks.anyCaps.add("location.read");
    mocks.locationCaps.set(LOCATION, new Set(["location.state"]));
    mocks.authFetch.mockImplementation(async (url: string, opts?: RequestInit) => {
      if (url.startsWith("/warehouse/locations/manage?")) return warehousePage;
      if (url === `/warehouse/locations/${LOCATION}/deactivate` && opts?.method === "POST") {
        throw structuredError("LOCATION_DEACTIVATION_BLOCKED", {
          blocker_type: "OPEN_TRANSFER",
          reference_number: "TR-204",
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    renderWarehouses(LOCATION);
    await screen.findByText("Main warehouse");
    fireEvent.click(screen.getByTitle("تعطيل"));
    const dialog = screen.getByRole("dialog", { name: "تعطيل المستودع" });
    const reason = dialog.querySelector("textarea")!;
    fireEvent.change(reason, { target: { value: "planned shutdown" } });
    fireEvent.click(screen.getByRole("button", { name: "تأكيد التعطيل" }));
    expect(await screen.findByText("تعذر التعطيل: حوالة غير نهائية")).toBeTruthy();
    expect(screen.getByText("المرجع: TR-204")).toBeTruthy();
    expect(reason).toHaveValue("planned shutdown");
    expect(screen.getByRole("dialog", { name: "تعطيل المستودع" })).toBeTruthy();
  });

  it("recovers from LOCATION_VERSION_CONFLICT by refreshing while preserving input and requiring a fresh request", async () => {
    mocks.anyCaps.add("location.read");
    mocks.locationCaps.set(LOCATION, new Set(["location.update"]));
    const patchBodies: Array<Record<string, unknown>> = [];
    let pageVersion = 1;
    mocks.authFetch.mockImplementation(async (url: string, opts?: RequestInit) => {
      if (url.startsWith("/warehouse/locations/manage?")) {
        return { ...warehousePage, items: [{ ...warehouse, version: pageVersion }] };
      }
      if (url === `/warehouse/locations/${LOCATION}` && opts?.method === "PATCH") {
        const body = JSON.parse(String(opts.body));
        patchBodies.push(body);
        if (patchBodies.length === 1) {
          pageVersion = 2;
          throw structuredError("LOCATION_VERSION_CONFLICT", {
            resource_id: LOCATION,
            expected_version: 1,
            current_version: 2,
          });
        }
        return { message: "updated", location: { ...warehouse, name: body.name, version: 3 } };
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    renderWarehouses(LOCATION);
    await screen.findByText("Main warehouse");
    fireEvent.click(screen.getByTitle("تعديل"));
    const dialog = screen.getByRole("dialog", { name: "تعديل المستودع" });
    const name = dialog.querySelectorAll("input")[0];
    fireEvent.change(name, { target: { value: "Operator draft" } });
    fireEvent.submit(name.closest("form")!);
    expect(await screen.findByText(/تغيرت بيانات المستودع/)).toBeTruthy();
    expect(name).toHaveValue("Operator draft");
    expect(patchBodies).toHaveLength(1);

    fireEvent.submit(name.closest("form")!);
    await waitFor(() => expect(patchBodies).toHaveLength(2));
    expect(patchBodies[1].expected_version).toBe(2);
    expect(patchBodies[1].request_id).not.toBe(patchBodies[0].request_id);
  });

  it("keeps Branch discovery dormant in Warehouse V1 even when branch.read exists", async () => {
    mocks.anyCaps.add("location.read");
    mocks.companyCaps.add("branch.read");
    mocks.locationCaps.set(LOCATION, new Set(["location.update"]));
    let optionCalls = 0;
    const patchBodies: Array<Record<string, unknown>> = [];
    mocks.authFetch.mockImplementation(async (url: string, opts?: RequestInit) => {
      if (url.startsWith("/warehouse/locations/manage?")) return warehousePage;
      if (url.startsWith("/warehouse/branches/options?")) {
        optionCalls += 1;
        return { items: [branch, otherBranch], next_cursor: null, has_more: false, total: 2 };
      }
      if (url === `/warehouse/locations/${LOCATION}` && opts?.method === "PATCH") {
        const body = JSON.parse(String(opts.body));
        patchBodies.push(body);
        return { message: "updated", location: { ...warehouse, name: body.name, version: 2 } };
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    renderWarehouses(LOCATION);
    const warehouseName = await screen.findByText("Main warehouse");
    const warehouseRow = warehouseName.closest("tr");
    expect(warehouseRow).toBeTruthy();
    const editButton = warehouseRow!.querySelector("button");
    expect(editButton).toBeTruthy();
    fireEvent.click(editButton!);
    expect(optionCalls).toBe(0);
    expect(screen.queryByRole("combobox")).toBeNull();
    const dialog = screen.getByRole("dialog");
    const name = dialog.querySelectorAll("input")[0];
    fireEvent.change(name, { target: { value: "Updated warehouse" } });
    fireEvent.submit(name.closest("form")!);
    await waitFor(() => expect(patchBodies).toHaveLength(1));
    expect(patchBodies[0]).not.toHaveProperty("branch_id");
    expect(optionCalls).toBe(0);
  });

  it("keeps AR/EN direction, non-cascade wording, and CP6 gating exact", async () => {
    const read = (path: string) => readFileSync(resolve(process.cwd(), "src", path), "utf8");
    const warehouses = read("pages/inventory/TabWarehouseLocations.tsx");
    const branchModal = read("pages/inventory/warehouse-locations/BranchManagementModal.tsx");
    const branchI18n = read("pages/inventory/warehouse-locations/i18n.ts");
    const selector = read("pages/inventory/warehouse-locations/BranchSelector.tsx");
    expect(warehouses).toContain('apiErrorCode(error)');
    expect(warehouses).toContain('"LOCATION_DEACTIVATION_BLOCKED"');
    expect(warehouses).toContain('"LOCATION_VERSION_CONFLICT"');
    expect(warehouses).toContain('access.can("inventory.minimum_stock.manage")');
    expect(warehouses).toContain('minimumStockAccess.can("inventory.read")');
    expect(branchModal).toContain("copy.nonCascade");
    expect(branchI18n).toContain('nonCascade: "Changing branch state does not change linked warehouse state or location permissions."');
    expect(branchModal).toContain("autoFocus");
    expect(branchModal).not.toContain("isCompanyOwner");
    expect(selector).toContain("dir={i18n.dir()}");

    mocks.language = "en";
    mocks.companyCaps.add("branch.read");
    mocks.companyCaps.add("branch.create");
    renderBranchModal();
    await screen.findByText(branch.name);
    fireEvent.click(screen.getByRole("button", { name: "New branch" }));
    expect(screen.getByRole("dialog", { name: "Add branch" }).querySelector('[dir="ltr"]')).toBeTruthy();
  });
});