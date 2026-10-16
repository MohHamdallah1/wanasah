import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WarehouseBatchIndexItem } from "@/pages/inventory/batches/batchIndexContracts";

const mocks = vi.hoisted(() => ({ authFetch: vi.fn(), language: "en", canManage: true }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.authFetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    can: (code: string) => code === "inventory.read" || mocks.canManage,
    data: { company_id: 1, principal_id: 7 },
  }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  const translate = (key: string, options?: Record<string, unknown>) => {
    let value = typeof options?.defaultValue === "string" ? options.defaultValue : key;
    for (const [name, candidate] of Object.entries(options ?? {})) value = value.replaceAll(`{{${name}}}`, String(candidate));
    return value;
  };
  return { ...actual, useTranslation: () => ({
    t: translate,
    i18n: { language: mocks.language, resolvedLanguage: mocks.language, dir: () => mocks.language === "ar" ? "rtl" : "ltr" },
  }) };
});
// Exercise the real modal/focus hook; mutation and secondary data panels are
// covered by CP3/CP6 regressions and are isolated here from presentation reads.
vi.mock("@/pages/inventory/batches/BatchQuantityActions", () => ({ BatchQuantityActions: () => null }));
vi.mock("@/pages/inventory/batches/StockStatusActionsPanel", () => ({ StockStatusActionsPanel: () => null }));
vi.mock("@/pages/inventory/batches/useBatchDispositionCommand", () => ({
  useBatchDispositionCommand: () => ({
    busy: false, pending: null, pendingBlocked: false, target: null, reason: "",
    isOnline: true, revisionConflict: false, setTarget: vi.fn(), setReason: vi.fn(),
  }),
}));
import { TabBatches } from "@/pages/inventory/TabBatches";
import { BatchIndexSummary } from "@/pages/inventory/batches/BatchIndexSummary";
import { BatchExpirySignal, BatchSellabilitySignal } from "@/pages/inventory/batches/BatchIndexSignals";
import { batchIndexText } from "@/pages/inventory/batches/batchIndexI18n";
import type { TFunction } from "i18next";

const item = (
  id: number,
  overrides: Partial<WarehouseBatchIndexItem> = {},
): WarehouseBatchIndexItem => ({
  batch_id: id,
  batch_number: `LOT-${id}`,
  production_date: "2026-01-01",
  expiry_date: "2026-12-31",
  disposition: "RELEASED",
  disposition_reason: null,
  disposition_revision: 1,
  allowed_disposition_targets: ["QUARANTINED", "BLOCKED", "RECALLED"],
  days_to_expiry: 76,
  product_id: 10,
  product_variant_id: 100 + id,
  product_name: `Product ${id}`,
  sku: `SKU-${id}`,
  family_name: "Family A",
  lot_control_mode: "REQUIRED",
  expiry_control_mode: "REQUIRED",
  minimum_remaining_shelf_life_days: 14,
  sellability_state: "SELLABLE",
  sellability_reason_codes: [],
  base_uom_id: 1,
  base_uom_code: "EACH",
  base_uom_name: "Each",
  display_uom_id: 1,
  display_uom_code: "EACH",
  display_uom_name: "Each",
  display_factor_to_base: "1",
  quantity_scale: 0,
  quantity_step: "1",
  on_hand_quantity: "10",
  reserved_quantity: "1",
  available_for_sale_quantity: "9",
  unavailable_quantity: "0",
  available_status_quantity: "10",
  quarantined_quantity: "0",
  blocked_quantity: "0",
  recalled_quantity: "0",
  damaged_quantity: "0",
  disposal_pending_quantity: "0",
  ...overrides,
});

const page = (
  items: WarehouseBatchIndexItem[],
  nextCursor: string | null = null,
) => ({
  location_id: 119,
  as_of_date: "2026-10-16",
  items,
  next_cursor: nextCursor,
  has_more: nextCursor !== null,
});

const summary = (overrides: Record<string, number> = {}) => ({
  location_id: 119,
  as_of_date: "2026-10-16",
  total_relevant_batches: 8,
  expired_count: 1,
  expiring_soon_count: 2,
  non_sellable_count: 3,
  quarantined_count: 1,
  blocked_count: 1,
  recalled_count: 1,
  damaged_or_disposal_attention_count: 1,
  ...overrides,
});


