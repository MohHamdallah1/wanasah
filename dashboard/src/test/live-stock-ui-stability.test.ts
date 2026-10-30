import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const readSource = (relativePath: string): string =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8");

const normalizeWhitespace = (value: string): string =>
  value.replace(/\s+/g, " ").trim();

const cssRuleBody = (
  styles: string,
  selector: string,
): string => {
  const escaped = selector.replace(/[.*+?^$()|[\]\\]/g, "\\$&");
  const match = styles.match(
    new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\}`),
  );
  expect(match, `Missing CSS rule: ${selector}`).not.toBeNull();
  return match?.[1] ?? "";
};

describe("Live Stock visual stability regressions", () => {
  it("does not animate the search field width", () => {
    const component = readSource(
      "../pages/inventory/Tab1LiveStock.tsx",
    );
    const styles = readSource(
      "../pages/inventory/inventory.css",
    );

    const searchWrapperRule = cssRuleBody(
      styles,
      ".live-stock-search",
    );
    const searchInputRule = cssRuleBody(
      styles,
      ".live-stock-search input",
    );

    expect(component).not.toContain(
      "outline-none transition-all",
    );
    expect(searchWrapperRule).not.toMatch(
      /transition\s*:/,
    );
    expect(searchInputRule).toMatch(
      /transition\s*:/,
    );
    expect(searchInputRule).not.toMatch(
      /transition\s*:[^;]*(?:width|flex|flex-basis)/s,
    );
  });

  it("keeps live-stock request failures local to the live tab", () => {
    const main = readSource(
      "../pages/inventory/MainInventory.tsx",
    );

    const fetchStockStart = main.indexOf(
      "const fetchStock = useCallback",
    );
    const fetchSummaryStart = main.indexOf(
      "const fetchStockSummary = useCallback",
    );
    const resetStart = main.indexOf(
      "const resetStockPagination = useCallback",
    );

    expect(fetchStockStart).toBeGreaterThan(-1);
    expect(fetchSummaryStart).toBeGreaterThan(fetchStockStart);
    expect(resetStart).toBeGreaterThan(fetchSummaryStart);

    const fetchStock = main.slice(
      fetchStockStart,
      fetchSummaryStart,
    );
    const fetchSummary = main.slice(
      fetchSummaryStart,
      resetStart,
    );

    expect(fetchStock).toContain("setStockPageError(");
    expect(fetchStock).toContain(
      "const hasVisibleRows = stockItemsRef.current.length > 0;",
    );
    expect(fetchStock).toContain(
      "if (!hasVisibleRows && warmSnapshot?.hasPage !== true)",
    );
    expect(fetchStock).not.toContain("toast.error(");
    expect(fetchSummary).toContain("setStockSummaryError(");
    expect(fetchSummary).not.toContain("toast.error(");
    expect(main).toContain("pageError={stockPageError}");
    expect(main).toContain("summaryError={stockSummaryError}");
  });

  it("defers Live Stock list and summary requests while another inventory tab is active", () => {
    const main = normalizeWhitespace(
      readSource("../pages/inventory/MainInventory.tsx"),
    );

    expect(main).toContain(
      'if (activeTab === "live" && selectedLocationId !== null) { void fetchStock(); }',
    );
    expect(main).toContain(
      'if (activeTab === "live" && selectedLocationId !== null) { void fetchStockSummary(); }',
    );
    expect(main).toContain(
      "[activeTab, selectedLocationId, fetchStockSummary, stockRefreshKey]",
    );
  });

  it("keeps warm inventory fail-closed until fresh canonical admission is verified", () => {
    const main = normalizeWhitespace(
      readSource("../pages/inventory/MainInventory.tsx"),
    );
    const live = normalizeWhitespace(
      readSource("../pages/inventory/Tab1LiveStock.tsx"),
    );

    expect(main).toContain(
      "const liveVisible = liveAuthorityVerified && !accessDenied && !locationError && liveReadPhase !== \"denied\";",
    );
    expect(main).toContain(
      'activeTab === "live" && selectedLocationId !== null && liveVisible && tabAllowed("live")',
    );
    expect(main).toContain(
      "locationAccess.isSuccess && locationAccess.isFetchedAfterMount && !locationAccess.isFetching",
    );
    expect(main).not.toContain("canShowWarmLiveDuringAccessRefresh");
    expect(main).toContain("pageReady={stockPageReady}");
    expect(live).toContain("loading && !pageReady");
  });
});
