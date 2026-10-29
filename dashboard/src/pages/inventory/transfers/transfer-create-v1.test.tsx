import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  display_uom_id: 1, display_uom_code: "EACH", display_uom_name: "Each", display_factor_to_base: "1", display_quantity_scale: 6,
  quantity_scale: 6, quantity_step: "0.000001", available_quantity: "0.300001" };
const cartonProduct = { id: 300, name: "Carton product", sku: "SKU-300", base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "Each",
  display_uom_id: 2, display_uom_code: "CARTON", display_uom_name: "Carton", display_factor_to_base: "50", display_quantity_scale: 0,
  quantity_scale: 0, quantity_step: "1", available_quantity: "12900" };
const page = (items = [product], next_cursor: string | null = null) => ({ items, next_cursor, has_more: next_cursor !== null, total: items.length });
const vehicle = { id: 91, name: "Vehicle must never appear", code: "V91", location_type: "VEHICLE", vehicle_id: 1 };

const fetchDefault = async (url: string) => {
  if (url.includes("/locations?")) return new URL(url, "http://test").searchParams.get("purpose") === "source"
    ? [warehouse(11), warehouse(14), vehicle]
    : [warehouse(11), warehouse(12), warehouse(15), vehicle];
  if (url.includes("source-inventory")) return page();
  if (url.includes("override-options")) return {
    location_id: 11,
    product_variant_id: 100,
    fefo_batch_id: 8,
    batches: [{ id: 8, batch_number: "LOT", production_date: null, expiry_date: null, available_quantity: "0.300001", is_fefo_head: true }],
    reasons: [{ id: 9, code: "APPROVED", description: "Approved" }],
  };
  return { message: "ok", header_id: 1 };
};

function Harness() {
  const c = useTransferCreate({ onCompleted: vi.fn(), onInventoryChanged: vi.fn() });
  return <><button onClick={c.openCreate}>Open</button><TransferCreateModal controller={c} /></>;
}

const open = () => {
  const view = render(<MemoryRouter><Harness /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Open" }));
  return view;
};

async function chooseWarehouse(label: string, name: string) {
  const input = screen.getByRole("combobox", { name: label });
  fireEvent.focus(input);
  fireEvent.click(input);
  const option = await screen.findByRole("option", { name: new RegExp(name) });
  fireEvent.click(option);
}

async function selectPair() {
  await chooseWarehouse(i18n.t("inventoryTransfers.sourceWarehouse"), "Warehouse 11");
  await chooseWarehouse(i18n.t("inventoryTransfers.destinationWarehouse"), "Warehouse 12");
  await screen.findByText(product.name);
}

const quantity = () => screen.getByRole("textbox", { name: i18n.t("inventoryTransfers.productQuantity", { name: product.name }) });
const send = () => screen.getByRole("button", { name: i18n.t("inventoryTransfers.send") });

beforeEach(async () => {
  localStorage.clear();
  localStorage.setItem("company_id", "1");
  localStorage.setItem("principal_id", "91");
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: webcrypto });
  mock.override = true;
  mock.send = true;
  mock.destination = true;
  mock.fetch.mockReset().mockImplementation(fetchDefault);
  await i18n.changeLanguage("en");
});

it.each([
  { direction: "incoming", counterpart: 91, notes: "old", purpose: "WAREHOUSE_BALANCING", items: [], locations: [vehicle] },
  { schema_version: 2, source: vehicle, destination: warehouse(12), items: [], notes: "old" },
  { schema_version: 2, source: warehouse(11), destination: vehicle, items: [], notes: "old" },
  { schema_version: 2, source: warehouse(11), destination: warehouse(11), items: [], notes: "old" },
  { schema_version: 2, source: { ...warehouse(11), location_type: "INVALID" }, destination: warehouse(12), items: [], notes: "old" },
  { schema_version: 2, source: {}, destination: warehouse(12), items: [], notes: "old" },
])("discards incompatible draft before any source request: %j", async (draft) => {
  const scope = transferCommandScope("TRANSFER_DRAFT", "workspace");
  localStorage.setItem(scope + ":draft", JSON.stringify(draft));
  expect(readTransferDraft(scope)).toBeNull();
  localStorage.setItem(scope + ":draft", JSON.stringify(draft));
  open();
  await screen.findByRole("combobox", { name: "Source Warehouse" });
  expect(screen.getByRole("combobox", { name: "Source Warehouse" })).toHaveValue("");
  expect(screen.queryByText(vehicle.name)).not.toBeInTheDocument();
  expect(mock.fetch.mock.calls.some(([url]) => url.includes("source-inventory"))).toBe(false);
});

