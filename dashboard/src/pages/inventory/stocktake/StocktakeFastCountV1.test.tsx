import { useState } from "react";
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StocktakeRow } from "../inventoryUtils";
import { StocktakeCountingPanel } from "./StocktakeCountingPanel";
import { useStocktakeCounting, isRowReadyForCountSubmit } from "./hooks/useStocktakeCounting";
import type { StocktakeAuthFetch, StocktakeReview } from "./types";

const locale = vi.hoisted(() => ({ value: "ar" }));
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({
      i18n: { language: locale.value, resolvedLanguage: locale.value, dir: () => locale.value === "ar" ? "rtl" : "ltr" },
      t: (key: string) => key,
    }),
  };
});
vi.mock("@/hooks/useInventoryAccess", () => ({
  parseInventoryCapabilities: (raw: unknown) => raw,
  hasInventoryPermission: () => true,
}));
vi.mock("./durableCommand", () => ({
  executeStocktakeDurableCommand: vi.fn(async ({
    payload, send,
  }: { payload: unknown; send: (value: unknown) => Promise<unknown> }) => send(payload)),
}));

const sheetRow = (id: number, dual = false) => ({
  product_variant_id: 118, batch_id: id, stock_status: "AVAILABLE",
  product_name: "Physical product", batch_number: `REAL-LOT-${id}`,
  expiry_date: "2027-06-01",
  base_uom_id: 7, base_uom_code: "EACH", base_uom_name: "Each",
  quantity_scale: 0, quantity_step: "1",
  ...(dual ? {
    count_outer_uom_id: 13, count_outer_uom_name: "Carton", count_outer_uom_code: "CTN",
    count_outer_factor_numerator: 50, count_outer_factor_denominator: 1,
  } : {}),
});

const key = "wanasah_audit_draft:1:11:45";
const read = (count = 1, dual = false) => Array.from({ length: count }, (_, i) => sheetRow(51 + i, dual && i === 0));
function makeFetch(count = 1, dual = false) {
  const requests: { url: string; opts?: RequestInit }[] = [];
  const fetched: StocktakeAuthFetch = async (url, opts) => {
    requests.push({ url, opts });
    if (url.startsWith("/inventory/access/me")) return { location_id: 11 };
    if (url.endsWith("/count-sheet")) return read(count, dual);
    if (url.endsWith("/count") && opts?.method === "POST") return { attempt_id: 1 };
    throw new Error(`Unexpected request: ${url}`);
  };
  return { fetched, requests };
}
function useFixture(fetch: StocktakeAuthFetch) {
  const [rows, setRows] = useState<StocktakeRow[]>([]);
  const [phase, setPhase] = useState<"COUNTING" | "REVIEW" | "WAITING_INDEPENDENT">("COUNTING");
  const [sessionId, setSessionId] = useState<string | null>("45");
  const [sessionLocationId, setSessionLocationId] = useState<number | null>(11);
  const [review, setReview] = useState<StocktakeReview | null>(null);
  const counting = useStocktakeCounting({
    durableIdentity: { companyId: 1, backofficeUserId: 17 },
    companyScope: "1", phaseKey: "phase:1:11", phase, sessionId,
    sessionLocationId, draftKey: key,
    authenticatedFetch: fetch, rows, setRows, setReview,
    setSessionId, setSessionLocationId, setPhase,
    onSubmitted: vi.fn(async () => {}),
  });
  return { ...counting, rows, review };
}
beforeEach(() => {
  localStorage.clear();
  locale.value = "ar";
});

