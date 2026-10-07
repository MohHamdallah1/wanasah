import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import InventoryPage from "@/pages/inventory/InventoryPage";
import { ProductStatusBadges } from "@/pages/products/list/ProductStatusBadges";
import { BatchFocusWorkspace } from "@/pages/inventory/batches/BatchFocusWorkspace";
import { parseBatchStockSources } from "@/pages/inventory/batches/batchStockSourcesContract";
import { batchFocusIdentity } from "@/features/inventory/batchFocusNavigation";
import { createInventoryBatchFocusNavigationState } from "@/features/inventory/navigation";
import { resources } from "@/i18n/resources";
import { batchFocusPayload, batchSource, inventoryReadAccess } from "./fixtures/batchFocus";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), shell: vi.fn(), toast: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("sonner", () => ({ toast: { error: mocks.toast, success: vi.fn() } }));
vi.mock("@/pages/inventory/MainInventory", () => ({ default: () => { mocks.shell(); return <p>Warehouse shell</p>; } }));

const clients: QueryClient[] = [];
beforeEach(() => {
  mocks.fetch.mockReset(); mocks.shell.mockReset(); mocks.toast.mockReset(); localStorage.clear();
  localStorage.setItem("company_id", "1"); localStorage.setItem("driver_id", "7");
  localStorage.setItem("inventory_selected_location:1", "999");
});
afterEach(() => { cleanup(); clients.forEach((client) => client.clear()); clients.length = 0; });

function mockReads(payload = batchFocusPayload(), admin = true) {
  mocks.fetch.mockImplementation(async (url: string) => {
    if (url === "/inventory/access/me") return inventoryReadAccess(admin);
    if (url === "/warehouse/batches/41/stock-sources") return payload;
    throw new Error(`Unexpected read: ${url}`);
  });
}

const intent = createInventoryBatchFocusNavigationState({ variantId: 118, batchId: 41, productName: "Untrusted navigation label", locationId: 999 });
function RouteEvidence() {
  const location = useLocation();
  return <output data-testid="route-state">{JSON.stringify(location.state)}</output>;
}

async function mount(options: { language?: "ar" | "en"; products?: boolean; client?: QueryClient; workspace?: boolean; navigationState?: unknown } = {}) {
  const i18n = createInstance();
  await i18n.init({ resources, lng: options.language ?? "en", fallbackLng: "en", interpolation: { escapeValue: false } });
  const client = options.client ?? new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  clients.push(client);
  const onConsumed = vi.fn();
  const product = { id: 118, name: "Product", lifecycle_status: "ACTIVE" as const, operational_hold: "NONE" as const,
    batch_restrictions: { schema_version: 1 as const, scope: "COMPANY" as const, quantity_unit: "BASE_STOCK_UNIT" as const,
      affected_batch_count: 1, affected_on_hand_quantity: "10", counts_by_disposition: { QUARANTINED: 1, BLOCKED: 0, RECALLED: 0 },
      representative_reason: { selection: "LOWEST_BATCH_ID_WITH_CURRENT_REASON" as const, batch_id: 41, disposition: "QUARANTINED" as const,
        disposition_revision: 3, disposition_reason: "Saved inspection reason" } } };
  render(<QueryClientProvider client={client}><I18nextProvider i18n={i18n}>
    <MemoryRouter initialEntries={[options.products ? "/products" : { pathname: "/inventory", state: options.navigationState ?? intent }]}>
      {options.workspace ? <BatchFocusWorkspace identity={{ batchId: 41, variantId: 118 }} onConsumed={onConsumed} onClose={vi.fn()} onOpenTransfers={vi.fn()} onOpenReservationOwner={vi.fn()} /> : <Routes>
        <Route path="/products" element={<ProductStatusBadges item={product} />} />
        <Route path="/inventory" element={<InventoryPage />} />
        <Route path="/dispatch" element={<p>Dispatch owner</p>} />
      </Routes>}
      <RouteEvidence />
    </MemoryRouter>
  </I18nextProvider></QueryClientProvider>);
  return { client, i18n, onConsumed };
}

