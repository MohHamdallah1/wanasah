import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createInventoryWholeProductIssueNavigationState } from "@/features/inventory/navigation";
import { inventoryWorkspaceFocus } from "@/features/inventory/workspaceFocusNavigation";
import InventoryPage from "@/pages/inventory/InventoryPage";
import { parseWholeProductIssueSourcesPage } from "@/pages/inventory/quality/wholeProductIssueContract";
import { resources } from "@/i18n/resources";
import { batchSource, inventoryReadAccess } from "./fixtures/batchFocus";
import { productQualityPage, qualityBatch } from "./fixtures/productQuality";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), shell: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/pages/inventory/MainInventory", () => ({ default: () => { mocks.shell(); return <p>Warehouse shell</p>; } }));
const clients: QueryClient[] = [];
const url = "/warehouse/variants/118/quality-issue-sources?limit=25";
const intent = createInventoryWholeProductIssueNavigationState({ variantId: 118, productName: "Test product", locationId: 999 });

beforeEach(() => {
  mocks.fetch.mockReset(); mocks.shell.mockReset(); localStorage.clear();
  localStorage.setItem("company_id", "1"); localStorage.setItem("driver_id", "7");
  localStorage.setItem("inventory_selected_location:1", "999");
});
afterEach(() => { cleanup(); clients.forEach((client) => client.clear()); clients.length = 0; });

