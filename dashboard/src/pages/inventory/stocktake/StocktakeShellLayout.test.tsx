import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StocktakeSessionCenter } from "./StocktakeSessionCenter";
import { StocktakeHistoryDialog } from "./StocktakeHistoryDialog";
import type { StocktakeAuthFetch } from "./types";
import type { StocktakeSessionSummary } from "./types";

const locale = vi.hoisted(() => ({ value: "ar" }));
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({
      i18n: {
        language: locale.value,
        resolvedLanguage: locale.value,
        dir: () => locale.value === "ar" ? "rtl" : "ltr",
      },
      t: (key: string) => key,
    }),
  };
});

const session = (id: number, stocktake_type: StocktakeSessionSummary["stocktake_type"] = "CYCLE_COUNT"): StocktakeSessionSummary => ({
  id,
  reference_number: `STK-0000${id}`,
  stocktake_type,
  status: "COUNTING",
  location_id: 11,
  scope_product_variant_id: stocktake_type === "CYCLE_COUNT" ? id + 40 : null,
  scope_product_name: stocktake_type === "CYCLE_COUNT" ? `Product ${id}` : null,
  scope_batch_id: null,
  scope_batch_number: null,
  related_work_session_id: null,
  started_by: 17,
  started_by_name: "Warehouse Operator",
  pending_independent_recount_required: false,
  snapshot_cutoff_at: null,
  created_at: "2026-11-05T08:00:00Z",
  updated_at: "2026-11-05T08:00:00Z",
});

const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");
const main = read("src/pages/inventory/MainInventory.tsx");
const tab = read("src/pages/inventory/Tab3Stocktake.tsx");

function SessionsHarness({
  sessions = [session(77), session(78)],
  total = 3,
  currentSessionId = 77,
  canRead = true,
  onOpenSession = vi.fn(),
  onLoadMore = vi.fn(),
}: {
  sessions?: StocktakeSessionSummary[];
  total?: number;
  currentSessionId?: number | null;
  canRead?: boolean;
  onOpenSession?: (session: StocktakeSessionSummary) => void;
  onLoadMore?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <StocktakeSessionCenter
      sessions={sessions}
      total={total}
      loading={false}
      loadingMore={false}
      nextCursor={sessions.length ? "next" : null}
      currentSessionId={currentSessionId}
      open={open}
      onOpenChange={setOpen}
      canRead={canRead}
      onOpenSession={(value) => { onOpenSession(value); setOpen(false); }}
      onLoadMore={onLoadMore}
    />
  );
}

beforeEach(() => { locale.value = "ar"; });