describe("Stocktake V1 exact physical count / explicit zero / draft invariant", () => {
  it("loads five blank rows, counts none, and cannot submit uncounted or invalid rows", async () => {
    const { fetched, requests } = makeFetch(5);
    const { result, unmount } = renderHook(() => useFixture(fetched));
    await act(async () => { await result.current.loadCountSheet("45", 11); });
    expect(result.current.rows).toHaveLength(5);
    expect(result.current.rows.every(row => row.actual_quantity === "" && !row.counted)).toBe(true);
    expect(result.current.countProgress).toEqual({ total: 5, counted: 0, remaining: 5 });
    await act(async () => { expect(await result.current.handleSubmit()).toBe(false); });
    expect(requests.some(request => request.opts?.method === "POST")).toBe(false);
    const first = result.current.rows[0].row_key;
    act(() => result.current.updateRow(first, "1.5")); // integer base scale/step violation
    expect(result.current.rows[0].counted).toBe(false);
    act(() => result.current.updateRow(first, "NaN"));
    expect(result.current.countProgress.counted).toBe(0);
    act(() => result.current.updateRow(first, ""));
    expect(result.current.rows[0].actual_quantity).toBe("");
    unmount();
  });

  it("does not conflate typed zero with physical zero confirmation; reversible even after editing", async () => {
    const { fetched } = makeFetch();
    const { result, unmount } = renderHook(() => useFixture(fetched));
    await act(async () => { await result.current.loadCountSheet("45", 11); });
    const rowKey = result.current.rows[0].row_key;
    act(() => result.current.updateRow(rowKey, "0"));
    expect(result.current.countProgress.counted).toBe(0);
    expect(result.current.rows[0].counted).toBe(false);
    act(() => result.current.confirmZeroCount(rowKey));
    expect(result.current.rows[0]).toMatchObject({ actual_quantity: "0", counted: true });
    expect(result.current.countProgress.counted).toBe(1);
    act(() => result.current.updateRow(rowKey, "17"));
    expect(result.current.rows[0]).toMatchObject({ actual_quantity: "17", counted: true });
    act(() => result.current.updateRow(rowKey, ""));
    expect(result.current.rows[0]).toMatchObject({ actual_quantity: "", counted: false });
    act(() => result.current.confirmZeroCount(rowKey));
    expect(result.current.rows[0].actual_quantity).toBe("0");
    act(() => result.current.undoRowCount(rowKey));
    expect(result.current.rows[0]).toMatchObject({ actual_quantity: "", counted: false });
    expect(result.current.countProgress.remaining).toBe(1);
    unmount();
  });

  it("restores old placeholder zero as blank but retains old explicitly counted zero", async () => {
    const old = { row_key: "118:51:AVAILABLE", actual_quantity: "0", counted: false };
    localStorage.setItem(key, JSON.stringify([old]));
    let fixture = makeFetch();
    let view = renderHook(() => useFixture(fixture.fetched));
    await act(async () => { await view.result.current.loadCountSheet("45", 11); });
    expect(view.result.current.rows[0]).toMatchObject({ actual_quantity: "", counted: false });
    view.unmount();
    localStorage.setItem(key, JSON.stringify([{ ...old, counted: true }]));
    fixture = makeFetch();
    view = renderHook(() => useFixture(fixture.fetched));
    await act(async () => { await view.result.current.loadCountSheet("45", 11); });
    expect(view.result.current.rows[0]).toMatchObject({ actual_quantity: "0", counted: true });
    expect(view.result.current.countProgress.remaining).toBe(0);
    view.unmount();
  });

  it("drafts and POSTs exactly 2 real cartons × 50 plus 7 loose as ONE base quantity", async () => {
    const { fetched, requests } = makeFetch(2, true);
    const view = renderHook(() => useFixture(fetched));
    await act(async () => { await view.result.current.loadCountSheet("45", 11); });
    const [outer, plain] = view.result.current.rows;
    expect(outer.actual_quantity).toBe("");
    act(() => view.result.current.updateCountPart(outer.row_key, "outer", "2"));
    act(() => view.result.current.updateCountPart(outer.row_key, "base", "7"));
    expect(view.result.current.rows[0]).toMatchObject({
      actual_quantity: "107", counted: true,
      count_outer_quantity: "2", count_base_quantity: "7",
    });
    act(() => view.result.current.updateRow(plain.row_key, "3"));
    expect(view.result.current.countProgress).toEqual({ total: 2, counted: 2, remaining: 0 });
    view.unmount(); // Flush exact durable count draft before starting a re-entry.
    const saved = JSON.parse(localStorage.getItem(key)!);
    expect(saved[0]).toMatchObject({ actual_quantity: "107", count_outer_quantity: "2", count_base_quantity: "7" });
    const reopened = renderHook(() => useFixture(fetched));
    await act(async () => { await reopened.result.current.loadCountSheet("45", 11); });
    expect(reopened.result.current.rows[0]).toMatchObject({
      actual_quantity: "107", counted: true,
      count_outer_quantity: "2", count_base_quantity: "7",
    });
    await act(async () => { expect(await reopened.result.current.handleSubmit()).toBe(true); });
    const post = requests.find(request => request.opts?.method === "POST")!;
    expect(post.url).toBe("/warehouse/unified/stocktake/45/count");
    const payload = JSON.parse(String(post.opts?.body));
    expect(payload.items).toEqual([
      { product_variant_id: 118, batch_id: 51, stock_status: "AVAILABLE", actual_quantity: "107", uom_id: 7 },
      { product_variant_id: 118, batch_id: 52, stock_status: "AVAILABLE", actual_quantity: "3", uom_id: 7 },
    ]);
    expect(JSON.stringify(payload)).not.toContain("count_outer_quantity");
    expect(localStorage.getItem(key)).toBeNull();
    reopened.unmount();
  });

  it("rejects invalid and tampered counted drafts at the final posting gate", async () => {
    const { fetched, requests } = makeFetch();
    const view = renderHook(() => useFixture(fetched));
    await act(async () => { await view.result.current.loadCountSheet("45", 11); });
    const k = view.result.current.rows[0].row_key;
    act(() => view.result.current.updateRow(k, "2"));
    expect(view.result.current.countProgress.remaining).toBe(0);
    act(() => view.result.current.updateRow(k, "-3"));
    expect(view.result.current.countProgress.remaining).toBe(1);
    act(() => view.result.current.updateRow(k, "1..2"));
    expect(view.result.current.countProgress.remaining).toBe(1);
    await act(async () => { expect(await view.result.current.handleSubmit()).toBe(false); });
    expect(requests.some(request => request.opts?.method === "POST")).toBe(false);
    expect(isRowReadyForCountSubmit({ ...view.result.current.rows[0], counted: true, actual_quantity: "1.5" })).toBe(false);
    view.unmount();
  });
});

