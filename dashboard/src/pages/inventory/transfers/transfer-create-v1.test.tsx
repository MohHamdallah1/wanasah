import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import i18n from "@/i18n";
import { MemoryRouter } from "react-router-dom";
import { getOrCreateDurableCommand } from "@/lib/durableOperations";
import { TransferCreateModal } from "./TransferCreateModal";
import { useTransferCreate } from "./hooks/useTransferCreate";
import { transferCommandScope } from "./hooks/useTransferCommand";
import { readTransferDraft, writeTransferDraft, type TransferDraft } from "./draftStorage";

const mock = vi.hoisted(() => ({ fetch: vi.fn(), override: true, send: true, destination: true }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mock.fetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({ useInventoryAccess: () => ({
  can: (code: string) => code === "inventory.fefo_override" ? mock.override : code === "transfer.send" ? mock.send : mock.destination,
  canAny: (code: string) => code === "transfer.send" ? mock.send : mock.destination,
}) }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));
const warehouse = (id: number) => ({ id, name: `Warehouse ${id}`, code: `WH-${id}`, location_type: "WAREHOUSE" as const, vehicle_id: null });
const product = { id: 100, name: "Precise product", sku: "SKU-100", base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "Each",
  quantity_scale: 6, quantity_step: "0.000001", available_quantity: "0.300001" };
const page = (items = [product]) => ({ items, next_cursor: null, has_more: false, total: items.length });
const vehicle = { id: 91, name: "Vehicle must never appear", code: "V91", location_type: "VEHICLE", vehicle_id: 1 };
const fetchDefault = async (url: string) => {
  if (url.includes("/locations?")) return new URL(url, "http://test").searchParams.get("purpose") === "source"
    ? [warehouse(11), warehouse(14), vehicle] : [warehouse(11), warehouse(12), warehouse(15), vehicle];
  if (url.includes("source-inventory")) return page();
  if (url.includes("override-options")) return { location_id: 11, product_variant_id: 100, fefo_batch_id: 8,
    batches: [{ id: 8, batch_number: "LOT", production_date: null, expiry_date: null, available_quantity: "0.300001", is_fefo_head: true }],
    reasons: [{ id: 9, code: "APPROVED", description: "Approved" }] };
  return { message: "ok", header_id: 1 };
};
function Harness() {
  const c = useTransferCreate({ locationId: 999, onCompleted: vi.fn(), onInventoryChanged: vi.fn() });
  return <><button onClick={c.openCreate}>Open</button><TransferCreateModal locationId={999} controller={c} /></>;
}
const open = () => {
  const view = render(<MemoryRouter><Harness /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Open" }));
  return view;
};
async function selectPair() {
  await within(screen.getByRole("combobox", { name: i18n.t("inventoryTransfers.sourceWarehouse") })).findByRole("option", { name: "Warehouse 11 (WH-11)" });
  await waitFor(() => expect(screen.getByRole("combobox", { name: i18n.t("inventoryTransfers.sourceWarehouse") })).not.toBeDisabled());
  fireEvent.change(screen.getByRole("combobox", { name: i18n.t("inventoryTransfers.sourceWarehouse") }), { target: { value: "11" } });
  await waitFor(() => expect(screen.getByRole("combobox", { name: i18n.t("inventoryTransfers.destinationWarehouse") })).not.toBeDisabled());
  fireEvent.change(screen.getByRole("combobox", { name: i18n.t("inventoryTransfers.destinationWarehouse") }), { target: { value: "12" } });
  await screen.findByText(product.name);
}
const quantity = () => screen.getByRole("textbox", { name: i18n.t("inventoryTransfers.productQuantity", { name: product.name }) });
const send = () => screen.getByRole("button", { name: i18n.t("inventoryTransfers.send") });
beforeEach(async () => {
  localStorage.clear(); localStorage.setItem("company_id", "1"); localStorage.setItem("principal_id", "91");
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: webcrypto });
  mock.override = true; mock.send = true; mock.destination = true;
  mock.fetch.mockReset().mockImplementation(fetchDefault); await i18n.changeLanguage("en");
});

it.each([
  { direction: "incoming", counterpart: 91, notes: "old", purpose: "WAREHOUSE_BALANCING", items: [], locations: [vehicle] },
  { schema_version: 2, source: vehicle, destination: warehouse(12), items: [], notes: "old" },
  { schema_version: 2, source: warehouse(11), destination: vehicle, items: [], notes: "old" },
  { schema_version: 2, source: warehouse(11), destination: warehouse(11), items: [], notes: "old" },
  { schema_version: 2, source: { ...warehouse(11), location_type: "INVALID" }, destination: warehouse(12), items: [], notes: "old" },
  { schema_version: 2, source: {}, destination: warehouse(12), items: [], notes: "old" },
])("discards incompatible draft before any source request: %j", async (draft) => {
  const scope = transferCommandScope("TRANSFER_DRAFT", 999);
  localStorage.setItem(scope + ":draft", JSON.stringify(draft));
  expect(readTransferDraft(scope)).toBeNull(); expect(localStorage.getItem(scope + ":draft")).toBeNull();
  localStorage.setItem(scope + ":draft", JSON.stringify(draft)); open();
  await screen.findByRole("combobox", { name: "Source Warehouse" });
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Source Warehouse" })).not.toBeDisabled());
  expect(screen.getByRole("combobox", { name: "Source Warehouse" })).toHaveValue("");
  expect(screen.queryByText(vehicle.name)).not.toBeInTheDocument();
  expect(mock.fetch.mock.calls.some(([url]) => url.includes("source-inventory"))).toBe(false);
});

