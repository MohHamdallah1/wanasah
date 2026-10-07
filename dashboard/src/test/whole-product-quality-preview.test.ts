import { describe, expect, it } from "vitest";

import { parseWholeProductQualityPreview } from "@/features/inventory/quality/wholeProductQualityPreviewContract";
import { formatCommercialQuantity } from "@/lib/quantity";

const movingAveragePreview = (): Record<string, unknown> => ({
  product_variant_id: 44,
  issue_reason: "اشتباه بسلامة المنتج",
  currency_code: "JOD",
  costing_method: "MOVING_AVERAGE",
  valuation_available: true,
  valuation_reason: null,
  total_quantity: "120",
  total_reserved_quantity: "0",
  total_book_value: "30.000000",
  average_unit_cost: "0.250000",
  locations: [
    {
      location_id: 7,
      location_name: "مستودع التطوير",
      location_type: "WAREHOUSE",
      quantity: "100",
    },
    {
      location_id: 8,
      location_name: "حركة قيد النقل",
      location_type: "IN_TRANSIT",
      quantity: "20",
    },
  ],
  batches: [
    { batch_id: 101, batch_number: "LOT-A", quantity: "70" },
    { batch_id: 102, batch_number: "LOT-B", quantity: "50" },
  ],
  valuation_lines: [
    {
      batch_id: 101,
      batch_number: "LOT-A",
      quantity: "70",
      unit_cost: "0.250000",
      book_value: "17.500000",
    },
    {
      batch_id: 102,
      batch_number: "LOT-B",
      quantity: "50",
      unit_cost: "0.250000",
      book_value: "12.500000",
    },
  ],
  blocker_codes: ["WHOLE_PRODUCT_QUALITY_CUSTODY_BLOCKER"],
});

describe("whole-product quality financial preview", () => {
  it("keeps warehouse/custody locations and physical batches informational", () => {
    const parsed = parseWholeProductQualityPreview(movingAveragePreview());
    expect(parsed.issueReason).toBe("اشتباه بسلامة المنتج");
    expect(parsed.locations).toEqual([
      expect.objectContaining({ locationName: "مستودع التطوير", locationType: "WAREHOUSE", quantity: "100" }),
      expect.objectContaining({ locationName: "حركة قيد النقل", locationType: "IN_TRANSIT", quantity: "20" }),
    ]);
    expect(parsed.batches).toEqual([
      expect.objectContaining({ batchNumber: "LOT-A", quantity: "70" }),
      expect.objectContaining({ batchNumber: "LOT-B", quantity: "50" }),
    ]);
  });

  it("preserves authoritative book value and per-line cost as exact strings", () => {
    const parsed = parseWholeProductQualityPreview(movingAveragePreview());
    expect(parsed.totalBookValue).toBe("30.000000");
    expect(parsed.averageUnitCost).toBe("0.250000");
    expect(parsed.valuationLines[0]).toEqual(expect.objectContaining({
      unitCost: "0.250000",
      bookValue: "17.500000",
    }));
  });

  it("accepts a fail-closed preview when reliable valuation is unavailable", () => {
    const raw = movingAveragePreview();
    raw.costing_method = null;
    raw.valuation_available = false;
    raw.valuation_reason = "COSTING_NOT_ACTIVE";
    raw.total_book_value = null;
    raw.average_unit_cost = null;
    raw.valuation_lines = [];
    const parsed = parseWholeProductQualityPreview(raw);
    expect(parsed.valuationAvailable).toBe(false);
    expect(parsed.totalBookValue).toBeNull();
    expect(parsed.valuationReason).toBe("COSTING_NOT_ACTIVE");
  });

  it("accepts a legacy active recall whose saved reason cannot be reconstructed", () => {
    const raw = movingAveragePreview();
    raw.issue_reason = null;
    expect(parseWholeProductQualityPreview(raw).issueReason).toBeNull();
  });

  it("rejects a claimed valuation that omits its book-value evidence", () => {
    const raw = movingAveragePreview();
    raw.total_book_value = null;
    expect(() => parseWholeProductQualityPreview(raw)).toThrow("WHOLE_PRODUCT_QUALITY_PREVIEW_INVALID");
  });

  it("exposes the exact reserved quantity used to explain blocked handling", () => {
    const raw = movingAveragePreview();
    raw.total_reserved_quantity = "100";
    raw.blocker_codes = ["WHOLE_PRODUCT_QUALITY_RESERVED_STOCK"];
    const parsed = parseWholeProductQualityPreview(raw);
    expect(parsed.totalReservedQuantity).toBe("100");
    expect(parsed.blockerCodes).toEqual(["WHOLE_PRODUCT_QUALITY_RESERVED_STOCK"]);
  });

  it("shows the larger package first and keeps loose base units exact", () => {
    expect(formatCommercialQuantity("5110", "كرتونة", "حبة", "50")).toEqual({
      primary: "102 كرتونة + 10 حبة",
      secondary: "5110 حبة",
    });
    expect(formatCommercialQuantity("5500", "كرتونة", "حبة", "50")).toEqual({
      primary: "110 كرتونة",
      secondary: "5500 حبة",
    });
  });
});
