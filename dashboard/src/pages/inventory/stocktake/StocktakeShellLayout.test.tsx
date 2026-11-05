import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
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
  scope_product_variant_id: stocktake_type === "CYCLE_COUNT" ? 118 : null,
  scope_product_name: stocktake_type === "CYCLE_COUNT" ? "Chickpeas 750 g" : null,
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

beforeEach(() => { locale.value = "ar"; });

describe("Stocktake #782 final shell: sessions and single workspace", () => {
  it.each([
    ["ar", "جلسات الجرد النشطة", "فتح", "مفتوحة"],
    ["en", "Active stocktake sessions", "Open", "Opened"],
  ] as const)("keeps multiple sessions reachable in a compact keyboard-accessible strip in %s", (language, title, open, opened) => {
    locale.value = language;
    const onOpenSession = vi.fn();
    const onLoadMore = vi.fn();
    render(<StocktakeSessionCenter
      sessions={[session(77, "FULL_COUNT"), session(78)]} total={3}
      loading={false} loadingMore={false} nextCursor="next"
      currentSessionId={77} onLoadMore={onLoadMore} onOpenSession={onOpenSession}
    />);
    const region = screen.getByRole("region", { name: title });
    expect(region).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
    const toggle = within(region).getByRole("button", { name: new RegExp(title) });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const list = within(region).getByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getByRole("button", { name: opened })).toBeDisabled();
    fireEvent.click(within(list).getByRole("button", { name: open }));
    expect(onOpenSession).toHaveBeenCalledWith(expect.objectContaining({ id: 78, location_id: 11 }));
    const more = within(region).getByRole("button", { name: language === "ar" ? "تحميل المزيد" : "Load more" });
    fireEvent.click(more);
    expect(onLoadMore).toHaveBeenCalledOnce();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(region).queryByRole("list")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(within(region).getAllByRole("listitem")).toHaveLength(2);
  });

  it.each(["ar", "en"] as const)("keeps zero sessions compact and does not add a duplicate cycle/refresh button in %s", (language) => {
    locale.value = language;
    const { container } = render(<StocktakeSessionCenter sessions={[]} total={0}
      loading={false} loadingMore={false} nextCursor={null}
      currentSessionId={null} onLoadMore={vi.fn()} onOpenSession={vi.fn()} />);
    expect(container.querySelector("[data-stocktake-sessions='compact']")).not.toBeNull();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(container.textContent).toContain(language === "ar" ? "لا توجد جلسات جرد نشطة" : "There are no active stocktake sessions");
  });

  it("moves the single MainInventory warehouse selector only for the selected Stocktake tab", () => {
    expect(main).toContain('warehouseSelector={stocktakeShellAdmitted ? stocktakeWarehouseSelector : null}');
    expect(main).toContain('onChange={(event) => handleLocationChange(event.target.value)}');
    expect(main).toContain('!stocktakeShellAdmitted && (');
    expect(main).toContain('locationTabScope !== null && tabAllowed("stocktake")');
    expect(main).toContain('activeTab !== "stocktake" && (');
    expect(main.match(/className="inventory-location-select/g)).toHaveLength(2); // One shared, one no-location fallback
    expect(main).toContain('data-it03-retained-tab="stocktake"');
    expect(main).toContain('key={`stocktake:${locationTabScope}`}');
  });

  it("uses one toolbar and one workspace for idle door, both count types and review", () => {
    expect(tab).toContain('data-stocktake-toolbar="true"');
    expect(tab).toContain("warehouseSelector");
    expect(tab).toContain("onClick={refreshSessions}");
    expect(tab).toContain("onClick={() => setShowCycleModal(true)}");
    expect(tab).toContain('data-stocktake-workspace={workspacePhase}');
    expect(tab.match(/<StocktakeCountingPanel/g)).toHaveLength(1);
    expect(tab.match(/<StocktakeReviewPanel/g)).toHaveLength(1);
    expect(tab.match(/<StocktakeIdlePanel/g)).toHaveLength(1);
    expect(tab).toContain('warehouseAccess.can("stocktake.start")');
    expect(tab).toContain('sessionAccess.can("stocktake.count")');
    expect(tab).toContain('sessionAccess.can("stocktake.review")');
    expect(tab).toContain('sessionLocationId === locationId ? locationName : null');
  });
});
