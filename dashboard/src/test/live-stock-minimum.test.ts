import { describe, expect, it } from "vitest";

import {
  convertBaseQuantityToUom,
  formatCommercialQuantity,
} from "@/pages/inventory/quantity";
import { parseBulkMinimumStockPlan } from "@/pages/inventory/liveStock/contracts";

describe("live stock quantity and minimum-stock contracts", () => {
  it("converts exact integer carton factors without floating point", () => {
    expect(convertBaseQuantityToUom("1000", "50")).toBe("20");
  });

  it("supports exact decimal factors within the quantity contract", () => {
    expect(convertBaseQuantityToUom("5", "2.5")).toBe("2");
  });

  it("refuses a display value that cannot be represented exactly at 6 decimals", () => {
    expect(convertBaseQuantityToUom("1", "3")).toBeNull();
  });

  it("shows loose units instead of hiding the remainder", () => {
    expect(
      formatCommercialQuantity("2520", "كرتونة", "حبة", "50"),
    ).toEqual({
      primary: "50 كرتونة + 20 حبة",
      secondary: "2520 حبة",
    });
  });

  it("validates bulk minimum-stock preview/apply responses fail-closed", () => {
    expect(
      parseBulkMinimumStockPlan({
        location_id: 1,
        scope: "FAMILY",
        family_ids: [8, 9],
        product_variant_ids: [],
        minimum_quantity: "10",
        unit_mode: "DISPLAY_UOM_PER_PRODUCT",
        apply_mode: "ONLY_UNSET",
        matched_count: 12,
        affected_count: 9,
        skipped_existing_count: 3,
        inactive_conflict_count: 0,
        target_conflict_count: 0,
        invalid_quantity_count: 0,
        conflict_samples: {
          inactive: [],
          target: [],
          invalid_quantity: [],
        },
      }).affected_count,
    ).toBe(9);
  });
});
