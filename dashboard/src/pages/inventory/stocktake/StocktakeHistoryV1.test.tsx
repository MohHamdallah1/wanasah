import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StocktakeHistoryDialog } from "./StocktakeHistoryDialog";
import type { StocktakeAuthFetch } from "./types";

const locale = vi.hoisted(() => ({ current: "ar" }));
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({ i18n: {
      language: locale.current,
      resolvedLanguage: locale.current,
      dir: () => locale.current === "ar" ? "rtl" : "ltr",
    }, t: (key: string) => key }),
  };
});

const session = (id: number, status: "POSTED" | "CANCELLED" = "CANCELLED") => ({
  id, reference_number: "STK-" + id, status,
  stocktake_type: "CYCLE_COUNT", location_id: 11,
  scope_product_name: "Real chickpeas", scope_batch_number: "REAL-LOT-9",
  created_at: "2026-11-06T08:00:00Z", finished_at: "2026-11-06T09:00:00Z",
  started_by_name: "Owner", counted_by_name: status === "POSTED" ? "Counter" : "Owner",
  attempt_number: 1, approved_by_name: status === "POSTED" ? "Approver" : null,
  cancelled_by_name: status === "CANCELLED" ? "Owner" : null,
  cancellation_reason: status === "CANCELLED" ? "Physical recount aborted" : null,
  cancelled_after_count: status === "CANCELLED",
});
const detail = (id: number) => ({
  session: {
    id, reference_number: "STK-" + id, status: "CANCELLED",
    stocktake_type: "CYCLE_COUNT", location_id: 11,
    scope_product_name: "Real chickpeas", scope_batch_number: "REAL-LOT-9",
    created_at: "2026-11-06T08:00:00Z", finished_at: "2026-11-06T09:00:00Z",
    snapshot_cutoff_at: "2026-11-06T08:00:00Z",
    cancellation_reason: "Physical recount aborted", notes: "Auditable note",
    cancelled_after_count: true, adjustment_movement_count: 0,
  },
  attempts: { items: [
    { id: 501, attempt_number: 2, counted_by_name: "Second Counter",
      submitted_at: "2026-11-06T08:40:00Z", recount_reason: "Recheck", requires_independent_recount: false,
      recount_of_attempt_id: 500 },
    { id: 500, attempt_number: 1, counted_by_name: "First Counter",
      submitted_at: "2026-11-06T08:20:00Z", recount_reason: null, requires_independent_recount: true,
      recount_of_attempt_id: null },
  ], next_cursor: null, has_more: false },
  movements: { items: [], next_cursor: null, has_more: false },
  audit: { items: [
    { id: 999, action_type: "STOCKTAKE_CANCELLED", actor_name: "Owner",
      timestamp: "2026-11-06T09:00:00Z", details: { reason: "Physical recount aborted" } },
    { id: 998, action_type: "STOCKTAKE_COUNT_SUBMITTED", actor_name: "Counter",
      timestamp: "2026-11-06T08:40:00Z", details: { attempt_number: 2 } },
  ], next_cursor: null, has_more: false },
});
const batchLine = (id: number) => ({
  id, product_name: "Real chickpeas", batch_number: "REAL-LOT-9",
  stock_status: "QUARANTINED", line_origin: "SNAPSHOT",
  base_uom_name: "Each", expected_quantity: "12",
  actual_quantity: id === 700 ? "8" : "10", variance_quantity: id === 700 ? "-4" : "-2",
});
const defaultFetcher = async (url: string) => {
  const request = new URL(url, "https://example.invalid");
  const path = request.pathname;
  if (request.searchParams.get("location_id") !== "11") throw Error("Foreign warehouse");
  if (path.endsWith("/history")) return {
    items: [session(91), session(92, "POSTED")], next_cursor: null, has_more: false,
  };
  if (path.endsWith("/history/91")) return detail(91);
  if (path.endsWith("/history/92")) return {
    ...detail(92), session: { ...detail(92).session, status: "POSTED",
      cancellation_reason: null, cancelled_after_count: false, adjustment_movement_count: 2 },
    movements: {items: [
      { id: 8001, reference_id: "STK-92", quantity: "-0.25", product_variant_id: 1, batch_id: 2 },
      { id: 8002, reference_id: "STK-92", quantity: "0.001", product_variant_id: 1, batch_id: 2 },
    ], next_cursor: null, has_more: false},
  };
  if (path.endsWith("/attempts/501/lines")) return {
    items: [batchLine(700),
      { ...batchLine(702), id: 702, variance_quantity: "-0.25", actual_quantity: "11.75" },
      { ...batchLine(703), id: 703, variance_quantity: "-0.001", actual_quantity: "11.999" },
      { ...batchLine(704), id: 704, variance_quantity: "-0.000", actual_quantity: "12" },
    ], next_cursor: "more-lines", has_more: true,
  };
  if (path.endsWith("/attempts/500/lines")) return {
    items: [batchLine(701)], next_cursor: null, has_more: false,
  };
  throw Error("Unexpected request " + path);
};
const fetcher = vi.fn(async (url: string): Promise<unknown> => defaultFetcher(url));
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return {promise, resolve};
};
function Harness({ canReview = true }: { canReview?: boolean }) {
  const [locationId, setLocation] = useState(11);
  return <div>
    <button onClick={() => setLocation(12)}>Change warehouse</button>
    <StocktakeHistoryDialog active locationId={locationId}
      canRead canReview={canReview} authenticatedFetch={fetcher as StocktakeAuthFetch} />
  </div>;
}
beforeEach(() => { locale.current = "ar"; fetcher.mockReset(); fetcher.mockImplementation(defaultFetcher); });

