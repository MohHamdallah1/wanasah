import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveStockFilters } from "@/pages/inventory/liveStock/LiveStockFilters";
import type {
  LiveStockIndicator,
  LiveStockStockState,
} from "@/pages/inventory/liveStock/contracts";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  language: "en",
}));

const translate = (key: string, options?: { name?: string }) =>
  options?.name ? `${key}: ${options.name}` : key;

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

// Keep the tests about the Live Stock filter behavior, not Radix portal layout.
vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverContent: ({ children, dir, className }: {
    children: ReactNode;
    dir?: string;
    className?: string;
  }) => (
    <div dir={dir} className={className}>{children}</div>
  ),
}));

vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: () => undefined },
  useTranslation: () => ({
    t: translate,
    i18n: {
      language: mocks.language,
      resolvedLanguage: mocks.language,
      dir: () => (mocks.language === "ar" ? "rtl" : "ltr"),
    },
  }),
}));

const family = (id: number, name: string) => ({
  id,
  name,
  code: `F-${id}`,
});
const familyPage = (items: ReturnType<typeof family>[]) => ({
  items,
  has_more: false,
});

function FilterHarness({ locationId = 11 }: { locationId?: number }) {
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [stockState, setStockState] = useState<LiveStockStockState>("all");
  const [indicators, setIndicators] = useState<LiveStockIndicator[]>([]);

  return (
    <LiveStockFilters
      locationId={locationId}
      alertCount={1}
      stockState={stockState}
      indicators={indicators}
      familyId={familyId}
      onSearchChange={() => undefined}
      onStockStateChange={setStockState}
      onIndicatorsChange={setIndicators}
      onFamilyChange={setFamilyId}
    />
  );
}

beforeEach(() => {
  mocks.authFetch.mockReset();
  mocks.language = "en";
});

afterEach(() => {
  cleanup();
});

