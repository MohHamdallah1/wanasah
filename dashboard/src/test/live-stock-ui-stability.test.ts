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

  it("keeps a warm warehouse page mounted during access revalidation", () => {
    const main = normalizeWhitespace(
      readSource("../pages/inventory/MainInventory.tsx"),
    );
    const live = normalizeWhitespace(
      readSource("../pages/inventory/Tab1LiveStock.tsx"),
    );

    expect(main).toContain(
      'const canShowWarmLiveDuringAccessRefresh = activeTab === "live" && selectedLocationId !== null && locationAccess.isPending && stockPageReady && !locationAccess.isError;',
    );
    expect(main).toContain(
      "selectedLocationId !== null && locationAccess.isPending && !canShowWarmLiveDuringAccessRefresh && (",
    );
    expect(main).toContain(
      'canShowWarmLiveDuringAccessRefresh || (!locationAccess.isPending && tabAllowed("live"))',
    );
    expect(main).toContain(
      "pageReady={stockPageReady}",
    );
    expect(live).toContain(
      "loading && !pageReady",
    );
  });
});
