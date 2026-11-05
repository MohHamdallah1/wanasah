import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StocktakeSessionCenter } from "./StocktakeSessionCenter";
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
    ["ar", "الجلسات (3)", "جلسات الجرد النشطة", "فتح", "مفتوحة"],
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
    const trigger = screen.getByRole("button", { name: language === "ar" ? "الجلسات (0)" : "Sessions (0)" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("list")).not.toBeInTheDocument();
    expect(dialog).toHaveTextContent(language === "ar" ? "لا توجد جلسات جرد نشطة" : "There are no active stocktake sessions");
  });

  it("does not open an unauthorized session drawer", () => {
    render(<SessionsHarness canRead={false} />);
    const trigger = screen.getByRole("button", { name: "الجلسات (3)" });
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("uses one MainInventory warehouse select with inline label only on admitted Stocktake", () => {
    expect(main).toContain('warehouseSelector={stocktakeShellAdmitted ? stocktakeWarehouseSelector : null}');
    expect(main).toContain('onChange={(event) => handleLocationChange(event.target.value)}');
    expect(main).toContain('locale.startsWith("ar") ? "المستودع:" : "Warehouse:"');
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