it("uses independently purpose-authorized warehouse selectors without the page location or Direction", async () => {
  open(); await selectPair();
  expect(screen.queryByRole("combobox", { name: "Transfer direction" })).not.toBeInTheDocument();
  const source = screen.getByRole("combobox", { name: "Source Warehouse" }), destination = screen.getByRole("combobox", { name: "Destination Warehouse" });
  expect(within(source).queryByRole("option", { name: "Warehouse 12 (WH-12)" })).not.toBeInTheDocument();
  expect(within(destination).queryByRole("option", { name: "Warehouse 14 (WH-14)" })).not.toBeInTheDocument();
  expect(within(destination).queryByRole("option", { name: "Warehouse 11 (WH-11)" })).not.toBeInTheDocument();
  expect(screen.queryByText(vehicle.name)).not.toBeInTheDocument();
  const url = mock.fetch.mock.calls.find(([url]) => url.includes("source-inventory"))![0];
  expect(url).toContain("location_id=11&destination_location_id=12"); expect(url).not.toContain("999");
});

it.each(["ar", "en"])("one product table, exact All, automatic FEFO and explicit WAREHOUSE_BALANCING payload (%s)", async (language) => {
  await i18n.changeLanguage(language); open(); await selectPair();
  const dialog = screen.getByRole("dialog"); expect(dialog.querySelector("[dir]")).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
  expect(screen.getAllByRole("table")).toHaveLength(1);
  expect(screen.getByRole("columnheader", { name: i18n.t("inventoryTransfers.availableTransfer") })).toBeVisible();
  expect(screen.getByText("0.300001")).toBeVisible(); expect(screen.getByText("SKU-100")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryTransfers.all") }));
  expect(quantity()).toHaveValue("0.300001"); await waitFor(() => expect(send()).not.toBeDisabled()); fireEvent.click(send());
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.endsWith("/dispatch"))).toBe(true));
  const body = JSON.parse(mock.fetch.mock.calls.find(([url]) => url.endsWith("/dispatch"))![1].body);
  expect(body).toMatchObject({ source_location_id: 11, destination_location_id: 12, transfer_purpose: "WAREHOUSE_BALANCING",
    items: [{ product_variant_id: 100, quantity: "0.300001", uom_id: 1, is_fefo_override: false }] });
  expect(body.request_id).toMatch(/^[a-f0-9-]{36}$/);
});

it("hides zero stock, blocks excess/invalid precision, and removes zero/empty from outgoing draft", async () => {
  mock.fetch.mockImplementation(async (url: string) => url.includes("source-inventory") ? page([product, { ...product, id: 101, name: "Zero product", available_quantity: "0" }]) : fetchDefault(url));
  open(); await selectPair(); expect(screen.queryByText("Zero product")).not.toBeInTheDocument();
  fireEvent.change(quantity(), { target: { value: "0.300002" } }); expect(send()).toBeDisabled();
  fireEvent.submit(screen.getByRole("dialog").querySelector("form")!); expect(mock.fetch.mock.calls.some(([url]) => url.endsWith("/dispatch"))).toBe(false);
  fireEvent.change(quantity(), { target: { value: "0.3000001" } }); expect(send()).toBeDisabled();
  fireEvent.change(quantity(), { target: { value: "0.1" } }); await waitFor(() => expect(send()).not.toBeDisabled());
  for (const value of ["0", ""]) {
    fireEvent.change(quantity(), { target: { value: value || "0.1" } });
    if (!value) fireEvent.change(quantity(), { target: { value: "" } });
    expect(send()).toBeDisabled();
    await waitFor(() => expect(readTransferDraft(transferCommandScope("TRANSFER_DRAFT", 999))?.items).toEqual([]));
  }
});