function mockReads(page = productQualityPage(), admin = true) {
  mocks.fetch.mockImplementation(async (path: string) => {
    if (path === "/inventory/access/me") return inventoryReadAccess(admin);
    if (path === url) return page;
    throw new Error(`Unexpected request: ${path}`);
  });
}
function Launcher() {
  const navigate = useNavigate();
  return <button onClick={() => navigate("/inventory", { state: intent })}>Open quality</button>;
}
function Evidence() {
  return <output data-testid="route-state">{JSON.stringify(useLocation().state)}</output>;
}
async function mount(language: "ar" | "en" = "ar", client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const i18n = createInstance();
  await i18n.init({ resources, lng: language, fallbackLng: "en", interpolation: { escapeValue: false } });
  clients.push(client);
  render(<QueryClientProvider client={client}><I18nextProvider i18n={i18n}><MemoryRouter initialEntries={["/products"]}>
    <Routes><Route path="/products" element={<Launcher />} /><Route path="/inventory" element={<InventoryPage />} /></Routes>
    <Evidence />
  </MemoryRouter></I18nextProvider></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Open quality" }));
  return i18n;
}

describe("Phase 2.1 dedicated product quality workspace", () => {
  it("enters a distinct Inventory workspace with Product → batches → sources → quantities/actions", async () => {
    mockReads();
    const i18n = await mount();
    await screen.findByRole("heading", { name: i18n.t("productQualityWorkspace.product", { name: "Test product" }) });
    expect(mocks.shell).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText(i18n.t("inventoryQualityIssue.companyHoldTitle"))).toBeVisible();
    expect(screen.getByText(i18n.t("productQualityWorkspace.catalogContext"))).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: i18n.t("productQualityWorkspace.batches", { count: "2" }) })).toBeVisible();
    const first = screen.getByRole("region", { name: i18n.t("inventoryQualityIssue.batchTitle", { batch: "LOT-41" }) });
    const second = screen.getByRole("region", { name: i18n.t("inventoryQualityIssue.batchTitle", { batch: "LOT-42" }) });
    expect(within(first).getByRole("heading", { level: 4, name: i18n.t("productQualityWorkspace.sources") })).toBeVisible();
    for (const name of ["Warehouse A", "Vehicle 13"]) expect(within(first).getByText(name)).toBeVisible();
    expect(within(second).getByText("Warehouse C")).toBeVisible();
    expect(within(first).getAllByText(i18n.t("inventoryBatches.quantityActions.reserved", { quantity: "2", unit: "EACH" }))).toHaveLength(2);
    expect(within(first).getAllByText(i18n.t("inventoryBatches.quantityActions.movable", { quantity: "8", unit: "EACH" }))).toHaveLength(2);
    expect(within(first).getAllByRole("button", { name: i18n.t("inventoryBatches.quantityActions.purposes.QUARANTINE.label") })).toHaveLength(2);
    expect(screen.queryByText(i18n.t("inventoryBatches.quantityActions.title"))).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("inventoryBatches.quantityActions.purposes.DISPOSAL.label") })).not.toBeInTheDocument();
    expect(mocks.fetch.mock.calls.filter(([path]) => path === url)).toHaveLength(1);
    expect(mocks.fetch.mock.calls.every(([path, init]) => !String(path).includes("/batches/") && !init?.method)).toBe(true);
    expect(localStorage.getItem("inventory_selected_location:1")).toBe("999");
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
  });

  it("does not infer hidden source details or completion from a permission-filtered response", async () => {
    mockReads(productQualityPage([qualityBatch(41, [batchSource(11, "Readable A", "WAREHOUSE", false)])]), false);
    const i18n = await mount();
    await screen.findByText("Readable A");
    expect(screen.getByRole("heading", { name: i18n.t("productQualityWorkspace.batches", { count: "1" }) })).toBeVisible();
    expect(screen.queryByText(/Hidden B|Vehicle 13|9184/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("inventoryBatches.quantityActions.purposes.QUARANTINE.label") })).not.toBeInTheDocument();
    expect(screen.queryByText(i18n.t("inventoryQualityIssue.readiness.readyTitle"))).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("inventoryBatches.quantityActions.openTransfers") })).not.toBeInTheDocument();
  });

  it("keeps a released batch distinct from the still-active company-wide Catalog hold", async () => {
    mockReads(productQualityPage([{ ...qualityBatch(41), disposition: "RELEASED", disposition_reason: null }]));
    const i18n = await mount();
    await screen.findByText(i18n.t("inventoryQualityIssue.dispositions.RELEASED"));
    expect(screen.getByText(i18n.t("inventoryQualityIssue.companyHoldTitle"))).toBeVisible();
    expect(mocks.fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });

  it.each(["ar", "en"] as const)("keeps %s direction, Western digits, keyboard entry and close/back consumption", async (language) => {
    mockReads();
    const i18n = await mount(language);
    await screen.findByText("Warehouse A");
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveFocus();
    expect(heading.closest("section")).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
    expect(screen.getByRole("heading", { name: i18n.t("productQualityWorkspace.batches", { count: "2" }) })).toBeVisible();
    expect(heading.closest("section")?.textContent).not.toMatch(/[٠-٩]/);
    const back = screen.getByRole("button", { name: i18n.t("batchFocus.back") });
    back.focus(); expect(back).toHaveFocus(); fireEvent.click(back);
    await screen.findByText("Warehouse shell");
    expect(screen.queryByText("Warehouse A")).not.toBeInTheDocument();
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
  });

  it("uses the existing bounded cursor contract without a per-batch/source read", async () => {
    const first = { ...productQualityPage([qualityBatch(41)]), next_cursor: 41, has_more: true };
    mocks.fetch.mockImplementation(async (path: string) => path === "/inventory/access/me" ? inventoryReadAccess()
      : path === url ? first : path === `${url}&cursor=41` ? productQualityPage([qualityBatch(42)]) : Promise.reject(new Error(path)));
    const i18n = await mount();
    await screen.findByRole("heading", { name: i18n.t("inventoryQualityIssue.batchTitle", { batch: "LOT-41" }) });
    fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryQualityIssue.loadMore") }));
    await screen.findByRole("heading", { name: i18n.t("inventoryQualityIssue.batchTitle", { batch: "LOT-42" }) });
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(2);
    expect(mocks.fetch.mock.calls.filter(([path]) => String(path).includes("quality-issue-sources"))).toHaveLength(2);
  });

  it("does not show warm source/capability cache before a fresh read and fails closed on revocation", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["inventory-access", "1", "7", null], inventoryReadAccess());
    client.setQueryData(["whole-product-quality-issue-sources", 1, 7, 118], {
      pages: [parseWholeProductIssueSourcesPage(productQualityPage([qualityBatch(41, [batchSource(12, "Hidden B")])]))], pageParams: [null],
    });
    let deny: (error: unknown) => void = () => {};
    mocks.fetch.mockImplementation((path: string) => path === "/inventory/access/me" ? Promise.resolve(inventoryReadAccess(false))
      : new Promise((_resolve, reject) => { deny = reject; }));
    await mount("ar", client);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledWith(url, expect.anything()));
    expect(screen.queryByText("Hidden B")).not.toBeInTheDocument();
    deny(Object.assign(new Error("Denied"), { status: 403, code: "PERMISSION_DENIED", requestId: "quality-read-42" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("quality-read-42");
    expect(screen.queryByText("Hidden B")).not.toBeInTheDocument();
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
  });

  it("rejects a fresh page for another product and does not treat route context as authority", async () => {
    mockReads({ ...productQualityPage([]), product_variant_id: 999 });
    const i18n = await mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("productQualityWorkspace.scopeMismatch"));
    expect(screen.queryByText(i18n.t("inventoryQualityIssue.companyHoldTitle"))).not.toBeInTheDocument();
    expect(inventoryWorkspaceFocus({ inventoryNavigation: { ...intent.inventoryNavigation, permissions: ["inventory.read"], operationalHold: "NONE" } }))
      .toEqual({ kind: "quality", variantId: 118, productName: "Test product" });
  });

  it("can close before resolution, aborting the read without reopening the consumed intent", async () => {
    let signal: AbortSignal | undefined;
    mocks.fetch.mockImplementation((path: string, init?: RequestInit) => {
      if (path === "/inventory/access/me") return Promise.resolve(inventoryReadAccess());
      signal = init?.signal ?? undefined;
      return new Promise(() => {});
    });
    const i18n = await mount();
    await waitFor(() => expect(signal).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: i18n.t("batchFocus.back") }));
    await screen.findByText("Warehouse shell");
    expect(signal?.aborted).toBe(true);
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
  });
});