describe("Live Stock family filter state and recovery", () => {
  it("shows a fetch failure and explicitly retries instead of showing an empty family list", async () => {
    mocks.authFetch
      .mockRejectedValueOnce(new Error("network unavailable"))
      .mockResolvedValueOnce(familyPage([family(1, "Alpha")]));

    render(<FilterHarness />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "inventoryLive.errors.familyLoadFailed",
    );
    expect(screen.queryByText("inventoryLive.familyNoMatches")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(await screen.findByRole("button", { name: /Alpha/ })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.authFetch).toHaveBeenCalledTimes(2);
    for (const [url] of mocks.authFetch.mock.calls) {
      const request = new URL(String(url), "http://test.local");
      expect(request.pathname).toBe("/warehouse/inventory/families");
      expect(request.searchParams.get("location_id")).toBe("11");
      expect(request.searchParams.get("limit")).toBe("50");
    }
  });

  it("retains the selected family name and ID across new, empty and failed searches", async () => {
    mocks.authFetch.mockImplementation((url: string) => {
      const term = new URL(url, "http://test.local").searchParams.get("search");
      if (term === "beta") return Promise.resolve(familyPage([family(2, "Beta")]));
      if (term === "gone") return Promise.resolve(familyPage([]));
      if (term === "error") return Promise.reject(new Error("offline"));
      return Promise.resolve(familyPage([family(1, "Alpha"), family(2, "Beta")]));
    });

    render(<FilterHarness />);
    fireEvent.click(await screen.findByRole("button", { name: /Alpha/ }));
    expect(
      screen.getByRole("button", { name: "inventoryLive.selectedFamilyLabel: Alpha" }),
    ).toBeInTheDocument();

    const search = screen.getByRole("searchbox", { name: "inventoryLive.familySearch" });
    fireEvent.change(search, { target: { value: "beta" } });
    const beta = await screen.findByRole("button", { name: /Beta/ });
    expect(beta).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByRole("button", { name: "inventoryLive.selectedFamilyLabel: Alpha" }),
    ).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "gone" } });
    expect(await screen.findByText("inventoryLive.familyNoMatches")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "inventoryLive.selectedFamilyLabel: Alpha" }),
    ).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "error" } });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "inventoryLive.selectedFamilyLabel: Alpha" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "inventoryLive.clearFamily" }));
    expect(screen.getByRole("button", { name: "inventoryLive.familyTitle" })).toBeInTheDocument();
  });

  it("aborts an older search and rejects its late response", async () => {
    let resolveOld!: (value: ReturnType<typeof familyPage>) => void;
    const oldResult = new Promise<ReturnType<typeof familyPage>>((resolve) => {
      resolveOld = resolve;
    });
    mocks.authFetch.mockImplementation((url: string) => {
      const term = new URL(url, "http://test.local").searchParams.get("search");
      if (term === "alpha") return oldResult;
      if (term === "beta") return Promise.resolve(familyPage([family(2, "Beta")]));
      return Promise.resolve(familyPage([]));
    });

    render(<FilterHarness />);
    await waitFor(() => expect(mocks.authFetch).toHaveBeenCalledTimes(1));
    const search = screen.getByRole("searchbox", { name: "inventoryLive.familySearch" });
    fireEvent.change(search, { target: { value: "alpha" } });
    await waitFor(() => expect(mocks.authFetch).toHaveBeenCalledTimes(2));
    const staleOptions = mocks.authFetch.mock.calls[1][1] as { signal: AbortSignal };

    fireEvent.change(search, { target: { value: "beta" } });
    const beta = await screen.findByRole("button", { name: /Beta/ });
    expect(beta).toBeInTheDocument();
    expect(staleOptions.signal.aborted).toBe(true);

    await act(async () => {
      resolveOld(familyPage([family(1, "Alpha")]));
      await oldResult;
    });
    expect(screen.queryByRole("button", { name: /Alpha/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Beta/ })).toBeInTheDocument();
  });

  it("exposes native focusable controls and semantic selection for stock, indicators, families and RTL", async () => {
    mocks.language = "ar";
    mocks.authFetch.mockResolvedValue(familyPage([family(1, "Alpha")]));
    const { container, rerender } = render(<FilterHarness />);

    const all = screen.getByRole("button", { name: "inventoryLive.filterAll" });
    const onHand = screen.getByRole("button", { name: "inventoryLive.filterOnHand" });
    const reserved = screen.getByRole("button", { name: "inventoryLive.indicatorReserved" });
    expect(all).toHaveAttribute("aria-pressed", "true");
    expect(onHand).toHaveAttribute("aria-pressed", "false");
    expect(reserved).toHaveAttribute("aria-pressed", "false");

    onHand.focus();
    expect(onHand).toHaveFocus();
    expect(onHand).toHaveAttribute("type", "button");
    fireEvent.click(onHand);
    expect(onHand).toHaveAttribute("aria-pressed", "true");
    expect(all).toHaveAttribute("aria-pressed", "false");

    reserved.focus();
    expect(reserved).toHaveFocus();
    fireEvent.click(reserved);
    expect(reserved).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector(".live-stock-filter-popover")).toHaveAttribute("dir", "rtl");

    const alpha = await screen.findByRole("button", { name: /Alpha/ });
    expect(alpha).toHaveAttribute("aria-pressed", "false");
    alpha.focus();
    expect(alpha).toHaveFocus();
    fireEvent.click(alpha);
    expect(alpha).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "inventoryLive.selectedFamilyLabel: Alpha" }),
    ).toBeInTheDocument();

    mocks.language = "en";
    rerender(<FilterHarness />);
    expect(container.querySelector(".live-stock-filter-popover")).toHaveAttribute("dir", "ltr");
  });

  it("does not request one-character family searches and resets a pending request on warehouse change", async () => {
    let resolveOld!: (value: ReturnType<typeof familyPage>) => void;
    const oldResult = new Promise<ReturnType<typeof familyPage>>((resolve) => {
      resolveOld = resolve;
    });
    mocks.authFetch.mockImplementation((url: string) => {
      const params = new URL(url, "http://test.local").searchParams;
      if (params.get("location_id") === "11" && params.get("search") === "alpha") return oldResult;
      if (params.get("location_id") === "12") return Promise.resolve(familyPage([family(2, "Beta")]));
      return Promise.resolve(familyPage([]));
    });
    const { rerender } = render(<FilterHarness locationId={11} />);
    await waitFor(() => expect(mocks.authFetch).toHaveBeenCalledTimes(1));

    const search = screen.getByRole("searchbox", { name: "inventoryLive.familySearch" });
    fireEvent.change(search, { target: { value: "a" } });
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(mocks.authFetch).toHaveBeenCalledTimes(1);

    fireEvent.change(search, { target: { value: "alpha" } });
    await waitFor(() => expect(mocks.authFetch).toHaveBeenCalledTimes(2));
    const oldOptions = mocks.authFetch.mock.calls[1][1] as { signal: AbortSignal };
    rerender(<FilterHarness locationId={12} />);
    expect(oldOptions.signal.aborted).toBe(true);
    expect(await screen.findByRole("button", { name: /Beta/ })).toBeInTheDocument();

    await act(async () => {
      resolveOld(familyPage([family(1, "Alpha")]));
      await oldResult;
    });
    expect(screen.queryByRole("button", { name: /Alpha/ })).not.toBeInTheDocument();
  });
});
