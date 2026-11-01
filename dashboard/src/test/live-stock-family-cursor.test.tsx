import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resources } from "@/i18n/resources";
import { LiveStockFilters } from "@/pages/inventory/liveStock/LiveStockFilters";
import { parseLiveStockFamilies } from "@/pages/inventory/liveStock/contracts";

const mock = vi.hoisted(() => ({ fetch: vi.fn(), language: "en", localizedError: false }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mock.fetch }));
vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverContent: ({ children, dir }: { children: ReactNode; dir?: string }) => (
    <div dir={dir}>{children}</div>
  ),
}));
const translate = (key: string, options?: { name?: string; count?: number }) =>
  mock.localizedError && key === "inventoryLive.errors.familyLoadFailed"
    ? resources[mock.language as "ar" | "en"].translation.inventoryLive.errors.familyLoadFailed :
  options?.name ? `${key}: ${options.name}` :
  options?.count !== undefined ? `${key}: ${options.count}` : key;
vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: () => undefined },
  useTranslation: () => ({
    t: translate,
    i18n: { language: mock.language, resolvedLanguage: mock.language,
      dir: () => mock.language === "ar" ? "rtl" : "ltr" },
  }),
}));

type Family = { id: number; name: string; code: string };
const options = (n: number): Family[] => Array.from({ length: n }, (_, i) =>
  ({ id: i + 1, name: `Family ${String(i + 1).padStart(3, "0")}`, code: `F${i + 1}` }));
const response = (all: Family[], start = 0, limit = 50) => {
  const page = all.slice(start, start + limit);
  const next = start + limit < all.length ? `opaque-${start + limit}` : null;
  return { items: page, has_more: next !== null, next_cursor: next };
};
const readParams = (url: string) => new URL(url, "http://localhost").searchParams;

function FilterHarness({ locationId = 11 }: { locationId?: number }) {
  const [familyId, setFamilyId] = useState<number | null>(null);
  return (
    <LiveStockFilters
      locationId={locationId}
      alertCount={1}
      familyId={familyId}
      stockState="all"
      view="warehouse"
      onViewChange={() => undefined}
      indicators={[]}
      onFamilyChange={setFamilyId}
      onSearchChange={() => undefined}
      onStockStateChange={() => undefined}
      onIndicatorsChange={() => undefined}
    />
  );
}
const more = () => screen.getByRole("button", { name: "inventoryLive.familyLoadMore" });
const searchFamily = () => screen.getByRole("searchbox", { name: "inventoryLive.familySearch" });

beforeEach(() => { mock.fetch.mockReset(); mock.language = "en"; mock.localizedError = false; });
afterEach(cleanup);