it("does not fake source loading before both warehouses are selected and ignores empty partial drafts", async () => {
  const scope = transferCommandScope("TRANSFER_DRAFT", "workspace");
  const draft: TransferDraft = { schema_version: 2, source: warehouse(11), destination: null, notes: "", items: [] };
  writeTransferDraft(scope, draft);
  open();
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Source Warehouse" })).toHaveValue("Warehouse 11 (WH-11)"));
  expect(screen.getByText(i18n.t("inventoryTransfers.chooseWarehousesFirst"))).toBeInTheDocument();
  expect(screen.queryByText(i18n.t("inventoryTransfers.restoringDraft"))).not.toBeInTheDocument();
  expect(mock.fetch.mock.calls.some(([url]) => url.includes("source-inventory"))).toBe(false);
});

it("uses one searchable control per warehouse and never exposes vehicles", async () => {
  open();
  const source = screen.getByRole("combobox", { name: "Source Warehouse" });
  expect(screen.queryByRole("searchbox", { name: "Search source warehouses" })).not.toBeInTheDocument();
  fireEvent.focus(source);
  expect(screen.queryByRole("option", { name: /Warehouse 11/ })).not.toBeInTheDocument();
  fireEvent.click(source);
  expect(await screen.findByRole("option", { name: /Warehouse 11/ })).toBeVisible();
  expect(screen.queryByRole("option", { name: /Vehicle must never appear/ })).not.toBeInTheDocument();
  fireEvent.change(source, { target: { value: "Warehouse 14" } });
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.includes("purpose=source") && url.includes("search=Warehouse+14"))).toBe(true));
});

it.each(["ar", "en"])("one product table, exact All, confirmation notes, automatic FEFO and WAREHOUSE_BALANCING payload (%s)", async (language) => {
  await i18n.changeLanguage(language);
  open();
  await selectPair();
  expect(screen.getAllByRole("table")).toHaveLength(1);
  expect(screen.getByRole("columnheader", { name: i18n.t("inventoryTransfers.availableTransfer") })).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: i18n.t("inventoryTransfers.notes") })).not.toBeInTheDocument();
  const allButton = screen.getByRole("button", { name: i18n.t("inventoryTransfers.all") });
  expect(allButton).toHaveAttribute("title", i18n.t("inventoryTransfers.allTooltip"));
  expect(screen.queryByText(product.sku)).not.toBeInTheDocument();
  expect(screen.getByRole("searchbox", { name: i18n.t("inventoryTransfers.productSearch") }).closest("th")).not.toBeNull();
  fireEvent.click(allButton);
  expect(quantity()).toHaveValue("0.300001");
  await waitFor(() => expect(send()).not.toBeDisabled());
  fireEvent.click(send());
  const notes = await screen.findByRole("textbox", { name: i18n.t("inventoryTransfers.notes") });
  fireEvent.change(notes, { target: { value: "Optional transfer note" } });
  fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryTransfers.confirmSend") }));
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.endsWith("/dispatch"))).toBe(true));
  const body = JSON.parse(mock.fetch.mock.calls.find(([url]) => url.endsWith("/dispatch"))![1].body);
  expect(body).toMatchObject({
    source_location_id: 11,
    destination_location_id: 12,
    transfer_purpose: "WAREHOUSE_BALANCING",
    notes: "Optional transfer note",
    items: [{ product_variant_id: 100, quantity: "0.300001", uom_id: 1, is_fefo_override: false }],
  });
  expect(body.request_id).toMatch(/^[a-f0-9-]{36}$/);
});