describe("batch-first Phase 1 acceptance", () => {
  it("keeps the Products batch warning compact and opens the Inventory batches page directly", async () => {
    mocks.fetch.mockImplementation(async (url: string) => {
      if (url === "/inventory/access/me") return inventoryReadAccess();
      throw new Error(`Unexpected read: ${url}`);
    });

    const { i18n } = await mount({ products: true, language: "ar" });
    expect(screen.getByText(i18n.t("productQualityWorkspace.affectedBatchesCompact", { count: 1 }))).toBeVisible();
    expect(screen.queryByText("Saved inspection reason")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {
      name: i18n.t("productQualityWorkspace.manageAffectedBatches"),
    }));

    expect(await screen.findByText("Warehouse shell")).toBeVisible();
    expect(mocks.fetch.mock.calls.some(([url]) => String(url).includes("quality-batch-candidates"))).toBe(false);
    expect(screen.queryByText(i18n.t("productQualityWorkspace.batchPicker.title"))).not.toBeInTheDocument();
  });

  it("shows only server-readable A, without hidden B identity, quantity or count", async () => {
    mockReads(batchFocusPayload([batchSource(11, "Readable A", "WAREHOUSE", false)]), false);
    const { i18n } = await mount();
    await screen.findByText("LOT-41");
    expect(screen.getByText(i18n.t("batchFocus.singleSource", { source: "Readable A" }))).toBeVisible();
    expect(screen.queryByText("Hidden B")).not.toBeInTheDocument();
    expect(screen.queryByText(/9184/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("inventoryBatches.quantityActions.purposes.QUARANTINE.label") })).not.toBeInTheDocument();
    expect(mocks.fetch.mock.calls.every(([, init]) => init?.method !== "PUT" && init?.method !== "DELETE")).toBe(true);
  });

  it("rejects a mismatched batch/variant and consumes the hint once", async () => {
    mockReads({ ...batchFocusPayload(), product_variant_id: 119 });
    const { i18n, onConsumed } = await mount({ workspace: true });
    await screen.findByRole("alert");
    expect(screen.getByText(i18n.t("batchFocus.scopeMismatch"))).toBeVisible();
    expect(screen.queryByText("LOT-41")).not.toBeInTheDocument();
    expect(onConsumed).toHaveBeenCalledOnce();
  });

  it("hides a warm cache until a new owner read and fails closed after revocation", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["batch-stock-sources", 1, 7, 41], parseBatchStockSources(batchFocusPayload([batchSource(12, "Hidden B")])));
    let deny: (reason: unknown) => void = () => {};
    mocks.fetch.mockImplementation((url: string) => url === "/inventory/access/me" ? Promise.resolve(inventoryReadAccess())
      : new Promise((_resolve, reject) => { deny = reject; }));
    await mount({ client });
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledWith("/warehouse/batches/41/stock-sources", expect.anything()));
    expect(screen.queryByText("Hidden B")).not.toBeInTheDocument();
    deny(Object.assign(new Error("Denied"), { status: 403, code: "PERMISSION_DENIED", requestId: "batch-read-42" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("batch-read-42");
    expect(screen.queryByText("Hidden B")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("route-state")).toHaveTextContent("null"));
  });

  it("waits for fresh destination capabilities instead of presenting cached admin actions", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["inventory-access", "1", "7", null], inventoryReadAccess());
    let resolveAccess: (value: ReturnType<typeof inventoryReadAccess>) => void = () => {};
    mocks.fetch.mockImplementation((url: string) => url === "/inventory/access/me"
      ? new Promise((resolve) => { resolveAccess = resolve; })
      : Promise.resolve(batchFocusPayload([batchSource(11, "Readable A", "WAREHOUSE", false)])));
    const { i18n } = await mount({ client });
    await waitFor(() => expect(client.getQueryData(["batch-stock-sources", 1, 7, 41])).toBeDefined());
    expect(screen.queryByText("LOT-41")).not.toBeInTheDocument();
    expect(screen.getByTestId("route-state")).not.toHaveTextContent("null");
    resolveAccess(inventoryReadAccess(false));
    await screen.findByText("LOT-41");
    expect(screen.queryByRole("button", { name: i18n.t("batchFocus.changeDisposition") })).not.toBeInTheDocument();
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
  });

  it.each(["ar", "en"] as const)("keeps keyboard entry, locale direction and Western source counts in %s", async (language) => {
    mockReads(batchFocusPayload([batchSource(11, "Warehouse A"), batchSource(13, "Vehicle 13", "VEHICLE")]));
    const { i18n } = await mount({ language });
    await screen.findByText("LOT-41");
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveFocus();
    expect(heading.closest("section")).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
    expect(screen.getByText(i18n.t("batchFocus.multipleSources", { count: "2" }))).toBeVisible();
    const back = screen.getByRole("button", { name: i18n.t("batchFocus.back") });
    back.focus(); expect(back).toHaveFocus(); fireEvent.click(back);
    expect(await screen.findByText("Warehouse shell")).toBeVisible();
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
  });

  it("keeps the reservation action inside its owning module", async () => {
    mockReads();
    const { i18n } = await mount();
    await screen.findByText("LOT-41");
    fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryBatches.quantityActions.reservationEvidence.openOwner") }));
    expect(await screen.findByText("Dispatch owner")).toBeVisible();
    expect(screen.getByTestId("route-state")).toHaveTextContent('"transferId":111');
    expect(screen.getByTestId("route-state")).toHaveTextContent('"openCancel":false');
  });

  it("uses no warehouse hint or authority from malformed navigation", () => {
    expect(batchFocusIdentity(intent)).toEqual({ batchId: 41, variantId: 118 });
    expect(batchFocusIdentity({ inventoryNavigation: { ...intent.inventoryNavigation, batchId: -1, permissions: ["inventory.read"] } })).toBeNull();
  });

  it("shows all server quantities/statuses but offers only the permitted source action", async () => {
    const readable = batchSource(11, "Warehouse A");
    const readOnly = batchSource(13, "Vehicle 13", "VEHICLE", false);
    readOnly.statuses[0].on_hand_quantity = "20";
    readOnly.statuses[0].movable_quantity = "18";
    mockReads(batchFocusPayload([readable, readOnly]));
    const { i18n } = await mount();
    await screen.findByText("LOT-41");
    expect(screen.getByText(i18n.t("inventoryBatches.quantityActions.onHand", { quantity: "10", unit: "EACH" }))).toBeVisible();
    expect(screen.getByText(i18n.t("inventoryBatches.quantityActions.onHand", { quantity: "20", unit: "EACH" }))).toBeVisible();
    expect(screen.getAllByText(i18n.t("inventoryBatches.quantityActions.reserved", { quantity: "2", unit: "EACH" }))).toHaveLength(2);
    expect(screen.getAllByText(i18n.t("inventoryBatches.quantityActions.stockStatuses.QUARANTINED"), { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: i18n.t("inventoryBatches.quantityActions.purposes.QUARANTINE.label") })).toHaveLength(1);
    expect(screen.getAllByText(i18n.t("qualityActionReasons.reasons.SOURCE_CANNOT_SEND")).length).toBeGreaterThan(0);
  });

  it("aborts a pending focus read when the user leaves and does not reopen it", async () => {
    let signal: AbortSignal | undefined;
    mocks.fetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/inventory/access/me") return Promise.resolve(inventoryReadAccess());
      signal = init?.signal ?? undefined;
      return new Promise(() => {});
    });
    const { i18n } = await mount();
    await waitFor(() => expect(signal).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: i18n.t("batchFocus.back") }));
    await screen.findByText("Warehouse shell");
    expect(signal?.aborted).toBe(true);
    expect(screen.getByTestId("route-state")).toHaveTextContent("null");
    expect(screen.queryByText("LOT-41")).not.toBeInTheDocument();
  });
});
