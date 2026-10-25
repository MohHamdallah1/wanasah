import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Inbound expiry not-tracked hint", () => {
  it("explains why a non-expiry-tracked row shows a dash", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/pages/inventory/Tab2Inbound.tsx"),
      "utf8",
    );

    expect(source).toContain('title={t("inventoryInbound.expiryNotTracked")}');
    expect(source).toContain('aria-label={t("inventoryInbound.expiryNotTracked")}');
  });
});
