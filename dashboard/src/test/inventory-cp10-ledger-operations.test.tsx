import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildLedgerOperationUrl, parseLedgerOperationPage } from "@/pages/inventory/ledger/operationContracts";
import { Tab4Ledger } from "@/pages/inventory/Tab4Ledger";
import { LedgerOperationRows } from "@/pages/inventory/ledger/LedgerOperationRows";
import type { LedgerOperation } from "@/pages/inventory/ledger/operationContracts";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  language: "en",
  adjust: true,
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.authFetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({ can: (code: string) => code !== "ledger.adjust" || mocks.adjust }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("react-i18next", async (original) => {
  const actual = await original<typeof import("react-i18next")>();
  return { ...actual, useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      let value = String(opts?.defaultValue ?? key);
      Object.entries(opts ?? {}).forEach(([name, v]) => { value = value.split(`{{${name}}}`).join(String(v)); });
      return value;
    },
    i18n: { language: mocks.language, resolvedLanguage: mocks.language,
      dir: () => mocks.language === "ar" ? "rtl" : "ltr" },
  }) };
});

const operation = (id: number, extra: Record<string, unknown> = {}) => ({
  group_key: `signed-group-${id}`,
  group_kind: "RECEIPT", operation_type: "INBOUND_SUPPLIER",
  reference: "REF-SAME", latest_at: "2026-11-07T14:00:00+00:00",
  latest_movement_id: 100 + id, source_location_name: null,
  destination_location_name: "Warehouse", latest_actor_name: "Operator",
  stage_types: ["INBOUND_SUPPLIER"], movement_kinds: ["PHYSICAL"],
  movement_count: 51, product_variant_count: 50, batch_count: 51,
  expandable: true, count_meaning: "AUTHORIZED_IMMUTABLE_MOVEMENTS",
  stocktake_history: null, ...extra,
});
const parent = (rows: unknown[], next_cursor: string | null = null) => ({
  items: rows, next_cursor, has_more: next_cursor !== null,
  snapshot_max_movement_id: 1000,
  type_filter_semantics: "MATCH_ANY_CHILD_SHOW_ALL_AUTHORIZED",
});
const movement = (id: number, extra: Record<string, unknown> = {}) => ({
  id, product_variant_id: id, product_name: "Product " + id,
  base_uom_id: 1, base_uom_code: "EACH", quantity_scale: 0, quantity_step: "1",
  type: "INBOUND_SUPPLIER", reference_type: "INBOUND_SUPPLIER",
  movement_kind: "PHYSICAL", quantity: "1", balance_before: "0",
  balance_after: "1", balance_scope: "PRODUCT_LOCATION", batch_id: id,
  batch_number: "LOT-" + id, source_location_id: null, source_location_name: null,
  destination_location_id: 11, destination_location_name: "Warehouse",
  source_stock_status: null, destination_stock_status: "AVAILABLE",
  display_uom_id: 1, display_uom_code: "EACH", display_uom_name: "Each",
  display_factor_to_base: "1", currency_code: "JOD",
  cost_method: "FIFO", input_quantity: null, input_uom_code: null,
  input_uom_name: null, input_unit_cost: null, total_cost: "0.000000",
  average_cost_after: "1.000000", average_cost_uom_code: "EACH",
  average_cost_uom_name: "Each", admin_name: "Operator",
  reference: "REF-SAME", notes: "Posted physical event",
  supplier_name: "Proof Supplier", supplier_code: "SUP-01", supplier_id: 1,
  date: "2026-11-07T14:00:00+00:00", matches_filter: true, ...extra,
});
const children = (key: string, rows: unknown[], next_cursor: string | null = null) =>
  ({ group_key: key, items: rows, next_cursor, has_more: next_cursor !== null });

const renderLedger = () => render(
  <MemoryRouter initialEntries={["/inventory"]}>
    <Tab4Ledger locationId={11} refreshKey={0} onInventoryChanged={() => undefined} />
  </MemoryRouter>,
);

beforeEach(() => {
  mocks.authFetch.mockReset();
  mocks.language = "en";
  mocks.adjust = true;
});