describe("Stocktake #782 density shell: sessions dialog and shared workspace", () => {
  it.each([
    ["ar", "الجلسات (٣)", "جلسات الجرد النشطة", "فتح", "مفتوحة"],
    ["en", "Sessions (3)", "Active stocktake sessions", "Open", "Open"],
  ] as const)("opens a focused authorized dialog with switch, page, escape and focus return in %s", async (language, triggerName, title, openLabel, currentLabel) => {
    locale.value = language;
    const onOpenSession = vi.fn();
    const onLoadMore = vi.fn();
    render(<SessionsHarness onOpenSession={onOpenSession} onLoadMore={onLoadMore} />);
    const trigger = screen.getByRole("button", { name: triggerName });
    expect(trigger).toHaveAttribute("data-stocktake-sessions-trigger", "true");
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: title });
    expect(dialog).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
    const list = within(dialog).getByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    const buttons = within(list).getAllByRole("button");
    expect(buttons[0]).toHaveAccessibleName(currentLabel);
    expect(buttons[0]).toHaveAttribute("aria-current", "true");
    expect(buttons[0]).toBeDisabled();
    expect(buttons[1]).toHaveAccessibleName(openLabel);
    expect(buttons[1]).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: language === "ar" ? "تحميل المزيد" : "Load more" }));
    expect(onLoadMore).toHaveBeenCalledOnce();
    fireEvent.keyDown(dialog, { key: "Escape", code: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    fireEvent.click(trigger);
    const second = screen.getByRole("dialog", { name: title });
    fireEvent.click(within(within(second).getByRole("list")).getAllByRole("button")[1]);
    expect(onOpenSession).toHaveBeenCalledWith(expect.objectContaining({ id: 78, location_id: 11 }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it.each(["ar", "en"] as const)("shows one toolbar trigger with 0 and no page-height-consuming list in %s", (language) => {
    locale.value = language;
    render(<SessionsHarness sessions={[]} total={0} currentSessionId={null} />);
    const trigger = screen.getByRole("button", { name: language === "ar" ? "الجلسات (٠)" : "Sessions (0)" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("list")).not.toBeInTheDocument();
    expect(dialog).toHaveTextContent(language === "ar" ? "لا توجد جلسات جرد نشطة" : "There are no active stocktake sessions");
  });

  it("does not open an unauthorized session drawer", () => {
    render(<SessionsHarness canRead={false} />);
    const trigger = screen.getByRole("button", { name: "الجلسات (٣)" });
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("uses one MainInventory warehouse select with inline label only on admitted Stocktake", () => {
    expect(main).toContain('warehouseSelector={stocktakeShellAdmitted ? stocktakeWarehouseSelector : null}');
    expect(main).toContain('onChange={(event) => handleLocationChange(event.target.value)}');
    expect(main).toContain('batchIndexText(t, locale, "warehouseLabel")');
    expect(main).toContain('!stocktakeShellAdmitted && (');
    expect(main).toContain('locationTabScope !== null && tabAllowed("stocktake")');
    expect(main).toContain('activeTab !== "stocktake" && (');
    expect(main.match(/<select/g)?.length).toBeGreaterThanOrEqual(1);
    expect(main).toContain('data-it03-retained-tab="stocktake"');
    expect(main).toContain('key={`stocktake:${locationTabScope}`}');
  });

  it("places sessions/refresh/product count in one toolbar and never duplicates the counting table or door", () => {
    expect(tab).toContain('data-stocktake-toolbar="true"');
    expect(tab).toContain('const { copy: uiCopy } = useStocktakeUiCopy()');
    expect(tab).toContain('uiCopy.sessions.refresh');
    expect(tab).toContain('uiCopy.sessions.cycleAction');
    expect(tab).toContain('canRead={active && canReadStocktake}');
    expect(tab).toContain('open={showSessions}');
    expect(tab).toContain('onOpenSession={async (session) => {');
    expect(tab).toContain('onClick={refreshSessions}');
    expect(tab).toContain('onClick={() => setShowCycleModal(true)}');
    expect(tab).toContain('data-stocktake-workspace={workspacePhase}');
    expect(tab.match(/<StocktakeSessionCenter/g)).toHaveLength(1);
    expect(tab.match(/<StocktakeCountingPanel/g)).toHaveLength(1);
    expect(tab.match(/<StocktakeReviewPanel/g)).toHaveLength(1);
    expect(tab.match(/<StocktakeIdlePanel/g)).toHaveLength(1);
    expect(tab).toContain('warehouseAccess.can("stocktake.start")');
    expect(tab).toContain('sessionAccess.can("stocktake.count")');
    expect(tab).toContain('sessionAccess.can("stocktake.review")');
    expect(tab).toContain('sessionLocationId === locationId ? locationName : null');
  });
});


describe("Stocktake #799 immutable terminal history acceptance", () => {
  const posted = {
    id: 902, reference_number: "STK-POSTED-902", stocktake_type: "FULL_COUNT",
    status: "POSTED", location_id: 11, scope_product_name: null,
    started_by_name: "First Operator", approved_by_name: "Reviewer",
    cancelled_by_name: null, counted_by_name: "Counter", attempt_number: 1,
    cancelled_after_count: false, cancellation_reason: null,
    created_at: "2026-11-06T08:00:00Z", finished_at: "2026-11-06T09:00:00Z",
  };
  const cancelled = {
    ...posted, id: 901, reference_number: "STK-CANCEL-901", status: "CANCELLED",
    scope_product_name: "Chickpeas", cancelled_by_name: "Reviewer",
    approved_by_name: null, attempt_number: 1, cancelled_after_count: true,
    cancellation_reason: "Count investigated",
  };
  const detail = {
    session_id: 901, reference_number: cancelled.reference_number, status: "CANCELLED",
    cancellation_reason: cancelled.cancellation_reason, cancelled_after_count: true,
    created_at: cancelled.created_at, finished_at: cancelled.finished_at, notes: null,
    started_by_name: "First Operator", approved_by_name: null, cancelled_by_name: "Reviewer",
    attempts: [{ id: 701, attempt_number: 1, counted_by_name: "Counter",
      authorized_by_name: null, recount_reason: null, submitted_at: "2026-11-06T08:30:00Z",
      requires_independent_recount: false }],
    next_cursor: null, audit_next_cursor: null,
    audit: [{ id: 1, action_type: "STOCKTAKE_CANCELLED",
      actor_name: "Reviewer", at: "2026-11-06T09:00:00Z", old_value: null, new_value: null }],
  };

  function HistoryHarness({ fetcher, locationId = 11, enabled = true }: {
    fetcher: StocktakeAuthFetch; locationId?: number; enabled?: boolean;
  }) {
    const [open, setOpen] = useState(false);
    return <StocktakeHistoryDialog open={open} onOpenChange={setOpen} locationId={locationId}
      enabled={enabled} authenticatedFetch={fetcher} />;
  }

  it.each(["ar", "en"] as const)("lists terminal sessions and immutable count/audit by permitted location in %s", async language => {
    locale.value = language;
    const fetcher = vi.fn(async (url: string) => {
      if (url.includes("/history/attempts/701/lines")) return {
        items: [{ id: 9011, product_name: "Chickpeas", batch_id: 51,
          batch_number: "LOT-51", stock_status: "BLOCKED", line_origin: "SNAPSHOT",
          base_uom_name: "Each", base_uom_code: "EACH",
          expected_quantity: "50", actual_quantity: "47", variance_quantity: "-3" }],
        next_cursor: null,
      };
      if (url.includes("/901/history")) return detail;
      return { items: [posted, cancelled], next_cursor: null, has_more: false };
    });
    render(<HistoryHarness fetcher={fetcher} />);
    const title = language === "ar" ? "سجل الجرد" : "Stocktake history";
    fireEvent.click(screen.getByRole("button", { name: title }));
    const dialog = await screen.findByRole("dialog", { name: title });
    await waitFor(() => expect(within(dialog).getByText("STK-CANCEL-901")).toBeInTheDocument());
    expect(within(dialog).getByText("STK-POSTED-902")).toBeInTheDocument();
    expect(dialog).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
    expect(dialog).toHaveTextContent(language === "ar" ? "أُلغي بعد تثبيت العد" : "Cancelled after count submission");
    const cancelledCard = within(dialog).getByText("STK-CANCEL-901").closest("article")!;
    fireEvent.click(within(cancelledCard).getByRole("button", {
      name: language === "ar" ? "عرض التفاصيل" : "View details",
    }));
    await waitFor(() => expect(dialog).toHaveTextContent("Count investigated"));
    fireEvent.click(within(dialog).getByRole("button", {
      name: language === "ar" ? "عرض الكميات" : "View quantities",
    }));
    await waitFor(() => expect(within(dialog).getByRole("table")).toHaveTextContent("LOT-51"));
    expect(within(dialog).getByRole("table")).toHaveTextContent(language === "ar" ? "محظور" : "Blocked");
    expect(within(dialog).getByRole("table")).not.toHaveTextContent("BLOCKED");
    expect(dialog).toHaveTextContent(language === "ar" ? "إلغاء الجرد" : "Stocktake cancelled");
    expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("/stocktakes/history?location_id=11"));
    expect(fetcher).not.toHaveBeenCalledWith(expect.stringMatching(/\/approve|\/cancel|\/count\b/));
  });

  it.each(["ar", "en"] as const)("fails closed and surfaces 403 request correlation in %s", async language => {
    locale.value = language;
    const fetcher = vi.fn(async () => {
      throw Object.assign(new Error("Authorization denied."), {
        status: 403, code: "PERMISSION_DENIED", requestId: "history-request-799",
      });
    });
    render(<HistoryHarness fetcher={fetcher} />);
    fireEvent.click(screen.getByRole("button", {
      name: language === "ar" ? "سجل الجرد" : "Stocktake history",
    }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("PERMISSION_DENIED");
    expect(alert).toHaveTextContent("history-request-799");
    expect(screen.queryByText("STK-CANCEL-901")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not open history without reviewer permission", () => {
    const fetcher = vi.fn();
    render(<HistoryHarness enabled={false} fetcher={fetcher} />);
    const trigger = screen.getByRole("button", { name: "سجل الجرد" });
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
