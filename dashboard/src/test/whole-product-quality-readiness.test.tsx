import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";

import { createInventoryWholeProductIssueNavigationState } from "@/features/inventory/navigation";
import { resources } from "@/i18n/resources";
import InventoryPage from "@/pages/inventory/InventoryPage";
import { parseWholeProductIssueSourcesPage } from "@/pages/inventory/quality/wholeProductIssueContract";
import { batchSource, inventoryReadAccess } from "./fixtures/batchFocus";
import { productQualityPage, qualityBatch } from "./fixtures/productQuality";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.fetch }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/pages/inventory/MainInventory", () => ({ default: () => <p>Warehouse shell</p> }));
const url = "/warehouse/variants/118/quality-issue-sources?limit=25";
const clients: QueryClient[] = [];
const readiness = (ready: boolean, batches = productQualityPage().batches) => ({
  ...productQualityPage(batches), ready_to_resume_sales: ready, company_requirements_remaining: !ready,
});
function RouteEvidence() {
  const route = useLocation();
  return <output data-testid="route-evidence">{JSON.stringify({ path: route.pathname, state: route.state })}</output>;
}
async function mount(language: "ar" | "en" = "ar", client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const i18n = createInstance();
  await i18n.init({ resources, lng: language, fallbackLng: "en", interpolation: { escapeValue: false } });
  clients.push(client);
  render(<QueryClientProvider client={client}><I18nextProvider i18n={i18n}>
    <MemoryRouter initialEntries={[{ pathname: "/inventory", state: createInventoryWholeProductIssueNavigationState({
      variantId: 118, productName: "Test product", locationId: 999,
    }) }]}>
      <Routes><Route path="/inventory" element={<InventoryPage />} /><Route path="/dispatch" element={<p>Dispatch owner</p>} /></Routes>
      <RouteEvidence />
    </MemoryRouter>
  </I18nextProvider></QueryClientProvider>);
  return i18n;
}
function reads(page: ReturnType<typeof readiness>, admin = true) {
  mocks.fetch.mockImplementation(async (path: string) => {
    if (path === "/inventory/access/me") return inventoryReadAccess(admin);
    if (path === url) return page;
    throw new Error(`Unexpected request: ${path}`);
  });
}
beforeEach(() => {
  mocks.fetch.mockReset(); localStorage.clear();
  localStorage.setItem("company_id", "1"); localStorage.setItem("driver_id", "7");
});
afterEach(() => { cleanup(); clients.forEach((client) => client.clear()); clients.length = 0; vi.unstubAllGlobals(); });