describe("Ledger #818 authoritative operations", () => {
  it("parses two unrelated documents with identical display reference as distinct signed groups", () => {
    const parsed = parseLedgerOperationPage(parent([operation(1), operation(2)]));
    expect(parsed.items).toHaveLength(2);
    expect(parsed.items[0].group_key).not.toEqual(parsed.items[1].group_key);
    expect(parsed.items[0].movement_count).toBe(51);
    expect(parsed.items[0].product_variant_count).toBe(50);
    expect(() => parseLedgerOperationPage(parent([operation(1), operation(1)]))).toThrow("LEDGER_OPERATION_DUPLICATE");
    expect(() => parseLedgerOperationPage({ ...parent([]), type_filter_semantics: "UNKNOWN" })).toThrow();
  });

  it("builds the child endpoint from the opaque key and identical signed scope", () => {
    const url = buildLedgerOperationUrl({
      groupKey: "signed/token+opaque", locationId: 11, referenceId: "STK-ABC",
      referenceType: "AUDIT_ADJUSTMENT", cursor: "signed-next",
    });
    expect(url).toContain("signed%2Ftoken%2Bopaque");
    expect(url).toContain("reference_id=STK-ABC");
    expect(url).toContain("cursor=signed-next");
    expect(url).not.toContain("search=");
  });

  it("defaults to one operation row per server group and reveals immutable cost/lot evidence", async () => {
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.includes("/operations/signed-group-1/movements/cursor")) {
        return children("signed-group-1", [movement(101), movement(102, { batch_number: "LOT-102" })]);
      }
      if (path.includes("/operations/cursor")) return parent([operation(1), operation(2)]);
      throw new Error("Unexpected Ledger request: " + path);
    });
    const { container } = renderLedger();
    await waitFor(() => expect(container.querySelectorAll('[data-ledger-operation-row="true"]')).toHaveLength(2));
    expect(screen.getAllByText("REF-SAME").length).toBeGreaterThan(0);
    expect(screen.getAllByText("50 products").length).toBeGreaterThan(0);
    expect(screen.getAllByText("51 immutable movements").length).toBeGreaterThan(0);
    expect(screen.queryByText("Inventory value movement: 0.000000 JOD")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Details: REF-SAME" })[0]);
    expect(await screen.findByText("Product 101 · LOT-101")).toBeInTheDocument();
    expect(screen.getByText("Product 102 · LOT-102")).toBeInTheDocument();
    expect(screen.getAllByText(/Inventory value movement: 0.000000 JOD/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Posted physical event/).length).toBeGreaterThan(0);
    expect(document.querySelector('[data-ledger-child-id="101"]')).not.toBeNull();
    expect(document.querySelector('[data-ledger-child-id="102"]')).not.toBeNull();
  });

  it("shows real posted variances, not 50 fake stocktake movements", async () => {
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.includes("/operations/cursor")) return parent([operation(9, {
        group_kind: "STOCKTAKE", operation_type: "AUDIT_ADJUSTMENT", reference: "STK-50",
        movement_count: 7, product_variant_count: 7, batch_count: 7,
        count_meaning: "POSTED_VARIANCE_MOVEMENTS", stage_types: ["AUDIT_ADJUSTMENT"],
        stocktake_history: { session_id: 50, warehouse_location_id: 11, reference: "STK-50" },
      })]);
      if (path.includes("/operations/signed-group-9/movements/cursor"))
        return children("signed-group-9", [movement(99, {
          type: "AUDIT_ADJUSTMENT", reference_type: "AUDIT_ADJUSTMENT", reference: "STK-50",
        })]);
      throw new Error("Unexpected Ledger request: " + path);
    });
    renderLedger();
    expect(await screen.findByText("7 immutable movements")).toBeInTheDocument();
    expect(screen.getByText("Posted variances only")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Details: STK-50" }));
    expect(await screen.findByText(/These are posted stocktake variances only/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open stocktake history/ })).toBeInTheDocument();
    expect(screen.queryByText("50 immutable movements")).not.toBeInTheDocument();
  });

  it("purges the parent and child disclosure after a 403 during details", async () => {
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.includes("/operations/signed-group-1/movements/cursor")) throw { status: 403 };
      if (path.includes("/operations/cursor")) return parent([operation(1)]);
      throw new Error("Unexpected request: " + path);
    });
    const { container } = renderLedger();
    await screen.findByRole("button", { name: "Details: REF-SAME" });
    fireEvent.click(screen.getByRole("button", { name: "Details: REF-SAME" }));
    await waitFor(() => expect(container.querySelector('[data-ledger-operation-row="true"]')).toBeNull());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it.each(["ar", "en"] as const)("renders localized operation labels and no raw producer codes in %s", async language => {
    mocks.language = language;
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.includes("/operations/cursor")) return parent([operation(1, {
        stage_types: ["QUALITY_HANDLING_STAGE"], reference: "",
      })]);
      throw new Error("Unexpected request: " + path);
    });
    const { container } = renderLedger();
    await waitFor(() => expect(container.querySelectorAll('[data-ledger-operation-row="true"]')).toHaveLength(1));
    expect(screen.getByText(language === "ar" ? "عملية توريد" : "Supplier receipt")).toBeInTheDocument();
    expect(screen.queryByText("QUALITY_HANDLING_STAGE")).not.toBeInTheDocument();
    expect(container.querySelector('[dir="rtl"]') !== null).toBe(language === "ar");
  });
  it("mounts fewer than 100 operation rows even with 10,001 server groups", () => {
    const operations = Array.from({ length: 10001 }, (_, i) =>
      operation(i + 1) as unknown as LedgerOperation);
    const { container } = render(
      <LedgerOperationRows
        t={((_key: string, options?: Record<string, unknown>) => String(options?.defaultValue ?? _key)) as never}
        language="en" locale="en-US" items={operations} onDetails={vi.fn()}
        onNearBottom={vi.fn()} hasMore={false} loadingMore={false}
      />,
    );
    expect(operations).toHaveLength(10001);
    expect(container.querySelectorAll('[data-ledger-operation-row="true"]').length).toBeLessThan(100);
    expect(Number(container.querySelector('[data-ledger-operation-root="true"]')?.getAttribute("data-ledger-mounted"))).toBeLessThan(100);
  });

});