describe("F5/UI-03 bounded family cursor and selected identity", () => {
  it.each([51, 101, 151])("browses %i families via opaque 50-row cursor without loss/duplicate", async (count) => {
    const all = options(count);
    mock.fetch.mockImplementation((url: string) => {
      const params = readParams(url);
      const cursor = params.get("cursor");
      return Promise.resolve(response(all, cursor ? Number(cursor.slice(7)) : 0));
    });
    render(<FilterHarness />);
    await screen.findByRole("button", { name: /Family 050/ });
    const requests = Math.ceil(count / 50);
    for (let i = 1; i < requests; i++) {
      fireEvent.click(more());
      await screen.findByRole("button", {
        name: new RegExp(`Family ${String(Math.min((i + 1) * 50, count)).padStart(3, "0")}`),
      });
    }
    expect(screen.queryByRole("button", { name: "inventoryLive.familyLoadMore" })).not.toBeInTheDocument();
    const renderedNames = Array.from(
      document.querySelectorAll(".live-stock-family-option strong"),
      (element) => element.textContent,
    );
    expect(renderedNames).toEqual(all.map((item) => item.name));
    expect(new Set(renderedNames).size).toBe(count);
    expect(mock.fetch).toHaveBeenCalledTimes(requests);
    mock.fetch.mock.calls.forEach(([url], i) => {
      const params = readParams(String(url));
      expect(params.get("location_id")).toBe("11");
      expect(params.get("limit")).toBe("50");
      expect(params.get("cursor")).toBe(i ? `opaque-${i * 50}` : null);
    });
  }, 15_000);

  it("preserves selected family from page 2 across new search, retry, and warehouse switch", async () => {
    const all = options(101);
    mock.fetch.mockImplementation((url: string) => {
      const p = readParams(url);
      if (p.get("location_id") === "12") return Promise.resolve(response(all.slice(0, 2)));
      if (p.get("search") === "beta") return Promise.resolve(response([]));
      if (p.get("cursor")) return Promise.resolve(response(all, 50));
      return Promise.resolve(response(all));
    });
    const { rerender } = render(<FilterHarness />);
    await screen.findByRole("button", { name: /Family 050/ });
    fireEvent.click(more());
    const selected = await screen.findByRole("button", { name: /Family 051/ });
    fireEvent.click(selected);
    expect(screen.getByRole("button", {
      name: "inventoryLive.selectedFamilyLabel: Family 051",
    })).toBeInTheDocument();

    fireEvent.change(searchFamily(), { target: { value: "beta" } });
    await screen.findByText("inventoryLive.familyNoMatches");
    expect(screen.getByRole("button", {
      name: "inventoryLive.selectedFamilyLabel: Family 051",
    })).toBeInTheDocument();
    rerender(<FilterHarness locationId={12} />);
    await screen.findByRole("button", { name: /Family 002/ });
    expect(screen.getByRole("button", {
      name: "inventoryLive.selectedFamilyLabel: Family 051",
    })).toBeInTheDocument();
  });

  it("keeps loaded options and cursor on continuation failure, then retries same page", async () => {
    const all = options(101);
    let failed = false;
    mock.fetch.mockImplementation((url: string) => {
      const p = readParams(url);
      if (p.get("cursor") === "opaque-50" && !failed) {
        failed = true;
        return Promise.reject(new Error("offline"));
      }
      return Promise.resolve(response(all, p.has("cursor") ? 50 : 0));
    });
    render(<FilterHarness />);
    await screen.findByRole("button", { name: /Family 050/ });
    fireEvent.click(more());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "inventoryLive.errors.familyLoadFailed",
    );
    expect(screen.getByRole("button", { name: /Family 050/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "inventoryLive.familyRetryMore" }));
    await screen.findByRole("button", { name: /Family 100/ });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(readParams(mock.fetch.mock.calls[1][0]).get("cursor")).toBe("opaque-50");
    expect(readParams(mock.fetch.mock.calls[2][0]).get("cursor")).toBe("opaque-50");
    expect(screen.getAllByRole("button", { name: /Family 050/ })).toHaveLength(1);
  });

  it("ignores late continuation from old search, keeps new scoped page, handles one-letter input", async () => {
    const all = options(101);
    let resolveOld!: (page: ReturnType<typeof response>) => void;
    const oldPage = new Promise<ReturnType<typeof response>>(resolve => { resolveOld = resolve; });
    mock.fetch.mockImplementation((url: string) => {
      const p = readParams(url);
      if (p.has("cursor")) return oldPage;
      if (p.get("search") === "beta") return Promise.resolve(response([{ id: 900, name: "Beta", code: "B" }]));
      return Promise.resolve(response(all));
    });
    render(<FilterHarness />);
    await screen.findByRole("button", { name: /Family 050/ });
    fireEvent.click(more());
    await waitFor(() => expect(mock.fetch).toHaveBeenCalledTimes(2));
    const oldSignal = (mock.fetch.mock.calls[1][1] as { signal: AbortSignal }).signal;
    fireEvent.change(searchFamily(), { target: { value: "beta" } });
    await screen.findByRole("button", { name: /Beta/ });
    expect(oldSignal.aborted).toBe(true);
    await act(async () => {
      resolveOld(response(all, 50));
      await oldPage;
    });
    expect(screen.queryByRole("button", { name: /Family 051/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Beta/ })).toBeInTheDocument();
    fireEvent.change(searchFamily(), { target: { value: "b" } });
    expect(await screen.findByText("inventoryLive.familySearchMinLength")).toBeInTheDocument();
    expect(mock.fetch).toHaveBeenCalledTimes(3);
  });

  it("rejects invalid cursor/has_more contracts and preserves RTL focus/selection", async () => {
    expect(() => parseLiveStockFamilies({ items: [], has_more: true, next_cursor: null })).toThrow();
    expect(() => parseLiveStockFamilies({ items: [], has_more: false, next_cursor: "invalid" })).toThrow();
    expect(() => parseLiveStockFamilies({ items: [], has_more: true })).toThrow();
    mock.language = "ar";
    mock.fetch.mockResolvedValue(response(options(51)));
    const { container } = render(<FilterHarness />);
    const first = await screen.findByRole("button", { name: /Family 001/ });
    first.focus();
    expect(first).toHaveFocus();
    fireEvent.click(first);
    expect(first).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector(".live-stock-family-list")).toHaveAttribute("role", "group");
    expect(container.querySelector(".live-stock-family-list")?.closest('[dir="rtl"]')).not.toBeNull();
    expect(more()).toHaveAttribute("type", "button");
    more().focus();
    expect(more()).toHaveFocus();
  });
  it.each(["ar", "en"] as const)("rejects a non-advancing family cursor and retries without loss in %s", async (locale) => {
    mock.language = locale;
    mock.localizedError = true;
    const all = options(101);
    let repeated = false;
    mock.fetch.mockImplementation((url: string) => {
      const cursor = readParams(url).get("cursor");
      if (cursor === "opaque-50" && !repeated) {
        repeated = true;
        // A valid-shaped page with the same next cursor must never be appended.
        return Promise.resolve({ ...response(all, 50), next_cursor: "opaque-50" });
      }
      return Promise.resolve(response(all, cursor ? Number(cursor.slice(7)) : 0));
    });
    render(<FilterHarness />);
    await screen.findByRole("button", { name: /Family 050/ });
    fireEvent.click(more());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      resources[locale].translation.inventoryLive.errors.familyLoadFailed,
    );
    expect(screen.queryByText("LIVE_STOCK_FAMILY_CURSOR_NON_ADVANCING")).not.toBeInTheDocument();
    expect(document.querySelectorAll(".live-stock-family-option strong")).toHaveLength(50);
    expect(screen.queryByRole("button", { name: /Family 051/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "inventoryLive.familyRetryMore" }));
    await screen.findByRole("button", { name: /Family 100/ });
    expect(readParams(mock.fetch.mock.calls[1][0]).get("cursor")).toBe("opaque-50");
    expect(readParams(mock.fetch.mock.calls[2][0]).get("cursor")).toBe("opaque-50");
    fireEvent.click(more());
    await screen.findByRole("button", { name: /Family 101/ });
    const names = Array.from(document.querySelectorAll(".live-stock-family-option strong"), e => e.textContent);
    expect(names).toEqual(all.map(family => family.name));
    expect(new Set(names).size).toBe(101);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "inventoryLive.familyLoadMore" })).not.toBeInTheDocument();
  });

});
