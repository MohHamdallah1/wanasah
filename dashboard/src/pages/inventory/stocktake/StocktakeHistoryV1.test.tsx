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
const fetcher = vi.fn(async (url: string) => {
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
  };
  if (path.endsWith("/attempts/501/lines")) return {
    items: [batchLine(700)], next_cursor: "more-lines", has_more: true,
  };
  if (path.endsWith("/attempts/500/lines")) return {
    items: [batchLine(701)], next_cursor: null, has_more: false,
  };
  throw Error("Unexpected request " + path);
});
function Harness({ canReview = true }: { canReview?: boolean }) {
  const [locationId, setLocation] = useState(11);
  return <div>
    <button onClick={() => setLocation(12)}>Change warehouse</button>
    <StocktakeHistoryDialog active locationId={locationId}
      canRead canReview={canReview} authenticatedFetch={fetcher as StocktakeAuthFetch} />
  </div>;
}
beforeEach(() => { locale.current = "ar"; fetcher.mockClear(); });

describe("Stocktake #799 terminal history (never a blind counting surface)", () => {
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
  it("closes and rejects retained history when the authorized warehouse changes", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "سجل الجرد" }));
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveTextContent("STK-91"));
    fireEvent.click(screen.getByText("Change warehouse"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