describe("Phase 2.4 backend-only readiness acceptance", () => {
  it.each([false, true])("uses backend ready=%s, never empty readable batches, and leaves Catalog hold unchanged", async (ready) => {
    reads(readiness(ready, []), false);
    const i18n = await mount();
    const title = `inventoryQualityIssue.readiness.${ready ? "ready" : "pending"}Title`;
    expect(await screen.findByText(i18n.t(title))).toBeVisible();
    expect(screen.getByText(i18n.t(`inventoryQualityIssue.readiness.${ready ? "ready" : "pending"}Hint`))).toBeVisible();
    expect(screen.getByText(i18n.t("inventoryQualityIssue.companyHoldTitle"))).toBeVisible();
    expect(screen.getByText(i18n.t("productQualityWorkspace.catalogContext"))).toBeVisible();
    expect(screen.getByText(i18n.t("productQualityWorkspace.noVisibleStock"))).toBeVisible();
    expect(i18n.exists("catalogLifecycle.actions.closeRecall")).toBe(true);
    expect(screen.queryByRole("button", { name: i18n.t("catalogLifecycle.actions.closeRecall") })).not.toBeInTheDocument();
    expect(mocks.fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });

  it("does not override server readiness with visible reservations, movable quantity or action count", async () => {
    // Counterfactual projection intentionally proves React does not recalculate lifecycle blockers.
    reads(readiness(true));
    const i18n = await mount();
    expect(await screen.findByText(i18n.t("inventoryQualityIssue.readiness.readyTitle"))).toBeVisible();
    expect(screen.getByText("Warehouse A")).toBeVisible();
    expect(screen.getByText("Warehouse C")).toBeVisible();
    expect(screen.getByText("Vehicle 13")).toBeVisible();
    expect(screen.getAllByText(i18n.t("inventoryBatches.quantityActions.reserved", { quantity: "2", unit: "EACH" }))).toHaveLength(3);
    expect(screen.getAllByText(i18n.t("inventoryBatches.quantityActions.movable", { quantity: "8", unit: "EACH" }))).toHaveLength(3);
    expect(screen.queryByText(i18n.t("inventoryQualityIssue.readiness.pendingTitle"))).not.toBeInTheDocument();
  });

  it("shows only a non-identifying company requirement signal and translates exact server no-action reasons", async () => {
    const source = batchSource(11, "Readable A", "WAREHOUSE", false);
    source.statuses[0].special_actions.forEach((action) => { action.reason_code = "NO_CONFIGURED_DESTINATION"; });
    reads(readiness(false, [qualityBatch(41, [source])]), false);
    const i18n = await mount();
    expect(await screen.findByText(i18n.t("inventoryQualityIssue.readiness.pendingHint"))).toBeVisible();
    const batch = screen.getByRole("region", { name: i18n.t("inventoryQualityIssue.batchTitle", { batch: "LOT-41" }) });
    expect(within(batch).getByText(i18n.t("qualityActionReasons.setupRequiredTitle"))).toBeVisible();
    expect(within(batch).getByText(i18n.t("qualityActionReasons.setupRequiredHint"))).toBeVisible();
    expect(within(batch).queryByText(i18n.t("qualityActionReasons.reasons.NO_CONFIGURED_DESTINATION"), { exact: false })).not.toBeInTheDocument();
    expect(within(batch).queryByRole("button", { name: i18n.t("qualityActionReasons.configure") })).not.toBeInTheDocument();
    expect(within(batch).queryByText(i18n.t("qualityActionReasons.reasons.SOURCE_CANNOT_SEND"))).not.toBeInTheDocument();
    expect(within(batch).queryByRole("button", { name: i18n.t("inventoryBatches.quantityActions.purposes.QUARANTINE.label") })).not.toBeInTheDocument();
    expect(screen.queryByText(/Hidden B|Vehicle 13|Warehouse C|9184/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(1);
    expect(mocks.fetch.mock.calls.filter(([path]) => path !== "/inventory/access/me").map(([path]) => path)).toEqual([url]);
  });

  it.each([false, true])("takes ready=%s from the latest bounded page, without AND/OR over pages or per-source reads", async (latest) => {
    const first = { ...readiness(!latest, [qualityBatch(41)]), next_cursor: 41, has_more: true };
    mocks.fetch.mockImplementation(async (path: string) => path === "/inventory/access/me" ? inventoryReadAccess()
      : path === url ? first : path === `${url}&cursor=41` ? readiness(latest, [qualityBatch(42)]) : Promise.reject(new Error(path)));
    const i18n = await mount();
    await screen.findByText(i18n.t(`inventoryQualityIssue.readiness.${latest ? "pending" : "ready"}Title`));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryQualityIssue.loadMore") }));
    await screen.findByRole("heading", { name: i18n.t("inventoryQualityIssue.batchTitle", { batch: "LOT-42" }) });
    expect(await screen.findByText(i18n.t(`inventoryQualityIssue.readiness.${latest ? "ready" : "pending"}Title`))).toBeVisible();
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: i18n.t("inventoryQualityIssue.loadMore") })).not.toBeInTheDocument();
    expect(mocks.fetch.mock.calls.filter(([path]) => path !== "/inventory/access/me").map(([path]) => path)).toEqual([url, `${url}&cursor=41`]);
  });

  it("hides previous positive readiness while re-reading, fails closed on revoked read, and retries with redacted evidence", async () => {
    let sourceReads = 0;
    let deny: (reason: unknown) => void = () => {};
    mocks.fetch.mockImplementation(async (path: string) => {
      if (path === "/inventory/access/me") return inventoryReadAccess();
      if (path !== url) throw new Error(path);
      sourceReads += 1;
      if (sourceReads === 1) return readiness(true, [qualityBatch(41, [batchSource(12, "Previously readable B")])]);
      if (sourceReads === 2) return new Promise((_resolve, reject) => { deny = reject; });
      return readiness(false, [qualityBatch(41, [batchSource(11, "Readable A", "WAREHOUSE", false)])]);
    });
    const i18n = await mount();
    await screen.findByText(i18n.t("inventoryQualityIssue.readiness.readyTitle"));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("common.refresh") }));
    await waitFor(() => expect(sourceReads).toBe(2));
    expect(screen.queryByText(i18n.t("inventoryQualityIssue.readiness.readyTitle"))).not.toBeInTheDocument();
    await act(async () => deny(Object.assign(new Error("Denied"), { status: 403, code: "PERMISSION_DENIED", requestId: "quality-revoked-24" })));
    expect(await screen.findByRole("alert")).toHaveTextContent("quality-revoked-24");
    expect(screen.queryByText("Previously readable B")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("common.retry") }));
    await screen.findByText("Readable A");
    expect(screen.getByText(i18n.t("inventoryQualityIssue.readiness.pendingTitle"))).toBeVisible();
    expect(screen.queryByText("Previously readable B")).not.toBeInTheDocument();
    expect(sourceReads).toBe(3);
    expect(screen.getByTestId("route-evidence")).toHaveTextContent('"state":null');
  });

  it("withholds cached ready evidence until both fresh destination reads finish", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["inventory-access", "1", "7", null], inventoryReadAccess());
    client.setQueryData(["whole-product-quality-issue-sources", 1, 7, 118], {
      pages: [parseWholeProductIssueSourcesPage(readiness(true, []))], pageParams: [null],
    });
    let allow: (data: unknown) => void = () => {};
    mocks.fetch.mockImplementation(async (path: string) => path === "/inventory/access/me"
      ? new Promise((resolve) => { allow = resolve; }) : readiness(false, []));
    const i18n = await mount("ar", client);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledWith(url, expect.anything()));
    expect(screen.queryByText(i18n.t("inventoryQualityIssue.readiness.readyTitle"))).not.toBeInTheDocument();
    expect(screen.queryByText(i18n.t("inventoryQualityIssue.readiness.pendingTitle"))).not.toBeInTheDocument();
    await act(async () => allow(inventoryReadAccess(false)));
    expect(await screen.findByText(i18n.t("inventoryQualityIssue.readiness.pendingTitle"))).toBeVisible();
  });

  it("withdraws readiness during capability refresh and after permission denial", async () => {
    let capabilityReads = 0;
    let revoked = false;
    let deny: (reason: unknown) => void = () => {};
    const deniedRead = new Promise((_resolve, reject) => { deny = reject; });
    mocks.fetch.mockImplementation(async (path: string) => {
      if (path === url) return readiness(true, []);
      if (path !== "/inventory/access/me") throw new Error(path);
      capabilityReads += 1;
      return revoked ? deniedRead : inventoryReadAccess();
    });
    const i18n = await mount();
    await screen.findByText(i18n.t("inventoryQualityIssue.readiness.readyTitle"));
    const previousReads = capabilityReads;
    revoked = true;
    act(() => window.dispatchEvent(new Event("inventory-permission-denied")));
    await waitFor(() => expect(capabilityReads).toBeGreaterThan(previousReads));
    expect(screen.queryByText(i18n.t("inventoryQualityIssue.readiness.readyTitle"))).not.toBeInTheDocument();
    await act(async () => deny(Object.assign(new Error("Denied"), { status: 403, code: "PERMISSION_DENIED", requestId: "access-revoked-24" })));
    expect(await screen.findByRole("alert")).toHaveTextContent("access-revoked-24");
    expect(screen.queryByText(i18n.t("inventoryQualityIssue.companyHoldTitle"))).not.toBeInTheDocument();
  });

  it("offers only a concrete reservation-owner route, never generic transfers or an Inventory cancellation proxy", async () => {
    reads(readiness(false, [qualityBatch(41)]));
    const i18n = await mount();
    await screen.findByText("HS-11", { exact: false });
    expect(screen.queryByRole("button", { name: i18n.t("inventoryBatches.quantityActions.openTransfers") })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("inventoryBatches.quantityActions.followCreatedTransfer") })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryBatches.quantityActions.reservationEvidence.openOwner") }));
    await screen.findByText("Dispatch owner");
    const route = JSON.parse(screen.getByTestId("route-evidence").textContent!);
    expect(route).toEqual({ path: "/dispatch", state: { dispatchNavigation: {
      version: 1, kind: "reservation-owner", routeId: 70, transferId: 111, openCancel: false,
    } } });
    expect(mocks.fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });

  it("exposes transfer navigation only after a concrete created result and fresh endpoint capabilities", async () => {
    vi.stubGlobal("crypto", webcrypto);
    let complete: (result: unknown) => void = () => {};
    mocks.fetch.mockImplementation(async (path: string) => {
      if (path === "/inventory/access/me") return inventoryReadAccess();
      if (path === url) return readiness(false, [qualityBatch(41)]);
      if (path === "/warehouse/unified/transfer/special/dispatch") return new Promise((resolve) => { complete = resolve; });
      if (path === "/inventory/access/locations/capabilities") return { locations: { 11: ["location.read", "transfer.read"], 22: [] } };
      throw new Error(path);
    });
    const i18n = await mount();
    await screen.findByText("Warehouse A");
    const generic = i18n.t("inventoryBatches.quantityActions.openTransfers");
    const follow = i18n.t("inventoryBatches.quantityActions.followCreatedTransfer");
    expect(screen.queryByRole("button", { name: generic })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: follow })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryBatches.quantityActions.purposes.QUARANTINE.label") }));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryBatches.quantityActions.confirm") }));
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledWith("/warehouse/unified/transfer/special/dispatch", expect.anything()));
    expect(screen.queryByRole("button", { name: follow })).not.toBeInTheDocument();
    await act(async () => complete({ header_id: 700, transfer_reference: "SPEC-700", transfer_purpose: "QUARANTINE",
      source_location_id: 11, destination_location_id: 22 }));
    const followButton = await screen.findByRole("button", { name: follow });
    expect(screen.getByText(i18n.t("inventoryBatches.quantityActions.createdReference", { reference: "SPEC-700" }))).toBeVisible();
    expect(screen.queryByRole("button", { name: generic })).not.toBeInTheDocument();
    const dispatch = mocks.fetch.mock.calls.find(([path]) => path === "/warehouse/unified/transfer/special/dispatch")!;
    expect(JSON.parse(dispatch[1].body)).toMatchObject({ request_id: expect.any(String), source_location_id: 11,
      transfer_purpose: "QUARANTINE", items: [{ product_variant_id: 118, batch_id: 41, source_status: "QUARANTINED", quantity: "8", uom_id: 7 }] });
    fireEvent.click(followButton);
    await screen.findByText("Warehouse shell");
    const capabilities = mocks.fetch.mock.calls.find(([path]) => path === "/inventory/access/locations/capabilities")!;
    expect(JSON.parse(capabilities[1].body)).toEqual({ location_ids: [11, 22] });
    const route = JSON.parse(screen.getByTestId("route-evidence").textContent!);
    expect(route.state.inventoryNavigation).toMatchObject({ kind: "owner-focus", flow: "transfer", operationId: 700,
      variantId: 118, locationId: 11, reference: "SPEC-700", tab: "transfers" });
    expect(mocks.fetch.mock.calls.some(([path]) => /terminal|dispose|handover/.test(String(path)))).toBe(false);
  });
});
