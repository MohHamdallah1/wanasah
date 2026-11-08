import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildLedgerOperationUrl, parseLedgerOperationPage } from "@/pages/inventory/ledger/operationContracts";
import { Tab4Ledger } from "@/pages/inventory/Tab4Ledger";
import { LedgerOperationRows } from "@/pages/inventory/ledger/LedgerOperationRows";
import { useLedgerOperations } from "@/pages/inventory/ledger/useLedgerOperations";
import { LEDGER_OPERATION_REFERENCE_TYPES, parseLedgerOperationFailure } from "@/pages/inventory/ledger/operationI18n";
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

  it("offers all recorded special transfer, disposal and quality stage filters", () => {
    expect(LEDGER_OPERATION_REFERENCE_TYPES).toContain("SPECIAL_TRANSFER_DISPATCH");
    expect(LEDGER_OPERATION_REFERENCE_TYPES).toContain("SPECIAL_TRANSFER_TERMINAL_STATUS");
    expect(LEDGER_OPERATION_REFERENCE_TYPES).toContain("FINAL_DISPOSAL");
    expect(LEDGER_OPERATION_REFERENCE_TYPES).toContain("QUALITY_HANDLING_STAGE");
    expect(LEDGER_OPERATION_REFERENCE_TYPES).toContain("VISIT_SAMPLE_OUT");
  });

  it("rejects unknown cursors and preserves the next signed cursor", () => {
    expect(() => parseLedgerOperationPage({ ...parent([]), next_cursor: 13, has_more: true })).toThrow();
    expect(() => parseLedgerOperationPage({ ...parent([]), next_cursor: null, has_more: true })).toThrow();
    expect(parseLedgerOperationPage(parent([], "signed-page")).next_cursor).toBe("signed-page");
  });

  it("shows safe structured parent 422 reason, context and request ID; retry retains scope", async () => {
    let calls = 0;
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (!path.includes("/operations/cursor")) throw new Error("Unexpected endpoint");
      calls++;
      if (calls === 1) throw {
        status: 422, code: "LEDGER_REFERENCE_INVALID", context: { field: "reference_type" },
        requestId: "req-parent-818", serverMessage: "internal details must not leak",
      };
      return parent([operation(1)]);
    });
    renderLedger();
    expect(await screen.findByText(/Request ID/)).toBeInTheDocument();
    expect(screen.getByText(/req-parent-818/)).toBeInTheDocument();
    expect(screen.getByText(/LEDGER_REFERENCE_INVALID/)).toBeInTheDocument();
    expect(screen.getByText(/field: reference_type/)).toBeInTheDocument();
    expect(screen.queryByText(/internal details must not leak/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("50 products")).toBeInTheDocument());
    expect(calls).toBe(2);
  });

  it("shows child 400 rejection and request ID without leaking server details", async () => {
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.includes("/operations/signed-group-1/movements/cursor")) throw {
        status: 400, code: "LEDGER_CURSOR_INVALID", context: { reason: "stale_cursor" },
        requestId: "req-child-818", serverMessage: "private stack or SQL",
      };
      if (path.includes("/operations/cursor")) return parent([operation(1)]);
      throw new Error("Unexpected endpoint");
    });
    renderLedger();
    fireEvent.click(await screen.findByRole("button", { name: "Details: REF-SAME" }));
    expect(await screen.findByText(/req-child-818/)).toBeInTheDocument();
    expect(screen.getByText(/LEDGER_CURSOR_INVALID/)).toBeInTheDocument();
    expect(screen.queryByText(/private stack or SQL/)).not.toBeInTheDocument();
  });

  it("shows a 503 request ID but never its internal error code or context", async () => {
    mocks.authFetch.mockRejectedValue({
      status: 503, code: "DATABASE_INTERNAL_ERROR",
      context: { reason: "secret_connection_string" }, requestId: "req-service-503",
      serverMessage: "sensitive traceback",
    });
    renderLedger();
    expect(await screen.findByText(/req-service-503/)).toBeInTheDocument();
    expect(screen.getByText(/temporarily unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/DATABASE_INTERNAL_ERROR/)).not.toBeInTheDocument();
    expect(screen.queryByText(/secret_connection_string/)).not.toBeInTheDocument();
    expect(screen.queryByText(/sensitive traceback/)).not.toBeInTheDocument();
  });

  it("continues an empty authorized group page through a real signed cursor", async () => {
    const requested: string[] = [];
    mocks.authFetch.mockImplementation(async (path: string) => {
      requested.push(path);
      if (path.includes("cursor=signed-next")) return parent([operation(1)]);
      return parent([], "signed-next");
    });
    const hook = renderHook(() => useLedgerOperations(11, 0, true, "", "ALL", null));
    await waitFor(() => expect(hook.result.current.hasMore).toBe(true));
    expect(hook.result.current.items).toHaveLength(0);
    await act(async () => hook.result.current.loadMore());
    await waitFor(() => expect(hook.result.current.items).toHaveLength(1));
    expect(requested.some(path => path.includes("cursor=signed-next"))).toBe(true);
    hook.unmount();
  });

  it("keeps signed continuation state on reentry but resets it on Refresh", async () => {
    const requested: string[] = [];
    mocks.authFetch.mockImplementation(async (path: string) => {
      requested.push(path);
      if (path.includes("cursor=signed-next")) return parent([operation(2)], null);
      return parent([operation(1)], "signed-next");
    });
    const hook = renderHook(({active}) => useLedgerOperations(11, 0, active, "", "ALL", null), {
      initialProps: { active: true },
    });
    await waitFor(() => expect(hook.result.current.hasMore).toBe(true));
    await act(async () => hook.result.current.loadMore());
    await waitFor(() => expect(hook.result.current.items).toHaveLength(2));
    await act(async () => hook.rerender({ active: false }));
    await act(async () => hook.rerender({ active: true }));
    await waitFor(() => expect(requested.length).toBeGreaterThanOrEqual(3));
    expect(hook.result.current.items).toHaveLength(2);
    await act(async () => hook.result.current.refresh());
    await waitFor(() => expect(hook.result.current.items).toHaveLength(1));
    expect(hook.result.current.hasMore).toBe(true);
    hook.unmount();
  });

  it("keeps context bounded and rejects arbitrary server payloads", () => {
    expect(parseLedgerOperationFailure({
      status: 422, code: "LEDGER_INVALID", requestId: "req-safe-818",
      context: { field: "reference_type", password: "do-not-display" },
    })).toEqual({
      status: 422, code: "LEDGER_INVALID", requestId: "req-safe-818",
      context: "field: reference_type",
    });
  });

  it("survives transient raw search changes before debounce without a frozen first read", async () => {
    let finish!: (value: unknown) => void;
    const first = new Promise<unknown>(resolve => { finish = resolve; });
    mocks.authFetch.mockImplementation(() => first);
    const hook = renderHook(({ search }) =>
      useLedgerOperations(11, 0, true, search, "ALL", null),
    { initialProps: { search: "" } });
    await waitFor(() => expect(mocks.authFetch).toHaveBeenCalledTimes(1));
    await act(async () => {
      hook.rerender({ search: "temporary" });
      hook.rerender({ search: "" });
    });
    await act(async () => finish(parent([operation(3)])));
    await waitFor(() => expect(hook.result.current.items).toHaveLength(1));
    expect(hook.result.current.loading).toBe(false);
    expect(hook.result.current.error).toBe(false);
    hook.unmount();
  });

  it.each([401, 403, 404])("fails closed for rejected grouped read HTTP %i", async status => {
    mocks.authFetch.mockRejectedValue({ status, code: "LEDGER_ACCESS_CHANGED", requestId: "req-denied" });
    const { container } = renderLedger();
    await waitFor(() => expect(container.querySelector('[data-ledger-operation-row="true"]')).toBeNull());
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText("req-denied")).not.toBeInTheDocument();
  });

  it("recovers a canceled Refresh during tab switch with a new first-page snapshot", async () => {
    let finishRefresh!: (value: unknown) => void;
    const pendingRefresh = new Promise<unknown>(resolve => { finishRefresh = resolve; });
    let count = 0;
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.includes("cursor=second")) return parent([operation(2)]);
      count++;
      if (count === 2) return pendingRefresh;
      return parent([operation(3)], "second");
    });
    const hook = renderHook(({ active }) => useLedgerOperations(11, 0, active, "", "ALL", null), {
      initialProps: { active: true },
    });
    await waitFor(() => expect(hook.result.current.items).toHaveLength(1));
    await act(async () => hook.result.current.loadMore());
    await waitFor(() => expect(hook.result.current.items).toHaveLength(2));
    // Start a fresh snapshot, then navigate away before its first page arrives.
    await act(async () => hook.result.current.refresh());
    await act(async () => hook.rerender({ active: false }));
    await act(async () => hook.rerender({ active: true }));
    await act(async () => finishRefresh(parent([operation(4)], "new-signed")));
    await waitFor(() => expect(hook.result.current.items.length).toBeGreaterThan(0));
    expect(hook.result.current.items.some(row => row.group_key === "signed-group-4")).toBe(false);
    expect(hook.result.current.hasMore).toBe(true);
    hook.unmount();
  });

  it("does not misrepresent alphabetically sorted transfer stages as a latest status", async () => {
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.includes("/operations/cursor")) return parent([operation(6, {
        group_kind: "TRANSFER", operation_type: "TRANSFER",
        source_location_name: null, destination_location_name: null,
        stage_types: ["TRANSFER_CANCELLED", "TRANSFER_DISPATCH"],
      })]);
      throw new Error("Unexpected endpoint: " + path);
    });
    const { container } = renderLedger();
    await waitFor(() => expect(container.querySelectorAll('[data-ledger-operation-row="true"]')).toHaveLength(1));
    const row = container.querySelector('[data-ledger-operation-row="true"]')!;
    expect(row.textContent).toContain("Transfer cancellation");
    expect(row.textContent).toContain("Transfer dispatch");
    expect(row.textContent).not.toContain("Latest stage");
  });

  it("keeps safe Arabic reason values but never arbitrary sensitive server context", () => {
    expect(parseLedgerOperationFailure({
      status: 422, code: "LEDGER_INVALID", context: { reason: "مرجع_غير_صالح", auth_token: "secret" },
      requestId: "req-ar-818",
    })).toEqual({ status: 422, code: "LEDGER_INVALID",
      requestId: "req-ar-818", context: "reason: مرجع_غير_صالح" });
  });

});