it("keeps a selected row in place, accepts carton plus base remainder, clears quantities, and dispatches canonical base quantity", async () => {
  const first = { ...cartonProduct, id: 299, name: "First product", sku: "SKU-299" };
  mock.fetch.mockImplementation(async (url: string) => url.includes("source-inventory")
    ? page([first, cartonProduct])
    : fetchDefault(url));
  open();
  await selectPair();
  await screen.findByText(cartonProduct.name);

  const table = screen.getByRole("table");
  const rowTextsBefore = Array.from(table.querySelectorAll("tbody tr")).map((row) => row.textContent);
  expect(rowTextsBefore[1]).toContain(cartonProduct.name);

  const cartons = screen.getByRole("spinbutton", {
    name: i18n.t("inventoryTransfers.productDisplayQuantity", { name: cartonProduct.name, unit: "Carton" }),
  });
  fireEvent.change(cartons, { target: { value: "5" } });
  const pieces = screen.getByRole("spinbutton", {
    name: i18n.t("inventoryTransfers.productBaseRemainder", { name: cartonProduct.name, unit: "Each" }),
  });
  fireEvent.change(pieces, { target: { value: "10" } });

  const rowTextsAfter = Array.from(table.querySelectorAll("tbody tr")).map((row) => row.textContent);
  expect(rowTextsAfter[1]).toContain(cartonProduct.name);
  expect(screen.getByText("258 Carton")).toBeInTheDocument();

  await waitFor(() => expect(send()).not.toBeDisabled());
  fireEvent.click(send());
  expect(await screen.findByText("5 Carton + 10 Each")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryTransfers.back") }));

  fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryTransfers.clearQuantities") }));
  expect(send()).toBeDisabled();

  fireEvent.change(screen.getByRole("spinbutton", {
    name: i18n.t("inventoryTransfers.productDisplayQuantity", { name: cartonProduct.name, unit: "Carton" }),
  }), { target: { value: "5" } });
  fireEvent.change(screen.getByRole("spinbutton", {
    name: i18n.t("inventoryTransfers.productBaseRemainder", { name: cartonProduct.name, unit: "Each" }),
  }), { target: { value: "10" } });
  await waitFor(() => expect(send()).not.toBeDisabled());
  fireEvent.click(send());
  fireEvent.click(await screen.findByRole("button", { name: i18n.t("inventoryTransfers.confirmSend") }));
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.endsWith("/dispatch"))).toBe(true));
  const body = JSON.parse(mock.fetch.mock.calls.find(([url]) => url.endsWith("/dispatch"))![1].body);
  expect(body.items).toEqual([{ product_variant_id: 300, quantity: "260", uom_id: 1, is_fefo_override: false }]);
});

it("hides zero stock, blocks excess/invalid precision, and removes zero/empty from draft", async () => {
  mock.fetch.mockImplementation(async (url: string) => url.includes("source-inventory")
    ? page([product, { ...product, id: 101, name: "Zero product", available_quantity: "0" }])
    : fetchDefault(url));
  open();
  await selectPair();
  expect(screen.queryByText("Zero product")).not.toBeInTheDocument();
  fireEvent.change(quantity(), { target: { value: "0.300002" } });
  expect(send()).toBeDisabled();
  fireEvent.change(quantity(), { target: { value: "0.3000001" } });
  expect(send()).toBeDisabled();
  fireEvent.change(quantity(), { target: { value: "0.1" } });
  await waitFor(() => expect(send()).not.toBeDisabled());
  for (const value of ["0", ""]) {
    fireEvent.change(quantity(), { target: { value: value || "0.1" } });
    if (!value) fireEvent.change(quantity(), { target: { value: "" } });
    expect(send()).toBeDisabled();
    await waitFor(() => expect(readTransferDraft(transferCommandScope("TRANSFER_DRAFT", "workspace"))?.items).toEqual([]));
  }
});

it.each(["source", "destination"] as const)("%s change clears selected rows and invalidates destination-aware discovery", async (side) => {
  open();
  await selectPair();
  fireEvent.change(quantity(), { target: { value: "0.1" } });
  mock.fetch.mockImplementation(async (url: string) => url.includes("source-inventory")
    ? page([{ ...product, id: 200, name: "New context", sku: "NEW" }])
    : fetchDefault(url));
  const label = side === "source" ? "Source Warehouse" : "Destination Warehouse";
  const nextName = side === "source" ? "Warehouse 14" : "Warehouse 15";
  await chooseWarehouse(label, nextName);
  await screen.findByText("New context");
  expect(screen.queryByText(product.name)).not.toBeInTheDocument();
  expect(send()).toBeDisabled();
});