describe("Stocktake #799 terminal history (never a blind counting surface)", () => {
  it.each(["ar", "en"] as const)("preserves signed canonical fractional shortages and zero in %s", async lang => {
    locale.current = lang;
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: lang === "ar" ? "سجل الجرد" : "Stocktake history" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toHaveTextContent("STK-91"));
    fireEvent.click(within(dialog).getAllByRole("button", { name: lang === "ar" ? "التفاصيل" : "Details" })[0]);
    await waitFor(() => expect(dialog).toHaveTextContent("-0.25 Each"));
    expect(dialog).toHaveTextContent("-0.001 Each");
    expect(within(dialog).getByText("0 Each", {exact: true})).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent("-0 Each");
    fireEvent.click(within(dialog).getByRole("button", { name: lang === "ar" ? "العودة للسجل" : "Back to history" }));
    fireEvent.click(within(dialog).getAllByRole("button", { name: lang === "ar" ? "التفاصيل" : "Details" })[1]);
    await waitFor(() => expect(dialog).toHaveTextContent("STK-92"));
    expect(dialog).toHaveTextContent("-0.25");
    expect(dialog).toHaveTextContent("0.001");
    expect(dialog).not.toHaveTextContent("#8001");
    expect(dialog).not.toHaveTextContent("#8002");
  });

  it.each(["ar", "en"] as const)("close while detail pending then reopen discards stale response and clears spinner in %s", async lang => {
    locale.current = lang;
    const pending = deferred<ReturnType<typeof detail>>();
    fetcher.mockImplementation(async (url: string) =>
      url.includes("/history/91?") ? pending.promise : defaultFetcher(url));
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: lang === "ar" ? "سجل الجرد" : "Stocktake history" });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toHaveTextContent("STK-91"));
    fireEvent.click(within(dialog).getAllByRole("button", { name: lang === "ar" ? "التفاصيل" : "Details" })[0]);
    await waitFor(() => expect(dialog).toHaveTextContent(lang === "ar" ? "جاري تحميل سجل الجرد" : "Loading stocktake history"));
    fireEvent.keyDown(dialog, { key: "Escape", code: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(trigger);
    const reopened = await screen.findByRole("dialog");
    await waitFor(() => expect(reopened).toHaveTextContent("STK-92"));
    pending.resolve(detail(91));
    await waitFor(() => expect(reopened).not.toHaveTextContent("Auditable note"));
    expect(within(reopened).getAllByRole("button", {name: lang === "ar" ? "التفاصيل" : "Details"})).toHaveLength(2);
    fireEvent.click(within(reopened).getAllByRole("button", {name: lang === "ar" ? "التفاصيل" : "Details"})[1]);
    await waitFor(() => expect(reopened).toHaveTextContent("STK-92"));
  });

  it("back and new session ignore slow attempts pagination and slow lines without stuck spinners", async () => {
    locale.current = "en";
    const oldLines = deferred<unknown>();
    const oldPage = deferred<unknown>();
    fetcher.mockImplementation(async (url: string) => {
      if (url.includes("/history/91/attempts/501/lines?")) return oldLines.promise;
      if (url.includes("/history/91/attempts?") && url.includes("cursor=old-attempt-page")) return oldPage.promise;
      if (url.includes("/history/91?")) return {
        ...detail(91), attempts: { ...detail(91).attempts, next_cursor: "old-attempt-page", has_more: true },
      };
      return defaultFetcher(url);
    });
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Stocktake history" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toHaveTextContent("STK-91"));
    fireEvent.click(within(dialog).getAllByRole("button", {name: "Details"})[0]);
    await waitFor(() => expect(dialog).toHaveTextContent("STK-91"));
    const more = within(dialog).getByRole("button", {name: "Load more"});
    fireEvent.click(more);
    await waitFor(() => expect(more).toBeDisabled());
    fireEvent.click(within(dialog).getByRole("button", {name: "Back to history"}));
    await waitFor(() => expect(within(dialog).getAllByRole("button", {name: "Details"})).toHaveLength(2));
    fireEvent.click(within(dialog).getAllByRole("button", {name: "Details"})[1]);
    await waitFor(() => expect(dialog).toHaveTextContent("STK-92"));
    oldLines.resolve({ items: [{...batchLine(987), product_name: "STALLED-OLD-LINES"}], next_cursor: null, has_more: false});
    oldPage.resolve({ items: [{
      id: 999, attempt_number: 99, counted_by_name: "STALLED-OLD-ATTEMPT",
      submitted_at: "2026-11-06T08:20:00Z", recount_reason: null,
      authorized_by_name: null, requires_independent_recount: false, recount_of_attempt_id: null,
    }], next_cursor: null, has_more: false});
    await waitFor(() => expect(dialog).not.toHaveTextContent("STALLED-OLD-ATTEMPT"));
    expect(dialog).not.toHaveTextContent("STALLED-OLD-LINES");
    // The new session legitimately has another line page. Its button must be
    // enabled, not disabled by stale pagination from the previous session.
    await waitFor(() => expect(within(dialog).getByRole("button", {name: "Load more"})).toBeEnabled());
  });

  it.each(["ar", "en"] as const)("shows terminal-only list and sensitive gated immutable attempts in %s", async lang => {
    locale.current = lang;
    render(<Harness />);
    const trigger = screen.getByRole("button", {
      name: lang === "ar" ? "سجل الجرد" : "Stocktake history",
    });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    await waitFor(() => expect(within(dialog).getAllByRole("listitem")).toHaveLength(2));
    expect(dialog).toHaveTextContent("STK-91");
    expect(dialog).toHaveTextContent("STK-92");
    expect(dialog).toHaveTextContent(lang === "ar" ? "تم الإلغاء بعد تثبيت العد" : "Cancelled after count submission");
    expect(dialog).not.toHaveTextContent("12 Each");
    fireEvent.click(within(dialog).getAllByRole("button", {
      name: lang === "ar" ? "التفاصيل" : "Details",
    })[0]);
    await waitFor(() => expect(dialog).toHaveTextContent("Auditable note"));
    await waitFor(() => expect(dialog).toHaveTextContent("12 Each"));
    expect(dialog).toHaveTextContent("8 Each");
    expect(dialog).toHaveTextContent("-4 Each");
    expect(dialog).toHaveTextContent("REAL-LOT-9");
    expect(dialog).toHaveTextContent(lang === "ar" ? "معزول" : "Quarantined");
    expect(dialog).toHaveTextContent("First Counter");
    fireEvent.click(within(dialog).getByRole("button", {
      name: (lang === "ar" ? "محاولة العد" : "Count attempt") + " #1 · First Counter",
    }));
    await waitFor(() => expect(dialog).toHaveTextContent("10 Each"));
    expect(dialog).toHaveTextContent(lang === "ar" ? "سجل الإجراءات" : "Audit events");
    expect(dialog).toHaveTextContent("Physical recount aborted");
    fireEvent.click(within(dialog).getByRole("button", {
      name: lang === "ar" ? "العودة للسجل" : "Back to history",
    }));
    expect(dialog).toHaveTextContent("STK-92");
    fireEvent.keyDown(dialog, { key: "Escape", code: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });
  it.each(["ar", "en"] as const)("count-only cannot open expected-versus-actual details in %s", async lang => {
    locale.current = lang;
    render(<Harness canReview={false} />);
    fireEvent.click(screen.getByRole("button", {
      name: lang === "ar" ? "سجل الجرد" : "Stocktake history",
    }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toHaveTextContent("STK-91"));
    const reviewButtons = within(dialog).getAllByRole("button", {
      name: lang === "ar" ? "التفاصيل" : "Details",
    });
    expect(reviewButtons).toHaveLength(2);
    expect(reviewButtons.every(button => button.hasAttribute("disabled"))).toBe(true);
    fireEvent.click(reviewButtons[0]);
    expect(fetcher.mock.calls.every(call => !call[0].includes("/history/91"))).toBe(true);
    expect(dialog).not.toHaveTextContent("12 Each");
  });
  it.each(["ar", "en"] as const)("preserves authorized 403 reason and retry after history read failure in %s", async lang => {
    locale.current = lang;
    fetcher.mockImplementationOnce(async () => {
      throw { status: 403, code: "STOCKTAKE_DENIED", serverMessage: "Selected warehouse access denied", requestId: "trace-123" };
    });
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", {
      name: lang === "ar" ? "سجل الجرد" : "Stocktake history",
    }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByRole("alert")).toHaveTextContent("Selected warehouse access denied"));
    expect(dialog).not.toHaveTextContent("trace-123");
    fireEvent.click(within(dialog).getByRole("button", { name: lang === "ar" ? "إعادة المحاولة" : "Retry" }));
    await waitFor(() => expect(dialog).toHaveTextContent("STK-91"));
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
  });
  it("keeps decimal quantity strings canonical in data and locale-formatted only in the review view", async () => {
    locale.current = "ar";
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "سجل الجرد" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toHaveTextContent("STK-91"));
    fireEvent.click(within(dialog).getAllByRole("button", { name: "التفاصيل" })[0]);
    await waitFor(() => expect(dialog).toHaveTextContent("12 Each"));
    expect(dialog).toHaveTextContent("-4 Each");
    expect(dialog).toHaveTextContent("الكمية المسجلة");
  });

  it("closes and rejects retained history when the authorized warehouse changes", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "سجل الجرد" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveTextContent("STK-91"));
    fireEvent.click(screen.getByText("Change warehouse"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