const uiRow = (id: number, counted = false, dual = false): StocktakeRow => ({
  ...sheetRow(id, dual), stock_status: "AVAILABLE",
  row_key: `118:${id}:AVAILABLE`,
  actual_quantity: counted ? "2" : "", counted,
});

describe("Stocktake V1 AR/EN responsive visible-input keyboard safety", () => {
  it.each(["ar", "en"] as const)("arrows stay inside visible count inputs; last Enter cannot submit in %s", lang => {
    locale.value = lang;
    const submit = vi.fn(), update = vi.fn(), zero = vi.fn(), undo = vi.fn();
    const { container } = render(
      <StocktakeCountingPanel rows={[uiRow(51, true), uiRow(52, true)]}
        progress={{ total: 2, counted: 2, remaining: 0 }}
        onUpdateRow={update} onConfirmZero={zero} onUndoCount={undo}
        onAddDiscovered={vi.fn()} onRemoveDiscovered={vi.fn()}
        canCancel onCancel={vi.fn()} onSubmit={submit} />,
    );
    const desktop = Array.from(container.querySelectorAll<HTMLInputElement>("table input[data-stocktake-count-input='true']"));
    expect(desktop).toHaveLength(2);
    desktop.forEach(input => { input.getClientRects = () => [{ width: 24 }] as unknown as DOMRectList; });
    desktop[0].focus();
    fireEvent.keyDown(desktop[0], { key: "ArrowDown" });
    expect(desktop[1]).toHaveFocus();
    fireEvent.keyDown(desktop[1], { key: "ArrowUp" });
    expect(desktop[0]).toHaveFocus();
    fireEvent.keyDown(desktop[0], { key: "Enter" });
    expect(desktop[1]).toHaveFocus();
    fireEvent.keyDown(desktop[1], { key: "Enter" }); // Final counted line.
    expect(desktop[1]).toHaveFocus();
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getAllByRole("button", { name: new RegExp(lang === "ar" ? "إلغاء تأكيد العد" : "Undo count") })).toHaveLength(4);
    fireEvent.click(screen.getAllByRole("button", { name: new RegExp(lang === "ar" ? "إلغاء تأكيد العد" : "Undo count") })[0]);
    expect(undo).toHaveBeenCalledWith("118:51:AVAILABLE");
  });

  it.each(["ar", "en"] as const)("never offers Confirm Zero for discovered stock that must be positive in %s", lang => {
    locale.value = lang;
    const row = {
      ...uiRow(53), line_origin: "DISCOVERED" as const, actual_quantity: "", counted: false,
    };
    const zero = vi.fn(), remove = vi.fn();
    const { container } = render(<StocktakeCountingPanel rows={[row]}
      progress={{ total: 1, counted: 0, remaining: 1 }}
      onUpdateRow={vi.fn()} onConfirmZero={zero} onUndoCount={vi.fn()}
      onAddDiscovered={vi.fn()} onRemoveDiscovered={remove}
      canCancel onCancel={vi.fn()} onSubmit={vi.fn()} />);
    expect(container).toHaveTextContent(lang === "ar"
      ? "السطر المكتشف يحتاج كمية أكبر من صفر" : "Unlisted stock must be greater than zero");
    expect(screen.queryByRole("button", {
      name: /Confirm zero for|تأكيد صفر لـ/,
    })).not.toBeInTheDocument();
    expect(isRowReadyForCountSubmit({ ...row, actual_quantity: "0", counted: true })).toBe(false);
    fireEvent.click(screen.getAllByRole("button", {
      name: lang === "ar" ? "حذف السطر المكتشف" : "Remove discovered row",
    })[0]);
    expect(remove).toHaveBeenCalledWith(row.row_key);
    expect(zero).not.toHaveBeenCalled();
  });

  it.each(["ar", "en"] as const)("shows two count fields only with authorized conversion in %s, independently per batch", lang => {
    locale.value = lang;
    const updatePart = vi.fn(), submit = vi.fn();
    const { container } = render(<StocktakeCountingPanel rows={[uiRow(51, false, true), uiRow(52)]}
      progress={{ total: 2, counted: 0, remaining: 2 }}
      onUpdateRow={vi.fn()} onUpdatePart={updatePart} onConfirmZero={vi.fn()} onUndoCount={vi.fn()}
      onAddDiscovered={vi.fn()} onRemoveDiscovered={vi.fn()}
      canCancel onCancel={vi.fn()} onSubmit={submit} />);
    const mobile = container.querySelectorAll("article");
    expect(mobile).toHaveLength(2);
    expect(mobile[0].querySelectorAll("input[data-stocktake-count-input]")).toHaveLength(2);
    expect(mobile[1].querySelectorAll("input[data-stocktake-count-input]")).toHaveLength(1);
    const outer = mobile[0].querySelector<HTMLInputElement>('input[data-stocktake-part="outer"]')!;
    expect(outer.value).toBe("");
    fireEvent.change(outer, { target: { value: "2" } });
    expect(updatePart).toHaveBeenCalledWith("118:51:AVAILABLE", "outer", "2");
    expect(submit).not.toHaveBeenCalled();
  });
});