it.each([false, true])("FEFO override is visible and loadable only with the exact capability (%s)", async (allowed) => {
  mock.override = allowed;
  open();
  await selectPair();
  fireEvent.change(quantity(), { target: { value: "0.1" } });
  const chooseBatch = screen.queryByRole("button", { name: i18n.t("inventoryTransfers.chooseSpecificBatch") });
  if (!allowed) {
    expect(chooseBatch).toBeNull();
    expect(mock.fetch.mock.calls.some(([url]) => url.includes("override-options"))).toBe(false);
    return;
  }
  fireEvent.click(chooseBatch!);
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.includes("override-options"))).toBe(true));
  fireEvent.change(await screen.findByRole("combobox", { name: i18n.t("inventoryTransfers.selectedBatch") }), { target: { value: "8" } });
  fireEvent.change(screen.getByRole("combobox", { name: i18n.t("inventoryTransfers.overrideReason") }), { target: { value: "9" } });
  await waitFor(() => expect(send()).not.toBeDisabled());
  fireEvent.click(send());
  fireEvent.click(await screen.findByRole("button", { name: i18n.t("inventoryTransfers.confirmSend") }));
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.endsWith("/dispatch"))).toBe(true));
  const body = JSON.parse(mock.fetch.mock.calls.find(([url]) => url.endsWith("/dispatch"))![1].body);
  expect(body.items).toEqual([{ product_variant_id: 100, quantity: "0.1", uom_id: 1, is_fefo_override: true, override_batch_id: 8, override_reason_id: 9 }]);
});

it("shows neutral warehouse unavailability and never exposes raw tenant wording", async () => {
  mock.fetch.mockImplementation(async (url: string) => {
    if (url.includes("source-inventory")) throw { status: 404, message: "NOT YOUR TENANT", request_id: "trace-warehouse" };
    return fetchDefault(url);
  });
  open();
  await chooseWarehouse("Source Warehouse", "Warehouse 11");
  await chooseWarehouse("Destination Warehouse", "Warehouse 12");
  expect(await screen.findByRole("alert")).toHaveTextContent("The selected warehouse is no longer available for this transfer.");
  expect(screen.getByRole("alert")).toHaveTextContent("trace-warehouse");
  expect(screen.queryByText("NOT YOUR TENANT")).not.toBeInTheDocument();
});

it("replays the original pending pair/request without attaching a different draft", async () => {
  const wire = {
    path: "/warehouse/unified/transfer/dispatch",
    method: "POST" as const,
    body: {
      source_location_id: 11,
      destination_location_id: 12,
      transfer_purpose: "WAREHOUSE_BALANCING",
      items: [{ product_variant_id: 100, quantity: "0.1", uom_id: 1 }],
    },
  };
  const pending = await getOrCreateDurableCommand(transferCommandScope("TRANSFER_DISPATCH", "workspace"), wire);
  const other: TransferDraft = { schema_version: 2, source: warehouse(14), destination: warehouse(15), notes: "different draft", items: [] };
  writeTransferDraft(transferCommandScope("TRANSFER_DRAFT", "workspace"), other);
  open();
  await screen.findByText(i18n.t("inventoryTransfers.pending"));
  expect(screen.queryByRole("combobox", { name: "Source Warehouse" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.endsWith("/dispatch"))).toBe(true));
  const body = JSON.parse(mock.fetch.mock.calls.find(([url]) => url.endsWith("/dispatch"))![1].body);
  expect(body).toEqual({ ...wire.body, request_id: pending.requestId });
  await waitFor(() => expect(readTransferDraft(transferCommandScope("TRANSFER_DRAFT", "workspace"))?.notes).toBe("different draft"));
});

it.each(["send", "destination"] as const)("blocks confirmation when exact %s capability is revoked", async (side) => {
  open();
  await selectPair();
  mock[side] = false;
  fireEvent.change(quantity(), { target: { value: "0.1" } });
  expect(send()).toBeDisabled();
  expect(mock.fetch.mock.calls.some(([url]) => url.endsWith("/dispatch"))).toBe(false);
});
