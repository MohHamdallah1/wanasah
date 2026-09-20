import { describe, expect, it } from "vitest";

import { convertBaseQuantityToUom } from "@/pages/inventory/quantity";

describe("live stock minimum display-unit conversion", () => {
  it("converts exact integer carton factors without floating point", () => {
    expect(convertBaseQuantityToUom("1000", "50")).toBe("20");
  });

  it("supports exact decimal factors within the quantity contract", () => {
    expect(convertBaseQuantityToUom("5", "2.5")).toBe("2");
  });

  it("refuses a display value that cannot be represented exactly at 6 decimals", () => {
    expect(convertBaseQuantityToUom("1", "3")).toBeNull();
  });
});