const t = ((key: string, values?: Record<string, unknown>) => {
  let result = String(values?.defaultValue ?? key);
  for (const [name, value] of Object.entries(values ?? {})) result = result.replaceAll(`{{${name}}}`, String(value));
  return result;
}) as TFunction;
const renderPage = (focus: { batchId: number; variantId: number; productName: string } | null = null, onFocusConsumed = vi.fn()) => render(
  <TabBatches locationId={119} focus={focus ? { ...focus, version: 1, kind: "batch-focus", tab: "batches", locationId: 119 } : null} onFocusConsumed={onFocusConsumed}
    onOpenTransfers={vi.fn()} onOpenReservationOwner={vi.fn()} onInventoryChanged={vi.fn()} />,
);
const serve = (rows = [item(1)]) => mocks.authFetch.mockImplementation(async (path: string) => {
  if (path.startsWith("/warehouse/inventory/batches/cursor?")) return page(rows);
  if (path.startsWith("/warehouse/inventory/batches/summary?")) return summary();
  throw new Error(`Unexpected request: ${path}`);
});

beforeEach(() => { mocks.authFetch.mockReset(); mocks.language = "en"; mocks.canManage = true; localStorage.clear(); });

describe("CP13 final Batches presentation", () => {
  it("loads batch-first without selecting a product and attaches search to the list surface", async () => {
    serve();
    const { container } = renderPage();
    await screen.findAllByText("Product 1");
    const paths = mocks.authFetch.mock.calls.map(([path]) => String(path));
    const request = paths.find((path) => path.includes("/batches/cursor?"))!;
    expect(new URLSearchParams(request.split("?")[1]).has("product_variant_id")).toBe(false);
    const surface = screen.getAllByRole("region", { name: "Batches" }).find((el) => el.contains(screen.getByRole("searchbox")))!;
    expect(surface.querySelector("table")).toBeTruthy();
    expect(container.querySelectorAll("input[type=search]")).toHaveLength(1);
    expect(within(surface).getByRole("columnheader", { name: "Lot number" })).toBeTruthy();
  });

  it("renders eight compact, textual, noninteractive counters without oversized cards", () => {
    const { container } = render(<BatchIndexSummary t={t} language="en" locale="en" summary={summary()} loading={false} error={false} onRetry={vi.fn()} />);
    const region = screen.getByRole("region", { name: "Batch attention summary" });
    expect(region.querySelectorAll("dt")).toHaveLength(8);
    expect(region.querySelectorAll("dd")).toHaveLength(8);
    expect(region.querySelector("dl")).toHaveClass("flex-wrap");
    expect(within(region).queryByRole("button")).toBeNull();
    expect(container.querySelector(".text-lg")).toBeNull();
  });

  it.each([
    [-2, "REQUIRED", "2026-10-14", "Expired"],
    [0, "REQUIRED", "2026-10-16", "Expires today"],
    [5, "REQUIRED", "2026-10-21", "Expiring soon"],
    [60, "REQUIRED", "2026-12-15", "Valid expiry"],
    [null, "REQUIRED", null, "Expiry date missing"],
    [null, "NONE", null, "No expiry tracking"],
  ] as const)("uses server expiry metadata for %s / %s with text and an icon", (days, mode, expiry, label) => {
    const { container } = render(<BatchExpirySignal t={t} language="en" locale="en" item={item(1, { days_to_expiry: days, expiry_control_mode: mode, expiry_date: expiry })} warningDays={30} />);
    expect(screen.getByText(label)).toBeTruthy();
    expect(container.querySelector('svg[aria-hidden="true"]')).toBeTruthy();
  });

  it("shows the backend primary reason and shelf-life explanation without deriving sellability from warning days", () => {
    const row = item(1, { days_to_expiry: 60, sellability_state: "NOT_SELLABLE",
      sellability_reason_codes: ["DISPOSITION_NOT_RELEASED", "MINIMUM_REMAINING_SHELF_LIFE_NOT_MET", "BATCH_INACTIVE"] });
    const { rerender } = render(<BatchSellabilitySignal t={t} language="en" locale="en" item={row} />);
    expect(screen.getByText("Not sellable")).toBeTruthy();
    expect(screen.getByText("Batch disposition prevents sale")).toBeTruthy();
    expect(screen.getByText("Minimum shelf life for sale: 14 days")).toBeTruthy();
    expect(screen.queryByText("Batch is inactive")).toBeNull();
    rerender(<BatchSellabilitySignal t={t} language="en" locale="en" item={row} allReasons />);
    expect(screen.getByText("Batch is inactive")).toBeTruthy();
  });

  it("separates company disposition from warehouse quantity status and moves secondary data to details", async () => {
    serve([item(1, { disposition: "RELEASED", quarantined_quantity: "3" })]);
    renderPage();
    await screen.findAllByText("Product 1");
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: /Disposition Company-wide/ })).toBeTruthy();
    const stock = within(table).getByLabelText("Stock quantity status");
    expect(stock).toHaveTextContent("Quarantined quantity");
    expect(stock.closest("td")).not.toHaveTextContent("Released");
    expect(within(table).queryByRole("columnheader", { name: "Production date" })).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "Manage batch status" })[0]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Family A");
    expect(dialog).toHaveTextContent("SKU-1");
  });

  it("keeps nullable public lot, omitted costs, and read-only detail access without mutation authority", async () => {
    mocks.canManage = false;
    serve([item(1, { batch_number: null })]);
    const { container } = renderPage();
    await screen.findAllByText("No lot supplied");
    expect(container.textContent).not.toMatch(/WANASAH_NOLOT|acquisition|purchase cost|valuation/i);
    expect(screen.queryByRole("button", { name: "Manage batch status" })).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "View batch details" })[0]);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("inventoryBatches.disposition.noPermission")).toBeTruthy();
    for (const button of within(dialog).getAllByRole("button").slice(1)) expect(button).toBeDisabled();
  });

  it("keeps native filter/action focus, traps only the open dialog, closes with Escape and restores focus", async () => {
    mocks.canManage = false;
    serve();
    renderPage();
    await screen.findAllByText("Product 1");
    const search = screen.getByRole("searchbox");
    search.focus();
    expect(search).toHaveFocus();
    const select = screen.getByRole("combobox", { name: "Expiry" });
    select.focus();
    expect(select).toHaveFocus();
    const trigger = screen.getAllByRole("button", { name: "View batch details" })[0];
    trigger.focus(); fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    const close = within(dialog).getByRole("button", { name: "common.close" });
    close.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
    search.focus(); expect(search).toHaveFocus();
  });

  it.each(["ar", "en"])("keeps %s direction, Western digits, compact phone rows and reachable actions", async (language) => {
    mocks.language = language;
    serve([item(1, { days_to_expiry: 5, batch_number: null })]);
    const { container } = renderPage();
    await screen.findAllByText(language === "ar" ? "بدون رقم دفعة" : "No lot supplied");
    expect(container.querySelector(".inventory-batches-view")).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
    expect(container.textContent).not.toMatch(/[\u0660-\u0669\u06f0-\u06f9]/);
    expect(container.textContent).toMatch(/5/);
    const mobile = container.querySelector(".md\\:hidden")!;
    expect(mobile).toHaveClass("divide-y");
    expect(mobile.querySelector("button")).toBeTruthy();
    expect(mobile.querySelector(".shadow-sm")).toBeNull();
    expect(container.querySelector(".hidden.md\\:block")).toHaveClass("overflow-auto");
  });

  it("provides distinct initial, continuation and summary retry surfaces", async () => {
    mocks.authFetch.mockRejectedValue(new Error("network"));
    renderPage();
    await screen.findByText("Could not load the batch index.");
    expect(screen.getAllByRole("alert")).toHaveLength(2);
    serve();
    fireEvent.click(screen.getAllByRole("button", { name: "Retry" }).at(-1)!);
    await screen.findAllByText("Product 1");
  });

  it("preserves deep-link resolution independently of the filtered list", async () => {
    const consumed = vi.fn();
    serve([]);
    const prior = mocks.authFetch.getMockImplementation()!;
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path === "/warehouse/batches/41/stock-sources") return {
        ...item(41), product_variant_id: 141, base_uom_id: 1, base_uom_code: "EACH",
        operational_hold: "NONE", sources: [],
      };
      return prior(path);
    });
    renderPage({ batchId: 41, variantId: 141, productName: "Untrusted label" }, consumed);
    await screen.findByRole("dialog");
    await waitFor(() => expect(consumed).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Untrusted label")).toBeNull();
    expect(mocks.authFetch.mock.calls.some(([path]) => path === "/warehouse/batches/41/stock-sources")).toBe(true);
  });

  it("keeps cost and command authorities out of the presentation diff", () => {
    const root = resolve(process.cwd(), "src/pages/inventory/batches");
    const source = ["BatchIndexTable.tsx", "BatchIndexSignals.tsx", "batchPresentation.ts"].map((p) => readFileSync(resolve(root, p), "utf8")).join("\n");
    expect(source).not.toMatch(/input_unit_cost|total_cost|latest_purchase_cost|cost\.read|is_admin|is_superuser/);
    expect(source).not.toMatch(/minimum_remaining_shelf_life_days\s*[<>]=?|sellability_state\s*=(?!=)/);
    expect(batchIndexText(t, "ar", "stockStatusColumn")).not.toBe(batchIndexText(t, "en", "stockStatusColumn"));
  });
});