it.each(["source", "destination"])("%s change clears selected rows and destination-aware discovery; old responses cannot return", async (side) => {
  open(); await selectPair(); fireEvent.change(quantity(), { target: { value: "0.1" } });
  let finish: (value: unknown) => void = () => {};
  mock.fetch.mockImplementation(async (url: string) => url.includes("source-inventory") ? new Promise((resolve) => { finish = resolve; }) : fetchDefault(url));
  fireEvent.change(screen.getByRole("searchbox", { name: i18n.t("inventoryTransfers.productSearch") }), { target: { value: "old" } });
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.includes("search=old"))).toBe(true));
  mock.fetch.mockImplementation(async (url: string) => url.includes("source-inventory") ? page([{ ...product, id: 200, name: "New context", sku: "NEW" }]) : fetchDefault(url));
  fireEvent.change(screen.getByRole("combobox", { name: side === "source" ? "Source Warehouse" : "Destination Warehouse" }), { target: { value: side === "source" ? "14" : "15" } });
  await screen.findByText("New context"); await act(async () => finish(page()));
  expect(screen.queryByText(product.name)).not.toBeInTheDocument(); expect(send()).toBeDisabled();
});

it.each([false, true])("FEFO override is visible and loadable only with the exact capability (%s)", async (allowed) => {
  mock.override = allowed; open(); await selectPair(); fireEvent.change(quantity(), { target: { value: "0.1" } });
  const advanced = screen.queryByText("Advanced batch allocation");
  if (!allowed) { expect(advanced).toBeNull(); expect(mock.fetch.mock.calls.some(([url]) => url.includes("override-options"))).toBe(false); return; }
  fireEvent.click(advanced!); fireEvent.change(screen.getByRole("combobox", { name: i18n.t("inventoryTransfers.batchPolicy") }), { target: { value: "override" } });
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.includes("override-options"))).toBe(true));
  expect(send()).toBeDisabled();
  fireEvent.change(await screen.findByRole("combobox", { name: i18n.t("inventoryTransfers.selectedBatch") }), { target: { value: "8" } });
  fireEvent.change(screen.getByRole("combobox", { name: i18n.t("inventoryTransfers.overrideReason") }), { target: { value: "9" } });
  await waitFor(() => expect(send()).not.toBeDisabled()); fireEvent.click(send());
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.endsWith("/dispatch"))).toBe(true));
  const body = JSON.parse(mock.fetch.mock.calls.find(([url]) => url.endsWith("/dispatch"))![1].body);
  expect(body.items).toEqual([{ product_variant_id: 100, quantity: "0.1", uom_id: 1, is_fefo_override: true, override_batch_id: 8, override_reason_id: 9 }]);
});

it("shows neutral warehouse unavailability, preserving request id and failing closed", async () => {
  mock.fetch.mockImplementation(async (url: string) => { if (url.includes("source-inventory")) throw { status: 404, message: "NOT YOUR TENANT", request_id: "trace-warehouse" }; return fetchDefault(url); });
  open();
  await within(screen.getByRole("combobox", { name: i18n.t("inventoryTransfers.sourceWarehouse") })).findByRole("option", { name: "Warehouse 11 (WH-11)" });
  fireEvent.change(screen.getByRole("combobox", { name: "Source Warehouse" }), { target: { value: "11" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Destination Warehouse" }), { target: { value: "12" } });
  expect(await screen.findByRole("alert")).toHaveTextContent("The selected warehouse is no longer available for this transfer.");
  expect(screen.getByRole("alert")).toHaveTextContent("trace-warehouse"); expect(screen.queryByText("NOT YOUR TENANT")).not.toBeInTheDocument(); expect(send()).toBeDisabled();
});

it("replays the original pending pair/request without attaching a different pair's draft", async () => {
  const wire = { path: "/warehouse/unified/transfer/dispatch", method: "POST" as const,
    body: { source_location_id: 11, destination_location_id: 12, transfer_purpose: "WAREHOUSE_BALANCING", items: [{ product_variant_id: 100, quantity: "0.1", uom_id: 1 }] } };
  const pending = await getOrCreateDurableCommand(transferCommandScope("TRANSFER_DISPATCH", 999), wire);
  const other: TransferDraft = { schema_version: 2, source: warehouse(14), destination: warehouse(15), notes: "different draft", items: [] };
  writeTransferDraft(transferCommandScope("TRANSFER_DRAFT", 999), other);
  open(); await screen.findByText(i18n.t("inventoryTransfers.pending"));
  expect(screen.queryByRole("combobox", { name: "Source Warehouse" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.endsWith("/dispatch"))).toBe(true));
  const body = JSON.parse(mock.fetch.mock.calls.find(([url]) => url.endsWith("/dispatch"))![1].body);
  expect(body).toEqual({ ...wire.body, request_id: pending.requestId });
  await waitFor(() => expect(readTransferDraft(transferCommandScope("TRANSFER_DRAFT", 999))?.notes).toBe("different draft"));
});


it.each(["send", "destination"] as const)("blocks submission when exact %s capability is revoked", async (side) => {
  open(); await selectPair(); mock[side] = false;
  fireEvent.change(quantity(), { target: { value: "0.1" } });
  expect(send()).toBeDisabled(); fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);
  expect(mock.fetch.mock.calls.some(([url]) => url.endsWith("/dispatch"))).toBe(false);
});
