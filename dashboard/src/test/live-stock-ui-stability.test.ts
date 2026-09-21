import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const readSource = (relativePath: string): string =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8");

describe("Live Stock visual stability regressions", () => {
  it("does not animate the search field width", () => {
    const component = readSource(
      "../pages/inventory/Tab1LiveStock.tsx",
    );
    const styles = readSource(
      "../pages/inventory/inventory.css",
    );

    expect(component).not.toContain(
      "outline-none transition-all",
    );
    expect(styles).toContain(
      "border-color 140ms ease,\n    box-shadow 140ms ease",
    );
  });

  it("keeps a warm warehouse page mounted during access revalidation", () => {
    const main = readSource(
      "../pages/inventory/MainInventory.tsx",
    );
    const live = readSource(
      "../pages/inventory/Tab1LiveStock.tsx",
    );

    expect(main).toContain(
      "canShowWarmLiveDuringAccessRefresh",
    );
    expect(main).toContain(
      "locationAccess.isPending &&\n          !canShowWarmLiveDuringAccessRefresh",
    );
    expect(main).toContain(
      "pageReady={stockPageReady}",
    );
    expect(live).toContain(
      "loading && !pageReady",
    );
  });
});
